# Acceptance Criteria - jupyterlab_export_markdown_extension

Acceptance criteria for the markdown export extension across PDF, DOCX and HTML. One `##` section per feature; append new features as new sections.

## Contents

- [Export page fitting](#export-page-fitting)

## Export page fitting

Exported content must stay inside the printable page - a table must not strand its header row at a page break, and a diagram must fit both page width and page height. PDF lays out manually with reportlab, DOCX relies on Word's pagination, HTML relies on the print stylesheet.

| Behaviour                               | PDF                  | DOCX                 | HTML                      |
| --------------------------------------- | -------------------- | -------------------- | ------------------------- |
| Orphan header deferred to next page     | `repeatRows` defers  | header repeat + keep | `@media print` break      |
| Header repeated on continuation pages   | `repeatRows`         | `w:tblHeader`        | `thead` native            |
| Image scaled to page width              | existing             | existing             | `max-width:100%` existing |
| Image scaled down further when too tall | scale to page height | existing             | `@media print` max-height |

### Orphan header pagination

- [x] **PDF: no header-only page bottom** - a content table whose header row would sit at a page bottom with no body row after it on that page is moved whole to the next page
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 implemented via `repeatRows=1` on the reportlab Table, which defers the whole table rather than splitting off a header-only piece (v1.6.16)
- [x] **PDF: header repeats on split** - a table taller than one page repeats its header row at the top of each continuation page
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 implemented; tested a 80-row table repeats its header on >= 2 pages (v1.6.16)
- [x] **DOCX: header repeat, no orphan** - the header row carries `w:tblHeader` so Word repeats it per page and does not strand it alone at a page bottom
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 implemented in `style_docx_table`, gated on a table having a body row (v1.6.16)
- [x] **HTML: print keeps header with a row** - the print stylesheet forbids a page break between the header and the first body row (`thead` break-inside and break-after avoid, `tr` break-inside avoid)
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 implemented in the `@media print` block; tested via computed style (v1.6.16)
- [x] **Edge: table taller than a full page** - splitting is still allowed; the guard only defers a header stranded with zero body rows, never a table that genuinely cannot fit one page
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 held - `splitInRow=1` still carries a page-tall row; multi-page table test passes (v1.6.16)
- [x] **Edge: header-only table** - a table with a header and no body rows exports without error and is not deferred forever
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 verified - header-only table exports in all three formats; DOCX header marking gated on a body row (v1.6.16)
- [x] **Edge: single-cell alert table** - the orphan guard does not touch the decorative single-cell alert-box tables
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 held - alert tables are excluded from `style_docx_table` by identity; a single-cell table has no header-plus-body to orphan (v1.6.16)

### Diagram and image page fit

- [x] **PDF: image fits page height** - an image scaled to page width is scaled down further, aspect preserved, when that width leaves it taller than the printable page height
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 implemented in `process_image` (frame width then frame height); replaced the stray `7*inch` width; tested a 300x3000 image fits (v1.6.16)
- [x] **DOCX: image fits page height** - an image wider or taller than the page is scaled down to fit both, aspect preserved (existing behaviour, held by test)
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 existing behaviour now covered by a regression test (v1.6.16)
- [x] **HTML: print caps image height** - the print stylesheet bounds image height to about one printed page so a tall diagram fits a page rather than spilling across several; width stays `max-width:100%`
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 implemented as `@media print img { max-height: 9in }` - `100vh` and `width:auto` proved unreliable in Chromium print (2-3 pages); tested by rendering the print PDF and asserting one page (v1.6.16)
- [x] **Mermaid: width from setting, height from page** - a mermaid diagram keeps its configured export width unless the page height forces a smaller uniform scale
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 held - mermaid renders to an image that flows through the same width-then-height fit as any image (v1.6.16)
- [x] **Edge: image already within the page** - an image that fits both dimensions is left untouched, never upscaled
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 held - all scaling is gated on the image exceeding a dimension, so a fitting image is untouched (v1.6.16)
- [x] **Edge: image in a table cell** - a table-cell image scales to its cell width, not the page width (existing behaviour, unaffected)
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 held - table-cell path unchanged, covered by the existing image-scaling tests (v1.6.16)
- [x] **Edge: degenerate scale** - a scale that would round a dimension to zero does not erase the image
  - log: 2026-07-22 criterion added
  - log: 2026-07-22 held - DOCX floors EMU with `max(1, ...)`; PDF clamps directly to the frame dimensions in float, which never reaches zero for a real image (v1.6.16)
