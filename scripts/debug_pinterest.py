#!/usr/bin/env python3
"""Script de depuração manual do scraper do Pinterest.

Este arquivo NÃO é um teste. Ele foi movido de ``tests/test_playwright.py``
para cá porque o pytest coletava o nome ``test_*.py`` e executava o script
inteiro -- abrindo um Chromium e acessando o Pinterest -- no meio da coleta
de testes, o que fazia o CI depender de browser e de rede externa.

Uso manual::

    python scripts/debug_pinterest.py
    python scripts/debug_pinterest.py --url https://www.pinterest.com/user/board/ --out /tmp/shot.png
"""

import argparse
import sys
from pathlib import Path

DEFAULT_URL = "https://www.pinterest.com/yuri_schmaltz/boards/"
DEFAULT_OUT = "pinterest_debug.png"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="URL da página do Pinterest a inspecionar (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="caminho do screenshot a salvar (default: %(default)s)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=3000,
        help="ms de espera após o load (default: %(default)s)",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright nao instalado. Rode:\n"
            "    python -m pip install playwright && python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"==> Navegando para {args.url}")
        page.goto(args.url, wait_until="networkidle")
        page.wait_for_timeout(args.wait)
        page.screenshot(path=str(out_path))
        text = page.evaluate("document.body.innerText")
        print(f"==> Screenshot salvo em {out_path}")
        print("--- Texto da pagina (500 primeiros caracteres) ---")
        print(text[:500])
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
