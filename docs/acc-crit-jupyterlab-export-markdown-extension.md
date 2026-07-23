# Acceptance Criteria - jupyterlab_export_markdown_extension

Acceptance criteria for the markdown export extension across PDF, DOCX and HTML. One `##` section per feature; append new features as new sections.

## Contents

- [Export page fitting](#export-page-fitting)
- [Blank grid header](#blank-grid-header)
- [Row and callout page splitting](#row-and-callout-page-splitting)
- [Mermaid raster framing](#mermaid-raster-framing)

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

## Blank grid header

Markdown has no table syntax without a header row, so a borderless image or layout grid is written with an empty one (`|  |  |  |`). Markdown renders nothing for that row, and the exports must agree - the row is removed, not merely stripped of header styling. The rule is structural, so a row that carries pictures but no text is content and is kept.

| Scenario                       | Markdown         | PDF         | DOCX        | HTML            |
| ------------------------------ | ---------------- | ----------- | ----------- | --------------- |
| Header with text               | header row       | header row  | header row  | `thead`         |
| Header blank, body rows follow | nothing rendered | row dropped | row dropped | `thead` dropped |
| Header blank with pictures     | pictures shown   | row kept    | row kept    | row kept        |
| Header blank, no body rows     | nothing rendered | row dropped | row dropped | `thead` dropped |

A header-only markdown table is not the fourth case: python-markdown synthesises an empty `<tbody>` row for it, so a body row always survives the delete. The single-row guard on all three paths only fires for a raw HTML table written by hand.

- [x] **All formats: blank header row removed** - a first row with no text and no embedded content is deleted from the exported table, not just unstyled
  - log: 2026-07-23 criterion added after `DEF-8` ("ms word and pdf render header row - while if empty in markdown it is never rendered")
  - log: 2026-07-23 implemented in `style_docx_table` (DOCX), `process_table` (PDF) and `drop_empty_table_headers` (HTML); tests `test_docx_empty_header_row_is_dropped`, `test_html_empty_header_row_is_dropped` (v1.6.18)
  - log: 2026-07-23 the DOCX and PDF predicates share one `docx_row_is_blank`, so they cannot drift; it counts `w:pict`, `w:object` and OMML equations as content alongside pictures (v1.6.18)
- [x] **No re-promotion** - the body row left in position 0 by the delete is not painted or marked as a header in its place
  - log: 2026-07-23 criterion added
  - log: 2026-07-23 implemented - DOCX clears `tblLook firstRow` and skips `w:tblHeader`, PDF carries a `dropped_empty_header` flag past its `has_header` test; caught in review by the existing `DEF-5` PDF test failing (v1.6.18)
- [x] **No data loss on a picture-bearing row** - an image-on-top / caption-below grid keeps its first row in all three formats, since "no text" alone is not "no content"
  - log: 2026-07-23 criterion added after the architect round found the text-only predicate deleted a row with two images
  - log: 2026-07-23 implemented for DOCX and PDF - predicate tests embedded content as well as text; test `test_image_only_header_row_is_kept_with_its_images` (v1.6.18)
  - log: 2026-07-23 the confirming round found HTML still losing them - it strips tags to test emptiness, which erases the `<img>` too (measured: 2 images in, 0 out). The HTML predicate now bails on embedded content and the same test covers all three formats (v1.6.18)
- [x] **A picture-only first row is content, not a header** - it is kept, but carries no banded emphasis and does not repeat, the same way the PDF reads it
  - log: 2026-07-23 criterion added after the confirming round found keeping the row had made Word treat it as a header while the PDF did not
  - log: 2026-07-23 implemented - header chrome now keys off text in the ORIGINAL first row, separately from the blank test (v1.6.18)
- [x] **Column widths not skewed by the delete** - row 0 of a headerless grid is measured as body text, not as a bold header
  - log: 2026-07-23 criterion added after the architect round found the 8% bold widening landing on body content
  - log: 2026-07-23 implemented - `fit_docx_table_to_page` applies the factor only while `tblLook firstRow` is set; test `test_headerless_grid_columns_are_not_skewed_by_bold_widening`, mutation-proved at 6.6% skew (v1.6.18)
  - log: 2026-07-23 the PDF measures the same way (`string_width` selects the bold face for row 0), so it carried the same skew; gated on `has_header`, test `test_pdf_headerless_grid_columns_are_not_skewed` (v1.6.18)
- [x] **Edge: single-row blank table** - a hand-written HTML table whose only row is blank is left alone rather than emptied
  - log: 2026-07-23 criterion added
  - log: 2026-07-23 held - all three paths require a surviving body row before deleting. Not reachable from a markdown table: python-markdown synthesises an empty body row even for a header-only table (v1.6.18)

## Row and callout page splitting

reportlab splits a table either at row boundaries (`splitByRow`) or inside a row (`splitInRow`), and the choice is per table, not per row. The scenario matrix below is what forces a conditional value rather than a constant.

| Row height vs page | Fits the space left | `splitInRow=0`   | `splitInRow=1`    | Correct        |
| ------------------ | ------------------- | ---------------- | ----------------- | -------------- |
| <= page            | yes                 | renders in place | renders in place  | either         |
| <= page            | no                  | moves whole      | torn across pages | `splitInRow=0` |
| > page             | n/a                 | `LayoutError`    | splits, renders   | `splitInRow=1` |

Only the measured maximum row height separates the second row of the matrix from the third, so the flag is set after `wrap()` from `t._rowHeights`. A repeating header takes its own height off every continuation page, so the comparison subtracts it for body rows.

- [x] **A row that fits a page is never torn** - a caption and its image in one row render on the same page, moving to the next page whole when the current one has no space
  - log: 2026-07-23 criterion added after `DEF-9` ("when full row fits onto one page - it must be rendered as a whole, not broken down")
  - log: 2026-07-23 implemented as conditional `splitInRow` from measured row heights; test `test_pdf_row_that_fits_a_page_is_not_split`, mutation-proved (v1.6.18)
  - limitation: `splitInRow` is per table, so a table that also holds one row taller than a page keeps intra-row splitting for ALL its rows. Accepted rather than emitting each row as its own `Table`, which would give up the repeating header and the shared column layout (v1.6.18)
- [x] **Word keeps a row whole too** - the DOCX export marks every content-table row `w:cantSplit`, the Word counterpart of the conditional `splitInRow`
  - log: 2026-07-23 criterion added after the UX round found the fix was PDF-only, so the reported symptom survived in the format the defect was filed against
  - log: 2026-07-23 implemented in `style_docx_table`; a row taller than a page still breaks, since Word drops the request when it cannot be met and nothing sets an exact `w:trHeight`. Test `test_docx_rows_are_marked_unbreakable` (v1.6.18)
- [x] **A row taller than a page still splits** - the v1.6.16 `LayoutError` fix is preserved for genuinely oversized rows
  - log: 2026-07-23 criterion added
  - log: 2026-07-23 held - `splitInRow` goes to 1 as soon as any row exceeds the frame; the tall-image tests still pass (v1.6.18)
- [x] **Header-aware measurement** - under a repeating header the oversize test uses `frame_height - header_height` for body rows
  - log: 2026-07-23 criterion added
  - log: 2026-07-23 implemented; the guard runs after the repeat decision so it reads the final `repeatRows` (v1.6.18)
- [x] **Callouts follow the same rule** - an alert box or blockquote that fits a page is not torn either
  - log: 2026-07-23 criterion added after the architect round found `make_callout` still setting the flag unconditionally
  - log: 2026-07-23 implemented in `make_callout`; test `test_pdf_callout_that_fits_a_page_is_not_split` (v1.6.18)

## Mermaid raster framing

A mermaid diagram is rendered to SVG in the browser and screenshotted at the configured export width. The raster must be the diagram, not the diagram adrift in whitespace.

- [x] **Diagram fills its raster** - a rasterized mermaid diagram's ink spans at least 85% of the image width
  - log: 2026-07-23 criterion added after `DEF-7` (regression: "inserted as mini svg-s and most of the svg is whitespace")
  - log: 2026-07-23 implemented - clear mermaid's inline `max-width` cap before sizing, and pad the tightened viewBox per axis instead of using one pad from the larger axis; the 10 diagrams of a real document went from 43.3% worst-case to 92.8-98.1% width (v1.6.18)
- [x] **Deterministic detection** - the check runs on the exported artefact, not on a hand-inspected render
  - log: 2026-07-23 criterion added ("reproduce and finally solve it with deterministic test")
  - log: 2026-07-23 implemented - `test_docx_mermaid_image_is_not_mostly_whitespace` pulls the PNG back out of the `.docx`, trims transparent and white margin, and measures the ink span; mutation-proved at 39% without the fix (v1.6.18)
- [x] **Equal printed margin on every side** - the crop pad is one value taken from the diagram's smaller extent, so a wide flowchart is not left floating between wide side gutters
  - log: 2026-07-23 criterion added after the UX round found the per-axis pad gave a wide diagram side gutters five times its top ones
  - log: 2026-07-23 implemented; also measures better on the real document - 97.1-98.9% ink width against 92.8-98.1% for the per-axis pad (v1.6.18)
- [x] **An extreme aspect ratio still exports** - a long single-column flowchart is scaled down to the raster limit rather than failing to rasterize and vanishing from the document
  - log: 2026-07-23 criterion added after the UX round traced the failure path: the screenshot throws past Chromium's ~16384px cap, the renderer falls back to the SVG data URI, and htmldocx cannot embed SVG
  - log: 2026-07-23 implemented as a `MAX_RASTER_PX` clamp on the target raster, aspect preserved; test `test_extreme_aspect_diagram_stays_within_the_raster_limit`, mutation-proved (400x8400 unclamped) (v1.6.18)
- [x] **A well-framed diagram is not cropped** - a diagram that already fills its viewBox is left untouched, since `getBBox` sees geometry only and would clip a boundary stroke or marker
  - log: 2026-07-23 criterion added
  - log: 2026-07-23 held - the crop is gated on a fill below 0.8; tests `test_well_framed_diagram_is_not_cropped` and `test_nonzero_viewbox_origin_is_preserved` (v1.6.18)
