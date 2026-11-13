"""Server root containment, event-loop blocking, SVG network access and the
small rendering defects closed with them."""

import http.server
import io
import json
import re
import threading
import zipfile

from jupyterlab_export_markdown_extension.routes import ExportHandlerBase

NAMESPACE = "jupyterlab-export-markdown-extension"


async def _post(jp_fetch, fmt, path):
    return await jp_fetch(
        NAMESPACE, f"export/{fmt}", method="POST",
        body=json.dumps({"path": path}), raise_error=False,
    )


def _docx_xml(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        return z.read("word/document.xml").decode("utf-8")


async def test_document_outside_the_server_root_is_not_exported(
        jp_fetch, jp_root_dir):
    """DEF-EXPO-122: the document path was joined to the root unchecked, so
    `../secret.md` and an absolute path exported a file outside the root."""
    secret = jp_root_dir.parent / "secret-outside-root.md"
    secret.write_text("# TOP-SECRET-CONTENT\n", encoding="utf-8")
    (jp_root_dir / "inside.md").write_text("# inside\n", encoding="utf-8")
    try:
        for path in (f"../{secret.name}", str(secret),
                     f"sub/../../{secret.name}"):
            response = await _post(jp_fetch, "html", path)
            assert response.code == 404, f"{path!r} answered {response.code}"
            assert b"TOP-SECRET-CONTENT" not in response.body
        # a path that stays inside the root still exports, `..` and all
        (jp_root_dir / "sub").mkdir()
        assert (await _post(jp_fetch, "html", "sub/../inside.md")).code == 200
        assert (await _post(jp_fetch, "html", "/inside.md")).code == 200
    finally:
        secret.unlink()


async def test_images_are_embedded_off_the_event_loop(
        jp_fetch, jp_root_dir, monkeypatch):
    """DEF-EXPO-123: a remote image download ran on the server's event loop
    and froze every kernel and terminal for up to 10 s per image."""
    seen = []
    original = ExportHandlerBase.embed_images_as_base64

    def record(self, *args, **kwargs):
        seen.append(threading.current_thread() is threading.main_thread())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ExportHandlerBase, "embed_images_as_base64", record)
    (jp_root_dir / "plain.md").write_text("# plain\n", encoding="utf-8")
    assert (await _post(jp_fetch, "html", "plain.md")).code == 200
    assert seen == [False], "the image pass ran on the event loop thread"


async def test_user_svg_cannot_make_the_server_fetch_a_private_address(
        jp_fetch, jp_root_dir):
    """DEF-DIAG-17: a document's own SVG was rasterized with the network
    open, so an `<image href>` inside it made the server fetch that URL."""
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        (jp_root_dir / "pic.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
            '<rect width="100" height="50" fill="red"/>'
            f'<image href="http://127.0.0.1:{port}/probe.png" width="10" '
            'height="10"/></svg>', encoding="utf-8")
        (jp_root_dir / "svg.md").write_text(
            "# SVG\n\n![pic](pic.svg)\n", encoding="utf-8")
        response = await _post(jp_fetch, "docx", "svg.md")
        assert response.code == 200
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            assert any(n.startswith("word/media/") for n in z.namelist()), (
                "the SVG itself must still be rasterized")
    finally:
        server.shutdown()
        server.server_close()
    assert hits == [], f"the server fetched {hits} for a document's SVG"


async def test_pdf_heading_is_not_stranded_at_the_foot_of_a_page(
        jp_fetch, jp_root_dir):
    """DEF-MARK-15: a page break could fall between a heading and its first
    paragraph. Whatever length the text above has, the two share a page."""
    import fitz

    stranded = []
    for lines in range(26, 34):
        (jp_root_dir / "strand.md").write_text(
            "# Top\n\n" + "".join(f"Filler line {i}.\n\n" for i in range(lines))
            + "## STRANDHEAD\n\nSTRANDBODY first paragraph.\n",
            encoding="utf-8")
        response = await _post(jp_fetch, "pdf", "strand.md")
        assert response.code == 200
        doc = fitz.open(stream=response.body, filetype="pdf")
        text = [page.get_text() for page in doc]
        doc.close()
        head = next(i for i, t in enumerate(text) if "STRANDHEAD" in t)
        body = next(i for i, t in enumerate(text) if "STRANDBODY" in t)
        if head != body:
            stranded.append(lines)
    assert not stranded, f"heading left alone at a page foot for {stranded}"


def test_tilde_fence_is_protected_like_a_backtick_fence():
    """DEF-DIAG-19: a `~~~` fence reached the math and alert passes
    unprotected. DEF-MARK-126: the alert pass protected no fence at all."""
    handler = ExportHandlerBase.__new__(ExportHandlerBase)
    for fence in ("```", "~~~"):
        sample = (f"{fence}sh\nPATH=$HOME/bin:$PATH\n> [!NOTE]\n> shown\n"
                  f"{fence}\n")
        assert handler.preprocess_github_alerts(sample) == sample, fence
        content, inline, display = handler.replace_math_with_markers(sample)
        assert (content, inline, display) == (sample, [], []), fence
    # outside a fence both passes still work
    assert "​NOTE​" in handler.preprocess_github_alerts(
        "> [!NOTE]\n> real\n")
    assert handler.replace_math_with_markers("$x^2$")[1] == ["x^2"]


async def test_inline_code_with_accented_letters_keeps_its_monospace(
        jp_fetch, jp_root_dir):
    """DEF-MARK-26: any non-ASCII character cost inline code its Courier."""
    (jp_root_dir / "mono.md").write_text(
        "Run `zażółć.py` for `100 €`.\n", encoding="utf-8")
    response = await _post(jp_fetch, "docx", "mono.md")
    assert response.code == 200
    xml = _docx_xml(response.body)
    for code in ("zażółć.py", "100 €"):
        run = re.search(r"<w:r>(?:(?!</w:r>).)*" + re.escape(code), xml, re.S)
        assert run and "Courier" in run.group(0), f"{code!r} lost its monospace"


async def test_html_export_styles_kbd_and_samp_as_code(jp_fetch, jp_root_dir):
    """DEF-MARK-28: `<kbd>` and `<samp>` took no rule of the stylesheet."""
    (jp_root_dir / "kbd.md").write_text(
        "Press <kbd>Ctrl</kbd>.\n", encoding="utf-8")
    response = await _post(jp_fetch, "html", "kbd.md")
    assert response.code == 200
    css = response.body.decode("utf-8").split("</style>")[0]
    assert re.search(r"\bcode, kbd, samp \{", css)


async def test_center_tag_is_a_centred_paragraph_of_its_own(
        jp_fetch, jp_root_dir):
    """DEF-DIAG-40: `<center>` joined the paragraph above it, uncentred."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    (jp_root_dir / "center.md").write_text(
        "Para one.\n\n<center>Centred</center>\n\nPara two.\n",
        encoding="utf-8")
    response = await _post(jp_fetch, "docx", "center.md")
    assert response.code == 200
    paragraphs = {p.text.strip(): p.alignment
                  for p in Document(io.BytesIO(response.body)).paragraphs}
    assert "Centred" in paragraphs, f"no paragraph of its own: {paragraphs}"
    assert paragraphs["Centred"] == WD_ALIGN_PARAGRAPH.CENTER


async def test_jpeg_is_not_recompressed(jp_fetch, jp_root_dir):
    """DEF-MARK-127: every JPEG was saved again at Pillow's default quality
    75 when its DPI was set, so a photo lost detail in DOCX and PDF."""
    from PIL import Image

    noise = Image.effect_noise((320, 240), 64).convert("RGB")
    noise.save(jp_root_dir / "photo.jpg", quality=95)
    (jp_root_dir / "photo.md").write_text(
        "# Photo\n\n![p](photo.jpg)\n", encoding="utf-8")
    response = await _post(jp_fetch, "docx", "photo.md")
    assert response.code == 200
    with zipfile.ZipFile(io.BytesIO(response.body)) as z:
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 1
        embedded = Image.open(io.BytesIO(z.read(media[0])))
    original = Image.open(jp_root_dir / "photo.jpg")
    assert embedded.quantization == original.quantization, (
        "the JPEG was encoded again with other quantization tables")
