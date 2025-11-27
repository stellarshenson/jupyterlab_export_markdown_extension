# jupyterlab_export_markdown_extension

[![GitHub Actions](https://github.com/stellarshenson/jupyterlab_export_markdown_extension/actions/workflows/build.yml/badge.svg)](https://github.com/stellarshenson/jupyterlab_export_markdown_extension/actions/workflows/build.yml)
[![npm version](https://img.shields.io/npm/v/jupyterlab_export_markdown_extension.svg)](https://www.npmjs.com/package/jupyterlab_export_markdown_extension)
[![PyPI version](https://img.shields.io/pypi/v/jupyterlab-export-markdown-extension.svg)](https://pypi.org/project/jupyterlab-export-markdown-extension/)
[![Total PyPI downloads](https://static.pepy.tech/badge/jupyterlab-export-markdown-extension)](https://pepy.tech/project/jupyterlab-export-markdown-extension)
[![JupyterLab 4](https://img.shields.io/badge/JupyterLab-4-orange.svg)](https://jupyterlab.readthedocs.io/en/stable/)
[![Brought To You By KOLOMOLO](https://img.shields.io/badge/Brought%20To%20You%20By-KOLOMOLO-00ffff?style=flat)](https://kolomolo.com)

Export markdown files to PDF, DOCX and HTML with embedded images directly from JupyterLab.

## Features

- **Export to PDF** - Convert markdown to publication-ready PDF documents
- **Export to DOCX** - Generate Microsoft Word documents from markdown
- **Export to HTML** - Create standalone HTML files with embedded images
- **Embedded images** - Images are automatically embedded in exported documents
- **Server-side conversion** - Uses pandoc for reliable document conversion

## Requirements

- JupyterLab >= 4.0.0
- Pandoc (system package)
- For PDF export: XeLaTeX with DejaVu fonts

### Installing Pandoc

**Ubuntu/Debian:**
```bash
sudo apt-get install pandoc
```

**macOS:**
```bash
brew install pandoc
```

**Windows:**
```bash
choco install pandoc
```

### Installing XeLaTeX for PDF Export

**Ubuntu/Debian:**
```bash
sudo apt-get install texlive-xetex texlive-fonts-recommended fonts-dejavu
```

**macOS:**
```bash
brew install --cask mactex
```

## Install

```bash
pip install jupyterlab_export_markdown_extension
```

## Uninstall

```bash
pip uninstall jupyterlab_export_markdown_extension
```
