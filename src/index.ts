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

/** One `>` per quote level, so strip while they match. */
function stripQuoteMarkers(line: string): string {
  let out = line;
  for (;;) {
    const next = out.replace(/^[ \t]*>[ ]?/, '');
    if (next === out) {
      return out;
    }
    out = next;
  }
}

/** Expand tabs to the next 4-column stop, as marked measures indentation. */
function expandTabs(line: string): string {
  let out = '';
  for (const ch of line) {
    if (ch === '\t') {
      out += ' '.repeat(4 - (out.length % 4));
    } else {
      out += ch;
    }
  }
  return out;
}

/**
 * The line in the coordinate marked re-lexes it in: blockquote markers removed
 * (with the one column each carries - a tab after `>` counts too) and tabs
 * expanded, so a fence's indent is measured against its container, not the raw
 * start of the line. Returns the blockquote depth and the stripped text.
 */
function quoteStripped(line: string): [number, string] {
  let text = expandTabs(line);
  let q = 0;
  for (;;) {
    const m = /^ {0,3}>[ ]?/.exec(text);
    if (!m) {
      return [q, text];
    }
    q += 1;
    text = text.slice(m[0].length);
  }
}

/**
 * The column a list item's content begins at, or null if the (quote-stripped)
 * text is not a list item. A bare marker or five-plus spaces counts as one -
 * the column a nested fence indents into.
 */
function listContentCol(text: string): number | null {
  const m = /^( {0,3})([-*+]|\d{1,9}[.)])([ \t]*)/.exec(text);
  if (!m) {
    return null;
  }
  const after = m[3].replace(/\r/g, '');
  if (m[0].length !== text.length && !after) {
    return null; // marker jammed against content, e.g. `-->`
  }
  const base = m[1].length + m[2].length;
  const n = after.length;
  if (m[0].length === text.length || n === 0 || n >= 5) {
    return base + 1;
  }
  return base + n;
}

/**
 * Drop the opening fence's indentation from a body line.
 *
 * The indent belongs to the list item holding the block, not to the diagram,
 * and marked hands mermaid the body without it.
 */
function dedentBody(line: string, indent: number): string {
  let cut = 0;
  let col = 0;
  while (cut < line.length && col < indent) {
    if (line[cut] === ' ') {
      col += 1;
    } else if (line[cut] === '\t') {
      col += 4;
    } else {
      break;
    }
    cut += 1;
  }
  return line.slice(cut);
}

/**
 * The mermaid blocks a document means as diagrams.
 *
 * A ```mermaid opened while any other fence is already open is
 * documentation showing the syntax, not a diagram - a fence carrying an info
 * string never closes a block, so a plain ```text quotes it as firmly as a
 * longer fence does. A fence may also sit behind list indentation or a
 * blockquote marker and still be a fence.
 *
 * The server counts them the same way (`iter_mermaid_blocks` in `routes.py`)
 * and pairs what we post here with fences BY POSITION, so counting one block
 * the other skips hands the server a picture addressed to the wrong diagram.
 * Both are measured against marked, which is what JupyterLab renders with and
 * therefore what the preview-capture path counts.
 */
function mermaidBlocksFromSource(source: string): string[] {
  const lines = source.split('\n');
  const blocks: string[] = [];

  let fenceChar: string | null = null;
  let fenceLen = 0;
  let isMermaid = false;
  let isQuoted = false;
  let openQ = 0;
  let listCol = 0;
  let listQ = 0;
  let openSpaces = 0;
  let body: string[] = [];

  const emit = (): void => {
    // openSpaces is already the container-relative column (the quote's own
    // space was stripped when it was measured), so the body is dedented by
    // exactly that after its own quote markers come off.
    const stripped = isQuoted ? body.map(stripQuoteMarkers) : body;
    blocks.push(stripped.map(l => dedentBody(l, openSpaces)).join('\n'));
  };

  for (const rawLine of lines) {
    // JS `.` excludes \r, so a CRLF file would match no fence at all and the
    // fallback would find nothing where it used to find every diagram.
    const line = rawLine.replace(/\r$/, '');
    const [q, text] = quoteStripped(line);
    const spaces = text.length - text.replace(/^ +/, '').length;

    if (fenceChar === null) {
      // Track the innermost open list item's content column, so a fence four
      // spaces PAST it is indented code just as at the top level.
      const col = listContentCol(text);
      if (col !== null) {
        listCol = col;
        listQ = q;
      } else if (text.trim() && (q !== listQ || spaces < listCol)) {
        listCol = 0;
      }
    }

    // Close a quoted block before the fence branch, so a line that both ends
    // the quote and is itself a fence closes the block instead of running on.
    if (fenceChar !== null && isQuoted && q < openQ) {
      if (isMermaid) {
        emit();
      }
      fenceChar = null;
      isMermaid = false;
      isQuoted = false;
    }

    const fence = /^([ \t>]*)(`{3,}|~{3,})(.*)$/.exec(line);
    if (fence === null) {
      if (isMermaid) {
        body.push(line);
      }
      continue;
    }
    const marker = fence[2];
    const info = fence[3].trim();
    if (fenceChar === null) {
      const base = listCol && q === listQ ? listCol : 0;
      if (spaces - base > 3) {
        continue; // indented code, not a fence opener
      }
      fenceChar = marker[0];
      fenceLen = marker.length;
      openSpaces = spaces;
      openQ = q;
      // marked decides what the preview renders, and so what this counts: an
      // exact, case-sensitive info string, with ~~~ treated like ```.
      isMermaid = info === 'mermaid';
      // A blockquote's markers are the quote's syntax, not the diagram's -
      // markdown strips them, and mermaid cannot parse `> flowchart LR`.
      isQuoted = q > 0;
      body = [];
    } else if (
      marker[0] === fenceChar &&
      marker.length >= fenceLen &&
      info === '' &&
      q === openQ &&
      spaces <= openSpaces + 3
    ) {
      // A closer has to live in the opener's container; a quoted or deeply
      // indented ``` inside an open fence is body text.
      if (isMermaid) {
        emit();
      }
      fenceChar = null;
      isMermaid = false;
      isQuoted = false;
    } else if (isMermaid) {
      body.push(line);
    }
  }
  if (isMermaid) {
    // An unclosed fence ends at the end of the document, and marked renders
    // what it opened.
    emit();
  }
  return blocks;
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
  theme: 'light' | 'dark',
  reThemeDom = true
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

  let mermaidIndex = 0;

  // Find all IMG elements with SVG data URIs (JupyterLab's Mermaid rendering).
  // When no markdown is rendered (source editor open, no preview), this yields
  // nothing and the source-based fallback below takes over.
  const imgElements = renderedMarkdown
    ? renderedMarkdown.querySelectorAll('img')
    : [];

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
      if (manager && reThemeDom) {
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
  const svgElements = renderedMarkdown
    ? Array.from(renderedMarkdown.querySelectorAll('svg'))
    : [];
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

  // Preview-independent fallback: when nothing was captured from the rendered
  // DOM (the file is open in the source editor with no rendered markdown view),
  // render the mermaid blocks straight from the document source so they export
  // as images instead of silently falling through as raw ```mermaid code.
  if (diagrams.length === 0 && manager) {
    const source = (currentWidget as any).context?.model?.toString?.() ?? '';
    const blocks = mermaidBlocksFromSource(source);
    let idx = 0;
    for (const inner of blocks) {
      const themed = await renderMermaidInTheme(manager, inner, theme);
      if (themed) {
        diagrams.push({
          index: idx,
          svg: svgToDataUri(themed),
          png: '',
          width: 0,
          height: 0
        });
      }
      idx++;
    }
  }

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
  docxTheme: string = 'light',
  exportFontSize: string = 'medium'
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
      docxTheme,
      exportFontSize
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
    let exportFontSize = 'medium'; // Default: 12pt base body text
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
        exportFontSize = settings.get('exportFontSize').composite as string;
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
          htmlTheme,
          'exportFontSize:',
          exportFontSize
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
          exportFontSize = settings.get('exportFontSize').composite as string;
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
            htmlTheme,
            'exportFontSize:',
            exportFontSize
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
              mermaidManager,
              resolvedDocxTheme,
              format !== 'html'
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
              resolvedDocxTheme,
              exportFontSize
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
