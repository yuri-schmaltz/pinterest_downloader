#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import sys
import time
import hashlib
import urllib.parse
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from playwright.sync_api import sync_playwright

# ---------- Config ----------
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

PIN_LINK_RE = re.compile(r'/pin/(\d+)/?')
USER_BOARDS_RE = re.compile(r'^https?://(?:www|br)\.pinterest\.com/([^/]+)/?$', re.I)


# ---------- Utils ----------
def safe_name(url: str) -> str:
    """Gera nome de arquivo estável (usa pin_id quando possível)."""
    m = PIN_LINK_RE.search(url)
    if m:
        return f"{m.group(1)}.jpg"
    base = urllib.parse.urlsplit(url).path.rsplit('/', 1)[-1].split('?')[0]
    if not base or '.' not in base:
        base = hashlib.sha1(url.encode()).hexdigest() + ".jpg"
    return base


def slugify(name: str) -> str:
    """
    Sanitiza componente de caminho preservando Unicode (acentos etc).
    Regras:
      - decode de %XX
      - normalização Unicode NFC
      - troca "/" por "／" (fullwidth) e remove NUL
      - colapsa espaços
    """
    if not isinstance(name, str):
        name = str(name)
    s = urllib.parse.unquote(name)
    s = unicodedata.normalize('NFC', s)
    s = s.replace('\u00A0', ' ')
    s = s.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    s = s.replace('/', '／').replace('\x00', '')
    return s or "sem_nome"


def split_user_board_from_url(board_url: str) -> tuple[str, str]:
    """
    Retorna (usuario, board) a partir de: https://www.pinterest.com/<usuario>/<board>/
    Preserva acentos.
    """
    p = urllib.parse.urlsplit(board_url)
    parts = [x for x in p.path.split('/') if x]
    user = urllib.parse.unquote(parts[0]) if len(parts) >= 1 else "user"
    board = urllib.parse.unquote(parts[1]) if len(parts) >= 2 else "board"
    return user, board


def out_dir_for(board_url: str, out_root: str) -> str:
    user, board = split_user_board_from_url(board_url)
    return os.path.join(out_root, slugify(user), slugify(board))


def _abs_url(href: str) -> str:
    if href.startswith('http'):
        return href.split('?')[0]
    if href.startswith('/'):
        return ('https://www.pinterest.com' + href).split('?')[0]
    return href.split('?')[0]


# ---------- Resolução de imagem ----------
def fetch_og_image(pin_url: str, session: requests.Session) -> str | None:
    """Pega a imagem grande via meta og:image do Pin."""
    try:
        r = session.get(pin_url, timeout=25)
        r.raise_for_status()
    except Exception:
        return None
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', r.text, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r.text, re.I)
    if not m:
        return None
    url = m.group(1)
    return url.split('?')[0]


def download_image(img_url: str, out_dir: str, session: requests.Session, filename_hint: str | None = None) -> bool:
    name = safe_name(filename_hint or img_url)
    dest = os.path.join(out_dir, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True
    try:
        with session.get(img_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            os.makedirs(out_dir, exist_ok=True)
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1 << 15):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception:
        try:
            time.sleep(1.0)
            with session.get(img_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dest, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1 << 15):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception:
            return False


# ---------- Coleta de links ----------
def collect_pin_links(board_url: str, headless: bool, manual_login: bool, scroll_pause: float, max_pins: int | None) -> list[str]:
    """Abre o quadro, rola a página e coleta URLs de Pins (robusto a DOM nulo)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto(board_url, wait_until="networkidle", timeout=90_000)

        # se caiu em login e não vamos fazer login manual, aborta cedo
        if ("login" in page.url or "auth" in page.url) and not manual_login:
            browser.close()
            return []

        if manual_login:
            print("\n>>> Faça login na janela aberta e certifique-se de estar no QUADRO desejado."
                  "\n>>> Volte ao terminal e pressione ENTER para continuar…", flush=True)
            try:
                input()
            except KeyboardInterrupt:
                browser.close()
                sys.exit(1)

        # aguarda DOM mínimo
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        seen = set()
        stable_rounds = 0
        last_count = 0

        while True:
            # coleta links atuais
            hrefs = page.eval_on_selector_all(
                'a[href^="/pin/"]',
                'els => Array.from(new Set(els.map(e => e.getAttribute("href"))))'
            )
            for h in hrefs:
                if not h:
                    continue
                u = _abs_url(h.split('?')[0])
                # normaliza para www
                u = u.replace("://br.pinterest.com/", "://www.pinterest.com/")
                if u.startswith('https://www.pinterest.com/pin/'):
                    seen.add(u)

            if max_pins and len(seen) >= max_pins:
                break

            # rolagem robusta
            try:
                page.evaluate(
                    '(() => { const el = document.scrollingElement || document.documentElement || document.body; '
                    'if (!el) return; window.scrollTo(0, el.scrollHeight); })()'
                )
            except Exception:
                print("  Aviso: falha ao rolar (DOM indisponível). Encerrando coleta deste quadro.")
                break

            page.wait_for_timeout(int(scroll_pause * 1000))

            if len(seen) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = len(seen)

            if stable_rounds >= 6:
                break

        browser.close()
        return list(seen)[:max_pins] if max_pins else list(seen)


def collect_board_urls(username_or_url: str, headless: bool, scroll_pause: float) -> list[str]:
    """
    Coleta URLs de TODOS os quadros públicos do usuário.
    Aceita 'nome' ou URL de perfil (www/br).
    Ignora endpoints agregadores como /_created e /_saved.
    """
    m = USER_BOARDS_RE.match(username_or_url.strip())
    if m:
        username = m.group(1)
    else:
        username = username_or_url.strip().strip('/')

    candidates = [
        f"https://www.pinterest.com/{username}/boards/",
        f"https://www.pinterest.com/{username}/",
        f"https://br.pinterest.com/{username}/boards/",
        f"https://br.pinterest.com/{username}/",
    ]

    EXCLUDE = {
        "boards", "pins", "created", "tried",
        "_created", "_saved", "ideas", "more-ideas",
        "following", "followers"
    }

    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        for url in candidates:
            try:
                page.goto(url, wait_until="networkidle", timeout=90_000)
                page.wait_for_timeout(1500)  # tempo para montar o layout

                stable_rounds = 0
                last_count = 0

                for _ in range(200):  # limite de ciclos de scroll
                    hrefs = page.eval_on_selector_all(
                        'a[href]',
                        'els => Array.from(new Set(els.map(e => e.getAttribute("href"))))'
                    )
                    for h in hrefs:
                        if not h:
                            continue
                        u = _abs_url(h)
                        parsed = urllib.parse.urlsplit(u)
                        parts = [x for x in parsed.path.split('/') if x]
                        # queremos /<user>/<board>/
                        if len(parts) == 2 and parts[0].lower() == username.lower():
                            board = parts[1]
                            if (board.lower() in EXCLUDE) or board.startswith('_'):
                                continue
                            seen.add(f"https://www.pinterest.com/{parts[0]}/{board}/")

                    # rolagem robusta
                    try:
                        page.evaluate(
                            '(() => { const el = document.scrollingElement || document.documentElement || document.body; '
                            'if (!el) return; window.scrollTo(0, el.scrollHeight); })()'
                        )
                    except Exception:
                        break

                    page.wait_for_timeout(int(scroll_pause * 1000))

                    if len(seen) == last_count:
                        stable_rounds += 1
                    else:
                        stable_rounds = 0
                        last_count = len(seen)

                    if stable_rounds >= 6:
                        break

                if seen:
                    break  # já achou; não precisa tentar outros candidatos
            except Exception:
                continue

        browser.close()
        return sorted(seen)


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(
        description="Baixa imagens de um QUADRO do Pinterest, ou de TODOS os quadros públicos de um usuário."
    )
    ap.add_argument("board_url", nargs="?", help="URL do quadro. Ex.: https://www.pinterest.com/<usuario>/<quadro>/")
    ap.add_argument("--user", help="Usuário para baixar TODOS os quadros públicos (ex.: yuri_schmaltz)")
    ap.add_argument("-o", "--out", default="pins", help="Pasta raiz de saída (default: ./pins)")
    ap.add_argument("--headful", action="store_true", help="Abre o navegador visível (útil p/ depurar/login)")
    ap.add_argument("--manual-login", action="store_true", help="Pausa para login antes de coletar (quando necessário)")
    ap.add_argument("--max-pins", type=int, default=None, help="Limita a N pins por quadro (opcional)")
    ap.add_argument("--scroll-pause", type=float, default=1.2, help="Pausa (s) entre rolagens (default: 1.2)")
    ap.add_argument("--workers", type=int, default=16, help="Downloads/resolução em paralelo (default: 16)")
    ap.add_argument("--boards-workers", type=int, default=1, help="Paralelismo entre QUADROS (abre N Chromiums; use 2~3 com cautela)")
    args = ap.parse_args()

    if not args.board_url and not args.user:
        print("Erro: informe uma URL de quadro OU use --user <usuario>.")
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })

    # ---- resolve imagens em paralelo ----
    def resolve_images(pin_links: list[str]) -> dict[str, str]:
        def work(link: str):
            img = fetch_og_image(link, session)
            if not img:
                mobile = link.replace("www.pinterest.com", "br.pinterest.com")
                img = fetch_og_image(mobile, session)
            return (link, img)
        out = {}
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for link, img in ex.map(work, pin_links):
                if img:
                    out[link] = img
        return out

    # ---- baixa um quadro ----
    def process_board(board_url: str, out_root: str | None):
        base_root = out_root or args.out
        target_dir = out_dir_for(board_url, base_root)

        print(f"\n[BOARD] {board_url}")
        print("  [1/3] Coletando links dos pins…")
        pin_links = collect_pin_links(
            board_url=board_url,
            headless=not args.headful,
            manual_login=args.manual_login,
            scroll_pause=args.scroll_pause,
            max_pins=args.max_pins
        )
        if not pin_links:
            print("  Nenhum pin encontrado (privado? login necessário?). Pulando.")
            return 0, 0

        print(f"  [2/3] Resolvendo imagem grande de {len(pin_links)} pins (paralelo)…")
        pin_img = resolve_images(pin_links)
        if not pin_img:
            print("  Não foi possível resolver nenhuma imagem. Pulando.")
            return 0, 0

        print(f"  [3/3] Baixando {len(pin_img)} imagens em '{target_dir}' (paralelo)…")
        ok = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = []
            for link, img_url in pin_img.items():
                futs.append(ex.submit(download_image, img_url, target_dir, session, filename_hint=link))
            for fut in as_completed(futs):
                ok += 1 if fut.result() else 0

        print(f"  Concluído: {ok}/{len(pin_img)}")
        return ok, len(pin_img)

    total_ok = 0
    total_all = 0

    # ---- modo: todos os quadros do usuário ----
    if args.user:
        boards = collect_board_urls(args.user, headless=not args.headful, scroll_pause=args.scroll_pause)
        if not boards:
            print("Nenhum quadro público encontrado para o usuário.")
            sys.exit(5)

        print(f"Encontrados {len(boards)} quadros. Iniciando downloads…")

        user_root = os.path.join(args.out, slugify(args.user))

        if args.boards_workers <= 1:
            for b in boards:
                ok, allc = process_board(b, user_root)
                total_ok += ok
                total_all += allc
        else:
            with ThreadPoolExecutor(max_workers=args.boards_workers) as ex:
                futs = [ex.submit(process_board, b, user_root) for b in boards]
                for fut in as_completed(futs):
                    ok, allc = fut.result()
                    total_ok += ok
                    total_all += allc

    # ---- modo: quadro único ----
    else:
        board = args.board_url.strip()
        ok, allc = process_board(board, args.out)
        total_ok += ok
        total_all += allc

    print(f"\n==> TOTAL: {total_ok}/{total_all} imagens baixadas.")


if __name__ == "__main__":
    main()
