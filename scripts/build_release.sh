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
# Preflight -- fail fast if the extension is incomplete
# ============================================================
# The manifest and popup.html reference files by path. If any of them is
# missing from the checkout, the built package loads in the browser but
# silently fails at runtime (Chrome refuses to inject a content script
# whose file does not exist). Better to fail the build here.
echo "[0/3] Preflight check..."
python3 - "$EXT" <<'PY'
import json, re, sys
from pathlib import Path

ext = Path(sys.argv[1])
manifest = json.loads((ext / "manifest.json").read_text())

referenced = []
for entry in manifest.get("content_scripts", []):
    referenced += entry.get("js", [])
if "background" in manifest:
    referenced.append(manifest["background"].get("service_worker", ""))
if "action" in manifest:
    referenced.append(manifest["action"].get("default_popup", ""))

popup = ext / "popup.html"
if popup.exists():
    referenced += re.findall(r'<script[^>]+src="([^"]+)"', popup.read_text())

missing = [r for r in filter(None, referenced) if not (ext / r).exists()]
if missing:
    print("ERROR: the extension references files that do not exist:", file=sys.stderr)
    for m in missing:
        print(f"  - extension/{m}", file=sys.stderr)
    print("Check that they are committed -- 'git check-ignore -v extension/<file>'", file=sys.stderr)
    raise SystemExit(1)

print(f"    ✓ all {len(referenced)} referenced files present")
PY

# ============================================================
# Chrome Web Store package (.zip)
# ============================================================
echo "[1/3] Chrome Web Store package..."
cd "$EXT"
# 'zip' ATUALIZA um arquivo existente em vez de recria-lo: o que foi
# apagado da origem continua no pacote para sempre. Como o nome do
# artefato inclui a versao, um rebuild da mesma versao reaproveitaria o
# pacote velho. Por isso os arquivos sao removidos antes.
rm -f "$DIST/pinterest-pro-downloader-chrome-v${VERSION}.zip"
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
rm -f "$DIST/pinterest-pro-downloader-firefox-v${VERSION}.xpi"
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
# Mesmo cuidado do zip: o tarball tambem e atualizado no lugar.
rm -f "$DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz"
# Must include the whole application: src/ (the app itself), tests/,
# extension/ (the browser extension), scripts/, docs/ and assets/.
# The previous version shipped only extension/ + scripts/, which meant
# the "source" download contained no application code at all.
tar -czf "$DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz" \
    --exclude='dist' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='*.pyc' \
    src \
    tests \
    extension \
    scripts \
    docs \
    assets \
    .github \
    pyproject.toml \
    requirements.txt \
    README.md \
    LICENSE \
    .gitignore

# Fail if the archive ended up without the application source.
# Note: capture into a variable first. With `set -o pipefail`, piping tar
# straight into `grep -q` makes grep exit early, which kills tar with
# SIGPIPE and makes the whole pipeline look like a failure.
ARCHIVE_CONTENTS="$(tar -tzf "$DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz")"
if ! printf '%s\n' "$ARCHIVE_CONTENTS" | grep -q "^src/"; then
    echo "ERROR: source archive does not contain src/ -- refusing to publish" >&2
    exit 1
fi
if ! printf '%s\n' "$ARCHIVE_CONTENTS" | grep -q "^tests/"; then
    echo "ERROR: source archive does not contain tests/ -- refusing to publish" >&2
    exit 1
fi
echo "    ✓ $DIST/pinterest-pro-downloader-source-v${VERSION}.tar.gz"

echo
echo "==> Done!"
echo "    Files:"
ls -la "$DIST"
echo
echo "==> Checksums:"
cd "$DIST"
sha256sum *.zip *.xpi *.tar.gz 2>/dev/null | sed 's/^/    /'