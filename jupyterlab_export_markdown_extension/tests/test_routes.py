import json


async def test_export_pdf_no_path(jp_fetch):
    """Test PDF export endpoint returns 400 when no path provided."""
    response = await jp_fetch(
        "jupyterlab-export-markdown-extension",
        "export/pdf",
        method="POST",
        body=json.dumps({}),
        raise_error=False,
    )
    assert response.code == 400
    payload = json.loads(response.body)
    assert "error" in payload
    assert payload["error"] == "No path provided"


async def test_export_docx_no_path(jp_fetch):
    """Test DOCX export endpoint returns 400 when no path provided."""
    response = await jp_fetch(
        "jupyterlab-export-markdown-extension",
        "export/docx",
        method="POST",
        body=json.dumps({}),
        raise_error=False,
    )
    assert response.code == 400
    payload = json.loads(response.body)
    assert "error" in payload
    assert payload["error"] == "No path provided"


async def test_export_html_no_path(jp_fetch):
    """Test HTML export endpoint returns 400 when no path provided."""
    response = await jp_fetch(
        "jupyterlab-export-markdown-extension",
        "export/html",
        method="POST",
        body=json.dumps({}),
        raise_error=False,
    )
    assert response.code == 400
    payload = json.loads(response.body)
    assert "error" in payload
    assert payload["error"] == "No path provided"


async def test_export_pdf_file_not_found(jp_fetch):
    """Test PDF export endpoint returns 404 when file not found."""
    response = await jp_fetch(
        "jupyterlab-export-markdown-extension",
        "export/pdf",
        method="POST",
        body=json.dumps({"path": "nonexistent.md"}),
        raise_error=False,
    )
    assert response.code == 404
    payload = json.loads(response.body)
    assert "error" in payload
    assert payload["error"] == "File not found"


def _disposition_for(filename):
    """Run set_attachment_filename in isolation and return the header value."""
    from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

    captured = {}

    class _Handler(ExportHandlerBase):
        def __init__(self):
            pass

        def set_header(self, name, value):
            captured[name] = value

    _Handler().set_attachment_filename(filename)
    return captured["Content-Disposition"]


def test_attachment_filename_non_ascii_is_header_safe():
    """A non-ASCII name must not raise 'Unsafe header value'.

    Tornado encodes header values as latin-1, so interpolating 'ł' straight
    into Content-Disposition aborted the export with a 500 before any bytes
    were written. Regression for zniesławienie-milena-kabza-2026.docx.
    """
    value = _disposition_for("zniesławienie-milena-kabza-2026.docx")

    value.encode("latin-1")  # the exact operation that used to raise
    assert 'filename="znieslawienie-milena-kabza-2026.docx"' in value
    assert "filename*=UTF-8''znies%C5%82awienie-milena-kabza-2026.docx" in value


def test_attachment_filename_ascii_unchanged():
    """An ASCII name keeps its plain filename, with filename* alongside."""
    value = _disposition_for("plain-report.pdf")

    assert 'filename="plain-report.pdf"' in value
    assert "filename*=UTF-8''plain-report.pdf" in value


def test_attachment_filename_non_latin_script_keeps_a_name():
    """A name with no Latin characters must not degrade to a dotfile."""
    for name, expected in (("評価.docx", "export.docx"), ("Ελληνικά.pdf", "export.pdf")):
        value = _disposition_for(name)
        value.encode("latin-1")
        assert f'filename="{expected}"' in value


def test_attachment_filename_cannot_inject_header():
    """Quotes and separators in a name must not escape the quoted string."""
    value = _disposition_for('ev"il;x.docx')

    value.encode("latin-1")
    assert 'filename="ev_il_x.docx"' in value
    assert value.count('"') == 2
