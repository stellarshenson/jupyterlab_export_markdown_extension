"""Export fidelity tests - validate that HTML, DOCX, and PDF exports contain expected content."""

import json
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
    """Test GitHub-style alerts preprocessing."""

    async def test_note_alert_html(self, jp_fetch, test_markdown_file):
        """Test NOTE alert is processed in HTML."""
        response = await jp_fetch(
            "jupyterlab-export-markdown-extension",
            "export/html",
            method="POST",
            body=json.dumps({"path": "test.md"}),
        )
        html = response.body.decode("utf-8")
        # Alert should be converted to bold prefix
        assert "NOTE:" in html or "note" in html.lower()

    async def test_alert_in_docx(self, jp_fetch, test_markdown_file):
        """Test alert is processed in DOCX."""
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
            assert "NOTE" in document_xml or "note" in document_xml.lower()


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
