# Acceptance Criteria - jupyterlab_export_markdown_extension

Acceptance criteria for the markdown export extension across PDF, DOCX and HTML. One `##` section per feature; append new features as new sections.

## Authors

- `@kj` Konrad Jelen

## Export page fitting `PAGE`

Exported content must stay inside the printable page - a table must not strand its header row at a page break, and a diagram must fit both page width and page height. PDF lays out manually with reportlab, DOCX relies on Word's pagination, HTML relies on the print stylesheet.

| Behaviour                               | PDF                  | DOCX                 | HTML                      |
| --------------------------------------- | -------------------- | -------------------- | ------------------------- |
| Orphan header deferred to next page     | `repeatRows` defers  | header repeat + keep | `@media print` break      |
| Header repeated on continuation pages   | `repeatRows`         | `w:tblHeader`        | `thead` native            |
| Image scaled to page width              | existing             | existing             | `max-width:100%` existing |
| Image scaled down further when too tall | scale to page height | existing             | `@media print` max-height |

### Orphan header pagination

- [x] `ACC-PAGE-1` **PDF: no header-only page bottom** - a content table whose header row would sit at a page bottom with no body row after it on that page is moved whole to the next page
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj implemented via `repeatRows=1` on the reportlab Table, which defers the whole table rather than splitting off a header-only piece (v1.6.16)
- [x] `ACC-PAGE-2` **PDF: header repeats on split** - a table taller than one page repeats its header row at the top of each continuation page
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj implemented; tested a 80-row table repeats its header on >= 2 pages (v1.6.16)
- [x] `ACC-PAGE-3` **DOCX: header repeat, no orphan** - the header row carries `w:tblHeader` so Word repeats it per page and does not strand it alone at a page bottom
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj implemented in `style_docx_table`, gated on a table having a body row (v1.6.16)
- [x] `ACC-PAGE-4` **HTML: print keeps header with a row** - the print stylesheet forbids a page break between the header and the first body row (`thead` break-inside and break-after avoid, `tr` break-inside avoid)
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj implemented in the `@media print` block; tested via computed style (v1.6.16)
- [x] `ACC-PAGE-5` **Edge: table taller than a full page** - splitting is still allowed; the guard only defers a header stranded with zero body rows, never a table that genuinely cannot fit one page
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj held - `splitInRow=1` still carries a page-tall row; multi-page table test passes (v1.6.16)
- [x] `ACC-PAGE-6` **Edge: header-only table** - a table with a header and no body rows exports without error and is not deferred forever
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj verified - header-only table exports in all three formats; DOCX header marking gated on a body row (v1.6.16)
- [x] `ACC-PAGE-7` **Edge: single-cell alert table** - the orphan guard does not touch the decorative single-cell alert-box tables
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj held - alert tables are excluded from `style_docx_table` by identity; a single-cell table has no header-plus-body to orphan (v1.6.16)

### Diagram and image page fit

- [x] `ACC-PAGE-8` **PDF: image fits page height** - an image scaled to page width is scaled down further, aspect preserved, when that width leaves it taller than the printable page height
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj implemented in `process_image` (frame width then frame height); replaced the stray `7*inch` width; tested a 300x3000 image fits (v1.6.16)
- [x] `ACC-PAGE-9` **DOCX: image fits page height** - an image wider or taller than the page is scaled down to fit both, aspect preserved (existing behaviour, held by test)
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj existing behaviour now covered by a regression test (v1.6.16)
- [x] `ACC-PAGE-10` **HTML: print caps image height** - the print stylesheet bounds image height to about one printed page so a tall diagram fits a page rather than spilling across several; width stays `max-width:100%`
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj implemented as `@media print img { max-height: 9in }` - `100vh` and `width:auto` proved unreliable in Chromium print (2-3 pages); tested by rendering the print PDF and asserting one page (v1.6.16)
- [x] `ACC-PAGE-11` **Mermaid: width from setting, height from page** - a mermaid diagram keeps its configured export width unless the page height forces a smaller uniform scale
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj held - mermaid renders to an image that flows through the same width-then-height fit as any image (v1.6.16)
- [x] `ACC-PAGE-12` **Edge: image already within the page** - an image that fits both dimensions is left untouched, never upscaled
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj held - all scaling is gated on the image exceeding a dimension, so a fitting image is untouched (v1.6.16)
- [x] `ACC-PAGE-13` **Edge: image in a table cell** - a table-cell image scales to its cell width, not the page width (existing behaviour, unaffected)
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj held - table-cell path unchanged, covered by the existing image-scaling tests (v1.6.16)
- [x] `ACC-PAGE-14` **Edge: degenerate scale** - a scale that would round a dimension to zero does not erase the image
  - log: 2026-07-22T00:00:00Z @kj criterion added
  - log: 2026-07-22T00:00:00Z @kj held - DOCX floors EMU with `max(1, ...)`; PDF clamps directly to the frame dimensions in float, which never reaches zero for a real image (v1.6.16)

## Blank grid header `GRID`

Markdown has no table syntax without a header row, so a borderless image or layout grid is written with an empty one (`|  |  |  |`). Markdown renders nothing for that row, and the exports must agree - the row is removed, not merely stripped of header styling. The rule is structural, so a row that carries pictures but no text is content and is kept.

| Scenario                       | Markdown         | PDF         | DOCX        | HTML            |
| ------------------------------ | ---------------- | ----------- | ----------- | --------------- |
| Header with text               | header row       | header row  | header row  | `thead`         |
| Header blank, body rows follow | nothing rendered | row dropped | row dropped | `thead` dropped |
| Header blank with pictures     | pictures shown   | row kept    | row kept    | row kept        |
| Header blank, no body rows     | nothing rendered | row dropped | row dropped | `thead` dropped |

A header-only markdown table is not the fourth case: python-markdown synthesises an empty `<tbody>` row for it, so a body row always survives the delete. The single-row guard on all three paths only fires for a raw HTML table written by hand.

- [x] `ACC-GRID-15` **All formats: blank header row removed** - a first row with no text and no embedded content is deleted from the exported table, not just unstyled
  - log: 2026-07-23T00:00:00Z @kj criterion added after `DEF-TABL-8` ("ms word and pdf render header row - while if empty in markdown it is never rendered")
  - log: 2026-07-23T00:00:00Z @kj implemented in `style_docx_table` (DOCX), `process_table` (PDF) and `drop_empty_table_headers` (HTML); tests `test_docx_empty_header_row_is_dropped`, `test_html_empty_header_row_is_dropped` (v1.6.18)
  - log: 2026-07-23T00:00:00Z @kj the DOCX and PDF predicates share one `docx_row_is_blank`, so they cannot drift; it counts `w:pict`, `w:object` and OMML equations as content alongside pictures (v1.6.18)
- [x] `ACC-GRID-16` **No re-promotion** - the body row left in position 0 by the delete is not painted or marked as a header in its place
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj implemented - DOCX clears `tblLook firstRow` and skips `w:tblHeader`, PDF carries a `dropped_empty_header` flag past its `has_header` test; caught in review by the existing `DEF-TABL-5` PDF test failing (v1.6.18)
- [x] `ACC-GRID-17` **No data loss on a picture-bearing row** - an image-on-top / caption-below grid keeps its first row in all three formats, since "no text" alone is not "no content"
  - log: 2026-07-23T00:00:00Z @kj criterion added after the architect round found the text-only predicate deleted a row with two images
  - log: 2026-07-23T00:00:00Z @kj implemented for DOCX and PDF - predicate tests embedded content as well as text; test `test_image_only_header_row_is_kept_with_its_images` (v1.6.18)
  - log: 2026-07-23T00:00:00Z @kj the confirming round found HTML still losing them - it strips tags to test emptiness, which erases the `<img>` too (measured: 2 images in, 0 out). The HTML predicate now bails on embedded content and the same test covers all three formats (v1.6.18)
- [x] `ACC-GRID-18` **A picture-only first row is content, not a header** - it is kept, but carries no banded emphasis and does not repeat, the same way the PDF reads it
  - log: 2026-07-23T00:00:00Z @kj criterion added after the confirming round found keeping the row had made Word treat it as a header while the PDF did not
  - log: 2026-07-23T00:00:00Z @kj implemented - header chrome now keys off text in the ORIGINAL first row, separately from the blank test (v1.6.18)
- [x] `ACC-GRID-19` **Column widths not skewed by the delete** - row 0 of a headerless grid is measured as body text, not as a bold header
  - log: 2026-07-23T00:00:00Z @kj criterion added after the architect round found the 8% bold widening landing on body content
  - log: 2026-07-23T00:00:00Z @kj implemented - `fit_docx_table_to_page` applies the factor only while `tblLook firstRow` is set; test `test_headerless_grid_columns_are_not_skewed_by_bold_widening`, mutation-proved at 6.6% skew (v1.6.18)
  - log: 2026-07-23T00:00:00Z @kj the PDF measures the same way (`string_width` selects the bold face for row 0), so it carried the same skew; gated on `has_header`, test `test_pdf_headerless_grid_columns_are_not_skewed` (v1.6.18)
- [x] `ACC-GRID-20` **Edge: single-row blank table** - a hand-written HTML table whose only row is blank is left alone rather than emptied
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - all three paths require a surviving body row before deleting. Not reachable from a markdown table: python-markdown synthesises an empty body row even for a header-only table (v1.6.18)

## Row and callout page splitting `SPLIT`

reportlab splits a table either at row boundaries (`splitByRow`) or inside a row (`splitInRow`), and the choice is per table, not per row. The scenario matrix below is what forces a conditional value rather than a constant.

| Row height vs page | Fits the space left | `splitInRow=0`   | `splitInRow=1`    | Correct        |
| ------------------ | ------------------- | ---------------- | ----------------- | -------------- |
| <= page            | yes                 | renders in place | renders in place  | either         |
| <= page            | no                  | moves whole      | torn across pages | `splitInRow=0` |
| > page             | n/a                 | `LayoutError`    | splits, renders   | `splitInRow=1` |

Only the measured maximum row height separates the second row of the matrix from the third, so the flag is set after `wrap()` from `t._rowHeights`. A repeating header takes its own height off every continuation page, so the comparison subtracts it for body rows.

- [x] `ACC-SPLIT-21` **A row that fits a page is never torn** - a caption and its image in one row render on the same page, moving to the next page whole when the current one has no space
  - log: 2026-07-23T00:00:00Z @kj criterion added after `DEF-TABL-9` ("when full row fits onto one page - it must be rendered as a whole, not broken down")
  - log: 2026-07-23T00:00:00Z @kj implemented as conditional `splitInRow` from measured row heights; test `test_pdf_row_that_fits_a_page_is_not_split`, mutation-proved (v1.6.18)
  - limitation: `splitInRow` is per table, so a table that also holds one row taller than a page keeps intra-row splitting for ALL its rows. Accepted rather than emitting each row as its own `Table`, which would give up the repeating header and the shared column layout (v1.6.18)
- [x] `ACC-SPLIT-22` **Word keeps a row whole too** - the DOCX export marks every content-table row `w:cantSplit`, the Word counterpart of the conditional `splitInRow`
  - log: 2026-07-23T00:00:00Z @kj criterion added after the UX round found the fix was PDF-only, so the reported symptom survived in the format the defect was filed against
  - log: 2026-07-23T00:00:00Z @kj implemented in `style_docx_table`; a row taller than a page still breaks, since Word drops the request when it cannot be met and nothing sets an exact `w:trHeight`. Test `test_docx_rows_are_marked_unbreakable` (v1.6.18)
- [x] `ACC-SPLIT-23` **A row taller than a page still splits** - the v1.6.16 `LayoutError` fix is preserved for genuinely oversized rows
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - `splitInRow` goes to 1 as soon as any row exceeds the frame; the tall-image tests still pass (v1.6.18)
- [x] `ACC-SPLIT-24` **Header-aware measurement** - under a repeating header the oversize test uses `frame_height - header_height` for body rows
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj implemented; the guard runs after the repeat decision so it reads the final `repeatRows` (v1.6.18)
- [x] `ACC-SPLIT-25` **Callouts follow the same rule** - an alert box or blockquote that fits a page is not torn either
  - log: 2026-07-23T00:00:00Z @kj criterion added after the architect round found `make_callout` still setting the flag unconditionally
  - log: 2026-07-23T00:00:00Z @kj implemented in `make_callout`; test `test_pdf_callout_that_fits_a_page_is_not_split` (v1.6.18)

## Mermaid raster framing `RAST`

A mermaid diagram is rendered to SVG in the browser and screenshotted at the configured export width. The raster must be the diagram, not the diagram adrift in whitespace.

- [x] `ACC-RAST-26` **Diagram fills its raster** - a rasterized mermaid diagram's ink spans at least 85% of the image width
  - log: 2026-07-23T00:00:00Z @kj criterion added after `DEF-DIAG-7` (regression: "inserted as mini svg-s and most of the svg is whitespace")
  - log: 2026-07-23T00:00:00Z @kj implemented - clear mermaid's inline `max-width` cap before sizing, and pad the tightened viewBox per axis instead of using one pad from the larger axis; the 10 diagrams of a real document went from 43.3% worst-case to 92.8-98.1% width (v1.6.18)
- [x] `ACC-RAST-27` **Deterministic detection** - the check runs on the exported artefact, not on a hand-inspected render
  - log: 2026-07-23T00:00:00Z @kj criterion added ("reproduce and finally solve it with deterministic test")
  - log: 2026-07-23T00:00:00Z @kj implemented - `test_docx_mermaid_image_is_not_mostly_whitespace` pulls the PNG back out of the `.docx`, trims transparent and white margin, and measures the ink span; mutation-proved at 39% without the fix (v1.6.18)
- [x] `ACC-RAST-28` **Equal printed margin on every side** - the crop pad is one value taken from the diagram's smaller extent, so a wide flowchart is not left floating between wide side gutters
  - log: 2026-07-23T00:00:00Z @kj criterion added after the UX round found the per-axis pad gave a wide diagram side gutters five times its top ones
  - log: 2026-07-23T00:00:00Z @kj implemented; also measures better on the real document - 97.1-98.9% ink width against 92.8-98.1% for the per-axis pad (v1.6.18)
- [x] `ACC-RAST-29` **An extreme aspect ratio still exports** - a long single-column flowchart is scaled down to the raster limit rather than failing to rasterize and vanishing from the document
  - log: 2026-07-23T00:00:00Z @kj criterion added after the UX round traced the failure path: the screenshot throws past Chromium's ~16384px cap, the renderer falls back to the SVG data URI, and htmldocx cannot embed SVG
  - log: 2026-07-23T00:00:00Z @kj implemented as a `MAX_RASTER_PX` clamp on the target raster, aspect preserved; test `test_extreme_aspect_diagram_stays_within_the_raster_limit`, mutation-proved (400x8400 unclamped) (v1.6.18)
- [x] `ACC-RAST-30` **A well-framed diagram is not cropped** - a diagram that already fills its viewBox is left untouched, since `getBBox` sees geometry only and would clip a boundary stroke or marker
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - the crop is gated on a fill below 0.8; tests `test_well_framed_diagram_is_not_cropped` and `test_nonzero_viewbox_origin_is_preserved` (v1.6.18)

## Line break fidelity `BREAK`

A break the author writes must render as one break. Markdown's `nl2br` also converts the newline that follows it, which doubles any hand-written `<br>` - and a doubled break is not cosmetic: it inverts the grouping of a question above its answer, the reason the idiom is used at all.

| Source                                | Author's intent             | Rendered breaks  |
| ------------------------------------- | --------------------------- | ---------------- |
| `line<br>` + newline                  | one break                   | 1                |
| `line<br>` + space + newline          | one break                   | 1                |
| `line<br>` + 2 spaces + newline       | break, then hard break      | 2                |
| `line<br><br>` + newline              | blank line                  | 2                |
| `line<BR>` / `<br clear="all">`       | one break                   | 1                |
| `line<br-spacer>` + newline           | custom element, not a break | 1                |
| `line<!-- ... <br> ... -->`           | a comment, not a break      | 1                |
| `**line<br>**` + newline              | one break                   | 2 (not detected) |
| `<br>` alone on its own line          | blank line                  | 2                |
| `<br>` in a table cell                | one break                   | 1                |
| `one<br /><br />` in a raw HTML block | blank line                  | 2                |

- [x] `ACC-BREAK-31` **One break where the author wrote one** - a line ended with `<br>` renders with a single break in HTML, DOCX and PDF. Known limitation: a break written INSIDE inline markup (`**Q<br>**`) is not detected, because the trailing node is then the emphasis element rather than the break; that shape still renders a blank line
  - log: 2026-07-23T00:00:00Z @kj criterion added after `DEF-MARK-10` ("question and answer ... in the docx they are spread apart, one cannot know that one q&a is separate from next q&a")
  - log: 2026-07-23T00:00:00Z @kj implemented in `markdown_to_html`, so all three formats inherit it; tests `test_html_keeps_one_break`, `test_docx_pair_holds_one_break` (v1.6.19)
  - log: 2026-07-23T00:00:00Z @kj adversarial review replaced the mechanism twice. Shipped as a regex over the finished HTML, it matched shape rather than provenance and deleted authored breaks - inside a raw HTML block, and for Markdown's own two-trailing-spaces hard break, which core Markdown emits as the same `<br />`. The rule now lives at the inline stage, where the author's tag is still a stashed node and the two-space break has already been claimed by a higher-priority pattern
- [x] `ACC-BREAK-32` **A pair reads as a pair** - a question sits closer to its own answer than to the next question
  - log: 2026-07-23T00:00:00Z @kj criterion added - the measurable form of the defect, since the break count alone does not prove the reader can see the grouping
  - log: 2026-07-23T00:00:00Z @kj held - PDF measures 12.0pt inside the pair against 18.0pt between pairs (24.0 against 18.0 before); DOCX gets ~13pt against the ~23pt its `w:after="200"` plus 1.15 line spacing gives a paragraph boundary. Test `test_pdf_pair_is_tighter_than_the_gap_between_pairs`, mutation-proved (v1.6.19)
- [x] `ACC-BREAK-33` **An explicit blank line survives** - `<br><br>` is an author asking for a blank line, not a duplicate to collapse
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - only the generated tag is dropped, so two hand-written breaks stay two; test `test_explicit_blank_line_is_preserved` (v1.6.19)
- [x] `ACC-BREAK-34` **Only a generated break is ever dropped** - every break the author typed survives, whatever its spelling and wherever it sits
  - log: 2026-07-23T00:00:00Z @kj criterion added - a caption-above-image grid depends on a cell's break, and the alert-box idiom on a raw block's
  - log: 2026-07-23T00:00:00Z @kj restated after the review proved the original wording ("the pattern requires the generated `<br />` plus its newline, which those contexts never carry") false for a raw HTML block. The rule now decides at the inline stage: a newline is skipped only when the node immediately before it is a break tag the author typed, so a table cell (which cannot hold a newline), a raw HTML block, a `<br-spacer>` custom element and the two-space hard break are all left alone
  - log: 2026-07-23T00:00:00Z @kj held - tests `test_break_in_a_table_cell_is_untouched`, `test_raw_html_block_keeps_its_own_breaks`, `test_custom_element_is_not_treated_as_a_break`, `test_manual_break_plus_hard_break_keeps_both`, `test_uppercase_and_attributed_breaks_are_recognised`, `test_non_breaking_space_after_the_break_still_collapses`, all mutation-proved
- [x] `ACC-BREAK-35` **A failure of this rule cannot fail an export** - it is cosmetic, and it reaches into Markdown's internals to read provenance
  - log: 2026-07-23T00:00:00Z @kj criterion added after the review found the internal import sitting in the request path, where an incompatible Markdown would 500 every export
  - log: 2026-07-23T00:00:00Z @kj held - each internal lookup falls back to emitting the break (plain `nl2br` behaviour) and the extension itself falls back to `'nl2br'` if it cannot be built

## Export font size `FONT`

One setting picks the base body size and everything else follows from it, so a document scales as a whole rather than only its paragraphs. Before this, the PDF hardcoded 10pt body text and the DOCX 11pt - the same document rendered at two different scales.

| Setting  | Base body | PDF heading 1 | PDF table | PDF code | HTML measure |
| -------- | --------- | ------------- | --------- | -------- | ------------ |
| `small`  | 10pt      | 14pt          | 9pt       | 8pt      | 50em         |
| `medium` | 12pt      | 16.8pt        | 10.8pt    | 9.6pt    | 50em         |
| `large`  | 14pt      | 19.6pt        | 12.6pt    | 11.2pt   | 50em         |

- [x] `ACC-FONT-36` **The base size follows the setting in all three formats** - PDF body text, the DOCX `Normal` style and the HTML body rule all render at 10 / 12 / 14pt
  - log: 2026-07-23T00:00:00Z @kj criterion added with the `exportFontSize` setting
  - log: 2026-07-23T00:00:00Z @kj implemented - `EXPORT_FONT_SIZES` resolves the setting, `PDF_TYPE_SCALE` derives every reportlab style, `apply_docx_font_size` scales the DOCX styles, the HTML body rule takes the size directly; tests `test_pdf_base_size_follows_the_setting`, `test_docx_base_size_follows_the_setting`, `test_html_base_size_follows_the_setting` (v1.6.20)
- [x] `ACC-FONT-37` **Everything else is a proportion of it** - a heading, a table cell and a code block keep the same ratio to body text at every size
  - log: 2026-07-23T00:00:00Z @kj criterion added - a base size that moved only paragraphs would change the document's proportions, not its scale
  - log: 2026-07-23T00:00:00Z @kj held - PDF sizes come from one ratio table, the DOCX template's explicit sizes are scaled by the same factor rather than overwritten, and the HTML stylesheet was already in `em`; test `test_pdf_headings_stay_proportional` (v1.6.20)
- [x] `ACC-FONT-38` **Line length scales too** - the HTML column is `50em`, so characters per line stay constant instead of shrinking a third at `large`
  - log: 2026-07-23T00:00:00Z @kj criterion added after review found `max-width: 800px` was the one measure left absolute
  - log: 2026-07-23T00:00:00Z @kj implemented; at the 12pt default 50em is the same 800px it was, so nothing moves for an existing reader. Test `test_html_measure_scales_with_the_body` (v1.6.20)
- [x] `ACC-FONT-39` **The default is medium, including for a client that sends nothing** - an older frontend, or a fresh install, exports at 12pt
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - the handlers resolve through `font_size_pt`, which defaults; test `test_default_is_medium_in_every_format` (v1.6.20)
- [x] `ACC-FONT-40` **A malformed setting cannot fail an export** - the size is cosmetic, so a value of the wrong type or an absurd number falls back or clamps rather than returning a 500
  - log: 2026-07-23T00:00:00Z @kj criterion added after review found a plain dict lookup raises `TypeError` on an unhashable value, and that an explicit 0 builds zero-height flowables
  - log: 2026-07-23T00:00:00Z @kj implemented - non-string, non-number values take the default; a number is clamped to 6-32pt. Test `test_a_malformed_setting_cannot_fail_an_export`, mutation-proved (500 without the guard) (v1.6.20)

## Alert box integrity `ALERT`

A `> [!NOTE]` block is one callout however many paragraphs it holds. The marker the DOCX and HTML passes key on has to live in a single paragraph, so the body's own structure is carried by explicit breaks rather than by several paragraphs.

- [x] `ACC-ALERT-41` **A multi-paragraph alert is one box** - a bare `>` separating two paragraphs of an alert does not end it
  - log: 2026-07-23T00:00:00Z @kj criterion added with DEF-MARK-11; the continuation group required `"> "` with a space, so the bare `>` terminated the match and the rest of the alert fell out as a plain blockquote - a coloured box followed by a grey one
  - log: 2026-07-23T00:00:00Z @kj held in all three formats - tests `test_html_is_one_box_holding_both_paragraphs`, `test_docx_is_one_alert_table_holding_both_paragraphs`, `test_pdf_is_one_callout_with_no_stray_blockquote`; mutation-proved. The PDF needed no code change: `process_alert` already walks every paragraph in the alert cell
- [x] `ACC-ALERT-42` **A source newline inside an alert breaks the line, as it does everywhere else** - `nl2br` gives body text a break per newline; an alert joined its lines with a space, so the same two source lines set two different ways in one document
  - log: 2026-07-23T00:00:00Z @kj criterion added with DEF-MARK-11
  - log: 2026-07-23T00:00:00Z @kj held - test `test_source_line_breaks_inside_an_alert_are_kept`, mutation-proved. Visible behaviour change for alerts whose prose is soft-wrapped across source lines
- [x] `ACC-ALERT-43` **A break the author wrote inside an alert is not doubled** - the same rule `manual_break_aware_nl2br` applies to body text, applied where no newline survives for it to see
  - log: 2026-07-23T00:00:00Z @kj criterion added - the join adds a break per line, which would land on top of one the author already typed
  - log: 2026-07-23T00:00:00Z @kj held - a line already ending in a break tag counts towards the break the join owes it; test `test_an_authored_break_in_an_alert_is_not_doubled`
- [x] `ACC-ALERT-44` **Widening the continuation captures no more than the alert** - two adjacent alerts stay two boxes, and an ordinary multi-paragraph blockquote is still a blockquote
  - log: 2026-07-23T00:00:00Z @kj criterion added - accepting a bare `>` widens what the pattern will swallow
  - log: 2026-07-23T00:00:00Z @kj held - tests `test_two_adjacent_alerts_stay_separate`, `test_a_plain_blockquote_is_still_a_blockquote`
- [ ] `ACC-ALERT-45` **Block structure inside an alert survives** - a list or a fence written in an alert body still flattens to run-on text
  - log: 2026-07-23T00:00:00Z @kj criterion added and left open; pre-dates DEF-MARK-11 and needs paired markers plus a body-element sweep in two passes. Registered as DEF-MARK-14

## Heading level fidelity `HEAD`

The PDF is built from the DOCX, so the two must draw the same document the same way. Word's template tells the levels below 3 apart by weight, slant and colour rather than by size.

| Level | Face        | Colour    | Size      |
| ----- | ----------- | --------- | --------- |
| H1    | bold        | `#365F91` | 1.4x body |
| H2    | bold        | `#4F81BD` | 1.2x body |
| H3    | bold        | `#4F81BD` | 1.1x body |
| H4    | bold italic | `#4F81BD` | body      |
| H5    | regular     | `#243F60` | body      |
| H6    | italic      | `#243F60` | body      |

- [x] `ACC-HEAD-46` **Every heading level is visually distinct in the PDF** - `####` no longer renders identically to `###`
  - log: 2026-07-23T00:00:00Z @kj criterion added with DEF-MARK-12; a `startswith('Heading')` catch-all routed levels 4, 5 and 6 into the Heading 3 style, so a sub-subsection read as a sibling of its parent
  - log: 2026-07-23T00:00:00Z @kj held - test `test_every_heading_level_is_visually_distinct` asserts six distinct (font, colour, size) triples; mutation-proved
- [x] `ACC-HEAD-47` **The PDF faces are the DOCX template's own** - the same document does not read differently in the two formats
  - log: 2026-07-23T00:00:00Z @kj criterion added with DEF-MARK-12
  - log: 2026-07-23T00:00:00Z @kj held - `PDF_MINOR_HEADING_FACES` carries the faces read off the live python-docx template; tests `test_minor_headings_match_the_docx_faces`, `test_minor_headings_sit_at_body_size`
- [x] `ACC-HEAD-48` **An unrecognised heading style still gets a heading face** - a style named `Heading` with no number, or beyond level 6, falls to Heading 3 as it did before
  - log: 2026-07-23T00:00:00Z @kj criterion added - replacing a catch-all with a lookup is where a level quietly stops being a heading
  - log: 2026-07-23T00:00:00Z @kj held - the dispatch parses the level and falls back to the Heading 3 style on any miss
- [x] `ACC-HEAD-49` **The italic heading faces draw in the document's own font, not a core substitute** - H4 and H6 must not fall back to Helvetica
  - log: 2026-07-23T00:00:00Z @kj criterion added after the confirming UX round measured H4/H6 in `Helvetica-BoldOblique`/`-Oblique` while H1-H3, H5 and body were DejaVu - `_register_unicode_fonts` committed to DejaVu (no oblique on this box) and stopped, so every italic fell to a core face
  - log: 2026-07-23T00:00:00Z @kj held - the registration now fills each variant from the first family that ships it; normal and bold stay DejaVu, the italics come from Liberation. Test `test_italic_headings_do_not_fall_back_to_a_core_font`, mutation-proved
- [ ] `ACC-HEAD-50` **A heading is not stranded at the foot of a page** - no PDF heading style sets `keepWithNext`, so a page break can fall between a heading and its first paragraph
  - log: 2026-07-23T00:00:00Z @kj criterion added and left open; a pagination question rather than a face question. Registered as DEF-MARK-15
- [ ] `ACC-HEAD-51` **H5 is legible against body text** - H5 is regular navy at body size, told from black body text by colour alone (~2:1)
  - log: 2026-07-23T00:00:00Z @kj criterion added and left open as an accepted trade-off; the face is copied from Word's own Heading 5, so raising the contrast would break the PDF/DOCX parity above. Recorded in DEF-MARK-12

## Code line wrapping `WRAP`

`XPreformatted` lays every source line out as exactly one line whatever its width - it never wraps, and no style setting changes that. A line wider than the frame is therefore drawn past the page edge, where its glyphs are not rendered at all. The code font is fixed-width, so the frame width converts to an exact column count and the line is split before the highlighting markup goes on.

- [x] `ACC-WRAP-52` **No code is drawn past the frame edge** - at every font size
  - log: 2026-07-23T00:00:00Z @kj criterion added with DEF-MARK-13; measured at x=614.4 against a 576pt margin
  - log: 2026-07-23T00:00:00Z @kj held - test `test_a_long_code_line_stays_inside_the_margin`; mutation-proved. Verified on the reference documents: 16 / 22 / 20 runs past the margin at small / medium / large on `00-inception-poc-owt.md` before, zero after, across all four documents
- [x] `ACC-WRAP-53` **Wrapping loses no characters** - the overflow was not merely past the margin, it was past the page, where reportlab draws nothing
  - log: 2026-07-23T00:00:00Z @kj criterion added after measuring a 300-character line put 91 characters on the page and dropped 209
  - log: 2026-07-23T00:00:00Z @kj held - test `test_wrapping_loses_no_characters` counts every character back out of the PDF
- [x] `ACC-WRAP-54` **A line that fits is not broken** - only an overflowing line wraps, or every code sample gains phantom breaks
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - test `test_a_short_code_line_is_not_broken` asserts a two-line block renders on two lines
- [x] `ACC-WRAP-55` **The split is measured on real characters, not on markup** - escaping before the split would count `&amp;` as five columns where the reader sees one
  - log: 2026-07-23T00:00:00Z @kj criterion added; the token loop was rewritten to carry raw `(colour, text)` segments and escape at render time
  - log: 2026-07-23T00:00:00Z @kj held by construction - `render()` is the only place escaping happens, and it runs after `wrap()`
- [ ] `ACC-WRAP-56` **Accepted limits** - a line dense with glyphs the fixed-width code font lacks (emoji, CJK) can still overrun, and a wrapped continuation carries no hanging indent to set it apart from a new statement
  - log: 2026-07-23T00:00:00Z @kj both raised in the adversarial round and left as accepted trade-offs - the wide-glyph case is rare in code and still far better than the whole line running off the page; the continuation marker is the universal soft-wrap tradeoff. Both stated in the `code_columns` docstring

## Mermaid without a browser `MERM`

Mermaid is a browser library. The extension renders each diagram in the page and posts the result to the server, so an export driven from the UI arrives with its diagrams already drawn. Nothing renders them when the REST endpoints are called directly, and the export used to fall back to the diagram's own source. The server now carries a vendored mermaid bundle and renders whatever the frontend did not, in the same headless Chromium that rasterizes SVGs.

- [x] `ACC-MERM-57` **A diagram renders in all three formats without a frontend payload** - the API is a first-class caller, not a degraded one
  - log: 2026-07-23T00:00:00Z @kj criterion added with DEF-DIAG-16; measured 10 mermaid fences in and 0 images out of the DOCX, with the source written into `word/document.xml` as code
  - log: 2026-07-23T00:00:00Z @kj held - tests `test_docx_renders_mermaid_without_a_frontend_payload`, `test_pdf_renders_mermaid_without_a_frontend_payload`, `test_html_renders_mermaid_without_a_frontend_payload`; all mutation-proved. The reference document exports 10 DOCX images at 97.1-98.9% ink width, 10 PDF images and 10 inline SVGs
- [x] `ACC-MERM-58` **The browser's own render still wins** - it carries the Lab theme and the fonts the reader sees, and re-rendering it would launch a browser for nothing
  - log: 2026-07-23T00:00:00Z @kj criterion added; the server pass runs after the frontend substitution, so it only ever sees what was left
  - log: 2026-07-23T00:00:00Z @kj held - test `test_a_diagram_the_frontend_supplied_is_not_re_rendered` supplies a 1x1 PNG and asserts it survives; mutation-proved at 14115 bytes when the order is swapped
- [x] `ACC-MERM-59` **A document with no diagram never starts a browser** - Chromium costs seconds to launch, and an export that worked on a server without it must keep working
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - test `test_a_document_without_mermaid_never_starts_a_browser` replaces the renderer with one that raises on construction; mutation-proved
- [x] `ACC-MERM-60` **One bad diagram costs only itself** - a syntax error keeps its source as text, and the diagrams around it still render
  - log: 2026-07-23T00:00:00Z @kj criterion added; a whole export failing on one unparseable block would be worse than the defect
  - log: 2026-07-23T00:00:00Z @kj held - test `test_a_diagram_mermaid_rejects_keeps_its_source`; a layout that does not converge within 30s is treated the same way
- [x] `ACC-MERM-61` **Rendering needs no network** - the bundle ships in the wheel, so an export on an air-gapped server behaves like any other
  - log: 2026-07-23T00:00:00Z @kj criterion added; a CDN would have been simpler and would have made every export a network call
  - log: 2026-07-23T00:00:00Z @kj held - `jlpm vendor:mermaid` copies the bundle out of `node_modules` into the package, and it is an `ensured-target`, so a wheel built without it fails the build instead of shipping a diagram-less export
- [x] `ACC-MERM-62` **An export never fails over a diagram** - a document missing one picture still beats no document
  - log: 2026-07-23T00:00:00Z @kj criterion added after weighing the alternative: raising the typed `CHROMIUM_UNAVAILABLE` 503 would have made HTML export, which has never needed Chromium, start failing on servers where it works today
  - log: 2026-07-23T00:00:00Z @kj held - no Chromium, no bundle, a syntax error, a layout past the 30s timeout and a failed rasterization all keep the source and return 200; tests `test_a_chromium_less_server_still_exports_and_says_why`, `test_html_export_also_reports_it`, `test_a_missing_bundle_is_named_as_such`; mutation-proved by re-raising, which fails both Chromium tests
- [x] `ACC-MERM-63` **Every un-rendered diagram is reported, with the remedy** - the body is a binary document, so `X-Export-Warnings` is the only channel an API caller has
  - log: 2026-07-23T00:00:00Z @kj criterion added; the caller must not have to diff the output against the source to notice a picture is missing
  - log: 2026-07-23T00:00:00Z @kj held - a JSON array of `{code, count, diagrams, message}` grouped by cause, `count` the number of diagrams a warning covers and `diagrams` a bounded prefix of their positions, `chromium-unavailable` carrying the install command; absent when everything rendered. Tests cover the four codes, the index attribution, and that the header is one line of valid JSON that never carries diagram source; all mutation-proved
- [x] `ACC-MERM-64` **The header stays machine-readable whatever the diagram contains** - the source is user content and a newline in a header value is rejected by the HTTP layer
  - log: 2026-07-23T00:00:00Z @kj criterion added
  - log: 2026-07-23T00:00:00Z @kj held - only codes and indices reach the header, never source; test `test_the_header_is_one_line_of_valid_json` feeds a diagram of quotes and non-ASCII and asserts the value parses and leaks nothing
- [x] `ACC-MERM-65` **One browser per export, not two** - the render and the rasterization are the same browser's work
  - log: 2026-07-23T00:00:00Z @kj criterion added after measuring ~300ms per Chromium launch
  - log: 2026-07-23T00:00:00Z @kj held - the pass rasterizes inside its own session and emits a PNG for DOCX/PDF, an SVG for HTML, exactly what the frontend posts for each; tests `test_one_browser_renders_and_rasterizes` and `test_docx_carries_a_png_and_html_an_svg`, mutation-proved at 2 launches when the rasterization is deferred
- [x] `ACC-MERM-66` **A diagram the SERVER renders cannot make it touch the network** - a markdown file is untrusted input, and the server has credentials a reader's browser does not
  - log: 2026-07-23T00:00:00Z @kj criterion added after a review lens raised it as a suspicion and the probe confirmed it: a label of `A["<img src='http://127.0.0.1:PORT/x.png'>"]` survives mermaid's HTML labels into a `<foreignObject>`, and exporting that document made the server issue **3 outbound requests** - a metadata endpoint away from being an SSRF primitive on a shared hub
  - log: 2026-07-23T00:00:00Z @kj held - every request is aborted in both the render context and the rasterize context; a mermaid diagram is self-contained, so nothing legitimate is lost. Only SVGs this server generated are blocked - a user's own `.svg` keeps the browser behaviour it always had. Test `test_a_mermaid_label_cannot_make_the_server_fetch_a_url`, mutation-proved at 2 requests
- [x] `ACC-MERM-67` **A mermaid example inside a longer fence stays text** - documentation that shows the syntax must not be replaced by a picture of itself
  - log: 2026-07-23T00:00:00Z @kj criterion added; latent before this change, because a quoted example was never rendered by the browser either
  - log: 2026-07-23T00:00:00Z @kj held - `iter_mermaid_blocks` tracks fence state and the substitution walks the same iterator, so collection and replacement cannot see different sets. Test `test_a_mermaid_example_inside_an_outer_fence_is_left_alone`, mutation-proved
  - log: 2026-07-23T00:00:00Z @kj corrected - an earlier version of this log said the scanner tracks fences 'the way `preprocess_task_lists` does'. It does not, and there are three mechanisms in `routes.py` rather than two: this scanner, that tracker, and the naive ` ```[\s\S]*?``` ` pair-matcher the math and alert passes protect with. Unifying them is a refactor of working code, out of this defect's scope
- [x] `ACC-MERM-68` **A warning names the diagram the reader would count to** - an index that points at a healthy diagram is worse than no index
  - log: 2026-07-23T00:00:00Z @kj criterion added; the pass only sees the blocks the frontend left, so numbering them 0, 1, 2 misreports every partial capture
  - log: 2026-07-23T00:00:00Z @kj held - `replace_mermaid_with_images` returns the document positions it left behind and the warning quotes those; test `test_a_warning_names_the_diagram_the_reader_would_count_to` (frontend supplies 0 and 1, failure on the third reports 2), mutation-proved
- [x] `ACC-MERM-69` **The API draws what the UI draws** - the point of the feature is that the two agree
  - log: 2026-07-23T00:00:00Z @kj criterion added after a review found the server initialising mermaid with `securityLevel: 'strict'` while this extension's own frontend uses `'loose'` - under strict, mermaid turns HTML labels off and the same diagram draws differently
  - log: 2026-07-23T00:00:00Z @kj held - `MERMAID_INIT_OPTIONS` mirrors `renderMermaidInTheme` in `src/index.ts`, and `test_the_server_renders_with_the_options_the_frontend_uses` reads the frontend source so the two cannot drift silently
- [x] `ACC-MERM-70` **A wrong diagram is told what is actually wrong** - a remedy that does not apply is worse than a generic one
  - log: 2026-07-23T00:00:00Z @kj criterion added; `syntax-error` was being reported for an elk-layout diagram, which is valid mermaid this server simply cannot draw, sending the author to fix syntax that is fine
  - log: 2026-07-23T00:00:00Z @kj held - `layout-unsupported` carries its own remedy, and the diagrams behind a timeout are `skipped` rather than accused of timing out themselves; test `test_the_diagrams_behind_a_timeout_are_not_blamed_for_it`
- [x] `ACC-MERM-71` **An upgrade in place builds** - a fresh clone working while an existing checkout fails is the asymmetry nobody notices until a user reports it
  - log: 2026-07-23T00:00:00Z @kj criterion added; `ensured-targets` gained the bundle while `skip-if-exists` did not, so a tree holding a pre-change labextension build skipped the build that creates the bundle and then failed on the bundle it had not created
  - log: 2026-07-23T00:00:00Z @kj held - both lists name the bundle; verified by removing `vendor/` from a built tree and running `python -m build`, which now rebuilds and passes
- [x] `ACC-MERM-72` **A quoted mermaid example stays text however it is quoted** - a fence carrying an info string never closes a block, so `\`\`\`text`around a`\`\`\`mermaid` quotes it exactly as a longer fence does
  - log: 2026-07-23T00:00:00Z @kj criterion added after the confirming round found the first fence rule tracked only 4-backtick and tilde openers, leaving the commonest way of quoting an example unprotected
  - log: 2026-07-23T00:00:00Z @kj held - one line scanner tracks every `\`\`\`{3,}`/`~~~{3,}`opener and treats a`mermaid` info string as a diagram only at the top level; the frontend's source fallback mirrors it, because the two pair diagrams by position and one counting an example the other skips hands a picture to the wrong diagram. Tests on both fence shapes plus a frontend-parity check, mutation-proved
- [x] `ACC-MERM-73` **The API accepts the same diagram sizes the UI does** - a document that renders in JupyterLab must not come back from the API as a syntax error
  - log: 2026-07-23T00:00:00Z @kj criterion added after the confirming round found that matching the frontend's `securityLevel` had dropped `maxTextSize`/`maxEdges`, which the frontend inherits from `@jupyterlab/mermaid` rather than setting itself
  - log: 2026-07-23T00:00:00Z @kj held - both ceilings restored at 100000; test `test_the_server_keeps_the_ceilings_the_browser_has`, mutation-proved
- [x] `ACC-MERM-74` **A malformed request setting cannot silently change the output format** - `svgPixelWidth: null` selected SVG output, which Word cannot display
  - log: 2026-07-23T00:00:00Z @kj criterion added; `data.get(key, default)` defaults a missing key only, so a key present and null passes `None` straight through
  - log: 2026-07-23T00:00:00Z @kj held - `svg_pixel_width()` coerces and clamps to the schema's range, following `font_size_pt`; tests for `null`, a string, zero, a negative, a bool and an absurd value, mutation-proved (the unfixed code 500s on a data URI used as a filename)
- [x] `ACC-MERM-75` **A browser that died is not reported as the author's mistake** - every remaining diagram would fail identically, each blaming the document
  - log: 2026-07-23T00:00:00Z @kj criterion added by the confirming round
  - log: 2026-07-23T00:00:00Z @kj held - a dead-session error is re-raised so the handler logs it once and marks the document `render-failed`; test `test_a_dead_browser_session_is_not_blamed_on_the_diagram`
- [x] `ACC-MERM-76` **Reporting a warning cannot fail an export, and the header stays small enough to travel** - the report is only useful if it arrives
  - log: 2026-07-23T00:00:00Z @kj criterion added; the first version of this log cited a 4000-character Tornado limit, which a later round disproved by reading the installed 6.5.7 - `_convert_header_value` validates characters only. The real constraint is the front end: nginx's default `proxy_buffer_size` is 4KB and has to hold the whole response header block
  - log: 2026-07-23T00:00:00Z @kj held - at most six codes can co-occur and `MAX_REPORTED_DIAGRAMS` caps the indices, measured at 1655 bytes worst case; test `test_the_header_stays_bounded_on_a_document_full_of_diagrams` (900 diagrams) asserts against the constant rather than a literal, and the header is added rather than set so it cannot displace another exposed header
- [ ] `ACC-MERM-77` **Nothing surfaces a warning in the JupyterLab UI** - a UI export that reaches the server-side path ships the document with the explanation in a header the client never reads
  - log: 2026-07-23T00:00:00Z @kj left open deliberately at the user's direction: asked how warnings should reach the caller, they chose the response header alone over a dialog. Reachable only when the mermaid manager token is absent, since otherwise the browser renders every diagram and the server pass finds nothing to warn about
- [x] `ACC-MERM-78` **A diagram is counted wherever markdown counts one** - inside a list item, behind a blockquote marker, at any indentation
  - log: 2026-07-23T00:00:00Z @kj criterion added after the third round found the second round's fence rule anchored indentation at column 0. CommonMark measures it from the container's content column, JupyterLab renders those diagrams, and the browser pairs them with fences by position - so skipping one puts every later picture on the wrong diagram
  - log: 2026-07-23T00:00:00Z @kj held - prefix `[ \t>]*` on both sides, and a quoted block's markers stripped before mermaid parses it (which the original regex never did); tests `test_a_diagram_nested_in_a_list_is_still_a_diagram` and `test_a_blockquoted_diagram_is_still_a_diagram`, mutation-proved
  - log: 2026-07-23T00:00:00Z @kj held fully after the sixth round - "at any indentation" was an overclaim while the indent gate was a boolean; measuring against the list item's content column made it literally true (count-vs-marked 0 across 18,000 realistic documents), with the reviewer-reproduced shapes added to the parity table
- [x] `ACC-MERM-79` **marked decides what a diagram is, not a reading of CommonMark** - JupyterLab renders the preview with marked and the capture posts one diagram per fence marked drew, so the server counts what marked counts or the pictures shift
  - log: 2026-07-23T00:00:00Z @kj criterion replaces "a diagram only opens on a fence the rest of the pipeline protects", which argued from what the downstream passes protect and concluded that `~~~mermaid` must not be a diagram. That traded a certainty for a residual risk the wrong way round: marked treats `~~~` exactly like ` ``` `, so refusing it dropped a diagram the browser had already counted
  - log: 2026-07-23T00:00:00Z @kj held - measured, not argued. Running `iter_mermaid_blocks` against the installed marked over 6000 generated documents found four divergence classes, two of which five review rounds had not named: case-sensitivity (` ```MERMAID ` is a code sample to marked and was a diagram here), the tilde fence, a fence closed by its container rather than by a closing fence, and a closer matched across containers. All four fixed. The remaining 0.3% - a fence four spaces past a list item's content column, and tab/bare-marker containers - the sixth round closed by measuring every fence in marked's own coordinate (`_quote_stripped` / `_list_content_col`): count-vs-marked is now 0 across 18,000 realistic documents, the only exception a ` ```text `-quoted example nested in a list item (recorded as a DEF-DIAG-16 known limitation). Test `test_marked_agrees_with_the_server_on_every_shape` re-derives every expected count from the installed marked, so the table cannot drift from the parser it describes
- [x] `ACC-MERM-80` **Nothing that rewrites the source runs before the diagrams are counted** - the browser counted them in the file the author wrote, and pairing is by position
  - log: 2026-07-23T00:00:00Z @kj criterion added after a diagram inside a `> [!NOTE]` was found exporting as the picture belonging to the next diagram. `preprocess_github_alerts` folds an alert body onto one line, which erases a fence inside it completely, and it ran before the mermaid passes - two diagrams in the browser, one on the server, every later picture one out
  - log: 2026-07-23T00:00:00Z @kj held - both mermaid passes run on the document as read; the alert's diagram survives as an image inside the note. The rule is stated on `render_mermaid_server_side` rather than only at the three call sites, so the next pass someone inserts is read against it
- [x] `ACC-MERM-81` **A list item's indentation is not part of the diagram** - marked hands mermaid the body dedented, and a source that only renders from the preview is the divergence this feature exists to remove
  - log: 2026-07-23T00:00:00Z @kj criterion added after the marked differential showed the body of an indented block reaching mermaid with the item's indentation on every line
  - log: 2026-07-23T00:00:00Z @kj held - `_body_source` removes the opening fence's columns, allowing for the one the quote marker takes; the TypeScript twin does the same. Caught by its own regression when the first version double-counted that column
- [x] `ACC-MERM-82` **A document-wide failure is visible without reading a header** - a mis-packaged wheel degrades every export in a way that looks exactly like the feature not existing
  - log: 2026-07-23T00:00:00Z @kj criterion added by the confirming round: `bundle-missing` and `chromium-unavailable` were reported only through `X-Export-Warnings`, and nothing in `src/` reads it
  - log: 2026-07-23T00:00:00Z @kj held - both branches log a warning carrying the same remedy the header does
- [x] `ACC-MERM-83` **Every numeric request setting is coerced, not just the one that was reported** - `null`, a string, a bool, zero, a negative, `Infinity`
  - log: 2026-07-23T00:00:00Z @kj criterion added after `mathPixelWidth` was found carrying the identical hazard one line from the fix, measured shipping `$x^2$` into a PDF as literal text
  - log: 2026-07-23T00:00:00Z @kj held - one `_pixel_width` helper behind `svg_pixel_width` and `math_pixel_width`, catching `OverflowError` as well (`Infinity` survives `json.loads`); tests for both settings, mutation-proved
- [x] `ACC-MERM-84` **The two fence scanners agree, proved by running both** - the frontend posts diagrams by position and the server pairs them by position, so a rule in one and not the other hands a diagram the wrong picture
  - log: 2026-07-23T00:00:00Z @kj criterion added after two rounds where a rule landed in one scanner and not the other - the failure is silent and produces a confidently wrong document
  - log: 2026-07-23T00:00:00Z @kj held - `TestFenceScannerParity` extracts `mermaidBlocksFromSource` from `src/index.ts`, runs it under node, and compares block-for-block against `iter_mermaid_blocks` over twenty-three shapes, every one of which also has its expected count re-derived from marked. Mutation-proved in both directions - removing the in-list rule or the blockquote termination from the TypeScript side fails it
  - log: 2026-07-23T00:00:00Z @kj held again after the sixth round moved six rules into both scanners at once: a differential over 12,000 generated documents finds no shape they disagree on, including the indented bodies inside quoted blocks that exposed a double-counted dedent column
  - log: 2026-07-23T00:00:00Z @kj held through the seventh round (both adversarial lenses CLEAN): the one asymmetry with teeth was that Python `str.strip()` keeps a U+FEFF that JS `.trim()` drops, so ` ```mermaid<BOM> ` shifted a count; the info trim now uses the exact ECMAScript trim set (`_JS_TRIM`), byte-equivalent to marked over 5,000 BOM-injected documents, `bom_info` in the parity table

## Symbol glyph fonts `SYMB`

Cambria, the DOCX body face, has no glyph for a star, a box-drawing rule or most dingbats. A run that names no font leaves the choice to Word, which substitutes from whatever the reading machine has installed - so the same file can draw a solid star on one PC and a hollow box on the next. The export names a font on exactly those characters and leaves the rest of the text alone.

- [x] `ACC-SYMB-85` **A character the body face cannot draw names a font that can** - the decision belongs in the file, not in the reader's font list
  - log: 2026-08-25T00:00:00Z @kj criterion added with DEF-MARK-22; measured on a court filing carrying 31 star markers - every star run exported with no `w:rFonts` at all
  - log: 2026-08-25T00:00:00Z @kj held - test `test_symbols_the_body_face_lacks_name_a_font`; mutation-proved. On the reported document all 31 star runs now name `Segoe UI Symbol`
- [x] `ACC-SYMB-86` **A character the body face does draw keeps it** - naming a symbol font for `·` or U+2192 would switch typeface mid-sentence for nothing
  - log: 2026-08-25T00:00:00Z @kj criterion added; the arrow range starts at U+2194 because Cambria carries U+2190-2193
  - log: 2026-08-25T00:00:00Z @kj held - test `test_body_characters_keep_the_body_font`. The reported document's 46 middot runs stay in the body face
- [x] `ACC-SYMB-87` **Splitting a run to font it loses no text** - the pass cuts each run into per-font pieces, and a cut that drops a character is worse than the box it was fixing
  - log: 2026-08-25T00:00:00Z @kj criterion added; the same split already served the task checkboxes
  - log: 2026-08-25T00:00:00Z @kj held - tests `test_no_text_is_lost_splitting_the_runs` and `test_symbols_survive_inside_a_table_cell`
- [x] `ACC-SYMB-88` **The export works through the real UI, not only through the handlers** - a rendering fix is worth nothing if the command, the menu entry or the download is broken
  - log: 2026-08-25T00:00:00Z @kj criterion added with DEF-MARK-22/DEF-MARK-23; the Python suite calls the endpoints directly and cannot see any of that
  - log: 2026-08-25T00:00:00Z @kj held - galata spec `ui-tests/tests/export-fidelity.spec.ts` opens the document in Lab, exports from File > Export Markdown As > Microsoft Word (.docx), and reads the downloaded `word/document.xml` back. Proved live against the released build: it fails on the star assertion, passes against the fix
- [ ] `ACC-SYMB-89` **Accepted limit** - the font is named, not embedded; a machine without `Segoe UI Symbol` (a Mac, a bare Linux) substitutes as before
  - log: 2026-08-27T00:00:00Z @kj accepted limit recorded alongside the criteria it bounds

## Inline HTML fidelity `HTML`

Markdown files carry HTML, and a Jupyter one carries more than most - `<font color>` and `<span style>` are how a notebook cell colours its text. htmldocx reads a handful of tags and two CSS properties; everything else arrives in Word as unstyled text. The gap is closed by rewriting the HTML into the markup htmldocx does read, before conversion. The PDF rebuilds from that same intermediate DOCX, so it inherits every run property `format_run` reads - weight, slant, underline, strike, colour and the mark fill - in a table cell as much as in a body paragraph, and `process_paragraph` maps the paragraph's own alignment onto its reportlab style.

- [x] `ACC-HTML-90` **A styled span carries every property it declares, not just colour** - `font-weight`, `font-style` and `text-decoration` sit beside `color` in the same attribute and were the ones being dropped
  - log: 2026-08-25T00:00:00Z @kj criterion added with DEF-MARK-23; measured each property through the pipeline and found colour and background the only two that survived
  - log: 2026-08-25T00:00:00Z @kj held - tests `test_span_style_properties_become_run_formatting` and `test_colour_and_weight_in_one_span_both_survive`; mutation-proved
- [x] `ACC-HTML-91` **A semantic inline tag reaches Word as formatting** - `<mark>`, `<del>`, `<kbd>` and `<font color>` all have a Word equivalent and were all arriving plain
  - log: 2026-08-25T00:00:00Z @kj criteria added; `<font color>` is the notebook colouring idiom, so it matters more here than its deprecation suggests
  - log: 2026-08-25T00:00:00Z @kj held - tests `test_semantic_inline_tags_reach_word` and `test_font_colour_attribute_reaches_word`; mutation-proved
- [x] `ACC-HTML-92` **A `<div>` opens its own block** - with no handler its content joined whatever paragraph was already open, so two blocks ran together and one alignment overwrote the other
  - log: 2026-08-25T00:00:00Z @kj criterion added after measuring `<p align="center">A</p><div align="right">B</div>` arrive as one right-aligned paragraph holding both
  - log: 2026-08-25T00:00:00Z @kj held - test `test_aligned_div_is_its_own_centred_paragraph` asserts the block is centred and has not swallowed the paragraph after it
- [ ] `ACC-HTML-93` **Accepted limit** - PDF alignment reaches a body paragraph and a heading only. `process_paragraph` maps `para.alignment` onto those two styles; a list item, a blockquote and a table cell keep the indent their own style sets, so a centred `<div>` inside one draws at that style's left edge. Registered as `DEF-MARK-25`
  - log: 2026-08-27T00:00:00Z @kj accepted limit recorded alongside the criteria it bounds
- [ ] `ACC-HTML-94` **Accepted limit** - `font-size`, `font-family` and `<small>` are still dropped; every property closed above had an equivalent tag to be rewritten into and these have none, so they need a marker and a run pass of their own. Registered as `DEF-MARK-24`
  - log: 2026-08-27T00:00:00Z @kj accepted limit recorded alongside the criteria it bounds
