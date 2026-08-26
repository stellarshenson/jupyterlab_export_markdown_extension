import { expect, test } from '@jupyterlab/galata';
import AdmZip from 'adm-zip';

/**
 * Drives a real Word export through the real UI: a markdown file in the
 * test's own directory, opened in Lab, exported from the File menu, and the
 * downloaded .docx read back. The Python suite covers the same rendering
 * against the handlers directly; this tier is what fails when the command,
 * the menu entry, the download or the packaging is wrong.
 */

const DOC_NAME = 'export-fidelity.md';

/** Mirrors the shapes a real document uses - the separator, its colour, and
 *  the inline HTML a markdown or notebook author writes by hand. */
const DOC = `# Export fidelity

Dowod D677 ★ i separator <span style="color:#e8e8e8">·  ·  ·</span> w tekscie.

Weight <span style="font-weight:bold">HEAVY</span>, mark <mark>HIGHLIT</mark>, key <kbd>CTRL</kbd>.

<div align="center">CENTRED</div>

TRAILING
`;

/** Every `<w:r>` in the document body, paired with the text it carries. */
function runs(xml: string): { xml: string; text: string }[] {
  return [...xml.matchAll(/<w:r(?:\s[^>]*)?>([\s\S]*?)<\/w:r>/g)].map(m => ({
    xml: m[1],
    text: [...m[1].matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g)]
      .map(t => t[1])
      .join('')
  }));
}

/** Every `<w:p>` in the document body, paired with the text it carries. */
function paragraphs(xml: string): { xml: string; text: string }[] {
  return [...xml.matchAll(/<w:p(?:\s[^>]*)?>([\s\S]*?)<\/w:p>/g)].map(m => ({
    xml: m[1],
    text: [...m[1].matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g)]
      .map(t => t[1])
      .join('')
  }));
}

/** The one run holding `needle`, or a failure naming what was found instead. */
function runWith(xml: string, needle: string): string {
  const found = runs(xml).filter(r => r.text.includes(needle));
  expect(
    found.length,
    `expected exactly one run holding ${JSON.stringify(needle)}, found ${found.length}`
  ).toBe(1);
  return found[0].xml;
}

test.describe('Word export fidelity', () => {
  test.beforeEach(async ({ page, tmpPath }) => {
    await page.contents.uploadContent(DOC, 'text', `${tmpPath}/${DOC_NAME}`);
  });

  test('exports symbols and inline HTML from the File menu', async ({
    page,
    tmpPath
  }) => {
    // `docmanager:open` is the command the file browser's double-click fires.
    // Driving it directly skips galata's breadcrumb walk, which reads a
    // `data-path` the file browser in this deployment does not write the way
    // it expects - and the document, not the file browser, is under test here.
    await page.evaluate(
      async target =>
        (window as any).jupyterapp.commands.execute('docmanager:open', {
          path: target
        }),
      `${tmpPath}/${DOC_NAME}`
    );
    await expect(page.activity.getTabLocator(DOC_NAME)).toBeVisible();

    // The submenu is hidden until a markdown document is the current widget,
    // so this click also proves the visibility wiring
    const download = page.waitForEvent('download', { timeout: 60_000 });
    await page.menu.clickMenuItem(
      'File>Export Markdown As>Microsoft Word (.docx)'
    );
    const saved = await download;

    expect(saved.suggestedFilename()).toBe('export-fidelity.docx');
    // Playwright already holds the download in a temp file it cleans up
    const file = await saved.path();
    const xml = new AdmZip(file).readAsText('word/document.xml');
    expect(xml.length, 'word/document.xml is empty').toBeGreaterThan(0);

    // A glyph Cambria has no shape for names a font that does, and one it can
    // draw keeps the body face - a symbol font on `·` would switch typeface
    // mid-sentence for nothing
    expect(runWith(xml, '★')).toContain('w:ascii="Segoe UI Symbol"');
    expect(runWith(xml, '·')).not.toContain('Segoe UI Symbol');

    // Inline HTML htmldocx has no handler for, rewritten before conversion
    expect(runWith(xml, '·')).toContain('w:val="E8E8E8"');
    expect(runWith(xml, 'HEAVY')).toContain('<w:b/>');
    expect(runWith(xml, 'HIGHLIT')).toContain('w:fill="FFFF00"');
    expect(runWith(xml, 'CTRL')).toContain('w:ascii="Courier"');

    // A <div> has no handler either, so its text used to join whatever
    // paragraph was already open
    const centred = paragraphs(xml).filter(p => p.text.includes('CENTRED'));
    expect(centred.length, 'the <div> text is not its own paragraph').toBe(1);
    expect(centred[0].xml).toContain('w:val="center"');
    expect(centred[0].text).not.toContain('TRAILING');
  });
});
