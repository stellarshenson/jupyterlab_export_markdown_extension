# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

## 1.6.26

### Fixed

- An equation inside a table cell renders as a native Word equation in DOCX instead of a raw `MATH_INLINE_N` marker; the equation pass reached only body paragraphs, so a formula in a cell was left as its placeholder while the same formula in a paragraph rendered
- A display formula written inside a raw HTML table cell beside text keeps that text and the inline formulas next to it; it took the paragraph-clearing path meant for a formula standing alone

## 1.6.25

### Added

- A nested list written with two-space indentation - the GitHub and JupyterLab convention - renders as a list in Word, PDF and HTML instead of an indented code block. The export decides by rendering the document with and without the shift and keeps it only when exactly one block turns from code into a list made of that chunk; an intended code sample, a fence, a raw HTML block, a link reference definition or a table of contents is left as written
- A hand-drawn callout - a `<div>` with a border or background style, the notebook idiom for a note box - draws as a bordered box with a coloured bar in Word and PDF, matching the HTML export. A neutral frame with a coloured left edge keeps the accent colour for the bar; translucent fills are composited onto the page colour
- Every ordered list restarts at 1 in Word and in the PDF. Each list carries its own numbering instance, so a second procedure on the page no longer continues the count of the first, and a step interrupted by a table, a code sample, a quote or a paragraph keeps counting

### Fixed

- A third-level ordered list no longer resets its parent's count in the PDF
- A list holding inline math is rescued in the PDF as it is in Word and HTML; a tag inside an item's text no longer counts as a raw block
- A stray space after the last item no longer leaves the whole list as a code block
- An empty numbered item keeps its number in the PDF
- A link reference definition under an indented item survives the export

## 1.6.24

### Added

- Symbol characters name a font of their own in DOCX instead of being left to Word's substitution. Cambria, the body face, has no glyph for `★`, `☆`, `✓`, `✗`, `☐`, `☒`, the wider arrows or box drawing, and those runs named no font at all - so each reader's Word substituted from its own list and a solid star on one machine was a hollow box on the next. The affected characters are split into their own runs tagged `Segoe UI Symbol`, task-list checkboxes keeping MS Gothic; the surrounding text, Polish diacritics and the arrows Cambria does carry are untouched
- Inline HTML written by hand in a markdown cell now survives the DOCX and PDF export. `<span style="font-weight:bold">`, `font-style`, `text-decoration`, `<mark>`, `<del>`, `<ins>`, `<kbd>`, `<font color>`, an `align=` attribute and a `<div>` were all dropped or merged into whatever paragraph was open; each is now rewritten into markup the converter reads, so a coloured span, a highlight or a centred block renders as written. CSS declarations follow the cascade - the last value for a property wins, as a browser resolves it

### Fixed

- A table cell in the PDF renders the formatting its text carries. Bold, italic, colour and highlighting inside a cell were flattened to plain text, and the column measurement now matches, so a bold word is no longer split across two lines
- A hyperlink label is no longer dropped from a PDF paragraph that carries any formatting, and a highlight around a link no longer prints its internal marker as visible text. Both came from the same place: a paragraph's runs, as the library reports them, never include a run nested inside a link
- A symbol inside italic text stays visible in the PDF. The italic face available on most Linux systems has no star, check mark or ballot box, and the character was painted as a blank space; such a run now renders upright rather than losing the character. The same applies to an italic heading
- An anchor target - an `<a id="...">` written to link to a spot mid-document - no longer fails the whole export with HTTP 500
- A `<div>` inside a blockquote, an alert box, a list item, a heading or a table cell stays inside it instead of ending the block early and continuing as a separate paragraph
- Inline math inside a link label exports instead of failing the request

## 1.6.23

### Fixed

- Exporting a document whose filename is not ASCII no longer fails. A name such as `zniesławienie-milena-kabza-2026.md` returned HTTP 500 from every format, through the JupyterLab UI and the REST endpoints alike: the filename went into the `Content-Disposition` header unencoded, and header values are limited to latin-1, so the export aborted before any of the document was written. The header now follows RFC 6266 - an ASCII name for older clients alongside the real name UTF-8 encoded - so Polish, Czech, Greek, Cyrillic and CJK filenames all download under their own name
- PDF italic headings no longer switch typeface mid-document. Heading 4 and Heading 6 are italic, and the font registration stopped at the first family shipping a regular face, which has no oblique here - both levels fell back to a Helvetica core font while the rest of the ladder stayed on DejaVu. Each weight and slant is now taken from the first family providing it

## 1.6.22

### Added

- Mermaid diagrams now render when a document is exported through the REST endpoints, not only from the JupyterLab UI. A script, `curl`, or a scheduled job previously got the raw ` ```mermaid ` source as a code block, because diagrams are rendered by the browser and posted from the page; the server now renders whatever the frontend did not, using a bundled copy of Mermaid inside the same headless Chromium the SVG rasterizer uses - no network access, no CDN
- An export never fails over a diagram: a diagram that cannot be rendered (no Chromium, a syntax error, an unsupported `layout: elk`) keeps its source and the response carries an `X-Export-Warnings` header - a JSON array of `{code, count, diagrams, message}` where the message is the full remedy (`chromium-unavailable` names the install command). The header is absent when everything rendered and is listed in `Access-Control-Expose-Headers` so a cross-origin caller can read it

### Fixed

- A diagram rendered server-side cannot make the server fetch a URL: Mermaid keeps HTML labels, so a label carrying an `<img src>` used to have the server issue the request - both the render and the rasterize contexts now block all network access for server-generated SVGs
- The server counts exactly the diagrams the browser does, in documents that nest a diagram inside a list item or a blockquote, quote one inside a longer fence, use `~~~` fences, or carry CRLF line endings - a miscount would otherwise pair a picture with the wrong diagram

## 1.6.21

- Fix a GitHub alert with more than one paragraph rendering as two separate boxes - the blank `>` line between paragraphs ended the alert, leaving the rest below it as a plain grey blockquote; the whole alert now stays in one coloured box with its paragraphs intact
- Fix PDF export drawing Heading 4, 5 and 6 identically to Heading 3, so a sub-subsection read as a sibling of its parent - the three levels now carry the same distinct faces the DOCX export gives them
- Fix a long line in a fenced code block running past the right margin in PDF, with the text beyond the page edge not drawn at all - long lines now wrap inside the code block
- Change the `exportFontSize` large option from 14pt to 13pt

## 1.6.20

### Added

- Export font size setting - `small` (10pt), `medium` (12pt, default) or `large` (14pt) sets the base body text size for PDF, DOCX and HTML; headings, tables, code and captions are fixed proportions of it, so the whole document scales together. This also aligns the PDF and DOCX, which previously rendered the same document at 10pt and 11pt respectively

### Fixed

- An explicit `<br>` written at the end of a line no longer loses a break the author asked for: a `<br>` inside a raw HTML block keeps its own breaks, `<BR>` and `<br clear="all">` are recognised, a trailing space or non-breaking space no longer defeats the rule, and `<br>` followed by Markdown's two-space hard break correctly renders both. A `<br>` written inside inline markup (`**Q<br>**`) is still not detected
- A failure of the line-break rule can no longer fail an export - it falls back to the previous behaviour instead of returning an error
- A malformed export font size no longer fails the export; an out-of-range value is clamped to a readable size

## 1.6.19

- Fix a line ended with an explicit `<br>` rendering as two line breaks in DOCX, PDF and HTML - a question written above its answer came out with a blank line between them, so the pair sat further apart than it sat from the next pair and the grouping read backwards; a deliberate `<br><br>` still renders its blank line, and a `<br>` inside a table cell or raw HTML block is unaffected

## 1.6.18

- Fix mermaid diagrams rasterizing mostly as whitespace - the inline `max-width` mermaid stamps on its SVG capped the diagram at its natural size inside a much larger canvas; diagrams now fill their image (97-99% of the width on a reference document, against 43% at worst before)
- Fix an empty header row still being rendered as a blank first row in DOCX, PDF and HTML - a borderless image or layout grid is written in Markdown with an empty header, which Markdown itself renders as nothing, so the row is now dropped rather than merely unstyled
- Fix a table row being torn across a page break when it would fit the next page whole - a caption and its image now stay together, in PDF (conditional intra-row splitting) and in Word (rows marked unbreakable); a row genuinely taller than a page still splits
- Fix a header row holding only pictures being deleted as "empty" in HTML export, losing the images of an image-on-top / caption-below grid that DOCX and PDF kept
- Fix a picture-only first row being banded and repeated as a table header in Word while PDF treated it as ordinary content
- Fix column widths in a headerless grid being skewed by the bold-header width allowance, which no longer applies once there is no header
- Fix a very tall, narrow diagram failing to rasterize and vanishing from the export - it is now scaled down to the renderer's raster limit with its aspect ratio intact

## 1.6.17

- Fix task-list checkboxes exporting as literal `[x]` / `[ ]` text - `- [x]` and `- [ ]` now render as checkbox glyphs (checked and empty) in HTML, DOCX and PDF
- Fix blockquotes losing their indent, left bar and shading in PDF - `>` quotes now render as an indented, left-barred, shaded callout matching the DOCX output
- Fix GitHub alert boxes rendering as a plain table header in PDF - alerts now render as a colored-left-bar shaded callout matching the DOCX output
- Fix mermaid diagrams rasterized inside a view window far larger than the diagram - the diagram is now cropped to its content so it fills the image instead of floating in whitespace
- Fix a borderless image/layout grid (empty header row) stranding a blank header across a page break in DOCX and PDF
- Fix table-cell images being dropped from PDF export - images inside table cells now render, sized to fit their column, including image-only grids where the cell has no caption text

## 1.6.16

- Fix a table header being stranded alone at a page break - a table whose header row would land at the bottom of a page now moves to the next page, and the header repeats on each continuation page, in PDF, DOCX and HTML
- Fix a tall diagram or image overflowing the page height - an image scaled to the page width is now scaled down further to fit the page height, so a tall mermaid diagram fits the page instead of being clipped, in PDF, DOCX and HTML

## 1.6.15

- Fix tables wider than the page running past the right margin in PDF, DOCX and HTML - cells now wrap onto multiple lines within a fitted column layout instead of overflowing, with a horizontal-scroll fallback (kept off when printing) for tables too wide to wrap in HTML

## 1.6.14

- Fix mermaid diagrams exporting as raw code instead of images when the markdown file is open in the source editor without a rendered preview - the exporter now renders mermaid blocks from the document source via the mermaid manager when no rendered diagram is present in the DOM, so DOCX/PDF/HTML exports embed the diagram regardless of whether the preview is open

## 1.6.13

- Rename the extension's entry in the JupyterLab Settings Editor from "Export Markdown Extension" to "Markdown Export Extension"

## 1.6.12

- Drop Python 3.9 support - minimum is now Python 3.10 (`requires-python >=3.10`), matching the PEP 604 `X | None` type-annotation syntax used in the server backend; the CI isolated-install job and README requirements are updated accordingly

## 1.6.11

- Fix server extension failing to load on Python 3.9 - the 1.6.10 hardening used PEP 604 `X | None` type annotations without `from __future__ import annotations`, which Python 3.9 evaluates eagerly and rejects with `unsupported operand type(s) for |`; annotations are now deferred so the extension imports on Python 3.9+ again

## 1.6.10

- Contain local image reads to the Jupyter server root - path-traversal guard (fail-closed) blocks `<img src="../../etc/passwd">` and other escapes outside the workspace
- Guard remote image fetches against SSRF - global-IP allowlist plus a connection-time peer-IP check that defeats DNS rebinding, with per-hop redirect re-validation and proxy-awareness so badges still load behind a proxy
- Harden HTML `<img>` badge sizing - strict numeric parsing, correct handling of width-only badges and `max-height`/`max-width` clamps, attribute tokenizer that ignores values inside `alt`/`data-*`, and a render-width cap
- Anchor image `src` rewriting so `data-src`/`lowsrc`/`xlink:src` are not matched, and make `<img>` tag matching quote-aware to avoid truncation on `>` inside attribute values

## 1.2.0

- Add syntax highlighting for code blocks using Pygments
- HTML export: Add Pygments CSS styles for all token types
- DOCX export: Convert Pygments output to inline colored spans
- PDF export: Render code blocks with Pygments-based colored text using reportlab
- Fix multiline code block preservation in PDF export (was flattening to single line)
- Add syntax highlighting tests to export fidelity test suite

## 1.1.13

- Add comprehensive markdown test file (`doc/comprehensive_test.md`)
- Fix numbered lists rendering as bullet lists in PDF export
- Add nested list indentation support using leftIndent detection from DOCX
- Add level-specific list styles for bullets and numbered lists (level 0 and level 1)
- Add GitHub-style alerts support (NOTE, TIP, IMPORTANT, WARNING, CAUTION)
- Add test image and mermaid diagram sections to comprehensive test

## 1.1.11

- Left-align tables in PDF export instead of centered

## 1.1.10

- Fix tables appearing at end of PDF instead of inline with content
- Add bullet points to list items in PDF export
- Reduce font sizes to match DOCX rendering (body 10pt, headings 11-14pt)

## 1.1.9

- Switch PDF export from weasyprint to reportlab via DOCX intermediate
- Fixes bold text character spacing issue (e.g., dates rendered with spaces between characters)
- Uses DejaVu Sans fonts with proper bold variants for reliable Unicode rendering

## 1.1.7

- Fix URL-encoded image paths not embedding (e.g., `%20` for spaces in Obsidian-style markdown)

## 1.1.6

- Fix CI lint by formatting package-lock.json after jlpm in build workflow

## 1.1.5

- Fix package-lock.json formatting for CI build

## 1.1.4

- Client-side Mermaid diagram capture with calibrated DPI scaling (no server-side mmdc required)
- Configurable diagram DPI via Settings Editor (default 150, range 72-600)
- Smart DOCX image sizing: preserve small images, fit large ones to page dimensions
- Modal dialog spinner during export operations
- Fix "File name too long" error in DOCX export

## 1.0.3

- Add Mermaid diagram rendering to exports via mermaid-cli
- Refine PDF export styling for MS Word compatibility
- Add export commands to command palette under "Export Markdown" category

## 1.0.2

- Add export commands to command palette under "Export Markdown" category
- Dynamic labels: full text in palette, short in menu
- Update README with screenshot and modus primaris documentation style
- Update GitHub workflow with ignore_links for badge URLs

## 0.6.23

- Switch PDF export from xhtml2pdf to weasyprint for proper Unicode and emoji support
- Add Noto Color Emoji font support for PDF rendering
- Create compact PDF stylesheet with tighter spacing

## 0.6.19 (STABLE_BASIC_PDF)

- Switch PDF export from fpdf2 to xhtml2pdf for HTML-to-PDF conversion
- Resolve fpdf2 write_html() incompatibility with complex markdown-generated HTML

## 0.6.17 (STABLE_DOCX)

- Implement pure Python markdown export (no pandoc/LaTeX dependencies)
- Add "Export Markdown As" submenu to File menu with visibility toggle
- PDF export via fpdf2 with DejaVu fonts for Unicode support
- DOCX export via python-docx with htmldocx parser
- HTML export with embedded base64 images
- DOCX formatting: 0.5" margins, banded tables (Light List Accent 1), no first column emphasis
- Menu visibility controlled by shell.currentChanged signal

## 0.1.0

- Initial JupyterLab extension scaffolding
- Frontend (TypeScript) and server (Python) components
- GitHub workflows configured

<!-- <END NEW CHANGELOG ENTRY> -->
