import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import {
  Dialog,
  ICommandPalette,
  showErrorMessage
} from '@jupyterlab/apputils';
import { IMainMenu } from '@jupyterlab/mainmenu';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { Menu, Widget } from '@lumino/widgets';
import { requestBlobAPI } from './request';

/**
 * Export format types
 */
type ExportFormat = 'pdf' | 'docx' | 'html';

/**
 * Mermaid diagram data captured from rendered markdown
 */
interface IMermaidDiagram {
  index: number;
  svg: string;
  png: string;
  width: number;
  height: number;
}

/**
 * Result of PNG conversion with dimensions
 */
interface IPngResult {
  dataUri: string;
  width: number;
  height: number;
}

/**
 * Convert an already-rendered IMG element directly to PNG data URI using Canvas.
 * This preserves fonts because the browser has already rendered the SVG with fonts loaded.
 * Uses calibrated DPI scaling matching jupyterlab_mmd_to_png_extension.
 */
function imgElementToPng(
  imgElement: HTMLImageElement,
  targetDPI: number = 300
): IPngResult {
  // Use natural dimensions (actual image size)
  const width = imgElement.naturalWidth || imgElement.width || 800;
  const height = imgElement.naturalHeight || imgElement.height || 600;

  // SVG native resolution calibrated to match Adobe converter output
  // Same formula as jupyterlab_mmd_to_png_extension
  const sourceDPI = 11.5;
  const scale = targetDPI / sourceDPI;

  const canvas = document.createElement('canvas');
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);

  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) {
    throw new Error('Failed to get canvas context');
  }

  // High quality rendering
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';

  // Draw the already-rendered image directly at scaled dimensions (preserves fonts)
  ctx.drawImage(imgElement, 0, 0, canvas.width, canvas.height);

  // Convert to PNG data URI
  return {
    dataUri: canvas.toDataURL('image/png'),
    width: canvas.width,
    height: canvas.height
  };
}

/**
 * Command IDs for the extension
 */
namespace CommandIDs {
  export const exportPdf = 'export-markdown:pdf';
  export const exportDocx = 'export-markdown:docx';
  export const exportHtml = 'export-markdown:html';
}

/**
 * Show loading dialog with spinner for export operations
 */
function showExportingDialog(format: string): Dialog<unknown> {
  const content = document.createElement('div');
  content.style.display = 'flex';
  content.style.alignItems = 'center';
  content.style.gap = '12px';
  content.style.padding = '8px 0';
  content.innerHTML = `
    <div style="
      width: 24px;
      height: 24px;
      border: 3px solid var(--jp-border-color2);
      border-top-color: var(--jp-brand-color1);
      border-radius: 50%;
      animation: jp-export-spin 1s linear infinite;
    "></div>
    <span>Exporting to ${format.toUpperCase()}...</span>
    <style>
      @keyframes jp-export-spin {
        to { transform: rotate(360deg); }
      }
    </style>
  `;

  const body = new Widget({ node: content });

  const dialog = new Dialog({
    title: 'Exporting',
    body,
    buttons: []
  });

  dialog.launch();
  return dialog;
}

/**
 * File extensions for each export format
 */
const FORMAT_EXTENSIONS: Record<ExportFormat, string> = {
  pdf: 'pdf',
  docx: 'docx',
  html: 'html'
};

/**
 * MIME types for each export format
 */
const FORMAT_MIME_TYPES: Record<ExportFormat, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  html: 'text/html'
};

/**
 * Capture rendered Mermaid diagrams from the current markdown preview
 * and convert them to PNG format using Canvas (preserves fonts).
 */
function captureMermaidDiagrams(
  shell: JupyterFrontEnd.IShell,
  targetDPI: number = 300
): IMermaidDiagram[] {
  const diagrams: IMermaidDiagram[] = [];
  const currentWidget = shell.currentWidget;

  if (!currentWidget) {
    return diagrams;
  }

  // Find rendered markdown content within the widget
  const widgetNode = currentWidget.node;
  const renderedMarkdown = widgetNode.querySelector('.jp-RenderedMarkdown');

  if (!renderedMarkdown) {
    return diagrams;
  }

  let mermaidIndex = 0;

  // Find all IMG elements with SVG data URIs (JupyterLab's Mermaid rendering)
  const imgElements = renderedMarkdown.querySelectorAll('img');

  imgElements.forEach(img => {
    const src = img.getAttribute('src') || '';

    // Check if this is a Mermaid diagram (SVG data URI)
    if (src.startsWith('data:image/svg+xml')) {
      // Extract base64 or URL-encoded SVG data for SVG fallback
      let svgData = src;

      if (src.startsWith('data:image/svg+xml,')) {
        // URL-encoded SVG - convert to base64 for consistency
        const encodedSvg = src.replace('data:image/svg+xml,', '');
        const decodedSvg = decodeURIComponent(encodedSvg);
        const base64Svg = btoa(unescape(encodeURIComponent(decodedSvg)));
        svgData = `data:image/svg+xml;base64,${base64Svg}`;
      }

      // Convert the already-rendered IMG element directly to PNG
      // This preserves fonts because the browser has already rendered them
      let pngResult: IPngResult = { dataUri: '', width: 0, height: 0 };
      try {
        pngResult = imgElementToPng(img, targetDPI);
      } catch (error) {
        console.warn(
          `Failed to convert Mermaid diagram ${mermaidIndex} to PNG:`,
          error
        );
      }

      diagrams.push({
        index: mermaidIndex,
        svg: svgData,
        png: pngResult.dataUri,
        width: pngResult.width,
        height: pngResult.height
      });
      mermaidIndex++;
    }
  });

  // Also check for inline SVG elements (alternative Mermaid rendering)
  const svgElements = renderedMarkdown.querySelectorAll('svg');
  svgElements.forEach(svg => {
    // Check if it's a Mermaid diagram
    const isMermaid =
      svg.id?.includes('mermaid') ||
      svg.getAttribute('aria-roledescription') === 'mermaid' ||
      svg.classList.contains('mermaid');

    if (isMermaid) {
      const serializer = new XMLSerializer();
      const svgString = serializer.serializeToString(svg);
      const base64Svg = btoa(unescape(encodeURIComponent(svgString)));
      const svgData = `data:image/svg+xml;base64,${base64Svg}`;

      // For inline SVG, we return the SVG data URI (PNG conversion is more complex)
      // The backend will handle conversion if needed
      diagrams.push({
        index: mermaidIndex,
        svg: svgData,
        png: '', // Backend will convert using cairosvg if available
        width: 0,
        height: 0
      });
      mermaidIndex++;
    }
  });

  return diagrams;
}

/**
 * Download a file from a blob response
 */
function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

/**
 * Get output filename from input path and format
 */
function getOutputFilename(path: string, format: ExportFormat): string {
  const baseName = path.split('/').pop()?.replace(/\.md$/i, '') || 'document';
  return `${baseName}.${FORMAT_EXTENSIONS[format]}`;
}

/**
 * Export a markdown file to the specified format
 */
async function exportMarkdown(
  path: string,
  format: ExportFormat,
  mermaidDiagrams: IMermaidDiagram[]
): Promise<void> {
  const blob = await requestBlobAPI(`export/${format}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ path, mermaidDiagrams })
  });

  // Ensure correct MIME type
  const typedBlob = new Blob([blob], { type: FORMAT_MIME_TYPES[format] });
  const filename = getOutputFilename(path, format);
  downloadBlob(typedBlob, filename);
}

/**
 * Initialization data for the jupyterlab_export_markdown_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_export_markdown_extension:plugin',
  description:
    'JupyterLab extension to export markdown files as PDF, DOCX and HTML with embedded images',
  autoStart: true,
  requires: [IMainMenu, ICommandPalette],
  optional: [ISettingRegistry],
  activate: async (
    app: JupyterFrontEnd,
    mainMenu: IMainMenu,
    palette: ICommandPalette,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log(
      'JupyterLab extension jupyterlab_export_markdown_extension is activated!'
    );

    // Load settings
    let diagramDPI = 150; // Default value
    if (settingRegistry) {
      try {
        const settings = await settingRegistry.load(plugin.id);
        diagramDPI = settings.get('diagramDPI').composite as number;
        console.log(
          'Export Markdown: Loaded diagram DPI from settings:',
          diagramDPI
        );

        // Listen for settings changes
        settings.changed.connect(() => {
          diagramDPI = settings.get('diagramDPI').composite as number;
          console.log('Export Markdown: Diagram DPI changed to:', diagramDPI);
        });
      } catch (error) {
        console.error('Export Markdown: Failed to load settings:', error);
      }
    }

    const { commands, shell } = app;

    /**
     * Get the path of the currently opened markdown file
     */
    const getCurrentMarkdownPath = (): string | null => {
      const currentWidget = shell.currentWidget;
      if (!currentWidget) {
        return null;
      }

      // Check if widget has a context with a path (DocumentWidget pattern)
      const context = (currentWidget as any).context;
      if (context?.path) {
        const path = context.path as string;
        if (path.toLowerCase().endsWith('.md')) {
          return path;
        }
      }

      return null;
    };

    /**
     * Check if a markdown file is currently open
     */
    const isMarkdownOpen = (): boolean => {
      return getCurrentMarkdownPath() !== null;
    };

    /**
     * Create an export command executor
     */
    const createExportExecutor = (format: ExportFormat) => {
      return async () => {
        const path = getCurrentMarkdownPath();
        if (path) {
          const dialog = showExportingDialog(format);

          try {
            // Capture rendered Mermaid diagrams from the preview (includes PNG conversion at configured DPI)
            const mermaidDiagrams = captureMermaidDiagrams(shell, diagramDPI);
            await exportMarkdown(path, format, mermaidDiagrams);
          } catch (error) {
            console.error(
              `Failed to export to ${format.toUpperCase()}:`,
              error
            );
            showErrorMessage(
              `Export to ${format.toUpperCase()} Failed`,
              error instanceof Error ? error.message : String(error)
            );
          } finally {
            dialog.dispose();
          }
        }
      };
    };

    // Register export commands
    commands.addCommand(CommandIDs.exportPdf, {
      label: args => (args.isPalette ? 'Export Markdown to PDF' : 'PDF'),
      caption: 'Export markdown to PDF',
      isEnabled: isMarkdownOpen,
      execute: createExportExecutor('pdf')
    });

    commands.addCommand(CommandIDs.exportDocx, {
      label: args =>
        args.isPalette
          ? 'Export Markdown to Word (.docx)'
          : 'Microsoft Word (.docx)',
      caption: 'Export markdown to DOCX',
      isEnabled: isMarkdownOpen,
      execute: createExportExecutor('docx')
    });

    commands.addCommand(CommandIDs.exportHtml, {
      label: args => (args.isPalette ? 'Export Markdown to HTML' : 'HTML'),
      caption: 'Export markdown to HTML with embedded images',
      isEnabled: isMarkdownOpen,
      execute: createExportExecutor('html')
    });

    // Add commands to command palette
    const category = 'Export Markdown';
    palette.addItem({
      command: CommandIDs.exportPdf,
      category,
      args: { isPalette: true }
    });
    palette.addItem({
      command: CommandIDs.exportDocx,
      category,
      args: { isPalette: true }
    });
    palette.addItem({
      command: CommandIDs.exportHtml,
      category,
      args: { isPalette: true }
    });

    // Create the "Export Markdown As" submenu
    const exportMenu = new Menu({ commands });
    exportMenu.title.label = 'Export Markdown As';
    exportMenu.addItem({ command: CommandIDs.exportPdf });
    exportMenu.addItem({ command: CommandIDs.exportDocx });
    exportMenu.addItem({ command: CommandIDs.exportHtml });

    // Add submenu to File menu (rank 5 = near Save/Export section)
    mainMenu.fileMenu.addGroup([{ type: 'submenu', submenu: exportMenu }], 5);

    // Update submenu visibility when current widget changes
    const updateMenuVisibility = () => {
      const visible = isMarkdownOpen();
      exportMenu.title.className = visible ? '' : 'lm-mod-hidden';
    };

    // Connect to shell's currentChanged signal
    if (shell.currentChanged) {
      shell.currentChanged.connect(updateMenuVisibility);
    }

    // Initial visibility check
    updateMenuVisibility();
  }
};

export default plugin;
