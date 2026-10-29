"""PyInstaller runtime hook.

Runs inside the frozen app before the user's code. Its job is to point
Playwright at the Chromium copy bundled with the application.

Without this, a frozen build looks for the browser in the per-user cache
(~/.cache/ms-playwright) and fails with a "Executable doesn't exist" error
on any machine that does not happen to have Playwright installed.
"""

import os
import sys

_base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
_bundled = os.path.join(_base, "browsers")

if os.path.isdir(_bundled):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _bundled
