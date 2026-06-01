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
import { IMermaidManager } from '@jupyterlab/mermaid';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { Menu, Widget } from '@lumino/widgets';
import { requestBlobAPI } from './request';

/**
 * Resolve the configured DOCX/PDF theme ('light' | 'dark' | 'auto') to a
 * concrete 'light' or 'dark'. 'auto' follows the current JupyterLab UI
 * theme via the `data-jp-theme-light` body attribute.
 */
function resolveDocxTheme(setting: string): 'light' | 'dark' {
  if (setting === 'dark') {
    return 'dark';
  }
  if (setting === 'light') {
    return 'light';
  }
  // 'auto' - follow the JupyterLab UI theme
  const isLight = document.body.dataset.jpThemeLight !== 'false';
  return isLight ? 'light' : 'dark';
}

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

  // Launch dialog but ignore the promise - we'll dispose it manually
  // The promise rejects with undefined when disposed, which is expected
  dialog.launch().catch(() => {
    // Ignore - dialog was disposed programmatically
  });
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
 * Encode an SVG string as a base64 data URI.
 */
function svgToDataUri(svgString: string): string {
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svgString)))}`;
}

/**
 * Re-render a mermaid source string to an SVG in the requested theme.
 *
 * The mermaid figure JupyterLab renders is themed to the live UI, which is
 * wrong for a printed Word document (dark UI -> light edges, invisible on
 * white paper). Re-rendering the source with `theme: 'default'` / 'dark'
 * gives a diagram matching the chosen export theme. Returns null on any
 * failure so the caller can fall back to the already-rendered SVG.
 */
async function renderMermaidInTheme(
  manager: IMermaidManager,
  source: string,
  theme: 'light' | 'dark'
): Promise<string | null> {
  try {
    const mermaid = await manager.getMermaid();
    // initialize() is global config; JupyterLab re-applies its own theme on
    // its next render, so forcing it here only affects this export pass.
    mermaid.initialize({
      startOnLoad: false,
      theme: theme === 'dark' ? 'dark' : 'default',
      securityLevel: 'loose'
    });
    const id = `jp-export-mmd-${Math.floor(performance.now())}`;
    const { svg } = await mermaid.render(id, source);
    return svg;
  } catch (error) {
    console.warn('Export Markdown: mermaid re-render failed:', error);
    return null;
  }
}

/**
 * Recover the mermaid source for a rendered diagram. JupyterLab places the
 * original source in a <pre><code> sibling of the <img> inside the <figure>.
 */
function findMermaidSource(img: HTMLImageElement): string | null {
  const figure = img.closest('figure');
  const code = figure?.querySelector('pre code, code');
  const text = code?.textContent?.trim();
  return text || null;
}

/**
 * Capture rendered Mermaid diagrams from the current markdown preview.
 *
 * Each diagram is re-rendered in the requested export theme (when the
 * mermaid manager is available and the source is recoverable); otherwise
 * the already-rendered SVG is used as-is. The server rasterizes the SVG to
 * PNG via Playwright at the configured svgPixelWidth.
 */
async function captureMermaidDiagrams(
  shell: JupyterFrontEnd.IShell,
  manager: IMermaidManager | null,
  theme: 'light' | 'dark'
): Promise<IMermaidDiagram[]> {
  const diagrams: IMermaidDiagram[] = [];
  const currentWidget = shell.currentWidget;

  if (!currentWidget) {
    return diagrams;
  }

  // Find rendered markdown content - first try within the widget, then search entire document
  // This handles cases where preview is in a separate panel from the editor
  const widgetNode = currentWidget.node;
  let renderedMarkdown = widgetNode.querySelector('.jp-RenderedMarkdown');

  // If not found in current widget, search entire document for rendered markdown
  if (!renderedMarkdown) {
    renderedMarkdown = document.querySelector('.jp-RenderedMarkdown');
  }

  if (!renderedMarkdown) {
    return diagrams;
  }

  let mermaidIndex = 0;

  // Find all IMG elements with SVG data URIs (JupyterLab's Mermaid rendering)
  const imgElements = renderedMarkdown.querySelectorAll('img');

  for (const img of Array.from(imgElements)) {
    const src = img.getAttribute('src') || '';

    // Check if this is an SVG data URI
    if (src.startsWith('data:image/svg+xml')) {
      // Filter out small SVG icons (like GitHub alert icons) by checking dimensions
      // Mermaid diagrams are typically > 100px, while icons are 16-32px
      const width = img.naturalWidth || img.width || 0;
      const height = img.naturalHeight || img.height || 0;

      // Skip small images (icons) - mermaid diagrams are always larger
      if (width < 50 && height < 50) {
        continue;
      }

      let svgData: string | null = null;

      // Prefer re-rendering the source in the chosen export theme
      if (manager) {
        const source = findMermaidSource(img);
        if (source) {
          const themed = await renderMermaidInTheme(manager, source, theme);
          if (themed) {
            svgData = svgToDataUri(themed);
          }
        }
      }

      // Fallback: use the already-rendered SVG as-is
      if (!svgData) {
        if (src.startsWith('data:image/svg+xml,')) {
          // URL-encoded SVG - convert to base64 for consistency
          const svgContent = decodeURIComponent(
            src.replace('data:image/svg+xml,', '')
          );
          svgData = svgToDataUri(svgContent);
        } else {
          svgData = src;
        }
      }

      // Hand the SVG to the server; it rasterizes via Playwright at svgPixelWidth
      diagrams.push({
        index: mermaidIndex,
        svg: svgData,
        png: '',
        width,
        height
      });
      mermaidIndex++;
    }
  }

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
      const svgData = svgToDataUri(svgString);

      diagrams.push({
        index: mermaidIndex,
        svg: svgData,
        png: '',
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
  mermaidDiagrams: IMermaidDiagram[],
  svgPixelWidth: number = 1920,
  mathPixelWidth: number = 800,
  showAlertLabels: boolean = false,
  htmlTheme: string = 'light',
  htmlDarkBackground: string = '#111111',
  htmlLightBackground: string = '#ffffff',
  docxTheme: string = 'light'
): Promise<void> {
  const blob = await requestBlobAPI(`export/${format}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      path,
      mermaidDiagrams,
      svgPixelWidth,
      mathPixelWidth,
      showAlertLabels,
      htmlTheme,
      htmlDarkBackground,
      htmlLightBackground,
      docxTheme
    })
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
  optional: [ISettingRegistry, IMermaidManager],
  activate: async (
    app: JupyterFrontEnd,
    mainMenu: IMainMenu,
    palette: ICommandPalette,
    settingRegistry: ISettingRegistry | null,
    mermaidManager: IMermaidManager | null
  ) => {
    console.log(
      'JupyterLab extension jupyterlab_export_markdown_extension is activated!'
    );

    // Load settings
    let svgPixelWidth = 1920; // Default: server-side SVG/Mermaid to PNG target pixel width (Full HD)
    let mathPixelWidth = 800; // Default: PDF math expression image target pixel width
    let showAlertLabels = false; // Default: hide alert type labels
    let docxTheme = 'light'; // Default: light - Word docs are usually printed
    let htmlTheme = 'light'; // Default: light theme
    let htmlDarkBackground = '#111111'; // Default: JupyterLab dark theme darkest gray
    let htmlLightBackground = '#ffffff'; // Default: light theme background
    if (settingRegistry) {
      try {
        const settings = await settingRegistry.load(plugin.id);
        svgPixelWidth = settings.get('svgPixelWidth').composite as number;
        mathPixelWidth = settings.get('mathPixelWidth').composite as number;
        showAlertLabels = settings.get('showAlertLabels').composite as boolean;
        docxTheme = settings.get('docxTheme').composite as string;
        htmlTheme = settings.get('htmlTheme').composite as string;
        htmlDarkBackground = settings.get('htmlDarkBackground')
          .composite as string;
        htmlLightBackground = settings.get('htmlLightBackground')
          .composite as string;
        console.log(
          'Export Markdown: Loaded settings - svgPixelWidth:',
          svgPixelWidth,
          'mathPixelWidth:',
          mathPixelWidth,
          'showAlertLabels:',
          showAlertLabels,
          'docxTheme:',
          docxTheme,
          'htmlTheme:',
          htmlTheme
        );

        // Listen for settings changes
        settings.changed.connect(() => {
          svgPixelWidth = settings.get('svgPixelWidth').composite as number;
          mathPixelWidth = settings.get('mathPixelWidth').composite as number;
          showAlertLabels = settings.get('showAlertLabels')
            .composite as boolean;
          docxTheme = settings.get('docxTheme').composite as string;
          htmlTheme = settings.get('htmlTheme').composite as string;
          htmlDarkBackground = settings.get('htmlDarkBackground')
            .composite as string;
          htmlLightBackground = settings.get('htmlLightBackground')
            .composite as string;
          console.log(
            'Export Markdown: Settings changed - svgPixelWidth:',
            svgPixelWidth,
            'mathPixelWidth:',
            mathPixelWidth,
            'showAlertLabels:',
            showAlertLabels,
            'docxTheme:',
            docxTheme,
            'htmlTheme:',
            htmlTheme
          );
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
            // Resolve the DOCX/PDF theme and re-render mermaid to match it
            const resolvedDocxTheme = resolveDocxTheme(docxTheme);
            const mermaidDiagrams = await captureMermaidDiagrams(
              shell,
              format === 'html' ? null : mermaidManager,
              resolvedDocxTheme
            );
            await exportMarkdown(
              path,
              format,
              mermaidDiagrams,
              svgPixelWidth,
              mathPixelWidth,
              showAlertLabels,
              htmlTheme,
              htmlDarkBackground,
              htmlLightBackground,
              resolvedDocxTheme
            );
          } catch (error) {
            console.error(
              `Failed to export to ${format.toUpperCase()}:`,
              error
            );
            const errorCode = (error as any)?.errorCode;
            if (errorCode === 'CHROMIUM_UNAVAILABLE') {
              showErrorMessage(
                'Chromium runtime required',
                'Server-side SVG rendering needs Playwright Chromium, which is not installed or cannot launch on the server.\n\n' +
                  'Run this once on the server:\n\n' +
                  '    jupyterlab-export-markdown-extension install\n\n' +
                  'Then retry the export.'
              );
            } else {
              showErrorMessage(
                `Export to ${format.toUpperCase()} Failed`,
                error instanceof Error ? error.message : String(error)
              );
            }
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
