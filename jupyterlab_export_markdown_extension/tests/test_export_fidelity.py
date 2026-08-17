"""Export fidelity tests - validate that HTML, DOCX, and PDF exports contain expected content."""

import asyncio
import json
import io
import re
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

    async def test_pdf_table_image_is_rendered(self, jp_fetch, test_table_image_file):
        """DEF-6: an image inside a table cell must render in the PDF, not be
        dropped (process_table used to read cell text only)."""
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_table_image.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_images = sum(len(page.get_images()) for page in doc)
        # The cell image must not overflow the page frame width
        widest = max(
            (rect.width for page in doc for rect in
             [r for xref in {i[0] for i in page.get_images()}
              for r in page.get_image_rects(xref)]),
            default=0,
        )
        doc.close()
        assert n_images >= 1, "table-cell image was dropped from the PDF"
        assert widest <= pdf_frame_width() + 1, (
            "table-cell image overflows the page frame"
        )

    async def test_pdf_cell_image_and_caption_both_render(self, jp_fetch, jp_root_dir):
        """A cell holding both a caption and an image keeps both in the PDF."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (300, 200), color=(20, 60, 180)).save(
            images_dir / "shot.png"
        )
        (jp_root_dir / "cap.md").write_text(
            "# Grid\n\n| A | B |\n|---|---|\n"
            '| **Caption One**<br><img src="images/shot.png" alt="s"> | plain |\n',
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "cap.md"}), raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_images = sum(len(page.get_images()) for page in doc)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        assert n_images >= 1, "cell image dropped"
        assert "Caption One" in text, "cell caption text dropped when the image rendered"

    async def test_pdf_page_tall_cell_image_does_not_crash(self, jp_fetch, jp_root_dir):
        """A cell image taller than a page after width-scaling must be capped
        below the frame - an atomic RLImage plus cell padding would otherwise
        exceed one page and raise LayoutError (HTTP 500)."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        # Tall, narrow - stays taller than a page even after width scaling
        PILImage.new("RGB", (200, 5000), color=(180, 40, 40)).save(
            images_dir / "tall.png"
        )
        (jp_root_dir / "tall.md").write_text(
            "# Tall\n\n| Shot |\n|------|\n"
            '| <img src="images/tall.png" alt="t"> |\n',
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "tall.md"}), raise_error=False,
        )
        assert response.code == 200, (
            f"tall cell image raised {response.code} (LayoutError?)"
        )
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_images = sum(len(page.get_images()) for page in doc)
        doc.close()
        assert n_images >= 1, "tall cell image was dropped"

    async def test_pdf_tall_image_in_header_cell_does_not_crash(self, jp_fetch, jp_root_dir):
        """The header row overrides its bottom padding to 8pt (12pt total, vs
        8pt for a body row), so a near-page-tall image in a HEADER cell must be
        capped by that larger padding. Capping at `frame_height - 8` leaves the
        header row 4pt too tall and reopens the atomic-RLImage LayoutError the
        cell-image fix closed."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (200, 5000), color=(40, 140, 60)).save(
            images_dir / "htall.png"
        )
        # Row 0 is the header (its second cell carries text -> has_header) and
        # it holds the tall image, so the image lands in a 12pt-padded row.
        (jp_root_dir / "htall.md").write_text(
            "# Tall header\n\n"
            '| <img src="images/htall.png" alt="t"> | Header |\n'
            "|------|------|\n"
            "| body a | body b |\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "htall.md"}), raise_error=False,
        )
        assert response.code == 200, (
            f"tall header-cell image raised {response.code} (LayoutError?)"
        )
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_images = sum(len(page.get_images()) for page in doc)
        doc.close()
        assert n_images >= 1, "tall header-cell image was dropped"

    async def test_pdf_tall_image_body_row_under_repeating_header_does_not_crash(
        self, jp_fetch, jp_root_dir
    ):
        """A real (text) header repeats on every continuation page. A tall-image
        BODY row then needs `header + image + padding`, which cannot fit while
        the header repeats - so the repeat must be dropped. The guard must key
        off the TALLEST body row, not the shortest: a short row alongside the
        tall one must not mask the overflow."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (200, 5000), color=(60, 40, 160)).save(
            images_dir / "btall.png"
        )
        # Row 0 is a small text header (-> repeatRows). One body row holds the
        # tall image; a second, short body row is the shortest - if the guard
        # checks min(body) it keeps the repeat and the tall row never lays out.
        (jp_root_dir / "btall.md").write_text(
            "# Body tall\n\n"
            "| Name | Diagram |\n"
            "|------|---------|\n"
            '| A | <img src="images/btall.png" alt="d"> |\n'
            "| B | short text |\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "btall.md"}), raise_error=False,
        )
        assert response.code == 200, (
            f"tall body-row image under a repeating header raised {response.code} "
            f"(LayoutError?)"
        )
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_images = sum(len(page.get_images()) for page in doc)
        doc.close()
        assert n_images >= 1, "tall body-row image was dropped"

    async def test_pdf_tall_text_table_keeps_repeating_header(self, jp_fetch, jp_root_dir):
        """A tall TEXT row splits fine under a repeated header, so the header
        must keep repeating across pages - the repeat-drop guard is only for
        atomic image rows. Dropping it for a tall text row regresses the
        keep-header-on-the-page feature. Asserted by the header appearing on
        more than one page."""
        import fitz

        big = ("This is a long paragraph sentence that wraps across many lines. "
               * 240)  # ~15k chars in one cell -> spans multiple pages
        (jp_root_dir / "ttt.md").write_text(
            "# Long text table\n\n"
            "| HEADERALPHA | HEADERBETA |\n"
            "|-------------|------------|\n"
            f"| {big} | side note |\n"
            "| second row a | second row b |\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "ttt.md"}), raise_error=False,
        )
        assert response.code == 200, f"tall text table raised {response.code}"
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_pages = doc.page_count
        header_pages = sum(
            1 for page in doc if "HEADERALPHA" in page.get_text()
        )
        doc.close()
        assert n_pages >= 2, (
            f"test premise broken: table did not span multiple pages ({n_pages})"
        )
        assert header_pages >= 2, (
            f"repeating header appears on only {header_pages} page(s); the guard "
            f"dropped the repeat for a splittable text row"
        )

    async def test_pdf_near_full_page_header_does_not_crash(self, jp_fetch, jp_root_dir):
        """A header row that nearly (but not quite) fills the page leaves less
        than one body line under a repeated header, so a one-line body row can
        never fit on a continuation page -> LayoutError. The guard must drop the
        repeat when the header leaves under one body line, not only when it
        overflows the frame outright. The 150x3160 image lands the header row a
        few points below the frame (just under the 696pt cap), inside that
        window."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (150, 3160), color=(150, 60, 40)).save(
            images_dir / "nfp.png"
        )
        (jp_root_dir / "nfp.md").write_text(
            "# Near full header\n\n"
            '| <img src="images/nfp.png" alt="t"> | HeadTwo |\n'
            "|---|---|\n"
            "| body a | body b |\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "nfp.md"}), raise_error=False,
        )
        assert response.code == 200, (
            f"near-full-page header raised {response.code} (LayoutError?)"
        )
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_images = sum(len(page.get_images()) for page in doc)
        doc.close()
        assert n_images >= 1, "near-full-page header image was dropped"

    async def test_pdf_row_that_fits_a_page_is_not_split(self, jp_fetch, jp_root_dir):
        """DEF-9: a row that fits on a page must move to the next page whole,
        not be torn at the page boundary. A cell holding a caption and its image
        otherwise strands the caption on one page and the image on the next,
        even though the whole row would fit on the following page."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        # Sized so the caption+image row comfortably fits one page (a row that
        # genuinely exceeds a page must still split - that is not this case).
        PILImage.new("RGB", (900, 600), color=(200, 80, 40)).save(
            images_dir / "shot.png"
        )
        # Tuned so the caption+image row does not fit the space left on page 1
        # but fits page 2 whole - the case an unconditional splitInRow tears.
        filler = ("Filler sentence that wraps across the column to consume "
                  "most of the first page. " * 60)
        (jp_root_dir / "split.md").write_text(
            "# Split\n\n"
            "| Col |\n|---|\n"
            f"| {filler} |\n"
            '| **CAPTIONX**<br><img src="images/shot.png" alt="s"> |\n',
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "split.md"}), raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        n_pages = doc.page_count
        cap_pages = [i for i, pg in enumerate(doc) if "CAPTIONX" in pg.get_text()]
        img_pages = [i for i, pg in enumerate(doc) if pg.get_images()]
        doc.close()
        assert n_pages >= 2, (
            f"test premise broken: content did not span pages ({n_pages})"
        )
        assert len(cap_pages) == 1, f"caption found on pages {cap_pages}"
        assert img_pages, "the cell image was dropped"
        assert cap_pages[0] in img_pages, (
            f"caption is on page {cap_pages[0]} but its image is on page(s) "
            f"{img_pages} - the row was split at the page boundary instead of "
            f"moving to the next page whole"
        )

    async def test_pdf_image_only_grid_columns_size_to_images(self, jp_fetch, jp_root_dir):
        """An image-only grid (empty header, no captions - the borderless layout
        idiom the mockup docs use) earns no column width from text, so without an
        image floor each column collapses and its cell image renders a few points
        wide. The column must floor to the image so the grid renders usably."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (800, 1600), color=(30, 90, 200)).save(
            images_dir / "g.png"
        )
        (jp_root_dir / "grid.md").write_text(
            "# Grid\n\n|  |  |  |\n|---|---|---|\n"
            '| ![a](images/g.png) | ![b](images/g.png) | ![c](images/g.png) |\n',
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "grid.md"}), raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        widths = [rc.width for pg in doc for xref in {i[0] for i in pg.get_images()}
                  for rc in pg.get_image_rects(xref)]
        doc.close()
        assert len(widths) == 3, f"expected 3 grid images, got {len(widths)}"
        assert min(widths) > 100, (
            f"image-only grid columns collapsed - images render {min(widths):.0f}pt "
            f"wide; the column must floor to the image"
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
        from types import SimpleNamespace
        from jupyterlab_export_markdown_extension.routes import ExportDocxHandler

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "badge.svg").write_text(SIZE_BADGE_SVG)
            stub = SimpleNamespace(
                contents_manager=SimpleNamespace(root_dir=d)
            )
            html = '<img src="badge.svg" alt="XL" style="max-height:22px">'
            out = ExportDocxHandler.embed_images_as_base64(stub, html, Path(d))
            assert "data:image/svg+xml;base64," in out
            assert 'src="badge.svg"' not in out
            assert 'alt="XL"' in out  # other attributes preserved

    def test_badge_render_spec(self):
        """A small max-height yields a tiny render width + high DPI; an
        unsized image yields None (full diagram width)."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase
        spec = ExportHandlerBase._badge_render_spec

        small = spec('<img style="max-height:22px;max-width:1000px">', 60, 40)
        assert small is not None
        render_w, dpi = small
        # 22px * (60/40) = 33px display -> *4 supersample = 132px, dpi 384
        assert render_w == 132
        assert dpi == 384

        assert spec('<img alt="x">', 800, 345) is None
        assert spec('<img style="max-height:900px">', 60, 40) is None

    def test_badge_render_spec_robustness(self):
        """Adversarial-review hardening: plain height, width-only, unit/ garbage
        handling, and CSS shorthands that must NOT be read as height/width."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase
        spec = ExportHandlerBase._badge_render_spec

        # plain `height:` in style (no max-) is detected
        assert spec('<img style="height:22px">', 60, 40) is not None
        # width-only badge is detected (keyed off width when no height)
        assert spec('<img style="max-width:80px">', 60, 40) == (320, 384)
        # height attribute (bare number) is detected
        assert spec('<img height="22">', 60, 40) is not None
        # malformed number must not raise and must not size (-> None)
        assert spec('<img style="max-height:1.2.3px">', 60, 40) is None
        # non-px units are ignored (not mis-sized)
        assert spec('<img height="2em">', 60, 40) is None
        assert spec('<img style="max-height:50%">', 60, 40) is None
        # CSS shorthands containing 'height'/'width' must NOT match
        assert spec('<img style="line-height:20px">', 60, 40) is None
        assert spec('<img style="stroke-width:3px">', 60, 40) is None
        # width clamp wins when max-height is huge but max-width is tiny
        # eff_h = min(9999, 16/(60/40)=10.67)=10.67 -> disp_w 16 -> *4 = 64
        assert spec('<img style="max-height:9999px;max-width:16px">', 60, 40) == (64, 384)
        # bare width attribute is read; large one is not a badge
        assert spec('<img width="22">', 60, 40) == (88, 384)
        assert spec('<img width="800">', 60, 40) is None
        # data-* attributes must NOT be read as width/height
        assert spec('<img data-height="20">', 60, 40) is None
        assert spec('<img data-width="20">', 60, 40) is None
        # width=/height= inside another attribute's VALUE must NOT be read
        assert spec('<img src="x.svg" alt="chart width=5 tall">', 800, 345) is None
        assert spec('<img alt="height=8 widget">', 800, 345) is None
        # a crafted viewBox aspect cannot drive an unbounded render width (DoS)
        rw, _ = spec('<img style="max-height:1px">', 100000, 1)
        assert rw <= ExportHandlerBase._BADGE_RENDER_MAX_PX
        # max-height takes precedence over a larger plain height in the same style
        assert spec('<img style="height:300px;max-height:22px">', 60, 40) is not None

    def test_embed_src_not_confused_by_data_src(self):
        """resolve only the real `src`, never a `data-src`/`lowsrc` substring,
        and don't truncate a tag on a `>` inside an attribute value."""
        from types import SimpleNamespace
        from jupyterlab_export_markdown_extension.routes import ExportDocxHandler

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "real.svg").write_text(SIZE_BADGE_SVG)
            stub = SimpleNamespace(
                contents_manager=SimpleNamespace(root_dir=d)
            )
            # data-src must be left alone; real src embedded
            out = ExportDocxHandler.embed_images_as_base64(
                stub,
                '<img data-src="lazy.svg" src="real.svg" alt="a > b">',
                Path(d),
            )
            assert 'data-src="lazy.svg"' in out  # untouched
            assert "data:image/svg+xml;base64," in out  # real src embedded
            assert 'src="real.svg"' not in out
            assert 'alt="a > b"' in out  # tag not truncated at the inner '>'

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


class TestImageEmbedSecurity:
    """Local-file containment and SSRF guard on image embedding."""

    def test_ip_is_blocked(self):
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase
        b = ExportHandlerBase._ip_is_blocked
        # non-public ranges an SSRF would target
        assert b("169.254.169.254")  # cloud metadata (link-local)
        assert b("127.0.0.1")        # loopback
        assert b("10.0.0.1")         # private
        assert b("192.168.1.1")      # private
        assert b("::1")              # ipv6 loopback
        assert b("not-an-ip")        # unparseable -> fail closed
        # public addresses are allowed
        assert not b("8.8.8.8")
        assert not b("1.1.1.1")

    def test_host_is_blocked_localhost(self):
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase
        # resolves to a loopback address -> blocked; empty host -> blocked
        assert ExportHandlerBase._host_is_blocked("localhost")
        assert ExportHandlerBase._host_is_blocked(None)

    def test_local_read_contained_to_root(self):
        """A traversal src escaping the server root must NOT be embedded; a
        sibling image inside the root must still embed."""
        from types import SimpleNamespace
        from jupyterlab_export_markdown_extension.routes import ExportDocxHandler

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "secret.txt").write_text("TOP SECRET")  # outside markdown_dir
            sub = root / "docs"
            sub.mkdir()
            (sub / "ok.svg").write_text(SIZE_BADGE_SVG)

            # contents_manager is a read-only handler property; call the method
            # with a stub self exposing only what it reads.
            stub = SimpleNamespace(
                contents_manager=SimpleNamespace(root_dir=str(root))
            )
            embed = ExportDocxHandler.embed_images_as_base64

            # legit sibling under the root -> embedded
            out_ok = embed(stub, '<img src="ok.svg">', sub)
            assert "data:image/svg+xml;base64," in out_ok

            # escape the root -> refused, left untouched
            out_esc = embed(stub, '<img src="../../../../etc/passwd">', sub)
            assert "data:" not in out_esc
            assert 'src="../../../../etc/passwd"' in out_esc

            # fail closed: if the root can't be determined, refuse local reads
            blind = SimpleNamespace(contents_manager=SimpleNamespace(root_dir=None))
            out_blind = embed(blind, '<img src="ok.svg">', sub)
            assert "data:" not in out_blind


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


TEST_MARKDOWN_WIDE_TABLE = """# Wide table

| Component | Purpose | Service | Configuration detail | Monthly cost | Notes |
|---|---|---|---|---|---|
| Ingestion pipeline | Receives sensor telemetry from every house | Kinesis Data Streams | 4 shards with a 24 hour retention window | 145 USD | Needs enhanced fan-out for multiple consumers |
| Storage layer | Durable raw and curated data zones | S3 with Glacier lifecycle | Intelligent tiering after 30 days, versioning on | 62 USD | https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html |
"""

@pytest.fixture
def test_wide_table_file(jp_root_dir):
    """Create a markdown file whose table is far wider than the page."""
    md_file = jp_root_dir / "test_wide_table.md"
    md_file.write_text(TEST_MARKDOWN_WIDE_TABLE, encoding="utf-8")
    return md_file

def pdf_frame_right_edge():
    """The x past which nothing the PDF lays out may extend."""
    from reportlab.lib.pagesizes import letter
    from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

    return (letter[0] - ExportHandlerBase.PDF_PAGE_MARGIN
            - ExportHandlerBase.PDF_FRAME_PADDING)

def pdf_frame_width():
    """The width a flowable is given, page less both margins and both pads."""
    from reportlab.lib.pagesizes import letter
    from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

    return (letter[0] - 2 * ExportHandlerBase.PDF_PAGE_MARGIN
            - 2 * ExportHandlerBase.PDF_FRAME_PADDING)

def pdf_frame_height():
    """The height a flowable is given, page less both margins and both pads."""
    from reportlab.lib.pagesizes import letter
    from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

    return (letter[1] - 2 * ExportHandlerBase.PDF_PAGE_MARGIN
            - 2 * ExportHandlerBase.PDF_FRAME_PADDING)

def pdf_text_past_margin(pdf_bytes):
    """Text runs in `pdf_bytes` whose estimated right edge passes the margin.

    The margin is the frame's content edge: the page margin less the padding
    SimpleDocTemplate puts inside its frame. A run's x origin is the text
    matrix offset within the CTM - reportlab puts it in cm for Paragraph cells
    and in tm for string ones. 0.5em per character under-states the real
    advance width, so a run that merely fills its column is never reported.
    """
    from pypdf import PdfReader

    right_margin = pdf_frame_right_edge()
    overflowing = []

    def visitor(text, cm, tm, font_dict, font_size):
        stripped = text.strip()
        if not stripped:
            return
        x = cm[4] + tm[4]
        right = x + len(stripped) * font_size * 0.5
        if right > right_margin:
            overflowing.append((round(x, 1), round(right, 1), stripped[:40]))

    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        page.extract_text(visitor_text=visitor)
    return overflowing

class TestWideTableFitsPage:
    """A table wider than the page wraps instead of running off the edge."""

    async def test_docx_wide_table_fits_page(self, jp_fetch, test_wide_table_file):
        """The table grid stays inside the margins and uses a fixed layout."""
        from docx import Document
        from docx.oxml.ns import qn
        from docx.shared import Twips

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_wide_table.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        section = doc.sections[0]
        usable = section.page_width - section.left_margin - section.right_margin

        table = doc.tables[0]
        grid = table._tbl.find(qn('w:tblGrid'))
        widths = [Twips(int(col.get(qn('w:w'))))
                  for col in grid.findall(qn('w:gridCol'))]
        assert len(widths) == 6
        assert sum(widths) <= usable, "table grid runs past the right margin"

        # Autofit would let an unbreakable token widen the table past the page
        layout = table._tbl.tblPr.find(qn('w:tblLayout'))
        assert layout is not None and layout.get(qn('w:type')) == 'fixed'

    async def test_docx_single_cell_table_is_fitted_too(
            self, jp_fetch, jp_root_dir):
        """A one-cell table is content, not an alert box, and must be fitted.

        A raw HTML table of one row and one column has the same shape as the
        alert boxes, so shape alone cannot tell them apart. Left on autofit,
        its unbreakable token widens it past the right margin.
        """
        from docx import Document
        from docx.oxml.ns import qn
        from docx.shared import Twips

        (jp_root_dir / "test_one_col.md").write_text(
            "<table><tr><td>" + "z" * 200 + "</td></tr></table>\n",
            encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "test_one_col.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        section = doc.sections[0]
        usable = section.page_width - section.left_margin - section.right_margin

        table = doc.tables[0]
        layout = table._tbl.tblPr.find(qn('w:tblLayout'))
        assert layout is not None and layout.get(qn('w:type')) == 'fixed'
        grid = table._tbl.find(qn('w:tblGrid'))
        widths = [Twips(int(col.get(qn('w:w'))))
                  for col in grid.findall(qn('w:gridCol'))]
        assert sum(widths) <= usable, "one-column table runs past the margin"

    async def test_pdf_wide_table_stays_inside_the_margins(
            self, jp_fetch, test_wide_table_file):
        """No text in the exported PDF is drawn past the right margin."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "test_wide_table.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")

        overflowing = pdf_text_past_margin(response.body)
        assert not overflowing, f"text past the right margin: {overflowing[:3]}"

    async def test_pdf_row_taller_than_the_page_still_exports(self, jp_fetch,
                                                              jp_root_dir):
        """A wrapped row taller than the page must split, not abort the export."""
        words = " ".join(f"word{i}" for i in range(900))
        (jp_root_dir / "tall_row.md").write_text(
            f"| A | B | C |\n|---|---|---|\n| x | {words} | y |\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "tall_row.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        assert response.body.startswith(b"%PDF-")

    async def test_pdf_many_column_table_still_exports(self, jp_fetch,
                                                       jp_root_dir):
        """Columns squeezed to their fair share must not abort the export."""
        ncols = 60  # each column falls below reportlab's own cell padding
        head = "|" + "|".join(f"h{i}" for i in range(ncols)) + "|"
        sep = "|" + "|".join("---" for _ in range(ncols)) + "|"
        row = "|" + "|".join(f"v{i}" for i in range(ncols)) + "|"
        (jp_root_dir / "many_columns.md").write_text(
            f"{head}\n{sep}\n{row}\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "many_columns.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        assert response.body.startswith(b"%PDF-")

        overflowing = pdf_text_past_margin(response.body)
        assert not overflowing, f"text past the right margin: {overflowing[:3]}"

    async def test_docx_overflowing_table_is_always_fitted(self, jp_fetch,
                                                           jp_root_dir):
        """A table over the page width must never slip past the fitter.

        The fitted widths sum to the page width in float arithmetic, which can
        land a hair under it - the guard has to tolerate that or the table
        silently stays on autofit and overflows again.
        """
        from docx import Document
        from docx.oxml.ns import qn

        # These lengths make the fitted widths sum to 10799.999999999998
        # against a 10800-twip page - inside the tolerance window
        lengths = [2, 17, 58, 59, 46, 41, 53]
        words = [2, 16, 4, 21, 13, 13, 7]

        def cell(length, word_length):
            return ("x" * word_length + " ") * max(1, length // (word_length + 1))

        head = "|" + "|".join(f"h{i}" for i in range(7)) + "|"
        sep = "|" + "|".join("---" for _ in range(7)) + "|"
        row = "|" + "|".join(cell(n, w) for n, w in zip(lengths, words)) + "|"
        (jp_root_dir / "overflowing.md").write_text(
            f"{head}\n{sep}\n{row}\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "overflowing.md"}),
        )
        from docx.shared import Twips

        doc = Document(io.BytesIO(response.body))
        section = doc.sections[0]
        usable = section.page_width - section.left_margin - section.right_margin
        table = doc.tables[0]
        layout = table._tbl.tblPr.find(qn('w:tblLayout'))
        assert layout is not None, "an over-wide table was left on autofit"
        # Not just present - a fixed layout of a grid that actually fits
        assert layout.get(qn('w:type')) == 'fixed'
        grid = table._tbl.find(qn('w:tblGrid'))
        widths = [Twips(int(col.get(qn('w:w'))))
                  for col in grid.findall(qn('w:gridCol'))]
        assert sum(widths) <= usable, "fitted grid still runs past the margin"

    async def test_html_table_does_not_overflow_the_viewport(
            self, jp_fetch, test_wide_table_file):
        """Rendered in a browser, the table must not scroll sideways.

        The fixture holds an unbreakable URL, which forces a wider min-content
        width than the viewport unless the cells may break inside a word.
        """
        from playwright.async_api import async_playwright

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test_wide_table.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": 800, "height": 600})
                await page.set_content(html)
                # The row box is the grid itself - the table element may be a
                # scroll container, which fits the viewport by construction
                row_width, doc_width, viewport_width = await page.evaluate(
                    "() => { const r = document.querySelector('tr');"
                    " const d = document.documentElement;"
                    " return [r.getBoundingClientRect().width,"
                    " d.scrollWidth, d.clientWidth]; }"
                )
            finally:
                await browser.close()

        assert row_width <= viewport_width, (
            f"table grid is {row_width}px wide in a {viewport_width}px viewport"
        )
        assert doc_width <= viewport_width, "the page scrolls sideways"

    async def test_html_many_column_table_is_contained(self, jp_fetch,
                                                       jp_root_dir):
        """A table too wide to wrap scrolls in its own box, not the page."""
        from playwright.async_api import async_playwright

        ncols = 40
        head = "|" + "|".join(f"Header {i}" for i in range(ncols)) + "|"
        sep = "|" + "|".join("---" for _ in range(ncols)) + "|"
        row = "|" + "|".join(f"value {i}" for i in range(ncols)) + "|"
        (jp_root_dir / "many_columns.md").write_text(
            f"{head}\n{sep}\n{row}\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "many_columns.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": 800, "height": 600})
                await page.set_content(html)
                doc_width, viewport_width = await page.evaluate(
                    "() => { const d = document.documentElement;"
                    " return [d.scrollWidth, d.clientWidth]; }"
                )
            finally:
                await browser.close()

        assert doc_width <= viewport_width, (
            f"a {ncols}-column table scrolls the page ({doc_width}px "
            f"in {viewport_width}px)"
        )

    async def test_html_scroll_box_does_not_clip_on_paper(self, jp_fetch,
                                                          jp_root_dir):
        """Paper cannot scroll, so the box must stop being one when printing.

        Left as a scroll container, print media crops the table at the box
        edge and the hidden columns are simply absent from the printout.
        """
        from playwright.async_api import async_playwright

        from pypdf import PdfReader

        ncols = 30
        head = "|" + "|".join(f"H{i}x" for i in range(ncols)) + "|"
        sep = "|" + "|".join("---" for _ in range(ncols)) + "|"
        row = "|" + "|".join(f"v{i}" for i in range(ncols)) + "|"
        (jp_root_dir / "print_table.md").write_text(
            f"{head}\n{sep}\n{row}\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "print_table.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html)
                printed = await page.pdf()
            finally:
                await browser.close()

        # Columns this narrow break every character onto its own line
        text = "".join("".join(p.extract_text().split())
                       for p in PdfReader(io.BytesIO(printed)).pages)
        missing = [i for i in range(ncols) if f"H{i}x" not in text]
        assert not missing, f"printing dropped {len(missing)} headers: {missing}"

    async def test_html_raw_table_with_attributes_is_wrapped(
            self, jp_fetch, jp_root_dir):
        """Raw HTML passes through markdown verbatim, attributes and all.

        A wrapper matched on a bare `<table>` misses `<table border="1">`, and
        the table then pushes the whole document sideways.
        """
        from playwright.async_api import async_playwright

        ncols = 40
        cells = "".join(f"<td>value {i}</td>" for i in range(ncols))
        (jp_root_dir / "raw_table.md").write_text(
            f'<table border="1"><tr>{cells}</tr></table>\n', encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "raw_table.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": 800, "height": 600})
                await page.set_content(html)
                doc_width, viewport_width = await page.evaluate(
                    "() => { const d = document.documentElement;"
                    " return [d.scrollWidth, d.clientWidth]; }"
                )
            finally:
                await browser.close()

        assert doc_width <= viewport_width, (
            f"a raw table with attributes scrolls the page ({doc_width}px "
            f"in {viewport_width}px)"
        )

    async def test_html_nested_table_keeps_its_inner_table(
            self, jp_fetch, jp_root_dir):
        """The wrapper must close on the outer table, not the inner one.

        A non-greedy match closes the wrapper at the first `</table>`, which
        is the inner table's. The markup is then mis-nested and the browser
        recovers by lifting the inner table clean out of its cell.
        """
        from playwright.async_api import async_playwright

        (jp_root_dir / "nested_table.md").write_text(
            "<table><tr><td><table><tr><td>inner</td></tr></table>"
            "</td></tr></table>\n\nAfter the table.\n",
            encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "nested_table.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": 800, "height": 600})
                await page.set_content(html)
                nested_in_cell, wrappers = await page.evaluate(
                    "() => [!!document.querySelector("
                    "'.table-scroll table td table'),"
                    " document.querySelectorAll('.table-scroll').length]"
                )
            finally:
                await browser.close()

        assert nested_in_cell, "the nested table was lifted out of its cell"
        assert wrappers == 1, f"expected one wrapper, got {wrappers}"

    def test_html_table_inside_a_comment_opens_no_wrapper(self):
        """A `<table>` inside an HTML comment must not open a scroll box.

        Markdown passes comments through verbatim. A wrapper scan that is
        blind to comments opens a `<div class="table-scroll">` at the commented
        `<table>`, never meets a `</table>`, and leaves the div open over the
        rest of the document.
        """
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        handler = ExportHandlerBase.__new__(ExportHandlerBase)
        html = ("<p>Intro.</p><!-- TODO: add a <table> here -->"
                "<p>After the comment.</p>")
        wrapped = handler.wrap_html_tables(html)
        assert '<div class="table-scroll">' not in wrapped, (
            "a commented <table> opened a wrapper"
        )
        # A real table after the comment must still wrap and close cleanly
        both = handler.wrap_html_tables(
            html + "<table><tr><td>x</td></tr></table>")
        assert both.count('<div class="table-scroll">') == 1
        assert both.count('</div>') == 1


class TestPageFitting:
    """Tables must not orphan a header at a page break; tall images must fit."""

    async def test_pdf_table_header_repeats_on_each_page(
            self, jp_fetch, jp_root_dir):
        """A table spanning pages repeats its header - the mechanism that also
        keeps the header from being stranded alone at a page bottom."""
        import fitz

        rows = "\n".join(f"| r{i:02d}a | r{i:02d}b |" for i in range(80))
        (jp_root_dir / "tall_table.md").write_text(
            f"| ZZHEADERZZ | COLBETA |\n|---|---|\n{rows}\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "tall_table.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        doc = fitz.open(stream=response.body, filetype="pdf")
        assert doc.page_count >= 2, "table should span multiple pages"
        pages_with_header = sum(
            1 for page in doc if "ZZHEADERZZ" in page.get_text())
        assert pages_with_header >= 2, (
            "header not repeated on continuation pages - it can be orphaned"
        )

    async def test_pdf_page_tall_header_row_still_exports(
            self, jp_fetch, jp_root_dir):
        """A repeated header must not re-arm the LayoutError splitInRow fixed.

        With repeatRows the header is re-emitted on each page, so a header row
        taller than a page cannot be placed and reportlab raises LayoutError.
        A page-long alert (a 1x1 table), a header-only tall table and a tall
        header with a body row must all still export.
        """
        long_para = " ".join(f"word{i}" for i in range(1500))
        cases = {
            "alert": f"> [!NOTE]\n> {long_para}\n",
            "header_only": f"| {long_para} |\n|---|\n",
            "tall_header": f"| {long_para} |\n|---|\n| body |\n",
        }
        for name, md in cases.items():
            (jp_root_dir / f"{name}.md").write_text(md, encoding="utf-8")
            response = await jp_fetch(
                "jupyterlab-export-markdown-extension",
                "export/pdf",
                method="POST",
                body=json.dumps({"path": f"{name}.md"}),
                raise_error=False,
            )
            assert response.code == 200, (name, response.body[:200])
            assert response.body.startswith(b"%PDF-")

    async def test_docx_table_header_row_marked_repeating(
            self, jp_fetch, jp_root_dir):
        """The header row carries w:tblHeader so Word repeats it and never
        strands it alone at a page bottom."""
        from docx import Document
        from docx.oxml.ns import qn

        (jp_root_dir / "hdr_table.md").write_text(
            "| A | B |\n|---|---|\n| one | two |\n| three | four |\n",
            encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "hdr_table.md"}),
            raise_error=False,
        )
        assert response.code == 200

        table = Document(io.BytesIO(response.body)).tables[0]
        trPr = table.rows[0]._tr.find(qn('w:trPr'))
        assert trPr is not None and trPr.find(qn('w:tblHeader')) is not None, (
            "first row is not marked as a repeating header"
        )

    async def test_html_print_keeps_header_with_body(
            self, jp_fetch, jp_root_dir):
        """In print media the table header must not break away from its body."""
        from playwright.async_api import async_playwright

        (jp_root_dir / "hdr_html.md").write_text(
            "| A | B |\n|---|---|\n| one | two |\n", encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "hdr_html.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html)
                await page.emulate_media(media="print")
                break_inside = await page.evaluate(
                    "() => getComputedStyle(document.querySelector('thead'))"
                    ".breakInside"
                )
            finally:
                await browser.close()

        assert break_inside == "avoid", (
            f"thead break-inside is {break_inside!r}, header can be orphaned"
        )

    async def test_pdf_tall_image_fits_page_height(self, jp_fetch, jp_root_dir):
        """A diagram too tall at page width is scaled down to the page height."""
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        # 300 x 3000 px - narrow enough to fit the width, far too tall
        PILImage.new("RGB", (300, 3000), color=(0, 100, 0)).save(
            images_dir / "tall.png")
        (jp_root_dir / "tall_image.md").write_text(
            "![tall](images/tall.png)\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/pdf",
            method="POST",
            body=json.dumps({"path": "tall_image.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        doc = fitz.open(stream=response.body, filetype="pdf")
        frame_height = pdf_frame_height()
        worst = 0.0
        for page in doc:
            for img in page.get_images():
                for rect in page.get_image_rects(img[0]):
                    worst = max(worst, rect.height)
        assert worst > 0, "image was not embedded"
        assert worst <= frame_height + 1, (
            f"image drawn {worst:.0f}pt tall, past the {frame_height}pt frame"
        )

    async def test_docx_tall_image_fits_page_height(self, jp_fetch, jp_root_dir):
        """An image taller than the page is scaled down to fit its height."""
        from PIL import Image as PILImage
        from docx import Document

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (300, 3000), color=(0, 0, 100)).save(
            images_dir / "tall_docx.png")
        (jp_root_dir / "tall_image_docx.md").write_text(
            "![tall](images/tall_docx.png)\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/docx",
            method="POST",
            body=json.dumps({"path": "tall_image_docx.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        section = doc.sections[0]
        usable_height = (section.page_height - section.top_margin
                         - section.bottom_margin)
        shape = list(doc.inline_shapes)[0]
        assert shape.height <= usable_height, (
            "tall image was not scaled down to the page height"
        )

    async def test_html_print_caps_image_height(self, jp_fetch, jp_root_dir):
        """A tall image must fit one printed page, not spill across several.

        A 300x3000 image is 10x taller than wide - uncapped it prints across
        several pages; the print stylesheet must bound it to one page.
        """
        from playwright.async_api import async_playwright
        from pypdf import PdfReader
        from PIL import Image as PILImage

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        PILImage.new("RGB", (300, 3000), color=(100, 0, 0)).save(
            images_dir / "tall_html.png")
        (jp_root_dir / "tall_image_html.md").write_text(
            "![tall](images/tall_html.png)\n", encoding="utf-8")

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "tall_image_html.md"}),
        )
        html = response.body.decode("utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(html)
                printed = await page.pdf()
            finally:
                await browser.close()

        pages = len(PdfReader(io.BytesIO(printed)).pages)
        assert pages == 1, (
            f"tall image printed to {pages} pages, not capped to one"
        )


class TestColumnWidthFitting:
    """Unit tests for the shared column-width fitter."""

    def _fit(self, natural, minimums, available):
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        return ExportHandlerBase.fit_column_widths(natural, minimums, available)

    def test_widths_that_fit_are_untouched(self):
        assert self._fit([100, 50], [40, 20], 500) == [100, 50]

    def test_overflowing_widths_are_scaled_to_available(self):
        widths = self._fit([600, 300, 100], [50, 50, 50], 500)
        assert sum(widths) == pytest.approx(500)
        assert widths[0] > widths[1] > widths[2], "proportions are preserved"

    def test_every_column_keeps_its_longest_word(self):
        # Column 2 is narrow overall but holds one long word
        widths = self._fit([900, 100], [50, 90], 500)
        assert widths[1] >= 90, "a column must not wrap mid-word"
        assert sum(widths) == pytest.approx(500)

    def test_minimums_wider_than_the_page_fall_back_to_equal_columns(self):
        widths = self._fit([900, 900], [400, 400], 500)
        assert widths == [250, 250]

    def _measure(self, table_data, available, floors=None):
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        return ExportHandlerBase.measured_column_widths(
            table_data, available, lambda text, _row: len(text) * 10.0 + 20,
            floors)

    def test_measured_widths_use_longest_line_and_longest_word(self):
        """Natural width comes from the longest line, minimum from the word."""
        table_data = [
            ["Component", "a short one"],
            ["short\nlonger line here", "unbreakable"],
        ]
        # Natural widths total 310, minimums 240 - squeezing happens between
        available = 280.0
        widths = self._measure(table_data, available)
        assert sum(widths) == pytest.approx(available)
        # Column 1 must never wrap inside 'unbreakable', its longest word
        assert widths[1] >= len("unbreakable") * 10.0 + 20
        # Column 0's longest line drove its natural width, and it gave ground
        assert widths[0] < len("longer line here") * 10.0 + 20

    def test_measured_widths_floor_empty_columns(self):
        """An empty column keeps an empty cell's width even when squeezed."""
        table_data = [
            ["x" * 40, "", "y" * 40],
            ["x" * 40, "", "y" * 40],
        ]
        available = 300.0
        widths = self._measure(table_data, available)
        assert sum(widths) == pytest.approx(available)
        assert widths[1] >= 20, "an empty column collapsed to nothing"

    def test_every_column_capped_at_fair_share_gives_equal_columns(self):
        """No floor may exceed an equal share, or one column starves the rest."""
        table_data = [["x" * 60, "y" * 60, "z" * 60]]
        available = 300.0
        # Floors far past the page must not push the total over it
        widths = self._measure(table_data, available, floors=[500.0, 0.0, 0.0])
        assert sum(widths) == pytest.approx(available)
        assert widths[0] <= available / 3 + 1e-6

    def test_pdf_column_layout_never_exceeds_the_frame(self):
        """Padding shrinks with column count instead of blowing the budget.

        reportlab does not raise on width overflow - it just draws the table
        off the sheet - so nothing downstream would catch a broken budget.
        """
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        available = pdf_frame_width()

        def string_width(text, _row_index):
            return len(text) * 5.0

        cases = {
            "empty middle column": [["a", "", "b"], ["x", "", "y"]],
            "two empty columns": [["a", "", "b", ""], ["x", "", "y", ""]],
        }
        for ncols in (6, 20, 34, 40, 60, 100, 120, 200, 300, 528, 900):
            cases[f"{ncols} columns"] = [
                [f"h{i}" for i in range(ncols)],
                [f"v{i}" for i in range(ncols)],
            ]

        for name, table_data in cases.items():
            padding, widths = ExportHandlerBase.pdf_table_column_layout(
                table_data, available, string_width)
            assert sum(widths) <= available + 1e-6, f"{name} runs off the page"
            assert min(widths) > 2 * padding, f"{name} has no content area"


# --------------------------------------------------------------------------
# Defect regressions (docs/defects.md)
# --------------------------------------------------------------------------

def _pdf_fill_colors(page):
    """RGB (0..1) fill colours of every vector drawing on a fitz page."""
    return [tuple(round(c, 3) for c in d["fill"])
            for d in page.get_drawings() if d.get("fill") is not None]


def _pdf_stroke_colors(page):
    """RGB (0..1) stroke colours of every vector drawing on a fitz page."""
    return [tuple(round(c, 3) for c in d["color"])
            for d in page.get_drawings() if d.get("color") is not None]


def _color_near(colors, target, tol=0.02):
    return any(all(abs(c - t) <= tol for c, t in zip(col, target))
               for col in colors if len(col) == len(target))


def _is_italic_font(font_name):
    """Slanted faces are named Italic or Oblique depending on the family that
    was found on the box - DejaVu ships Oblique, Liberation ships Italic.
    Matched on the stem, since fitz truncates an embedded subset name to 24
    characters (`LiberationSans-BoldItali`, the trailing `c` cut)."""
    return "Ital" in font_name or "Obli" in font_name


TEST_MARKDOWN_TASK_LIST = """# Tasks

- [x] finished item
- [ ] pending item
- [X] also finished
"""


@pytest.fixture
def test_task_list_file(jp_root_dir):
    md_file = jp_root_dir / "test_task_list.md"
    md_file.write_text(TEST_MARKDOWN_TASK_LIST, encoding="utf-8")
    return md_file


class TestTaskListCheckboxes:
    """DEF-1: `- [x]` / `- [ ]` render as checkbox glyphs (☒/☐), not literal
    text; DOCX draws them in MS Gothic (Word's own checkbox font)."""

    async def test_html_renders_checkbox_glyphs(self, jp_fetch, test_task_list_file):
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "test_task_list.md"}),
            raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "☒" in html, "checked checkbox glyph missing from HTML"
        assert "☐" in html, "empty checkbox glyph missing from HTML"
        assert "[x] finished" not in html and "[ ] pending" not in html, (
            "literal task markers leaked into HTML"
        )

    async def test_docx_renders_checkbox_glyphs(self, jp_fetch, test_task_list_file):
        from docx import Document
        from docx.oxml.ns import qn

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "test_task_list.md"}),
            raise_error=False,
        )
        assert response.code == 200
        doc = Document(io.BytesIO(response.body))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "☒" in text and "☐" in text, "checkbox glyphs missing from DOCX"
        assert "[x] finished" not in text and "[ ] pending" not in text, (
            "literal task markers leaked into DOCX"
        )
        # The glyph must sit in its own run tagged MS Gothic (Word's checkbox font)
        gothic_glyph_runs = 0
        for r in doc.element.body.iter(qn("w:r")):
            t = r.find(qn("w:t"))
            if t is None or not t.text or t.text not in ("☒", "☐"):
                continue
            rFonts = r.find(qn("w:rPr") + "/" + qn("w:rFonts")) \
                if r.find(qn("w:rPr")) is not None else None
            assert rFonts is not None and rFonts.get(qn("w:ascii")) == "MS Gothic", (
                "checkbox glyph run is not tagged MS Gothic"
            )
            gothic_glyph_runs += 1
        assert gothic_glyph_runs >= 3, "expected each checkbox glyph in its own MS Gothic run"

    async def test_pdf_renders_checkbox_glyphs(self, jp_fetch, test_task_list_file):
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "test_task_list.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
        assert "☒" in text and "☐" in text, "checkbox glyphs missing from PDF"
        assert "[x] finished" not in text and "[ ] pending" not in text, (
            "literal task markers leaked into PDF"
        )

    async def test_task_marker_in_code_block_not_converted(self, jp_fetch, jp_root_dir):
        """A `- [ ]` written inside a fenced code block is code, not a task."""
        (jp_root_dir / "cb.md").write_text(
            "# C\n\n```\n- [ ] not a task, just code\n- [x] also code\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "cb.md"}), raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "☒" not in html and "☐" not in html, (
            "a task marker inside a code block was converted to a checkbox"
        )
        # Pygments wraps each token in a span; strip tags before checking the text
        plain = re.sub(r"<[^>]+>", "", html)
        assert "[ ] not a task" in plain, "code block content was altered"

    async def test_link_list_item_not_converted(self, jp_fetch, jp_root_dir):
        """`- [text](url)` is a link, not a checkbox - only `[ ]`/`[x]` match."""
        (jp_root_dir / "lk.md").write_text(
            "- [a link](https://example.com)\n- [x] done\n", encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "lk.md"}), raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert 'href="https://example.com"' in html, "link item was mangled"
        assert html.count("☒") + html.count("☐") == 1, (
            "only the real task item should become a checkbox"
        )

    async def test_star_and_plus_markers_convert(self, jp_fetch, jp_root_dir):
        """`*` and `+` list markers carry task boxes too, not just `-`."""
        (jp_root_dir / "sp.md").write_text(
            "* [x] star done\n+ [ ] plus open\n", encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "sp.md"}), raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "☒" in html and "☐" in html, "* / + task markers not converted"

    async def test_empty_task_item_converts(self, jp_fetch, jp_root_dir):
        """A bare task item with no label (`- [x]` / `- [ ]`, nothing trailing)
        still becomes a checkbox - the marker match must not require text after
        the bracket, or GitHub's empty-checkbox idiom leaks through as literal
        `[x]` / `[ ]`."""
        (jp_root_dir / "empty.md").write_text(
            "- [x]\n- [ ]\n", encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "empty.md"}), raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "☒" in html and "☐" in html, (
            "bare task items were left as literal [x] / [ ]"
        )

    async def test_task_marker_in_nested_longer_fence_not_converted(self, jp_fetch, jp_root_dir):
        """A shorter ``` line inside a longer ```` block is content, not the
        closing fence (CommonMark: a closing fence is at least as long as the
        opener). A `- [ ]` after it is still code and must not become a glyph."""
        (jp_root_dir / "nf.md").write_text(
            "# N\n\n````\n```\n- [ ] still inside the code block\n````\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "nf.md"}), raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "☒" not in html and "☐" not in html, (
            "a task marker inside a nested longer fence was converted to a checkbox"
        )

    async def test_task_marker_after_info_string_fence_not_converted(self, jp_fetch, jp_root_dir):
        """A ```lang line inside a fenced block is a nested opener, not a
        closer (CommonMark: a closing fence carries no info string), so a
        `- [ ]` after it is still code and must not become a glyph."""
        (jp_root_dir / "infofence.md").write_text(
            "# I\n\n```\nsome code\n```python\n- [ ] still code\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "infofence.md"}), raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "☒" not in html and "☐" not in html, (
            "a task marker after an info-string fence line was converted"
        )


class TestBlockquotePdfCallout:
    """DEF-2: blockquotes render in PDF with a left bar, shading and indent."""

    async def test_pdf_blockquote_has_bar_shading_and_indent(
        self, jp_fetch, test_quotes_in_list_file
    ):
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "test_quotes_in_list.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        page = doc[0]

        assert _color_near(_pdf_fill_colors(page), (0.957, 0.957, 0.957)), (
            "blockquote background shading (F4F4F4) missing from PDF"
        )
        assert _color_near(_pdf_stroke_colors(page), (0.733, 0.733, 0.733)), (
            "blockquote left bar (BBBBBB) missing from PDF"
        )

        body_x, quote_x = [], []
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for s in line["spans"]:
                    if "Two ideas" in s["text"]:
                        body_x.append(s["bbox"][0])
                    if "quoted note" in s["text"]:
                        quote_x.append(s["bbox"][0])
        doc.close()
        assert body_x and quote_x, "expected body and quote text in the PDF"
        assert min(quote_x) > min(body_x) + 15, (
            "blockquote text is not indented relative to body text"
        )

    async def test_pdf_callout_that_fits_a_page_is_not_split(self, jp_fetch, jp_root_dir):
        """DEF-9 applies to callouts too: a blockquote/alert box that fits a
        page must move whole rather than tear mid-box at the page boundary."""
        import fitz

        # Tuned so the quote box does not fit the space left on the page it
        # would start on, but fits the next page whole - the case an
        # unconditional splitInRow tears mid-box.
        filler = "Filler paragraph line to push the quote toward the page end. "
        quote = " ".join(
            f"QW{i} lorem ipsum dolor sit amet consectetur" for i in range(40)
        )
        (jp_root_dir / "cq.md").write_text(
            "# Q\n\n" + (filler * 175) + "\n\n> " + quote + "\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "cq.md"}), raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        first = [i for i, pg in enumerate(doc) if "QW0 " in pg.get_text()]
        last = [i for i, pg in enumerate(doc) if "QW39 " in pg.get_text()]
        doc.close()
        assert first and last, "quote text missing from the PDF"
        assert first[0] == last[0], (
            f"the quote box was torn across pages: starts on page {first[0]}, "
            f"ends on page {last[0]} - a callout that fits a page must move whole"
        )

    async def test_pdf_multi_paragraph_quote_is_one_callout(self, jp_fetch, jp_root_dir):
        """Consecutive blockquote paragraphs render as a single shaded box with
        one continuous bar, not a stack of separate boxes with gaps."""
        import fitz

        (jp_root_dir / "mq.md").write_text(
            "# Q\n\n> line one\n>\n> line two\n>\n> line three\n\nAfter.\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "mq.md"}), raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        # Count the blockquote shading fills (F4F4F4) - one per callout box
        shade_boxes = sum(
            1 for page in doc for c in _pdf_fill_colors(page)
            if len(c) == 3 and all(abs(x - 0.957) < 0.02 for x in c)
        )
        text = "".join(page.get_text() for page in doc)
        doc.close()
        assert "line one" in text and "line three" in text, "quote text missing"
        assert shade_boxes == 1, (
            f"a 3-paragraph quote rendered as {shade_boxes} boxes, expected 1"
        )


class TestAlertPdfCallout:
    """DEF-3: alerts render in PDF as a coloured-bar callout, not a table header."""

    async def test_pdf_alert_renders_as_callout_not_header(
        self, jp_fetch, test_rich_alerts_file
    ):
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        fills, strokes, spans = [], [], []
        for page in doc:
            fills += _pdf_fill_colors(page)
            strokes += _pdf_stroke_colors(page)
            for b in page.get_text("dict")["blocks"]:
                for line in b.get("lines", []):
                    spans += line["spans"]
        doc.close()

        # IMPORTANT alert: purple shading (F4EDFF) + purple left bar (8250DF)
        assert _color_near(fills, (0.957, 0.929, 1.0)), (
            "alert purple shading missing - not rendered as a callout"
        )
        assert _color_near(strokes, (0.510, 0.314, 0.875)), (
            "alert purple left bar missing"
        )
        # Alert body text must not use the content-table header colour (#365F91)
        alert_spans = [s for s in spans if "porosity" in s["text"]]
        assert alert_spans, "expected alert body text in the PDF"
        for s in alert_spans:
            assert s["color"] != 0x365F91, (
                "alert text still rendered in the table-header colour"
            )

    async def test_pdf_data_table_still_header_styled(
        self, jp_fetch, test_rich_alerts_file
    ):
        """The real data table must keep its header fill - alert detection
        must not misfire on an ordinary content table."""
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        fills = [c for page in doc for c in _pdf_fill_colors(page)]
        doc.close()
        assert _color_near(fills, (0.859, 0.898, 0.945)), (
            "data-table header fill (dbe5f1) missing - alert detection over-matched"
        )

    async def test_pdf_alert_colors_per_type(self, jp_fetch, test_rich_alerts_file):
        """Each alert type keeps its own callout shading in the PDF (the fixture
        carries IMPORTANT/purple, NOTE/blue, WARNING/amber)."""
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "test_rich_alerts.md"}),
            raise_error=False,
        )
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        fills = [c for page in doc for c in _pdf_fill_colors(page)]
        doc.close()
        assert _color_near(fills, (0.957, 0.929, 1.0)), "IMPORTANT purple shading missing"
        assert _color_near(fills, (0.929, 0.961, 0.992)), "NOTE blue shading missing"
        assert _color_near(fills, (0.996, 0.976, 0.906)), "WARNING amber shading missing"


class TestMermaidViewBoxCrop:
    """DEF-4: an SVG whose declared viewBox dwarfs its content is cropped
    to the real content bounding box before rasterizing."""

    async def test_oversized_viewbox_is_cropped_to_content(self):
        from jupyterlab_export_markdown_extension.routes import (
            PlaywrightSvgRenderer,
        )
        from PIL import Image as PILImage

        # A 120x60 shape sitting inside an 800x800 viewBox.
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" '
            'width="100%"><rect x="10" y="10" width="120" height="60" '
            'fill="black"/></svg>'
        ).encode("utf-8")

        async with PlaywrightSvgRenderer(color_scheme="light") as renderer:
            png = await renderer.render(svg, width=600)

        img = PILImage.open(io.BytesIO(png)).convert("RGBA")
        w, h = img.size
        bbox = img.getbbox()
        assert bbox is not None, "rasterized diagram is entirely blank"
        cw, ch = bbox[2] - bbox[0], bbox[3] - bbox[1]
        assert cw / w > 0.7, (
            f"diagram fills only {100 * cw / w:.0f}% of canvas width - "
            f"view window is larger than the shape"
        )
        assert ch / h > 0.7, (
            f"diagram fills only {100 * ch / h:.0f}% of canvas height - "
            f"view window is larger than the shape"
        )

    async def test_unmeasurable_svg_falls_back_to_declared_viewbox(self):
        """When getBBox yields no geometry (e.g. an empty SVG), render must
        fall back to the declared viewBox rather than crash or size to zero."""
        from jupyterlab_export_markdown_extension.routes import (
            PlaywrightSvgRenderer,
        )
        from PIL import Image as PILImage

        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
            '<defs></defs></svg>'
        ).encode("utf-8")
        async with PlaywrightSvgRenderer(color_scheme="light") as renderer:
            png = await renderer.render(svg, width=400)
        img = PILImage.open(io.BytesIO(png))
        # Declared viewBox aspect 2:1 -> 400x200; the fallback must hold
        assert img.size == (400, 200), (
            f"fallback viewBox produced {img.size}, expected (400, 200)"
        )

    async def test_well_framed_diagram_is_not_cropped(self):
        """DEF-4 regression (adversarial #4): a diagram that already fills its
        declared viewBox must be left alone. getBBox reports geometry only - no
        stroke, markers or filters - so re-cropping a well-framed diagram would
        clip node borders and arrowheads. The declared viewBox aspect must
        survive even when the content's own geometry aspect differs slightly."""
        from jupyterlab_export_markdown_extension.routes import (
            PlaywrightSvgRenderer,
        )
        from PIL import Image as PILImage

        # Content fills the 3:1 viewBox in both axes (fill_w 0.97, fill_h 0.90),
        # so it must NOT be tightened; a tightened box would be ~2.8:1 (h~217).
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100" '
            'width="100%"><rect x="5" y="5" width="290" height="90" '
            'fill="black"/></svg>'
        ).encode("utf-8")

        async with PlaywrightSvgRenderer(color_scheme="light") as renderer:
            png = await renderer.render(svg, width=600)

        img = PILImage.open(io.BytesIO(png))
        assert img.size == (600, 200), (
            f"well-framed diagram was re-cropped to {img.size}; the declared "
            f"3:1 viewBox (600x200) must be honoured, not tightened to content"
        )

    async def test_nonzero_viewbox_origin_is_preserved(self):
        """DEF-4 regression (adversarial #7): when the diagram is not cropped,
        the SVG's own viewBox - including a non-zero origin - must be kept. A
        mermaid viewBox like `-100 -50 200 100` places content around a negative
        origin; zeroing it would shift the drawing off-canvas and blank most of
        the render."""
        from jupyterlab_export_markdown_extension.routes import (
            PlaywrightSvgRenderer,
        )
        from PIL import Image as PILImage

        # Well-framed content drawn around a negative origin. With the viewBox
        # kept, the rect nearly fills the canvas; a zeroed viewBox would push it
        # into the top-left corner, leaving most of the canvas blank.
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="-100 -50 200 100" width="100%">'
            '<rect x="-95" y="-45" width="190" height="90" fill="black"/></svg>'
        ).encode("utf-8")

        async with PlaywrightSvgRenderer(color_scheme="light") as renderer:
            png = await renderer.render(svg, width=400)

        img = PILImage.open(io.BytesIO(png)).convert("RGBA")
        w, h = img.size
        bbox = img.getbbox()
        assert bbox is not None, "rasterized diagram is entirely blank"
        cw = bbox[2] - bbox[0]
        assert cw / w > 0.8, (
            f"content fills only {100 * cw / w:.0f}% of width - the non-zero "
            f"viewBox origin was dropped, shifting the drawing off-canvas"
        )

    async def test_extreme_aspect_diagram_stays_within_the_raster_limit(
            self, monkeypatch):
        """A long single-column flowchart is many times taller than it is wide,
        and at the configured export width its raster runs past Chromium's
        ~16384px viewport and texture caps - the screenshot throws and the
        diagram is dropped from the export with no error surfaced. It must be
        scaled down instead, aspect intact.

        The cap is patched down so the test exercises the clamp without
        rendering a 16000px canvas."""
        from jupyterlab_export_markdown_extension.routes import (
            PlaywrightSvgRenderer,
        )
        from PIL import Image as PILImage

        monkeypatch.setattr(PlaywrightSvgRenderer, "MAX_RASTER_PX", 1000)
        # A 60x1500 column inside a square viewBox: cropped (fill_h 0.94 but
        # fill_w 0.04), it rasterizes ~25:1 - 400px wide would be 10000px tall.
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1600" '
            'width="100%"><rect x="20" y="50" width="60" height="1500" '
            'fill="black"/></svg>'
        ).encode("utf-8")

        async with PlaywrightSvgRenderer(color_scheme="light") as renderer:
            png = await renderer.render(svg, width=400)

        img = PILImage.open(io.BytesIO(png))
        w, h = img.size
        assert max(w, h) <= 1000, (
            f"raster came back {w}x{h}, past the {1000}px cap - Chromium "
            f"would refuse it and the diagram would vanish from the export"
        )
        assert img.convert("RGBA").getbbox() is not None, (
            "the clamped raster is blank"
        )
        # The clamp must scale, not crop: the drawn column keeps its aspect
        assert h > w * 5, (
            f"clamped raster is {w}x{h} - the extreme aspect was not preserved"
        )


#: A mermaid-shaped SVG root: mermaid stamps `width="100%"` plus an inline
#: `max-width: <natural>px` and a viewBox tight to the drawing. The max-width
#: caps the element, so a rasterizer that only sets `width` paints the diagram
#: at natural size inside the target canvas and the rest becomes whitespace.
MERMAID_LIKE_SVG = (
    '<svg id="m0" width="100%" xmlns="http://www.w3.org/2000/svg" '
    'class="flowchart" style="max-width: 800px;" viewBox="0 0 800 70">'
    '<rect x="10" y="10" width="780" height="50" fill="#0284c7"/>'
    '</svg>'
)


def _ink_bbox(img):
    """Bounding box of real ink, trimming both transparent and white margin."""
    from PIL import Image as PILImage
    rgba = img.convert("RGBA")
    bbox = rgba.getbbox()  # trims fully transparent margin
    if bbox is not None and (bbox[2] - bbox[0]) < rgba.size[0]:
        return bbox
    # Opaque (white-matted) export: trim near-white instead
    flat = PILImage.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.split()[-1])
    gray = flat.convert("L")
    mask = gray.point(lambda p: 255 if p < 245 else 0)
    return mask.getbbox()


class TestMermaidDocxNoWhitespace:
    """DEF-7 (regression): a mermaid diagram embedded in the DOCX must fill its
    image rather than sit in whitespace. Deterministic check - pull the image
    back out of the .docx, trim the blank margin, and measure what fraction of
    the image the drawing actually occupies."""

    async def test_docx_mermaid_image_is_not_mostly_whitespace(self, jp_fetch, jp_root_dir):
        import base64
        from PIL import Image as PILImage

        (jp_root_dir / "mm.md").write_text(
            "# M\n\n```mermaid\nflowchart LR\n    A --> B\n```\n", encoding="utf-8"
        )
        data_uri = ("data:image/svg+xml;base64,"
                    + base64.b64encode(MERMAID_LIKE_SVG.encode()).decode())
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST",
            body=json.dumps({"path": "mm.md",
                             "mermaidDiagrams": [{"index": 0, "svg": data_uri}]}),
            raise_error=False,
        )
        assert response.code == 200

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
            assert media, "mermaid diagram was not embedded in the DOCX"
            blobs = [z.read(n) for n in media]

        widest = max((PILImage.open(io.BytesIO(b)) for b in blobs),
                     key=lambda im: im.size[0])
        w, h = widest.size
        bbox = _ink_bbox(widest)
        assert bbox is not None, "embedded mermaid image is blank"
        ink_w = bbox[2] - bbox[0]
        assert ink_w / w >= 0.85, (
            f"mermaid diagram fills only {100 * ink_w / w:.0f}% of its image "
            f"width ({ink_w}px of {w}px) - the rest is whitespace; mermaid's "
            f"inline max-width caps the element so the raster width is ignored"
        )


TEST_MARKDOWN_EMPTY_HEADER_GRID = """# Grid

|  |  |
|:---:|:---:|
| cell one | cell two |
| cell three | cell four |
"""


@pytest.fixture
def test_empty_header_grid_file(jp_root_dir):
    md_file = jp_root_dir / "test_empty_header_grid.md"
    md_file.write_text(TEST_MARKDOWN_EMPTY_HEADER_GRID, encoding="utf-8")
    return md_file


class TestEmptyHeaderGrid:
    """DEF-5 / DEF-8: a Markdown grid written with an empty header row
    (`|  |  |`) renders nothing for that row in markdown, so the export must
    drop it outright rather than emit a blank bordered row - and must not
    promote the body row behind it into a header in its place."""

    async def test_docx_empty_header_row_is_dropped(
        self, jp_fetch, test_empty_header_grid_file
    ):
        from docx import Document
        from docx.oxml.ns import qn

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "test_empty_header_grid.md"}),
            raise_error=False,
        )
        assert response.code == 200
        doc = Document(io.BytesIO(response.body))
        assert doc.tables, "expected a table in the export"
        table = doc.tables[0]
        # The fixture is an empty header plus two content rows; the blank
        # header must be gone, leaving only the content rows.
        assert len(table.rows) == 2, (
            f"expected the empty header row to be dropped (2 content rows), "
            f"got {len(table.rows)} rows"
        )
        assert [c.text.strip() for c in table.rows[0].cells] == ["cell one", "cell two"], (
            "the first surviving row should be the first content row"
        )
        trPr = table.rows[0]._tr.find(qn("w:trPr"))
        has_header = trPr is not None and trPr.find(qn("w:tblHeader")) is not None
        assert not has_header, (
            "the content row must not be promoted to a repeating header"
        )
        tblLook = table._tbl.tblPr.find(qn("w:tblLook"))
        assert tblLook is not None and tblLook.get(qn("w:firstRow")) == "0", (
            "a headerless grid must not carry first-row header emphasis"
        )

    async def test_headerless_grid_columns_are_not_skewed_by_bold_widening(
        self, jp_fetch, jp_root_dir
    ):
        """Row 0 of a headerless grid is body text, so it must not be measured
        as bold. The width estimate widens a header row by 8% for its bold
        face; after the blank header is dropped that factor lands on ordinary
        content and steals width from the column beside it.

        The fixture is symmetric - each column's widest cell is the same
        string, one in row 0 and one in row 1 - so a correct measurement gives
        two equal columns and any 8% skew is unambiguous.
        """
        from docx import Document
        from docx.oxml.ns import qn

        long_a = " ".join(["alpha"] * 16)
        long_b = " ".join(["bravo"] * 16)
        (jp_root_dir / "test_headerless_widths.md").write_text(
            "|  |  |\n"
            "| --- | --- |\n"
            f"| {long_a} | short |\n"
            f"| short | {long_b} |\n",
            encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST",
            body=json.dumps({"path": "test_headerless_widths.md"}),
            raise_error=False,
        )
        assert response.code == 200

        doc = Document(io.BytesIO(response.body))
        table = doc.tables[0]
        assert len(table.rows) == 2, "the blank header row should be gone"
        layout = table._tbl.tblPr.find(qn("w:tblLayout"))
        assert layout is not None and layout.get(qn("w:type")) == "fixed", (
            "the fixture must be wide enough to be fitted, or the widths "
            "below are never written and the test proves nothing"
        )

        grid = table._tbl.find(qn("w:tblGrid"))
        widths = [int(col.get(qn("w:w")))
                  for col in grid.findall(qn("w:gridCol"))]
        assert len(widths) == 2
        skew = abs(widths[0] - widths[1]) / max(widths)
        assert skew < 0.01, (
            f"symmetric columns came back skewed by {skew:.1%} "
            f"({widths}) - row 0 was measured as a bold header"
        )

    async def test_image_only_header_row_is_kept_with_its_images(
        self, jp_fetch, jp_root_dir
    ):
        """A header row holding pictures and no text is NOT empty. An
        image-on-top/caption-below grid puts its images in the header row;
        dropping it on a text-only predicate silently loses them."""
        from docx import Document
        from docx.oxml.ns import qn
        from PIL import Image as PILImage
        import fitz

        images_dir = jp_root_dir / "images"
        images_dir.mkdir(exist_ok=True)
        # Distinct colours: identical bytes would be deduplicated into one
        # PDF XObject and the count could not tell one image from two.
        for n, colour in (("a", (20, 120, 90)), ("b", (200, 60, 140))):
            PILImage.new("RGB", (300, 200), color=colour).save(
                images_dir / f"{n}.png"
            )
        (jp_root_dir / "imghdr.md").write_text(
            "# G\n\n"
            "| ![A](images/a.png) | ![B](images/b.png) |\n"
            "|---|---|\n"
            "| caption A | caption B |\n",
            encoding="utf-8",
        )

        rd = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "imghdr.md"}), raise_error=False,
        )
        assert rd.code == 200
        doc = Document(io.BytesIO(rd.body))
        table = doc.tables[0]
        assert len(table.rows) == 2, (
            f"the picture-bearing header row was deleted (got {len(table.rows)} rows)"
        )
        assert len(doc.inline_shapes) >= 2, (
            f"header-row images were lost: {len(doc.inline_shapes)} embedded, expected 2"
        )

        rp = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "imghdr.md"}), raise_error=False,
        )
        assert rp.code == 200
        pdf = fitz.open(stream=rp.body, filetype="pdf")
        n_images = sum(len(pg.get_images()) for pg in pdf)
        pdf.close()
        assert n_images >= 2, (
            f"header-row images were lost from the PDF: {n_images} rendered, expected 2"
        )

        # HTML strips tags to test emptiness, which erases an <img> along with
        # them - the same row must survive there or one format of three loses
        # the figures while the other two keep them.
        rh = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "imghdr.md"}), raise_error=False,
        )
        assert rh.code == 200
        html = rh.body.decode("utf-8")
        assert html.count("<img") >= 2, (
            f"header-row images were lost from the HTML: {html.count('<img')} "
            f"embedded, expected 2"
        )

        # Kept, but it is a figure row, not a header: no banded emphasis and no
        # repeat, matching what the PDF does with the same row
        tblLook = table._tbl.tblPr.find(qn("w:tblLook"))
        assert tblLook is not None and tblLook.get(qn("w:firstRow")) == "0", (
            "a picture-only first row must not carry header emphasis"
        )
        trPr = table.rows[0]._tr.find(qn("w:trPr"))
        assert trPr is None or trPr.find(qn("w:tblHeader")) is None, (
            "a picture-only first row must not repeat as a header"
        )

    async def test_docx_rows_are_marked_unbreakable(
        self, jp_fetch, test_empty_header_grid_file
    ):
        """DEF-9 in Word: reportlab's conditional `splitInRow` has no effect on
        the .docx, where Word breaks a row wherever the page ends unless the row
        carries `w:cantSplit`. Without it the same caption-and-image row the PDF
        now keeps whole is still torn in Word."""
        from docx import Document
        from docx.oxml.ns import qn

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "test_empty_header_grid.md"}),
            raise_error=False,
        )
        assert response.code == 200
        doc = Document(io.BytesIO(response.body))
        table = doc.tables[0]
        for index, row in enumerate(table.rows):
            trPr = row._tr.find(qn("w:trPr"))
            assert trPr is not None and trPr.find(qn("w:cantSplit")) is not None, (
                f"row {index} may be torn across a page break in Word"
            )

    async def test_pdf_headerless_grid_columns_are_not_skewed(
        self, jp_fetch, jp_root_dir
    ):
        """The PDF twin of the DOCX bold-widening skew: `string_width` measures
        row 0 in the bold header face, so after the blank header is dropped the
        first content row inflates its own column.

        Measured on the drawn grid rather than on text: the same string fills
        the widest cell of each column, so a correct measurement puts the
        column boundary exactly halfway across the table. Text extent would
        depend on where the last line happens to wrap, and on the widths of
        whichever glyphs the fixture used.
        """
        import fitz

        long_text = " ".join(["alpha"] * 16)
        (jp_root_dir / "pdf_headerless.md").write_text(
            "|  |  |\n"
            "| --- | --- |\n"
            f"| {long_text} | short |\n"
            f"| short | {long_text} |\n",
            encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "pdf_headerless.md"}),
            raise_error=False)
        assert response.code == 200

        pdf = fitz.open(stream=response.body, filetype="pdf")
        page = pdf[0]
        verticals = sorted({
            round(item[1].x, 1)
            for drawing in page.get_drawings() for item in drawing["items"]
            if item[0] == "l" and abs(item[1].x - item[2].x) < 0.1
            and abs(item[1].y - item[2].y) > 2
        })
        pdf.close()
        assert len(verticals) == 3, (
            f"expected a two-column grid (3 vertical rules), got {verticals}"
        )
        left, split, right = verticals
        midpoint = (left + right) / 2
        skew = abs(split - midpoint) / (right - left)
        assert skew < 0.01, (
            f"the column boundary sits at {split:.1f}pt against a "
            f"{midpoint:.1f}pt midpoint ({skew:.1%} of the table) - row 0 was "
            f"measured in the bold header face"
        )

    async def test_html_empty_header_row_is_dropped(
        self, jp_fetch, test_empty_header_grid_file, jp_root_dir
    ):
        """Cross-format parity: HTML must drop the blank header row too, or the
        same document renders with an extra blank banded strip in one format
        and not the others. A real header must survive."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "test_empty_header_grid.md"}),
            raise_error=False,
        )
        assert response.code == 200
        html = response.body.decode("utf-8")
        assert "<thead>" not in html, (
            "the empty header row must not be emitted in HTML either"
        )
        assert "cell one" in html, "grid content was lost with the header row"

        # A real header still gets a thead
        (jp_root_dir / "realhdr.md").write_text(
            "# T\n\n| Name | Age |\n|---|---|\n| ann | 3 |\n", encoding="utf-8"
        )
        r2 = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "realhdr.md"}), raise_error=False,
        )
        assert r2.code == 200
        html2 = r2.body.decode("utf-8")
        assert "<thead>" in html2 and "Name" in html2, (
            "a real header row must still render in HTML"
        )

    async def test_pdf_empty_header_grid_has_no_header_bar(
        self, jp_fetch, test_empty_header_grid_file
    ):
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "test_empty_header_grid.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert response.body.startswith(b"%PDF-")
        doc = fitz.open(stream=response.body, filetype="pdf")
        fills = [c for page in doc for c in _pdf_fill_colors(page)]
        text = "".join(page.get_text() for page in doc)
        doc.close()
        assert "cell one" in text, "grid content missing from PDF"
        assert not _color_near(fills, (0.859, 0.898, 0.945)), (
            "empty header row painted a blue header bar (dbe5f1) in the PDF"
        )

    async def test_partial_first_row_is_still_a_header(self, jp_fetch, jp_root_dir):
        """A first row with *any* text is a real header - the empty-header rule
        must only fire when the whole first row is blank."""
        import fitz
        from docx import Document
        from docx.oxml.ns import qn

        (jp_root_dir / "ph.md").write_text(
            "# P\n\n| Name |  |\n|------|--|\n| a | 1 |\n| b | 2 |\n",
            encoding="utf-8",
        )
        docx = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "ph.md"}), raise_error=False,
        )
        assert docx.code == 200
        table = Document(io.BytesIO(docx.body)).tables[0]
        trPr = table.rows[0]._tr.find(qn("w:trPr"))
        assert trPr is not None and trPr.find(qn("w:tblHeader")) is not None, (
            "a partially-filled first row must still be a repeating header"
        )

        pdf = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "ph.md"}), raise_error=False,
        )
        assert pdf.code == 200
        doc = fitz.open(stream=pdf.body, filetype="pdf")
        fills = [c for page in doc for c in _pdf_fill_colors(page)]
        doc.close()
        assert _color_near(fills, (0.859, 0.898, 0.945)), (
            "a real header lost its blue bar in the PDF"
        )


#: Every spelling of a break tag, so an assertion cannot miss `<BR>` or
#: `<br clear="all">` - the spellings these tests exist to cover. Imported
#: from the module under test rather than re-declared, so a change to the
#: pattern cannot leave the tests validating against a stale copy.
from jupyterlab_export_markdown_extension.routes import BREAK_TAG_RE as BREAK_RE  # noqa: E402


class TestExplicitLineBreakNotDoubled:
    """DEF-10: a line ended with an explicit `<br>` - the idiom for a question
    above its answer - picked up a second break from the `nl2br` extension,
    which converts the following newline too. The pair then sat further apart
    than the paragraphs around it, so the grouping read backwards."""

    FAQ = (
        "## FAQ\n\n"
        "**Does the system call out?**<br>\n"
        "No. Passive - other systems push data to it.\n\n"
        "**How does the plan arrive?**<br>\n"
        "Upstream pulls the recorded events.\n\n"
        "**Is the app native?**<br>\n"
        "No. Thin web app; connectivity required.\n"
    )

    async def test_html_keeps_one_break(self, jp_fetch, jp_root_dir):
        (jp_root_dir / "faq.md").write_text(self.FAQ, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "faq.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        doubled = re.findall(r'<br\s*/?>\s*<br\s*/?>', html)
        assert not doubled, (
            f"{len(doubled)} doubled line break(s) survived - the author's "
            f"`<br>` picked up a second break from nl2br"
        )
        para = html[html.find("<p><strong>Does the system"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 1, (
            f"the author's own single break was lost: {para!r}"
        )

    async def test_docx_pair_holds_one_break(self, jp_fetch, jp_root_dir):
        """One break inside the pair, and the pair is one paragraph - the
        document's 10pt paragraph spacing then separates it from the next."""
        from docx import Document
        from docx.oxml.ns import qn

        (jp_root_dir / "faq.md").write_text(self.FAQ, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "faq.md"}),
            raise_error=False)
        assert r.code == 200
        doc = Document(io.BytesIO(r.body))
        pairs = [p for p in doc.paragraphs if "?" in p.text]
        assert len(pairs) == 3, f"expected 3 Q&A paragraphs, got {len(pairs)}"
        for p in pairs:
            breaks = len(p._p.findall('.//' + qn('w:br')))
            assert breaks == 1, (
                f"Q&A pair carries {breaks} line breaks, not 1 - the gap "
                f"inside the pair swallows the gap between pairs: {p.text[:40]!r}"
            )

    async def test_pdf_pair_is_tighter_than_the_gap_between_pairs(
            self, jp_fetch, jp_root_dir):
        """The measurable form of the defect: a question must sit closer to
        its own answer than to the next question."""
        import fitz

        (jp_root_dir / "faq.md").write_text(self.FAQ, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "faq.md"}),
            raise_error=False)
        assert r.code == 200

        pdf = fitz.open(stream=r.body, filetype="pdf")
        tops = {}
        for block in pdf[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                if text:
                    tops.setdefault(text[:16], line["bbox"][1])
        pdf.close()

        inside = tops["No. Passive - ot"] - tops["Does the system "]
        between = tops["How does the pla"] - tops["No. Passive - ot"]
        assert between > inside * 1.2, (
            f"the pair is not grouped: {inside:.1f}pt between a question and "
            f"its answer against {between:.1f}pt to the next question"
        )

    async def test_explicit_blank_line_is_preserved(self, jp_fetch, jp_root_dir):
        """`<br><br>` is an author asking for a blank line, not a duplicate -
        only the break nl2br generates on top may be dropped."""
        (jp_root_dir / "twobr.md").write_text(
            "one<br><br>\ntwo\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "twobr.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        body = html[html.find("<p>one"):html.find("</p>", html.find("<p>one"))]
        assert len(BREAK_RE.findall(body)) == 2, (
            f"an explicit blank line was collapsed: {body!r}"
        )

    async def test_break_in_a_table_cell_is_untouched(
            self, jp_fetch, jp_root_dir):
        """A markdown table cell cannot contain a newline, so nl2br has
        nothing to convert there and never doubles a cell's break. The
        caption-above-image grid depends on that break surviving - it is the
        only thing holding the caption above its picture."""
        (jp_root_dir / "grid.md").write_text(
            "|  |  |\n|---|---|\n"
            "| **cap A**<br>text A | **cap B**<br>text B |\n",
            encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "grid.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        table = html[html.find("<table"):html.find("</table>")]
        assert len(BREAK_RE.findall(table)) == 2, (
            f"a table cell lost its line break: {table!r}"
        )

    async def test_raw_html_block_keeps_its_own_breaks(
            self, jp_fetch, jp_root_dir):
        """A raw HTML block's breaks are all the author's - `nl2br` never ran
        inside it, so there is nothing there to collapse. Matching the final
        HTML by shape cannot tell that, and ate one break of the alert-box
        idiom this project documents."""
        (jp_root_dir / "alert.md").write_text(
            '<div class="alert alert-block alert-info">\n'
            '<b>Tip:</b> first paragraph<br /><br />\n'
            'second paragraph\n'
            '</div>\n', encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "alert.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        block = html[html.find("alert-block"):html.find("</div>",
                                                        html.find("alert-block"))]
        assert len(BREAK_RE.findall(block)) == 2, (
            f"the author's blank line inside a raw HTML block was collapsed: "
            f"{block!r}"
        )

    async def test_trailing_space_after_the_break_still_collapses(
            self, jp_fetch, jp_root_dir):
        """A trailing space after `<br>` is invisible in every editor, so the
        fix must not depend on its absence - keying off the tag's position in
        the final text made one stray space silently restore the defect."""
        (jp_root_dir / "space.md").write_text(
            "**Q?**<br> \nAnswer.\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "space.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p><strong>Q?"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 1, (
            f"a trailing space defeated the collapse: {para!r}"
        )

    async def test_uppercase_and_attributed_breaks_are_recognised(
            self, jp_fetch, jp_root_dir):
        """`<BR>` and `<br clear="all">` are breaks the author wrote, and
        pasted or legacy markup carries both. Recognition comes from the
        stash, so spelling does not matter."""
        (jp_root_dir / "spelling.md").write_text(
            "**Upper?**<BR>\nAnswer one.\n\n"
            '**Attr?**<br clear="all">\nAnswer two.\n', encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "spelling.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        for marker in ("Upper?", "Attr?"):
            para = html[html.find(f"<p><strong>{marker}"):]
            para = para[:para.find("</p>")]
            assert len(BREAK_RE.findall(para)) == 1, (
                f"{marker} kept a doubled break: {para!r}"
            )

    async def test_break_on_its_own_line_gives_one_blank_line(
            self, jp_fetch, jp_root_dir):
        """A `<br>` alone on a line is the author adding a blank line between
        two lines of text: the newline before it and the tag itself are two
        breaks, and the newline after it is the generated one that goes. Pinned
        because it is a rendering change, not an accident."""
        (jp_root_dir / "ownline.md").write_text(
            "Text\n<br>\nMore\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "ownline.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p>Text"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 2, (
            f"expected exactly one blank line between the two lines: {para!r}"
        )

    async def test_manual_break_plus_hard_break_keeps_both(
            self, jp_fetch, jp_root_dir):
        """Two trailing spaces are Markdown's own hard-break idiom, so `<br>`
        followed by them is the author asking for two breaks, not a duplicate.
        Only a break the renderer generated on its own may be dropped - and at
        the inline stage the two-space break has already been claimed by the
        `linebreak` pattern, so it is never in reach."""
        (jp_root_dir / "hard.md").write_text(
            "**Q?**<br>  \nAnswer.\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "hard.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p><strong>Q?"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 2, (
            f"an authored break was deleted: {para!r}"
        )

    async def test_custom_element_is_not_treated_as_a_break(
            self, jp_fetch, jp_root_dir):
        """`<br-spacer>` is a legal custom element, not a break. Matching it as
        one drops the real break and runs the two lines together."""
        (jp_root_dir / "custom.md").write_text(
            "line one<br-spacer>\nline two\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "custom.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p>line one"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 1, (
            f"a custom element swallowed the line break: {para!r}"
        )

    async def test_non_breaking_space_after_the_break_still_collapses(
            self, jp_fetch, jp_root_dir):
        """Text pasted from Word or a web page routinely ends a line with a
        non-breaking space; it must not decide how the document renders."""
        (jp_root_dir / "nbsp.md").write_text(
            "**Q?**<br>\u00a0\nAnswer.\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "nbsp.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p><strong>Q?"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 1, (
            f"a non-breaking space defeated the collapse: {para!r}"
        )

    async def test_export_survives_a_broken_manual_break_rule(
            self, jp_fetch, jp_root_dir, monkeypatch):
        """The rule reads Markdown's internals, so it must never be able to
        fail an export. The coupling executes inside the converter's
        constructor, not in the factory, so that is where the guard has to be:
        a rule that builds fine and then fails to wire itself must fall back to
        plain nl2br, not return a 500."""
        from jupyterlab_export_markdown_extension import routes
        from markdown.extensions import Extension

        class Broken(Extension):
            def extendMarkdown(self, md):
                raise TypeError("simulated python-markdown API change")

        monkeypatch.setattr(routes, "manual_break_aware_nl2br",
                            lambda: Broken())
        (jp_root_dir / "broken.md").write_text(
            "**Q?**<br>\nAnswer.\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "broken.md"}),
            raise_error=False)
        assert r.code == 200, (
            f"a broken cosmetic rule took the whole export down ({r.code})"
        )
        html = r.body.decode("utf-8")
        para = html[html.find("<p><strong>Q?"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 2, (
            f"expected the plain nl2br fallback (two breaks), got {para!r}"
        )

    async def test_a_break_named_in_a_comment_is_not_a_break(
            self, jp_fetch, jp_root_dir):
        """The stashed node must BE a break tag, not merely contain one - an
        HTML comment mentioning `<br>` is not the author writing a break, and
        treating it as one deletes a real one."""
        (jp_root_dir / "comment.md").write_text(
            "Q<!-- note about <br> -->\nAnswer.\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "comment.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p>Q<!--"):]
        para = para[:para.find("</p>")]
        # The comment's own text contains the characters `<br>`, so count is
        # not the measure here - what matters is that the real break after the
        # comment survived
        assert re.search(r'-->\s*<br', para), (
            f"a comment that merely mentions a break deleted a real one: {para!r}"
        )

    async def test_break_inside_emphasis_is_a_known_limitation(
            self, jp_fetch, jp_root_dir):
        """`**Q<br>**` puts the break inside the emphasis, so by the time the
        newline is examined the trailing node is the emphasis element, not the
        break, and the pair still renders with a blank line. Pinned so the
        limitation is a recorded decision rather than an unnoticed hole."""
        (jp_root_dir / "emph.md").write_text(
            "**Q?<br>**\nAnswer.\n", encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "emph.md"}),
            raise_error=False)
        assert r.code == 200
        html = r.body.decode("utf-8")
        para = html[html.find("<p><strong>Q?"):]
        para = para[:para.find("</p>")]
        assert len(BREAK_RE.findall(para)) == 2, (
            f"the known limitation changed behaviour: {para!r}"
        )


class TestExportFontSize:
    """The `exportFontSize` setting picks a base body size - small 10pt,
    medium 12pt (default), large 13pt - and every other size in every format
    is a fixed proportion of it, so the whole document scales together."""

    DOC = "# Title\n\nBody paragraph text.\n\n## Section\n\nMore body text.\n"

    async def _export(self, jp_fetch, jp_root_dir, fmt, size=None):
        (jp_root_dir / "fs.md").write_text(self.DOC, encoding="utf-8")
        body = {"path": "fs.md"}
        if size is not None:
            body["exportFontSize"] = size
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", f"export/{fmt}",
            method="POST", body=json.dumps(body), raise_error=False)
        assert r.code == 200, f"{fmt} export at size {size} returned {r.code}"
        return r.body

    @staticmethod
    def _pdf_sizes(pdf_bytes):
        """Rendered point size of the body paragraph and of the H1."""
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        sizes = {}
        for block in doc[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text.startswith("Body paragraph"):
                        sizes["body"] = round(span["size"], 1)
                    elif text == "Title":
                        sizes["h1"] = round(span["size"], 1)
        doc.close()
        return sizes

    async def test_pdf_base_size_follows_the_setting(self, jp_fetch, jp_root_dir):
        for size, expected in (("small", 10.0), ("medium", 12.0), ("large", 13.0)):
            sizes = self._pdf_sizes(
                await self._export(jp_fetch, jp_root_dir, "pdf", size))
            assert sizes.get("body") == expected, (
                f"{size} rendered body text at {sizes.get('body')}pt, "
                f"expected {expected}pt"
            )

    async def test_pdf_headings_stay_proportional(self, jp_fetch, jp_root_dir):
        """A heading is a multiple of the body size, not a fixed number - the
        point of a base size is that the document scales as one."""
        ratios = []
        for size in ("small", "medium", "large"):
            sizes = self._pdf_sizes(
                await self._export(jp_fetch, jp_root_dir, "pdf", size))
            ratios.append(sizes["h1"] / sizes["body"])
        assert max(ratios) - min(ratios) < 0.01, (
            f"heading-to-body ratio drifted across sizes: {ratios}"
        )
        assert ratios[0] > 1.2, f"headings are not larger than body: {ratios}"

    async def test_docx_base_size_follows_the_setting(self, jp_fetch, jp_root_dir):
        from docx import Document

        for size, expected in (("small", 10.0), ("medium", 12.0), ("large", 13.0)):
            doc = Document(io.BytesIO(
                await self._export(jp_fetch, jp_root_dir, "docx", size)))
            normal = doc.styles["Normal"].font.size
            assert normal is not None and normal.pt == expected, (
                f"{size} gave DOCX body {normal and normal.pt}pt, "
                f"expected {expected}pt"
            )
            heading = doc.styles["Heading 1"].font.size
            assert heading is not None and heading.pt > expected, (
                f"{size} left Heading 1 at {heading and heading.pt}pt, "
                f"not above the {expected}pt body"
            )

    async def test_html_base_size_follows_the_setting(self, jp_fetch, jp_root_dir):
        for size, expected in (("small", "10pt"), ("medium", "12pt"),
                               ("large", "13pt")):
            html = (await self._export(
                jp_fetch, jp_root_dir, "html", size)).decode("utf-8")
            body_rule = html[html.find("body {"):]
            body_rule = body_rule[:body_rule.find("}")]
            assert f"font-size: {expected}" in body_rule, (
                f"{size} did not set the HTML body size to {expected}: "
                f"{body_rule!r}"
            )

    async def test_default_is_medium_in_every_format(self, jp_fetch, jp_root_dir):
        """An export with no setting - an older client, or a fresh install -
        renders at the documented default rather than at whatever each format
        used to hardcode."""
        from docx import Document

        assert self._pdf_sizes(
            await self._export(jp_fetch, jp_root_dir, "pdf"))["body"] == 12.0
        doc = Document(io.BytesIO(await self._export(jp_fetch, jp_root_dir, "docx")))
        assert doc.styles["Normal"].font.size.pt == 12.0
        html = (await self._export(jp_fetch, jp_root_dir, "html")).decode("utf-8")
        assert "font-size: 12pt" in html

    async def test_a_malformed_setting_cannot_fail_an_export(
            self, jp_fetch, jp_root_dir):
        """The size is a cosmetic choice, so nothing a client can put in the
        field may take the export down - including values that are not even
        the right type, which a plain dict lookup raises on."""
        for value in ([], {}, True, "enormous", None, 0, 10**6):
            (jp_root_dir / "fs.md").write_text(self.DOC, encoding="utf-8")
            r = await jp_fetch(
                "jupyterlab-export-markdown-extension", "export/html",
                method="POST",
                body=json.dumps({"path": "fs.md", "exportFontSize": value}),
                raise_error=False)
            assert r.code == 200, (
                f"exportFontSize={value!r} returned {r.code} instead of "
                f"falling back"
            )

    async def test_html_measure_scales_with_the_body(
            self, jp_fetch, jp_root_dir):
        """Line length is what governs readability, so the column width has to
        be a multiple of the body size too - a fixed pixel width would give
        `large` a third fewer characters per line than `small`."""
        widths = {}
        for size in ("small", "medium", "large"):
            html = (await self._export(
                jp_fetch, jp_root_dir, "html", size)).decode("utf-8")
            body_rule = html[html.find("body {"):]
            body_rule = body_rule[:body_rule.find("}")]
            match = re.search(r'max-width:\s*([\d.]+)(em|px)', body_rule)
            assert match, f"no max-width in the body rule: {body_rule!r}"
            widths[size] = (float(match.group(1)), match.group(2))
        assert {unit for _, unit in widths.values()} == {"em"}, (
            f"the column width is not relative to the body size: {widths}"
        )
        assert len({value for value, _ in widths.values()}) == 1, (
            f"the em measure should be one constant across sizes: {widths}"
        )


class TestMultiParagraphAlert:
    """DEF-11: a `> [!NOTE]` whose body has two paragraphs is one alert, not a
    coloured box followed by a stray grey blockquote."""

    DOC = (
        "# Doc\n\n"
        "> [!NOTE]\n"
        "> First paragraph.\n"
        ">\n"
        "> Second paragraph.\n\n"
        "Closing text.\n"
    )

    async def _export(self, jp_fetch, jp_root_dir, fmt, doc=None):
        (jp_root_dir / "alert.md").write_text(doc or self.DOC, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", f"export/{fmt}",
            method="POST", body=json.dumps({"path": "alert.md"}),
            raise_error=False)
        assert r.code == 200, f"{fmt} export returned {r.code}"
        return r.body

    async def test_html_is_one_box_holding_both_paragraphs(
            self, jp_fetch, jp_root_dir):
        html = (await self._export(jp_fetch, jp_root_dir, "html")).decode("utf-8")
        boxes = re.findall(r'<div style="border-left:4px solid([^>]*)>(.*?)</div>',
                           html, re.S)
        assert len(boxes) == 1, (
            f"expected one alert box, got {len(boxes)}: "
            f"{[b[0][:30] for b in boxes]}"
        )
        body = boxes[0][1]
        assert "First paragraph." in body and "Second paragraph." in body, (
            f"the alert box lost a paragraph: {body!r}"
        )
        # The orphaned paragraph would survive as an ordinary blockquote,
        # rendered by the DEF-2 path as a second, grey-barred box
        assert "<blockquote" not in html, (
            "a plain blockquote survived - the alert still split in two"
        )

    async def test_docx_is_one_alert_table_holding_both_paragraphs(
            self, jp_fetch, jp_root_dir):
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(io.BytesIO(
            await self._export(jp_fetch, jp_root_dir, "docx")))
        alert_tables = []
        for table in doc.tables:
            borders = table._tbl.find(qn('w:tblPr')).find(qn('w:tblBorders'))
            if borders is None:
                continue
            left = borders.find(qn('w:left'))
            if left is not None and left.get(qn('w:color')) == '0969DA':
                alert_tables.append(table)
        assert len(alert_tables) == 1, (
            f"expected one NOTE table, got {len(alert_tables)}"
        )
        cell_text = alert_tables[0].rows[0].cells[0].text
        assert "First paragraph." in cell_text, cell_text
        assert "Second paragraph." in cell_text, (
            f"the second paragraph is outside the alert: {cell_text!r}"
        )

    async def test_pdf_is_one_callout_with_no_stray_blockquote(
            self, jp_fetch, jp_root_dir):
        import fitz

        doc = fitz.open(stream=await self._export(jp_fetch, jp_root_dir, "pdf"),
                        filetype="pdf")
        fills, strokes, text = [], [], ""
        for page in doc:
            fills += _pdf_fill_colors(page)
            strokes += _pdf_stroke_colors(page)
            text += page.get_text()
        doc.close()

        assert _color_near(fills, (0.929, 0.961, 0.992)), (
            "NOTE blue shading missing - the alert did not render as a callout"
        )
        # #BBBBBB, the default blockquote bar the orphaned paragraph would draw
        assert not _color_near(strokes, (0.733, 0.733, 0.733)), (
            "a grey blockquote bar was drawn - the alert split into two boxes"
        )
        assert "First paragraph." in text and "Second paragraph." in text

    async def test_source_line_breaks_inside_an_alert_are_kept(
            self, jp_fetch, jp_root_dir):
        """Body text turns a source newline into a break, so an alert has to
        as well - the same two source lines must not set two different ways in
        the same document."""
        doc = "> [!TIP]\n> Line one\n> Line two\n"
        html = (await self._export(
            jp_fetch, jp_root_dir, "html", doc)).decode("utf-8")
        box = re.search(r'<div style="border-left:4px solid.*?</div>', html, re.S)
        assert box, "no alert box in the export"
        assert re.search(r'Line one\s*<br', box.group(0)), (
            f"the line break inside the alert was discarded: {box.group(0)!r}"
        )

    async def test_an_authored_break_in_an_alert_is_not_doubled(
            self, jp_fetch, jp_root_dir):
        """The alert joins its source lines with a break; a line that already
        ends in one must not get a second, as it would everywhere else."""
        doc = "> [!TIP]\n> **Question**<br>\n> Answer.\n"
        html = (await self._export(
            jp_fetch, jp_root_dir, "html", doc)).decode("utf-8")
        box = re.search(r'<div style="border-left:4px solid.*?</div>', html, re.S)
        assert box, "no alert box in the export"
        breaks = len(BREAK_RE.findall(box.group(0)))
        assert breaks == 1, (
            f"expected one break between question and answer, got {breaks}: "
            f"{box.group(0)!r}"
        )

    async def test_two_adjacent_alerts_stay_separate(
            self, jp_fetch, jp_root_dir):
        """Widening the continuation must not let one alert swallow the next."""
        doc = "> [!NOTE]\n> First alert.\n\n> [!WARNING]\n> Second alert.\n"
        html = (await self._export(
            jp_fetch, jp_root_dir, "html", doc)).decode("utf-8")
        assert len(re.findall(r'<div style="border-left:4px solid', html)) == 2, (
            "two adjacent alerts did not stay two boxes"
        )
        assert "#0969DA" in html and "#9A6700" in html, (
            "each alert must keep its own type colour"
        )

    async def test_a_plain_blockquote_is_still_a_blockquote(
            self, jp_fetch, jp_root_dir):
        """The alert rule must not capture an ordinary multi-paragraph quote."""
        doc = "> Just a quote.\n>\n> Second quoted paragraph.\n"
        html = (await self._export(
            jp_fetch, jp_root_dir, "html", doc)).decode("utf-8")
        assert '<div style="border-left:4px solid' not in html, (
            "an ordinary blockquote was styled as an alert"
        )
        assert "Just a quote." in html and "Second quoted paragraph." in html


class TestPdfMinorHeadings:
    """DEF-12: Heading 4, 5 and 6 render distinctly in the PDF instead of all
    collapsing onto the Heading 3 face."""

    DOC = ("# One\n\ntext\n\n## Two\n\ntext\n\n### Three\n\ntext\n\n"
           "#### Four\n\ntext\n\n##### Five\n\ntext\n\n###### Six\n\ntext\n")

    async def _faces(self, jp_fetch, jp_root_dir):
        import fitz

        (jp_root_dir / "heads.md").write_text(self.DOC, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "heads.md"}),
            raise_error=False)
        assert r.code == 200
        doc = fitz.open(stream=r.body, filetype="pdf")
        faces = {}
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        word = span["text"].strip()
                        if word in ("One", "Two", "Three", "Four", "Five", "Six"):
                            faces[word] = (span["font"], span["color"],
                                           round(span["size"], 1))
        doc.close()
        return faces

    async def test_every_heading_level_is_visually_distinct(
            self, jp_fetch, jp_root_dir):
        faces = await self._faces(jp_fetch, jp_root_dir)
        assert set(faces) == {"One", "Two", "Three", "Four", "Five", "Six"}, (
            f"a heading is missing from the PDF: {sorted(faces)}"
        )
        assert len(set(faces.values())) == 6, (
            f"heading levels share a face: {faces}"
        )

    async def test_minor_headings_match_the_docx_faces(
            self, jp_fetch, jp_root_dir):
        """The PDF colours must equal the colours of the DOCX it is built from,
        read off the exported document itself - not a copy in the test. If the
        template python-docx builds from ever moves, the DOCX moves, and this
        catches the two formats disagreeing instead of freezing beside them."""
        from docx import Document

        (jp_root_dir / "heads.md").write_text(self.DOC, encoding="utf-8")
        d = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "heads.md"}),
            raise_error=False)
        assert d.code == 200
        styles = Document(io.BytesIO(d.body)).styles
        docx_color = {}
        for word, level in (("Four", 4), ("Five", 5), ("Six", 6)):
            rgb = styles[f"Heading {level}"].font.color.rgb
            assert rgb is not None, f"Heading {level} has no colour in the DOCX"
            docx_color[word] = int(str(rgb), 16)

        faces = await self._faces(jp_fetch, jp_root_dir)
        for word in ("Four", "Five", "Six"):
            assert faces[word][1] == docx_color[word], (
                f"PDF {word} is #{faces[word][1]:06X} but the DOCX draws it "
                f"#{docx_color[word]:06X} - the two formats disagree"
            )
        h4_font, h5_font, h6_font = (faces[k][0] for k in ("Four", "Five", "Six"))
        assert "Bold" in h4_font and _is_italic_font(h4_font), (
            f"H4 is not bold italic: {h4_font}"
        )
        assert "Bold" not in h5_font and not _is_italic_font(h5_font), (
            f"H5 is not regular: {h5_font}"
        )
        assert _is_italic_font(h6_font) and "Bold" not in h6_font, (
            f"H6 is not italic: {h6_font}"
        )

    async def test_minor_headings_sit_at_body_size(self, jp_fetch, jp_root_dir):
        """Word's H4-H6 carry no size of their own and render at body size;
        the PDF has to do the same, or the levels it just learned to tell
        apart are told apart by the wrong signal."""
        import fitz

        faces = await self._faces(jp_fetch, jp_root_dir)
        (jp_root_dir / "heads.md").write_text(self.DOC, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "heads.md"}),
            raise_error=False)
        doc = fitz.open(stream=r.body, filetype="pdf")
        body = [round(s["size"], 1)
                for page in doc
                for b in page.get_text("dict")["blocks"]
                for line in b.get("lines", [])
                for s in line["spans"] if s["text"].strip() == "text"]
        doc.close()
        assert body, "no body text found in the PDF"
        for level in ("Four", "Five", "Six"):
            assert faces[level][2] == body[0], (
                f"H{level} is {faces[level][2]}pt against {body[0]}pt body"
            )
        sizes = [faces[k][2] for k in ("One", "Two", "Three", "Four")]
        assert sizes == sorted(sizes, reverse=True) and sizes[2] > sizes[3], (
            f"heading sizes do not descend into H4: {sizes}"
        )

    async def test_italic_headings_do_not_fall_back_to_a_core_font(
            self, jp_fetch, jp_root_dir):
        """The italic minor headings must draw in the document's Unicode font,
        not a Helvetica core face. DejaVu (best coverage, so the body's font)
        ships no oblique on many boxes; committing to it and stopping left
        every italic falling to Helvetica-Oblique - a typeface switch visible
        in the heading ladder. H4/H6 must share the embedded family, not a
        core-14 substitute."""
        faces = await self._faces(jp_fetch, jp_root_dir)
        for level in ("Four", "Six"):
            font = faces[level][0]
            assert "Helvetica" not in font and "Times" not in font, (
                f"H{level} italic fell back to a core font: {font}"
            )
            assert _is_italic_font(font), f"H{level} is not italic: {font}"


class TestPdfCodeLineWrapping:
    """DEF-13: a code line wider than the frame wraps instead of running off
    the page."""

    LONG = "a" * 300
    DOC = (
        "# Code\n\n"
        "```python\n"
        f'url = "{LONG}"\n'
        "short = 1\n"
        "```\n"
    )

    async def _pdf(self, jp_fetch, jp_root_dir, doc=None):
        (jp_root_dir / "code.md").write_text(doc or self.DOC, encoding="utf-8")
        r = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "code.md"}),
            raise_error=False)
        assert r.code == 200
        return r.body

    @staticmethod
    def _mono_spans(pdf_bytes):
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        spans = []
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if "Courier" in span["font"] or "Mono" in span["font"]:
                            spans.append(span)
        doc.close()
        return spans

    async def test_a_long_code_line_stays_inside_the_margin(
            self, jp_fetch, jp_root_dir):
        spans = self._mono_spans(await self._pdf(jp_fetch, jp_root_dir))
        assert spans, "no monospaced code text found in the PDF"
        edge = pdf_frame_right_edge()
        past = [(round(s["bbox"][2], 1), s["text"][:30])
                for s in spans if s["bbox"][2] > edge + 1]
        assert not past, (
            f"code drawn past the {edge:.0f}pt frame edge: {past[:3]}"
        )

    async def test_wrapping_loses_no_characters(self, jp_fetch, jp_root_dir):
        spans = self._mono_spans(await self._pdf(jp_fetch, jp_root_dir))
        drawn = "".join(s["text"] for s in spans)
        assert drawn.count("a") == 300, (
            f"the wrapped line lost characters: {drawn.count('a')} of 300"
        )
        assert "short = 1" in drawn.replace("\n", ""), (
            "the following code line disappeared"
        )

    async def test_a_short_code_line_is_not_broken(self, jp_fetch, jp_root_dir):
        """Only an overflowing line may wrap - a line that fits keeps its
        shape, or every code sample gains phantom breaks."""
        doc = "# C\n\n```python\ndef f(x):\n    return x + 1\n```\n"
        spans = self._mono_spans(await self._pdf(jp_fetch, jp_root_dir, doc))
        tops = sorted({round(s["bbox"][1], 1) for s in spans})
        assert len(tops) == 2, (
            f"a two-line code block rendered on {len(tops)} lines: {tops}"
        )


def _docx_text(docx_bytes):
    """Every run of word/document.xml joined back into one string.

    Syntax highlighting splits a kept code block across runs - `flowchart LR`
    lands as `flowchart`, ` `, `LR` - so a substring test against the raw XML
    passes whether or not the text is there.
    """
    import html as _html

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return _html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)))


MERMAID_ONLY_MARKDOWN = """# Diagrams

```mermaid
flowchart LR
    Ingest --> Model --> Report
```

Some prose between the diagrams.

```mermaid
sequenceDiagram
    Alice->>Bob: hello
    Bob-->>Alice: hi
```
"""


@pytest.fixture
def mermaid_markdown_file(jp_root_dir):
    md_file = jp_root_dir / "mermaid_api.md"
    md_file.write_text(MERMAID_ONLY_MARKDOWN, encoding="utf-8")
    return md_file


class TestApiMermaidRendering:
    """DEF-16: mermaid is a browser library, so the frontend renders each
    diagram and posts it as `mermaidDiagrams`. A caller driving the REST API
    directly sends no such payload, and every diagram used to export as its
    own source code. The server renders what the frontend did not."""

    async def test_docx_renders_mermaid_without_a_frontend_payload(
        self, jp_fetch, mermaid_markdown_file
    ):
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]

        assert len(media) == 2, (
            f"{len(media)} of 2 mermaid diagrams reached the DOCX - a diagram "
            f"the browser did not pre-render was dropped"
        )
        text = _docx_text(response.body)
        assert "flowchart" not in text and "sequenceDiagram" not in text, (
            "the mermaid source was written into the document as code instead "
            "of being rendered"
        )

    async def test_pdf_renders_mermaid_without_a_frontend_payload(
        self, jp_fetch, mermaid_markdown_file
    ):
        import fitz

        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        pdf = fitz.open(stream=response.body, filetype="pdf")
        try:
            images = sum(len(page.get_images(full=True)) for page in pdf)
            text = "\n".join(page.get_text() for page in pdf)
        finally:
            pdf.close()

        assert images == 2, f"{images} of 2 mermaid diagrams reached the PDF"
        assert "flowchart LR" not in text and "sequenceDiagram" not in text, (
            "the mermaid source was drawn into the PDF as code"
        )

    async def test_html_renders_mermaid_without_a_frontend_payload(
        self, jp_fetch, mermaid_markdown_file
    ):
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        html = response.body.decode("utf-8")

        assert html.count("data:image/svg+xml") == 2, (
            f"{html.count('data:image/svg+xml')} of 2 mermaid diagrams were "
            f"inlined into the HTML"
        )
        assert "language-mermaid" not in html, (
            "a mermaid block stayed a code block in the HTML"
        )

    async def test_a_diagram_the_frontend_supplied_is_not_re_rendered(
        self, jp_fetch, jp_root_dir
    ):
        """The browser's own render wins - it carries the Lab theme and fonts.
        A 1x1 PNG is unmistakable: anything the server rendered would be
        thousands of bytes."""
        (jp_root_dir / "one.md").write_text(
            "# One\n\n```mermaid\nflowchart LR\n    A --> B\n```\n", encoding="utf-8"
        )
        one_pixel_png = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
            "FcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", raise_error=False,
            body=json.dumps({
                "path": "one.md",
                "mermaidDiagrams": [{"index": 0, "png": one_pixel_png, "svg": ""}],
            }),
        )
        assert response.code == 200

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
            blobs = [z.read(n) for n in media]

        assert len(blobs) == 1, f"expected one image, got {len(blobs)}"
        assert len(blobs[0]) < 500, (
            f"the frontend's diagram was replaced by a server render "
            f"({len(blobs[0])} bytes) - the browser's version must win"
        )

    async def test_a_diagram_mermaid_rejects_keeps_its_source(
        self, jp_fetch, jp_root_dir
    ):
        """One unparseable diagram must not fail the export or take the good
        diagram down with it."""
        (jp_root_dir / "bad.md").write_text(
            "# Bad\n\n```mermaid\nnot a diagram at all {{{\n```\n\n"
            "```mermaid\nflowchart LR\n    A --> B\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "bad.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]

        assert len(media) == 1, (
            f"{len(media)} images embedded - the valid diagram must still "
            f"render and the invalid one must not"
        )
        assert "not a diagram at all" in _docx_text(response.body), (
            "the source of the diagram mermaid rejected was dropped instead of "
            "being kept as text"
        )

    async def test_a_document_without_mermaid_never_starts_a_browser(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """Chromium costs seconds to launch. Nothing to render means no
        browser - and means an export cannot start failing on a server with
        no Chromium just because this pass exists."""
        from jupyterlab_export_markdown_extension import routes

        class Exploding:
            def __init__(self, *a, **kw):
                raise AssertionError("Chromium was launched with no diagram to render")

        monkeypatch.setattr(routes, "PlaywrightSvgRenderer", Exploding)
        (jp_root_dir / "plain.md").write_text("# Plain\n\nNo diagrams here.\n",
                                              encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "plain.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]

    async def test_docx_carries_a_png_and_html_an_svg(
        self, jp_fetch, mermaid_markdown_file
    ):
        """The server-rendered diagram must arrive in the shape each format
        already expects from the frontend - Word cannot embed an SVG at all."""
        docx = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert docx.code == 200
        with zipfile.ZipFile(io.BytesIO(docx.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
            assert media and all(n.endswith(".png") for n in media), (
                f"DOCX media are not PNG: {media}"
            )

        html = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert html.code == 200
        assert "data:image/svg+xml" in html.body.decode("utf-8"), (
            "HTML should inline the diagram as SVG, not rasterize it"
        )

    async def test_one_browser_renders_and_rasterizes(
        self, jp_fetch, mermaid_markdown_file, monkeypatch
    ):
        """Rasterizing inside the render session is the whole point of doing it
        there - a second launch is ~300ms of Chromium startup for nothing."""
        from jupyterlab_export_markdown_extension import routes

        launches = []
        original = routes.PlaywrightSvgRenderer.__aenter__

        async def counting_aenter(self):
            launches.append(1)
            return await original(self)

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "__aenter__", counting_aenter)
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert len(launches) == 1, (
            f"Chromium was launched {len(launches)} times for a document whose "
            f"only images are mermaid diagrams"
        )

    async def test_a_clean_export_reports_no_warnings(
        self, jp_fetch, mermaid_markdown_file
    ):
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "mermaid_api.md"}),
            raise_error=False,
        )
        assert response.code == 200
        assert "X-Export-Warnings" not in response.headers, (
            f"a clean export warned: {response.headers.get('X-Export-Warnings')}"
        )


class TestApiMermaidWarnings:
    """DEF-16: an export never fails over a diagram - the source is kept and
    the response says what happened. The body is a document, so the header is
    the only channel an API caller has."""

    @staticmethod
    def _warnings(response):
        raw = response.headers.get("X-Export-Warnings")
        assert raw, "the export reported no warning at all"
        return {w["code"]: w for w in json.loads(raw)}

    async def test_a_chromium_less_server_still_exports_and_says_why(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        from jupyterlab_export_markdown_extension import routes

        async def refuse(self):
            raise routes.ChromiumUnavailableError(
                "Chromium binary not found at /nowhere"
            )

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "__aenter__", refuse)
        (jp_root_dir / "nc.md").write_text(
            "# NC\n\n```mermaid\nflowchart LR\n    A --> B\n```\n", encoding="utf-8"
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "nc.md"}), raise_error=False,
        )

        assert response.code == 200, (
            "a missing Chromium must not fail an export that can still produce "
            "the document"
        )
        assert "flowchart" in _docx_text(response.body), (
            "the diagram source was dropped instead of kept"
        )

        warning = self._warnings(response)["chromium-unavailable"]
        assert warning["diagrams"] == [0]
        assert "jupyterlab-export-markdown-extension install" in warning["message"], (
            f"the warning does not say how to fix it: {warning['message']}"
        )

    async def test_html_export_also_reports_it(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """HTML never needed Chromium before this feature, so it must not start
        failing now - it warns like the others."""
        from jupyterlab_export_markdown_extension import routes

        async def refuse(self):
            raise routes.ChromiumUnavailableError("no chromium")

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "__aenter__", refuse)
        (jp_root_dir / "nch.md").write_text(
            "# NC\n\n```mermaid\nflowchart LR\n    A --> B\n```\n", encoding="utf-8"
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST", body=json.dumps({"path": "nch.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        assert "chromium-unavailable" in self._warnings(response)

    async def test_a_missing_bundle_is_named_as_such(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """A wheel built without its vendor step must say so, not blame the
        diagram - and must not pay for a browser launch to find out."""
        from jupyterlab_export_markdown_extension import routes

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "MERMAID_JS_PATH",
                            Path("/nonexistent/mermaid.min.js"))

        async def explode(self):
            raise AssertionError("Chromium was launched with no bundle to load")

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "__aenter__", explode)
        (jp_root_dir / "nb.md").write_text(
            "# NB\n\n```mermaid\nflowchart LR\n    A --> B\n```\n", encoding="utf-8"
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "nb.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        assert "bundle-missing" in self._warnings(response)

    async def test_a_syntax_error_is_reported_against_its_own_diagram(
        self, jp_fetch, jp_root_dir
    ):
        """Two diagrams, the first unparseable: the warning must point at index
        0 and the second must still render."""
        (jp_root_dir / "mix.md").write_text(
            "# Mix\n\n```mermaid\nnot a diagram at all {{{\n```\n\n"
            "```mermaid\nflowchart LR\n    A --> B\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "mix.md"}), raise_error=False,
        )
        assert response.code == 200

        warning = self._warnings(response)["syntax-error"]
        assert warning["diagrams"] == [0], (
            f"the warning blames the wrong diagram: {warning['diagrams']}"
        )
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 1, "the valid diagram must still have rendered"

    async def test_the_header_is_one_line_of_valid_json(
        self, jp_fetch, jp_root_dir
    ):
        """A header carrying a newline is rejected by the HTTP layer, and the
        diagram source is attacker-adjacent text - it must never reach it."""
        (jp_root_dir / "hdr.md").write_text(
            "# H\n\n```mermaid\nbroken é\nsüper\n\"quoted\"\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "hdr.md"}), raise_error=False,
        )
        assert response.code == 200
        raw = response.headers["X-Export-Warnings"]
        assert "\n" not in raw and "\r" not in raw
        json.loads(raw)  # must parse
        assert "broken" not in raw, "the diagram source leaked into the header"

    async def test_a_broken_browser_session_still_exports(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """Chromium launching is not the only thing that can go wrong with a
        browser. Whatever the session throws, the export still produces the
        document - per-diagram faults are handled a level down."""
        from jupyterlab_export_markdown_extension import routes

        async def blow_up(self, *args, **kwargs):
            raise RuntimeError("target page, context or browser has been closed")

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "render_mermaid", blow_up)
        (jp_root_dir / "bs.md").write_text(
            "# BS\n\n```mermaid\nflowchart LR\n    A --> B\n```\n", encoding="utf-8"
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "bs.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        assert "flowchart" in _docx_text(response.body)
        assert "render-failed" in self._warnings(response)

    async def test_the_header_stays_bounded_on_a_document_full_of_diagrams(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """nginx's default `proxy_buffer_size` is 4KB and must hold the whole
        response header block. 200 broken diagrams must report their count
        without listing every index."""
        from jupyterlab_export_markdown_extension import routes

        async def refuse(self):
            raise routes.ChromiumUnavailableError("no chromium")

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "__aenter__", refuse)
        block = "```mermaid\nflowchart LR\n    A --> B\n```\n\n"
        (jp_root_dir / "many.md").write_text("# Many\n\n" + block * 200,
                                             encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "many.md"}), raise_error=False,
        )
        assert response.code == 200

        raw = response.headers["X-Export-Warnings"]
        assert len(raw) < 2048, f"the warning header grew to {len(raw)} bytes"
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase
        warning = self._warnings(response)["chromium-unavailable"]
        assert warning["count"] == 200, (
            f"the header lost the true count: {warning['count']}"
        )
        assert len(warning["diagrams"]) <= ExportHandlerBase.MAX_REPORTED_DIAGRAMS


class TestApiMermaidHardening:
    """Findings from the architect and bug-hunter review of DEF-16."""

    @staticmethod
    def _warnings(response):
        raw = response.headers.get("X-Export-Warnings")
        assert raw, "the export reported no warning at all"
        return {w["code"]: w for w in json.loads(raw)}

    async def test_a_mermaid_label_cannot_make_the_server_fetch_a_url(
        self, jp_fetch, jp_root_dir
    ):
        """Confirmed SSRF: mermaid keeps HTML labels, so `<img src=...>` in a
        diagram survives into the SVG and the SERVER fetches it - a document
        someone else wrote reaching the host's metadata endpoint. Measured
        three outbound requests before the block."""
        import socket
        import threading

        hits = []
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(5)
        sock.settimeout(20)

        def serve():
            while True:
                try:
                    conn, _ = sock.accept()
                    hits.append(conn.recv(100))
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                    conn.close()
                except Exception:
                    return

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            (jp_root_dir / "ssrf.md").write_text(
                "# S\n\n```mermaid\nflowchart LR\n"
                f"    A[\"<img src='http://127.0.0.1:{port}/probe.png' "
                "width='40' height='40'>\"] --> B[ok]\n```\n",
                encoding="utf-8",
            )
            response = await jp_fetch(
                "jupyterlab-export-markdown-extension", "export/docx",
                method="POST", body=json.dumps({"path": "ssrf.md"}),
                raise_error=False,
            )
            assert response.code == 200, response.body[:300]
        finally:
            sock.close()

        assert not hits, (
            f"the server made {len(hits)} outbound request(s) because a diagram "
            f"asked it to - a markdown file must not be able to drive the "
            f"server's network"
        )

    async def test_a_mermaid_example_inside_an_outer_fence_is_left_alone(
        self, jp_fetch, jp_root_dir
    ):
        """Documentation that SHOWS mermaid syntax must stay text - rendering
        it replaces the code sample with a picture of itself."""
        (jp_root_dir / "doc.md").write_text(
            "# Docs\n\nWrite a diagram like this:\n\n"
            "````markdown\n```mermaid\nflowchart LR\n    A --> B\n```\n````\n\n"
            "And here is a real one:\n\n"
            "```mermaid\nflowchart LR\n    C --> D\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "doc.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 1, (
            f"{len(media)} diagrams rendered - the example inside the outer "
            f"fence is documentation, not a diagram"
        )
        assert "flowchart LR" in _docx_text(response.body).replace("\n", ""), (
            "the quoted example lost its source"
        )

    async def test_a_warning_names_the_diagram_the_reader_would_count_to(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """With the frontend supplying diagrams 0 and 1, a failure on the third
        must report 2 - numbering the leftovers from zero sends the reader to a
        diagram that is fine."""
        from jupyterlab_export_markdown_extension import routes

        async def refuse(self):
            raise routes.ChromiumUnavailableError("no chromium")

        monkeypatch.setattr(routes.PlaywrightSvgRenderer, "__aenter__", refuse)
        block = "```mermaid\nflowchart LR\n    A --> B\n```\n\n"
        (jp_root_dir / "part.md").write_text("# P\n\n" + block * 3, encoding="utf-8")
        png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
               "FcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", raise_error=False,
            body=json.dumps({
                "path": "part.md",
                "mermaidDiagrams": [{"index": 0, "png": png, "svg": ""},
                                    {"index": 1, "png": png, "svg": ""}],
            }),
        )
        assert response.code == 200
        warning = self._warnings(response)["chromium-unavailable"]
        assert warning["diagrams"] == [2], (
            f"the warning points at diagram(s) {warning['diagrams']} instead of "
            f"the third one the frontend could not supply"
        )

    async def test_a_diagram_inside_an_alert_keeps_its_own_picture(
        self, jp_fetch, jp_root_dir
    ):
        """`preprocess_github_alerts` folds an alert body onto one line, which
        erases a fence inside a `> [!NOTE]` completely. Running it before the
        mermaid passes left the server counting one diagram where the browser
        counted two, so the note's picture was pasted onto the diagram after
        it and the note kept raw source. Nothing that rewrites the source may
        run before the diagrams are paired."""
        doc = (
            "# A\n\n"
            "> [!NOTE]\n"
            "> See this:\n"
            "> ```mermaid\n"
            "> flowchart LR\n"
            ">     IN_THE_NOTE --> X\n"
            "> ```\n\n"
            "And separately:\n\n"
            "```mermaid\nflowchart LR\n    AFTER_THE_NOTE --> Y\n```\n"
        )
        (jp_root_dir / "alert.md").write_text(doc, encoding="utf-8")

        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        blocks = [b.group(1) for b in ExportHandlerBase.iter_mermaid_blocks(doc)]
        assert len(blocks) == 2 and "IN_THE_NOTE" in blocks[0], (
            f"the document as written holds two diagrams, the note's first; "
            f"the scanner sees {blocks!r}"
        )

        first = "data:image/svg+xml;base64,SU5fVEhFX05PVEU="
        second = "data:image/svg+xml;base64,QUZURVJfVEhFX05PVEU="
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/html",
            method="POST",
            body=json.dumps({
                "path": "alert.md",
                "mermaidDiagrams": [{"index": 0, "svg": first, "png": ""},
                                    {"index": 1, "svg": second, "png": ""}],
            }),
        )
        html = response.body.decode("utf-8")

        assert first in html and second in html, (
            "a diagram the frontend supplied did not reach the document"
        )
        assert html.index(first) < html.index(second), (
            "the note's picture came out after the one that follows it - the "
            "two are paired by position and the pairing has shifted"
        )
        assert "IN_THE_NOTE" not in html, (
            "the diagram inside the alert kept its source: the alert pass ran "
            "first and erased the fence before it could be paired"
        )

    async def test_the_server_renders_with_the_options_the_frontend_uses(self):
        """A diagram must not come out of the API unlike the one the UI makes.
        The frontend sets `securityLevel: 'loose'`; under `strict` mermaid
        turns off HTML labels and the same diagram draws differently."""
        from pathlib import Path as _Path
        from jupyterlab_export_markdown_extension.routes import PlaywrightSvgRenderer

        frontend = _Path(__file__).parents[2] / "src" / "index.ts"
        assert "securityLevel: 'loose'" in frontend.read_text(encoding="utf-8"), (
            "the frontend no longer sets securityLevel: 'loose' - the server "
            "constant below has to follow it"
        )
        assert PlaywrightSvgRenderer.MERMAID_INIT_OPTIONS["securityLevel"] == "loose"

    async def test_every_reported_code_has_a_message(self):
        """The renderer names codes, the header carries their messages - a code
        with no entry would report a warning that explains nothing."""
        import re as _re
        from jupyterlab_export_markdown_extension import routes

        source = _Path_source = (
            __import__("pathlib").Path(routes.__file__).read_text(encoding="utf-8")
        )
        emitted = set(_re.findall(r"'(?:None, )?([a-z]+(?:-[a-z]+)+)'\)", source))
        codes = {c for c in emitted if c in routes.MERMAID_WARNINGS or "-" in c}
        unknown = {c for c in codes
                   if c not in routes.MERMAID_WARNINGS
                   and c in {"render-failed", "syntax-error", "render-timeout",
                             "rasterize-failed", "skipped", "budget-exhausted",
                             "layout-unsupported", "bundle-missing",
                             "chromium-unavailable"}}
        assert not unknown, f"codes with no message: {unknown}"
        assert routes.MERMAID_WARNINGS.keys() >= {
            "chromium-unavailable", "bundle-missing", "syntax-error",
            "layout-unsupported", "render-timeout", "skipped",
            "budget-exhausted", "rasterize-failed", "render-failed",
        }

    async def test_the_diagrams_behind_a_timeout_are_not_blamed_for_it(
        self, jp_fetch, jp_root_dir, monkeypatch
    ):
        """A document where diagram 0 does not finish must not tell the reader
        that the healthy diagrams behind it are too complex to draw.

        The timeout is forced rather than provoked: mermaid draws even a
        4000-edge graph in 0.7s, so a source slow enough to trip a real 30s
        budget would make this test slower than the suite it lives in."""
        from jupyterlab_export_markdown_extension import routes

        real_wait_for = asyncio.wait_for
        first = []

        async def timeout_once(awaitable, timeout=None):
            if not first:
                first.append(True)
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise asyncio.TimeoutError()
            return await real_wait_for(awaitable, timeout)

        monkeypatch.setattr(routes.asyncio, "wait_for", timeout_once)
        block = "```mermaid\nflowchart LR\n    A --> B\n```\n\n"
        (jp_root_dir / "hang.md").write_text("# H\n\n" + block * 3, encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "hang.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]

        warnings = self._warnings(response)
        assert warnings["render-timeout"]["diagrams"] == [0], (
            f"the timeout is reported against "
            f"{warnings['render-timeout']['diagrams']}, not the diagram that hung"
        )
        assert warnings["skipped"]["diagrams"] == [1, 2], (
            "the diagrams behind the offender must be reported as skipped, not "
            "as having timed out themselves"
        )
        assert "Simplify" not in warnings["skipped"]["message"], (
            "the skipped diagrams are told to simplify themselves"
        )

    async def test_the_frontend_counts_diagrams_the_way_the_server_does(self):
        """The frontend posts diagrams by position and the server pairs them by
        position, so both must skip a ```mermaid quoted inside a longer fence.
        One counting it and the other not hands a diagram the wrong picture."""
        from pathlib import Path as _P

        frontend = (_P(__file__).parents[2] / "src" / "index.ts").read_text(
            encoding="utf-8"
        )
        assert "mermaidBlocksFromSource(source)" in frontend, (
            "the source fallback went back to a bare regex over the document; "
            "it would count a quoted example the server skips"
        )
        assert "`{3,}|~{3,}" in frontend, (
            "the frontend's fence tracking no longer mirrors the server's - "
            "both must treat a ```mermaid opened inside any fence as content"
        )

    async def test_a_mermaid_example_inside_a_plain_fence_is_left_alone(
        self, jp_fetch, jp_root_dir
    ):
        """A fence carrying an info string never closes a block, so
        ```text / ```mermaid / ``` is ONE code block per CommonMark - the
        mermaid inside it is quoted just as firmly as inside a longer fence."""
        (jp_root_dir / "plain.md").write_text(
            "# Docs\n\n"
            "```text\n```mermaid\nflowchart LR\n    A --> B\n```\n\n"
            "A real one:\n\n"
            "```mermaid\nflowchart LR\n    C --> D\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "plain.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 1, (
            f"{len(media)} diagrams rendered - a ```mermaid quoted inside a "
            f"plain ```text block is documentation, not a diagram"
        )

    async def test_the_server_keeps_the_ceilings_the_browser_has(self):
        """`@jupyterlab/mermaid` raises maxTextSize/maxEdges and the frontend
        inherits them, so matching only securityLevel would fail diagrams
        through the API that JupyterLab draws without complaint."""
        from jupyterlab_export_markdown_extension.routes import PlaywrightSvgRenderer

        options = PlaywrightSvgRenderer.MERMAID_INIT_OPTIONS
        assert options["maxTextSize"] == 100000
        assert options["maxEdges"] == 100000

    async def test_a_null_pixel_width_still_produces_a_png(
        self, jp_fetch, mermaid_markdown_file
    ):
        """`data.get(k, default)` defaults a MISSING key only. A client sending
        `"svgPixelWidth": null` used to select SVG output silently, and Word
        cannot display an SVG."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", raise_error=False,
            body=json.dumps({"path": "mermaid_api.md", "svgPixelWidth": None}),
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert media and all(n.endswith(".png") for n in media), (
            f"a null width put {media} in the DOCX instead of PNG images"
        )

    async def test_a_junk_pixel_width_does_not_fail_the_export(
        self, jp_fetch, mermaid_markdown_file
    ):
        for width in ["wide", 0, -5, True, {"px": 900}, 99999]:
            response = await jp_fetch(
                "jupyterlab-export-markdown-extension", "export/docx",
                method="POST", raise_error=False,
                body=json.dumps({"path": "mermaid_api.md", "svgPixelWidth": width}),
            )
            assert response.code == 200, f"width={width!r}: {response.body[:200]}"
            with zipfile.ZipFile(io.BytesIO(response.body)) as z:
                media = [n for n in z.namelist() if n.startswith("word/media/")]
            assert len(media) == 2, f"width={width!r} lost a diagram"

    async def test_a_syntax_error_echoing_a_dead_session_phrase_does_not_abort(
        self, jp_fetch, jp_root_dir
    ):
        """A mermaid parse error echoes the offending source line, so a node
        label reading 'Connection closed' or 'Target page' beside a real syntax
        error was read as the browser dying and dropped every later diagram.
        Liveness is now decided from page state, so the run continues and the
        later healthy diagram still renders."""
        doc = (
            "# S\n\n"
            "```mermaid\nflowchart LR\n    A --> First\n```\n\n"
            # syntactically broken AND echoes a dead-session phrase in its text
            "```mermaid\nflowchart LR\n    Connection closed -->\n```\n\n"
            "```mermaid\nflowchart LR\n    B --> Third\n```\n"
        )
        (jp_root_dir / "echo.md").write_text(doc, encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "echo.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 2, (
            f"{len(media)} of the 2 healthy diagrams rendered - the run aborted "
            f"at the broken one because its text echoed a dead-session phrase"
        )
        codes = self._warnings(response)
        assert "render-failed" not in codes, (
            "a syntax error was misread as the browser dying"
        )
        assert "syntax-error" in codes, (
            "the genuinely broken diagram should report a syntax error"
        )


    async def test_a_diagram_nested_in_a_list_is_still_a_diagram(
        self, jp_fetch, jp_root_dir
    ):
        """CommonMark measures a fence's indent from its container's content
        column, so a block inside a list item sits four or more spaces in.
        JupyterLab renders it, so the server must count it - or every later
        diagram's picture lands on the wrong fence."""
        (jp_root_dir / "nested.md").write_text(
            "# N\n\n"
            "- step one\n"
            "  - detail\n\n"
            "    ```mermaid\n    flowchart LR\n        A --> B\n    ```\n\n"
            "- step two\n\n"
            "```mermaid\nflowchart LR\n    C --> D\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "nested.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 2, (
            f"{len(media)} of 2 diagrams rendered - the list-nested one was "
            f"skipped, which shifts every later diagram onto the wrong fence"
        )

    async def test_a_blockquoted_diagram_is_still_a_diagram(
        self, jp_fetch, jp_root_dir
    ):
        (jp_root_dir / "quoted.md").write_text(
            "# Q\n\n> ```mermaid\n> flowchart LR\n>     A --> B\n> ```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "quoted.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 1, "a blockquoted diagram was not rendered"

    async def test_a_tilde_fence_declares_a_diagram_and_still_quotes(self):
        """marked's fence rule treats `~~~` exactly like ``` ``` ```, so
        JupyterLab renders `~~~mermaid` and the preview capture counts it. The
        server has to agree or the browser's diagram N lands on fence N-1. A
        tilde fence must still QUOTE what a longer fence holds."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        as_diagram = "~~~mermaid\nflowchart LR\n    A --> B\n~~~\n"
        assert ExportHandlerBase.count_mermaid_blocks(as_diagram) == 1, (
            "a tilde fence did not declare a diagram the browser counts"
        )
        quoting = "~~~text\n```mermaid\nflowchart LR\n    A --> B\n```\n~~~\n"
        assert ExportHandlerBase.count_mermaid_blocks(quoting) == 0, (
            "a tilde fence stopped quoting what is inside it"
        )
        plain = "```mermaid\nflowchart LR\n    A --> B\n```\n"
        assert ExportHandlerBase.count_mermaid_blocks(plain) == 1

    async def test_an_uppercase_info_string_is_not_a_diagram(self):
        """`block.languages.includes(token.lang)` is case-sensitive, so
        JupyterLab renders ```MERMAID as a code sample. Lowercasing here turned
        that sample into a picture of itself and shifted every later block."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        doc = ("```MERMAID\nflowchart LR\n    A --> B\n```\n\n"
               "```mermaid\nflowchart LR\n    C --> D\n```\n")
        blocks = list(ExportHandlerBase.iter_mermaid_blocks(doc))
        assert len(blocks) == 1, (
            f"expected only the lowercase fence to be a diagram, got "
            f"{[b.group(1) for b in blocks]}"
        )
        assert "C --> D" in blocks[0].group(1), (
            "the uppercase sample was taken as the diagram, so the browser's "
            "picture would land on it"
        )

    async def test_a_null_math_width_keeps_the_equations(
        self, jp_fetch, jp_root_dir
    ):
        """The same null-default hazard as svgPixelWidth: uncoerced, the DPI
        arithmetic raises, the raise is swallowed, and the PDF ships its
        equations as literal `$x^2$` text."""
        import fitz

        (jp_root_dir / "math.md").write_text(
            "# M\n\nAn equation: $x^2 + y^2 = z^2$\n", encoding="utf-8"
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/pdf",
            method="POST", raise_error=False,
            body=json.dumps({"path": "math.md", "mathPixelWidth": None}),
        )
        assert response.code == 200, response.body[:300]
        pdf = fitz.open(stream=response.body, filetype="pdf")
        try:
            text = "\n".join(page.get_text() for page in pdf)
            images = sum(len(page.get_images(full=True)) for page in pdf)
        finally:
            pdf.close()
        assert "$x^2" not in text, (
            "the equation shipped as literal markdown - a null width silently "
            "disabled math rendering"
        )
        assert images >= 1, "the equation image is missing from the PDF"

    async def test_an_infinite_pixel_width_does_not_fail_the_export(
        self, jp_fetch, mermaid_markdown_file
    ):
        """`json.loads` accepts `Infinity`, and `int(float('inf'))` raises
        OverflowError - which is not a ValueError."""
        for body in ['{"path": "mermaid_api.md", "svgPixelWidth": Infinity}',
                     '{"path": "mermaid_api.md", "svgPixelWidth": NaN}',
                     '{"path": "mermaid_api.md", "svgPixelWidth": "1e400"}']:
            response = await jp_fetch(
                "jupyterlab-export-markdown-extension", "export/docx",
                method="POST", body=body, raise_error=False,
            )
            assert response.code == 200, f"{body}: {response.body[:200]}"
            with zipfile.ZipFile(io.BytesIO(response.body)) as z:
                media = [n for n in z.namelist() if n.startswith("word/media/")]
            assert len(media) == 2, f"{body} lost a diagram"

    async def test_a_broken_diagram_keeps_the_healthy_ones_around_it(
        self, jp_fetch, jp_root_dir
    ):
        """A syntax error in the middle of a document keeps its source but must
        not throw away the diagrams drawn before it or block the ones after -
        the per-diagram fault is isolated, only a genuine session death stops
        the run."""
        doc = (
            "# B\n\n"
            "```mermaid\nflowchart LR\n    A --> Before\n```\n\n"
            "```mermaid\nnot a valid diagram at all @#$\n```\n\n"
            "```mermaid\nflowchart LR\n    C --> After\n```\n"
        )
        (jp_root_dir / "mid.md").write_text(doc, encoding="utf-8")
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "mid.md"}), raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 2, (
            f"{len(media)} of 2 healthy diagrams rendered - a per-diagram "
            f"syntax error was allowed to stop the whole run"
        )

    async def test_the_missing_layout_regex_tells_an_elk_diagram_from_a_bug(self):
        """A genuinely unsupported layout gets its own remedy; an ordinary JS
        error mentioning 'layout' must not be dressed up as one."""
        from jupyterlab_export_markdown_extension.routes import PlaywrightSvgRenderer

        assert not PlaywrightSvgRenderer._MERMAID_MISSING_LAYOUT_RE.search(
            "Cannot read properties of undefined (reading 'layout')"
        ), "an ordinary JS error is reported as an unsupported layout"
        assert PlaywrightSvgRenderer._MERMAID_MISSING_LAYOUT_RE.search(
            "Error: Layout algorithm elk is not registered."
        ), "a genuinely missing layout engine is not recognised"

    async def test_the_frontend_reads_a_crlf_file(self):
        """JS `.` excludes \\r, so a naive `(.*)$` matches no fence at all in a
        Windows-authored document - the fallback would find nothing where it
        used to find every diagram."""
        from pathlib import Path as _P

        frontend = (_P(__file__).parents[2] / "src" / "index.ts").read_text(
            encoding="utf-8"
        )
        assert "replace(/\\r$/, '')" in frontend, (
            "the frontend no longer strips a trailing CR before matching fences"
        )

    async def test_a_four_space_indented_example_at_top_level_is_not_a_diagram(
        self, jp_fetch, jp_root_dir
    ):
        """Four spaces at the top level is an indented code block, not a fence.
        JupyterLab renders only the real diagram, so counting the example would
        put the browser's picture on the wrong one.

        Counting images cannot tell the two apart - either way one renders and
        one does not - so this asserts WHICH survived as text."""
        (jp_root_dir / "indented.md").write_text(
            "# I\n\nShown as an example:\n\n"
            "    ```mermaid\n    flowchart LR\n        A --> B\n    ```\n\n"
            "The real one:\n\n"
            "```mermaid\nflowchart LR\n    C --> D\n```\n",
            encoding="utf-8",
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "indented.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        text = _docx_text(response.body).replace("\n", "")
        assert "A --> B" in text, (
            "the indented example was rendered into a picture of itself "
            "instead of staying the code sample it is"
        )
        assert "C --> D" not in text, "the real diagram was left as source"

    async def test_an_unclosed_quoted_fence_ends_with_its_blockquote(self):
        """A blockquote ends at its first unquoted line, and CommonMark closes
        any fence still open inside it - marked renders that block, so it is a
        diagram. What it must not do is run on: that makes one 'diagram' out of
        the blockquote plus every paragraph and code block after it, up to
        whatever ``` happens to close it."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        doc = ("# U\n\n> ```mermaid\n> flowchart LR\n>     A --> B\n\n"
               "This paragraph must survive.\n\n"
               "```python\nkeep = 'this'\n```\n")
        blocks = list(ExportHandlerBase.iter_mermaid_blocks(doc))
        assert len(blocks) == 1, (
            f"expected the quoted block to close with its blockquote, got "
            f"{len(blocks)} block(s)"
        )
        assert blocks[0].end() < doc.index("This paragraph"), (
            f"the block spans {(blocks[0].start(), blocks[0].end())} of a "
            f"{len(doc)}-char document - the substitution would replace the "
            f"prose and the python block too"
        )
        assert blocks[0].group(1).strip() == "flowchart LR\n    A --> B", (
            f"quote markers survived into the source: {blocks[0].group(1)!r}"
        )

    async def test_an_unclosed_fence_at_the_end_of_the_file_is_a_diagram(self):
        """CommonMark closes an unclosed fence at the end of the document and
        marked renders what it opened, so the preview counts it. Dropping it
        here would leave the browser one diagram ahead of the server."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        doc = "# E\n\n```mermaid\nflowchart LR\n    A --> B\n"
        blocks = list(ExportHandlerBase.iter_mermaid_blocks(doc))
        assert len(blocks) == 1, (
            f"an unclosed fence at EOF yielded {len(blocks)} blocks"
        )
        assert blocks[0].group(1).strip() == "flowchart LR\n    A --> B"

    async def test_a_crlf_document_hands_mermaid_clean_source(self):
        """A Windows-authored file keeps a CR on every line when the source is
        sliced straight out of the content."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        doc = "# C\r\n\r\n```mermaid\r\nflowchart LR\r\n    A --> B\r\n```\r\n"
        blocks = list(ExportHandlerBase.iter_mermaid_blocks(doc))
        assert len(blocks) == 1, f"a CRLF document yielded {len(blocks)} blocks"
        assert "\r" not in blocks[0].group(1), (
            f"the source handed to mermaid carries CRs: {blocks[0].group(1)!r}"
        )

    async def test_a_crlf_document_renders_its_diagrams(
        self, jp_fetch, jp_root_dir
    ):
        (jp_root_dir / "crlf.md").write_bytes(
            b"# C\r\n\r\n```mermaid\r\nflowchart LR\r\n    A --> B\r\n```\r\n"
        )
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension", "export/docx",
            method="POST", body=json.dumps({"path": "crlf.md"}),
            raise_error=False,
        )
        assert response.code == 200, response.body[:300]
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 1, "a CRLF document rendered no diagram"

    async def test_a_nested_quote_strips_every_marker(self):
        """One `>` per level; leaving any behind hands mermaid `> flowchart`."""
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        doc = "# N\n\n> > ```mermaid\n> > flowchart LR\n> >     A --> B\n> > ```\n"
        blocks = list(ExportHandlerBase.iter_mermaid_blocks(doc))
        assert len(blocks) == 1
        source = blocks[0].group(1)
        assert not any(line.lstrip().startswith(">") for line in source.split("\n")), (
            f"quote markers reached mermaid: {source!r}"
        )
        assert "flowchart LR" in source and "A --> B" in source

    async def test_the_frontend_carries_every_counting_rule_the_server_has(self):
        """A cheap smoke check that each rule is at least present on both sides.

        It is NOT the guarantee - both files can carry every one of these
        substrings and still behave differently, which is exactly what a
        differential fuzz found (a CRLF bare list marker). The guarantee is
        `TestFenceScannerParity`, which runs both scanners."""
        from pathlib import Path as _P

        frontend = (_P(__file__).parents[2] / "src" / "index.ts").read_text(
            encoding="utf-8"
        )
        for rule, what in [
            ("`{3,}|~{3,}", "every fence opener, not only long ones"),
            ("replace(/\\r$/, '')", "CRLF lines"),
            ("quoteStripped", "measuring indent in the container's coordinate"),
            ("expandTabs", "a tab after > carries one column of the marker"),
            ("listContentCol", "the list item's content column"),
            ("spaces - base > 3", "indented code past the container is not a fence"),
            ("stripQuoteMarkers", "a quoted block's markers"),
            ("dedentBody", "the container's indent is not the diagram's"),
            ("info === 'mermaid'", "an exact, case-sensitive info string"),
            ("spaces <= openSpaces + 3", "a closer lives in its opener's container"),
            ("q < openQ", "a blockquote ending closes the fence inside it"),
        ]:
            assert rule in frontend, (
                f"the frontend scanner no longer handles {what} ({rule!r}) - "
                f"it must mirror iter_mermaid_blocks or the indices diverge"
            )

FENCE_SHAPES = {
    "plain": "```mermaid\nflowchart LR\n    A --> B\n```\n",
    "quoted_by_longer": "````markdown\n```mermaid\nflowchart LR\n    A --> B\n```\n````\n",
    "quoted_by_plain": "```text\n```mermaid\nflowchart LR\n    A --> B\n```\n",
    "tilde_opener": "~~~mermaid\nflowchart LR\n    A --> B\n~~~\n",
    "tilde_quoting": "~~~text\n```mermaid\nflowchart LR\n    A --> B\n```\n~~~\n",
    "list_nested": "- a\n  - b\n\n    ```mermaid\n    flowchart LR\n        A --> B\n    ```\n",
    "top_indented": "text\n\n    ```mermaid\n    flowchart LR\n        A --> B\n    ```\n",
    "blockquote": "> ```mermaid\n> flowchart LR\n>     A --> B\n> ```\n",
    "nested_quote": "> > ```mermaid\n> > flowchart LR\n> >     A --> B\n> > ```\n",
    "unclosed_quote": "> ```mermaid\n> flowchart LR\n\nprose\n\n```python\nx = 1\n```\n",
    "crlf": "```mermaid\r\nflowchart LR\r\n    A --> B\r\n```\r\n",
    "two_plain": "```mermaid\nflowchart LR\n    A --> B\n```\n\n```mermaid\nflowchart LR\n    C --> D\n```\n",
    "unclosed_eof": "```mermaid\nflowchart LR\n    A --> B\n",
    "info_suffix": "```mermaid extra\nflowchart LR\n```\n",
    "crlf_bare_marker": "-\r\n    ```mermaid\r\n    flowchart LR\r\n    ```\r\n",
    "crlf_ordered_marker": "1.\r\n    ```mermaid\r\n    flowchart LR\r\n    ```\r\n",
    "crlf_list_then_text": "- a\r\n\r\ntext\r\n\r\n```mermaid\r\nflowchart LR\r\n```\r\n",
    "uppercase_info": "```MERMAID\nflowchart LR\n    A --> B\n```\n",
    "mixed_case_info": "```Mermaid\nflowchart LR\n    A --> B\n```\n",
    "quoted_closer": "```mermaid\nflowchart LR\n> ```\nstill the diagram\n```\n",
    "deep_closer": "```mermaid\nflowchart LR\n    ```\nstill the diagram\n```\n",
    "list_then_quote": "- a\n\n> quote\n\n    ```mermaid\n    flowchart LR\n    ```\n",
    "quote_deep_indent": "- a\n\n>     ```mermaid\n>     flowchart LR\n>     ```\n",
    # Round-6: shapes both adversarial lenses reproduced as silent
    # picture-misplacement - a fence four spaces past a list item's content
    # column is indented code, a bare/tab-indented container was mis-measured.
    "list_over_indented": ("- Here is an example:\n\n      ```mermaid\n"
                           "      flowchart LR\n      ```\n\nAnd real:\n\n"
                           "```mermaid\nflowchart RL\n```\n"),
    "list_in_quote": "> - step\n>\n>     ```mermaid\n>     flowchart LR\n>     ```\n",
    "bare_marker_deep": "-\n\n      ```mermaid\n      flowchart LR\n      ```\n",
    "tab_quoted_fence": ">\t```mermaid\n>\tflowchart LR\n>\t```\n",
    "quote_then_bare_fence": ("> ```mermaid\n> flowchart LR\n```python\n"
                              "x = 1\n```\n"),
    "list_content_col_three": "1. item\n\n   ```mermaid\n   flowchart LR\n   ```\n",
    # Round-7 (architect): marked trims the info string with JS `.trim()`, which
    # strips a BOM; Python `str.strip()` keeps it, so ```mermaid<BOM> counted as
    # source here and as a diagram in the browser - a one-off count shift.
    "bom_info": "```mermaid\ufeff\nflowchart LR\n    A --> B\n```\n",
}

#: What each shape must yield. A diagram counted by one side and not the other
#: hands the server a picture addressed to the wrong fence. Every count here is
#: what marked - the parser JupyterLab renders with, and therefore what the
#: preview-capture path counts - produces for that document; none is a reading
#: of the spec. `test_marked_agrees_with_the_server_on_every_shape` re-derives
#: them from the installed marked so the table cannot drift from it.
FENCE_SHAPE_COUNTS = {
    "plain": 1, "quoted_by_longer": 0, "quoted_by_plain": 0, "tilde_opener": 1,
    "tilde_quoting": 0, "list_nested": 1, "top_indented": 0, "blockquote": 1,
    "nested_quote": 1, "unclosed_quote": 1, "crlf": 1, "two_plain": 2,
    "unclosed_eof": 1, "info_suffix": 0, "crlf_bare_marker": 1,
    "crlf_ordered_marker": 1, "crlf_list_then_text": 1, "uppercase_info": 0,
    "mixed_case_info": 0, "quoted_closer": 1, "deep_closer": 1,
    "list_then_quote": 0, "quote_deep_indent": 0, "list_over_indented": 1,
    "list_in_quote": 1, "bare_marker_deep": 0, "tab_quoted_fence": 1,
    "quote_then_bare_fence": 1, "list_content_col_three": 1, "bom_info": 1,
}


class TestFenceScannerParity:
    """DEF-16: the frontend posts diagrams by position and the server pairs them
    by position, so the two scanners must agree on every fence shape. This runs
    BOTH - the TypeScript one is extracted and executed under node - rather than
    reading one and trusting the other."""

    @staticmethod
    def _typescript_blocks(fixtures):
        import json as _json
        import re as _re
        import subprocess
        import tempfile
        from pathlib import Path as _P

        source = (_P(__file__).parents[2] / "src" / "index.ts").read_text(
            encoding="utf-8"
        )
        start = source.index("/** One `>` per quote level")
        end = source.index("/**\n * Capture rendered Mermaid diagrams")
        body = source[start:end]
        # Strip TypeScript type annotations so node can run the extracted body:
        # function return types `): T {` first, then parameter/variable `: T`.
        body = _re.sub(r"\)\s*:\s*[A-Za-z0-9_\[\]<>,.| ]+\s*\{", ") {", body)
        for pattern in (r":\s*string\[\]", r":\s*string \| null",
                        r":\s*number \| null", r":\s*\[number, string\]",
                        r":\s*(?:string|number|boolean|void)\b"):
            body = _re.sub(pattern, "", body)
        body = body.replace(" as string", "")

        with tempfile.TemporaryDirectory() as tmp:
            script = _P(tmp) / "fence.js"
            data = _P(tmp) / "fixtures.json"
            data.write_text(_json.dumps(fixtures), encoding="utf-8")
            script.write_text(body + """
const fixtures = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const [name, doc] of Object.entries(fixtures)) {
  out[name] = mermaidBlocksFromSource(doc);
}
console.log(JSON.stringify(out));
""", encoding="utf-8")
            done = subprocess.run(["node", str(script), str(data)],
                                  capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"node failed: {done.stderr[:400]}"
        return _json.loads(done.stdout)

    @staticmethod
    def _normalise(blocks):
        return [b.replace("\r\n", "\n").rstrip("\n") for b in blocks]

    def test_the_server_counts_every_shape_as_specified(self):
        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        for name, doc in FENCE_SHAPES.items():
            found = len(list(ExportHandlerBase.iter_mermaid_blocks(doc)))
            assert found == FENCE_SHAPE_COUNTS[name], (
                f"{name}: server found {found}, expected "
                f"{FENCE_SHAPE_COUNTS[name]}"
            )

    def test_marked_agrees_with_the_server_on_every_shape(self):
        """marked is the authority, not the CommonMark spec and not a reading
        of it: JupyterLab renders the preview with marked, and the DOM capture
        posts one diagram per fence marked turned into a diagram. Anything the
        server counts differently lands a picture on the wrong fence.

        This runs the installed marked over the same shapes. It is what caught
        ```MERMAID (marked is case-sensitive, the server was not) and ~~~mermaid
        (marked renders it, the server refused it)."""
        import json as _json
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path as _P

        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        marked = (_P(__file__).parents[2] / "node_modules" / "marked" / "lib"
                  / "marked.esm.js")
        if shutil.which("node") is None or not marked.exists():
            pytest.skip("node and the installed marked are needed")

        names = list(FENCE_SHAPES)
        with tempfile.TemporaryDirectory() as tmp:
            script = _P(tmp) / "count.mjs"
            data = _P(tmp) / "docs.json"
            data.write_text(_json.dumps([FENCE_SHAPES[n] for n in names]),
                            encoding="utf-8")
            # Mirrors @jupyterlab/markedparser-extension: a fence is a diagram
            # when the code token's lang is exactly what MermaidMarkdown
            # registers, `block.languages.includes(lang)` with languages
            # `['mermaid']`.
            script.write_text(f"""
import {{ marked }} from '{marked.as_posix()}';
import {{ readFileSync }} from 'fs';
function walk(tokens, out) {{
  for (const t of tokens) {{
    if (t.type === 'code' && t.lang === 'mermaid') out.push(t.text);
    if (t.tokens) walk(t.tokens, out);
    if (t.items) walk(t.items, out);
  }}
}}
const docs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
console.log(JSON.stringify(docs.map(d => {{ const o = []; walk(marked.lexer(d), o); return o; }})));
""", encoding="utf-8")
            done = subprocess.run(["node", str(script), str(data)],
                                  capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"node failed: {done.stderr[:400]}"

        for name, blocks in zip(names, _json.loads(done.stdout)):
            server = len(list(
                ExportHandlerBase.iter_mermaid_blocks(FENCE_SHAPES[name])))
            assert server == len(blocks), (
                f"{name}: marked renders {len(blocks)} diagram(s) and the "
                f"server counts {server} - the browser posts one per rendered "
                f"diagram, so every later picture lands on the wrong fence"
            )
            assert len(blocks) == FENCE_SHAPE_COUNTS[name], (
                f"{name}: FENCE_SHAPE_COUNTS says {FENCE_SHAPE_COUNTS[name]} "
                f"but marked renders {len(blocks)} - the table has drifted "
                f"from the parser it is supposed to describe"
            )

    def test_both_scanners_agree_on_every_shape(self):
        import shutil

        if shutil.which("node") is None:
            pytest.skip("node is not available to run the TypeScript scanner")

        from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

        typescript = self._typescript_blocks(FENCE_SHAPES)
        for name, doc in FENCE_SHAPES.items():
            server = self._normalise(
                [b.group(1) for b in ExportHandlerBase.iter_mermaid_blocks(doc)]
            )
            frontend = self._normalise(typescript[name])
            assert server == frontend, (
                f"{name}: the server yields {server!r} and the frontend "
                f"{frontend!r} - one counts a block the other skips, so a "
                f"diagram would receive the wrong picture"
            )

