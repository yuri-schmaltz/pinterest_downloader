"""Versao do app, resolvida em um lugar so.

A versao do projeto mora em `extension/manifest.json` -- o
`scripts/sync_version.py` deriva dela o `pyproject.toml` e o
`src/_version.py`, e a CI falha o build se qualquer um dos tres divergir.

Este modulo pergunta, nesta ordem:

  1. `src/_version.py`, que e gerado a partir do manifest e viaja com o
     codigo -- inclusive dentro do AppImage congelado, onde nao ha metadata
     de pacote nem o manifest no disco;
  2. `extension/manifest.json`, para um checkout de codigo em que o
     arquivo gerado nao existe;
  3. os metadados do pacote instalado;
  4. "desconhecida".

O passo 3 vem por ultimo de proposito: num `pip install -e .` a metadata
fica congelada na instalacao e continua reportando a versao antiga depois
de um bump. Confiar nela primeiro seria mostrar um numero errado.
"""

from __future__ import annotations

import json
from pathlib import Path

PACKAGE_NAME = "pinterest-board-downloader"
UNKNOWN = "desconhecida"

# src/ -> raiz do repositorio
_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST = _ROOT / "extension" / "manifest.json"


def _from_generated() -> str | None:
    """A constante gerada por scripts/sync_version.py."""
    try:
        from _version import __version__  # type: ignore[import-not-found]

        return __version__
    except Exception:
        return None


def _from_manifest() -> str | None:
    """O manifest da extensao -- a fonte da verdade do repositorio."""
    try:
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version")
    return version if isinstance(version, str) and version else None


def _from_package_metadata() -> str | None:
    """A versao do pacote instalado, se houver."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python antigo
        return None
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return None


def get_version() -> str:
    """A versao do app, como string. Nunca levanta excecao."""
    return _from_generated() or _from_manifest() or _from_package_metadata() or UNKNOWN


def get_version_banner() -> str:
    """Versao numa linha, para `--version` e para o rodape da GUI."""
    return f"{PACKAGE_NAME} {get_version()}"
