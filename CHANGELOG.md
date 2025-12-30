# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

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
