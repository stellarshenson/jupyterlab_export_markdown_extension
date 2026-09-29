"""Command line for jupyterlab_export_markdown_extension.

`convert` exports a Markdown file through the extension's own export
endpoints, served by a private in-process Jupyter server, so a file converts
as the JupyterLab menu converts it - with no JupyterLab running:

    jupyterlab-export-markdown-extension convert doc.md --to pdf docx html

The DOCX/PDF export pipeline rasterises embedded SVG images through
Playwright Chromium so CSS, web fonts, filters and `prefers-color-scheme`
match a real browser. Chromium needs (a) the binary itself (~270 MB,
downloaded once into ~/.cache/ms-playwright) and (b) a handful of
shared system libraries (libnspr4, libnss3, ...). `install` and `check`
handle both:

    jupyterlab-export-markdown-extension install   # do it
    jupyterlab-export-markdown-extension check     # verify only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from .routes import API_NAMESPACE, CHROMIUM_INSTALL_COMMAND, ExportHandlerBase

PROG = "jupyterlab-export-markdown-extension"

#: One export endpoint per format, `<base_url>/<API_NAMESPACE>/export/<format>`.
FORMATS: tuple[str, ...] = ("pdf", "docx", "html")

# System libs required by Chromium on Debian/Ubuntu. Mirrors the list
# emitted by `playwright install-deps chromium`. Distro package names
# differ across Ubuntu generations; we pick the broadly-compatible set.
APT_PACKAGES: tuple[str, ...] = (
    "libnspr4", "libnss3", "libasound2t64", "libatk1.0-0t64",
    "libatk-bridge2.0-0t64", "libatspi2.0-0t64", "libcups2t64",
    "libdrm2", "libgbm1", "libxcomposite1", "libxdamage1",
    "libxfixes3", "libxkbcommon0", "libxrandr2",
    "libpango-1.0-0", "libcairo2", "libfontconfig1", "libfreetype6",
    "libdbus-1-3", "fonts-liberation",
)


def _have_sudo() -> bool:
    return shutil.which("sudo") is not None


def _print_manual_apt_command() -> None:
    libs = " ".join(APT_PACKAGES)
    print(
        "\nUnable to install system libraries automatically.\n"
        "Run this command yourself (root or sudo):\n\n"
        f"    apt-get install -y --no-install-recommends {libs}\n",
        file=sys.stderr,
    )


def _install_chromium_binary() -> int:
    """Run `playwright install chromium` to fetch the browser binary."""
    print("Installing Chromium browser binary via Playwright...")
    return subprocess.call(
        [sys.executable, "-m", "playwright", "install", "chromium"]
    )


def _try_launch_chromium() -> tuple[bool, str]:
    """Try a one-shot Chromium launch; report success or stderr message."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return False, f"playwright not installed: {e}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True, "Chromium launches successfully"
    except Exception as e:
        return False, str(e)


def _install_apt_packages() -> int:
    """Install system libs via apt-get; uses sudo if not already root."""
    if shutil.which("apt-get") is None:
        print(
            "apt-get not found - this auto-installer only handles Debian/Ubuntu.",
            file=sys.stderr,
        )
        _print_manual_apt_command()
        return 1

    cmd = ["apt-get", "install", "-y", "--no-install-recommends", *APT_PACKAGES]
    if os.geteuid() != 0:
        if not _have_sudo():
            print(
                "Not running as root and `sudo` is not on PATH.",
                file=sys.stderr,
            )
            _print_manual_apt_command()
            return 1
        cmd = ["sudo", *cmd]

    print(f"Installing Chromium system libraries: {' '.join(APT_PACKAGES)}")
    rc = subprocess.call(cmd)
    if rc != 0:
        print(
            f"\napt-get exited with code {rc}.",
            file=sys.stderr,
        )
        _print_manual_apt_command()
    return rc


def cmd_install(_args: argparse.Namespace) -> int:
    """`install` subcommand entry point."""
    rc = _install_chromium_binary()
    if rc != 0:
        print(
            f"\n`playwright install chromium` exited with code {rc}.",
            file=sys.stderr,
        )
        return rc

    ok, msg = _try_launch_chromium()
    if ok:
        print(f"\n{msg}")
        return 0

    print(f"\nChromium present but failed to launch:\n  {msg}")
    print("Attempting to install missing system libraries...\n")

    rc = _install_apt_packages()
    if rc != 0:
        return rc

    ok, msg = _try_launch_chromium()
    if ok:
        print(f"\n{msg}")
        return 0

    print(f"\nChromium still cannot launch after installing libs:\n  {msg}", file=sys.stderr)
    return 1


def cmd_check(_args: argparse.Namespace) -> int:
    """`check` subcommand entry point - verify, no install."""
    ok, msg = _try_launch_chromium()
    if ok:
        print(msg)
        return 0
    # The remedy first: Playwright's own message advises `playwright install`,
    # which fetches every browser and none of the system libraries
    print(f"FAIL: Chromium cannot launch. Fix with:  {CHROMIUM_INSTALL_COMMAND}\n\n"
          f"{msg}", file=sys.stderr)
    return 1


def _error_text(response) -> str:
    """The reason a failed export gives, from its JSON body.

    The export handlers answer `{error, message?}`, and `message`, when
    present, is the remedy, written for the reader; the raw `error` under it
    is library text (Playwright's own advice among it). jupyter_server's own
    refusals (403, 404) answer `{message, reason}`.
    """
    try:
        payload = json.loads(response.body)
    except ValueError:
        return str(response.error)
    return payload.get("message") or payload.get("error") or str(response.error)


def _warning_text(warning: dict) -> str:
    """One `X-Export-Warnings` entry as a line. Diagram positions are
    zero-based in the header and counted from 1 here, as a reader counts the
    mermaid blocks in the file."""
    if "images" in warning:
        where = "images: " + ", ".join(warning["images"])
        listed = len(warning["images"])
    else:
        where = "mermaid blocks " + ", ".join(
            str(i + 1) for i in warning["diagrams"])
        listed = len(warning["diagrams"])
    if warning["count"] > listed:
        where += f", {warning['count']} in all"
    return f"{warning['message']} ({where})"


async def _export(root: Path, path: str, jobs: list[tuple[str, Path]],
                  options: dict) -> int:
    """POST `path` to each format's endpoint and write what comes back.

    The server is a private ServerApp in this process: bound to 127.0.0.1 on
    a free port, authenticated by a token that never leaves the process, with
    only this extension loaded. It is never started through `start_app`, so
    it writes no server info file and `jupyter server list` never sees it.
    """
    from jupyter_server.serverapp import ServerApp
    from jupyter_server.utils import url_path_join
    from tornado.httpclient import AsyncHTTPClient, HTTPClientError
    from tornado.httpserver import HTTPServer
    from tornado.netutil import bind_sockets

    token = secrets.token_hex(16)
    app = ServerApp()
    # The user's own Jupyter config is not read: a contents root set there
    # made the handlers export another file of the same name, and a log level
    # or a preferred dir there printed server logs or failed the start
    app.load_config_file = lambda *args, **kwargs: None
    # Only this extension - any other would add startup time and nothing the
    # export uses
    app.jpserver_extensions = {"jupyterlab_export_markdown_extension": True}
    # ServerApp's own SIGINT handler asks "Shut down this Jupyter server?" on
    # the terminal; Ctrl-C keeps the default cmd_convert set
    app.init_signal = lambda: None
    app.initialize(
        argv=[
            f"--ServerApp.root_dir={root}",
            f"--IdentityProvider.token={token}",
            # the handlers log what they also return, and a failed export
            # would print its request headers on top of the error line
            "--ServerApp.log_level=CRITICAL",
        ],
        find_extensions=False,
        new_httpserver=False,
    )
    sockets = bind_sockets(0, "127.0.0.1")
    server = HTTPServer(app.web_app)
    server.add_sockets(sockets)
    port = sockets[0].getsockname()[1]
    # The server holds each whole document in memory already; the client's
    # own 100 MB default refused an HTML export carrying 75 MB of images
    client = AsyncHTTPClient(max_body_size=4 << 30)

    rc = 0
    try:
        for fmt, output in jobs:
            try:
                response = await client.fetch(
                    f"http://127.0.0.1:{port}"
                    + url_path_join(app.base_url, API_NAMESPACE, "export", fmt),
                    method="POST",
                    body=json.dumps({"path": path, **options}),
                    headers={"Authorization": f"token {token}"},
                    raise_error=False,
                    # 0 is no limit: every Mermaid diagram and SVG image is a
                    # Chromium render, and a long document runs for minutes
                    request_timeout=0,
                )
            except (HTTPClientError, OSError) as e:
                # raise_error=False covers an HTTP error status only; a
                # connection that failed or closed early still raises
                print(f"error: {fmt}: {e}", file=sys.stderr)
                rc = 1
                continue
            for warning in json.loads(
                    response.headers.get("X-Export-Warnings", "[]")):
                print(f"warning: {fmt}: {_warning_text(warning)}",
                      file=sys.stderr)
            if response.code != 200:
                print(f"error: {fmt}: {_error_text(response)}", file=sys.stderr)
                rc = 1
                continue
            try:
                output.write_bytes(response.body)
            except OSError as e:
                print(f"error: {fmt}: cannot write {output}: {e.strerror}",
                      file=sys.stderr)
                rc = 1
                continue
            # flush: a caller logging stdout to a file sees each path as it
            # lands, not all of them at exit
            print(output, flush=True)
    finally:
        server.stop()
    return rc


def _in_real_folder(path: str) -> Path:
    """The path with its folder resolved and its own name kept.

    The folder is resolved because the current directory arrives resolved
    while a typed path keeps its links, and the two must compare. The name is
    kept because the server joins root and path without resolving links, so
    a FILE that is itself a link exports as the lab exports it - images from
    the link's folder, output beside the link.
    """
    path = os.path.expanduser(path)
    return Path(os.path.realpath(os.path.dirname(path) or ".")) / os.path.basename(path)


def cmd_convert(args: argparse.Namespace) -> int:
    """`convert` subcommand entry point."""
    source = _in_real_folder(args.file)
    root = Path(os.path.realpath(os.path.expanduser(args.root)))
    if not source.is_file():
        state = "is a folder" if source.is_dir() else "does not exist"
        print(f"error: FILE {args.file} {state}; pass the Markdown file to "
              "convert", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"error: --root {args.root} is not a folder; pass the folder "
              "that holds FILE and its images", file=sys.stderr)
        return 2
    if not source.is_relative_to(root):
        print(
            f"error: {source} is outside the root {root}. Pass --root with a "
            "folder that holds the file and the images it links to",
            file=sys.stderr,
        )
        return 2

    formats = list(dict.fromkeys(args.to))  # `--to pdf pdf` exports once
    if args.output:
        if len(formats) > 1:
            print("error: -o/--output takes a single --to format; drop -o to "
                  "write each format beside the source", file=sys.stderr)
            return 2
        outputs = [_in_real_folder(args.output)]
    else:
        outputs = [source.with_suffix(f".{fmt}") for fmt in formats]
    for output in outputs:
        # samefile, not ==: a link, a hard link or a case-insensitive file
        # system can name the source under another path
        if output.exists() and output.samefile(source):
            print(f"error: {output} is the source file; pass -o PATH",
                  file=sys.stderr)
            return 2
        if output.is_dir():
            print(f"error: {output} is a folder; -o takes a file path",
                  file=sys.stderr)
            return 2
        if not output.parent.is_dir():
            print(f"error: folder {output.parent} does not exist; create it "
                  "or pass -o PATH", file=sys.stderr)
            return 2

    # Only what was asked for: an absent key takes the handler's own default,
    # so the defaults live in one place. htmlTheme alone: the DOCX and PDF
    # handlers read it when no docxTheme is sent
    options = {"htmlTheme": args.theme, "exportFontSize": args.font_size}
    options = {k: v for k, v in options.items() if v is not None}
    if args.alert_labels:
        options["showAlertLabels"] = True

    # Ctrl-C ends the command at once. Under asyncio.run's own handler it
    # cancelled the export and then waited, without end, for the handler's
    # Chromium render to finish cancelling. Only over Python's own handler -
    # the rule asyncio uses: a job started with SIGINT ignored keeps it ignored
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    return asyncio.run(_export(root, source.relative_to(root).as_posix(),
                               list(zip(formats, outputs)), options))


FONT_SIZES = ExportHandlerBase.EXPORT_FONT_SIZES
DEFAULT_FONT_SIZE = next(name for name, pt in FONT_SIZES.items()
                         if pt == ExportHandlerBase.DEFAULT_FONT_SIZE_PT)

CONVERT_DESCRIPTION = """\
Convert one Markdown file to PDF, DOCX and/or HTML through the extension's own
export endpoints - the ones the JupyterLab menu calls - so the result matches a
UI export made with default settings. Mermaid diagrams are the one difference:
the menu renders them in the browser, this command in the server's bundled
Mermaid. No JupyterLab needs to run: the command starts a private Jupyter
server of its own. It does not read your Jupyter config.

stdout: each written path, one per line, nothing else.
stderr: warnings, e.g. a Mermaid diagram that kept its source or an image that
was not embedded; they do not fail the command. Errors, one line per failed
format.

Existing output files are overwritten without asking.

Images: relative paths resolve from the file's folder, but only inside --root,
the same boundary the server root is in JupyterLab. http(s) images are
downloaded from public hosts. An image that is not embedded - outside --root,
missing, or a failed download - keeps its path in HTML and is a text
placeholder in PDF and DOCX; a warning names it. Image syntax inside code is
left as written. Reference-style images (![alt][id]) are never embedded.

Chromium: SVG images and Mermaid diagrams render in Playwright Chromium. Without
it a PDF or DOCX of a file holding an SVG image fails, and Mermaid diagrams keep
their source. Test with `check`, fix with `install`.

Duration: about 2 s to start the server, then the export. Each diagram and SVG
image is a Chromium render, so a long PDF or DOCX runs for minutes, with no
output until each file is written; no timeout is applied.
"""

CONVERT_EPILOG = f"""\
examples:
  # PDF beside the source; images read from inside the current directory
  {PROG} convert docs/report.md --to pdf

  # three formats from one server start, rooted at the repository
  {PROG} convert ~/repo/docs/report.md --to pdf docx html --root ~/repo

  # one format to a chosen path, dark diagrams, small type
  {PROG} convert notes.md --to docx -o /tmp/notes.docx --theme dark --font-size small
"""

MAIN_EPILOG = f"""\
environment:
  PLAYWRIGHT_BROWSERS_PATH  where Playwright keeps Chromium
                            (default ~/.cache/ms-playwright)

exit codes:
  0  success
  1  a step failed, the reason is on stderr; `install` may also exit with
     the code of the playwright or apt-get step that failed
  2  the arguments cannot work (a missing FILE, a FILE outside --root, an
     -o PATH that is a folder, ...), the reason is on stderr

examples:
  {PROG} convert report.md --to pdf docx html
  {PROG} check
  {PROG} convert --help
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Convert Markdown to PDF, DOCX and HTML with the export pipeline "
            "of jupyterlab_export_markdown_extension, and install or check "
            "the Playwright Chromium that pipeline renders SVG images and "
            "Mermaid diagrams in."
        ),
        epilog=MAIN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser(
        "convert",
        help="Convert a Markdown file to pdf, docx and/or html.",
        # FILE first: after `--to pdf` argparse reads the next word as another
        # format, so the order argparse would print fails
        usage="%(prog)s FILE --to FORMAT [FORMAT ...] [options]",
        description=CONVERT_DESCRIPTION,
        epilog=CONVERT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_convert.add_argument("file", metavar="FILE",
                           help="Markdown file to convert.")
    p_convert.add_argument(
        "--to", nargs="+", action="extend", required=True, choices=FORMATS,
        metavar="FORMAT",
        help="One or more of: pdf, docx, html; may be repeated. Put FILE "
             "before --to, or the file name is read as a format.",
    )
    p_convert.add_argument(
        "-o", "--output", metavar="PATH",
        help="Write to PATH, used as given - its suffix is not checked "
             "against --to. Only with a single --to format. Default: FILE "
             "with the format's suffix, in FILE's folder.",
    )
    p_convert.add_argument(
        "--root", default=".", metavar="DIR",
        help="Server root: a folder holding FILE and every image it links "
             "to, for example the repository root. Images are read only from "
             "inside it. Default: the current directory.",
    )
    p_convert.add_argument(
        "--theme", choices=("light", "dark", "system"),
        help="Colour scheme of SVG images and Mermaid diagrams, and of the "
             "HTML page. system: the HTML page follows the reader's OS "
             "setting; PDF and DOCX render it light. Default: light.",
    )
    p_convert.add_argument(
        "--font-size", choices=tuple(FONT_SIZES),
        help="Base body size, "
             + ", ".join(f"{name} {pt:g} pt" for name, pt in FONT_SIZES.items())
             + f"; every other size scales with it. Default: {DEFAULT_FONT_SIZE}.",
    )
    p_convert.add_argument(
        "--alert-labels", action="store_true",
        help="Print the type (NOTE:, TIP:, ...) at the start of each GitHub "
             "alert box. Default: no label.",
    )
    p_convert.set_defaults(func=cmd_convert)

    p_install = sub.add_parser(
        "install",
        help="Install Chromium binary plus required system libraries "
             "(about 270 MB; may wait for a sudo password).",
        description=(
            "Download Playwright Chromium (about 270 MB, once, into "
            "~/.cache/ms-playwright, or PLAYWRIGHT_BROWSERS_PATH when set), "
            "then launch it. When it does not "
            "launch, install the missing system libraries with apt-get "
            "(Debian and Ubuntu only) and launch it again. apt-get runs "
            "through sudo when not root, so the command can stop and wait "
            "for a sudo password on the terminal; when it cannot install, it "
            "prints the apt-get command to run by hand. Needs network access "
            "and takes minutes."
        ),
    )
    p_install.set_defaults(func=cmd_install)

    p_check = sub.add_parser(
        "check",
        help="Verify Chromium can launch; do not modify the system.",
        description=(
            "Launch Chromium once, headless, and change nothing. Prints "
            "'Chromium launches successfully' and exits 0, or prints FAIL "
            "and the reason on stderr and exits 1."
        ),
    )
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
