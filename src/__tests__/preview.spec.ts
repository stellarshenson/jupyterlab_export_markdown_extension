import { diagramTheme, renderedMarkdownFor } from '../preview';

function widget(path: string, rendered: boolean) {
  const node = document.createElement('div');
  if (rendered) {
    node.innerHTML = `<div class="jp-RenderedMarkdown" data-of="${path}"></div>`;
  }
  return { node, context: { path } };
}

describe('diagramTheme', () => {
  it('follows htmlTheme for HTML and the DOCX theme otherwise', () => {
    expect(diagramTheme('html', 'dark', 'light')).toBe('dark');
    expect(diagramTheme('html', 'light', 'dark')).toBe('light');
    expect(diagramTheme('html', 'system', 'dark')).toBe('light');
    expect(diagramTheme('docx', 'dark', 'light')).toBe('light');
    expect(diagramTheme('pdf', 'light', 'dark')).toBe('dark');
  });
});

describe('renderedMarkdownFor', () => {
  it('takes the preview of the same file, never another document', () => {
    const editor = widget('a.md', false);
    const other = widget('b.md', true);
    const preview = widget('a.md', true);
    const found = renderedMarkdownFor(editor, [other, editor, preview]);
    expect(found?.getAttribute('data-of')).toBe('a.md');
    expect(found?.parentElement).toBe(preview.node);
  });

  it('answers null when only another document is rendered', () => {
    const editor = widget('a.md', false);
    expect(renderedMarkdownFor(editor, [widget('b.md', true), editor])).toBe(
      null
    );
  });

  it('prefers the rendered markdown inside the widget itself', () => {
    const own = widget('a.md', true);
    expect(
      renderedMarkdownFor(own, [widget('a.md', true)])?.parentElement
    ).toBe(own.node);
  });
});
