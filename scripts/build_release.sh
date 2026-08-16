#!/usr/bin/env bash
# ============================================================================
# Pinterest Pro Downloader — Release Builder
# ============================================================================
# Gera artefatos prontos para publicação:
#   - dist/pinterest-pro-downloader-chrome-v2.0.0.zip     (Chrome Web Store)
#   - dist/pinterest-pro-downloader-firefox-v2.0.0.xpi   (Firefox Add-ons)
#   - dist/pinterest-pro-downloader-source-v2.0.0.zip    (source code)
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT="$ROOT/extension"
DIST="$ROOT/dist"
VERSION=$(python3 -c "import json; print(json.load(open('$EXT/manifest.json'))['version'])")

mkdir -p "$DIST"

echo "==> Building Pinterest Pro Downloader v${VERSION}"
echo "    Extension source: $EXT"
echo "    Output:           $DIST"
echo

# ============================================================
# Chrome Web Store package (.zip)
# ============================================================
echo "[1/3] Chrome Web Store package..."
cd "$EXT"
zip -r "$DIST/pinterest-pro-downloader-chrome-v${VERSION}.zip" \
    manifest.json \
    background.js \
    content.js \
    popup.html \
    popup.js \
    lib/ \
    _locales/ \
    icons/ \
    -x "*.DS_Store" \
       "icons/*.svg" \
       "*/.git/*"
echo "    ✓ $DIST/pinterest-pro-downloader-chrome-v${VERSION}.zip"

# ============================================================
# Firefox Add-ons package (.xpi — same as zip)
# ============================================================
echo "[2/3] Firefox Add-ons package..."
# Firefox MV3 add-ons are distributed as .xpi (which is a ZIP file).
# Note: we keep both background.js (chrome.* API). Firefox 121+ accepts this.
cd "$EXT"
zip -r "$DIST/pinterest-pro-downloader-firefox-v${VERSION}.xpi" \
    manifest.json \
    background.js \
    content.js \
    popup.html \
    popup.js \
    lib/ \
    _locales/ \
    icons/ \
    -x "*.DS_Store" \
       "icons/*.svg" \
       "*/.git/*"
echo "    ✓ $DIST/pinterest-pro-downloader-firefox-v${VERSION}.xpi"

# ============================================================
# Source code archive (for releases page)
# ============================================================
echo "[3/3] Source archive..."
cd "$ROOT"
# Include everything except dist/ and __pycache__/
tar -czf "$DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz" \
    --exclude='dist' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='node_modules' \
    extension scripts pyproject.toml requirements.txt README.md LICENSE 2>/dev/null \
    || tar -czf "$DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz" \
       --exclude='dist' \
       --exclude='__pycache__' \
       extension
echo "    ✓ $DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz"

echo
echo "==> Done!"
echo "    Files:"
ls -la "$DIST"
echo
echo "==> Checksums:"
cd "$DIST"
sha256sum *.zip *.xpi *.tar.gz 2>/dev/null | sed 's/^/    /'