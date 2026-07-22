# Recovery State

## BRACE - 2026-07-22 (Opus usage limit, resets 15:00)

**HORIZON: SESSION-ONLY.** No detached compute exists. Two adversarial-review subagents
(round 6 architect + bug-hunter) were in flight and die with the session - they must be
relaunched, not reattached.

### FIRST ACTION

Read `.claude/round6-architect.md` and `.claude/round6-bug-hunter.md` if the braced agents
managed to write them. If either file is absent, relaunch that reviewer with the round-6
brief (reconstructable from the state below). Triage findings, fix the real ones, then
refresh journal entry 63 via `/journal:update` and commit.

### What is on disk and valid

Working tree, uncommitted, all verified green:

- `jupyterlab_export_markdown_extension/routes.py` - the wide-table fix (+360/-75)
- `jupyterlab_export_markdown_extension/tests/test_export_fidelity.py` - +19 tests
- `pyproject.toml` - `pypdf` added to the test extra
- `.claude/JOURNAL.md` - entry 63, STALE (see pending work)

**Suite: 90 passed.** Nine guards are mutation-proved - each fails when its own fix is
reverted (verified via `/tmp/mutate.py` and `/tmp/mutate2.py`, which do not survive).

Real-document geometry check: PDF text 570.1 / borders 570.0 against a 576pt limit;
widest fitted DOCX grid 10798 of 10800 twips.

### The change, in brief

Tables wider than the page wrap instead of running past the border, in PDF, DOCX and HTML.

- Shared helpers on `ExportHandlerBase`: `fit_column_widths`, `measured_column_widths`,
  `pdf_table_column_layout`; constants `DOCX_CELL_MARGIN_TWIPS`, `PDF_FRAME_PADDING`,
  `PDF_PAGE_MARGIN`
- PDF: `Paragraph` cells, `splitInRow=1`, sized to the frame not the page; padding steps
  6pt then 1pt then 0pt as the fair share narrows
- DOCX: `style_docx_alert_boxes` returns the tables it builds so the caller skips them by
  identity; every content table is styled and, when it overflows, fitted with a
  proportional grid and `autofit = False`
- HTML: `overflow-wrap: anywhere` on cells, a depth-tracking `wrap_html_tables` that wraps
  only outermost tables and tolerates attributes, plus an `@media print` override

### Pending work

1. Round 6 triage (see FIRST ACTION) - rounds 1-5 found and fixed 14 real defects
2. Journal entry 63 is stale: it claims 83 tests and two review rounds; the truth is 90
   tests and six rounds, and it omits the HTML `.table-scroll` wrapper and the print
   override. Must go through `/journal:update`, never a freehand edit, then
   `journal-tools check .claude/JOURNAL.md`
3. Commit - the Star Colonel authorised one commit after a confirming round. Nothing is
   committed yet. No release was requested

### Known and accepted, not defects

- Past roughly 150 columns reportlab paints a wide glyph a point or two past the margin;
  borders stay inside. Documented in `pdf_table_column_layout`
- Pre-existing, left alone deliberately: the dead `markdown_to_html(compact=True)` branch
  and the README line advertising it, the decorative `gridCol w=9360` in alert boxes,
  `max_width = 7 * inch` for PDF images, PDF code blocks that do not wrap

### Scar tissue from this session

An accidental `git checkout` on `test_export_fidelity.py` destroyed all uncommitted test
work. Reconstructing it by replaying transcript edits produced a corrupt file with 24
duplicated blocks. It was rebuilt cleanly from HEAD plus the wide-table blocks and
verified additive: zero HEAD tests lost. Never `git checkout` a file holding uncommitted
work to undo a temporary edit.
