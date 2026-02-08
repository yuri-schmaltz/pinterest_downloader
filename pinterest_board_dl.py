#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Ferramentas para baixar quadros do Pinterest via CLI ou GUI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, NamedTuple, TypedDict

class BoardMetadata(TypedDict):
    url: str
    title: str
    thumbnail_url: str
    pin_count: str

import requests
from playwright.sync_api import sync_playwright

from json_logger import get_logger, reset_logger
from adaptive_workers import get_adaptive_manager, reset_adaptive_manager
from rate_limiter import get_rate_limiter, reset_rate_limiter, RateLimitConfig

# ---------- Config ----------
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
# URLs base
PINTEREST_BASE_URL = "https://www.pinterest.com"

# Timeouts (em milissegundos para Playwright, segundos para requests)
TIMEOUT_HTTP_GET = 25  # requests.get() para fetch og:image
TIMEOUT_IMAGE_DOWNLOAD = 60  # requests.get() stream para imagens
TIMEOUT_PAGE_LOAD = 90_000  # Playwright page.goto()
TIMEOUT_DOM_READY = 15_000  # Playwright wait_for_load_state()

# Retry config
DOWNLOAD_RETRY_DELAY = 1.0  # segundos entre retries
DOWNLOAD_MAX_RETRIES = 1  # número de retries (além da tentativa inicial)

# Scroll detection
SCROLL_STABLE_ROUNDS = 10  # Aumentado para 10 para lidar com carregamento lento/lag
SCROLL_HEIGHT_CHECK = True  # usar detecção de altura de página

PIN_LINK_RE = re.compile(r"/pin/(\d+)/?")
USER_BOARDS_RE = re.compile(r"^https?://(?:www|br)\\.pinterest\\.com/([^/]+)/?$", re.I)

# ---------- Cache (XDG/AppData compliant) ----------

APP_NAME = "pinterest-downloader"


def get_cache_dir() -> Path:
    """Retorna o diretório de cache apropriado para o SO.
    
    Linux: XDG_CACHE_HOME (~/.cache/pinterest-downloader/)
    Windows: LOCALAPPDATA (C:\\Users\\<user>\\AppData\\Local\\pinterest-downloader\\)
    Fallback: Diretório atual
    """
    if sys.platform == "win32":
        # Windows: Use LOCALAPPDATA
        base = os.environ.get("LOCALAPPDATA")
        if base:
            cache_dir = Path(base) / APP_NAME
        else:
            cache_dir = Path.home() / "AppData" / "Local" / APP_NAME
    else:
        # Linux/macOS: Use XDG_CACHE_HOME
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            cache_dir = Path(xdg_cache) / APP_NAME
        else:
            cache_dir = Path.home() / ".cache" / APP_NAME
    
    # Ensure directory exists
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback to current directory if creation fails
        cache_dir = Path(".")
    
    return cache_dir


def get_config_dir() -> Path:
    """Retorna o diretório de configuração apropriado para o SO.
    
    Linux: XDG_CONFIG_HOME (~/.config/pinterest-downloader/)
    Windows: LOCALAPPDATA (C:\\Users\\<user>\\AppData\\Local\\pinterest-downloader\\)
    Fallback: Diretório atual
    """
    if sys.platform == "win32":
        # Windows: Use LOCALAPPDATA (same as cache for simplicity)
        base = os.environ.get("LOCALAPPDATA")
        if base:
            config_dir = Path(base) / APP_NAME
        else:
            config_dir = Path.home() / "AppData" / "Local" / APP_NAME
    else:
        # Linux/macOS: Use XDG_CONFIG_HOME
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            config_dir = Path(xdg_config) / APP_NAME
        else:
            config_dir = Path.home() / ".config" / APP_NAME
    
    # Ensure directory exists
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback to current directory if creation fails
        config_dir = Path(".")
    
    return config_dir


def get_cache_file_path(filename: str = ".pinterest_cache.json") -> Path:
    """Retorna o caminho completo para um arquivo de cache."""
    return get_cache_dir() / filename


# Legacy compatibility: CACHE_FILE now resolves dynamically
CACHE_FILE = get_cache_file_path()


def load_pin_cache(cache_dir: str | None = None) -> Dict[str, str]:
    """Carrega cache de pin_url -> og:image_url.
    
    Args:
        cache_dir: Diretório personalizado (opcional). Se None, usa XDG/AppData.
    """
    if cache_dir:
        cache_path = Path(cache_dir) / ".pinterest_cache.json"
    else:
        cache_path = get_cache_file_path()
    
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            return {}
    return {}


def save_pin_cache(cache: Dict[str, str], cache_dir: str | None = None) -> None:
    """Salva cache de pins em disco.
    
    Args:
        cache: Dict de pin_url -> og:image_url
        cache_dir: Diretório personalizado (opcional). Se None, usa XDG/AppData.
    """
    if cache_dir:
        cache_path = Path(cache_dir) / ".pinterest_cache.json"
    else:
        cache_path = get_cache_file_path()
    
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # Falha de cache não deve quebrar fluxo

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
    cache_dir: str = "."  # Diretório para .pinterest_cache.json
    use_cache: bool = True  # Habilitar/desabilitar cache
    adaptive_workers: bool = False  # ONDA 5C: Ajuste dinâmico de workers
    rate_limiting: bool = False  # ONDA 5E: Rate limiting inteligente


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


def normalize_url(url_or_user: str) -> str:
    """Normaliza entrada do usuário para uma URL válida do Pinterest."""
    url = url_or_user.strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    
    # Se contém '.' no domínio mas s/ protocolo
    if "." in url.split("/")[0]:
        return f"https://{url}"
        
    # Remove '/' extras no início (ex: /pin/...)
    url = url.lstrip("/")
    
    # Se parece um pin path
    if url.startswith("pin/"):
        return f"{PINTEREST_BASE_URL}/{url}"
        
    # Assume ser um username (yuri_schmaltz) ou username/board
    return f"{PINTEREST_BASE_URL}/{url}"


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
        return (PINTEREST_BASE_URL + href).split('?')[0]
    return href.split('?')[0]


# ---------- Resolução de imagem ----------


def fetch_pin_media(pin_url: str, session: requests.Session, use_rate_limit: bool = False) -> str | None:
    """Pega a URL da mídia (vídeo se disponível, senão imagem) via meta tags do Pin."""
    # Aplicar rate limiting se habilitado
    if use_rate_limit:
        limiter = get_rate_limiter()
        limiter.acquire()
    
    try:
        r = session.get(pin_url, timeout=TIMEOUT_HTTP_GET)
        if r.status_code == 429 and use_rate_limit:
            limiter = get_rate_limiter()
            limiter.report_429()
            return None
        r.raise_for_status()
        if use_rate_limit:
            limiter = get_rate_limiter()
            limiter.report_success()
    except Exception:
        return None
    
    # 1. Tentar vídeo primeiro (og:video:secure_url)
    m = re.search(r'<meta[^>]+property=["\']og:video:secure_url["\'][^>]+content=["\']([^"\']+)', r.text, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video:secure_url["\']', r.text, re.I)
    
    # 2. Fallback para imagem (og:image)
    if not m:
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', r.text, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r.text, re.I)
        
    if not m:
        return None
        
    url = m.group(1)
    return url.split('?')[0]


def download_media(
    media_url: str,
    out_dir: str,
    session: requests.Session,
    filename_hint: str | None = None,
    max_retries: int = DOWNLOAD_MAX_RETRIES,
) -> bool:
    """Baixa mídia (imagem ou vídeo) e detecta extensão correta."""
    # Placeholder initial name based on hint or URL
    base_name = safe_name(filename_hint or media_url)
    dest_path = Path(out_dir) / base_name
    
    # Pre-check: se já existir um arquivo com o mesmo "stem" (ex: ID do pin) e tamanho > 0, 
    # podemos assumir que já foi baixado (mesmo que a extensão mude depois).
    # Isso evita uma requisição HTTP só para verificar o cabeçalho.
    if os.path.exists(out_dir):
        stem = Path(base_name).stem
        for existing_file in os.listdir(out_dir):
            if existing_file.startswith(stem) and os.path.getsize(os.path.join(out_dir, existing_file)) > 0:
                return True

    for attempt in range(max_retries + 1):
        try:
            with session.get(media_url, stream=True, timeout=TIMEOUT_IMAGE_DOWNLOAD) as r:
                r.raise_for_status()
                os.makedirs(out_dir, exist_ok=True)
                
                # Detectar extensão pelo Content-Type
                content_type = r.headers.get("Content-Type", "")
                ext = ".jpg"
                if "video/mp4" in content_type:
                    ext = ".mp4"
                elif "image/png" in content_type:
                    ext = ".png"
                elif "image/gif" in content_type:
                    ext = ".gif"
                elif "image/webp" in content_type:
                    ext = ".webp"
                
                final_filename = base_name if base_name.endswith(ext) else f"{base_name}{ext}"
                dest = os.path.join(out_dir, final_filename)
                
                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    return True
                    
                with open(dest, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1 << 15):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception:
            if attempt < max_retries:
                delay = DOWNLOAD_RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
            else:
                return False
    return False


# ---------- Coleta de links ----------


def _collect_pin_links_with_browser(
    page,
    board_url: str,
    manual_login: bool,
    scroll_pause: float,
    max_pins: int | None,
    manual_login_handler: Callable[[], None] | None = None,
) -> List[str]:
    """Lógica interna: coleta pins usando page já inicializado."""
    page.goto(board_url, wait_until="networkidle", timeout=TIMEOUT_PAGE_LOAD)

    if ("login" in page.url or "auth" in page.url) and not manual_login:
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
                sys.exit(1)

    try:
        page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_DOM_READY)
    except Exception:
        pass
    page.wait_for_timeout(1000)

    seen = set()
    stable_rounds = 0
    last_count = 0
    last_height = 0

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
            if u.startswith(f'{PINTEREST_BASE_URL}/pin/'):
                seen.add(u)

        if max_pins and len(seen) >= max_pins:
            break

        # Scroll detection inteligente: verificar altura da página
        if SCROLL_HEIGHT_CHECK:
            try:
                # Verificar se chegamos na seção "Mais como esse" para evitar poluição
                # E apenas se NÃO estamos encontrando novos pins (para evitar falso positivo)
                current_count = len(seen)
                if current_count == last_count:
                    has_more_like_this = page.evaluate(
                        '(() => { '
                        '  const headers = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6")); '
                        '  return headers.some(h => h.innerText.includes("Mais como esse") || h.innerText.includes("More like this")); '
                        '})()'
                    )
                    if has_more_like_this:
                        # Se encontramos o cabeçalho de recomendações E não temos novos pins, paramos
                         # Aumentar a chance de ser real: verificar se o scroll está lá embaixo
                        is_bottom = page.evaluate(
                            '(() => { '
                            '  return (window.innerHeight + window.scrollY) >= (document.body.offsetHeight - 500);'
                            '})()'
                        )
                        if is_bottom:
                            stable_rounds += 2 # Acelerar parada
                
                current_height = page.evaluate(
                    '(() => { const el = document.scrollingElement || document.documentElement || document.body; '
                    'return el ? el.scrollHeight : 0; })()'
                )
                if current_height == last_height and len(seen) == last_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_height = current_height
                    last_count = len(seen)
            except Exception:
                # Fallback para detecção por contagem
                if len(seen) == last_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_count = len(seen)
        else:
            # Modo legado: só por contagem
            if len(seen) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = len(seen)

        if stable_rounds >= SCROLL_STABLE_ROUNDS:
            break

        try:
            page.evaluate(
                '(() => { const el = document.scrollingElement || document.documentElement || document.body; '
                'if (!el) return; window.scrollTo(0, el.scrollHeight); })()'
            )
            # Aguarda um pouco mais em boards grandes para o Pinterest respirar
            page.wait_for_timeout(500)
        except Exception:
            print("  Aviso: falha ao rolar (DOM indisponível). Encerrando coleta deste quadro.")
            break

        page.wait_for_timeout(int(scroll_pause * 1000))

    return list(seen)[:max_pins] if max_pins else list(seen)


def collect_pin_links(
    board_url: str,
    headless: bool,
    manual_login: bool,
    scroll_pause: float,
    max_pins: int | None,
    manual_login_handler: Callable[[], None] | None = None,
    browser=None,
) -> List[str]:
    """Abre o quadro, rola a página e coleta URLs de Pins.
    
    Se browser for fornecido, reusa-o. Caso contrário, cria um temporário.
    """
    if browser is not None:
        # Reusa browser existente
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        try:
            return _collect_pin_links_with_browser(
                page, board_url, manual_login, scroll_pause, max_pins, manual_login_handler
            )
        finally:
            ctx.close()
    else:
        # Cria browser temporário (API legada)
        with sync_playwright() as p:
            browser_temp = p.chromium.launch(headless=headless)
            ctx = browser_temp.new_context(user_agent=UA)
            page = ctx.new_page()
            try:
                return _collect_pin_links_with_browser(
                    page, board_url, manual_login, scroll_pause, max_pins, manual_login_handler
                )
            finally:
                browser_temp.close()


def collect_board_urls(username_or_url: str, headless: bool, scroll_pause: float, browser=None) -> List[BoardMetadata]:
    """Coleta URLs e metadados de todos os quadros públicos do usuário.
    
    Se browser for fornecido, reusa-o. Caso contrário, cria um temporário.
    """
    m = USER_BOARDS_RE.match(username_or_url.strip())
    if m:
        username = m.group(1)
    else:
        username = username_or_url.strip().strip('/')

    candidates = [
        f"{PINTEREST_BASE_URL}/{username}/boards/",
        f"{PINTEREST_BASE_URL}/{username}/",
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

    def _collect_with_page(page) -> List[BoardMetadata]:
        """Helper interno para coletar boards usando page fornecido."""
        seen_urls = set()
        results: List[BoardMetadata] = []
        
        for url in candidates:
            try:
                page.goto(url, wait_until="networkidle", timeout=TIMEOUT_PAGE_LOAD)
                page.wait_for_timeout(1500)

                stable_rounds = 0
                last_count = 0
                last_height = 0

                for _ in range(200):
                    # Extrair objetos com metadados via JS
                    boards_data = page.evaluate(
                        f"""(username) => {{
                            const results = [];
                            const exclude = {list(exclude)};
                            const els = document.querySelectorAll('a[href]');
                            
                            els.forEach(el => {{
                                const href = el.getAttribute("href");
                                if (!href) return;
                                
                                // Extrair partes do path: /<user>/<board>/
                                const parts = href.split('/').filter(Boolean);
                                if (parts.length === 2 && parts[0].toLowerCase() === username.toLowerCase()) {{
                                    const board = parts[1];
                                    if (exclude.includes(board.toLowerCase()) || board.startsWith('_')) return;
                                    
                                    const fullUrl = "https://www.pinterest.com/" + parts[0] + "/" + parts[1] + "/";
                                    
                                    // Tentar encontrar número de pins
                                    let pins = "";
                                    try {{
                                        const text = el.innerText;
                                        // Regex para pegar apenas a contagem de pins: "10 Pins", "1,5 mil Pins", etc.
                                        const match = text.match(/([\\d,.]+\s*(?:mil|mi|k|m|pins|pin)\s*(?:Pins|Pin)?)/i);
                                        if (match) pins = match[0].trim();
                                    }} catch(e) {{}}
                                    
                                    // Tentar encontrar título usando data-test-id se possível
                                    let title = board;
                                    try {{
                                        const h2 = el.querySelector('h2, [data-test-id="board-card-title"]');
                                        if (h2) title = h2.innerText.trim();
                                        else {{
                                            title = el.innerText.split('\\n')[0].trim() || board;
                                        }}
                                    }} catch(e) {{}}
                                    
                                    // Tentar encontrar thumbnail
                                    let thumb = "";
                                    const img = el.querySelector('img');
                                    if (img) thumb = img.getAttribute('src') || "";
                                    
                                    results.push({{url: fullUrl, title: title, thumbnail_url: thumb, pin_count: pins}});
                                }}
                            }});
                            return results;
                        }}""",
                        username
                    )
                    
                    for b in boards_data:
                        if b['url'] not in seen_urls:
                            seen_urls.add(b['url'])
                            results.append(b)

                    # Scroll detection inteligente
                    if SCROLL_HEIGHT_CHECK:
                        try:
                            current_height = page.evaluate(
                                '(() => { const el = document.scrollingElement || document.documentElement || document.body; '
                                'return el ? el.scrollHeight : 0; })()'
                            )
                            if current_height == last_height and len(results) == last_count:
                                stable_rounds += 1
                            else:
                                stable_rounds = 0
                                last_height = current_height
                                last_count = len(results)
                        except Exception:
                            if len(results) == last_count:
                                stable_rounds += 1
                            else:
                                stable_rounds = 0
                                last_count = len(results)
                    else:
                        if len(results) == last_count:
                            stable_rounds += 1
                        else:
                            stable_rounds = 0
                            last_count = len(results)

                    if stable_rounds >= SCROLL_STABLE_ROUNDS:
                        break

                    try:
                        page.evaluate(
                            '(() => { const el = document.scrollingElement || document.documentElement || document.body; '
                            'if (!el) return; window.scrollTo(0, el.scrollHeight); })()'
                        )
                    except Exception:
                        break

                    page.wait_for_timeout(int(scroll_pause * 1000))

                if results:
                    break
            except Exception:
                continue
        return results

    if browser is not None:
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        try:
            return _collect_with_page(page)
        finally:
            ctx.close()
    else:
        with sync_playwright() as p:
            browser_temp = p.chromium.launch(headless=headless)
            ctx = browser_temp.new_context(user_agent=UA)
            page = ctx.new_page()
            try:
                return _collect_with_page(page)
            finally:
                browser_temp.close()


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
    use_cache: bool = True,
    adaptive: bool = False,
    rate_limiting: bool = False,
) -> Dict[str, str]:
    emit = emit or (lambda *_: None)
    logger = get_logger()
    
    # Initialize adaptive manager if enabled
    if adaptive:
        manager = get_adaptive_manager(min_workers=4, max_workers=workers)
        actual_workers = manager.current_workers
    else:
        manager = None
        actual_workers = workers

    links = list(pin_links)
    total_links = len(links)
    emit("resolve_start", {"total": total_links})

    # Log phase start
    logger.start_phase("resolve_images")

    # Carregar cache existente
    cache = load_pin_cache() if use_cache else {}
    out: Dict[str, str] = {}
    to_fetch: List[str] = []

    # Verificar quais pins já estão em cache
    for link in links:
        if link in cache:
            out[link] = cache[link]
        else:
            to_fetch.append(link)

    processed = len(out)  # Iniciar contagem a partir dos já em cache
    cache_hits = len(out)

    # Se tudo está em cache, retornar rápido
    if not to_fetch:
        emit("resolve_complete", {"found": len(out), "total": total_links, "from_cache": len(out)})
        logger.end_phase("resolve_images", count=len(out), message=f"Todos os {len(out)} pins em cache")
        return out

    def work(link: str) -> tuple[str, str | None]:
        start_time = time.time()
        img = fetch_pin_media(link, session, use_rate_limit=rate_limiting)
        if not img:
            mobile = link.replace("www.pinterest.com", "br.pinterest.com")
            img = fetch_pin_media(mobile, session, use_rate_limit=rate_limiting)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Record metrics if adaptive
        if manager:
            if img:
                manager.record_success(latency_ms)
            else:
                manager.record_failure()
        
        return link, img

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        for idx, (link, img) in enumerate(ex.map(work, to_fetch), 1):
            processed += 1
            if img:
                out[link] = img
                cache[link] = img  # Atualizar cache com novo resultado
            
            # Adjust workers every 10 operations (if adaptive)
            if manager and idx % 10 == 0:
                new_workers = manager.adjust_workers()
                if new_workers != actual_workers:
                    actual_workers = new_workers
                    logger.info("resolve_images", f"Workers ajustados para {new_workers}", count=new_workers)
            
            emit("resolve_progress", {"current": processed, "total": total_links})

    # Salvar cache atualizado em disco
    if use_cache:
        save_pin_cache(cache)
    
    # Save adaptive metrics if enabled
    if manager:
        manager.save_metrics()
        summary = manager.get_summary()
        logger.info("resolve_images", f"Adaptive: {summary['current_workers']} workers final, {summary['success_rate']:.1%} success", count=summary['current_workers'])

    resolved_count = len(out)
    logger.end_phase("resolve_images", count=resolved_count, message=f"Resolvidas {resolved_count} imagens (cache: {cache_hits})")
    emit("resolve_complete", {"found": len(out), "total": total_links, "from_cache": cache_hits})
    return out


def download_board(
    board_url: str,
    options: DownloadOptions,
    session: requests.Session | None = None,
    status_cb: StatusCallback | None = None,
    manual_login_handler: Callable[[str], None] | None = None,
    browser_shared=None,
) -> BoardDownloadResult:
    board_url = normalize_url(board_url)
    emit = status_cb or (lambda *_: None)
    logger = get_logger()
    session = session or create_session()

    # Log phase start
    logger.start_phase("download_board")
    display_url = urllib.parse.unquote(board_url)
    logger.info("download_board", f"Iniciando download: {display_url}", board_url=board_url)

    target_dir = out_dir_for(board_url, options.out_root)

    emit("board_start", {"board_url": display_url, "output_dir": target_dir})
    emit("log", {"message": f"[BOARD] {display_url}"})
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
        browser=browser_shared,
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
        logger.warn("download_board", "Nenhum pin encontrado", board_url=board_url)
        logger.end_phase("download_board", count=0, message="Nenhum pin encontrado")
        return BoardDownloadResult(board_url, 0, 0, target_dir)

    emit("pins_collected", {"board_url": board_url, "count": len(pin_links)})
    emit(
        "log",
        {"message": f"  [2/3] Resolvendo imagem grande de {len(pin_links)} pins (paralelo, cache={'ativado' if options.use_cache else 'desativado'})…"},
    )
    pin_img = resolve_images(pin_links, session=session, workers=options.workers, emit=emit, use_cache=options.use_cache, adaptive=options.adaptive_workers, rate_limiting=options.rate_limiting)

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
        logger.warn("download_board", "Nenhuma imagem resolvida", board_url=board_url, count=len(pin_links))
        logger.end_phase("download_board", count=0, message="Nenhuma imagem resolvida")
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
            ex.submit(download_media, img_url, target_dir, session, filename_hint=link)
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

    logger.end_phase("download_board", count=ok, message=f"Baixadas {ok}/{total} imagens")
    return BoardDownloadResult(board_url, ok, total, target_dir)


def download_user_boards(
    username_or_url: str,
    options: DownloadOptions,
    status_cb: StatusCallback | None = None,
    manual_login_handler: Callable[[str], None] | None = None,
) -> List[BoardDownloadResult]:
    username_or_url = normalize_url(username_or_url)
    display_name = urllib.parse.unquote(username_or_url)
    emit = status_cb or (lambda *_: None)
    logger = get_logger()
    
    # Log phase start
    logger.start_phase("download_user_boards")
    logger.info("download_user_boards", f"Iniciando downloads do usuário: {display_name}", board_url=username_or_url)
    emit("log", {"message": f"[USER] {display_name}"})
    
    # Criar browser uma única vez para todas as operações
    with sync_playwright() as p:
        browser_shared = p.chromium.launch(headless=options.headless)
        try:
            emit("log", {"message": "Coletando quadros públicos do usuário…"})
            boards = collect_board_urls(
                username_or_url,
                headless=options.headless,
                scroll_pause=options.scroll_pause,
                browser=browser_shared,
            )

            if not boards:
                emit("log", {"message": "Nenhum quadro público encontrado para o usuário."})
                logger.warn("download_user_boards", "Nenhum quadro público encontrado", board_url=username_or_url)
                logger.end_phase("download_user_boards", count=0, message="Nenhum quadro encontrado")
                return []

            emit("boards_found", {"boards": boards})
            emit("log", {"message": f"Encontrados {len(boards)} quadros. Iniciando downloads…"})
            logger.info("download_user_boards", f"Encontrados {len(boards)} quadros", board_url=username_or_url, count=len(boards))

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
                        browser_shared=browser_shared,
                    )
                    results[board] = res
                    emit("overall_progress", {"current": idx, "total": len(boards)})
            else:
                # Nota: modo paralelo (boards_workers > 1) não pode reusar browser
                # pois Playwright não é thread-safe. Cada worker criará seu próprio browser.
                def worker(board_url: str) -> BoardDownloadResult:
                    return download_board(
                        board_url,
                        options,
                        session=None,
                        status_cb=emit,
                        manual_login_handler=manual_login_handler,
                        browser_shared=None,  # Sem browser compartilhado em modo paralelo
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
            
            # Log phase end
            total_downloaded = sum(r.downloaded for r in ordered_results)
            logger.end_phase("download_user_boards", count=total_downloaded, message=f"Baixadas {total_downloaded} imagens de {len(ordered_results)} quadros")
            return ordered_results
        finally:
            browser_shared.close()


# ---------- CLI ----------


def _cli_status_printer(stage: str, data: Dict) -> None:
    if stage == "log":
        print(data.get("message", ""))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Baixa imagens de TODOS os quadros públicos de um usuário do Pinterest."
    )
    ap.add_argument(
        "user",
        help="Usuário do Pinterest para baixar todos os quadros (ex.: yuri_schmaltz ou URL do perfil)",
    )
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
    ap.add_argument(
        "--cache-dir",
        type=str,
        default=".",
        help="Diretório para armazenar cache de pins (default: .)",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="Desabilita cache de metadados de pins (sempre refetch)",
    )
    ap.add_argument(
        "--json-log",
        action="store_true",
        help="Habilita logging estruturado em JSON com timestamps",
    )
    ap.add_argument(
        "--log-file",
        type=str,
        default="download_log.json",
        help="Arquivo para salvar logs JSON (default: download_log.json)",
    )
    ap.add_argument(
        "--adaptive-workers",
        action="store_true",
        help="Ativa ajuste dinâmico de workers baseado em CPU/RAM (ONDA 5C)",
    )
    ap.add_argument(
        "--rate-limiting",
        action="store_true",
        help="Ativa limitação inteligente de requisições (ONDA 5E)",
    )
    args = ap.parse_args()

    if not args.user:
        ap.print_help()
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)

    # Initialize logger if JSON logging is enabled
    if args.json_log:
        logger = get_logger(output_file=args.log_file, enabled=True)
    else:
        logger = get_logger(enabled=False)

    options = DownloadOptions(
        out_root=args.out,
        headless=not args.headful,
        manual_login=args.manual_login,
        max_pins=args.max_pins,
        scroll_pause=args.scroll_pause,
        workers=args.workers,
        boards_workers=args.boards_workers,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
        adaptive_workers=args.adaptive_workers,
        rate_limiting=args.rate_limiting,
    )

    total_ok = 0
    total_all = 0

    results = download_user_boards(args.user, options, status_cb=_cli_status_printer)
    if not results:
        sys.exit(5)
    for res in results:
        total_ok += res.downloaded
        total_all += res.total

    print(f"\n==> TOTAL: {total_ok}/{total_all} imagens baixadas.")

    # Save JSON logs if enabled
    if args.json_log:
        logger = get_logger()
        logger.save()
        print(f"\nLogs JSON salvos em: {args.log_file}")
    
    # Save rate limiting stats if enabled
    if args.rate_limiting:
        limiter = get_rate_limiter()
        stats = limiter.get_stats()
        print(f"\n==> RATE LIMITING:")
        print(f"  Total requests: {stats['total_requests']}")
        print(f"  429 errors: {stats['total_429s']}")
        print(f"  Backoff time: {stats['backoff_seconds']:.1f}s")
        limiter.save_stats("rate_limit_stats.json")
        print(f"  Stats salvas em: rate_limit_stats.json")


if __name__ == "__main__":
    main()
