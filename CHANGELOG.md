# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

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
