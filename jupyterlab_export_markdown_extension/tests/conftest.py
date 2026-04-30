"""Test fixtures shared across the export-fidelity suite."""

import os
import pathlib

# pytest-jupyter (via jp_root_dir) sets HOME to a temp directory for the
# duration of each test. Playwright resolves the Chromium binary as
# `~/.cache/ms-playwright/...`, so the temp HOME hides the binary that's
# actually installed in the running user's real cache.
#
# Pin PLAYWRIGHT_BROWSERS_PATH to the real cache (if present) before any
# fixture takes effect, which Playwright honours over HOME.
_real_cache = pathlib.Path.home() / ".cache" / "ms-playwright"
if _real_cache.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_real_cache))
