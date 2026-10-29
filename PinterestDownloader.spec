# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Pinterest Pro Downloader desktop app.

Build with:
    pyinstaller PinterestDownloader.spec

Produces (onedir, so the AppImage/deb packaging in .github/workflows/release.yml
has a directory to work with):
    dist/pinterest-board-downloader/pinterest-board-downloader

Notes:
- The app is the PyQt6 GUI (src/pinterest_board_gui.py). The CLI
  (src/pinterest_board_dl.py) is a library module and is bundled along with
  it, since the GUI imports it.
- The modules under src/ use flat imports ("from json_logger import ..."), so
  src/ must be on the analysis path AND the modules must be listed as
  hidden imports -- otherwise PyInstaller cannot discover them.
- Playwright ships a bundled Node driver, so it has to be collected whole.
  The Chromium browser itself is NOT bundled: the app expects
  `playwright install chromium` to have been run, or PLAYWRIGHT_BROWSERS_PATH
  to point at a preinstalled browser directory.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(os.path.abspath(SPECPATH))
SRC = ROOT / "src"
ASSETS = ROOT / "assets"
HOOKS = ROOT / "hooks"

# Playwright: collect the package, its binaries and its data files.
pw_datas, pw_binaries, pw_hiddenimports = collect_all("playwright")

# The Chromium browser itself is installed separately ("playwright install
# chromium"). When PLAYWRIGHT_BROWSERS_PATH points at a directory, bundle it
# so the frozen app is self-contained -- otherwise it only runs on machines
# that happen to have Playwright installed. The runtime hook in
# hooks/playwright_browsers.py points the bundled app back at this copy.
browsers_dir = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
browser_datas = []
if browsers_dir.is_dir():
    browser_datas = [(str(browsers_dir), "browsers")]
    print(f"[spec] bundling Playwright browsers from {browsers_dir}")
else:
    print(
        "[spec] PLAYWRIGHT_BROWSERS_PATH not set or not a directory -- "
        "the frozen app will look for a system-wide Chromium"
    )

block_cipher = None

a = Analysis(
    [str(SRC / "pinterest_board_gui.py")],
    pathex=[str(SRC)],
    binaries=pw_binaries,
    datas=[
        (str(ASSETS / "icon.svg"), "assets"),
    ]
    + pw_datas
    + browser_datas,
    hiddenimports=[
        # Flat-imported siblings from src/ -- PyInstaller cannot see these
        # through static analysis of the GUI module alone.
        "pinterest_board_dl",
        "json_logger",
        "adaptive_workers",
        "rate_limiter",
        # Used by the GUI for the board thumbnails.
        "PyQt6.QtSvg",
    ]
    + pw_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(HOOKS / "playwright_browsers.py"),
    ],
    # These are heavy and not needed for the GUI app.
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL.ImageQt",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pinterest-board-downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Tell the bundled Playwright where to look for the browser and make
    # sure it does not try to write into a read-only bundle.
    runtime_tmpdir=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="pinterest-board-downloader",
)
