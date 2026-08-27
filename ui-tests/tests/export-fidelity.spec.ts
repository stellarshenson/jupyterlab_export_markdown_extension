import { expect, test } from '@jupyterlab/galata';
import AdmZip from 'adm-zip';
import { readFileSync } from 'fs';

/**
 * Drives a real Word export through the real UI: a markdown file in the
 * test's own directory, opened in Lab, exported from the File menu, and the
 * downloaded .docx read back. The Python suite covers the same rendering
 * against the handlers directly; this tier is what fails when the command,
 * the menu entry, the download or the packaging is wrong.
 */

const DOC_NAME = 'export-fidelity.md';

/** The second fixture, and the two shapes that reach every format: a table of
 *  contents written two spaces in - what every generator emits - and a
 *  callout the author drew as a bordered `<div>`. */
const STRUCTURE_NAME = 'export-structure.md';

const STRUCTURE = `# Field guide

## Contents

  - [Setup](#setup)
  - [Run it](#run-it)

<div style="border: 2px solid #0284c7; background: #e0f2fe">
<b>Heads up</b> - read this first.
</div>

## Setup

Nothing to do.

## Run it

Run it.
`;

/** Opens \`path\` in Lab, fires the named export, returns the saved download. */
async function exportFromTheMenu(
  page: any,
  path: string,
  name: string,
  entry: string
): Promise<any> {
  await page.evaluate(
    async (target: string) =>
      (window as any).jupyterapp.commands.execute('docmanager:open', {
        path: target
      }),
    path
  );
  await expect(page.activity.getTabLocator(name)).toBeVisible();
  const download = page.waitForEvent('download', { timeout: 120_000 });
  await page.menu.clickMenuItem(`File>Export Markdown As>${entry}`);
  return download;
}

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

test.describe('Structure across all three formats', () => {
  test.beforeEach(async ({ page, tmpPath }) => {
    await page.contents.uploadContent(
      STRUCTURE,
      'text',
      `${tmpPath}/${STRUCTURE_NAME}`
    );
  });

  test('Word gets a real list and a real box', async ({ page, tmpPath }) => {
    const saved = await exportFromTheMenu(
      page,
      `${tmpPath}/${STRUCTURE_NAME}`,
      STRUCTURE_NAME,
      'Microsoft Word (.docx)'
    );
    expect(saved.suggestedFilename()).toBe('export-structure.docx');
    const xml = new AdmZip(await saved.path()).readAsText('word/document.xml');

    // The table of contents is two spaces in, which is the indented-code
    // threshold the converter runs at - it used to arrive as its own source
    // Matched on the list style, not on the text alone: the two headings the
    // entries point at carry the same words
    const entries = paragraphs(xml).filter(
      p => /^(Setup|Run it)$/.test(p.text) && p.xml.includes('ListBullet')
    );
    expect(entries.length, 'the two TOC entries are not two list items').toBe(
      2
    );

    // The `<div>` carries a border and a background, so it is a callout the
    // author drew by hand and exports as the box an alert already gets
    const tables = [...xml.matchAll(/<w:tbl>([\s\S]*?)<\/w:tbl>/g)].map(
      m => m[1]
    );
    const box = tables.filter(t => t.includes('Heads up'));
    expect(box.length, 'the bordered div is not a single-cell table').toBe(1);
    // Both of the div's own declarations survive: its border colour draws the
    // bar, its background fills the cell
    expect(box[0]).toContain('w:color="0284C7"');
    expect(box[0]).toContain('w:fill="E0F2FE"');
  });

  test('HTML gets links, not link source', async ({ page, tmpPath }) => {
    const saved = await exportFromTheMenu(
      page,
      `${tmpPath}/${STRUCTURE_NAME}`,
      STRUCTURE_NAME,
      'HTML'
    );
    expect(saved.suggestedFilename()).toBe('export-structure.html');
    const html = readFileSync(await saved.path(), 'utf-8');

    // The link, not the absence of its source: codehilite tokenises an
    // indented code block into spans, so `](#` is split across element
    // boundaries and a substring test for it cannot fail on the regression
    // it names - in either format
    expect(html).toContain('<a href="#setup">Setup</a>');
    expect(html).toContain('<a href="#run-it">Run it</a>');
    expect(html).toContain('#e0f2fe');
  });

  test('PDF is a PDF', async ({ page, tmpPath }) => {
    // The PDF rebuilds the intermediate DOCX with reportlab, and its content
    // is asserted page-geometry-deep by the Python suite. What only this tier
    // can fail on is the menu entry, the command and the download itself.
    const saved = await exportFromTheMenu(
      page,
      `${tmpPath}/${STRUCTURE_NAME}`,
      STRUCTURE_NAME,
      'PDF'
    );
    expect(saved.suggestedFilename()).toBe('export-structure.pdf');
    const bytes = readFileSync(await saved.path());
    expect(bytes.subarray(0, 5).toString('latin1')).toBe('%PDF-');
    expect(
      bytes.length,
      'the PDF is too small to hold the document'
    ).toBeGreaterThan(2000);
  });
});
