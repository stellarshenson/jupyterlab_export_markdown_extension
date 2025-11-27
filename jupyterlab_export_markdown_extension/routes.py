"""
Route handlers for the markdown export extension.

Provides API endpoints for exporting markdown files to PDF, DOCX, and HTML formats
using pure Python libraries (no system dependencies).
"""

import json
import os
import tempfile
import base64
import re
import io
from pathlib import Path

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
import tornado.web


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

            full_path = (markdown_dir / img_path).resolve()

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

    def markdown_to_html(self, content: str, title: str = 'Exported Document') -> str:
        """Convert markdown to standalone HTML."""
        import markdown

        md = markdown.Markdown(extensions=[
            'tables',
            'fenced_code',
            'codehilite',
            'toc',
            'nl2br'
        ])
        body = md.convert(content)

        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }}
        pre {{
            background: #f4f4f4;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 4px;
            border-radius: 2px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
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
    </style>
</head>
<body>
{body}
</body>
</html>'''
        return html


class ExportPdfHandler(ExportHandlerBase):
    """Handler for exporting markdown to PDF."""

    @tornado.web.authenticated
    async def post(self):
        try:
            data = json.loads(self.request.body)
            relative_path = data.get('path')

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

            from fpdf import FPDF

            pdf = FPDF(orientation='P', unit='mm', format='A4')
            pdf.set_margins(15, 15, 15)
            pdf.set_auto_page_break(auto=True, margin=15)

            # Add Unicode font (DejaVu) for proper character support
            font_dir = '/usr/share/fonts/truetype/dejavu'
            font_name = 'Helvetica'
            if os.path.exists(f'{font_dir}/DejaVuSans.ttf'):
                pdf.add_font('DejaVu', '', f'{font_dir}/DejaVuSans.ttf')
                pdf.add_font('DejaVu', 'B', f'{font_dir}/DejaVuSans-Bold.ttf')
                pdf.add_font('DejaVu', 'I', f'{font_dir}/DejaVuSans-Oblique.ttf')
                pdf.add_font('DejaVu', 'BI', f'{font_dir}/DejaVuSans-BoldOblique.ttf')
                font_name = 'DejaVu'

            pdf.add_page()
            pdf.set_font(font_name, size=11)

            # Calculate effective width (page width minus margins)
            effective_width = pdf.w - pdf.l_margin - pdf.r_margin

            # Render markdown with basic formatting
            for line in content.split('\n'):
                # Reset X position to left margin for each line
                pdf.set_x(pdf.l_margin)

                if line.startswith('# '):
                    pdf.set_font(font_name, 'B', 18)
                    pdf.multi_cell(effective_width, 10, line[2:])
                    pdf.ln(2)
                elif line.startswith('## '):
                    pdf.set_font(font_name, 'B', 15)
                    pdf.multi_cell(effective_width, 8, line[3:])
                    pdf.ln(2)
                elif line.startswith('### '):
                    pdf.set_font(font_name, 'B', 13)
                    pdf.multi_cell(effective_width, 7, line[4:])
                    pdf.ln(1)
                elif line.startswith('#### '):
                    pdf.set_font(font_name, 'B', 11)
                    pdf.multi_cell(effective_width, 6, line[5:])
                    pdf.ln(1)
                elif line.startswith('- ') or line.startswith('* '):
                    pdf.set_font(font_name, size=11)
                    pdf.multi_cell(effective_width, 6, f'  • {line[2:]}')
                elif line.strip() == '':
                    pdf.ln(3)
                else:
                    pdf.set_font(font_name, size=11)
                    pdf.multi_cell(effective_width, 6, line)

            pdf_content = pdf.output()

            self.set_header('Content-Type', 'application/pdf')
            self.set_header('Content-Disposition',
                          f'attachment; filename="{file_path.stem}.pdf"')
            self.finish(pdf_content)

        except ImportError as e:
            self.set_status(500)
            self.finish(json.dumps({
                'error': f'Missing dependency: {e}. Install with: pip install fpdf2 markdown'
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
            content = self.embed_images_as_base64(content, file_path.parent)
            html = self.markdown_to_html(content, file_path.stem)

            from htmldocx import HtmlToDocx
            from docx import Document
            from docx.shared import Inches

            # Extract just the body content for DOCX conversion
            body_match = re.search(r'<body>(.*?)</body>', html, re.DOTALL)
            body_html = body_match.group(1) if body_match else html

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
