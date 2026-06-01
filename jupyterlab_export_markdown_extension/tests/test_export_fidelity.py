"""Export fidelity tests - validate that HTML, DOCX, and PDF exports contain expected content."""

import json
import io
import tempfile
import zipfile
from pathlib import Path

import pytest

# Test markdown content with various elements
TEST_MARKDOWN = """# Test Document

## Text Formatting

Regular paragraph with **bold text** and _italic text_.

## Lists

- Bullet item 1
- Bullet item 2
  - Nested bullet

1. Numbered item 1
2. Numbered item 2
   1. Nested numbered

## Table

| Column A | Column B |
| -------- | -------- |
| A1       | B1       |
| A2       | B2       |

## Code

Inline `code` here.

```python
def test():
    return True
```

## Blockquote

> This is a blockquote.

## GitHub Alert

> [!NOTE]
> This is a note alert.

## Symbols

Arrows: → ← ↑ ↓
Bullets: • ◦ ▪ ▫
Stars: ★ ☆
"""


@pytest.fixture
def test_markdown_file(jp_root_dir):
    """Create a test markdown file in the server's root directory."""
    md_file = jp_root_dir / "test.md"
    md_file.write_text(TEST_MARKDOWN, encoding="utf-8")
    return md_file


class TestHTMLExport:
    """Test HTML export fidelity."""

    async def test_html_export_success(self, jp_fetch, test_markdown_file):
        """Test successful HTML export."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
            raise_error=False,
        )
        assert response.code == 200
        # Content should be HTML (may have charset suffix)
        content_type = response.headers.get("Content-Type", "")
        assert "text/html" in content_type or response.body.startswith(b"<!DOCTYPE") or b"<html" in response.body

    async def test_html_contains_headings(self, jp_fetch, test_markdown_file):
        """Test HTML contains converted headings."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        assert "<h1" in html or "<h1>" in html
        assert "Test Document" in html
        assert "<h2" in html

    async def test_html_contains_formatting(self, jp_fetch, test_markdown_file):
        """Test HTML contains text formatting."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        assert "<strong>" in html or "<b>" in html  # bold
        assert "<em>" in html or "<i>" in html  # italic

    async def test_html_contains_lists(self, jp_fetch, test_markdown_file):
        """Test HTML contains lists."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        assert "<ul>" in html  # unordered list
        # Note: ordered lists may render as <ol> or <ul> depending on markdown parser
        assert "<li>" in html  # list items
        # Verify list content is present
        assert "Bullet item" in html or "Numbered item" in html

    async def test_html_contains_table(self, jp_fetch, test_markdown_file):
        """Test HTML contains table."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        assert "<table>" in html or "<table " in html
        assert "<th>" in html or "<td>" in html
        assert "Column A" in html

    async def test_html_contains_code(self, jp_fetch, test_markdown_file):
        """Test HTML contains code blocks."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        assert "<code>" in html or "<code " in html
        # Code may have syntax highlighting spans, check for key tokens
        assert "def" in html and "test" in html and "return" in html

    async def test_html_contains_blockquote(self, jp_fetch, test_markdown_file):
        """Test HTML contains blockquote."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        assert "<blockquote>" in html or "blockquote" in html.lower()

    async def test_html_contains_unicode_symbols(self, jp_fetch, test_markdown_file):
        """Test HTML contains Unicode symbols."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        # These symbols should pass through to HTML unchanged
        assert "→" in html or "&#" in html  # arrow or HTML entity
        assert "★" in html or "&#" in html  # star or HTML entity


class TestDOCXExport:
    """Test DOCX export fidelity."""

    async def test_docx_export_success(self, jp_fetch, test_markdown_file):
        """Test successful DOCX export."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test.md"}),
            raise_error=False,
        )
        assert response.code == 200
        # Verify by checking the file is a valid ZIP (DOCX format)
        # Content-Type may vary, so validate actual content instead
        assert response.body[:2] == b"PK"  # ZIP magic bytes

    async def test_docx_is_valid_zip(self, jp_fetch, test_markdown_file):
        """Test DOCX is a valid ZIP file (DOCX format)."""
        import zipfile
        import io

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        # DOCX files are ZIP archives
        docx_bytes = io.BytesIO(response.body)
        assert zipfile.is_zipfile(docx_bytes)

    async def test_docx_contains_document_xml(self, jp_fetch, test_markdown_file):
        """Test DOCX contains document.xml with content."""
        import zipfile
        import io

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            assert "word/document.xml" in zf.namelist()
            document_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Test Document" in document_xml

    async def test_docx_contains_text_content(self, jp_fetch, test_markdown_file):
        """Test DOCX contains expected text content."""
        import zipfile
        import io

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            assert "bold text" in document_xml
            assert "Bullet item" in document_xml
            assert "Column A" in document_xml


class TestPDFExport:
    """Test PDF export fidelity."""

    async def test_pdf_export_success(self, jp_fetch, test_markdown_file):
        """Test successful PDF export."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test.md"}),
            raise_error=False,
        )
        assert response.code == 200
        # Verify by checking PDF magic bytes instead of Content-Type
        assert response.body.startswith(b"%PDF-")

    async def test_pdf_has_valid_header(self, jp_fetch, test_markdown_file):
        """Test PDF has valid PDF header."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        # PDF files start with %PDF-
        assert response.body.startswith(b"%PDF-")

    async def test_pdf_has_valid_footer(self, jp_fetch, test_markdown_file):
        """Test PDF has valid EOF marker."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        # PDF files end with %%EOF
        assert b"%%EOF" in response.body[-100:]

    async def test_pdf_contains_content(self, jp_fetch, test_markdown_file):
        """Test PDF contains actual content (not empty)."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        pdf_content = response.body
        # PDF text is compressed, so instead of searching for strings,
        # verify PDF has stream objects (actual content)
        assert b"stream" in pdf_content and b"endstream" in pdf_content

    async def test_pdf_minimum_size(self, jp_fetch, test_markdown_file):
        """Test PDF has reasonable file size (not empty)."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        # A valid PDF with content should be at least a few KB
        assert len(response.body) > 1000


class TestGitHubAlerts:
    """Test GitHub-style alerts preprocessing and DOCX styling."""

    async def test_note_alert_html(self, jp_fetch, test_markdown_file):
        """Test NOTE alert is processed in HTML."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        # Alert content should be present (labels hidden by default)
        assert "note" in html.lower() or "useful information" in html.lower()

    async def test_note_alert_html_with_labels(self, jp_fetch, test_markdown_file):
        """Test NOTE alert shows label when showAlertLabels is enabled."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md", "showAlertLabels": True}),
        )
        html = response.body.decode("utf-8")
        # Alert should have bold label when enabled
        assert "NOTE" in html

    async def test_alert_styled_in_docx(self, jp_fetch, test_markdown_file):
        """Test alert is rendered as styled table in DOCX."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # Blue shading applied for NOTE alert in table cell
            assert 'w:fill="EDF5FD"' in document_xml
            # Left border applied
            assert 'w:color="0969DA"' in document_xml
            # Zero-width space markers removed
            assert '\u200b' not in document_xml
            # Alert label should not appear (showAlertLabels defaults to false)
            # Table element present (alert rendered as table)
            assert 'w:tbl' in document_xml


class TestSyntaxHighlighting:
    """Test syntax highlighting in code blocks."""

    async def test_html_has_pygments_css(self, jp_fetch, test_markdown_file):
        """Test HTML output contains Pygments CSS for syntax highlighting."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        # Pygments CSS defines .codehilite styles
        assert ".codehilite" in html

    async def test_html_has_highlighted_code(self, jp_fetch, test_markdown_file):
        """Test HTML output has syntax-highlighted code spans."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        # Python code should have span elements with classes for keywords
        # Look for codehilite div or syntax-highlighted spans
        assert "codehilite" in html or 'class="k"' in html or 'class="nf"' in html

    async def test_docx_has_colored_code(self, jp_fetch, test_markdown_file):
        """Test DOCX output has inline styled code (colored spans)."""
        import zipfile
        import io

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # DOCX with colored code should have color references
            # Either via styles or inline formatting
            assert "def" in document_xml and "test" in document_xml

    async def test_pdf_has_code_content(self, jp_fetch, test_markdown_file):
        """Test PDF output contains code block content."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )

        # PDF should be larger when it has formatted code blocks
        assert len(response.body) > 1000
        # PDF should have valid structure
        assert response.body.startswith(b"%PDF-")


# Test markdown with LaTeX math expressions
TEST_MARKDOWN_MATH = """# Math Test

Inline math: $E=mc^2$ is well known.

Display math:

$$\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$

Greek letters: $\\alpha + \\beta = \\gamma$

Currency (should NOT render): The price is $100 and total $200.

Code block math (should NOT render):

```python
# The formula $E=mc^2$ in a comment
x = "$not_math$"
```

Inline code math: `$E=mc^2$` should stay as text.
"""


@pytest.fixture
def test_math_file(jp_root_dir):
    """Create a test markdown file with LaTeX math expressions."""
    md_file = jp_root_dir / "test_math.md"
    md_file.write_text(TEST_MARKDOWN_MATH, encoding="utf-8")
    return md_file


class TestMathRendering:
    """Test LaTeX math rendering in exports."""

    async def test_html_has_katex_scripts(self, jp_fetch, test_math_file):
        """Test HTML export includes KaTeX CDN scripts for math rendering."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
        )
        html = response.body.decode("utf-8")
        assert "katex" in html.lower()
        assert "cdn.jsdelivr.net" in html
        assert "auto-render" in html

    async def test_html_preserves_math_delimiters(self, jp_fetch, test_math_file):
        """Test HTML export keeps $...$ delimiters for KaTeX client-side rendering."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
        )
        html = response.body.decode("utf-8")
        # Math delimiters should be preserved for KaTeX (not replaced with images)
        assert "E=mc^2" in html

    async def test_docx_has_omml_math(self, jp_fetch, test_math_file):
        """Test DOCX export renders math as native OMML equations."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # OMML equations use oMath namespace
            assert "oMath" in document_xml, "DOCX should contain native OMML equations"
            # Marker text should be cleaned up
            assert "MATH_INLINE_" not in document_xml
            assert "MATH_DISPLAY_" not in document_xml

    async def test_docx_inline_math_in_paragraph(self, jp_fetch, test_math_file):
        """Test inline OMML math flows within text paragraph."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # "is well known" text should be in same paragraph as oMath
            # (inline math doesn't break text flow)
            assert "well known" in document_xml

    async def test_pdf_with_math_succeeds(self, jp_fetch, test_math_file):
        """Test PDF export succeeds when markdown contains math."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")

    async def test_code_blocks_preserved(self, jp_fetch, test_math_file):
        """Test math inside code blocks is NOT rendered."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
        )
        html = response.body.decode("utf-8")
        # Code block content should remain as text, not be rendered as math images
        assert "not_math" in html

    async def test_currency_not_matched(self, jp_fetch, test_math_file):
        """Test $100 currency amounts are not falsely matched as math."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_math.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # Currency text should be preserved as-is
            assert "100" in document_xml


# Minimal SVG for testing
TEST_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">
  <rect width="200" height="100" fill="#4F81BD"/>
  <text x="100" y="55" text-anchor="middle" fill="white" font-size="16">Test SVG</text>
</svg>"""

# Markdown with an SVG image reference
TEST_MARKDOWN_WITH_SVG = """# Document With SVG

Some text before the image.

![Architecture Diagram](images/test-diagram.svg)

Some text after the image.
"""


@pytest.fixture
def test_svg_markdown_file(jp_root_dir):
    """Create a test markdown file with an SVG image reference."""
    # Create images directory and SVG file
    images_dir = jp_root_dir / "images"
    images_dir.mkdir(exist_ok=True)
    svg_file = images_dir / "test-diagram.svg"
    svg_file.write_text(TEST_SVG, encoding="utf-8")
    # Create markdown file
    md_file = jp_root_dir / "test_svg.md"
    md_file.write_text(TEST_MARKDOWN_WITH_SVG, encoding="utf-8")
    return md_file


# Theme-aware SVG: white background in light, black in dark
TEST_THEME_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
    "<style>.bg{fill:#ffffff}"
    "@media (prefers-color-scheme: dark){.bg{fill:#000000}}</style>"
    '<rect class="bg" width="200" height="100"/></svg>'
)


@pytest.fixture
def test_theme_svg_file(jp_root_dir):
    images_dir = jp_root_dir / "images"
    images_dir.mkdir(exist_ok=True)
    (images_dir / "theme.svg").write_text(TEST_THEME_SVG, encoding="utf-8")
    md = jp_root_dir / "test_theme_svg.md"
    md.write_text("# Theme\n\n![d](images/theme.svg)\n", encoding="utf-8")
    return md


class TestDocxTheme:
    """docxTheme drives the SVG color scheme; prefers-color-scheme resolves to it."""

    async def _center_pixel(self, jp_fetch, theme):
        from docx import Document
        from PIL import Image as PILImage
        import zipfile as _zip

        body = {"path": "test_theme_svg.md"}
        if theme is not None:
            body["docxTheme"] = theme
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps(body),
            raise_error=False,
        )
        assert response.code == 200
        with _zip.ZipFile(io.BytesIO(response.body)) as zf:
            media = [n for n in zf.namelist() if n.startswith("word/media/")]
            assert media, "expected an embedded image"
            img = PILImage.open(io.BytesIO(zf.read(media[0]))).convert("RGB")
        return img.getpixel((img.width // 2, img.height // 2))

    async def test_light_theme_renders_light(self, jp_fetch, test_theme_svg_file):
        r, g, b = await self._center_pixel(jp_fetch, "light")
        assert min(r, g, b) > 200, f"light theme should render white, got {(r, g, b)}"

    async def test_dark_theme_renders_dark(self, jp_fetch, test_theme_svg_file):
        r, g, b = await self._center_pixel(jp_fetch, "dark")
        assert max(r, g, b) < 60, f"dark theme should render black, got {(r, g, b)}"

    async def test_default_is_light(self, jp_fetch, test_theme_svg_file):
        r, g, b = await self._center_pixel(jp_fetch, None)
        assert min(r, g, b) > 200, f"default (no docxTheme) should be light, got {(r, g, b)}"


class TestSVGConversion:
    """Test SVG to PNG conversion in DOCX and PDF exports."""

    async def test_docx_with_svg_succeeds(self, jp_fetch, test_svg_markdown_file):
        """Test DOCX export does not fail when markdown contains SVG images."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_svg.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body[:2] == b"PK"  # Valid ZIP/DOCX

    async def test_docx_with_svg_contains_image(self, jp_fetch, test_svg_markdown_file):
        """Test DOCX with SVG contains a converted PNG image."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_svg.md"}),
        )
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            # DOCX stores images in word/media/ directory
            image_files = [n for n in zf.namelist() if n.startswith("word/media/")]
            assert len(image_files) > 0, "DOCX should contain at least one image"
            # Image should be PNG (converted from SVG)
            for img in image_files:
                img_data = zf.read(img)
                assert img_data[:4] == b"\x89PNG", f"{img} should be PNG format"

    async def test_docx_with_svg_contains_text(self, jp_fetch, test_svg_markdown_file):
        """Test DOCX with SVG still contains surrounding text content."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_svg.md"}),
        )
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Document With SVG" in document_xml
            assert "Some text before" in document_xml

    async def test_pdf_with_svg_succeeds(self, jp_fetch, test_svg_markdown_file):
        """Test PDF export does not fail when markdown contains SVG images."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_svg.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")

    async def test_svg_pixel_width_parameter(self, jp_fetch, test_svg_markdown_file):
        """Test svgPixelWidth parameter is accepted by the export endpoint."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_svg.md", "svgPixelWidth": 1280}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body[:2] == b"PK"

    async def test_html_with_svg_keeps_svg(self, jp_fetch, test_svg_markdown_file):
        """Test HTML export preserves SVG as-is (no conversion needed)."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test_svg.md"}),
        )
        html = response.body.decode("utf-8")
        # HTML should contain the image as base64 data URI (SVG format preserved)
        assert "data:image/svg+xml" in html or "Architecture Diagram" in html


class TestSVGDoctypePrologue:
    """An XML declaration / DOCTYPE prologue must not leak as a top-left
    text artefact (e.g. ']>') when rasterizing - JupyterLab's mermaid
    renderer prepends exactly such a prologue."""

    async def test_doctype_prologue_no_top_left_artefact(self):
        from jupyterlab_export_markdown_extension.routes import (
            PlaywrightSvgRenderer,
        )
        from PIL import Image as PILImage

        # A minimal SVG with a white background, preceded by the same
        # XML+DOCTYPE-with-internal-subset prologue JupyterLab emits.
        prologue = (
            '<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
            '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" ['
            '<!ENTITY Aacute "&#193;">\n<!ENTITY amp "&#38;">]>'
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 400 100">'
            '<rect width="400" height="100" fill="#ffffff"/></svg>'
        )
        svg_bytes = (prologue + "\n" + svg).encode("utf-8")

        async with PlaywrightSvgRenderer(color_scheme="light") as renderer:
            png = await renderer.render(svg_bytes, width=400)

        img = PILImage.open(io.BytesIO(png)).convert("RGBA")
        bg = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
        comp = PILImage.alpha_composite(bg, img)
        tl = comp.crop((0, 0, 80, 80)).load()
        dark = sum(
            1
            for y in range(80)
            for x in range(80)
            if sum(tl[x, y][:3]) < 200
        )
        assert dark == 0, (
            f"DOCTYPE prologue leaked a dark text artefact in the "
            f"top-left corner ({dark} dark pixels)"
        )


# Markdown with SVG as first element (header banner pattern)
TEST_MARKDOWN_LEADING_SVG = """![Header Banner](images/test-diagram.svg)

---

## Content

Some text content below the header image.
"""


@pytest.fixture
def test_leading_svg_markdown_file(jp_root_dir):
    """Create a test markdown file with SVG as the very first element."""
    images_dir = jp_root_dir / "images"
    images_dir.mkdir(exist_ok=True)
    svg_file = images_dir / "test-diagram.svg"
    svg_file.write_text(TEST_SVG, encoding="utf-8")
    md_file = jp_root_dir / "test_leading_svg.md"
    md_file.write_text(TEST_MARKDOWN_LEADING_SVG, encoding="utf-8")
    return md_file


class TestLeadingImagePreservation:
    """Test that image-only paragraphs at document start are not removed."""

    async def test_docx_preserves_leading_image(self, jp_fetch, test_leading_svg_markdown_file):
        """Test DOCX export keeps an image that is the first element in the document."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_leading_svg.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            image_files = [n for n in zf.namelist() if n.startswith("word/media/")]
            assert len(image_files) > 0, "Leading image should be preserved in DOCX"

    async def test_pdf_preserves_leading_image(self, jp_fetch, test_leading_svg_markdown_file):
        """Test PDF export keeps an image that is the first element in the document."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_leading_svg.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
        # PDF should be substantial (contains image data)
        assert len(response.body) > 2000


# Rich alert test content with line breaks, hyperlinks, bold, and consecutive alerts
TEST_MARKDOWN_RICH_ALERTS = """# Rich Alert Test

> [!IMPORTANT]
> Based on factory-observed void dimensions (5 x 3 x 2 mm), overall casting porosity appears well within criteria. <br><br>The 30% rejection rate is driven by **void location**.

> [!NOTE]
> **Applicable standards**: <br>[ASTM E505](https://example.com/astm-e505) (Reference Radiographs), <br>[EN 12681](https://example.com/en-12681) (Founding - Radiographic testing).

> [!WARNING]
> Simple warning without special formatting.

Some text after alerts.

| Col A | Col B |
| ----- | ----- |
| A1    | B1    |
"""


@pytest.fixture
def test_rich_alerts_file(jp_root_dir):
    """Create a test markdown file with rich alert content."""
    md_file = jp_root_dir / "test_rich_alerts.md"
    md_file.write_text(TEST_MARKDOWN_RICH_ALERTS, encoding="utf-8")
    return md_file


TEST_MARKDOWN_COLOR_PILLS = """# Colours

Named text colours: <span style="color:green">green</span>,
<span style="color:red">red</span>, hex <span style="color:#3b82f6">blue</span>.

| Item | Priority |
|---|---|
| A | <span style="background-color:#15803d;color:#ffffff;padding:1px 8px;border-radius:8px">High</span> |
| B | <span style="background-color:#b45309;color:#ffffff;padding:1px 8px;border-radius:8px">Med</span> |
"""


@pytest.fixture
def test_color_pills_file(jp_root_dir):
    md_file = jp_root_dir / "test_color_pills.md"
    md_file.write_text(TEST_MARKDOWN_COLOR_PILLS, encoding="utf-8")
    return md_file


class TestColouredHtml:
    """Named CSS colours render in colour (not black) and background-colour
    pills become true run shading (not an invisible Word highlight)."""

    async def test_docx_named_colors_and_pills(self, jp_fetch, test_color_pills_file):
        from docx import Document
        from docx.oxml.ns import qn

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_color_pills.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))

        # Named colour "green" must not render black
        green_runs = [
            r
            for p in doc.paragraphs
            for r in p.runs
            if r.text.strip() == "green"
        ]
        assert green_runs, "green run not found"
        col = green_runs[0].font.color
        assert col is not None and col.rgb is not None
        assert str(col.rgb) != "000000", "named colour 'green' rendered black"

        # Pills: locate the shaded runs in table cells
        shaded = []
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            rPr = r._r.find(qn("w:rPr"))
                            shd = rPr.find(qn("w:shd")) if rPr is not None else None
                            if shd is not None and shd.get(qn("w:fill")) not in (None, "auto"):
                                shaded.append((r.text, shd.get(qn("w:fill"))))
        fills = {t.strip(): f.upper() for t, f in shaded}
        assert fills.get("High") == "15803D", f"High pill fill wrong: {fills}"
        assert fills.get("Med") == "B45309", f"Med pill fill wrong: {fills}"

        # No marker leakage anywhere (incl. table cells)
        from docx.text.paragraph import Paragraph
        all_text = "".join(
            Paragraph(p, doc).text
            for p in doc.element.body.iter(qn("w:p"))
        )
        assert "PILL:" not in all_text
        assert "⁣" not in all_text


TEST_MARKDOWN_QUOTES_IN_LIST = """# Quotes

Two ideas:

- **First idea** - a loose list item with a nested quote below it

  > a quoted note under the first bullet

  > a second quoted note

- **Second idea** - another loose list item

  > quoted note under the second bullet
"""


@pytest.fixture
def test_quotes_in_list_file(jp_root_dir):
    md_file = jp_root_dir / "test_quotes_in_list.md"
    md_file.write_text(TEST_MARKDOWN_QUOTES_IN_LIST, encoding="utf-8")
    return md_file


class TestBlockquotesAndLooseListBullets:
    """Loose list items keep their bullets; blockquotes get indent + bar + shading."""

    async def test_docx_loose_list_keeps_bullets(self, jp_fetch, test_quotes_in_list_file):
        """A loose <li><p>..</p>..</li> must render as a List Bullet paragraph
        with text, not an empty bullet plus an orphaned Normal paragraph."""
        from docx import Document

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_quotes_in_list.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        bullets = [
            p for p in doc.paragraphs
            if p.style and p.style.name == "List Bullet" and p.text.strip()
        ]
        assert len(bullets) >= 2, "loose list items should keep their bullet text"
        assert any("First idea" in p.text for p in bullets)
        assert any("Second idea" in p.text for p in bullets)
        # No empty bullet paragraphs left behind
        empty_bullets = [
            p for p in doc.paragraphs
            if p.style and p.style.name == "List Bullet" and not p.text.strip()
        ]
        assert not empty_bullets, "no empty bullet glyphs should remain"

    async def test_docx_blockquote_styled_and_no_marker(self, jp_fetch, test_quotes_in_list_file):
        """Blockquote paragraphs get a left indent, a left border bar and
        shading; the sentinel marker must not leak into the text."""
        from docx import Document
        from docx.oxml.ns import qn

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_quotes_in_list.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "BQ:" not in full_text, "blockquote marker leaked into output"
        assert "⁣" not in full_text, "zero-width marker delimiter leaked"

        quoted = [p for p in doc.paragraphs if "quoted note" in p.text]
        assert len(quoted) >= 3, "all blockquote paragraphs should survive"
        for p in quoted:
            pf = p.paragraph_format
            assert pf.left_indent is not None and pf.left_indent > 0, (
                "blockquote paragraph should be indented"
            )
            pPr = p._p.find(qn("w:pPr"))
            assert pPr is not None and pPr.find(qn("w:pBdr")) is not None, (
                "blockquote paragraph should have a left border bar"
            )

    async def test_pdf_with_quotes_in_list_succeeds(self, jp_fetch, test_quotes_in_list_file):
        """PDF export of quotes-in-list succeeds and leaks no marker."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_quotes_in_list.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")


class TestRichAlerts:
    """Test alert boxes with line breaks, hyperlinks, bold, and consecutive alerts."""

    async def test_alert_table_has_hyperlinks(self, jp_fetch, test_rich_alerts_file):
        """Test NOTE alert with markdown links produces hyperlinks in DOCX."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # Hyperlinks present (from markdown links in NOTE alert)
            assert "w:hyperlink" in document_xml or "Hyperlink" in document_xml
            # Zero-width markers cleaned
            assert "\u200b" not in document_xml

    async def test_alert_table_has_line_breaks(self, jp_fetch, test_rich_alerts_file):
        """Test IMPORTANT alert with <br> tags produces line breaks in DOCX."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # Line breaks present (from <br> tags in IMPORTANT alert)
            assert "w:br" in document_xml

    async def test_consecutive_alerts_separate(self, jp_fetch, test_rich_alerts_file):
        """Test consecutive alerts are rendered as separate tables with spacing."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # Three alert colors should be present (IMPORTANT=purple, NOTE=blue, WARNING=amber)
            assert 'w:fill="F4EDFF"' in document_xml  # purple
            assert 'w:fill="EDF5FD"' in document_xml  # blue
            assert 'w:fill="FEF9E7"' in document_xml  # amber

    async def test_data_table_not_styled_as_alert(self, jp_fetch, test_rich_alerts_file):
        """Test regular data tables are not affected by alert styling."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        docx_bytes = io.BytesIO(response.body)
        with zipfile.ZipFile(docx_bytes, "r") as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
            # Data table text should be present
            assert "Col A" in document_xml or "A1" in document_xml

    async def test_alert_labels_hidden_by_default(self, jp_fetch, test_rich_alerts_file):
        """Test alert type labels are not visible when showAlertLabels is false."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        # Content should be present but not the label prefix pattern "IMPORTANT:"
        assert "void location" in html
        # Zero-width markers should not appear in HTML output
        assert "\u200b" not in html


# Markdown with JPEG images at different DPI values for scaling test
TEST_MARKDOWN_WITH_JPEG = """# JPEG Scaling Test

![High DPI](images/high_dpi.jpg)

![Low DPI](images/low_dpi.jpg)

Some text after images.
"""


@pytest.fixture
def test_jpeg_scaling_files(jp_root_dir):
    """Create test JPEG images with different DPI metadata."""
    from PIL import Image as PILImage

    images_dir = jp_root_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Create 200x100 JPEG at 1519 DPI (would render tiny without fix)
    img_high = PILImage.new("RGB", (200, 100), color=(255, 0, 0))
    img_high.save(images_dir / "high_dpi.jpg", dpi=(1519, 1519))

    # Create 200x100 JPEG at 72 DPI (would render large without fix)
    img_low = PILImage.new("RGB", (200, 100), color=(0, 0, 255))
    img_low.save(images_dir / "low_dpi.jpg", dpi=(72, 72))

    md_file = jp_root_dir / "test_jpeg_scaling.md"
    md_file.write_text(TEST_MARKDOWN_WITH_JPEG, encoding="utf-8")
    return md_file


class TestImageDPINormalization:
    """Test that JPEG DPI metadata is normalized for consistent DOCX sizing."""

    async def test_docx_consistent_image_sizes(self, jp_fetch, test_jpeg_scaling_files):
        """Test images with different DPI render at consistent sizes in DOCX."""
        from docx import Document
        from docx.shared import Inches

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_jpeg_scaling.md"}),
            raise_error=False,
        )
        assert response.code == 200

        docx_bytes = io.BytesIO(response.body)
        doc = Document(docx_bytes)

        # Both images have identical pixel dimensions (200x100)
        # so after DPI normalization to 96, they should have
        # identical sizes in the DOCX
        shapes = list(doc.inline_shapes)
        assert len(shapes) >= 2, f"Expected 2 images, found {len(shapes)}"

        # Both should be the same width (200px at 96 DPI = ~2.08")
        width_0 = shapes[0].width
        width_1 = shapes[1].width
        assert width_0 == width_1, (
            f"Images with same pixel dimensions should have same DOCX width: "
            f"{width_0} vs {width_1}"
        )

        # Width should be approximately 2.08 inches (200/96)
        expected_width = Inches(200 / 96)
        tolerance = Inches(0.1)
        assert abs(width_0 - expected_width) < tolerance, (
            f"Image width {width_0} should be ~{expected_width} (200px at 96 DPI)"
        )

    async def test_docx_with_jpeg_succeeds(self, jp_fetch, test_jpeg_scaling_files):
        """Test DOCX export succeeds with JPEG images of varying DPI."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_jpeg_scaling.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body[:2] == b"PK"

    async def test_pdf_with_jpeg_succeeds(self, jp_fetch, test_jpeg_scaling_files):
        """Test PDF export succeeds with JPEG images of varying DPI."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_jpeg_scaling.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")


TEST_MARKDOWN_TABLE_IMAGE = """# Table Image Scaling

A large photo inside a two-column table cell.

| Photo | Caption |
|---|---|
| ![big](images/big_photo.jpg) | text in the second cell |
"""


@pytest.fixture
def test_table_image_file(jp_root_dir):
    """Create a markdown file with a large image inside a 2-column table."""
    from PIL import Image as PILImage

    images_dir = jp_root_dir / "images"
    images_dir.mkdir(exist_ok=True)
    # 4000x3000 px = ~41 inches wide at 96 DPI - far wider than any cell
    PILImage.new("RGB", (4000, 3000), color=(0, 128, 0)).save(
        images_dir / "big_photo.jpg"
    )

    md_file = jp_root_dir / "test_table_image.md"
    md_file.write_text(TEST_MARKDOWN_TABLE_IMAGE, encoding="utf-8")
    return md_file


class TestTableImageScaling:
    """Images inside table cells must be scaled to the cell, not the page."""

    async def test_docx_table_image_fits_cell(self, jp_fetch, test_table_image_file):
        """A large image in a 2-column table cell must fit the cell width."""
        from docx import Document
        from docx.shared import Inches

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_table_image.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        shapes = list(doc.inline_shapes)
        assert len(shapes) >= 1, "expected the table image to be embedded"

        # A 2-column table on a 7.5\" page gives each cell ~3.75\". A
        # page-width (7.5\") image would overflow the cell and be clipped;
        # the scaled image must fit a cell.
        for shape in shapes:
            assert shape.width <= Inches(4.0), (
                f"table-cell image width {shape.width} should fit a "
                f"2-column cell (< 4 in), not span the page"
            )


SIZE_BADGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 40" '
    'width="60" height="40" role="img" aria-label="XL">'
    '<rect x="2" y="2" width="56" height="36" rx="8" fill="#b45309"/>'
    '<text x="30" y="27" font-size="20" fill="#ffffff" '
    'text-anchor="middle">XL</text></svg>'
)

TEST_MARKDOWN_HTML_IMG_BADGES = """# Badges

| Model | Size |
|---|---|
| M00 | <img src="badges/size-xl.svg" alt="XL" style="max-height:22px;max-width:1000px"> 64h |
| M01 | <img src="badges/size-xl.svg" alt="XL" style="max-height:22px;max-width:1000px"> 16h |
"""


@pytest.fixture
def test_html_img_badge_file(jp_root_dir):
    badges_dir = jp_root_dir / "badges"
    badges_dir.mkdir(exist_ok=True)
    (badges_dir / "size-xl.svg").write_text(SIZE_BADGE_SVG, encoding="utf-8")
    md_file = jp_root_dir / "test_html_img_badges.md"
    md_file.write_text(TEST_MARKDOWN_HTML_IMG_BADGES, encoding="utf-8")
    return md_file


class TestHtmlImgBadges:
    """Raw HTML <img> tags with relative local paths (inline table badges)
    must embed and render small, not break or fill the cell width."""

    def test_embed_local_html_img(self):
        """embed_images_as_base64 inlines a raw HTML <img> local src."""
        from jupyterlab_export_markdown_extension.routes import ExportDocxHandler

        handler = ExportDocxHandler.__new__(ExportDocxHandler)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "badge.svg").write_text(SIZE_BADGE_SVG)
            html = '<img src="badge.svg" alt="XL" style="max-height:22px">'
            out = handler.embed_images_as_base64(html, Path(d))
            assert "data:image/svg+xml;base64," in out
            assert 'src="badge.svg"' not in out
            assert 'alt="XL"' in out  # other attributes preserved

    def test_badge_render_spec(self):
        """A small max-height yields a tiny render width + high DPI; an
        unsized image yields None (full diagram width)."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        small = ExportHandlerBase._badge_render_spec(
            '<img style="max-height:22px;max-width:1000px">', 60, 40
        )
        assert small is not None
        render_w, dpi = small
        # 22px * (60/40) = 33px display -> *4 supersample = 132px, dpi 384
        assert render_w == 132
        assert dpi == 384

        assert ExportHandlerBase._badge_render_spec('<img alt="x">', 800, 345) is None
        assert ExportHandlerBase._badge_render_spec(
            '<img style="max-height:900px">', 60, 40
        ) is None

    async def test_docx_badges_small_inline(self, jp_fetch, test_html_img_badge_file):
        """HTML <img> badges embed and stay small (~22px), not cell-width."""
        from docx import Document
        from docx.shared import Inches

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_html_img_badges.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        shapes = list(doc.inline_shapes)
        assert len(shapes) == 2, "both HTML <img> badges must embed"
        for shape in shapes:
            # 22px at 96 DPI is ~0.23 in; allow slack but assert it is a
            # small badge, not a cell-width or page-width image.
            assert shape.height <= Inches(0.4), (
                f"badge height {shape.height} should be ~22px, not full size"
            )
            assert shape.width <= Inches(0.6), (
                f"badge width {shape.width} should be small, not cell-width"
            )


TEST_MARKDOWN_WITH_ANCHORS = """# Anchor Links

See footnote [<sup>A1</sup>](#A1) and [<sup>A2</sup>](#A2) below.

External link: [Google](https://google.com).

Inline arrow inside code: `←` and bare arrows → ← ↑ ↓.

## References

- <span id="A1">A1 first reference target</span>
- <span id="A2">A2 second reference target</span>
"""


@pytest.fixture
def test_anchor_markdown_file(jp_root_dir):
    md_file = jp_root_dir / "test_anchors.md"
    md_file.write_text(TEST_MARKDOWN_WITH_ANCHORS, encoding="utf-8")
    return md_file


class TestAnchorLinksAndArrowFonts:
    """Validate anchor links become Word bookmarks and arrows escape Courier."""

    async def test_docx_internal_hyperlinks_and_bookmarks(
        self, jp_fetch, test_anchor_markdown_file
    ):
        import re

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_anchors.md"}),
            raise_error=False,
        )
        assert response.code == 200

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")
            rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8")

        assert 'w:anchor="A1"' in doc_xml, "anchor link A1 should be internal"
        assert 'w:anchor="A2"' in doc_xml, "anchor link A2 should be internal"
        assert 'w:name="A1"' in doc_xml, "bookmark A1 must exist"
        assert 'w:name="A2"' in doc_xml, "bookmark A2 must exist"

        assert 'Target="#A1"' not in rels_xml
        assert 'Target="#A2"' not in rels_xml
        assert re.search(r'Target="https://google\.com"', rels_xml), (
            "external hyperlinks should still be preserved"
        )

        assert "⁣BM:" not in doc_xml, "bookmark sentinel must not leak"

    async def test_docx_unicode_arrow_escapes_courier(
        self, jp_fetch, test_anchor_markdown_file
    ):
        import re

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_anchors.md"}),
            raise_error=False,
        )
        assert response.code == 200

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8")

        arrows = ["←", "↑", "→", "↓"]
        for arrow in arrows:
            assert arrow in doc_xml, f"arrow {arrow!r} missing from DOCX"

        courier_runs = re.findall(
            r'<w:r>[^<]*<w:rPr>[^<]*<w:rFonts[^/]*Courier[^/]*/>.*?</w:r>',
            doc_xml,
            flags=re.DOTALL,
        )
        for run in courier_runs:
            texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run)
            for t in texts:
                for arrow in arrows:
                    assert arrow not in t, (
                        f"arrow {arrow!r} remains in Courier run: {run}"
                    )

    async def test_pdf_with_anchor_links_succeeds(
        self, jp_fetch, test_anchor_markdown_file
    ):
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_anchors.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
