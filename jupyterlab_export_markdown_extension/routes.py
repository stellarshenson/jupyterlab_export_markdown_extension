"""
Route handlers for the markdown export extension.

Provides API endpoints for exporting markdown files to PDF, DOCX, and HTML formats
using pure Python libraries (no system dependencies).
"""

from __future__ import annotations

import json
import os
import base64
import ipaddress
import re
import io
import socket
import tempfile
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlparse

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
import tornado.web

# Reportlab imports for DOCX-to-PDF conversion
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
        Preformatted, XPreformatted
    )
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class ChromiumUnavailableError(RuntimeError):
    """Raised when Playwright cannot launch Chromium (binary or sys-libs missing).

    Carries the original error message so the handler can return install
    guidance to the frontend.
    """


#: Built once - the rule is stateless, and `markdown_to_html` runs per export
_MANUAL_BREAK_RULE = None


def manual_break_aware_nl2br():
    """The `nl2br` rule, minus the break it would add after a manual one.

    `nl2br` turns every newline into a break. A line the author ended with
    `<br>` - the idiom for a question above its answer - therefore gets two,
    and the resulting blank line makes the gap inside the pair match the gap
    between pairs, so the grouping reads backwards. The author asked for one
    break and should get one.

    Deciding that needs to happen where provenance still exists, which is the
    inline stage. By the time the HTML is serialized a break the author typed
    and a break `nl2br` generated are the same six characters, and so is the
    one core Markdown generates for the two-trailing-spaces idiom - collapsing
    on shape there deletes authored breaks. Here the author's tag is still a
    stashed node, and the two-space break is consumed by the `linebreak`
    pattern (priority 100) long before this one (priority 5) is reached, so
    `text<br>` + two spaces keeps both of its breaks.

    Everything the resolution touches is guarded: if Markdown's internals move,
    this cannot tell a manual break from a generated one and falls back to
    emitting the break, which is exactly `nl2br`'s own behaviour.
    """
    global _MANUAL_BREAK_RULE
    if _MANUAL_BREAK_RULE is not None:
        return _MANUAL_BREAK_RULE

    from markdown.extensions import Extension
    from markdown.inlinepatterns import InlineProcessor
    from markdown import util
    from xml.etree import ElementTree

    # The author's tag as it sits in the text at this point: an inline
    # placeholder, at the very end of what precedes the newline
    trailing_node = re.compile(
        re.escape(util.INLINE_PLACEHOLDER).replace(re.escape('%s'), r'(\d+)')
        + r'\Z')
    # `\b` would accept a custom element like `<br-spacer>`, whose break is
    # not a break at all
    break_tag = re.compile(r'<br(?:\s[^>]*?)?/?>', re.IGNORECASE)

    class NewlineToBreak(InlineProcessor):
        def handleMatch(self, m, data):
            if self._after_manual_break(data[:m.start(0)]):
                return None, None, None
            return ElementTree.Element('br'), m.start(0), m.end(0)

        def _after_manual_break(self, before):
            """True when a break tag the author typed ends ``before``.

            Trailing blanks are skipped: one space after `<br>` is invisible
            in an editor and must not decide how the document renders. Two
            spaces never reach here - `linebreak` has already claimed them. A
            tab cannot either - `expandtabs` runs before inline processing.

            A break nested inside inline markup (`**Q<br>**`) is NOT detected:
            the trailing node is then the emphasis Element, not the break, and
            the pair renders with a blank line. Known limitation, pinned by
            `test_break_inside_emphasis_is_a_known_limitation`.
            """
            node = trailing_node.search(before.rstrip(' \xa0'))
            if node is None:
                return False
            try:
                inline = self.md.treeprocessors['inline'].stashed_nodes
                stashed = inline.get(node.group(1))
                if not isinstance(stashed, str):
                    return False       # a real element, so not raw HTML
                held = util.HTML_PLACEHOLDER_RE.fullmatch(stashed)
                if held is None:
                    return False
                raw = self.md.htmlStash.rawHtmlBlocks[int(held.group(1))]
            except (AttributeError, IndexError, KeyError, TypeError):
                return False           # cannot tell - behave like plain nl2br
            return isinstance(raw, str) and bool(break_tag.fullmatch(raw.strip()))

    class ManualBreakAwareNl2Br(Extension):
        def extendMarkdown(self, md):
            # Same slot and priority nl2br itself uses
            md.inlinePatterns.register(NewlineToBreak(r'\n', md), 'nl', 5)

    _MANUAL_BREAK_RULE = ManualBreakAwareNl2Br()
    return _MANUAL_BREAK_RULE


class PlaywrightSvgRenderer:
    """Render SVG bytes to PNG bytes via Playwright Chromium.

    Reuses one browser process across multiple render() calls within an
    `async with` block. Uses a real browser engine, so CSS classes,
    @font-face, gradients, filters, and @media (prefers-color-scheme)
    all behave the way they do in the user's browser.

    The output PNG is `width` pixels wide; height follows the SVG's
    viewBox aspect ratio. Chromium anti-aliases natively, so no
    supersampling is needed - it renders straight to the target size.
    Pass supersample > 1 only if a specific SVG needs extra smoothing.
    """

    def __init__(self, color_scheme: str = 'light'):
        if color_scheme not in ('light', 'dark'):
            color_scheme = 'light'
        self.color_scheme = color_scheme
        self._pw = None
        self._browser = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise ChromiumUnavailableError(
                f'playwright not installed: {e}'
            ) from e
        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=True)
        except Exception as e:
            # Most common failure is missing system libs (libnspr4, libnss3
            # etc.) or Chromium binary not downloaded yet.
            await self._safe_stop()
            raise ChromiumUnavailableError(str(e)) from e
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._safe_stop()

    async def _safe_stop(self):
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None

    # Chromium refuses a viewport, and silently fails a texture, past roughly
    # 16384px. Held a little under it for the compositor's own overhead.
    MAX_RASTER_PX = 16000

    @staticmethod
    def _viewbox_dims(svg_text: str) -> tuple[float, float]:
        m = re.search(r'viewBox\s*=\s*"([^"]+)"', svg_text)
        if m:
            parts = re.split(r'[\s,]+', m.group(1).strip())
            if len(parts) >= 4:
                try:
                    return float(parts[2]), float(parts[3])
                except ValueError:
                    pass
        wm = re.search(r'\bwidth\s*=\s*"([0-9.]+)', svg_text)
        hm = re.search(r'\bheight\s*=\s*"([0-9.]+)', svg_text)
        return (
            float(wm.group(1)) if wm else 800.0,
            float(hm.group(1)) if hm else 600.0,
        )

    async def render(self, svg_bytes: bytes, *,
                     width: int = 1920, supersample: int = 1) -> bytes:
        svg_text = svg_bytes.decode('utf-8', errors='replace')

        # Drop any XML declaration / DOCTYPE prologue before the <svg> root.
        # The SVG is embedded into an HTML document and parsed by Chromium's
        # HTML parser, which does not understand a DOCTYPE internal subset
        # (`<!DOCTYPE svg [ <!ENTITY ...> ]>`). It ends the DOCTYPE at the
        # first `>`, spilling the rest of the subset - including the closing
        # `]>` - as a visible text node in the top-left corner. JupyterLab's
        # mermaid renderer prepends exactly such a prologue, so this leak
        # showed up on every exported mermaid diagram. Cutting to the first
        # `<svg` removes it; Chromium renders the element fine without it.
        svg_start = svg_text.find('<svg')
        if svg_start > 0:
            svg_text = svg_text[svg_start:]

        # Many mermaid outputs declare a viewBox far larger than the drawn
        # shape, rasterizing the diagram tiny inside a mostly-empty canvas.
        # Load the SVG, measure the content bounding box with getBBox(), and -
        # ONLY when the declared viewBox has real excess whitespace - tighten
        # the viewBox to it. A viewBox that already frames the content is left
        # alone: getBBox reports geometry only (no stroke, markers or filters),
        # so cropping a well-framed diagram would clip node borders and
        # arrowheads that its own padding is there to hold.
        declared_w, declared_h = self._viewbox_dims(svg_text)
        probe = max(1, int(width))

        ctx = await self._browser.new_context(
            color_scheme=self.color_scheme,
            viewport={'width': probe, 'height': probe},
        )
        try:
            page = await ctx.new_page()
            probe_html = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
                "*{margin:0;padding:0}"
                "html,body{background:transparent;overflow:hidden}"
                "svg{display:block}"
                "</style></head><body>"
                f"{svg_text}"
                "</body></html>"
            )
            await page.set_content(probe_html, wait_until='load')

            # Real content bounds in the SVG's own (viewBox) coordinate space.
            bbox = await page.evaluate(
                """() => {
                    const svg = document.querySelector('svg');
                    if (!svg) return null;
                    try {
                        const b = svg.getBBox();
                        if (!b || b.width <= 0 || b.height <= 0) return null;
                        return {x: b.x, y: b.y, width: b.width, height: b.height};
                    } catch (e) { return null; }
                }"""
            )

            tighten = None  # (x, y, w, h) when we crop the viewBox, else keep it
            if bbox:
                fill_w = bbox['width'] / declared_w if declared_w > 0 else 0.0
                fill_h = bbox['height'] / declared_h if declared_h > 0 else 0.0
                if min(fill_w, fill_h) < 0.8:  # >20% empty in some dimension
                    # One pad, taken from the SMALLER extent, on both axes. The
                    # crop is scaled uniformly to the page, so an equal pad here
                    # is an equal printed margin all round. Taking it from the
                    # larger extent swamps the short axis - 4% of an 844pt width
                    # is 34pt, which nearly doubles a 70pt-tall flowchart - and
                    # padding each axis by its own extent instead trades that for
                    # a diagram whose side gutters are five times its top ones,
                    # and stretches an already extreme aspect ratio further.
                    pad = max(6.0, 0.04 * min(bbox['width'], bbox['height']))
                    tighten = (bbox['x'] - pad, bbox['y'] - pad,
                               bbox['width'] + 2 * pad, bbox['height'] + 2 * pad)

            # Size from the box we will render: the tightened box if cropping,
            # otherwise the declared viewBox (which we leave in place).
            vb_w, vb_h = (tighten[2], tighten[3]) if tighten else (declared_w, declared_h)
            nominal_w = probe
            nominal_h = max(1, round(vb_h * nominal_w / vb_w)) if vb_w > 0 else nominal_w
            target_w = max(1, nominal_w * supersample)
            target_h = max(1, nominal_h * supersample)
            # A long single-column flowchart is many times taller than it is
            # wide, and at the configured export width its raster passes the
            # ~16384px Chromium caps on a viewport and a texture. The screenshot
            # then throws and the diagram is dropped from the export entirely,
            # so scale the whole raster down instead - the aspect ratio and the
            # page fit are unaffected, only the pixel density.
            longest = max(target_w, target_h)
            if longest > self.MAX_RASTER_PX:
                shrink = self.MAX_RASTER_PX / longest
                target_w = max(1, int(target_w * shrink))
                target_h = max(1, int(target_h * shrink))

            # Rewrite the viewBox only when cropping; otherwise keep the SVG's
            # own (honouring a non-zero origin). Size the element either way.
            await page.evaluate(
                """({vb, w, h}) => {
                    const svg = document.querySelector('svg');
                    if (!svg) return;
                    if (vb) svg.setAttribute('viewBox', vb);
                    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                    // Mermaid stamps an inline `max-width: <natural>px` on the
                    // root. It caps the element at its natural size, so the
                    // width set below is ignored and the diagram paints small
                    // inside the target canvas - the rest rasterizing as
                    // whitespace. Clear both caps before sizing.
                    svg.style.maxWidth = 'none';
                    svg.style.maxHeight = 'none';
                    svg.setAttribute('width', w);
                    svg.setAttribute('height', h);
                    svg.style.width = w + 'px';
                    svg.style.height = h + 'px';
                    for (const el of [document.documentElement, document.body]) {
                        el.style.width = w + 'px';
                        el.style.height = h + 'px';
                    }
                }""",
                {'vb': (f'{tighten[0]} {tighten[1]} {tighten[2]} {tighten[3]}'
                        if tighten else None),
                 'w': target_w, 'h': target_h},
            )
            await page.set_viewport_size({'width': target_w, 'height': target_h})

            png_bytes = await page.screenshot(
                type='png',
                omit_background=True,
                clip={'x': 0, 'y': 0, 'width': target_w, 'height': target_h},
            )
        finally:
            await ctx.close()

        if supersample > 1:
            from PIL import Image as _PILImage
            img = _PILImage.open(io.BytesIO(png_bytes))
            final = img.resize((nominal_w, nominal_h), _PILImage.LANCZOS)
            buf = io.BytesIO()
            final.save(buf, 'PNG')
            png_bytes = buf.getvalue()

        return png_bytes


class ExportHandlerBase(APIHandler):
    """Base class for export handlers with common functionality."""

    #: w:tblCellMar of the 'Light List Accent 1' style applied to every content
    #: table, 108 twips each side. Column widths are outer widths, so this much
    #: of each is margin rather than content.
    DOCX_CELL_MARGIN_TWIPS = 216

    #: Padding SimpleDocTemplate puts inside its frame on every side, so a
    #: flowable has this much less room than the page margins suggest.
    PDF_FRAME_PADDING = 6

    #: Page margin of the exported PDF, every side.
    PDF_PAGE_MARGIN = 36

    #: reportlab's default LEFT/RIGHTPADDING inside a table cell. Distinct from
    #: PDF_FRAME_PADDING (which happens to share the value): this is the gap
    #: around cell text, that is the gap inside the page frame.
    PDF_TABLE_CELL_PADDING = 6

    #: Base body size in points for each `exportFontSize` setting. Every other
    #: size in every format is a proportion of this one, so the whole document
    #: scales together rather than only its paragraphs.
    EXPORT_FONT_SIZES = {'small': 10.0, 'medium': 12.0, 'large': 14.0}
    DEFAULT_FONT_SIZE_PT = EXPORT_FONT_SIZES['medium']

    #: Body size the DOCX template is built around: its named styles carry
    #: explicit sizes proportioned against this, and so does the column-width
    #: estimate in `fit_docx_table_to_page`.
    DOCX_TEMPLATE_BASE_PT = 11.0

    #: Every size the PDF draws, as a multiple of the base body size, with the
    #: leading each one needs. Sized against the DOCX template's proportions so
    #: the two formats render the same document at the same scale.
    PDF_TYPE_SCALE = {
        'body': (1.0, 1.2),
        'heading1': (1.4, 1.8),
        'heading2': (1.2, 1.5),
        'heading3': (1.1, 1.4),
        'table': (0.9, 1.1),
        'code': (0.8, 1.0),
    }

    @classmethod
    def font_size_pt(cls, name) -> float:
        """Base body size in points for a setting value.

        Anything unrecognised - an older client that does not send the
        setting, a hand-edited value, a value of the wrong type entirely -
        falls back to the default rather than failing an export over a
        cosmetic choice. An explicit number is accepted but clamped to a range
        that still produces a readable document.
        """
        if isinstance(name, bool) or not isinstance(name, (int, float, str)):
            return cls.DEFAULT_FONT_SIZE_PT   # a list or dict is not a size
        if isinstance(name, str):
            return cls.EXPORT_FONT_SIZES.get(name, cls.DEFAULT_FONT_SIZE_PT)
        # An explicit number is honoured, but clamped: 0 gives zero-height
        # flowables and a huge value one glyph per page, neither of which is
        # a document
        return min(max(float(name), 6.0), 32.0)

    @classmethod
    def pdf_type(cls, role: str, base_pt: float) -> dict:
        """`fontSize`/`leading` kwargs for one role at a given base size."""
        size_ratio, leading_ratio = cls.PDF_TYPE_SCALE[role]
        return {'fontSize': base_pt * size_ratio,
                'leading': base_pt * leading_ratio}

    def apply_docx_font_size(self, document, base_pt: float) -> None:
        """Scale a document's type so its body text is ``base_pt``.

        Word resolves an unset size through the style chain, so setting Normal
        moves body text, tables and lists together. The styles that carry an
        explicit size - headings, caption, title - are scaled by the same
        factor instead of being overwritten, which keeps the proportions the
        template was designed with.
        """
        from docx.shared import Pt

        scale = base_pt / self.DOCX_TEMPLATE_BASE_PT
        if scale != 1.0:
            for style in document.styles:
                try:
                    size = style.font.size
                except (AttributeError, NotImplementedError):
                    continue  # table and numbering styles carry no font
                if size is not None:
                    style.font.size = Pt(round(size.pt * scale, 1))
        document.styles['Normal'].font.size = Pt(base_pt)

    def get_absolute_path(self, relative_path: str) -> Path:
        """Convert a relative path to an absolute path within the server root."""
        root_dir = self.contents_manager.root_dir
        return Path(root_dir) / relative_path

    @staticmethod
    def _ip_is_blocked(ip_str: str) -> bool:
        """True for any non-public address - the ranges an SSRF would target
        (cloud metadata 169.254.169.254, localhost, intranet, CGNAT). Allowlist
        via ``is_global`` rather than enumerating private ranges, so special-use
        blocks we didn't think of stay blocked.
        """
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return True
        return not ip.is_global

    @classmethod
    def _host_is_blocked(cls, host: str | None) -> bool:
        """Resolve a hostname and block it if any resolved IP is non-public.
        Unresolvable hosts are blocked (fail closed)."""
        if not host:
            return True
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return True
        return any(cls._ip_is_blocked(info[4][0]) for info in infos)

    def read_markdown_file(self, path: Path) -> str:
        """Read and return the contents of a markdown file."""
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def replace_mermaid_with_images(self, content: str, mermaid_diagrams: list,
                                      use_png: bool = False) -> str:
        """
        Replace mermaid code blocks with pre-rendered images from the frontend.

        Args:
            content: Markdown content with mermaid code blocks
            mermaid_diagrams: List of dicts with 'index' and 'svg' (base64 data URI)
            use_png: If True, convert SVG to PNG (for DOCX compatibility)

        Returns:
            Markdown content with mermaid blocks replaced by image references
        """
        if not mermaid_diagrams:
            return content

        # Pattern to match mermaid code blocks
        mermaid_pattern = r'```mermaid\s*\n(.*?)```'

        # Create lookup dicts by index for both SVG and PNG
        diagrams_by_index = {}
        for d in mermaid_diagrams:
            diagrams_by_index[d['index']] = {
                'svg': d.get('svg', ''),
                'png': d.get('png', '')
            }

        current_index = [0]  # Use list to allow mutation in nested function

        def replace_mermaid(match):
            idx = current_index[0]
            current_index[0] += 1

            if idx in diagrams_by_index:
                diagram = diagrams_by_index[idx]
                svg_data_uri = diagram['svg']
                png_data_uri = diagram['png']

                if use_png and png_data_uri:
                    # Prefer PNG from frontend (client-side Canvas conversion)
                    return f'![Mermaid Diagram]({png_data_uri})'
                # Otherwise emit SVG; extract_data_uri_images() converts to
                # PNG server-side via Playwright when convert_svg=True.
                return f'![Mermaid Diagram]({svg_data_uri})'

            # No pre-rendered diagram available, keep original
            return match.group(0)

        return re.sub(mermaid_pattern, replace_mermaid, content, flags=re.DOTALL)

    # Inline images carrying an explicit display size at or below this many
    # CSS px are treated as small badges/pills, not full-width diagrams.
    _BADGE_MAX_PX = 200
    # Pixel-density multiplier applied to a badge's display size when
    # rasterizing, so it stays crisp when zoomed in Word.
    _BADGE_RENDER_SCALE = 4
    # Hard ceiling on a badge's rasterized width (px) - guards against a crafted
    # SVG viewBox aspect ratio driving the Playwright canvas to an absurd size.
    _BADGE_RENDER_MAX_PX = 4096

    @classmethod
    def _badge_render_spec(cls, full_tag: str, vb_w: float, vb_h: float):
        """Render width and DPI for a small, explicitly-sized inline image.

        Reads height/width from the tag's ``style`` (``max-height`` preferred
        over ``height``) or its ``width``/``height`` attributes. When the
        resulting display size is small, returns ``(render_width_px, dpi)`` so
        the PNG embeds at that physical size with ``_BADGE_RENDER_SCALE``x pixel
        density. Returns ``None`` for unsized or large images, which then
        rasterize at the full diagram width.
        """
        num = r'(\d+(?:\.\d+)?)'  # strict number - no ValueError on "1.2.3px"
        max_h = max_w = None
        style_m = re.search(r'style=["\']([^"\']*)["\']', full_tag, re.IGNORECASE)
        if style_m:
            s = style_m.group(1)
            # max-height wins over plain height (CSS clamps height to max-height);
            # the leading delimiter stops `line-height` / `stroke-width` matching.
            mh = (re.search(r'(?:^|[;\s])max-height\s*:\s*' + num + r'\s*px', s, re.IGNORECASE)
                  or re.search(r'(?:^|[;\s])height\s*:\s*' + num + r'\s*px', s, re.IGNORECASE))
            mw = (re.search(r'(?:^|[;\s])max-width\s*:\s*' + num + r'\s*px', s, re.IGNORECASE)
                  or re.search(r'(?:^|[;\s])width\s*:\s*' + num + r'\s*px', s, re.IGNORECASE))
            if mh:
                max_h = float(mh.group(1))
            if mw:
                max_w = float(mw.group(1))
        # HTML width/height attributes. Tokenise attributes so a `width=`/
        # `height=` sitting inside another attribute's quoted value (e.g.
        # alt="x width=5") or a `data-width`/`data-height` is never read as
        # geometry. Bare number, optional px; %, em etc. are rejected.
        if max_h is None or max_w is None:
            for name, dq, sq, bare in re.findall(
                r'([-\w]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))',
                full_tag, re.IGNORECASE,
            ):
                key = name.lower()
                if key not in ('width', 'height'):
                    continue
                vm = re.fullmatch(num + r'(?:px)?', (dq or sq or bare).strip(), re.IGNORECASE)
                if not vm:
                    continue
                if key == 'height' and max_h is None:
                    max_h = float(vm.group(1))
                elif key == 'width' and max_w is None:
                    max_w = float(vm.group(1))
        if max_h is None and max_w is None:
            return None
        if vb_w <= 0 or vb_h <= 0:
            return None
        # Effective rendered height = smallest height the constraints permit
        # (a max-width can shrink a tall image below its max-height). Qualify on
        # height so wide-but-short pills (max-width:1000px) still count as badges.
        aspect = vb_w / vb_h
        eff_h = max_h
        if max_w is not None:
            h_from_w = max_w / aspect
            eff_h = h_from_w if eff_h is None else min(eff_h, h_from_w)
        if eff_h > cls._BADGE_MAX_PX:
            return None
        disp_w = eff_h * aspect
        render_w = min(cls._BADGE_RENDER_MAX_PX,
                       max(1, round(disp_w * cls._BADGE_RENDER_SCALE)))
        return render_w, 96 * cls._BADGE_RENDER_SCALE

    async def extract_data_uri_images(self, html: str, temp_dir: str,
                                      convert_svg: bool = False,
                                      svg_pixel_width: int = 1920,
                                      color_scheme: str = 'light') -> str:
        """
        Extract data URI images to temp files for htmldocx compatibility.

        When convert_svg=True, SVG images are rasterized to PNG via Playwright
        Chromium so CSS (including @media (prefers-color-scheme)), web fonts,
        filters and tspan layout match a real browser. One Chromium instance
        is reused across all SVGs in this call.

        Raises ChromiumUnavailableError if convert_svg=True and Chromium
        cannot launch (binary or system libs missing).

        Args:
            html: HTML content with data URI images
            temp_dir: Directory to store temp image files
            convert_svg: If True, convert SVG images to PNG via Playwright
            svg_pixel_width: Target pixel width for each rasterized SVG;
                height follows the SVG's viewBox aspect ratio
            color_scheme: 'light' or 'dark'; passed to the browser context so
                @media (prefers-color-scheme) rules in the SVG resolve correctly
        """
        img_pattern = r'<img\s+[^>]*src=["\']data:image/([^;]+);base64,([^"\']+)["\'][^>]*>'
        ext_map = {
            'png': '.png', 'jpeg': '.jpg', 'jpg': '.jpg',
            'gif': '.gif', 'svg+xml': '.svg',
        }

        matches = list(re.finditer(img_pattern, html))
        if not matches:
            return html

        svg_indices = [
            i for i, m in enumerate(matches)
            if convert_svg and m.group(1) == 'svg+xml'
        ]
        rendered: dict[int, bytes | None] = {}
        # Per-image target DPI: small inline badges get a high DPI so their
        # rasterized PNG embeds at the badge's physical size (not page width).
        target_dpi: dict[int, int] = {}

        if svg_indices:
            async with PlaywrightSvgRenderer(color_scheme=color_scheme) as renderer:
                for i in svg_indices:
                    try:
                        svg_bytes = base64.b64decode(matches[i].group(2))
                        svg_text = svg_bytes.decode('utf-8', errors='replace')
                        vb_w, vb_h = PlaywrightSvgRenderer._viewbox_dims(svg_text)
                        spec = self._badge_render_spec(
                            matches[i].group(0), vb_w, vb_h
                        )
                        render_w = spec[0] if spec is not None else svg_pixel_width
                        rendered[i] = await renderer.render(
                            svg_bytes, width=render_w
                        )
                        # Commit the badge DPI only after a successful render so
                        # a later failure can't leave a stale badge flag set.
                        if spec is not None:
                            target_dpi[i] = spec[1]
                    except ChromiumUnavailableError:
                        # Bubble up; handler converts to a typed HTTP error
                        # so the frontend can show its install-required popup.
                        raise
                    except Exception:
                        rendered[i] = None  # render failed; keep original SVG

        out: list[str] = []
        last = 0
        for i, m in enumerate(matches):
            out.append(html[last:m.start()])
            last = m.end()

            img_type = m.group(1)
            base64_data = m.group(2)
            full_tag = m.group(0)
            ext = ext_map.get(img_type, '.png')

            try:
                if i in rendered:
                    if rendered[i] is None:
                        out.append(full_tag)
                        continue
                    img_bytes = rendered[i]
                    ext = '.png'
                else:
                    img_bytes = base64.b64decode(base64_data)

                import hashlib
                hash_id = hashlib.md5(img_bytes).hexdigest()[:8]
                filepath = os.path.join(temp_dir, f'img_{hash_id}{ext}')
                with open(filepath, 'wb') as f:
                    f.write(img_bytes)

                # Normalize DPI for consistent sizing in DOCX. Embedded DPI
                # metadata drives python-docx's native-size computation; without
                # it the same pixel dimensions render at wildly different sizes.
                # Small inline badges get a high DPI (target_dpi[i]) so their PNG
                # embeds at the badge's physical size rather than at page width.
                dpi = target_dpi.get(i, 96)
                if ext in ('.jpg', '.jpeg', '.png'):
                    try:
                        from PIL import Image
                        img = Image.open(filepath)
                        img.save(filepath, dpi=(dpi, dpi))
                    except Exception:
                        pass

                if i in target_dpi:
                    # Badge: rely on native DPI size; drop width/height/style so
                    # nothing scales it back up to the cell width. Keep alt only.
                    alt = re.search(r'(alt=["\'][^"\']*["\'])', full_tag)
                    out.append(
                        f'<img src="{filepath}" {alt.group(1)}>' if alt
                        else f'<img src="{filepath}">'
                    )
                else:
                    other_attrs = re.findall(
                        r'((?:alt|style|width|height)=["\'][^"\']*["\'])', full_tag
                    )
                    attrs_str = ' '.join(other_attrs)
                    if attrs_str:
                        out.append(f'<img src="{filepath}" {attrs_str}>')
                    else:
                        out.append(f'<img src="{filepath}">')
            except Exception:
                out.append(full_tag)

        out.append(html[last:])
        return ''.join(out)

    def embed_images_as_base64(self, content: str, markdown_dir: Path) -> str:
        """
        Replace local and remote image references with base64-encoded data URIs.

        Handles both Markdown image syntax ``![alt](path)`` and raw HTML
        ``<img src="path">`` tags (the latter common inside Markdown tables,
        where inline badges/pills are written as HTML).

        - Local paths are read from disk relative to ``markdown_dir`` but must
          stay within the Jupyter server root (the user's workspace); paths that
          escape it (absolute, ``../`` traversal) are refused.
        - ``http://`` / ``https://`` URLs are fetched (10 s timeout, 5 MB cap)
          so badges and other remote images embed in DOCX/PDF, but only when the
          host resolves to a public IP (SSRF guard). Failures fall back to the
          original reference silently.
        - ``data:`` URIs are passed through.
        """
        img_pattern = r'!\[([^\]]*)\]\(([^)"\s]+)(?:\s+"[^"]*")?\)'
        mime_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.webp': 'image/webp',
        }
        remote_cache: dict[str, str | None] = {}
        # Containment boundary for local reads - the server root the user is
        # already allowed to browse.
        try:
            root_dir = Path(self.contents_manager.root_dir).resolve()
        except Exception:
            root_dir = None

        def fetch_remote(url: str) -> str | None:
            if url in remote_cache:
                return remote_cache[url]
            try:
                import http.client
                import urllib.request as _urlreq
                from urllib.request import (
                    Request, build_opener, HTTPRedirectHandler,
                    HTTPHandler, HTTPSHandler,
                )
                parsed = urlparse(url)
                # SSRF guard: only public http(s) hosts. Blocks localhost,
                # intranet and the 169.254.169.254 cloud-metadata endpoint.
                if parsed.scheme not in ('http', 'https') or \
                        self._host_is_blocked(parsed.hostname):
                    remote_cache[url] = None
                    return None

                # When an HTTP proxy applies, the socket connects to the proxy
                # (often a private IP), so the peer-IP check can't run - the host
                # pre-check above plus the proxy's own egress policy guard it.
                try:
                    proxied = bool(_urlreq.getproxies().get(parsed.scheme)) and \
                        not _urlreq.proxy_bypass(parsed.hostname or '')
                except Exception:
                    proxied = False

                host_blocked = self._host_is_blocked
                ip_blocked = self._ip_is_blocked

                def _check_peer(conn):
                    # Authoritative SSRF check: validate the IP actually connected
                    # to. Closes the DNS-rebinding/TOCTOU gap between the host
                    # pre-check and urllib's own connect-time resolution.
                    ip = conn.sock.getpeername()[0]
                    if ip_blocked(ip):
                        conn.close()
                        raise OSError(f'blocked non-public address: {ip}')

                class _GHTTP(http.client.HTTPConnection):
                    def connect(self):
                        super().connect()
                        _check_peer(self)

                class _GHTTPS(http.client.HTTPSConnection):
                    def connect(self):
                        super().connect()
                        _check_peer(self)

                class _GHTTPHandler(HTTPHandler):
                    def http_open(self, req):
                        return self.do_open(_GHTTP, req)

                class _GHTTPSHandler(HTTPSHandler):
                    def https_open(self, req):
                        return self.do_open(
                            _GHTTPS, req,
                            context=getattr(self, '_context', None),
                            check_hostname=getattr(self, '_check_hostname', None),
                        )

                class _GuardedRedirect(HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                        p = urlparse(newurl)
                        if p.scheme not in ('http', 'https') or host_blocked(p.hostname):
                            return None  # refuse redirect to a non-public host
                        return super().redirect_request(
                            req, fp, code, msg, hdrs, newurl)

                if proxied:
                    # Default handlers route through the proxy; keep the redirect
                    # host guard but skip the peer-IP check (peer is the proxy).
                    opener = build_opener(_GuardedRedirect())
                else:
                    opener = build_opener(
                        _GHTTPHandler(), _GHTTPSHandler(), _GuardedRedirect()
                    )
                req = Request(
                    url,
                    headers={'User-Agent': 'jupyterlab-export-markdown-extension'},
                )
                with opener.open(req, timeout=10) as resp:
                    raw = resp.read(5 * 1024 * 1024 + 1)
                    if len(raw) > 5 * 1024 * 1024:
                        remote_cache[url] = None
                        return None
                    ctype = (resp.headers.get('Content-Type') or '').split(';', 1)[0].strip()
                if not ctype:
                    ext = os.path.splitext(url)[1].lower()
                    ctype = mime_types.get(ext, 'application/octet-stream')
                b64 = base64.b64encode(raw).decode('utf-8')
                data_uri = f'data:{ctype};base64,{b64}'
                remote_cache[url] = data_uri
                return data_uri
            except Exception:
                remote_cache[url] = None
                return None

        def local_data_uri(img_path: str) -> str | None:
            try:
                # URL-decode the path (handles %20 for spaces, etc.). resolve()
                # can raise (NUL byte, symlink loop) - treat as unresolvable.
                full_path = (markdown_dir / unquote(img_path)).resolve()
                # Containment: stay within the server root. Refuses absolute
                # paths and ../ traversal that escape the workspace (e.g.
                # /etc/passwd), while still allowing legit ../sibling refs inside
                # the root. Fails closed: no known root -> refuse the read.
                if root_dir is None or not full_path.is_relative_to(root_dir):
                    return None
                if not full_path.exists():
                    return None
                with open(full_path, 'rb') as img_file:
                    img_data = base64.b64encode(img_file.read()).decode('utf-8')
                ext = full_path.suffix.lower()
                mime_type = mime_types.get(ext, 'application/octet-stream')
                return f'data:{mime_type};base64,{img_data}'
            except Exception:
                return None

        def resolve_src(src: str) -> str | None:
            """Return a base64 data URI for ``src``, or None to leave it as-is."""
            low = src.lower()
            if low.startswith('data:'):
                return None
            if low.startswith(('http://', 'https://')):
                return fetch_remote(src)
            return local_data_uri(src)

        def replace_image(match):
            alt_text = match.group(1)
            data_uri = resolve_src(match.group(2))
            if data_uri is None:
                return match.group(0)
            return f'![{alt_text}]({data_uri})'

        content = re.sub(img_pattern, replace_image, content)

        # Raw HTML <img> tags (inline badges/pills inside Markdown tables).
        # The (?<![-\w:]) guard keeps `data-src`/`lowsrc`/`xlink:src` from
        # matching as `src`.
        src_attr_re = re.compile(r'(?<![-\w:])(src\s*=\s*)(["\'])(.*?)\2', re.IGNORECASE)

        def replace_html_img(tag_match):
            tag = tag_match.group(0)

            def sub_src(m):
                data_uri = resolve_src(m.group(3))
                if data_uri is None:
                    return m.group(0)
                return f'{m.group(1)}"{data_uri}"'

            return src_attr_re.sub(sub_src, tag, count=1)

        # Quote-aware tag match so a `>` inside an attribute value (e.g.
        # alt="a > b") doesn't truncate the tag.
        img_tag_re = r'<img\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>'
        return re.sub(img_tag_re, replace_html_img, content, flags=re.IGNORECASE)

    def get_pygments_css(self, dark: bool = False) -> str:
        """Get Pygments CSS for syntax highlighting.

        Args:
            dark: If True, return dark theme (monokai) CSS for use inside
                  @media (prefers-color-scheme: dark) block.
        """
        try:
            from pygments.formatters import HtmlFormatter
            theme = 'monokai' if dark else 'default'
            return HtmlFormatter(style=theme).get_style_defs('.codehilite')
        except ImportError:
            return ''

    def highlight_code_blocks(self, content: str, use_inline_styles: bool = False) -> str:
        """Highlight code blocks using Pygments.

        Args:
            content: Markdown content with fenced code blocks
            use_inline_styles: If True, use inline styles (for DOCX). If False, use CSS classes (for HTML).

        Returns:
            Content with code blocks replaced by highlighted HTML
        """
        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
            from pygments.formatters import HtmlFormatter
        except ImportError:
            return content

        # Pattern to match fenced code blocks with optional language
        code_pattern = r'```(\w*)\n(.*?)```'

        def highlight_match(match):
            lang = match.group(1).strip().lower() or 'text'
            code = match.group(2)

            try:
                lexer = get_lexer_by_name(lang)
            except Exception:
                try:
                    lexer = guess_lexer(code)
                except Exception:
                    lexer = TextLexer()

            formatter = HtmlFormatter(
                noclasses=use_inline_styles,
                nowrap=False,
                cssclass='codehilite'
            )
            highlighted = highlight(code, lexer, formatter)

            # Fix color format for htmldocx (needs # prefix, but only 6-char hex)
            if use_inline_styles:
                # Convert 3-char hex to 6-char hex (e.g., #BBB -> #BBBBBB, #00F -> #0000FF)
                highlighted = re.sub(
                    r'color:\s*#([0-9A-Fa-f])([0-9A-Fa-f])([0-9A-Fa-f])(?![0-9A-Fa-f])',
                    lambda m: f'color: #{m.group(1)*2}{m.group(2)*2}{m.group(3)*2}',
                    highlighted
                )
                highlighted = re.sub(
                    r'background:\s*#([0-9A-Fa-f])([0-9A-Fa-f])([0-9A-Fa-f])(?![0-9A-Fa-f])',
                    lambda m: f'background: #{m.group(1)*2}{m.group(2)*2}{m.group(3)*2}',
                    highlighted
                )

            return highlighted

        return re.sub(code_pattern, highlight_match, content, flags=re.DOTALL)

    def extract_code_blocks(self, content: str) -> tuple:
        """Extract code blocks from markdown for PDF rendering.

        Returns:
            Tuple of (modified_content, code_blocks_list)
            code_blocks_list contains dicts with 'lang' and 'code' keys
        """
        code_blocks = []
        code_pattern = r'```(\w*)\n(.*?)```'

        def extract_match(match):
            lang = match.group(1).strip().lower() or 'text'
            code = match.group(2).rstrip('\n')
            idx = len(code_blocks)
            code_blocks.append({'lang': lang, 'code': code})
            # Replace with placeholder
            return f'[[CODE_BLOCK_{idx}]]'

        modified = re.sub(code_pattern, extract_match, content, flags=re.DOTALL)
        return modified, code_blocks

    def highlight_code_for_pdf(self, code: str, lang: str,
                               base_pt: float = None) -> list:
        """Highlight code for PDF using Pygments and return reportlab flowables.

        Returns list of reportlab flowables (Preformatted paragraphs)
        """
        code_base = self.DEFAULT_FONT_SIZE_PT if base_pt is None else base_pt
        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
            from pygments.formatters import get_formatter_by_name
        except ImportError:
            # Fallback: return plain preformatted text
            if REPORTLAB_AVAILABLE:
                from reportlab.lib.styles import getSampleStyleSheet
                styles = getSampleStyleSheet()
                code_style = ParagraphStyle(
                    'CodeBlock',
                    parent=styles['Code'],
                    fontName='Courier',
                    **self.pdf_type('code', code_base),
                    backColor=colors.HexColor('#f8f8f8'),
                    leftIndent=6,
                    rightIndent=6,
                    spaceBefore=6,
                    spaceAfter=6
                )
                return [Preformatted(code, code_style)]
            return []

        try:
            lexer = get_lexer_by_name(lang)
        except Exception:
            try:
                lexer = guess_lexer(code)
            except Exception:
                lexer = TextLexer()

        # Use a monospace font for code
        font_name = 'Courier'
        if REPORTLAB_AVAILABLE and 'UnicodeSans' in pdfmetrics.getRegisteredFontNames():
            # Check if we have a monospace Unicode font
            pass  # Keep Courier for code

        code_style = ParagraphStyle(
            'CodeBlock',
            fontName=font_name,
            **self.pdf_type('code', code_base),
            backColor=colors.HexColor('#f8f8f8'),
            leftIndent=6,
            rightIndent=6,
            spaceBefore=6,
            spaceAfter=6,
            wordWrap='CJK'  # Allow wrapping on any character
        )

        # Convert Pygments tokens to reportlab XML markup
        from pygments.token import Token, Keyword, Name, Comment, String, Number, Operator

        # Color mapping for token types
        token_colors = {
            Token.Keyword: '#008000',
            Token.Keyword.Constant: '#008000',
            Token.Keyword.Declaration: '#008000',
            Token.Keyword.Namespace: '#008000',
            Token.Keyword.Type: '#B00040',
            Token.Name.Function: '#0000FF',
            Token.Name.Class: '#0000FF',
            Token.Name.Decorator: '#AA22FF',
            Token.Name.Builtin: '#008000',
            Token.Name.Tag: '#008000',
            Token.Comment: '#3D7B7B',
            Token.Comment.Single: '#3D7B7B',
            Token.Comment.Multiline: '#3D7B7B',
            Token.String: '#BA2121',
            Token.String.Doc: '#BA2121',
            Token.String.Escape: '#AA5D1F',
            Token.Number: '#666666',
            Token.Number.Integer: '#666666',
            Token.Number.Float: '#666666',
            Token.Operator: '#666666',
            Token.Operator.Word: '#AA22FF',
        }

        # Build XML-formatted code
        formatted_lines = []
        current_line = []

        for ttype, value in lexer.get_tokens(code):
            # Escape XML special characters
            value = value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            # Find color for token type
            color = None
            for token_type, token_color in token_colors.items():
                if ttype in token_type or ttype is token_type:
                    color = token_color
                    break

            # Split by newlines to handle multiline tokens
            parts = value.split('\n')
            for i, part in enumerate(parts):
                if part:
                    if color:
                        current_line.append(f'<font color="{color}">{part}</font>')
                    else:
                        current_line.append(part)
                if i < len(parts) - 1:  # Not the last part, meaning there was a newline
                    formatted_lines.append(''.join(current_line))
                    current_line = []

        # Add remaining content
        if current_line:
            formatted_lines.append(''.join(current_line))

        # Join with newlines - XPreformatted preserves whitespace like Preformatted
        formatted_code = '\n'.join(formatted_lines)

        return [XPreformatted(formatted_code, code_style)]

    # Alert color scheme (GitHub-aligned)
    ALERT_COLORS = {
        'NOTE':      {'border': '0969DA', 'shading': 'EDF5FD'},  # Blue
        'TIP':       {'border': '1A7F37', 'shading': 'EDFBF2'},  # Green
        'IMPORTANT': {'border': '8250DF', 'shading': 'F4EDFF'},  # Purple
        'WARNING':   {'border': '9A6700', 'shading': 'FEF9E7'},  # Amber
        'CAUTION':   {'border': 'CF222E', 'shading': 'FEF0F0'},  # Red
    }

    #: Task-list checkbox glyphs - Word's own checkbox defaults (U+2612 ballot
    #: box with X for done, U+2610 empty box), which DejaVu (PDF) and every
    #: browser (HTML) also carry. In DOCX they are tagged MS Gothic - the font
    #: Word draws its native checkboxes in - by style_docx_task_checkboxes().
    TASK_CHECKBOX_DONE = '☒'
    TASK_CHECKBOX_OPEN = '☐'

    def preprocess_task_lists(self, content: str) -> str:
        """Render GitHub task-list markers as Unicode checkbox glyphs.

        The markdown converter carries no task-list extension, so ``- [x]`` /
        ``- [ ]`` would pass through as literal ``[x]`` / ``[ ]`` text. Swapping
        the marker for a ballot glyph (done U+2612, open U+2610) renders a
        checkbox in every export format, since the glyph flows through as plain
        list text - HTML, DOCX and PDF all carry it in their body font.

        Fenced code blocks are skipped so a ``- [ ]`` written inside a code
        sample is not rewritten. Only a real list item (``[x]`` / ``[ ]`` / a
        space) matches, so ``- [link](url)`` is left alone.
        """
        task_re = re.compile(r'^(\s*[-*+]\s+)\[([ xX])\](?:\s+|$)')
        fence_re = re.compile(r'^\s*(`{3,}|~{3,})')

        def replace(match):
            box = (self.TASK_CHECKBOX_DONE if match.group(2) in 'xX'
                   else self.TASK_CHECKBOX_OPEN)
            return f'{match.group(1)}{box} '

        # Track the fence character and length so a ``` inside a ~~~ block (or a
        # shorter ``` inside a ```` block) is treated as content. Per CommonMark
        # a block closes only on a same-char fence at least as long as the
        # opener AND carrying no info string (a ```lang line is a nested opener,
        # never a closer), while the opening fence itself may carry one.
        out, fence_char, fence_len = [], None, 0
        for line in content.split('\n'):
            fence = fence_re.match(line)
            if fence:
                marker = fence.group(1)
                bare = not line[fence.end():].strip()
                if fence_char is None:
                    fence_char, fence_len = marker[0], len(marker)
                elif marker[0] == fence_char and len(marker) >= fence_len and bare:
                    fence_char, fence_len = None, 0
            elif fence_char is None:
                line = task_re.sub(replace, line)
            out.append(line)
        return '\n'.join(out)

    def preprocess_github_alerts(self, content: str, show_labels: bool = False) -> str:
        """Convert GitHub-style alerts to paragraphs with markers.

        Supports: NOTE, TIP, IMPORTANT, WARNING, CAUTION.
        Zero-width space markers (\u200b) around the type name allow
        post-processing in DOCX to apply colored styling.
        Preserves <br> tags and markdown links/formatting within alert content.
        When show_labels is False, the alert type label is hidden from output.
        """
        alert_pattern = r'> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\] *\n((?:> .*\n?)*)'

        def replace_alert(match):
            alert_type = match.group(1).upper()
            # Remove '> ' prefix from each line, preserve content including <br> and links
            alert_lines = match.group(2).strip().split('\n')
            alert_content = ' '.join(line.lstrip('> ').strip() for line in alert_lines if line.strip())

            # Zero-width space markers for DOCX post-processing
            marker = f'\u200b{alert_type}\u200b'
            if show_labels:
                return f'\n\n**{marker}:** {alert_content}\n\n'
            else:
                return f'\n\n{marker}{alert_content}\n\n'

        return re.sub(alert_pattern, replace_alert, content)

    def clean_alert_markers_from_html(self, html: str, show_labels: bool = False) -> str:
        """Remove zero-width space markers from HTML output.

        When show_labels is True, only strip the zero-width markers, keeping
        the alert type text visible. When False, strip both markers and the
        alert type text between them.
        """
        if show_labels:
            html = html.replace('\u200b', '')
        else:
            for alert_type in self.ALERT_COLORS:
                html = html.replace(f'\u200b{alert_type}\u200b', '')
            html = html.replace('\u200b', '')
        return html

    def drop_empty_table_headers(self, html: str) -> str:
        """Remove a table's header row when every header cell is empty.

        Markdown requires a header row, so a borderless image/layout grid is
        written with an empty one (`|  |  |  |`) and the converter emits a
        `<thead>` of blank `<th>`. DOCX and PDF drop that row; HTML must drop it
        too, or the same document renders with an extra blank banded strip in
        one format and not the others.

        Matched with a regex rather than a soup round-trip: this runs on the
        finished standalone document, and reparsing it would risk disturbing the
        embedded KaTeX/Pygments markup for a change this local.
        """
        if '<thead' not in html:
            return html

        def strip_tags(text):
            return unescape(re.sub(r'<[^>]+>', '', text)).strip()

        def replace(match):
            block = match.group(0)
            # Stripping tags erases an <img> along with them, so a header row
            # of pictures would read as blank - the DOCX and PDF paths keep
            # such a row for the same reason (image-on-top/caption-below grid)
            if re.search(r'<(img|svg|picture|video|object|iframe|input)\b',
                         block, re.I):
                return block
            cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', block, re.S)
            if cells and not any(strip_tags(c) for c in cells):
                return ''
            return block

        # Only when a body row survives the delete, as on the other two paths.
        # The tag pattern admits attributes so it cannot silently miss a
        # `<thead class="...">` the guard above already let through.
        if not re.search(r'</thead>\s*<tbody[^>]*>\s*<tr', html, re.I | re.S):
            return html
        return re.sub(r'<thead\b[^>]*>.*?</thead\s*>\s*', replace, html,
                      flags=re.S | re.I)

    def wrap_html_tables(self, html: str) -> str:
        """Put every table in a horizontal scroll box.

        Cell wrapping cannot shrink a table below one character per column, so
        a table with very many columns would push the whole document sideways.
        The box has to be a wrapper element: `overflow-x` on the table itself
        only takes effect with `display: block`, which turns the grid into a
        shrink-to-fit anonymous box and voids its width.

        Only outermost tables are wrapped, and a table's attributes are kept:
        a non-greedy regex would close the wrapper at a nested table's end tag,
        and browser error recovery then stretches the box over the rest of the
        document, scrolling every element that follows. Comments are matched
        and skipped so a `<table>` written inside `<!-- ... -->` (markdown
        passes comments through verbatim) cannot open a wrapper that never
        closes.

        HTML export only - the DOCX and PDF paths parse this markup with
        htmldocx and have their own page fitting.
        """
        out = []
        depth = 0
        start = 0
        for tag in re.finditer(r'<!--.*?-->|<table\b[^>]*>|</table\s*>', html,
                               flags=re.DOTALL):
            if tag.group().startswith('<!--'):
                continue
            if tag.group().startswith('</'):
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0:
                    out.append(html[start:tag.end()])
                    out.append('</div>')
                    start = tag.end()
            else:
                if depth == 0:
                    out.append(html[start:tag.start()])
                    out.append('<div class="table-scroll">')
                    start = tag.start()
                depth += 1
        out.append(html[start:])
        return ''.join(out)

    def style_html_alert_boxes(self, html: str, show_labels: bool = False) -> str:
        """Replace alert markers in HTML with styled div elements.

        Converts zero-width space markers into colored alert boxes with
        left border and background shading matching the DOCX alert style.

        HTML patterns from markdown conversion:
        - show_labels=True:  <p><strong>\u200bNOTE\u200b:</strong> content</p>
        - show_labels=False: <p>\u200bNOTE\u200bcontent</p>
        """
        for alert_type, colors in self.ALERT_COLORS.items():
            marker = f'\u200b{alert_type}\u200b'
            if marker not in html:
                continue

            border = f'#{colors["border"]}'
            shading = f'#{colors["shading"]}'

            if show_labels:
                # Pattern: <p><strong>\u200bTYPE\u200b:</strong> content</p>
                pattern = re.compile(
                    r'<p><strong>' + re.escape(marker) + r':?</strong>\s*(.*?)</p>',
                    re.DOTALL
                )

                def make_alert(m, _border=border, _shading=shading, _type=alert_type):
                    content = m.group(1).strip()
                    return (
                        f'<div style="border-left:4px solid {_border};'
                        f'background:{_shading};padding:12px 16px;'
                        f'border-radius:4px;margin:1em 0">'
                        f'<strong>{_type}:</strong> {content}</div>'
                    )
            else:
                # Pattern: <p>\u200bTYPE\u200bcontent</p>
                pattern = re.compile(
                    r'<p>' + re.escape(marker) + r'(.*?)</p>',
                    re.DOTALL
                )

                def make_alert(m, _border=border, _shading=shading):
                    content = m.group(1).strip()
                    return (
                        f'<div style="border-left:4px solid {_border};'
                        f'background:{_shading};padding:12px 16px;'
                        f'border-radius:4px;margin:1em 0">'
                        f'{content}</div>'
                    )

            html = pattern.sub(make_alert, html)

        # Clean any remaining stray markers
        html = html.replace('\u200b', '')
        return html

    def render_math_to_png(self, latex: str, width: int = 800, display: bool = False) -> str:
        """Render a LaTeX math expression to a PNG base64 data URI.

        Uses matplotlib.mathtext to render LaTeX to PNG with a transparent
        background, scaled so the result is approximately `width` pixels
        wide. The PNG's DPI metadata is then set so reportlab places it at
        the right physical size in the PDF (12pt tall inline, 16pt display).

        Args:
            latex: LaTeX math expression (without delimiters)
            width: Target pixel width for the rendered image
            display: If True, use larger font size for display math
        """
        from matplotlib.mathtext import math_to_image
        from matplotlib.font_manager import FontProperties
        from PIL import Image as PILImage

        fontsize = 16 if display else 12
        prop = FontProperties(size=fontsize)

        # matplotlib mathtext requires $ delimiters
        tex = f'${latex.strip()}$'

        # Probe render at a reference DPI to learn the equation's natural width,
        # then re-render at a DPI that lands close to the requested pixel width
        # (clamped so tiny inline equations don't get absurd DPIs).
        ref_dpi = 200
        probe = io.BytesIO()
        math_to_image(tex, probe, dpi=ref_dpi, format='png', prop=prop)
        probe.seek(0)
        probe_w = max(1, PILImage.open(probe).width)
        render_dpi = ref_dpi * width / probe_w
        render_dpi = max(72.0, min(1200.0, render_dpi))

        buf = io.BytesIO()
        math_to_image(tex, buf, dpi=render_dpi, format='png', prop=prop)
        buf.seek(0)

        # Fix DPI metadata so reportlab sizes the image at fontsize points tall.
        img = PILImage.open(buf)
        target_height_inches = fontsize / 72  # points to inches
        effective_dpi = img.height / target_height_inches
        corrected_buf = io.BytesIO()
        img.save(corrected_buf, format='png', dpi=(effective_dpi, effective_dpi))
        corrected_buf.seek(0)

        b64 = base64.b64encode(corrected_buf.read()).decode('ascii')
        return f'data:image/png;base64,{b64}'

    def replace_math_with_images(self, content: str, width: int = 800) -> str:
        """Replace LaTeX math delimiters with rendered PNG images (PDF export).

        Protects code blocks (fenced and inline) before processing.
        Matches $$...$$ (display) and $...$ (inline) while avoiding
        false positives on currency amounts like $100.

        Args:
            content: Markdown content with LaTeX math expressions
            width: Target pixel width for each rendered math image
        """
        # Protect code blocks by replacing with placeholders
        code_placeholders = []

        # Protect fenced code blocks (```...```)
        def protect_fenced(match):
            code_placeholders.append(match.group(0))
            return f'[[MATH_CODE_BLOCK_{len(code_placeholders) - 1}]]'

        content = re.sub(r'```[\s\S]*?```', protect_fenced, content)

        # Protect inline code (`...`)
        def protect_inline(match):
            code_placeholders.append(match.group(0))
            return f'[[MATH_CODE_BLOCK_{len(code_placeholders) - 1}]]'

        content = re.sub(r'`[^`]+`', protect_inline, content)

        # Protect escaped dollars from being matched as math delimiters
        # Handle \\$ (double backslash + dollar, common in markdown/LaTeX) first,
        # then \$ (single backslash + dollar). Both render as literal $ in output.
        content = content.replace('\\\\$', '[[ESCAPED_DOLLAR]]')
        content = content.replace('\\$', '[[ESCAPED_DOLLAR]]')

        # Replace display math $$...$$ first (greedy within single expression)
        def replace_display(match):
            latex = match.group(1)
            try:
                data_uri = self.render_math_to_png(latex, width=width, display=True)
                return f'\n\n<div style="text-align:center"><img src="{data_uri}" alt="{latex}" style="max-width:100%"></div>\n\n'
            except Exception:
                return match.group(0)

        content = re.sub(r'\$\$(.+?)\$\$', replace_display, content, flags=re.DOTALL)

        # Replace inline math $...$ (require non-space after opening and before closing $)
        def replace_inline(match):
            latex = match.group(1)
            try:
                data_uri = self.render_math_to_png(latex, width=width, display=False)
                return f'<img src="{data_uri}" alt="{latex}" style="vertical-align:middle">'
            except Exception:
                return match.group(0)

        content = re.sub(r'(?<!\$)\$(\S(?:[^$]*?\S)?)\$(?!\$)', replace_inline, content)

        # Restore escaped dollars as literal $ (both \$ and \\$ mean literal dollar)
        content = content.replace('[[ESCAPED_DOLLAR]]', '$')

        # Restore code blocks
        for i, block in enumerate(code_placeholders):
            content = content.replace(f'[[MATH_CODE_BLOCK_{i}]]', block)

        return content

    def latex_to_omml(self, latex: str):
        """Convert LaTeX to OMML element for Word documents.

        Pipeline: LaTeX -> MathML (latex2mathml) -> OMML (XSLT mml2omml.xsl)
        Returns an lxml Element with the oMath OMML structure.

        Post-processes nary operators (sum, prod, int) whose <e/> element
        is empty - moves all following siblings into <e> so Word renders
        the summand/integrand inside the operator rather than showing
        a dashed placeholder square.
        """
        import latex2mathml.converter
        from lxml import etree

        mathml = latex2mathml.converter.convert(latex)
        tree = etree.fromstring(mathml.encode('utf-8'))

        xsl_path = Path(__file__).parent / 'mml2omml.xsl'
        xslt = etree.parse(str(xsl_path))
        transform = etree.XSLT(xslt)
        omml = transform(tree)
        root = omml.getroot()

        # Fix nary operators with empty <e/> by moving following siblings in
        OMML_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
        for nary in root.iter(f'{{{OMML_NS}}}nary'):
            e_elem = nary.find(f'{{{OMML_NS}}}e')
            if e_elem is not None and len(e_elem) == 0 and (e_elem.text is None or not e_elem.text.strip()):
                parent = nary.getparent()
                if parent is not None:
                    siblings = list(parent)
                    nary_idx = siblings.index(nary)
                    # Move all elements after nary into <e>
                    for sibling in siblings[nary_idx + 1:]:
                        parent.remove(sibling)
                        e_elem.append(sibling)

        return root

    def replace_math_with_markers(self, content: str):
        """Replace LaTeX math delimiters with text markers for DOCX post-processing.

        Instead of rendering math as images, inserts zero-width joiner markers
        that are later replaced with native OMML equations after htmldocx processing.

        Returns (content, inline_math_list, display_math_list).
        """
        inline_math = []
        display_math = []

        # Protect code blocks by replacing with placeholders
        code_placeholders = []

        def protect_fenced(match):
            code_placeholders.append(match.group(0))
            return f'[[MATH_CODE_BLOCK_{len(code_placeholders) - 1}]]'

        content = re.sub(r'```[\s\S]*?```', protect_fenced, content)

        def protect_inline(match):
            code_placeholders.append(match.group(0))
            return f'[[MATH_CODE_BLOCK_{len(code_placeholders) - 1}]]'

        content = re.sub(r'`[^`]+`', protect_inline, content)

        # Protect escaped dollars from being matched as math delimiters
        # Handle \\$ (double backslash + dollar, common in markdown/LaTeX) first,
        # then \$ (single backslash + dollar). Both render as literal $ in output.
        content = content.replace('\\\\$', '[[ESCAPED_DOLLAR]]')
        content = content.replace('\\$', '[[ESCAPED_DOLLAR]]')

        # Replace display math $$...$$ first
        def replace_display(match):
            latex = match.group(1)
            idx = len(display_math)
            display_math.append(latex)
            return f'\n\n\u200dMATH_DISPLAY_{idx}\u200d\n\n'

        content = re.sub(r'\$\$(.+?)\$\$', replace_display, content, flags=re.DOTALL)

        # Replace inline math $...$
        def replace_inline(match):
            latex = match.group(1)
            idx = len(inline_math)
            inline_math.append(latex)
            return f'\u200dMATH_INLINE_{idx}\u200d'

        content = re.sub(r'(?<!\$)\$(\S(?:[^$]*?\S)?)\$(?!\$)', replace_inline, content)

        # Restore escaped dollars as literal $ (both \$ and \\$ mean literal dollar)
        content = content.replace('[[ESCAPED_DOLLAR]]', '$')

        # Restore code blocks
        for i, block in enumerate(code_placeholders):
            content = content.replace(f'[[MATH_CODE_BLOCK_{i}]]', block)

        return content, inline_math, display_math

    def merge_inline_math_omml(self, document, inline_math, display_math):
        """Post-process DOCX to replace math markers with native OMML equations.

        Scans all paragraph runs for MATH_INLINE_N and MATH_DISPLAY_N markers,
        splits runs at marker boundaries, and inserts OMML elements.
        """
        from docx.oxml.ns import qn
        from lxml import etree
        import copy

        OMML_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'

        for paragraph in document.paragraphs:
            full_text = paragraph.text

            # Handle display math (marker in its own paragraph)
            for idx, latex in enumerate(display_math):
                marker = f'\u200dMATH_DISPLAY_{idx}\u200d'
                if marker in full_text:
                    try:
                        omml_elem = self.latex_to_omml(latex)
                        # Create oMathPara wrapper for display (centered) math
                        omath_para = etree.SubElement(
                            paragraph._p, f'{{{OMML_NS}}}oMathPara'
                        )
                        omath_para.append(omml_elem)
                        # Remove all existing runs (marker text)
                        for run in paragraph.runs:
                            run._r.getparent().remove(run._r)
                    except Exception:
                        # Fallback: leave marker text (will show raw LaTeX)
                        for run in paragraph.runs:
                            if marker in run.text:
                                run.text = run.text.replace(marker, latex)

            # Handle inline math (marker within text runs)
            for idx, latex in enumerate(inline_math):
                marker = f'\u200dMATH_INLINE_{idx}\u200d'
                if marker not in full_text:
                    continue

                # Find the run containing the marker
                for run in list(paragraph.runs):
                    if marker not in run.text:
                        continue

                    try:
                        omml_elem = self.latex_to_omml(latex)
                    except Exception:
                        run.text = run.text.replace(marker, latex)
                        continue

                    parts = run.text.split(marker, 1)
                    parent = run._r.getparent()
                    run_index = list(parent).index(run._r)

                    # Set before-text in current run
                    run.text = parts[0]

                    # Insert OMML element after current run
                    parent.insert(run_index + 1, omml_elem)

                    # Create after-text run if needed
                    if parts[1]:
                        after_run = copy.deepcopy(run._r)
                        after_run.find(qn('w:t')).text = parts[1]
                        parent.insert(run_index + 2, after_run)

                    break  # Only one marker per run expected

    def style_docx_alert_boxes(self, document, show_labels: bool = False) -> list:
        """Replace alert paragraphs with styled single-cell tables.

        Scans for zero-width space markers inserted by preprocess_github_alerts()
        and wraps each alert in a one-cell table with colored left border,
        background shading, and cell margins for padding control.
        Moves the original paragraph XML (preserving hyperlinks, bold, etc.)
        into the table cell rather than rebuilding it.

        Returns the ``w:tbl`` elements created, which carry their own styling
        and must be left out of the content-table pass.
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        import copy

        # Collect paragraphs to replace (can't modify while iterating)
        alert_tables = []
        replacements = []
        for paragraph in document.paragraphs:
            text = paragraph.text
            for alert_type, colors in self.ALERT_COLORS.items():
                marker = f'\u200b{alert_type}\u200b'
                if marker not in text:
                    continue
                replacements.append((paragraph, alert_type, colors))
                break

        for paragraph, alert_type, colors in replacements:
            parent = paragraph._p.getparent()

            # Clean zero-width markers from runs; strip type label only when hidden
            for run in paragraph.runs:
                text = run.text
                if '\u200b' in text:
                    cleaned = text.replace('\u200b', '')
                    if not show_labels:
                        for at in self.ALERT_COLORS:
                            if cleaned.startswith(at):
                                cleaned = cleaned[len(at):]
                                if cleaned.startswith(':'):
                                    cleaned = cleaned[1:]
                                cleaned = cleaned.lstrip()
                                break
                    run.text = cleaned

            # Build the one-cell table
            tbl = OxmlElement('w:tbl')

            # Table properties: 100% width via percentage
            tblPr = OxmlElement('w:tblPr')
            tblW = OxmlElement('w:tblW')
            tblW.set(qn('w:w'), '5000')
            tblW.set(qn('w:type'), 'pct')
            tblPr.append(tblW)

            # Table borders: only left border colored, others invisible
            tblBorders = OxmlElement('w:tblBorders')
            for side in ['top', 'bottom', 'right', 'insideH', 'insideV']:
                border = OxmlElement(f'w:{side}')
                border.set(qn('w:val'), 'none')
                border.set(qn('w:sz'), '0')
                border.set(qn('w:space'), '0')
                border.set(qn('w:color'), 'auto')
                tblBorders.append(border)
            left_border = OxmlElement('w:left')
            left_border.set(qn('w:val'), 'single')
            left_border.set(qn('w:sz'), '24')  # 3pt
            left_border.set(qn('w:space'), '0')
            left_border.set(qn('w:color'), colors['border'])
            tblBorders.append(left_border)
            tblPr.append(tblBorders)

            # Cell margins for internal padding
            tblCellMar = OxmlElement('w:tblCellMar')
            for side, val in [('top', '80'), ('bottom', '80'),
                              ('left', '180'), ('right', '120')]:
                margin = OxmlElement(f'w:{side}')
                margin.set(qn('w:w'), val)
                margin.set(qn('w:type'), 'dxa')
                tblCellMar.append(margin)
            tblPr.append(tblCellMar)

            tbl.append(tblPr)

            # Table grid (single column)
            tblGrid = OxmlElement('w:tblGrid')
            gridCol = OxmlElement('w:gridCol')
            gridCol.set(qn('w:w'), '9360')
            tblGrid.append(gridCol)
            tbl.append(tblGrid)

            # Single row, single cell
            tr = OxmlElement('w:tr')
            tc = OxmlElement('w:tc')
            tcPr = OxmlElement('w:tcPr')
            tcW = OxmlElement('w:tcW')
            tcW.set(qn('w:w'), '5000')
            tcW.set(qn('w:type'), 'pct')
            tcPr.append(tcW)

            # Cell shading
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), colors['shading'])
            tcPr.append(shd)
            tc.append(tcPr)

            # Move the original paragraph into the cell (preserves all formatting,
            # hyperlinks, bold, italic, line breaks, etc.)
            tc.append(copy.deepcopy(paragraph._p))
            tr.append(tc)
            tbl.append(tr)

            # Insert table then a spacer paragraph after the original paragraph
            paragraph._p.addnext(tbl)
            spacer = OxmlElement('w:p')
            tbl.addnext(spacer)

            # Remove the original paragraph
            parent.remove(paragraph._p)
            alert_tables.append(tbl)

        return alert_tables

    def style_docx_task_checkboxes(self, document):
        """Draw task-list checkbox glyphs in MS Gothic - the font Word uses for
        its own checkboxes - so they render solid on Windows instead of via a
        thin Calibri fallback. Each glyph is split into its own run and only
        that run gets the font, leaving the item text in the body font.
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        import copy

        glyphs = (self.TASK_CHECKBOX_DONE, self.TASK_CHECKBOX_OPEN)

        def set_gothic(r_elem):
            rPr = r_elem.find(qn('w:rPr'))
            if rPr is None:
                rPr = OxmlElement('w:rPr')
                r_elem.insert(0, rPr)
            rFonts = rPr.find(qn('w:rFonts'))
            if rFonts is None:
                rFonts = OxmlElement('w:rFonts')
                # rFonts must follow w:rStyle in the CT_RPr sequence
                rStyle = rPr.find(qn('w:rStyle'))
                if rStyle is not None:
                    rStyle.addnext(rFonts)
                else:
                    rPr.insert(0, rFonts)
            for attr in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
                rFonts.set(qn(attr), 'MS Gothic')

        def segment(text):
            out, buf, buf_glyph = [], '', None
            for ch in text:
                is_g = ch in glyphs
                if buf and is_g != buf_glyph:
                    out.append((buf, buf_glyph))
                    buf = ''
                buf += ch
                buf_glyph = is_g
            if buf:
                out.append((buf, buf_glyph))
            return out

        for r_elem in list(document.element.body.iter(qn('w:r'))):
            t_elem = r_elem.find(qn('w:t'))
            if t_elem is None or not t_elem.text:
                continue
            if not any(g in t_elem.text for g in glyphs):
                continue

            segments = segment(t_elem.text)

            # Formatting-only template: carries the run's rPr but none of its
            # content (w:t/w:br/w:tab/w:drawing), so cloned segment runs get a
            # fresh single w:t and never duplicate the original's breaks/tabs.
            template = copy.deepcopy(r_elem)
            for child in list(template):
                if child.tag != qn('w:rPr'):
                    template.remove(child)

            first_text, first_glyph = segments[0]
            t_elem.text = first_text
            t_elem.set(qn('xml:space'), 'preserve')
            if first_glyph:
                set_gothic(r_elem)

            anchor = r_elem
            for seg_text, seg_glyph in segments[1:]:
                new_r = copy.deepcopy(template)
                nt = OxmlElement('w:t')
                nt.text = seg_text
                nt.set(qn('xml:space'), 'preserve')
                new_r.append(nt)
                if seg_glyph:
                    set_gothic(new_r)
                anchor.addnext(new_r)
                anchor = new_r

    def remove_empty_paragraphs_before_images(self, document):
        """Remove empty paragraphs that immediately precede image paragraphs.

        htmldocx inserts blank paragraphs before images. This removes them
        to eliminate unnecessary vertical space above images.
        """
        from docx.oxml.ns import qn
        body = document.element.body
        paragraphs = body.findall(qn('w:p'))
        to_remove = []
        for i in range(len(paragraphs) - 1):
            current = paragraphs[i]
            nxt = paragraphs[i + 1]
            # Check if current paragraph is empty (no text content)
            if current.text and current.text.strip():
                continue
            runs = current.findall('.//' + qn('w:t'))
            if any(r.text and r.text.strip() for r in runs):
                continue
            # Check current has no image itself
            if (current.findall('.//' + qn('w:drawing')) or
                    current.findall('.//{urn:schemas-microsoft-com:vml}imagedata')):
                continue
            # Check next paragraph contains an image
            if (nxt.findall('.//' + qn('w:drawing')) or
                    nxt.findall('.//{urn:schemas-microsoft-com:vml}imagedata')):
                to_remove.append(current)
        for p in to_remove:
            p.getparent().remove(p)

    # Unicode sentinels for bookmark markers injected into HTML.
    # U+2063 (INVISIBLE SEPARATOR) is unlikely to appear in normal text and
    # survives htmldocx as literal text that we can regex-match later.
    _BOOKMARK_MARKER_RE = re.compile(r'⁣BM:([A-Za-z0-9_\-:.]+)⁣')
    _SAFE_BOOKMARK_ID_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_\-:.]*$')

    def inject_anchor_markers(self, html: str) -> str:
        """Inject sentinel markers for every HTML element with an id attribute.

        For ``<span id="D119">D119 ...</span>`` injects
        ``<span id="D119">⁣BM:D119⁣D119 ...</span>``. The marker
        survives htmldocx as plain text and is later converted into a Word
        bookmark by apply_anchor_bookmarks().
        """
        def replace(match):
            open_tag = match.group(0)
            anchor_id = match.group(1)
            if not self._SAFE_BOOKMARK_ID_RE.match(anchor_id):
                return open_tag
            return f'{open_tag}⁣BM:{anchor_id}⁣'

        return re.sub(r'<[^>]*?\bid="([^"]+)"[^>]*?>', replace, html)

    def apply_anchor_bookmarks(self, document):
        """Convert bookmark markers and external hash hyperlinks into internal anchors.

        Works in two passes on the finished DOCX tree:

        1. Replaces each ``⁣BM:NAME⁣`` marker in a run's text with a
           ``w:bookmarkStart`` / ``w:bookmarkEnd`` pair, preserving surrounding text.
        2. Rewrites every ``<w:hyperlink r:id="...">`` that points to a hash-prefix
           external relationship into ``<w:hyperlink w:anchor="NAME">`` and drops
           the now-unused relationship. htmldocx always writes anchor links as
           external, so this rescues them.
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        import copy

        body = document.element.body
        bookmark_id = 0

        for run_elem in list(body.iter(qn('w:r'))):
            t_elem = run_elem.find(qn('w:t'))
            if t_elem is None or not t_elem.text:
                continue
            text = t_elem.text
            match = self._BOOKMARK_MARKER_RE.search(text)
            if not match:
                continue

            anchor_name = match.group(1)
            before = text[:match.start()]
            after = text[match.end():]

            parent = run_elem.getparent()
            run_index = list(parent).index(run_elem)

            t_elem.text = before

            bm_start = OxmlElement('w:bookmarkStart')
            bm_start.set(qn('w:id'), str(bookmark_id))
            bm_start.set(qn('w:name'), anchor_name)
            bm_end = OxmlElement('w:bookmarkEnd')
            bm_end.set(qn('w:id'), str(bookmark_id))
            bookmark_id += 1

            parent.insert(run_index + 1, bm_start)
            parent.insert(run_index + 2, bm_end)

            if after:
                after_run = copy.deepcopy(run_elem)
                after_t = after_run.find(qn('w:t'))
                if after_t is not None:
                    after_t.text = after
                parent.insert(run_index + 3, after_run)

        HYPERLINK_RELTYPE = (
            'http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/hyperlink'
        )
        rels = document.part.rels
        anchor_rels = {
            rel_id: rel.target_ref[1:]
            for rel_id, rel in rels.items()
            if rel.reltype == HYPERLINK_RELTYPE and rel.target_ref.startswith('#')
        }
        if not anchor_rels:
            return

        r_id_qn = qn('r:id')
        anchor_qn = qn('w:anchor')
        for hyperlink in body.iter(qn('w:hyperlink')):
            ref = hyperlink.get(r_id_qn)
            if ref in anchor_rels:
                del hyperlink.attrib[r_id_qn]
                hyperlink.set(anchor_qn, anchor_rels[ref])

        for rel_id in anchor_rels:
            del rels[rel_id]

    _BLOCKQUOTE_MARKER_RE = re.compile(r'⁣BQ:(\d+)⁣')
    _PILL_MARKER_RE = re.compile(r'⁣PILL:([0-9A-Fa-f]{6})⁣')

    # CSS named colours htmldocx fails to parse (it only understands hex),
    # so a `color: green` span renders black. Mapped to hex here. Covers the
    # standard 16 plus the few extended names that show up in practice.
    _CSS_NAMED_COLORS = {
        'black': '000000', 'silver': 'C0C0C0', 'gray': '808080',
        'grey': '808080', 'white': 'FFFFFF', 'maroon': '800000',
        'red': 'FF0000', 'purple': '800080', 'fuchsia': 'FF00FF',
        'magenta': 'FF00FF', 'green': '008000', 'lime': '00FF00',
        'olive': '808000', 'yellow': 'FFFF00', 'navy': '000080',
        'blue': '0000FF', 'teal': '008080', 'aqua': '00FFFF',
        'cyan': '00FFFF', 'orange': 'FFA500', 'pink': 'FFC0CB',
        'brown': 'A52A2A', 'gold': 'FFD700', 'darkgreen': '006400',
        'darkred': '8B0000', 'darkblue': '00008B',
    }

    @classmethod
    def _normalize_css_color(cls, value: str) -> str:
        """Return a 6-hex (no #) for a CSS colour value, or '' if not resolvable."""
        v = value.strip().lower()
        if v.startswith('#'):
            h = v[1:]
            if len(h) == 3:
                h = ''.join(c * 2 for c in h)
            if len(h) == 6 and all(c in '0123456789abcdef' for c in h):
                return h.upper()
            return ''
        return cls._CSS_NAMED_COLORS.get(v, '')

    def restructure_html_for_docx(self, html: str) -> str:
        """Fix htmldocx structural and styling blind spots before conversion.

        Handles four htmldocx limitations:

        1. Loose list items (``<li><p>text</p>...</li>``) - ``handle_li``
           opens a bullet paragraph, then the inner ``<p>`` opens a fresh
           ``Normal`` paragraph, so the bullet glyph ends up empty and the
           text loses its bullet. Unwrapping the leading ``<p>`` of each
           ``<li>`` puts the text back into the bullet paragraph.
        2. Blockquotes - there is no ``<blockquote>`` handler at all, so the
           inner ``<p>`` become plain paragraphs with no indent or bar. A
           sentinel marker ``⁣BQ:<indent>⁣`` is injected.
        3. Named CSS text colours (``color: green``) - htmldocx parses only
           hex, rendering named colours black. Normalised to hex in-place.
        4. Coloured pills (``background-color`` spans) - htmldocx maps a CSS
           background to a Word *highlight* from a tiny fixed palette, so an
           arbitrary hex becomes ``lightGray``. The background is stripped
           from the style and re-encoded as a ``⁣PILL:<hex>⁣`` marker
           that style_docx_color_runs() turns into true run shading.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        # 1. Loose list items: merge a leading <p> into the <li> itself
        for li in soup.find_all('li'):
            first_el = next(
                (c for c in li.children if getattr(c, 'name', None)), None
            )
            if first_el is not None and first_el.name == 'p':
                first_el.unwrap()

        # 2. Blockquote paragraphs: prefix an indent-encoding marker
        for bq in soup.find_all('blockquote'):
            depth_bq = len(bq.find_parents('blockquote')) + 1
            depth_list = len(bq.find_parents(['ul', 'ol']))
            indent_in = depth_list * 0.5 + depth_bq * 0.3
            marker = f'⁣BQ:{int(round(indent_in * 100))}⁣'
            paras = bq.find_all('p', recursive=False)
            if paras:
                for p in paras:
                    p.insert(0, marker)
            else:
                bq.insert(0, marker)

        # 3 & 4. Inline colour / pill styling on any element with a style attr
        for el in soup.find_all(style=True):
            style = el.get('style', '')
            decls = [d.strip() for d in style.split(';') if d.strip()]
            kept, fg_hex, bg_hex = [], '', ''
            for d in decls:
                if ':' not in d:
                    kept.append(d)
                    continue
                prop, val = d.split(':', 1)
                prop = prop.strip().lower()
                if prop == 'color':
                    h = self._normalize_css_color(val)
                    if h:
                        fg_hex = h
                        kept.append(f'color:#{h}')
                    else:
                        kept.append(d)
                elif prop == 'background-color' or prop == 'background':
                    h = self._normalize_css_color(val.split()[0] if val.split() else '')
                    if h:
                        bg_hex = h  # drop from style; re-encode as marker below
                    else:
                        kept.append(d)
                else:
                    kept.append(d)
            if bg_hex:
                el['style'] = ';'.join(kept)
                el.insert(0, f'⁣PILL:{bg_hex}⁣')
            elif fg_hex:
                el['style'] = ';'.join(kept)

        return str(soup)

    def style_docx_color_runs(self, document):
        """Apply true run shading (``w:shd``) to runs carrying a pill marker
        from restructure_html_for_docx(). htmldocx can only express a CSS
        background as a Word highlight from a fixed palette; this gives the
        exact hex fill instead. Strips the marker afterwards.
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.text.paragraph import Paragraph

        body = document.element.body
        for p_elem in body.iter(qn('w:p')):
            paragraph = Paragraph(p_elem, document)
            for run in paragraph.runs:
                text = run.text or ''
                m = self._PILL_MARKER_RE.search(text)
                if not m:
                    continue
                fill = m.group(1)
                run.text = self._PILL_MARKER_RE.sub('', text)

                rPr = run._r.get_or_add_rPr()
                # Remove any highlight htmldocx may have added for the bg
                for hl in rPr.findall(qn('w:highlight')):
                    rPr.remove(hl)
                existing = rPr.find(qn('w:shd'))
                if existing is not None:
                    rPr.remove(existing)
                shd = OxmlElement('w:shd')
                shd.set(qn('w:val'), 'clear')
                shd.set(qn('w:color'), 'auto')
                shd.set(qn('w:fill'), fill)
                rPr.append(shd)

    def style_docx_blockquotes(self, document):
        """Apply indent, a gray left bar, light shading and muted italic text
        to paragraphs carrying the blockquote marker from
        restructure_html_for_docx(). Strips the marker afterwards.
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.shared import Inches, RGBColor

        # Successors of w:pBdr / w:shd in the CT_PPr schema - inserting before
        # these keeps the element order valid (mirrors htmldocx's hr handler).
        pbdr_succ = (
            'w:shd', 'w:tabs', 'w:suppressAutoHyphens', 'w:kinsoku',
            'w:wordWrap', 'w:overflowPunct', 'w:topLinePunct', 'w:autoSpaceDE',
            'w:autoSpaceDN', 'w:bidi', 'w:adjustRightInd', 'w:snapToGrid',
            'w:spacing', 'w:ind', 'w:contextualSpacing', 'w:mirrorIndents',
            'w:suppressOverlap', 'w:jc', 'w:textDirection', 'w:textAlignment',
            'w:textboxTightWrap', 'w:outlineLvl', 'w:divId', 'w:cnfStyle',
            'w:rPr', 'w:sectPr', 'w:pPrChange',
        )
        shd_succ = pbdr_succ[1:]

        # Iterate every paragraph in the body, including those nested in table
        # cells (document.paragraphs only yields body-level paragraphs, so a
        # blockquote inside a table would otherwise keep its raw marker).
        from docx.text.paragraph import Paragraph
        body = document.element.body
        for p_elem in body.iter(qn('w:p')):
            paragraph = Paragraph(p_elem, document)
            match = self._BLOCKQUOTE_MARKER_RE.search(paragraph.text or '')
            if not match:
                continue
            indent_in = int(match.group(1)) / 100.0

            # Strip the marker from whichever run(s) carry it
            for run in paragraph.runs:
                if run.text and '⁣' in run.text:
                    run.text = self._BLOCKQUOTE_MARKER_RE.sub('', run.text)

            paragraph.paragraph_format.left_indent = Inches(indent_in)

            pPr = paragraph._p.get_or_add_pPr()

            existing = pPr.find(qn('w:pBdr'))
            if existing is not None:
                pPr.remove(existing)
            pBdr = OxmlElement('w:pBdr')
            left = OxmlElement('w:left')
            left.set(qn('w:val'), 'single')
            left.set(qn('w:sz'), '18')      # ~2.25pt bar
            left.set(qn('w:space'), '12')   # gap bar-to-text
            left.set(qn('w:color'), 'BBBBBB')
            pBdr.append(left)
            pPr.insert_element_before(pBdr, *pbdr_succ)

            existing_shd = pPr.find(qn('w:shd'))
            if existing_shd is not None:
                pPr.remove(existing_shd)
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), 'F4F4F4')
            pPr.insert_element_before(shd, *shd_succ)

            for run in paragraph.runs:
                run.font.italic = True
                run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    def strip_monospace_from_unicode_runs(self, document):
        """Drop monospace font overrides from runs containing non-ASCII characters.

        htmldocx applies Courier font to every ``<code>``/``<pre>`` run, but
        Courier does not contain unicode arrows (U+2190 etc.) and many symbol
        glyphs. Stripping the rFonts override lets Word render these characters
        in the body font (Cambria), which has full arrow coverage.
        """
        from docx.oxml.ns import qn
        MONOSPACE_FONTS = {'Courier', 'Courier New', 'Consolas', 'Monaco'}
        body = document.element.body
        for run_elem in body.iter(qn('w:r')):
            text = ''.join((t.text or '') for t in run_elem.findall(qn('w:t')))
            if not text or text.isascii():
                continue
            rpr = run_elem.find(qn('w:rPr'))
            if rpr is None:
                continue
            rfonts = rpr.find(qn('w:rFonts'))
            if rfonts is None:
                continue
            if (rfonts.get(qn('w:ascii')) or '') in MONOSPACE_FONTS:
                rpr.remove(rfonts)

    @staticmethod
    def fit_column_widths(natural: list, minimums: list, available: float) -> list:
        """Scale natural column widths down so the row fits ``available``.

        ``natural`` holds the width each column would take on a single line and
        ``minimums`` the width of its longest unbreakable word. When the natural
        widths already fit they are returned untouched. Otherwise every column
        keeps its minimum - so wrapping falls on word boundaries rather than
        mid-word - and the remaining space is shared in proportion to the
        excess, keeping wide columns wide. Falls back to equal columns when
        every column is already capped at its fair share.
        """
        ncols = len(natural)
        if ncols == 0:
            return []
        if sum(natural) <= available:
            return natural
        # No single column may claim more than its fair share as a minimum,
        # otherwise one very long word starves every other column.
        fair_share = available / ncols
        minimums = [min(m, fair_share) for m in minimums]
        slack = available - sum(minimums)
        excess = [max(0.0, n - m) for n, m in zip(natural, minimums)]
        if slack == 0 or sum(excess) == 0:
            return [fair_share] * ncols
        scale = slack / sum(excess)
        return [m + e * scale for m, e in zip(minimums, excess)]

    @classmethod
    def measured_column_widths(cls, table_data: list, available: float,
                               measure, floors: list | None = None) -> list:
        """Column widths for a table of cell strings that fit ``available``.

        ``measure(text, row_index)`` returns the rendered width of one string,
        letting the caller supply the font metrics. A cell's natural width is
        its longest line, its minimum the longest word it cannot break, and
        ``floors`` adds a per-column lower bound for content this cannot see
        (an image - only the DOCX path passes any; the PDF path renders a cell
        image but scales it to whatever column its text earns rather than
        flooring the column to it). Every column keeps at least the width of an
        empty cell, so none comes back zero-width, unless an equal share of
        ``available`` is itself smaller than that.
        """
        ncols = max((len(row) for row in table_data), default=0)
        natural, minimums = [], []
        for c in range(ncols):
            cells = [(r, row[c]) for r, row in enumerate(table_data)
                     if c < len(row)]
            # No floor may exceed an equal share, or one column starves the rest
            floor = min(max(floors[c] if floors else 0.0, measure('', 0)),
                        available / ncols)
            natural.append(max(
                [measure(line, r) for r, t in cells for line in t.split('\n')]
                + [floor]))
            minimums.append(max(
                [measure(word, r) for r, t in cells for word in t.split()]
                + [floor]))
        return cls.fit_column_widths(natural, minimums, available)

    @classmethod
    def pdf_table_column_layout(cls, table_data: list, available: float,
                                string_width, image_widths: list | None = None) -> tuple:
        """Cell padding and column widths for a PDF table of ``available`` width.

        ``string_width(text, row_index)`` measures rendered text. reportlab
        raises rather than rendering when a column is no wider than its own
        padding, so a table with very many columns gets a tighter padding
        instead of a width floor that would push it back off the page. The
        widths always sum to at most ``available``.

        ``image_widths`` is a per-column content width (points) for the widest
        cell image, so an image-only cell - which earns no width from its empty
        text - floors its column to the image instead of collapsing to a few
        points (the DOCX path floors the same way). measured_column_widths caps
        each floor at a fair share so an image cannot starve its text neighbours.

        Past roughly 150 columns a column is narrower than a single wide glyph
        at any font size used here, and reportlab paints such a glyph past its
        column - the borders stay inside the margin but the ink can pass it by
        a point or two. Such a table is unreadable regardless.
        """
        ncols = max((len(row) for row in table_data), default=1) or 1
        fair_share = available / ncols
        # Full padding while columns are roomy, then step down so reportlab
        # still has room to render as the fair share shrinks past the padding
        # (>= 16pt) and then past a hairline column (>= 3pt)
        full = cls.PDF_TABLE_CELL_PADDING
        side_padding = full if fair_share >= 16 else (1 if fair_share >= 3 else 0)
        # Both paddings, plus rounding slack so a word whose width matches its
        # column is not split mid-word
        cell_padding = 2 * side_padding + 2

        def measure(text, row_index):
            return string_width(text, row_index) + cell_padding

        # An image floor is the image content width plus the same padding a
        # text measurement carries, so the column holds the image at full size
        floors = None
        if image_widths and any(image_widths):
            floors = [w + cell_padding if w else 0.0 for w in image_widths]

        # The empty-cell floor already keeps every width above the padding
        return side_padding, cls.measured_column_widths(
            table_data, available, measure, floors)

    # Cell content a `w:t` run does not carry, so `cell.text` cannot see it.
    # The blank-row predicate is the only thing between the header delete below
    # and silent data loss, so it tests every kind this pipeline can emit.
    DOCX_CONTENT_ELEMENTS = (
        'w:drawing',                                  # inline/floating picture
        'w:pict', 'w:object',                         # VML / embedded object
        'm:oMath', 'm:oMathPara',                     # OMML equation
        '{urn:schemas-microsoft-com:vml}imagedata',   # VML image reference
    )

    @classmethod
    def docx_row_is_blank(cls, row) -> bool:
        """True when a table row holds neither text nor embedded content.

        Shared by the DOCX and PDF paths so the two cannot drift: 'no text'
        alone is not 'no content' - an image-on-top/caption-below grid puts its
        pictures in the header row, and deleting that row would drop them.
        """
        from docx.oxml.ns import qn

        if any(c.text.strip() for c in row.cells):
            return False
        tr = row._tr
        return not any(
            tr.findall('.//' + (tag if tag.startswith('{') else qn(tag)))
            for tag in cls.DOCX_CONTENT_ELEMENTS
        )

    def style_docx_table(self, table) -> None:
        """Style a content table, and drop its blank header row if it has one.

        Two jobs: the banded style plus 100% page width, and - because Markdown
        forces a header row that a borderless image/layout grid does not want -
        deleting that row when it is genuinely blank. The delete is structural,
        so it runs first; the PDF path applies the same rule separately in
        ``process_table`` because its intermediate DOCX skips this function.
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        table.style = 'Light List Accent 1'

        # A Markdown table needs a header row, so a borderless image/layout
        # grid is written with an empty one (`|  |  |  |`). The rendered
        # markdown shows nothing for it, so drop the row outright - left in, it
        # is a blank banded bar that Word repeats and strands above its image
        # rows.
        rows = table.rows
        first_row_empty = len(rows) >= 1 and self.docx_row_is_blank(rows[0])

        # Header CHROME is a separate question from whether the row is blank: a
        # picture-only first row is content and is kept, but it is a figure, not
        # a header, and banding or repeating it would be wrong. Read on the
        # ORIGINAL first row, so a body row left in position 0 by the delete is
        # not promoted into a header in its place. The PDF path decides the same
        # way (`has_header` reads text only), so both formats look alike.
        header_has_text = bool(rows) and any(
            c.text.strip() for c in rows[0].cells)

        if first_row_empty and len(rows) > 1:
            tr = rows[0]._tr
            tr.getparent().remove(tr)

        tblPr = table._tbl.tblPr
        # Disable first column emphasis, and first row emphasis for any table
        # whose first row is not a real (text-bearing) header
        tblLook = tblPr.find(qn('w:tblLook'))
        if tblLook is not None:
            tblLook.set(qn('w:firstColumn'), '0')
            if not header_has_text:
                tblLook.set(qn('w:firstRow'), '0')
        # Set table to 100% page width. Update in place, or insert at the slot
        # w:tblPr's schema sequence gives it - appending would put it after
        # w:tblLook, and a validating reader may then drop the width entirely
        tblW = tblPr.find(qn('w:tblW'))
        if tblW is None:
            tblW = OxmlElement('w:tblW')
            tblPr.insert_element_before(
                tblW, 'w:jc', 'w:tblCellSpacing', 'w:tblInd', 'w:tblBorders',
                'w:shd', 'w:tblLayout', 'w:tblCellMar', 'w:tblLook',
                'w:tblCaption', 'w:tblDescription', 'w:tblPrChange')
        tblW.set(qn('w:w'), '5000')
        tblW.set(qn('w:type'), 'pct')
        # Mark the first row as a repeating header: Word then repeats it at the
        # top of each page the table spans and does not strand it alone at a
        # page bottom. Only a table with a real (text-bearing) header row to
        # repeat qualifies - a blank or picture-only first row is not a header.
        if len(table.rows) > 1 and header_has_text:
            trPr = table.rows[0]._tr.get_or_add_trPr()
            if trPr.find(qn('w:tblHeader')) is None:
                trPr.append(OxmlElement('w:tblHeader'))

        # Keep each row whole across a page break, the DOCX counterpart of the
        # PDF's conditional `splitInRow`: without it Word breaks a row wherever
        # the page ends, stranding a caption on one page and its image on the
        # next when the whole row would have fitted the next page. A row taller
        # than a page still breaks - `w:cantSplit` is a request Word drops when
        # it cannot be met, and nothing here sets an exact `w:trHeight`, which
        # is what would make Word clip the overflow instead.
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            if trPr.find(qn('w:cantSplit')) is None:
                trPr.insert(0, OxmlElement('w:cantSplit'))

    def fit_docx_table_to_page(self, table, available_twips: int,
                               base_pt: float = None) -> None:
        """Pin an over-wide table to the page with proportional columns.

        Word's default autofit layout widens a table past the right margin when
        a cell holds an unbreakable token (a long URL, a code identifier). A
        fixed layout with an explicit grid keeps the table inside the margins
        and wraps the cell text instead. A table that already fits is left on
        autofit, where Word's own font metrics beat the estimate below.
        """
        from docx.oxml.ns import qn
        from docx.shared import Emu, Twips

        ncols = len(table.columns)
        if ncols == 0:
            return

        # Nominal width of one character of Calibri body text at the document's
        # base size - a stand-in for the measurement only Word itself can make.
        # 120 twips is the figure for the template's 11pt.
        base_pt = self.DOCX_TEMPLATE_BASE_PT if base_pt is None else base_pt
        char_twips = 120 * base_pt / self.DOCX_TEMPLATE_BASE_PT
        cell_margin_twips = self.DOCX_CELL_MARGIN_TWIPS

        # Row 0 is only bold when the table actually has a header. A borderless
        # grid whose blank header row was dropped upstream has plain body text
        # in row 0, and style_docx_table records that by clearing tblLook's
        # firstRow flag - widening it by the bold factor would over-allocate
        # that column at its neighbours' expense.
        tblPr = table._tbl.tblPr
        tblLook = tblPr.find(qn('w:tblLook')) if tblPr is not None else None
        header_is_bold = not (
            tblLook is not None and tblLook.get(qn('w:firstRow')) == '0'
        )

        def measure(text, row_index):
            # The header row carries the table style's bold face
            width = len(text) * char_twips
            bold = row_index == 0 and header_is_bold
            return (width * 1.08 if bold else width) + cell_margin_twips

        # Walk the grid once, by row: _Column.cells rebuilds the whole cell
        # list on every access, which turns this into O(rows x cols x cols)
        grid = [list(row.cells) for row in table.rows]
        table_data = [[cell.text for cell in row] for row in grid]

        def image_twips(cell):
            """Width the widest inline image in a cell asks for, 0 if none.

            measured_column_widths caps this at an equal share, so an oversized
            image - it is scaled to whatever column it lands in - cannot starve
            the text columns beside it.
            """
            widest = max((Emu(int(ext.get('cx') or 0)).twips
                          for ext in cell._tc.iter(qn('wp:extent'))), default=0)
            return widest + cell_margin_twips if widest else 0.0

        image_floors = [0.0] * ncols
        for row in grid:
            for index, cell in enumerate(row[:ncols]):
                image_floors[index] = max(image_floors[index], image_twips(cell))

        widths = self.measured_column_widths(
            table_data, float(available_twips), measure, image_floors)

        # Under the page width the estimate is not worth imposing - autofit
        # lays the table out with real metrics and it cannot overflow anyway.
        # The tolerance matters: a fitted result sums to `available` in float
        # arithmetic, which lands a hair under it often enough to matter
        if sum(widths) < available_twips - 1:
            return

        for col, width in zip(table.columns, widths):
            col.width = Twips(int(width))
        for row in grid:
            for index, cell in enumerate(row[:ncols]):
                cell.width = Twips(int(widths[index]))

        # autofit=False writes w:tblLayout type="fixed" in its schema-mandated
        # position; appending the element by hand puts it out of sequence.
        table.autofit = False

    def markdown_to_html(self, content: str, title: str = 'Exported Document',
                         compact: bool = False, math_support: bool = False,
                         theme: str = 'light',
                         dark_background: str = '#111111',
                         light_background: str = '#ffffff',
                         base_pt: float = None) -> str:
        """Convert markdown to standalone HTML.

        Args:
            content: Markdown content to convert
            title: Document title
            compact: If True, use tighter spacing (for PDF)
            math_support: If True, inject KaTeX CSS/JS for client-side math rendering
            theme: 'system' (auto-detect via prefers-color-scheme), 'light', or 'dark'
            dark_background: Background color for dark theme (hex)
            light_background: Background color for light theme (hex)
            base_pt: Base body text size in points; every other size in the
                stylesheet is expressed in `em`, so this scales the document
        """
        base_pt = self.DEFAULT_FONT_SIZE_PT if base_pt is None else base_pt
        import markdown

        # tab_length=2 supports 2-space nested lists (GitHub/CommonMark)
        base = ['tables', 'fenced_code', 'codehilite', 'toc']
        try:
            md = markdown.Markdown(
                extensions=base + [manual_break_aware_nl2br()], tab_length=2)
        except Exception:
            # The manual-break rule reads Markdown's internals to tell an
            # authored break from a generated one, and the wiring that touches
            # them runs HERE, inside the constructor - not in the factory
            # above. It is a cosmetic refinement either way, so any failure
            # falls back: one blank line too many beats a 500 on every export.
            md = markdown.Markdown(extensions=base + ['nl2br'], tab_length=2)
        body = md.convert(content)

        if compact:
            # PDF-optimized stylesheet with tighter spacing
            style = '''
        @page {
            size: A4;
            margin: 0.5in;
        }
        body {
            font-family: Calibri, "Noto Color Emoji", sans-serif;
            font-size: ''' + f'{base_pt:g}' + '''pt;
            line-height: 1.4;
            margin: 0;
            padding: 0;
            color: #333;
        }
        p {
            margin: 0.1em 0 0.4em 0;
        }
        pre {
            background: #f4f4f4;
            padding: 8px;
            margin: 0.5em 0;
            font-size: 9pt;
        }
        code {
            background: #f4f4f4;
            padding: 1px 3px;
            font-family: Courier, monospace;
            font-size: 9pt;
        }
        pre code {
            background: none;
            padding: 0;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 0.5em 0;
            font-size: 9pt;
            table-layout: fixed;
            word-wrap: break-word;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 3px 5px;
            text-align: left;
            overflow: hidden;
        }
        th {
            background: #dbe5f1;
            color: #365F91;
            font-weight: bold;
        }
        img {
            max-width: 100%;
            height: auto;
        }
        blockquote {
            border-left: 3px solid #4F81BD;
            margin: 0.5em 0;
            padding-left: 10px;
            color: #666;
        }
        h1, h2, h3, h4, h5, h6 {
            font-family: Calibri, "Noto Color Emoji", sans-serif;
        }
        h1 {
            font-size: 18pt;
            margin: 0.6em 0 0.15em 0;
            color: #365F91;
        }
        h2 {
            font-size: 14pt;
            margin: 0.5em 0 0.1em 0;
            color: #4F81BD;
        }
        h3 {
            font-size: 12pt;
            margin: 0.4em 0 0.1em 0;
            color: #4F81BD;
        }
        h4 {
            font-size: 11pt;
            margin: 0.3em 0 0.1em 0;
            color: #4F81BD;
        }
        h5, h6 {
            font-size: 11pt;
            margin: 0.3em 0 0.1em 0;
            color: #243F60;
        }
        ul, ol {
            margin: 0.3em 0;
            padding-left: 1.5em;
        }
        li {
            margin: 0.1em 0;
        }
        a {
            color: #0563C1;
            text-decoration: underline;
            text-underline-offset: 2px;
        }'''
        else:
            # Standard HTML stylesheet with Pygments syntax highlighting
            pygments_css = self.get_pygments_css()
            pygments_dark_css = self.get_pygments_css(dark=True)

            use_dark = theme == 'dark'
            use_light = theme == 'light'
            use_system = theme == 'system'

            def adjust_color(hex_color: str, amount: int) -> str:
                """Lighten (positive) or darken (negative) a hex color."""
                hex_color = hex_color.lstrip('#')
                r = max(0, min(255, int(hex_color[0:2], 16) + amount))
                g = max(0, min(255, int(hex_color[2:4], 16) + amount))
                b = max(0, min(255, int(hex_color[4:6], 16) + amount))
                return f'#{r:02x}{g:02x}{b:02x}'

            # Determine base styles based on theme
            if use_dark:
                # Dark theme as base (no media query)
                bg_color = dark_background
                text_color = '#e6edf3'
                link_color = '#58a6ff'
                code_bg = '#161b22'
                border_color = '#30363d'
                heading_color = '#e6edf3'
                blockquote_color = '#8b949e'
                th_bg = adjust_color(dark_background, 20)
                tr_stripe = adjust_color(dark_background, 14)
                tr_hover = adjust_color(dark_background, 22)
                code_bg = adjust_color(dark_background, 20)
                border_color = adjust_color(dark_background, 40)
                active_pygments = pygments_dark_css
            else:
                # Light theme as base (for both 'light' and 'system')
                bg_color = light_background
                text_color = '#1a1a1a'
                link_color = '#0969da'
                code_bg = adjust_color(light_background, -6)
                border_color = adjust_color(light_background, -46)
                heading_color = '#1a1a1a'
                blockquote_color = '#656d76'
                th_bg = adjust_color(light_background, -6)
                tr_stripe = adjust_color(light_background, -6)
                tr_hover = adjust_color(light_background, -14)
                active_pygments = pygments_css

            style = f'''
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: {base_pt:g}pt;
            line-height: 1.6;
            max-width: 50em;
            margin: 0 auto;
            padding: 20px;
            color: {text_color};
            background-color: {bg_color};
        }}
        a {{
            color: {link_color};
        }}
        pre {{
            background: {code_bg};
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.85em;
            border: 1px solid {border_color};
        }}
        code {{
            background: {code_bg};
            padding: 2px 6px;
            border-radius: 4px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            font-size: 0.85em;
        }}
        pre code {{
            background: none;
            padding: 0;
            border: none;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        .table-scroll {{
            /* Wrapping alone cannot shrink a table past one character per
               column, so a table with very many columns scrolls inside this
               box rather than pushing the document sideways. It has to be a
               wrapper: overflow-x on the table itself needs display:block,
               which makes the grid shrink-to-fit and voids its width */
            overflow-x: auto;
        }}
        @media print {{
            /* Paper cannot scroll, so a scroll box crops what it hides -
               fewer columns than the unwrapped table would have printed */
            .table-scroll {{
                overflow-x: visible;
            }}
            /* Keep a table header with a body row so it is never stranded
               alone at a page bottom, and repeat it on each page */
            thead {{
                display: table-header-group;
                break-inside: avoid;
                break-after: avoid;
            }}
            tr {{
                break-inside: avoid;
            }}
            /* Cap a tall image (a mermaid diagram) to one printed page so it
               is not split across pages. A Letter page less ~1in of margins
               is about 9in; vh units are unreliable in print and width:auto
               defeats the cap, so a concrete bound is used. The base
               max-width:100% and height:auto keep the width and aspect ratio. */
            img {{
                max-height: 9in;
            }}
        }}
        th, td {{
            border: 1px solid {border_color};
            padding: 8px;
            text-align: left;
            overflow-wrap: anywhere;
            /* anywhere, not break-word: only anywhere shrinks a column's
               min-content width, which is what keeps a table with a long
               unbreakable token inside the page */
        }}
        th {{
            background: {th_bg};
            font-weight: 600;
        }}
        tbody tr:nth-child(even) {{
            background: {tr_stripe};
        }}
        tbody tr:hover {{
            background: {tr_hover};
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        blockquote {{
            border-left: 4px solid {border_color};
            margin: 0;
            padding-left: 16px;
            color: {blockquote_color};
        }}
        h1, h2, h3, h4, h5, h6 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            color: {heading_color};
        }}
        h1 {{
            padding-bottom: 0.3em;
            border-bottom: 1px solid {border_color};
        }}
        hr {{
            border: none;
            border-top: 1px solid {border_color};
            margin: 1.5em 0;
        }}
        /* Pygments syntax highlighting */
        {active_pygments}'''

            # System theme: add dark overrides via media query
            # Derive dark UI colors from dark_background
            if use_system:
                dk_code = adjust_color(dark_background, 20)
                dk_border = adjust_color(dark_background, 40)
                dk_stripe = adjust_color(dark_background, 14)
                dk_hover = adjust_color(dark_background, 22)
                style += f'''
        @media (prefers-color-scheme: dark) {{
            body {{
                background-color: {dark_background};
                color: #e6edf3;
            }}
            a {{
                color: #58a6ff;
            }}
            pre {{
                background: {dk_code};
                border-color: {dk_border};
            }}
            code {{
                background: {dk_code};
            }}
            pre code {{
                background: none;
            }}
            th, td {{
                border-color: {dk_border};
            }}
            th {{
                background: {dk_code};
                color: #e6edf3;
            }}
            tbody tr:nth-child(even) {{
                background: {dk_stripe};
            }}
            tbody tr:hover {{
                background: {dk_hover};
            }}
            blockquote {{
                border-left-color: {dk_border};
                color: #8b949e;
            }}
            h1, h2, h3, h4, h5, h6 {{
                color: #e6edf3;
            }}
            h1 {{
                border-bottom-color: {dk_border};
            }}
            hr {{
                border-top-color: {dk_border};
            }}
            img {{
                opacity: 0.9;
            }}
            /* Pygments dark syntax highlighting */
            {pygments_dark_css}
        }}'''

        katex_head = ''
        katex_script = ''
        if math_support:
            katex_head = '''
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/katex.min.css">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/katex.min.js"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/contrib/auto-render.min.js"></script>'''
            katex_script = '''
    <script>
      document.addEventListener("DOMContentLoaded", function() {
        renderMathInElement(document.body, {
          delimiters: [
            {left: "$$", right: "$$", display: true},
            {left: "$", right: "$", display: false}
          ],
          ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
          throwOnError: false
        });
      });
    </script>'''

        # Force color-scheme on <html> element so embedded SVGs with
        # @media (prefers-color-scheme) follow the chosen theme
        if use_dark:
            html_style = ' style="color-scheme: dark"'
        elif use_light:
            html_style = ' style="color-scheme: light"'
        else:
            html_style = ' style="color-scheme: light dark"'

        html = f'''<!DOCTYPE html>
<html{html_style}>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>{style}
    </style>{katex_head}
</head>
<body>
{body}{katex_script}
</body>
</html>'''
        return html

    def _register_unicode_fonts(self):
        """Register Unicode-supporting fonts from system paths with font family support."""
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        # Define font sets with normal, bold, italic, bolditalic variants
        font_sets = [
            # DejaVu fonts (most common, excellent Unicode support)
            {
                'normal': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                'bold': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                'italic': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
                'boldItalic': '/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf',
            },
            # Liberation fonts (alternative)
            {
                'normal': '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                'bold': '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                'italic': '/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf',
                'boldItalic': '/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf',
            },
            # FreeSans (GNU FreeFont)
            {
                'normal': '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
                'bold': '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
                'italic': '/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf',
                'boldItalic': '/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf',
            },
        ]

        font_names = {
            'normal': 'UnicodeSans',
            'bold': 'UnicodeSansBold',
            'italic': 'UnicodeSansItalic',
            'boldItalic': 'UnicodeSansBoldItalic',
        }

        registered_fonts = set()

        # Try each font set until we find one with at least normal and bold
        for font_set in font_sets:
            if 'UnicodeSans' in registered_fonts:
                break

            if font_set['normal'] and os.path.exists(font_set['normal']):
                for variant, path in font_set.items():
                    if path and os.path.exists(path):
                        font_name = font_names[variant]
                        if font_name not in registered_fonts:
                            try:
                                pdfmetrics.registerFont(TTFont(font_name, path))
                                registered_fonts.add(font_name)
                            except Exception:
                                pass

        # Register font family to enable <b> and <i> tags in Paragraph
        if 'UnicodeSans' in registered_fonts:
            try:
                italic_font = 'UnicodeSansItalic' if 'UnicodeSansItalic' in registered_fonts else 'Helvetica-Oblique'
                bold_italic_font = 'UnicodeSansBoldItalic' if 'UnicodeSansBoldItalic' in registered_fonts else 'Helvetica-BoldOblique'

                registerFontFamily(
                    'UnicodeSans',
                    normal='UnicodeSans',
                    bold='UnicodeSansBold' if 'UnicodeSansBold' in registered_fonts else 'UnicodeSans',
                    italic=italic_font,
                    boldItalic=bold_italic_font
                )
            except Exception:
                pass

    def convert_docx_to_pdf(self, docx_bytes: bytes, code_blocks: list = None,
                            base_pt: float = None) -> bytes:
        """
        Convert DOCX document to PDF using python-docx + reportlab.

        Args:
            docx_bytes: DOCX file content as bytes
            code_blocks: Optional list of code blocks extracted from markdown

        Returns:
            PDF file content as bytes
        """
        if code_blocks is None:
            code_blocks = []
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab is required for PDF export")

        from docx import Document

        # Register Unicode fonts
        self._register_unicode_fonts()

        # Read the DOCX from bytes
        doc = Document(io.BytesIO(docx_bytes))

        # Determine which font to use
        font_name = 'UnicodeSans' if 'UnicodeSans' in pdfmetrics.getRegisteredFontNames() else 'Helvetica'
        font_name_bold = 'UnicodeSansBold' if 'UnicodeSansBold' in pdfmetrics.getRegisteredFontNames() else 'Helvetica-Bold'

        # Create PDF in memory
        pdf_buffer = io.BytesIO()
        pdf_doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=self.PDF_PAGE_MARGIN,
            leftMargin=self.PDF_PAGE_MARGIN,
            topMargin=self.PDF_PAGE_MARGIN,
            bottomMargin=self.PDF_PAGE_MARGIN
        )

        # Get default styles
        styles = getSampleStyleSheet()

        # Every size below is a proportion of the base body size, so the
        # document scales as one and matches what the DOCX renders at
        base_pt = self.DEFAULT_FONT_SIZE_PT if base_pt is None else base_pt
        body_type = self.pdf_type('body', base_pt)
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName=font_name,
            **body_type,
            spaceAfter=0.6 * base_pt
        )

        # Level-specific list styles for bullets
        list_bullet_style = ParagraphStyle(
            'CustomListBullet',
            parent=styles['Normal'],
            fontName=font_name,
            **body_type,
            spaceAfter=0.3 * base_pt,
            leftIndent=18,
            bulletIndent=6
        )

        list_bullet_2_style = ParagraphStyle(
            'CustomListBullet2',
            parent=styles['Normal'],
            fontName=font_name,
            **body_type,
            spaceAfter=0.3 * base_pt,
            leftIndent=36,
            bulletIndent=24
        )

        # Level-specific list styles for numbered lists
        list_number_style = ParagraphStyle(
            'CustomListNumber',
            parent=styles['Normal'],
            fontName=font_name,
            **body_type,
            spaceAfter=0.3 * base_pt,
            leftIndent=18,
            bulletIndent=6
        )

        list_number_2_style = ParagraphStyle(
            'CustomListNumber2',
            parent=styles['Normal'],
            fontName=font_name,
            **body_type,
            spaceAfter=0.3 * base_pt,
            leftIndent=36,
            bulletIndent=24
        )

        heading1_style = ParagraphStyle(
            'CustomHeading1',
            parent=styles['Heading1'],
            fontName=font_name_bold,
            **self.pdf_type('heading1', base_pt),
            spaceAfter=0.6 * base_pt,
            spaceBefore=1.0 * base_pt,
            textColor=colors.HexColor('#365F91')
        )

        heading2_style = ParagraphStyle(
            'CustomHeading2',
            parent=styles['Heading2'],
            fontName=font_name_bold,
            **self.pdf_type('heading2', base_pt),
            spaceAfter=0.4 * base_pt,
            spaceBefore=0.8 * base_pt,
            textColor=colors.HexColor('#4F81BD')
        )

        heading3_style = ParagraphStyle(
            'CustomHeading3',
            parent=styles['Heading3'],
            fontName=font_name_bold,
            **self.pdf_type('heading3', base_pt),
            spaceAfter=0.3 * base_pt,
            spaceBefore=0.6 * base_pt,
            textColor=colors.HexColor('#4F81BD')
        )

        # Callout body (blockquotes, alert boxes). Same size as body text but
        # no trailing space - the surrounding callout table supplies padding.
        callout_body_style = ParagraphStyle(
            'CustomCalloutBody',
            parent=normal_style,
            spaceAfter=0,
            spaceBefore=0,
        )

        # Table cells are Paragraphs so their text wraps inside the column
        table_cell_style = ParagraphStyle(
            'CustomTableCell',
            parent=styles['Normal'],
            fontName=font_name,
            **self.pdf_type('table', base_pt)
        )

        table_header_style = ParagraphStyle(
            'CustomTableHeader',
            parent=table_cell_style,
            fontName=font_name_bold,
            textColor=colors.HexColor('#365F91')
        )

        # Build the story (content) - iterate body elements in document order
        story = []

        from docx.text.paragraph import Paragraph as DocxParagraph
        from docx.table import Table as DocxTable
        from docx.oxml.ns import qn

        def get_list_info(para):
            """Get list type and level from paragraph style and indentation.

            Returns: (list_type, level) where list_type is 'number', 'bullet', or None
            """
            style_name = para.style.name if para.style else ''

            # Determine list type from style name
            list_type = None
            if 'List Number' in style_name:
                list_type = 'number'
            elif 'List Bullet' in style_name:
                list_type = 'bullet'
            elif 'List' in style_name:
                list_type = 'bullet'

            if list_type is None:
                # Check numPr for lists without explicit style
                try:
                    if para._element.pPr is not None and para._element.pPr.numPr is not None:
                        list_type = 'bullet'
                except AttributeError:
                    pass

            if list_type is None:
                return (None, 0)

            # Determine level from style name first (List Number 2, List Bullet 2)
            if '2' in style_name or '3' in style_name:
                level = 1
            else:
                # Check leftIndent for nesting level (720 = level 0, 1440+ = level 1+)
                level = 0
                try:
                    pPr = para._element.pPr
                    if pPr is not None:
                        ind = pPr.find(qn('w:ind'))
                        if ind is not None:
                            left_val = ind.get(qn('w:left'))
                            if left_val:
                                left_indent = int(left_val)
                                # 720 twips = level 0, 1440+ = level 1+
                                if left_indent > 720:
                                    level = 1
                except (AttributeError, ValueError):
                    pass

            return (list_type, level)

        # Track numbering for ordered lists
        number_counters = {0: 0, 1: 0, 2: 0}
        last_list_level = -1

        def is_horizontal_rule(para):
            """Check if paragraph represents a horizontal divider line."""
            try:
                pPr = para._element.pPr
                if pPr is not None:
                    pBdr = pPr.find(qn('w:pBdr'))
                    if pBdr is not None:
                        bottom = pBdr.find(qn('w:bottom'))
                        top = pBdr.find(qn('w:top'))
                        if bottom is not None or top is not None:
                            if not para.text.strip():
                                return True
            except (AttributeError, TypeError):
                pass
            return False

        def format_run(run):
            """Format a single run with all its styling."""
            run_text = run.text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            if not run_text:
                return run_text

            # Convert newlines to HTML line breaks
            run_text = run_text.replace('\n', '<br/>')
            result = run_text

            # Apply formatting tags (can be combined)
            if run.bold:
                result = f'<b>{result}</b>'
            if run.italic:
                result = f'<i>{result}</i>'
            if run.underline:
                result = f'<u>{result}</u>'
            if run.font.strike:
                result = f'<strike>{result}</strike>'
            if run.font.subscript:
                result = f'<sub>{result}</sub>'
            if run.font.superscript:
                result = f'<super>{result}</super>'

            # Check for text color
            try:
                if run.font.color and run.font.color.rgb:
                    color_hex = str(run.font.color.rgb)
                    if color_hex and color_hex != 'None' and len(color_hex) == 6:
                        result = f'<font color="#{color_hex}">{result}</font>'
            except (AttributeError, TypeError):
                pass

            return result

        def process_paragraph(para):
            """Process a single paragraph and return reportlab element(s)."""
            nonlocal last_list_level

            # Check for horizontal rule/divider first
            if is_horizontal_rule(para):
                from reportlab.platypus import HRFlowable
                return [HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceBefore=3, spaceAfter=6)]

            text = para.text.strip()
            if not text:
                # Empty paragraph - render as actual blank line (not invisible spacer)
                return Paragraph("&nbsp;", normal_style)

            # Check for code block placeholder [[CODE_BLOCK_N]]
            code_match = re.match(r'\[\[CODE_BLOCK_(\d+)\]\]', text)
            if code_match and code_blocks:
                idx = int(code_match.group(1))
                if idx < len(code_blocks):
                    block = code_blocks[idx]
                    return self.highlight_code_for_pdf(
                        block['code'], block['lang'], base_pt)
                return Paragraph("&nbsp;", normal_style)

            # Escape XML special characters for base text
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text = text.replace('\n', '<br/>')

            # Check if any run has formatting that needs processing
            has_formatting = False
            for run in para.runs:
                if run.text.strip():
                    if (run.bold or run.italic or run.underline or
                        run.font.strike or run.font.subscript or run.font.superscript):
                        has_formatting = True
                        break
                    try:
                        if run.font.color and run.font.color.rgb:
                            has_formatting = True
                            break
                    except (AttributeError, TypeError):
                        pass

            if has_formatting:
                formatted_parts = [format_run(run) for run in para.runs]
                text = ''.join(formatted_parts)

            # Detect heading styles
            style_name = para.style.name if para.style else ''
            if style_name.startswith('Heading 1'):
                last_list_level = -1
                return Paragraph(text, heading1_style)
            elif style_name.startswith('Heading 2'):
                last_list_level = -1
                return Paragraph(text, heading2_style)
            elif style_name.startswith('Heading 3') or style_name.startswith('Heading'):
                last_list_level = -1
                return Paragraph(text, heading3_style)

            # Blockquote: style_docx_blockquotes gave it a left border, shading
            # and indent that process_paragraph would otherwise drop. Render it
            # as a left-barred, shaded, indented callout so the PDF matches the
            # DOCX. The runs already carry the muted italic colour.
            bq = blockquote_info(para)
            if bq is not None:
                last_list_level = -1
                indent_pts, bar_hex, shd_hex = bq
                return make_callout(
                    [Paragraph(text, callout_body_style)],
                    bar_hex, shd_hex, left_pad=12 + max(0.0, indent_pts),
                    trailing=0.05,
                )

            # Check for list items
            list_type, level = get_list_info(para)

            if list_type == 'number':
                # Reset lower levels when moving up, increment current level
                if level <= last_list_level:
                    for l in range(level + 1, 3):
                        number_counters[l] = 0
                number_counters[level] += 1
                last_list_level = level

                prefix = f"{number_counters[level]}. "
                style = list_number_2_style if level > 0 else list_number_style
                return Paragraph(f'{prefix}{text}', style)

            elif list_type == 'bullet':
                last_list_level = level
                style = list_bullet_2_style if level > 0 else list_bullet_style
                return Paragraph(f'• {text}', style)

            else:
                # Reset counters when not in list
                last_list_level = -1
                for l in number_counters:
                    number_counters[l] = 0
                return Paragraph(text, normal_style)

        # Printable frame: the page area less the frame's own 6pt padding each
        # side. Sizing a flowable to pdf_doc.width/height instead would put its
        # edge past the page margin. One source for both tables and images.
        frame_width = pdf_doc.width - 2 * self.PDF_FRAME_PADDING
        frame_height = pdf_doc.height - 2 * self.PDF_FRAME_PADDING

        def make_callout(flowables, bar_hex, shd_hex, left_pad=12, trailing=0.12):
            """A full-width box with a coloured left bar and background shading.

            Shared by blockquotes and GitHub alert boxes. ``splitInRow`` lets a
            callout taller than a page carry over instead of raising
            LayoutError - but it is enabled only for such a callout. Left on,
            it also tears a box that merely runs past the space left on the
            current page, splitting a quote or alert mid-frame when the whole
            box would have fit the next page.
            """
            t = Table([[flowables]], colWidths=[frame_width],
                      hAlign='LEFT', splitInRow=1)
            t.setStyle(TableStyle([
                ('LINEBEFORE', (0, 0), (0, -1), 3, colors.HexColor('#' + bar_hex)),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#' + shd_hex)),
                ('LEFTPADDING', (0, 0), (-1, -1), left_pad),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            t.wrap(frame_width, frame_height)
            heights = getattr(t, '_rowHeights', None)
            if heights:
                t.splitInRow = 1 if max(heights) > frame_height else 0
            return [t, Spacer(1, trailing * inch)]

        def blockquote_info(para):
            """(indent_pts, bar_hex, shd_hex) if the paragraph is a styled
            blockquote (a left ``w:pBdr`` from style_docx_blockquotes), else None.
            Horizontal rules use a bottom/top border and empty text, already
            handled before this is reached."""
            pPr = para._element.pPr
            if pPr is None:
                return None
            pBdr = pPr.find(qn('w:pBdr'))
            if pBdr is None:
                return None
            left = pBdr.find(qn('w:left'))
            if left is None:
                return None
            bar = left.get(qn('w:color')) or 'BBBBBB'
            if bar in ('auto', ''):
                bar = 'BBBBBB'
            shd = pPr.find(qn('w:shd'))
            shd_fill = shd.get(qn('w:fill')) if shd is not None else None
            if not shd_fill or shd_fill == 'auto':
                shd_fill = 'F4F4F4'
            indent_pts = 0.0
            ind = pPr.find(qn('w:ind'))
            if ind is not None:
                lv = ind.get(qn('w:left'))
                if lv:
                    try:
                        indent_pts = int(lv) / 20.0
                    except ValueError:
                        pass
            return (indent_pts, bar, shd_fill)

        def alert_info(tbl):
            """(bar_hex, shd_hex) if the table is a GitHub alert box (a single
            1x1 cell with a coloured left border, the other sides none, from
            style_docx_alert_boxes), else None. The 1x1 shape is required so a
            normal multi-row/column table that happens to share the border
            signature is never routed to the single-cell callout (which would
            drop every other cell)."""
            if len(tbl.rows) != 1 or len(tbl.rows[0].cells) != 1:
                return None
            tblPr = tbl._tbl.find(qn('w:tblPr'))
            if tblPr is None:
                return None
            borders = tblPr.find(qn('w:tblBorders'))
            if borders is None:
                return None
            left = borders.find(qn('w:left'))
            if left is None or left.get(qn('w:val')) != 'single':
                return None
            bar = left.get(qn('w:color'))
            if not bar or bar in ('auto', '000000'):
                return None
            top = borders.find(qn('w:top'))
            if top is not None and top.get(qn('w:val')) not in ('none', None):
                return None
            shd_fill = 'FFFFFF'
            try:
                tcPr = tbl.rows[0].cells[0]._tc.find(qn('w:tcPr'))
                if tcPr is not None:
                    shd = tcPr.find(qn('w:shd'))
                    if shd is not None and shd.get(qn('w:fill')):
                        shd_fill = shd.get(qn('w:fill'))
            except (IndexError, AttributeError):
                pass
            return (bar, shd_fill)

        def process_alert(tbl, bar_hex, shd_hex):
            """Render an alert box as a coloured-left-bar shaded callout with
            normal (not table-header) text, preserving run formatting."""
            flow = []
            for p in tbl.rows[0].cells[0].paragraphs:
                markup = ''.join(format_run(run) for run in p.runs).strip()
                if markup:
                    flow.append(Paragraph(markup, callout_body_style))
            if not flow:
                flow = [Paragraph('&nbsp;', callout_body_style)]
            return make_callout(flow, bar_hex, shd_hex, left_pad=12)

        def process_table(tbl):
            """Process a single table and return reportlab elements."""
            # A GitHub alert box is a single-cell table with a coloured left
            # bar; render it as a callout rather than a header-styled table.
            alert = alert_info(tbl)
            if alert is not None:
                return process_alert(tbl, alert[0], alert[1])

            # Raw text, so the widths below are measured on what is rendered
            # rather than on the XML entities that stand in for it
            table_data = [[cell.text for cell in row.cells] for row in tbl.rows]

            if not table_data:
                return []

            # A borderless image/layout grid is written with an empty header row
            # (`|  |  |  |`) because Markdown requires a header. The rendered
            # markdown shows nothing for it, so drop it entirely rather than
            # emitting a blank bordered first row above the grid.
            rows = list(tbl.rows)
            dropped_empty_header = False

            if len(table_data) > 1 and self.docx_row_is_blank(rows[0]):
                table_data = table_data[1:]
                rows = rows[1:]
                dropped_empty_header = True

            # A Markdown layout grid carries an empty header row (`|  |  |  |`);
            # it must not be styled or repeated as a header, or a blank blue bar
            # detaches from its rows across a page break. Row 0 is a real header
            # only when it holds text - a picture-only row is a figure, and the
            # DOCX path reads it the same way. A grid whose empty header was
            # dropped has no header at all: the row now in position 0 is body
            # content and must not be promoted into one.
            has_header = (not dropped_empty_header
                          and any(text.strip() for text in table_data[0]))

            def cell_markup(text):
                markup = (text.replace('&', '&amp;')
                              .replace('<', '&lt;').replace('>', '&gt;'))
                # A Paragraph collapses newlines that a string cell honoured
                return markup.replace('\n', '<br/>')

            def string_width(text, row_index):
                # Only a real header row is drawn bold, so only it may be
                # measured bold - after the blank-header delete row 0 is
                # ordinary content, and widening it would over-allocate its
                # column at its neighbours' expense (the DOCX path carries the
                # same rule through tblLook)
                font = (font_name_bold if row_index == 0 and has_header
                        else font_name)
                return pdfmetrics.stringWidth(
                    text, font, table_cell_style.fontSize)

            # Per-column widest image (points): an image-only cell earns no
            # column width from its empty text, so without this floor its column
            # collapses and the cell image renders a few points wide. Mirrors the
            # DOCX path's image_floors; the extent cx is in EMU.
            from docx.shared import Emu
            ncols = max((len(r) for r in table_data), default=0)
            image_widths = [0.0] * ncols
            for row in rows:
                for c, cell in enumerate(row.cells):
                    if c >= ncols:
                        continue
                    widest = max((Emu(int(ext.get('cx') or 0)).pt
                                  for ext in cell._tc.iter(qn('wp:extent'))),
                                 default=0)
                    if widest:
                        image_widths[c] = max(image_widths[c], widest)

            side_padding, col_widths = self.pdf_table_column_layout(
                table_data, frame_width, string_width, image_widths)

            # A cell adds 4pt top + 4pt bottom padding around its content, and
            # the header row overrides its bottom padding to 8pt (12pt total).
            # An RLImage is atomic (never splits), so a cell image capped at the
            # full frame height plus that padding would exceed one page and
            # raise LayoutError. Cap below the frame by the largest per-row
            # padding (the 12pt header row) so no row - header included - can
            # overflow.
            cell_image_max_height = frame_height - 12

            def cell_content(cell, col_width, style):
                """Flowables for one cell: its text plus any inline images,
                scaled to the column so a cell image renders instead of being
                dropped. Walks the cell's paragraphs so text and images keep
                document order."""
                content_width = max(1.0, col_width - 2 * side_padding)
                flow = []
                for p in cell.paragraphs:
                    ptext = cell_markup(p.text)
                    if ptext.strip():
                        flow.append(Paragraph(ptext, style))
                    for drawing in p._p.findall('.//' + qn('w:drawing')):
                        img = process_image(drawing, doc, max_width=content_width,
                                            max_height=cell_image_max_height)
                        if img is not None:
                            flow.append(img)
                if not flow:
                    flow = [Paragraph(cell_markup(cell.text), style)]
                return flow

            # Paragraph/Image cells wrap and fit inside the column.
            wrapped = []
            for r, row in enumerate(rows):
                style = (table_header_style if (r == 0 and has_header)
                         else table_cell_style)
                wrapped.append([
                    cell_content(cell,
                                 col_widths[c] if c < len(col_widths) else frame_width,
                                 style)
                    for c, cell in enumerate(row.cells)
                ])

            # splitInRow lets a single row taller than the page carry over to
            # the next one - without it reportlab raises LayoutError and the
            # whole export fails, which wrapping made reachable. repeatRows=1
            # repeats a real header on each continuation page and, as a side
            # effect, defers the whole table to the next page rather than
            # stranding the header alone at a page bottom.
            t = Table(wrapped, colWidths=col_widths, hAlign='LEFT',
                      splitInRow=1, repeatRows=1 if has_header else 0)
            style = [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), side_padding),
                ('RIGHTPADDING', (0, 0), (-1, -1), side_padding),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ]
            if has_header:
                style.append(
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dbe5f1')))
                style.append(('BOTTOMPADDING', (0, 0), (-1, 0), 8))
            t.setStyle(TableStyle(style))
            # A repeated header re-emits on every continuation page, so each
            # body row must fit in the space it leaves (`frame_height -
            # header_h`). A text row splits fine under the header (splitInRow
            # carries the overflow) but cannot shrink below one line, and an
            # image is atomic and cannot shrink at all - either would raise
            # LayoutError if it can't fit under the repeated header. Drop the
            # repeat when the header leaves less than one body line (this also
            # covers a header taller than the whole frame), or when a body
            # row's tallest ATOMIC image can't fit. Keying off total row height
            # would needlessly drop the header for a tall *text* table.
            t.wrap(sum(col_widths), frame_height)
            if has_header and t._rowHeights:
                avail = frame_height - t._rowHeights[0]
                one_body_line = table_cell_style.leading + 8  # + cell padding

                def _atomic_floor(cells):
                    """Smallest height a row can shrink to when split: its
                    tallest atomic image plus cell padding, or 0 when the row
                    is all splittable text (bounded separately by one line)."""
                    tall = 0.0
                    for cell_flow in cells:
                        for f in cell_flow:
                            if isinstance(f, RLImage):
                                tall = max(tall, f.drawHeight)
                    return tall + 8 if tall else 0.0

                if avail < one_body_line or any(
                    _atomic_floor(r) > avail for r in wrapped[1:]
                ):
                    t.repeatRows = 0

            # Tear a row across pages ONLY when it cannot fit whole anywhere.
            # splitInRow is per-table, so leaving it on breaks any row that
            # merely runs past the space left on the current page - a cell's
            # caption stranded on one page and its image on the next - when
            # moving the whole row to the next page would have fit. The limit is
            # the space a row actually gets: a repeated header re-emits above
            # every continuation, so it comes off the top. Decided after the
            # repeat guard above so it sees the final repeatRows.
            row_heights = getattr(t, '_rowHeights', None)
            if row_heights:
                if t.repeatRows:
                    limit = frame_height - row_heights[0]
                    oversized = any(h > limit for h in row_heights[1:])
                else:
                    limit = frame_height
                    oversized = any(h > limit for h in row_heights)
                t.splitInRow = 1 if oversized else 0
            return [t, Spacer(1, 0.15 * inch)]

        def process_image(drawing_element, doc, max_width=None, max_height=None):
            """Extract image from drawing element and return reportlab Image.

            Scales to ``max_width`` then, if still too tall, ``max_height``,
            aspect preserved. Both default to the printable frame; a table cell
            passes its own column width so a cell image fits its column.
            """
            if max_width is None:
                max_width = frame_width
            if max_height is None:
                max_height = frame_height
            try:
                # Navigate to blip element containing image reference
                blip = drawing_element.find('.//' + qn('a:blip'))
                if blip is None:
                    return None

                # Get the relationship ID
                rId = blip.get(qn('r:embed'))
                if not rId:
                    return None

                # Get image data from document parts
                image_part = doc.part.related_parts.get(rId)
                if not image_part:
                    return None

                # Create reportlab Image from bytes
                img_buffer = io.BytesIO(image_part.blob)
                img = RLImage(img_buffer)

                # Scale to the width, then - if that leaves it taller than the
                # height - down to the height, aspect preserved. A tall mermaid
                # diagram at full width would otherwise run off the bottom.
                if max_width > 0 and img.drawWidth > max_width:
                    scale = max_width / img.drawWidth
                    img.drawWidth = max_width
                    img.drawHeight = img.drawHeight * scale
                if max_height > 0 and img.drawHeight > max_height:
                    scale = max_height / img.drawHeight
                    img.drawHeight = max_height
                    img.drawWidth = img.drawWidth * scale

                # Left-align image
                img.hAlign = 'LEFT'

                return img
            except Exception:
                return None

        def add_to_story(result):
            """Add paragraph result to story, handling lists or single elements."""
            if isinstance(result, list):
                story.extend(result)
            else:
                story.append(result)

        def build_blockquote_callout(paras, bq):
            """One callout for a run of consecutive blockquote paragraphs, so a
            multi-paragraph quote renders as a single shaded box with an
            unbroken left bar rather than a stack of separate boxes (Word
            merges them the same way in the DOCX)."""
            indent_pts, bar_hex, shd_hex = bq
            flow = []
            for p in paras:
                markup = ''.join(format_run(run) for run in p.runs).strip()
                flow.append(Paragraph(markup or '&nbsp;', callout_body_style))
            return make_callout(flow, bar_hex, shd_hex,
                                left_pad=12 + max(0.0, indent_pts), trailing=0.12)

        # Iterate through body elements in document order
        body_elements = list(doc.element.body)
        i = 0
        while i < len(body_elements):
            element = body_elements[i]
            if element.tag == qn('w:p'):  # Paragraph
                para = DocxParagraph(element, doc)
                drawings = element.findall('.//' + qn('w:drawing'))

                # Group consecutive blockquote paragraphs (without images) into
                # a single callout.
                bq = blockquote_info(para) if not drawings else None
                if bq is not None:
                    group = [para]
                    j = i + 1
                    while (j < len(body_elements)
                           and body_elements[j].tag == qn('w:p')
                           and not body_elements[j].findall('.//' + qn('w:drawing'))):
                        nxt = DocxParagraph(body_elements[j], doc)
                        if blockquote_info(nxt) is None:
                            break
                        group.append(nxt)
                        j += 1
                    last_list_level = -1
                    for _l in number_counters:
                        number_counters[_l] = 0
                    add_to_story(build_blockquote_callout(group, bq))
                    i = j
                    continue

                if drawings:
                    # Process paragraph text first (if any)
                    if para.text.strip():
                        add_to_story(process_paragraph(para))
                    # Then add images
                    for drawing in drawings:
                        img = process_image(drawing, doc)
                        if img:
                            story.append(img)
                            story.append(Spacer(1, 0.1 * inch))
                else:
                    add_to_story(process_paragraph(para))
            elif element.tag == qn('w:tbl'):  # Table
                tbl = DocxTable(element, doc)
                story.extend(process_table(tbl))
            i += 1

        # Build the PDF
        if not story:
            story.append(Paragraph("Document appears to be empty.", normal_style))

        pdf_doc.build(story)

        # Get the PDF bytes
        pdf_bytes = pdf_buffer.getvalue()
        pdf_buffer.close()

        return pdf_bytes


class ExportPdfHandler(ExportHandlerBase):
    """Handler for exporting markdown to PDF via DOCX intermediate."""

    @tornado.web.authenticated
    async def post(self):
        try:
            data = json.loads(self.request.body)
            relative_path = data.get('path')
            mermaid_diagrams = data.get('mermaidDiagrams', [])
            svg_pixel_width = data.get("svgPixelWidth", 1920)
            show_alert_labels = data.get('showAlertLabels', False)
            base_pt = self.font_size_pt(data.get('exportFontSize'))
            math_pixel_width = data.get('mathPixelWidth', 800)
            # DOCX/PDF SVG + Mermaid rasterization theme. Defaults to light
            # (Word docs are usually printed). 'auto' is resolved by the
            # frontend to a concrete light/dark before the request.
            docx_theme = data.get('docxTheme', data.get('htmlTheme', 'light'))
            svg_color_scheme = 'dark' if docx_theme == 'dark' else 'light'

            if not relative_path:
                self.set_status(400)
                self.finish(json.dumps({'error': 'No path provided'}))
                return

            file_path = self.get_absolute_path(relative_path)

            if not file_path.exists():
                self.set_status(404)
                self.finish(json.dumps({'error': 'File not found'}))
                return

            content = self.read_markdown_file(file_path)
            content = self.preprocess_task_lists(content)
            content = self.preprocess_github_alerts(content, show_labels=show_alert_labels)
            content = self.replace_math_with_images(content, width=math_pixel_width)
            content = self.replace_mermaid_with_images(content, mermaid_diagrams, use_png=True)
            content = self.embed_images_as_base64(content, file_path.parent)

            # Extract code blocks for PDF rendering (before DOCX conversion)
            content, code_blocks = self.extract_code_blocks(content)

            html = self.markdown_to_html(content, file_path.stem,
                                         base_pt=base_pt)

            # Step 1: Create DOCX in memory (same logic as DOCX export)
            from htmldocx import HtmlToDocx
            from docx import Document
            from docx.shared import Inches

            body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL)
            body_html = body_match.group(1) if body_match else html

            # Fix loose-list bullets and tag blockquotes before htmldocx
            body_html = self.restructure_html_for_docx(body_html)
            body_html = self.inject_anchor_markers(body_html)

            with tempfile.TemporaryDirectory() as temp_dir:
                body_html = await self.extract_data_uri_images(
                    body_html, temp_dir,
                    convert_svg=True,
                    svg_pixel_width=svg_pixel_width,
                    color_scheme=svg_color_scheme,
                )

                document = Document()

                for section in document.sections:
                    section.top_margin = Inches(0.5)
                    section.bottom_margin = Inches(0.5)
                    section.left_margin = Inches(0.5)
                    section.right_margin = Inches(0.5)

                parser = HtmlToDocx()
                parser.add_html_to_document(body_html, document)

                self.apply_anchor_bookmarks(document)
                self.strip_monospace_from_unicode_runs(document)
                # Style and de-marker blockquotes (also strips the marker so it
                # never leaks into the PDF text rebuild below)
                self.style_docx_blockquotes(document)
                # Apply true run shading to coloured pills (background spans)
                self.style_docx_color_runs(document)

                # Style GitHub alert boxes with colored borders and shading
                self.style_docx_alert_boxes(document, show_labels=show_alert_labels)

                # No table styling or fitting here: this DOCX is only an
                # intermediate for convert_docx_to_pdf, which reads cell text
                # and applies its own style and column widths

                while document.paragraphs and not document.paragraphs[0].text.strip():
                    p_elem = document.paragraphs[0]._element
                    # Keep paragraphs that contain images (drawings or VML)
                    from docx.oxml.ns import qn as _qn
                    has_image = bool(
                        p_elem.findall('.//' + _qn('w:drawing')) or
                        p_elem.findall('.//{urn:schemas-microsoft-com:vml}imagedata')
                    )
                    if has_image:
                        break
                    p_elem.getparent().remove(p_elem)

                # Remove empty paragraphs before images
                self.remove_empty_paragraphs_before_images(document)

                docx_buffer = io.BytesIO()
                document.save(docx_buffer)
                docx_bytes = docx_buffer.getvalue()

            # Step 2: Convert DOCX to PDF using reportlab (with code blocks)
            pdf_content = self.convert_docx_to_pdf(docx_bytes, code_blocks,
                                                   base_pt=base_pt)

            self.set_header('Content-Type', 'application/pdf')
            self.set_header('Content-Disposition',
                          f'attachment; filename="{file_path.stem}.pdf"')
            self.finish(pdf_content)

        except ChromiumUnavailableError as e:
            self.set_status(503)
            self.finish(json.dumps({
                'error': str(e),
                'errorCode': 'CHROMIUM_UNAVAILABLE',
                'message': (
                    'Chromium is required to render embedded SVG images. '
                    'Run: jupyterlab-export-markdown-extension install'
                ),
            }))
        except ImportError as e:
            self.set_status(500)
            self.finish(json.dumps({
                'error': f'Missing dependency: {e}. Install with: pip install reportlab python-docx htmldocx markdown'
            }))
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({'error': str(e)}))


class ExportDocxHandler(ExportHandlerBase):
    """Handler for exporting markdown to DOCX."""

    @tornado.web.authenticated
    async def post(self):
        try:
            data = json.loads(self.request.body)
            relative_path = data.get('path')
            mermaid_diagrams = data.get('mermaidDiagrams', [])
            svg_pixel_width = data.get("svgPixelWidth", 1920)
            show_alert_labels = data.get('showAlertLabels', False)
            base_pt = self.font_size_pt(data.get('exportFontSize'))
            # DOCX/PDF SVG + Mermaid rasterization theme. Defaults to light
            # (Word docs are usually printed). 'auto' is resolved by the
            # frontend to a concrete light/dark before the request.
            docx_theme = data.get('docxTheme', data.get('htmlTheme', 'light'))
            svg_color_scheme = 'dark' if docx_theme == 'dark' else 'light'

            if not relative_path:
                self.set_status(400)
                self.finish(json.dumps({'error': 'No path provided'}))
                return

            file_path = self.get_absolute_path(relative_path)

            if not file_path.exists():
                self.set_status(404)
                self.finish(json.dumps({'error': 'File not found'}))
                return

            content = self.read_markdown_file(file_path)
            content = self.preprocess_task_lists(content)
            content = self.preprocess_github_alerts(content, show_labels=show_alert_labels)
            # Use OMML markers for DOCX (native Word equations)
            content, inline_math, display_math = self.replace_math_with_markers(content)
            # Use PNG for DOCX (better Word compatibility)
            content = self.replace_mermaid_with_images(content, mermaid_diagrams, use_png=True)
            content = self.embed_images_as_base64(content, file_path.parent)
            # Highlight code blocks with inline styles for DOCX
            content = self.highlight_code_blocks(content, use_inline_styles=True)
            html = self.markdown_to_html(content, file_path.stem,
                                         base_pt=base_pt)

            from htmldocx import HtmlToDocx
            from docx import Document
            from docx.shared import Emu, Inches, Twips

            # Extract just the body content for DOCX conversion
            body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL)
            body_html = body_match.group(1) if body_match else html

            # Fix loose-list bullets and tag blockquotes before htmldocx
            body_html = self.restructure_html_for_docx(body_html)

            # Inject bookmark sentinels for every id="..." anchor so Word
            # internal links (#anchor) resolve after htmldocx strips them.
            body_html = self.inject_anchor_markers(body_html)

            # Use temp directory for images (htmldocx can't handle data URIs)
            with tempfile.TemporaryDirectory() as temp_dir:
                body_html = await self.extract_data_uri_images(
                    body_html, temp_dir,
                    convert_svg=True,
                    svg_pixel_width=svg_pixel_width,
                    color_scheme=svg_color_scheme,
                )

                document = Document()

                # Set document margins (0.5 inch)
                for section in document.sections:
                    section.top_margin = Inches(0.5)
                    section.bottom_margin = Inches(0.5)
                    section.left_margin = Inches(0.5)
                    section.right_margin = Inches(0.5)

                parser = HtmlToDocx()
                parser.add_html_to_document(body_html, document)

                # Insert native OMML equations replacing markers
                self.merge_inline_math_omml(document, inline_math, display_math)

                # Convert anchor markers to bookmarks and rewrite hash-prefix
                # hyperlinks from external to internal links.
                self.apply_anchor_bookmarks(document)

                # Drop Courier font from runs with unicode chars so arrows and
                # symbols render in the body font instead of failing glyph lookup.
                self.strip_monospace_from_unicode_runs(document)

                # Style blockquotes (left bar, indent, shading) and strip marker
                self.style_docx_blockquotes(document)
                # Apply true run shading to coloured pills (background spans)
                self.style_docx_color_runs(document)

                # Style GitHub alert boxes with colored borders and shading
                alert_tables = self.style_docx_alert_boxes(
                    document, show_labels=show_alert_labels)

                # Draw task-list checkbox glyphs in MS Gothic (Word's checkbox font)
                self.style_docx_task_checkboxes(document)

                # Style tables: banded rows (pale blue), no first column emphasis
                # Usable page area - one source for both the table grid below
                # and the image scaling further down
                section = document.sections[0]
                page_width = Emu(section.page_width - section.left_margin
                                 - section.right_margin)
                page_height = Emu(section.page_height - section.top_margin
                                  - section.bottom_margin)
                self.apply_docx_font_size(document, base_pt)
                for table in document.tables:
                    if table._tbl in alert_tables:
                        continue
                    self.style_docx_table(table)
                    self.fit_docx_table_to_page(table, page_width.twips, base_pt)

                # Remove empty paragraphs at the beginning
                while document.paragraphs and not document.paragraphs[0].text.strip():
                    p_elem = document.paragraphs[0]._element
                    # Keep paragraphs that contain images (drawings or VML)
                    from docx.oxml.ns import qn as _qn
                    has_image = bool(
                        p_elem.findall('.//' + _qn('w:drawing')) or
                        p_elem.findall('.//{urn:schemas-microsoft-com:vml}imagedata')
                    )
                    if has_image:
                        break
                    p_elem.getparent().remove(p_elem)

                # Remove empty paragraphs before images
                self.remove_empty_paragraphs_before_images(document)

                from docx.oxml.ns import qn as _qn

                def container_width(inline_el):
                    """Usable width for an inline shape - its table cell width
                    if nested in a table, otherwise the full page width.

                    Images in a multi-column table cell must be scaled to the
                    cell, not the page; a page-width image overflows its cell
                    and Word clips it at the cell boundary.
                    """
                    node = inline_el.getparent()
                    tc = None
                    while node is not None:
                        if node.tag == _qn('w:tc'):
                            tc = node
                            break
                        node = node.getparent()
                    if tc is None:
                        return page_width
                    tbl = tc.getparent()
                    while tbl is not None and tbl.tag != _qn('w:tbl'):
                        tbl = tbl.getparent()
                    cell_width = None
                    if tbl is not None:
                        grid = tbl.find(_qn('w:tblGrid'))
                        cols = grid.findall(_qn('w:gridCol')) if grid is not None else []
                        # Only a fitted table's grid states the real column
                        # widths. Elsewhere (the alert boxes, whose single
                        # gridCol is decorative next to their 100% tblW) the
                        # grid is fiction, so fall back to an equal share.
                        tbl_pr = tbl.find(_qn('w:tblPr'))
                        fitted = (tbl_pr is not None
                                  and tbl_pr.find(_qn('w:tblLayout')) is not None)
                        row = tc.getparent()
                        index = list(row.findall(_qn('w:tc'))).index(tc)
                        if fitted and index < len(cols):
                            # A fitted grid width is an outer width, so the
                            # allowance due is exactly the cell margin baked
                            # into it. No lower bound here: the column really
                            # is that narrow, and an image wider than its cell
                            # would push the fixed grid past the margin
                            outer = int(cols[index].get(_qn('w:w')) or 0)
                            return Twips(max(
                                1, outer - self.DOCX_CELL_MARGIN_TWIPS))
                        elif cols:
                            cell_width = int(page_width / len(cols))
                    if cell_width is None:
                        cell_width = page_width
                    # Per-cell content width, less the cell margin allowance
                    return max(Inches(0.5),
                               cell_width - Twips(self.DOCX_CELL_MARGIN_TWIPS))

                # Process images: scale every image down to fit its container
                # (page width, or table cell width when nested in a table).
                for shape in document.inline_shapes:
                    orig_width = shape.width
                    orig_height = shape.height
                    max_width = container_width(shape._inline)

                    ratio = 1.0
                    if orig_width > max_width:
                        ratio = min(ratio, max_width / orig_width)
                    if orig_height > page_height:
                        ratio = min(ratio, page_height / orig_height)

                    if ratio < 1.0:
                        # A column no wider than its own cell margin scales the
                        # image to a fraction of an EMU; truncating either side
                        # to zero writes a degenerate wp:extent
                        shape.width = max(1, int(orig_width * ratio))
                        shape.height = max(1, int(orig_height * ratio))

                docx_buffer = io.BytesIO()
                document.save(docx_buffer)
                docx_content = docx_buffer.getvalue()

            self.set_header('Content-Type',
                          'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            self.set_header('Content-Disposition',
                          f'attachment; filename="{file_path.stem}.docx"')
            self.finish(docx_content)

        except ChromiumUnavailableError as e:
            self.set_status(503)
            self.finish(json.dumps({
                'error': str(e),
                'errorCode': 'CHROMIUM_UNAVAILABLE',
                'message': (
                    'Chromium is required to render embedded SVG images. '
                    'Run: jupyterlab-export-markdown-extension install'
                ),
            }))
        except ImportError as e:
            self.set_status(500)
            self.finish(json.dumps({
                'error': f'Missing dependency: {e}. Install with: pip install python-docx htmldocx markdown'
            }))
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({'error': str(e)}))


class ExportHtmlHandler(ExportHandlerBase):
    """Handler for exporting markdown to HTML."""

    @tornado.web.authenticated
    async def post(self):
        try:
            data = json.loads(self.request.body)
            relative_path = data.get('path')
            mermaid_diagrams = data.get('mermaidDiagrams', [])
            show_alert_labels = data.get('showAlertLabels', False)
            base_pt = self.font_size_pt(data.get('exportFontSize'))
            html_theme = data.get('htmlTheme', 'light')
            dark_background = data.get('htmlDarkBackground', '#111111')
            light_background = data.get('htmlLightBackground', '#ffffff')

            if not relative_path:
                self.set_status(400)
                self.finish(json.dumps({'error': 'No path provided'}))
                return

            file_path = self.get_absolute_path(relative_path)

            if not file_path.exists():
                self.set_status(404)
                self.finish(json.dumps({'error': 'File not found'}))
                return

            content = self.read_markdown_file(file_path)
            content = self.preprocess_task_lists(content)
            content = self.preprocess_github_alerts(content, show_labels=show_alert_labels)
            content = self.replace_mermaid_with_images(content, mermaid_diagrams)
            content = self.embed_images_as_base64(content, file_path.parent)
            html = self.markdown_to_html(
                content, file_path.stem, math_support=True,
                theme=html_theme,
                dark_background=dark_background,
                light_background=light_background,
                base_pt=base_pt
            )

            # Style GitHub alert boxes with colored borders and shading
            html = self.style_html_alert_boxes(html, show_labels=show_alert_labels)
            html = self.drop_empty_table_headers(html)
            html = self.wrap_html_tables(html)

            self.set_header('Content-Type', 'text/html; charset=utf-8')
            self.set_header('Content-Disposition',
                          f'attachment; filename="{file_path.stem}.html"')
            self.finish(html.encode('utf-8'))

        except ImportError as e:
            self.set_status(500)
            self.finish(json.dumps({
                'error': f'Missing dependency: {e}. Install with: pip install markdown'
            }))
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({'error': str(e)}))


def setup_route_handlers(web_app):
    """Register all route handlers for the extension."""
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    namespace = "jupyterlab-export-markdown-extension"

    handlers = [
        (url_path_join(base_url, namespace, "export/pdf"), ExportPdfHandler),
        (url_path_join(base_url, namespace, "export/docx"), ExportDocxHandler),
        (url_path_join(base_url, namespace, "export/html"), ExportHtmlHandler),
    ]

    web_app.add_handlers(host_pattern, handlers)
