"""Post-install CLI for jupyterlab_export_markdown_extension.

The DOCX/PDF export pipeline rasterises embedded SVG images through
Playwright Chromium so CSS, web fonts, filters and `prefers-color-scheme`
match a real browser. Chromium needs (a) the binary itself (~270 MB,
downloaded once into ~/.cache/ms-playwright) and (b) a handful of
shared system libraries (libnspr4, libnss3, ...).

This CLI handles both:

    jupyterlab-export-markdown-extension install   # do it
    jupyterlab-export-markdown-extension check     # verify only
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

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
    print(f"FAIL: {msg}", file=sys.stderr)
    print(
        "\nFix with:  jupyterlab-export-markdown-extension install",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jupyterlab-export-markdown-extension",
        description=(
            "Post-install helper for jupyterlab_export_markdown_extension. "
            "Installs and verifies the Playwright Chromium runtime used for "
            "server-side SVG-to-PNG rendering."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser(
        "install",
        help="Install Chromium binary plus required system libraries.",
    )
    p_install.set_defaults(func=cmd_install)

    p_check = sub.add_parser(
        "check",
        help="Verify Chromium can launch; do not modify the system.",
    )
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
