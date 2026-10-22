#!/usr/bin/env python3
"""Diagnóstico rápido do ambiente do Pinterest Board Downloader.

Substitui o antigo `diagnostics.py`, removido no commit 9fb4c3e. A versão
antiga era pesada: abria o navegador, batia no Pinterest e media
performance, o que a tornava inútil para "minha instalação está correta?".

Esta versão é rápida e offline por padrão:
- não abre navegador
- não faz requisição de rede
- não escreve nada fora do diretório de cache

Uso:
    python scripts/diagnose.py            # checagem rápida (offline)
    python scripts/diagnose.py --deep     # checagem completa (abre o browser)
    python scripts/diagnose.py --json     # saida em JSON, para CI ou suporte
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

REQUIRED_MODULES = [
    "requests",
    "playwright",
    "psutil",
]

APP_MODULES = [
    "pinterest_board_dl",
    "pinterest_board_gui",
    "json_logger",
    "adaptive_workers",
    "rate_limiter",
]


def _ok(msg: str) -> dict:
    return {"status": OK, "message": msg}


def _warn(msg: str) -> dict:
    return {"status": WARN, "message": msg}


def _fail(msg: str) -> dict:
    return {"status": FAIL, "message": msg}


def check_python() -> dict:
    version = platform.python_version()
    if sys.version_info < (3, 10):
        return _fail(f"Python {version} -- o projeto exige 3.10 ou superior")
    return _ok(f"Python {version} ({platform.system()} {platform.machine()})")


def check_dependencies() -> list[dict]:
    results = []
    for name in REQUIRED_MODULES:
        try:
            mod = importlib.import_module(name)
            results.append(_ok(f"{name} {getattr(mod, '__version__', '(versao desconhecida)')}"))
        except ImportError as exc:
            results.append(_fail(f"{name} nao instalado ({exc}) -- rode: pip install -r requirements.txt"))
    return results


def check_app_modules() -> list[dict]:
    """Importa os modulos da aplicacao a partir de src/."""
    results = []
    added = str(SRC) not in sys.path
    if added:
        sys.path.insert(0, str(SRC))
    for name in APP_MODULES:
        try:
            importlib.import_module(name)
            results.append(_ok(f"{name} importa"))
        except ImportError as exc:
            results.append(_fail(f"{name} nao importa ({exc})"))
        except Exception as exc:
            # Falha de import pode ser so falta de lib de sistema (libEGL etc)
            results.append(_warn(f"{name} importou com erro ({type(exc).__name__}: {exc})"))
    return results


def check_browser(deep: bool) -> dict:
    """Verifica se o Chromium do Playwright esta disponivel."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _fail("playwright nao instalado -- rode: pip install playwright && playwright install chromium")

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not browsers_path:
        default = Path.home() / ".cache" / "ms-playwright"
        browsers_path = str(default) if default.exists() else ""

    if not deep:
        # Sem --deep, apenas checa se o diretorio de browsers existe.
        if browsers_path and Path(browsers_path).exists():
            return _ok(f"Chromium instalado em {browsers_path}")
        return _warn(
            "Chromium nao encontrado -- rode: playwright install chromium " "(ou use --deep para um teste completo)"
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            version = browser.version
            browser.close()
        return _ok(f"Chromium funciona (versao {version})")
    except Exception as exc:
        return _fail(f"Chromium nao subiu: {type(exc).__name__}: {exc}")


def check_cache_dir() -> dict:
    try:
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        from pinterest_board_dl import get_cache_dir, get_config_dir

        cache_dir = get_cache_dir()
        config_dir = get_config_dir()
        probe = cache_dir / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return _ok(f"cache: {cache_dir} | config: {config_dir} (gravavel)")
    except Exception as exc:
        return _fail(f"cache nao gravavel: {type(exc).__name__}: {exc}")


def check_extension() -> dict:
    """Confere se a extensao referencia apenas arquivos versionados."""
    ext = ROOT / "extension"
    manifest_path = ext / "manifest.json"
    if not manifest_path.exists():
        return _fail("extension/manifest.json nao encontrado")

    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:
        return _fail(f"manifest.json invalido: {exc}")

    referenced = []
    for entry in manifest.get("content_scripts", []):
        referenced += entry.get("js", [])
    if "background" in manifest:
        referenced.append(manifest["background"].get("service_worker", ""))
    if "action" in manifest:
        referenced.append(manifest["action"].get("default_popup", ""))

    popup = ext / "popup.html"
    if popup.exists():
        import re

        referenced += re.findall(r'<script[^>]+src="([^"]+)"', popup.read_text())

    missing = [r for r in filter(None, referenced) if not (ext / r).exists()]
    if missing:
        return _fail(f"extension referencia arquivos ausentes: {', '.join(missing)}")
    return _ok(f"extension ok ({len(referenced)} arquivos referenciados, todos presentes)")


def check_disk_space() -> dict:
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / (1024**3)
    if free_gb < 1:
        return _warn(f"apenas {free_gb:.1f} GB livres -- downloads podem falhar")
    return _ok(f"{free_gb:.1f} GB livres em {ROOT}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true", help="inclui o teste real do Chromium")
    parser.add_argument("--json", action="store_true", help="saida em JSON")
    args = parser.parse_args()

    # Cada grupo tem um titulo e as checagens filhas. As filhas herdam o
    # status do grupo quando nao produzirem um proprio.
    groups: list[tuple[str, list[dict]]] = [
        ("Python", [check_python()]),
        ("Dependencias", check_dependencies()),
        ("Modulos da app", check_app_modules()),
        ("Navegador", [check_browser(args.deep)]),
        ("Cache", [check_cache_dir()]),
        ("Extensao", [check_extension()]),
        ("Disco", [check_disk_space()]),
    ]

    flat = []
    for name, children in groups:
        for child in children:
            flat.append({"group": name, "status": child["status"], "message": child["message"]})

    failures = [c for c in flat if c["status"] == FAIL]
    warnings = [c for c in flat if c["status"] == WARN]

    if args.json:
        print(
            json.dumps(
                {
                    "version": 1,
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "checks": flat,
                    "summary": {
                        "total": len(flat),
                        "failed": len(failures),
                        "warnings": len(warnings),
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        symbols = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}
        print("=" * 62)
        print("  Pinterest Board Downloader -- diagnostico de ambiente")
        print("=" * 62)
        last_group = None
        for check in flat:
            if check["group"] != last_group:
                print()
                print(f"  {check['group']}")
                last_group = check["group"]
            print(f"    {symbols[check['status']]} {check['message']}")
        print()
        print("-" * 62)
        print(f"  {len(flat)} checagens | {len(failures)} falha(s) | {len(warnings)} aviso(s)")
        if failures:
            print()
            print("  FALHAS:")
            for check in failures:
                print(f"    - {check['group']}: {check['message']}")
        print("=" * 62)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
