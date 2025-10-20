#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Ferramentas para baixar quadros do Pinterest via CLI ou GUI."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, NamedTuple

import requests
from playwright.sync_api import sync_playwright

# ---------- Config ----------
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

PIN_LINK_RE = re.compile(r"/pin/(\d+)/?")
USER_BOARDS_RE = re.compile(r"^https?://(?:www|br)\\.pinterest\\.com/([^/]+)/?$", re.I)


# ---------- Tipos ----------


class BoardDownloadResult(NamedTuple):
    board_url: str
    downloaded: int
    total: int
    output_dir: str


StatusCallback = Callable[[str, Dict], None]


@dataclass(slots=True)
class DownloadOptions:
    out_root: str = "pins"
    headless: bool = True
    manual_login: bool = False
    max_pins: int | None = None
    scroll_pause: float = 1.2
    workers: int = 16
    boards_workers: int = 1


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
    """Sanitiza componente de caminho preservando Unicode."""
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
    """Retorna (usuario, board) a partir de uma URL."""
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


def download_image(
    img_url: str,
    out_dir: str,
    session: requests.Session,
    filename_hint: str | None = None,
) -> bool:
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


def collect_pin_links(
    board_url: str,
    headless: bool,
    manual_login: bool,
    scroll_pause: float,
    max_pins: int | None,
    manual_login_handler: Callable[[], None] | None = None,
) -> List[str]:
    """Abre o quadro, rola a página e coleta URLs de Pins."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto(board_url, wait_until="networkidle", timeout=90_000)

        if ("login" in page.url or "auth" in page.url) and not manual_login:
            browser.close()
            return []

        if manual_login:
            if manual_login_handler:
                manual_login_handler()
            else:
                print(
                    "\n>>> Faça login na janela aberta e certifique-se de estar no QUADRO desejado."
                    "\n>>> Volte ao terminal e pressione ENTER para continuar…",
                    flush=True,
                )
                try:
                    input()
                except KeyboardInterrupt:
                    browser.close()
                    sys.exit(1)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        seen = set()
        stable_rounds = 0
        last_count = 0

        while True:
            hrefs = page.eval_on_selector_all(
                'a[href^="/pin/"]',
                'els => Array.from(new Set(els.map(e => e.getAttribute("href"))))',
            )
            for h in hrefs:
                if not h:
                    continue
                u = _abs_url(h.split('?')[0])
                u = u.replace("://br.pinterest.com/", "://www.pinterest.com/")
                if u.startswith('https://www.pinterest.com/pin/'):
                    seen.add(u)

            if max_pins and len(seen) >= max_pins:
                break

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


def collect_board_urls(username_or_url: str, headless: bool, scroll_pause: float) -> List[str]:
    """Coleta URLs de todos os quadros públicos do usuário."""
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

    exclude = {
        "boards",
        "pins",
        "created",
        "tried",
        "_created",
        "_saved",
        "ideas",
        "more-ideas",
        "following",
        "followers",
    }

    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()

        for url in candidates:
            try:
                page.goto(url, wait_until="networkidle", timeout=90_000)
                page.wait_for_timeout(1500)

                stable_rounds = 0
                last_count = 0

                for _ in range(200):
                    hrefs = page.eval_on_selector_all(
                        'a[href]',
                        'els => Array.from(new Set(els.map(e => e.getAttribute("href"))))',
                    )
                    for h in hrefs:
                        if not h:
                            continue
                        u = _abs_url(h)
                        parsed = urllib.parse.urlsplit(u)
                        parts = [x for x in parsed.path.split('/') if x]
                        if len(parts) == 2 and parts[0].lower() == username.lower():
                            board = parts[1]
                            if board.lower() in exclude or board.startswith('_'):
                                continue
                            seen.add(f"https://www.pinterest.com/{parts[0]}/{board}/")

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
                    break
            except Exception:
                continue

        browser.close()
        return sorted(seen)


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
    )
    return session


def resolve_images(
    pin_links: Iterable[str],
    session: requests.Session,
    workers: int,
    emit: StatusCallback | None = None,
) -> Dict[str, str]:
    emit = emit or (lambda *_: None)

    links = list(pin_links)
    total_links = len(links)
    emit("resolve_start", {"total": total_links})

    out: Dict[str, str] = {}
    processed = 0

    def work(link: str) -> tuple[str, str | None]:
        img = fetch_og_image(link, session)
        if not img:
            mobile = link.replace("www.pinterest.com", "br.pinterest.com")
            img = fetch_og_image(mobile, session)
        return link, img

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for link, img in ex.map(work, links):
            processed += 1
            if img:
                out[link] = img
            emit("resolve_progress", {"current": processed, "total": total_links})

    emit("resolve_complete", {"found": len(out), "total": total_links})
    return out


def download_board(
    board_url: str,
    options: DownloadOptions,
    session: requests.Session | None = None,
    status_cb: StatusCallback | None = None,
    manual_login_handler: Callable[[str], None] | None = None,
) -> BoardDownloadResult:
    emit = status_cb or (lambda *_: None)
    session = session or create_session()

    target_dir = out_dir_for(board_url, options.out_root)

    emit("board_start", {"board_url": board_url, "output_dir": target_dir})
    emit("log", {"message": f"[BOARD] {board_url}"})
    emit("log", {"message": "  [1/3] Coletando links dos pins…"})
    def handle_manual_login() -> None:
        emit(
            "manual_login_required",
            {"board_url": board_url, "message": "Faça login e retorne para continuar."},
        )
        if manual_login_handler:
            manual_login_handler(board_url)
            return
        if sys.stdin.isatty():
            print(
                "\n>>> Faça login na janela aberta e certifique-se de estar no QUADRO desejado."
                "\n>>> Volte ao terminal e pressione ENTER para continuar…",
                flush=True,
            )
            try:
                input()
            except KeyboardInterrupt:
                sys.exit(1)
        else:
            raise RuntimeError("Manual login requerido sem manipulador interativo disponível.")

    pin_links = collect_pin_links(
        board_url=board_url,
        headless=options.headless,
        manual_login=options.manual_login,
        scroll_pause=options.scroll_pause,
        max_pins=options.max_pins,
        manual_login_handler=handle_manual_login if options.manual_login else None,
    )

    if not pin_links:
        emit("log", {"message": "  Nenhum pin encontrado (privado? login necessário?). Pulando."})
        emit(
            "board_complete",
            {
                "board_url": board_url,
                "downloaded": 0,
                "total": 0,
                "output_dir": target_dir,
            },
        )
        return BoardDownloadResult(board_url, 0, 0, target_dir)

    emit("pins_collected", {"board_url": board_url, "count": len(pin_links)})
    emit(
        "log",
        {"message": f"  [2/3] Resolvendo imagem grande de {len(pin_links)} pins (paralelo)…"},
    )
    pin_img = resolve_images(pin_links, session=session, workers=options.workers, emit=emit)

    if not pin_img:
        emit("log", {"message": "  Não foi possível resolver nenhuma imagem. Pulando."})
        emit(
            "board_complete",
            {
                "board_url": board_url,
                "downloaded": 0,
                "total": 0,
                "output_dir": target_dir,
            },
        )
        return BoardDownloadResult(board_url, 0, 0, target_dir)

    emit(
        "log",
        {
            "message": f"  [3/3] Baixando {len(pin_img)} imagens em '{target_dir}' (paralelo)…",
        },
    )

    ok = 0
    total = len(pin_img)
    emit("download_start", {"board_url": board_url, "total": total})

    with ThreadPoolExecutor(max_workers=options.workers) as ex:
        futs = [
            ex.submit(download_image, img_url, target_dir, session, filename_hint=link)
            for link, img_url in pin_img.items()
        ]
        for idx, fut in enumerate(as_completed(futs), 1):
            if fut.result():
                ok += 1
            emit(
                "download_progress",
                {
                    "board_url": board_url,
                    "current": idx,
                    "total": total,
                    "downloaded": ok,
                },
            )

    emit("log", {"message": f"  Concluído: {ok}/{total}"})
    emit(
        "board_complete",
        {
            "board_url": board_url,
            "downloaded": ok,
            "total": total,
            "output_dir": target_dir,
        },
    )

    return BoardDownloadResult(board_url, ok, total, target_dir)


def download_user_boards(
    username_or_url: str,
    options: DownloadOptions,
    status_cb: StatusCallback | None = None,
    manual_login_handler: Callable[[str], None] | None = None,
) -> List[BoardDownloadResult]:
    emit = status_cb or (lambda *_: None)
    emit("log", {"message": "Coletando quadros públicos do usuário…"})
    boards = collect_board_urls(
        username_or_url,
        headless=options.headless,
        scroll_pause=options.scroll_pause,
    )

    if not boards:
        emit("log", {"message": "Nenhum quadro público encontrado para o usuário."})
        return []

    emit("boards_found", {"boards": boards})
    emit("log", {"message": f"Encontrados {len(boards)} quadros. Iniciando downloads…"})

    results: Dict[str, BoardDownloadResult] = {}

    if options.boards_workers <= 1:
        session = create_session()
        for idx, board in enumerate(boards, 1):
            res = download_board(
                board,
                options,
                session=session,
                status_cb=emit,
                manual_login_handler=manual_login_handler,
            )
            results[board] = res
            emit("overall_progress", {"current": idx, "total": len(boards)})
    else:
        def worker(board_url: str) -> BoardDownloadResult:
            return download_board(
                board_url,
                options,
                session=None,
                status_cb=emit,
                manual_login_handler=manual_login_handler,
            )

        with ThreadPoolExecutor(max_workers=options.boards_workers) as ex:
            futs = {ex.submit(worker, board): board for board in boards}
            completed = 0
            for fut in as_completed(futs):
                res = fut.result()
                results[res.board_url] = res
                completed += 1
                emit("overall_progress", {"current": completed, "total": len(boards)})

    ordered_results = [results[b] for b in boards if b in results]
    emit("user_complete", {"boards": boards, "results": ordered_results})
    return ordered_results


# ---------- CLI ----------


def _cli_status_printer(stage: str, data: Dict) -> None:
    if stage == "log":
        print(data.get("message", ""))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Baixa imagens de um QUADRO do Pinterest, ou de TODOS os quadros públicos de um usuário."
    )
    ap.add_argument(
        "board_url",
        nargs="?",
        help="URL do quadro. Ex.: https://www.pinterest.com/<usuario>/<quadro>/",
    )
    ap.add_argument("--user", help="Usuário para baixar TODOS os quadros públicos (ex.: yuri_schmaltz)")
    ap.add_argument("-o", "--out", default="pins", help="Pasta raiz de saída (default: ./pins)")
    ap.add_argument("--headful", action="store_true", help="Abre o navegador visível (útil p/ depurar/login)")
    ap.add_argument(
        "--manual-login",
        action="store_true",
        help="Pausa para login antes de coletar (quando necessário)",
    )
    ap.add_argument("--max-pins", type=int, default=None, help="Limita a N pins por quadro (opcional)")
    ap.add_argument(
        "--scroll-pause",
        type=float,
        default=1.2,
        help="Pausa (s) entre rolagens (default: 1.2)",
    )
    ap.add_argument("--workers", type=int, default=16, help="Downloads/resolução em paralelo (default: 16)")
    ap.add_argument(
        "--boards-workers",
        type=int,
        default=1,
        help="Paralelismo entre QUADROS (abre N Chromiums; use 2~3 com cautela)",
    )
    args = ap.parse_args()

    if not args.board_url and not args.user:
        print("Erro: informe uma URL de quadro OU use --user <usuario>.")
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)

    options = DownloadOptions(
        out_root=args.out,
        headless=not args.headful,
        manual_login=args.manual_login,
        max_pins=args.max_pins,
        scroll_pause=args.scroll_pause,
        workers=args.workers,
        boards_workers=args.boards_workers,
    )

    total_ok = 0
    total_all = 0

    if args.user:
        results = download_user_boards(args.user, options, status_cb=_cli_status_printer)
        if not results:
            sys.exit(5)
        for res in results:
            total_ok += res.downloaded
            total_all += res.total
    else:
        board = args.board_url.strip()
        res = download_board(board, options, status_cb=_cli_status_printer)
        total_ok += res.downloaded
        total_all += res.total

    print(f"\n==> TOTAL: {total_ok}/{total_all} imagens baixadas.")


if __name__ == "__main__":
    main()
