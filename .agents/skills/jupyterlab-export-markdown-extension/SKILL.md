---
name: jupyterlab-export-markdown-extension
description: Converts Markdown to PDF, DOCX and HTML with the JupyterLab Markdown export pipeline, through the `jupyterlab-export-markdown-extension` CLI of jupyterlab_export_markdown_extension. Use when converting or exporting a .md file to Word, PDF or HTML, reproducing a JupyterLab menu export outside the lab, checking the Chromium it renders diagrams in, or "export this markdown to docx".
---

# jupyterlab-export-markdown-extension

CLI of the JupyterLab Markdown export extension. `convert` runs the extension's own export endpoints in a private server inside the command - no JupyterLab needed, same pipeline as the menu export. Commands, flags, output, errors: `jupyterlab-export-markdown-extension --help`, `jupyterlab-export-markdown-extension <command> --help`. Read first.

## Rules

- `--root` = folder holding the file and all its images (repository or workspace root), not the file's folder
- Target file exists: may be hand-edited. Ask user before overwrite, or `-o` to a new name
- Exit 0 with `warning:` on stderr = degraded document (diagram kept its source, image not embedded). Tell user
- Ask user before `install`: 270 MB download, sudo apt-get, may stop for a password
- Many diagrams = minutes per format. Run in background, log to file
