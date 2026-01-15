"""
Route handlers for the markdown export extension.

Provides API endpoints for exporting markdown files to PDF, DOCX, and HTML formats
using pure Python libraries (no system dependencies).
"""

import json
import os
import base64
import re
import io
import tempfile
from pathlib import Path
from urllib.parse import unquote

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


class ExportHandlerBase(APIHandler):
    """Base class for export handlers with common functionality."""

    def get_absolute_path(self, relative_path: str) -> Path:
        """Convert a relative path to an absolute path within the server root."""
        root_dir = self.contents_manager.root_dir
        return Path(root_dir) / relative_path

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

                if use_png:
                    # Prefer PNG from frontend (client-side Canvas conversion)
                    if png_data_uri:
                        return f'![Mermaid Diagram]({png_data_uri})'
                    # Fallback to server-side conversion
                    try:
                        converted_png = self.svg_to_png(svg_data_uri)
                        return f'![Mermaid Diagram]({converted_png})'
                    except Exception:
                        # Last resort: use SVG
                        return f'![Mermaid Diagram]({svg_data_uri})'
                else:
                    return f'![Mermaid Diagram]({svg_data_uri})'

            # No pre-rendered diagram available, keep original
            return match.group(0)

        return re.sub(mermaid_pattern, replace_mermaid, content, flags=re.DOTALL)

    def svg_to_png(self, svg_data_uri: str) -> str:
        """
        Convert SVG data URI to PNG data URI using cairosvg.

        Args:
            svg_data_uri: SVG as base64 data URI

        Returns:
            PNG as base64 data URI
        """
        import cairosvg

        # Extract base64 data from URI
        if svg_data_uri.startswith('data:image/svg+xml;base64,'):
            svg_base64 = svg_data_uri.replace('data:image/svg+xml;base64,', '')
            svg_bytes = base64.b64decode(svg_base64)
        else:
            raise ValueError('Invalid SVG data URI format')

        # Convert SVG to PNG
        png_bytes = cairosvg.svg2png(bytestring=svg_bytes)

        # Encode as base64 data URI
        png_base64 = base64.b64encode(png_bytes).decode('utf-8')
        return f'data:image/png;base64,{png_base64}'

    def extract_data_uri_images(self, html: str, temp_dir: str) -> str:
        """
        Extract data URI images to temp files for htmldocx compatibility.

        Args:
            html: HTML content with data URI images
            temp_dir: Directory to store temp image files

        Returns:
            HTML with data URIs replaced by file paths
        """
        img_pattern = r'<img\s+[^>]*src=["\']data:image/([^;]+);base64,([^"\']+)["\'][^>]*>'

        def replace_img(match):
            img_type = match.group(1)
            base64_data = match.group(2)

            # Determine file extension
            ext_map = {
                'png': '.png',
                'jpeg': '.jpg',
                'jpg': '.jpg',
                'gif': '.gif',
                'svg+xml': '.svg'
            }
            ext = ext_map.get(img_type, '.png')

            # Decode and save to temp file
            try:
                img_bytes = base64.b64decode(base64_data)
                # Create unique filename
                import hashlib
                hash_id = hashlib.md5(img_bytes).hexdigest()[:8]
                filename = f'img_{hash_id}{ext}'
                filepath = os.path.join(temp_dir, filename)

                with open(filepath, 'wb') as f:
                    f.write(img_bytes)

                return f'<img src="{filepath}">'
            except Exception:
                return match.group(0)

        return re.sub(img_pattern, replace_img, html)

    def embed_images_as_base64(self, content: str, markdown_dir: Path) -> str:
        """
        Replace local image references with base64-encoded data URIs.

        This ensures images are embedded in the output document.
        """
        img_pattern = r'!\[([^\]]*)\]\(([^)"\s]+)(?:\s+"[^"]*")?\)'

        def replace_image(match):
            alt_text = match.group(1)
            img_path = match.group(2)

            if img_path.startswith(('http://', 'https://', 'data:')):
                return match.group(0)

            # URL-decode the path (handles %20 for spaces, etc.)
            img_path_decoded = unquote(img_path)
            full_path = (markdown_dir / img_path_decoded).resolve()

            if not full_path.exists():
                return match.group(0)

            try:
                with open(full_path, 'rb') as img_file:
                    img_data = base64.b64encode(img_file.read()).decode('utf-8')

                ext = full_path.suffix.lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.svg': 'image/svg+xml',
                    '.webp': 'image/webp'
                }
                mime_type = mime_types.get(ext, 'application/octet-stream')

                return f'![{alt_text}](data:{mime_type};base64,{img_data})'
            except Exception:
                return match.group(0)

        return re.sub(img_pattern, replace_image, content)

    def get_pygments_css(self) -> str:
        """Get Pygments CSS for syntax highlighting."""
        try:
            from pygments.formatters import HtmlFormatter
            return HtmlFormatter(style='default').get_style_defs('.codehilite')
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

    def highlight_code_for_pdf(self, code: str, lang: str) -> list:
        """Highlight code for PDF using Pygments and return reportlab flowables.

        Returns list of reportlab flowables (Preformatted paragraphs)
        """
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
                    fontSize=8,
                    leading=10,
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
            fontSize=8,
            leading=10,
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

    def preprocess_github_alerts(self, content: str) -> str:
        """Convert GitHub-style alerts to HTML divs.

        Supports: NOTE, TIP, IMPORTANT, WARNING, CAUTION
        """
        alert_pattern = r'> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\n((?:> .*\n?)*)'

        def replace_alert(match):
            alert_type = match.group(1).lower()
            # Remove '> ' prefix from each line and join
            alert_lines = match.group(2).strip().split('\n')
            alert_content = ' '.join(line.lstrip('> ').strip() for line in alert_lines if line.strip())

            # Map alert types to colors
            color_map = {
                'note': '#0969da',      # Blue
                'tip': '#1a7f37',       # Green
                'important': '#8250df', # Purple
                'warning': '#9a6700',   # Yellow/Orange
                'caution': '#cf222e'    # Red
            }
            color = color_map.get(alert_type, '#0969da')

            return f'**{alert_type.upper()}:** {alert_content}\n\n'

        return re.sub(alert_pattern, replace_alert, content)

    def markdown_to_html(self, content: str, title: str = 'Exported Document',
                         compact: bool = False) -> str:
        """Convert markdown to standalone HTML.

        Args:
            content: Markdown content to convert
            title: Document title
            compact: If True, use tighter spacing (for PDF)
        """
        import markdown

        md = markdown.Markdown(extensions=[
            'tables',
            'fenced_code',
            'codehilite',
            'toc',
            'nl2br'
        ])
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
            font-size: 11pt;
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
            style = f'''
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }}
        pre {{
            background: #f8f8f8;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85em;
        }}
        code {{
            background: #f8f8f8;
            padding: 2px 4px;
            border-radius: 2px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            font-size: 0.85em;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background: #f4f4f4;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
        blockquote {{
            border-left: 4px solid #ddd;
            margin: 0;
            padding-left: 16px;
            color: #666;
        }}
        h1, h2, h3, h4, h5, h6 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
        }}
        /* Pygments syntax highlighting */
        {pygments_css}'''

        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>{style}
    </style>
</head>
<body>
{body}
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

    def convert_docx_to_pdf(self, docx_bytes: bytes, code_blocks: list = None) -> bytes:
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
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        # Get default styles
        styles = getSampleStyleSheet()

        # Create custom styles (sizes matched to DOCX rendering)
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=12,
            spaceAfter=6
        )

        # Level-specific list styles for bullets
        list_bullet_style = ParagraphStyle(
            'CustomListBullet',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=12,
            spaceAfter=3,
            leftIndent=18,
            bulletIndent=6
        )

        list_bullet_2_style = ParagraphStyle(
            'CustomListBullet2',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=12,
            spaceAfter=3,
            leftIndent=36,
            bulletIndent=24
        )

        # Level-specific list styles for numbered lists
        list_number_style = ParagraphStyle(
            'CustomListNumber',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=12,
            spaceAfter=3,
            leftIndent=18,
            bulletIndent=6
        )

        list_number_2_style = ParagraphStyle(
            'CustomListNumber2',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=12,
            spaceAfter=3,
            leftIndent=36,
            bulletIndent=24
        )

        heading1_style = ParagraphStyle(
            'CustomHeading1',
            parent=styles['Heading1'],
            fontName=font_name_bold,
            fontSize=14,
            leading=18,
            spaceAfter=6,
            spaceBefore=10,
            textColor=colors.HexColor('#365F91')
        )

        heading2_style = ParagraphStyle(
            'CustomHeading2',
            parent=styles['Heading2'],
            fontName=font_name_bold,
            fontSize=12,
            leading=15,
            spaceAfter=4,
            spaceBefore=8,
            textColor=colors.HexColor('#4F81BD')
        )

        heading3_style = ParagraphStyle(
            'CustomHeading3',
            parent=styles['Heading3'],
            fontName=font_name_bold,
            fontSize=11,
            leading=14,
            spaceAfter=3,
            spaceBefore=6,
            textColor=colors.HexColor('#4F81BD')
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
                    return self.highlight_code_for_pdf(block['code'], block['lang'])
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

        def process_table(tbl):
            """Process a single table and return reportlab elements."""
            table_data = []
            for row in tbl.rows:
                row_data = []
                for cell in row.cells:
                    cell_text = cell.text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    row_data.append(cell_text)
                table_data.append(row_data)

            if not table_data:
                return []

            t = Table(table_data, hAlign='LEFT')
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dbe5f1')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#365F91')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), font_name_bold),
                ('FONTNAME', (0, 1), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc'))
            ]))
            return [t, Spacer(1, 0.15 * inch)]

        def process_image(drawing_element, doc):
            """Extract image from drawing element and return reportlab Image."""
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

                # Scale image to fit page width (max 7 inches)
                max_width = 7 * inch
                if img.drawWidth > max_width:
                    scale = max_width / img.drawWidth
                    img.drawWidth = max_width
                    img.drawHeight = img.drawHeight * scale

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

        # Iterate through body elements in document order
        for element in doc.element.body:
            if element.tag == qn('w:p'):  # Paragraph
                para = DocxParagraph(element, doc)

                # Check for drawings (images) in paragraph
                drawings = element.findall('.//' + qn('w:drawing'))
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
            content = self.preprocess_github_alerts(content)
            content = self.replace_mermaid_with_images(content, mermaid_diagrams, use_png=True)
            content = self.embed_images_as_base64(content, file_path.parent)

            # Extract code blocks for PDF rendering (before DOCX conversion)
            content, code_blocks = self.extract_code_blocks(content)

            html = self.markdown_to_html(content, file_path.stem)

            # Step 1: Create DOCX in memory (same logic as DOCX export)
            from htmldocx import HtmlToDocx
            from docx import Document
            from docx.shared import Inches

            body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL)
            body_html = body_match.group(1) if body_match else html

            with tempfile.TemporaryDirectory() as temp_dir:
                body_html = self.extract_data_uri_images(body_html, temp_dir)

                document = Document()

                for section in document.sections:
                    section.top_margin = Inches(0.5)
                    section.bottom_margin = Inches(0.5)
                    section.left_margin = Inches(0.5)
                    section.right_margin = Inches(0.5)

                parser = HtmlToDocx()
                parser.add_html_to_document(body_html, document)

                for table in document.tables:
                    table.style = 'Light List Accent 1'
                    tblPr = table._tbl.tblPr
                    if tblPr is not None:
                        from docx.oxml.ns import qn
                        tblLook = tblPr.find(qn('w:tblLook'))
                        if tblLook is not None:
                            tblLook.set(qn('w:firstColumn'), '0')

                while document.paragraphs and not document.paragraphs[0].text.strip():
                    p = document.paragraphs[0]._element
                    p.getparent().remove(p)

                docx_buffer = io.BytesIO()
                document.save(docx_buffer)
                docx_bytes = docx_buffer.getvalue()

            # Step 2: Convert DOCX to PDF using reportlab (with code blocks)
            pdf_content = self.convert_docx_to_pdf(docx_bytes, code_blocks)

            self.set_header('Content-Type', 'application/pdf')
            self.set_header('Content-Disposition',
                          f'attachment; filename="{file_path.stem}.pdf"')
            self.finish(pdf_content)

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
            content = self.preprocess_github_alerts(content)
            # Use PNG for DOCX (better Word compatibility)
            content = self.replace_mermaid_with_images(content, mermaid_diagrams, use_png=True)
            content = self.embed_images_as_base64(content, file_path.parent)
            # Highlight code blocks with inline styles for DOCX
            content = self.highlight_code_blocks(content, use_inline_styles=True)
            html = self.markdown_to_html(content, file_path.stem)

            from htmldocx import HtmlToDocx
            from docx import Document
            from docx.shared import Inches

            # Extract just the body content for DOCX conversion
            body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL)
            body_html = body_match.group(1) if body_match else html

            # Use temp directory for images (htmldocx can't handle data URIs)
            with tempfile.TemporaryDirectory() as temp_dir:
                body_html = self.extract_data_uri_images(body_html, temp_dir)

                document = Document()

                # Set document margins (0.5 inch)
                for section in document.sections:
                    section.top_margin = Inches(0.5)
                    section.bottom_margin = Inches(0.5)
                    section.left_margin = Inches(0.5)
                    section.right_margin = Inches(0.5)

                parser = HtmlToDocx()
                parser.add_html_to_document(body_html, document)

                # Style tables: banded rows (pale blue), no first column emphasis
                for table in document.tables:
                    table.style = 'Light List Accent 1'
                    # Disable first column emphasis via XML properties
                    tblPr = table._tbl.tblPr
                    if tblPr is not None:
                        from docx.oxml.ns import qn
                        tblLook = tblPr.find(qn('w:tblLook'))
                        if tblLook is not None:
                            tblLook.set(qn('w:firstColumn'), '0')

                # Remove empty paragraphs at the beginning
                while document.paragraphs and not document.paragraphs[0].text.strip():
                    p = document.paragraphs[0]._element
                    p.getparent().remove(p)

                # Page dimensions (Letter/A4 width minus margins)
                page_width = Inches(8.5) - Inches(1.0)  # 7.5 inches usable
                page_height = Inches(11) - Inches(1.0)  # 10 inches usable

                # Process images: preserve small ones, fit large ones to page
                for shape in document.inline_shapes:
                    orig_width = shape.width
                    orig_height = shape.height

                    # Only resize if larger than page dimensions
                    needs_resize = False
                    ratio = 1.0

                    if orig_width > page_width:
                        ratio = min(ratio, page_width / orig_width)
                        needs_resize = True

                    if orig_height > page_height:
                        ratio = min(ratio, page_height / orig_height)
                        needs_resize = True

                    if needs_resize:
                        shape.width = int(orig_width * ratio)
                        shape.height = int(orig_height * ratio)

                docx_buffer = io.BytesIO()
                document.save(docx_buffer)
                docx_content = docx_buffer.getvalue()

            self.set_header('Content-Type',
                          'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            self.set_header('Content-Disposition',
                          f'attachment; filename="{file_path.stem}.docx"')
            self.finish(docx_content)

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
            content = self.preprocess_github_alerts(content)
            content = self.replace_mermaid_with_images(content, mermaid_diagrams)
            content = self.embed_images_as_base64(content, file_path.parent)
            html = self.markdown_to_html(content, file_path.stem)

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
