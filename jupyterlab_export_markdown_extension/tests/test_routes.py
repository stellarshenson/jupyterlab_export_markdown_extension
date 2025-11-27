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
