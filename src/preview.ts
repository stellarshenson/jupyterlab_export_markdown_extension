/**
 * Which rendered markdown, and which diagram theme, an export reads.
 */

/** What this module needs of a widget: its DOM node and its document path. */
interface IDocumentLike {
  node: Element;
  context?: { path?: string };
}

/**
 * The theme the mermaid diagrams of an export are drawn in.
 *
 * `htmlTheme` governs an HTML export and `docxTheme` DOCX and PDF, as the
 * settings say and as the server renders a diagram it draws itself. 'system'
 * has no diagram of its own and draws light, as it does on the server.
 */
export function diagramTheme(
  format: string,
  htmlTheme: string,
  docxTheme: 'light' | 'dark'
): 'light' | 'dark' {
  if (format !== 'html') {
    return docxTheme;
  }
  return htmlTheme === 'dark' ? 'dark' : 'light';
}

/**
 * The rendered markdown of the document in `current`: inside the widget, or
 * in a preview of the SAME file open in another panel. Rendered markdown of
 * any other document - a second preview, a notebook cell - is not this
 * document's, and its diagrams must not be posted as this document's.
 */
export function renderedMarkdownFor(
  current: IDocumentLike,
  widgets: Iterable<IDocumentLike>
): Element | null {
  const selector = '.jp-RenderedMarkdown';
  const own = current.node.querySelector(selector);
  const path = current.context?.path;
  if (own || !path) {
    return own;
  }
  for (const widget of widgets) {
    if (widget !== current && widget.context?.path === path) {
      const rendered = widget.node.querySelector(selector);
      if (rendered) {
        return rendered;
      }
    }
  }
  return null;
}
