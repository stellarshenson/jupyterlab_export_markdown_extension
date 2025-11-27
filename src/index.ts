import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { showErrorMessage } from '@jupyterlab/apputils';
import { IMainMenu } from '@jupyterlab/mainmenu';
import { Menu } from '@lumino/widgets';
import { requestBlobAPI } from './request';

/**
 * Export format types
 */
type ExportFormat = 'pdf' | 'docx' | 'html';

/**
 * Command IDs for the extension
 */
namespace CommandIDs {
  export const exportPdf = 'export-markdown:pdf';
  export const exportDocx = 'export-markdown:docx';
  export const exportHtml = 'export-markdown:html';
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
  format: ExportFormat
): Promise<void> {
  const blob = await requestBlobAPI(`export/${format}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ path })
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
  requires: [IMainMenu],
  activate: (app: JupyterFrontEnd, mainMenu: IMainMenu) => {
    console.log(
      'JupyterLab extension jupyterlab_export_markdown_extension is activated!'
    );

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
          try {
            await exportMarkdown(path, format);
          } catch (error) {
            console.error(`Failed to export to ${format.toUpperCase()}:`, error);
            showErrorMessage(
              `Export to ${format.toUpperCase()} Failed`,
              error instanceof Error ? error.message : String(error)
            );
          }
        }
      };
    };

    // Register export commands
    commands.addCommand(CommandIDs.exportPdf, {
      label: 'PDF',
      caption: 'Export markdown to PDF',
      isEnabled: isMarkdownOpen,
      execute: createExportExecutor('pdf')
    });

    commands.addCommand(CommandIDs.exportDocx, {
      label: 'Microsoft Word (.docx)',
      caption: 'Export markdown to DOCX',
      isEnabled: isMarkdownOpen,
      execute: createExportExecutor('docx')
    });

    commands.addCommand(CommandIDs.exportHtml, {
      label: 'HTML',
      caption: 'Export markdown to HTML with embedded images',
      isEnabled: isMarkdownOpen,
      execute: createExportExecutor('html')
    });

    // Create the "Export Markdown As" submenu
    const exportMenu = new Menu({ commands });
    exportMenu.title.label = 'Export Markdown As';
    exportMenu.addItem({ command: CommandIDs.exportPdf });
    exportMenu.addItem({ command: CommandIDs.exportDocx });
    exportMenu.addItem({ command: CommandIDs.exportHtml });

    // Add submenu to File menu (rank 5 = near Save/Export section)
    mainMenu.fileMenu.addGroup(
      [{ type: 'submenu', submenu: exportMenu }],
      5
    );

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
