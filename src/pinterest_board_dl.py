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
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, TypedDict

import requests
from playwright.sync_api import sync_playwright

from adaptive_workers import AdaptiveWorkerManager, get_adaptive_manager
from app_version import get_version_banner
from json_logger import get_logger
from rate_limiter import get_rate_limiter


class PrivateProfileError(Exception):
    """Raised when trying to access a private Pinterest profile without login."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            f"O perfil '{username}' é privado. " "Marque a opção 'Login Manual (perfis privados)' e tente novamente."
        )


class BoardMetadata(TypedDict):
    url: str
    title: str
    thumbnail_url: str
    pin_count: str
    pin_count_int: int | None


class PinMetadata(TypedDict, total=False):
    id: str
    url: str
    image_url: str
    title: str
    description: str


# ---------- Config ----------
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
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
SCROLL_STABLE_ROUNDS = 20  # Aumentado para 20 para ser mais resiliente a lag e popups
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
            data = json.loads(cache_path.read_text())
            # Um cache corrompido (ou escrito por outra versão) não pode
            # quebrar o contrato Dict[str, str] do restante do código.
            return data if isinstance(data, dict) else {}
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
    base = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1].split("?")[0]
    if not base or "." not in base:
        base = hashlib.sha1(url.encode()).hexdigest() + ".jpg"
    return base


def slugify(name: str) -> str:
    """Sanitiza componente de caminho preservando Unicode."""
    if not isinstance(name, str):
        name = str(name)
    s = urllib.parse.unquote(name)
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u00a0", " ")
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("/", "／").replace("\x00", "")
    return s or "sem_nome"


def parse_pin_count(count_str: str) -> int | None:
    """Converte strings de contagem do Pinterest (ex: '1,2 mil', '1.2k', '10 pins') em int."""
    if not count_str:
        return None

    # Limpeza básica
    s = count_str.strip().lower()
    s = s.strip(",")
    s = s.replace("pins", "").replace("pin", "").strip()

    if not s:
        return None

    try:
        # Lidando com multiplicadores
        multiplier = 1
        has_suffix = False
        if "mil" in s or "k" in s:
            multiplier = 1000
            s = s.replace("mil", "").replace("k", "").strip()
            has_suffix = True
        elif "mi" in s or "m" in s:
            multiplier = 1000000
            s = s.replace("mi", "").replace("m", "").strip()
            has_suffix = True

        if has_suffix:
            # Com sufixo, '.' ou ',' são separadores decimais (ex: 1,2 mil = 1.2 * 1000)
            s = s.replace(",", ".")
        else:
            # Sem sufixo, '.' ou ',' são provavelmente separadores de milhar (ex: 1.000 = 1000)
            # Removemos tudo que não for dígito
            s = re.sub(r"[.,]", "", s)

        # Tentar converter
        val = float(s)
        return int(val * multiplier)
    except Exception:
        return None


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
    parts = [x for x in p.path.split("/") if x]
    user = urllib.parse.unquote(parts[0]) if len(parts) >= 1 else "user"
    board = urllib.parse.unquote(parts[1]) if len(parts) >= 2 else "board"
    return user, board


def out_dir_for(board_url: str, out_root: str) -> str:
    user, board = split_user_board_from_url(board_url)
    return os.path.join(out_root, slugify(user), slugify(board))


def _abs_url(href: str) -> str:
    if href.startswith("http"):
        return href.split("?")[0]
    if href.startswith("/"):
        return (PINTEREST_BASE_URL + href).split("?")[0]
    return href.split("?")[0]


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
    return url.split("?")[0]


def _detect_media_extension(content_type: str) -> str:
    """Mapeia Content-Type HTTP para a extensão de arquivo correspondente."""
    if "video/mp4" in content_type:
        return ".mp4"
    if "image/png" in content_type:
        return ".png"
    if "image/gif" in content_type:
        return ".gif"
    if "image/webp" in content_type:
        return ".webp"
    return ".jpg"


def _is_media_already_downloaded(out_dir: str, base_name: str) -> bool:
    """Verifica se um arquivo com o mesmo stem já existe e tem tamanho > 0."""
    if not os.path.exists(out_dir):
        return False
    stem = Path(base_name).stem
    for existing_file in os.listdir(out_dir):
        if existing_file.startswith(stem):
            filepath = os.path.join(out_dir, existing_file)
            if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                return True
    return False


def download_media(
    media_url: str,
    out_dir: str,
    session: requests.Session,
    filename_hint: str | None = None,
    max_retries: int = DOWNLOAD_MAX_RETRIES,
) -> bool:
    """Baixa mídia (imagem ou vídeo) e detecta extensão correta."""
    base_name = safe_name(filename_hint or media_url)

    if _is_media_already_downloaded(out_dir, base_name):
        return True

    for attempt in range(max_retries + 1):
        try:
            with session.get(media_url, stream=True, timeout=TIMEOUT_IMAGE_DOWNLOAD) as r:
                r.raise_for_status()
                os.makedirs(out_dir, exist_ok=True)

                ext = _detect_media_extension(r.headers.get("Content-Type", ""))
                final_filename = base_name if base_name.endswith(ext) else f"{base_name}{ext}"
                dest = os.path.join(out_dir, final_filename)

                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    return True

                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 15):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception:
            if attempt < max_retries:
                delay = DOWNLOAD_RETRY_DELAY * (2**attempt)
                time.sleep(delay)
            else:
                return False
    return False


# ---------- Coleta de links ----------


def _pin_metadata_from_payload(pin: dict) -> PinMetadata | None:
    """Converte um payload de pin do Pinterest em metadados normalizados.

    Aceita tanto o formato antigo (`id` + `images.orig`) quanto o GraphQL
    (`entityId` + `images_orig`/`images_736x`), porque a mesma função
    agora serve aos dois caminhos de resposta.

    Devolve None quando o payload nao tem id ou nao tem imagem -- nesse
    caso nao ha nada de util para baixar.
    """
    pin_id = str(pin.get("entityId") or pin.get("id") or "")
    if not pin_id:
        return None

    # O GraphQL achata as imagens no proprio objeto; o formato antigo as
    # aninha em "images". Nos dois, a preferencia e a maior resolucao.
    flat = pin.get("images_orig") or pin.get("images_736x") or pin.get("images_474x")
    if flat:
        image_url = flat.get("url")
    else:
        images = pin.get("images") or {}
        best = images.get("orig") or images.get("736x") or {}
        image_url = best.get("url")

    if not image_url:
        return None

    pin_url = f"{PINTEREST_BASE_URL}/pin/{pin_id}/"
    return {
        "id": pin_id,
        "url": pin_url,
        "image_url": image_url,
        "title": pin.get("title") or pin.get("gridTitle") or pin.get("grid_title", ""),
        "description": pin.get("description", ""),
    }


def _looks_like_pin(obj: dict) -> bool:
    """Um objeto do GraphQL tem forma de pin?

    graphQL aninha os pins em varios niveis, entao a busca e feita por
     forma, nao por posicao na arvore.
    """
    if not str(obj.get("entityId") or obj.get("id") or ""):
        return False
    return bool(obj.get("images") or obj.get("images_orig") or obj.get("images_736x") or obj.get("images_474x"))


def _find_pins_in_graphql(obj) -> List[dict]:
    """Acha todos os payloads de pin dentro de uma resposta GraphQL.

    A resposta do GraphQL muda de forma conforme o endpoint, entao a
    busca e recursiva: qualquer dict que tenha id e imagem conta como
    pin, e seus valores sao vasculhados tambem.
    """
    found: List[dict] = []
    if isinstance(obj, list):
        for item in obj:
            found.extend(_find_pins_in_graphql(item))
        return found
    if not isinstance(obj, dict):
        return found

    if _looks_like_pin(obj):
        found.append(obj)

    for value in obj.values():
        if isinstance(value, (dict, list)):
            found.extend(_find_pins_in_graphql(value))
    return found


def _pins_from_resource_payload(data: dict) -> List[dict]:
    """Extrai a lista de pins de uma resposta `resource/...`."""
    if "resource_response" in data:
        payload = data["resource_response"]
        if not isinstance(payload, dict):
            return []
        data_list = payload.get("data", [])
    elif "data" in data:
        data_list = data["data"]
    else:
        return []

    if not isinstance(data_list, list):
        return []
    return [pin for pin in data_list if isinstance(pin, dict)]


def _collect_pin_metadata(response) -> List[PinMetadata]:
    """Extrai metadados de pins de uma resposta de rede do Pinterest.

    Devolve a lista do que deu para extrair. Uma resposta que nao seja
    do Pinterest, ou que nao seja JSON, devolve lista vazia -- nunca
    levanta excecao, porque um erro aqui nao pode derrubar a coleta.
    """
    url = getattr(response, "url", "") or ""
    is_resource = (
        "resource/BoardFeedResource/get" in url
        or "resource/UserPinsResource/get" in url
        or "resource/BoardResource/get" in url
    )
    is_graphql = "/_/graphql/" in url

    if not (is_resource or is_graphql):
        return []

    try:
        data = response.json()
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    if is_graphql:
        candidates = _find_pins_in_graphql(data)
    else:
        candidates = _pins_from_resource_payload(data)

    metas: List[PinMetadata] = []
    for pin in candidates:
        meta = _pin_metadata_from_payload(pin)
        if meta is not None:
            metas.append(meta)
    return metas


def _pin_from_pws_dict(d: dict) -> PinMetadata | None:
    """Extrai metadados de pin a partir de um fragmento de dicionário PWS."""
    pid = str(d.get("entityId") or d.get("id") or "")
    imgs_dict = d.get("images", {})
    flat_orig = d.get("images_orig") or d.get("images_736x") or d.get("images_474x")
    if not (pid and (imgs_dict or flat_orig)):
        return None

    iurl = None
    if flat_orig:
        iurl = flat_orig.get("url")
    elif imgs_dict:
        orig = imgs_dict.get("orig", {}) or imgs_dict.get("736x", {})
        iurl = orig.get("url")

    if not iurl:
        return None

    purl = f"{PINTEREST_BASE_URL}/pin/{pid}/"
    return {
        "id": pid,
        "url": purl,
        "image_url": iurl,
        "title": d.get("title") or d.get("gridTitle") or d.get("grid_title", ""),
    }


def _walk_pws_data(data: Any, out_cache: Dict[str, PinMetadata]) -> None:
    """Navega recursivamente pela estrutura do PWS_DATA coletando pins."""
    if isinstance(data, list):
        for item in data:
            _walk_pws_data(item, out_cache)
    elif isinstance(data, dict):
        meta = _pin_from_pws_dict(data)
        if meta and meta["url"] not in out_cache:
            out_cache[meta["url"]] = meta
        for v in data.values():
            if isinstance(v, (dict, list)):
                _walk_pws_data(v, out_cache)


def _extract_pws_metadata_from_page(page, metadata_cache: Dict[str, PinMetadata]) -> None:
    """Tenta extrair metadados da página inicial contidos no script __PWS_DATA__."""
    try:
        pws_data_raw = page.evaluate(
            '() => { var el = document.getElementById("__PWS_DATA__") || document.querySelector("script[id=\'__PWS_DATA__\']"); return el ? el.innerText : null; }'
        )
        if pws_data_raw:
            pws_json = json.loads(pws_data_raw)
            _walk_pws_data(pws_json, metadata_cache)
    except Exception:
        pass


def _dismiss_popups_if_stalled(page, stable_rounds: float) -> None:
    """Tenta fechar modais flutuantes e popups do Pinterest quando o scroll começa a estagnar."""
    try:
        if stable_rounds > 2:
            page.keyboard.press("Escape")
        page.evaluate(
            "() => { "
            '  const closes = Array.from(document.querySelectorAll(\'[aria-label="Close"], [aria-label="Fechar"], button\')); '
            '  closes.forEach(c => { if(c.innerText === "✕" || c.innerText === "X") c.click(); }); '
            "}"
        )
    except Exception:
        pass


def _scrape_pin_hrefs_from_page(page, seen: set[str]) -> None:
    """Extrai links normalizados de pins a partir do DOM atual."""
    try:
        hrefs = page.eval_on_selector_all(
            'a[href^="/pin/"]',
            'els => Array.from(new Set(els.map(e => e.getAttribute("href"))))',
        )
        for h in hrefs:
            if not h:
                continue
            u = _abs_url(h.split("?")[0])
            u = u.replace("://br.pinterest.com/", "://www.pinterest.com/")
            if u.startswith(f"{PINTEREST_BASE_URL}/pin/"):
                seen.add(u)
    except Exception:
        pass


def _evaluate_board_scroll_progress(
    page,
    seen_count: int,
    stable_rounds: float,
    last_count: int,
    last_height: int,
) -> tuple[float, int, int, bool]:
    """Avalia o progresso do scroll do quadro e retorna o novo estado de estabilidade."""
    has_more_like_this = False
    if SCROLL_HEIGHT_CHECK:
        try:
            has_more_like_this = bool(
                page.evaluate(
                    "(() => { "
                    "  const text = document.body.innerText; "
                    '  return text.includes("Mais como esse") || text.includes("More like this"); '
                    "})()"
                )
            )
            current_height = page.evaluate(
                "(() => { const el = document.scrollingElement || document.documentElement || document.body; "
                "return el ? el.scrollHeight : 0; })()"
            )
            is_bottom = bool(
                page.evaluate(
                    "(() => { "
                    "  return (window.innerHeight + window.scrollY) >= (document.body.offsetHeight - 800);"
                    "})()"
                )
            )
            stable_rounds, last_count, last_height = _compute_scroll_stability(
                stable_rounds,
                last_count,
                last_height,
                seen_count,
                current_height,
                has_more_like_this,
                is_bottom,
            )
            return stable_rounds, last_count, last_height, has_more_like_this
        except Exception:
            pass

    if seen_count == last_count:
        stable_rounds += 1
    else:
        stable_rounds = 0
        last_count = seen_count
    return stable_rounds, last_count, last_height, has_more_like_this


def _prepare_board_page_for_scraping(
    page,
    manual_login: bool,
    manual_login_handler: Callable[[], None] | None = None,
) -> None:
    """Prepara a página de quadro para scraping, tratando login manual e espera de elementos."""
    if manual_login:
        if manual_login_handler:
            manual_login_handler()
        elif sys.stdin.isatty():
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
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    try:
        page.wait_for_selector('a[href^="/pin/"]', state="visible", timeout=10000)
    except Exception:
        pass

    page.wait_for_timeout(3000)


def _collect_pin_links_with_browser(
    page,
    board_url: str,
    manual_login: bool,
    scroll_pause: float,
    max_pins: int | None,
    manual_login_handler: Callable[[], None] | None = None,
    target_pin_count: int | None = None,
) -> List[str]:
    """Lógica interna: coleta pins usando page já inicializado."""
    page.goto(board_url, wait_until="load", timeout=TIMEOUT_PAGE_LOAD)

    if ("login" in page.url or "auth" in page.url) and not manual_login:
        return []

    # ONDA 7: Metadata Buffer
    metadata_cache: Dict[str, PinMetadata] = {}

    def handle_response(response):
        """Intercepta respostas XHR/Fetch para extrair metadados dos pins."""
        for meta in _collect_pin_metadata(response):
            metadata_cache[meta["url"]] = meta

    page.on("response", handle_response)

    _prepare_board_page_for_scraping(page, manual_login, manual_login_handler)

    seen: set[str] = set()
    # float, não int: o scroll dá "crédito parcial" (+0.5) quando a altura da
    # página muda mas a contagem de pins não (linha do stable_rounds += 0.5).
    stable_rounds: float = 0
    last_count = 0
    last_height = 0

    while True:
        _dismiss_popups_if_stalled(page, stable_rounds)
        _scrape_pin_hrefs_from_page(page, seen)

        if max_pins and len(seen) >= max_pins:
            break

        stable_rounds, last_count, last_height, has_more_like_this = _evaluate_board_scroll_progress(
            page,
            seen_count=len(seen),
            stable_rounds=stable_rounds,
            last_count=last_count,
            last_height=last_height,
        )

        if stable_rounds >= SCROLL_STABLE_ROUNDS:
            if target_pin_count and len(seen) < target_pin_count:
                if not has_more_like_this and stable_rounds < (SCROLL_STABLE_ROUNDS * 2):
                    stable_rounds -= 1
                    page.wait_for_timeout(2000)
                    continue
            break

        try:
            page.evaluate(
                "(() => { const el = document.scrollingElement || document.documentElement || document.body; "
                "if (!el) return; window.scrollTo(0, el.scrollHeight); })()"
            )
            # Aguarda um pouco mais em boards grandes para o Pinterest respirar
            wait_time = 500
            if stable_rounds > 5:
                wait_time = 1000  # Ser mais paciente se estiver "travado"
            page.wait_for_timeout(wait_time)
        except Exception:
            break

        page.wait_for_timeout(int(scroll_pause * 1000))

    _extract_pws_metadata_from_page(page, metadata_cache)

    # Atualizar cache global temporário
    _intercepted_metadata.update(metadata_cache)

    return list(seen)[:max_pins] if max_pins else list(seen)


# Singleton para armazenar metadados interceptados durante a sessão de coleta
_intercepted_metadata: Dict[str, PinMetadata] = {}


def get_intercepted_metadata() -> Dict[str, PinMetadata]:
    return _intercepted_metadata


def clear_intercepted_metadata() -> None:
    _intercepted_metadata.clear()


def _compute_scroll_stability(
    stable_rounds: float,
    last_count: int,
    last_height: int,
    current_count: int,
    current_height: int,
    has_more_like_this: bool,
    is_bottom: bool,
) -> tuple[float, int, int]:
    """Atualiza o contador de estabilidade usado para decidir quando parar o scroll.

    Extraído de _collect_pin_links_with_browser para ser testável sem
    browser: a decisão é aritmética pura sobre o estado observado.

    Regras:
    - houve progresso (mais pins) -> zera o contador e memoriza o novo estado
    - sem progresso, com "Mais como esse" visível no fim da página -> conta 2
      (indício forte de que chegou ao fim)
    - sem progresso e altura igual -> conta 1
    - sem progresso e altura diferente -> conta 0,5 (crédito parcial: a página
      pode estar carregando outra coisa, ainda não é o fim)

    Retorna (stable_rounds, last_count, last_height).
    """
    if current_count == last_count:
        if has_more_like_this and is_bottom:
            stable_rounds += 2
        elif current_height == last_height:
            stable_rounds += 1
        else:
            stable_rounds += 0.5
    else:
        # Houve progresso! Resetar rounds
        stable_rounds = 0
        last_height = current_height
        last_count = current_count
    return stable_rounds, last_count, last_height


def _extract_boards_from_page(page, username: str, exclude: set[str]) -> List[BoardMetadata]:
    """Extrai os quadros do usuário da página já carregada.

    Separado de collect_board_urls para permitir teste com HTML local: a
    função depende apenas do DOM da página, não de onde ela veio. É o que
    permite testar a extração sem tocar a rede.
    """
    boards_data = page.evaluate(
        rf"""(username) => {{
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

                    // Tentar encontrar número de pins de forma mais precisa
                    let pins = "";
                    try {{
                        // Pegar o container de texto do board card
                        const text = el.innerText;
                        // Regex mais restrita: ignorar o título (que vem antes de quebras de linha ou espaços duplos)
                        // e ignorar sufixos de tempo (1d, 2h, etc)
                        const lines = text.split('\n').filter(l => l.trim());
                        for (const line of lines) {{
                            const match = line.match(/^([\d,.]+\s*(?:mil|mi|k|m|pins|pin))\s*$/i);
                            if (match) {{
                                pins = match[1].trim();
                                break;
                            }}
                        }}

                        // Fallback se não achou em linhas separadas
                        if (!pins) {{
                            const match = text.match(/([\d,.]+\s*(?:mil|mi|k|m|pins|pin))\s*(?:Pins|Pin)?/i);
                            if (match) pins = match[1].trim();
                        }}
                    }} catch(e) {{}}

                    // Tentar encontrar título usando data-test-id se possível
                    let title = board;
                    try {{
                        const titleEl = el.querySelector('h2, [data-test-id="board-card-title"]');
                        if (titleEl) {{
                            title = titleEl.innerText.trim();
                        }} else {{
                            // Fallback: primeira linha do texto
                            const firstLine = el.innerText.split('\n')[0].trim();
                            if (firstLine && !firstLine.match(/^\d/)) title = firstLine;
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
        username,
    )

    results: List[BoardMetadata] = []
    for b in boards_data:
        # Pre-parse pin count to int
        b["pin_count_int"] = parse_pin_count(b["pin_count"])
        results.append(b)
    return results


def collect_pin_links(
    board_url: str,
    headless: bool,
    manual_login: bool,
    scroll_pause: float,
    max_pins: int | None,
    manual_login_handler: Callable[[], None] | None = None,
    browser=None,
    target_pin_count: int | None = None,
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
                page,
                board_url,
                manual_login,
                scroll_pause,
                max_pins,
                manual_login_handler,
                target_pin_count=target_pin_count,
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
                    page,
                    board_url,
                    manual_login,
                    scroll_pause,
                    max_pins,
                    manual_login_handler,
                    target_pin_count=target_pin_count,
                )
            finally:
                browser_temp.close()


def _scroll_step_profile_boards(
    page,
    current_count: int,
    stable_rounds: int,
    last_count: int,
    last_height: int,
    scroll_pause: float,
) -> tuple[int, int, int, bool]:
    """Executa um passo de scroll na listagem de quadros de perfil e avalia estabilidade."""
    if SCROLL_HEIGHT_CHECK:
        try:
            current_height = page.evaluate(
                "(() => { const el = document.scrollingElement || document.documentElement || document.body; "
                "return el ? el.scrollHeight : 0; })()"
            )
            if current_height == last_height and current_count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_height = current_height
                last_count = current_count
        except Exception:
            if current_count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = current_count
    else:
        if current_count == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = current_count

    if stable_rounds >= SCROLL_STABLE_ROUNDS:
        return stable_rounds, last_count, last_height, True

    try:
        page.evaluate(
            "(() => { const el = document.scrollingElement || document.documentElement || document.body; "
            "if (!el) return; window.scrollTo(0, el.scrollHeight); })()"
        )
    except Exception:
        return stable_rounds, last_count, last_height, True

    page.wait_for_timeout(int(scroll_pause * 1000))
    return stable_rounds, last_count, last_height, False


def _prepare_profile_page(
    page,
    candidate_index: int,
    manual_login: bool,
    manual_login_handler: Callable[[], None] | None,
    username: str,
) -> None:
    """Trata login e verificação de perfil privado para cada URL candidata de perfil."""
    if manual_login and candidate_index == 0:
        if manual_login_handler:
            manual_login_handler()
        elif sys.stdin.isatty():
            print(
                "\n>>> Faça login na janela aberta." "\n>>> Volte ao terminal e pressione ENTER para continuar…",
                flush=True,
            )
            try:
                input()
            except KeyboardInterrupt:
                sys.exit(1)

    page.wait_for_timeout(1500)

    is_private = page.evaluate(
        "(() => {"
        '  const text = document.body.innerText || "";'
        '  return text.includes("This profile is private") || '
        '         text.includes("Este perfil é privado") || '
        '         text.includes("profile is private");'
        "})()"
    )
    if is_private and not manual_login:
        raise PrivateProfileError(username)


def collect_board_urls(
    username_or_url: str,
    headless: bool,
    scroll_pause: float,
    manual_login: bool = False,
    manual_login_handler: Callable[[], None] | None = None,
    browser=None,
) -> List[BoardMetadata]:
    """Coleta URLs e metadados de todos os quadros públicos do usuário.

    Se browser for fornecido, reusa-o. Caso contrário, cria um temporário.
    """
    m = USER_BOARDS_RE.match(username_or_url.strip())
    if m:
        username = m.group(1)
    else:
        username = username_or_url.strip().strip("/")

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

        for i, url in enumerate(candidates):
            try:
                page.goto(url, wait_until="load", timeout=TIMEOUT_PAGE_LOAD)

                _prepare_profile_page(page, i, manual_login, manual_login_handler, username)

                stable_rounds = 0
                last_count = 0
                last_height = 0

                for _ in range(200):
                    # Extrair objetos com metadados via JS
                    boards_data = _extract_boards_from_page(page, username, exclude)

                    for b in boards_data:
                        if b["url"] not in seen_urls:
                            seen_urls.add(b["url"])
                            results.append(b)

                    stable_rounds, last_count, last_height, should_stop = _scroll_step_profile_boards(
                        page,
                        current_count=len(results),
                        stable_rounds=stable_rounds,
                        last_count=last_count,
                        last_height=last_height,
                        scroll_pause=scroll_pause,
                    )
                    if should_stop:
                        break

                if results:
                    break
            except PrivateProfileError:
                raise
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


def _partition_links(
    links: Iterable[str],
    cache: Dict[str, str],
    intercepted: Dict[str, PinMetadata],
) -> tuple[Dict[str, str], List[str]]:
    """Separa os pins que já sabemos resolver dos que ainda vão ser buscados.

    O que foi interceptado durante a navegação tem prioridade sobre o
    cache: o metadado veio da página que o usuário está vendo agora, então
    é mais fresco que qualquer coisa guardada em disco.
    """
    out: Dict[str, str] = {}
    to_fetch: List[str] = []
    for link in links:
        if link in intercepted:
            out[link] = intercepted[link]["image_url"]
        elif link in cache:
            out[link] = cache[link]
        else:
            to_fetch.append(link)
    return out, to_fetch


def _count_cache_hits(out: Dict[str, str], intercepted: Dict[str, PinMetadata]) -> tuple[int, int]:
    """Quantos pins vieram do cache e quantos da interceptação."""
    intercept_hits = len([link for link in out if link in intercepted])
    cache_hits = len(out) - intercept_hits
    return cache_hits, intercept_hits


def _resolve_single_pin(
    link: str,
    session: requests.Session,
    use_rate_limit: bool,
    manager: AdaptiveWorkerManager | None = None,
) -> tuple[str, str | None]:
    """Resolve a imagem de um pin, com o fallback para o domínio mobile.

    O Pinterest responde diferente em `www` e `br`: quando a URL canônica
    falha, o domínio mobile costuma funcionar.
    """
    start_time = time.time()
    img = fetch_pin_media(link, session, use_rate_limit=use_rate_limit)
    if not img:
        mobile = link.replace("www.pinterest.com", "br.pinterest.com")
        img = fetch_pin_media(mobile, session, use_rate_limit=use_rate_limit)

    latency_ms = (time.time() - start_time) * 1000

    # Record metrics if adaptive
    if manager:
        if img:
            manager.record_success(latency_ms)
        else:
            manager.record_failure()

    return link, img


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
    intercepted = get_intercepted_metadata()

    # Verificar quais pins já estão em cache ou foram interceptados
    out, to_fetch = _partition_links(links, cache, intercepted)
    cache_hits, intercept_hits = _count_cache_hits(out, intercepted)

    processed = len(out)

    # Se tudo está em cache ou interceptado, retornar rápido
    if not to_fetch:
        emit(
            "resolve_complete",
            {"found": len(out), "total": total_links, "from_cache": cache_hits, "intercepted": intercept_hits},
        )
        logger.end_phase(
            "resolve_images",
            count=len(out),
            message=f"Todos os {len(out)} pins resolvidos (Intercept: {intercept_hits}, Cache: {cache_hits})",
        )
        return out

    def work(link: str) -> tuple[str, str | None]:
        return _resolve_single_pin(link, session, rate_limiting, manager)

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
        logger.info(
            "resolve_images",
            f"Adaptive: {summary['current_workers']} workers final, {summary['success_rate']:.1%} success",
            count=summary["current_workers"],
        )

    resolved_count = len(out)
    logger.end_phase(
        "resolve_images", count=resolved_count, message=f"Resolvidas {resolved_count} imagens (cache: {cache_hits})"
    )
    emit("resolve_complete", {"found": len(out), "total": total_links, "from_cache": cache_hits})
    return out


def _verify_downloaded_pins(pin_img: Dict[str, str], target_dir: str) -> tuple[int, list[str]]:
    """Confere no disco quais pins foram efetivamente gravados e quais faltam."""
    verified_ok = 0
    missing_pins = []
    for link in pin_img:
        stem = Path(safe_name(link)).stem
        if _is_media_already_downloaded(target_dir, stem):
            verified_ok += 1
        else:
            missing_pins.append(link)
    return verified_ok, missing_pins


def _retry_missing_pins(
    missing_links: list[str],
    target_dir: str,
    session: requests.Session,
    options: DownloadOptions,
    emit: StatusCallback,
) -> int:
    """Tenta resolver e baixar novamente os pins ausentes pós-download."""
    miss_pin_img = resolve_images(
        missing_links,
        session=session,
        workers=options.workers,
        emit=emit,
        use_cache=False,
        rate_limiting=options.rate_limiting,
    )
    recovered = 0
    with ThreadPoolExecutor(max_workers=options.workers) as ex:
        futs = [
            ex.submit(download_media, iurl, target_dir, session, filename_hint=link)
            for link, iurl in miss_pin_img.items()
        ]
        for fut in as_completed(futs):
            if fut.result():
                recovered += 1
    return recovered


def _handle_interactive_login(
    board_url: str,
    emit: StatusCallback,
    handler: Callable[[str], None] | None = None,
) -> None:
    """Notifica e aguarda login interativo do usuário se necessário."""
    emit("manual_login_required", {"board_url": board_url, "message": "Faça login e retorne para continuar."})
    if handler:
        handler(board_url)
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


def download_board(
    board_url: str | BoardMetadata,
    options: DownloadOptions,
    session: requests.Session | None = None,
    status_cb: StatusCallback | None = None,
    manual_login_handler: Callable[[str], None] | None = None,
    browser_shared=None,
) -> BoardDownloadResult:
    target_pin_count = None
    _board_url_str: str
    if isinstance(board_url, str):
        _board_url_str = board_url
    else:
        target_pin_count = board_url.get("pin_count_int")
        _board_url_str = board_url["url"]

    actual_board_url = normalize_url(_board_url_str)
    emit = status_cb or (lambda *_: None)
    logger = get_logger()
    session = session or create_session()

    # ONDA 7: Garantir que o cache de interceptação comece limpo para este board
    # (Ou acumulativo se for multi-board? Pinterest costuma misturar se não limpar)
    # Vamos manter acumulativo dentro de download_user_boards mas limpar aqui para single-board CLI
    if browser_shared is None:
        clear_intercepted_metadata()

    # Log phase start
    logger.start_phase("download_board")
    display_url = urllib.parse.unquote(actual_board_url)
    logger.info("download_board", f"Iniciando download: {display_url}", board_url=actual_board_url)

    target_dir = out_dir_for(actual_board_url, options.out_root)

    emit("board_start", {"board_url": display_url, "output_dir": target_dir})
    emit("log", {"message": f"[BOARD] {display_url}"})
    emit("log", {"message": "  [1/3] Coletando links dos pins…"})

    def handle_manual_login() -> None:
        _handle_interactive_login(actual_board_url, emit, manual_login_handler)

    pin_links = collect_pin_links(
        board_url=actual_board_url,
        headless=options.headless,
        manual_login=options.manual_login,
        scroll_pause=options.scroll_pause,
        max_pins=options.max_pins,
        manual_login_handler=handle_manual_login if options.manual_login else None,
        browser=browser_shared,
        target_pin_count=target_pin_count,
    )

    if not pin_links:
        emit("log", {"message": "  Nenhum pin encontrado (privado? login necessário?). Pulando."})
        emit(
            "board_complete",
            {
                "board_url": actual_board_url,
                "downloaded": 0,
                "total": 0,
                "output_dir": target_dir,
            },
        )
        emit("log", {"message": "  Concluído: 0/0 pins (pulado)"})
        logger.warn("download_board", "Nenhum pin encontrado", board_url=actual_board_url)
        logger.end_phase("download_board", count=0, message="Nenhum pin encontrado")
        return BoardDownloadResult(actual_board_url, 0, 0, target_dir)

    emit("pins_collected", {"board_url": actual_board_url, "count": len(pin_links)})
    emit(
        "log",
        {
            "message": f"  [2/3] Resolvendo imagem grande de {len(pin_links)} pins (paralelo, cache={'ativado' if options.use_cache else 'desativado'})…"
        },
    )
    pin_img = resolve_images(
        pin_links,
        session=session,
        workers=options.workers,
        emit=emit,
        use_cache=options.use_cache,
        adaptive=options.adaptive_workers,
        rate_limiting=options.rate_limiting,
    )

    if not pin_img:
        emit("log", {"message": "  Não foi possível resolver nenhuma imagem. Pulando."})
        emit(
            "board_complete",
            {
                "board_url": actual_board_url,
                "downloaded": 0,
                "total": 0,
                "output_dir": target_dir,
            },
        )
        logger.warn("download_board", "Nenhuma imagem resolvida", board_url=actual_board_url, count=len(pin_links))
        logger.end_phase("download_board", count=0, message="Nenhuma imagem resolvida")
        return BoardDownloadResult(actual_board_url, 0, 0, target_dir)

    emit(
        "log",
        {
            "message": f"  [3/3] Baixando {len(pin_img)} imagens em '{target_dir}' (paralelo)…",
        },
    )

    ok = 0
    total = len(pin_img)
    emit("download_start", {"board_url": actual_board_url, "total": total})

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
                    "board_url": actual_board_url,
                    "current": idx,
                    "total": total,
                    "downloaded": ok,
                },
            )

    verified_ok, missing_pins_links = _verify_downloaded_pins(pin_img, target_dir)

    if missing_pins_links:
        emit("log", {"message": f"  Retentativa direcionada para {len(missing_pins_links)} pins ausentes…"})
        recovered = _retry_missing_pins(
            missing_pins_links,
            target_dir=target_dir,
            session=session,
            options=options,
            emit=emit,
        )
        verified_ok += recovered

    # Status final de verificação
    status_msg = f"  Verificação: {verified_ok}/{total} pins efetivados no disco."
    if target_pin_count and verified_ok < target_pin_count:
        status_msg += f" (Esperado: {target_pin_count})"

    emit("log", {"message": status_msg})

    emit("log", {"message": f"  Concluído: {verified_ok}/{total}"})
    emit(
        "board_complete",
        {
            "board_url": actual_board_url,
            "downloaded": verified_ok,
            "total": total,
            "output_dir": target_dir,
            "verified": verified_ok,
            "expected": target_pin_count,
        },
    )

    logger.end_phase("download_board", count=verified_ok, message=f"Baixadas/Verificadas {verified_ok}/{total} imagens")
    return BoardDownloadResult(actual_board_url, verified_ok, total, target_dir)


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
        clear_intercepted_metadata()  # Limpar antes de começar batch
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
            logger.info(
                "download_user_boards",
                f"Encontrados {len(boards)} quadros",
                board_url=username_or_url,
                count=len(boards),
            )

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
                    results[res.board_url] = res
                    emit("overall_progress", {"current": idx, "total": len(boards)})
            else:
                # Nota: modo paralelo (boards_workers > 1) não pode reusar browser
                # pois Playwright não é thread-safe. Cada worker criará seu próprio browser.
                def worker(board_data: str | BoardMetadata) -> BoardDownloadResult:
                    return download_board(
                        board_data,
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

            ordered_results = [results[b["url"]] for b in boards if b["url"] in results]
            emit("user_complete", {"boards": boards, "results": ordered_results})

            # Log phase end
            total_downloaded = sum(r.downloaded for r in ordered_results)
            logger.end_phase(
                "download_user_boards",
                count=total_downloaded,
                message=f"Baixadas {total_downloaded} imagens de {len(ordered_results)} quadros",
            )
            return ordered_results
        finally:
            browser_shared.close()


# ---------- CLI ----------


def _cli_status_printer(stage: str, data: Dict) -> None:
    if stage == "log":
        print(data.get("message", ""))


def build_arg_parser() -> argparse.ArgumentParser:
    """Monta o parser de argumentos da CLI.

    Fica separado do `main()` para que os testes possam exercitar o
    parse sem disparar o download -- o `main()` abre o navegador e
    toca a rede, o que a suite nao faz.
    """
    ap = argparse.ArgumentParser(description="Baixa imagens de TODOS os quadros públicos de um usuário do Pinterest.")
    ap.add_argument(
        "user",
        nargs="?",
        help="Usuário do Pinterest para baixar todos os quadros (ou URL do perfil)",
    )
    ap.add_argument(
        "--user",
        dest="user_option",
        metavar="NOME",
        help="Usuário do Pinterest (alias do argumento posicional)",
    )
    ap.add_argument(
        "--version",
        action="version",
        version=get_version_banner(),
        help="Mostra a versão e sai",
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
    return ap


def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()

    # O usuario pode vir como posicional ou como --user. O README e os
    # guias antigos usam --user, a CLI original usava so o posicional --
    # os dois funcionam.
    user = args.user_option or args.user

    if not user:
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

    results = download_user_boards(user, options, status_cb=_cli_status_printer)
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
        print("\n==> RATE LIMITING:")
        print(f"  Total requests: {stats['total_requests']}")
        print(f"  429 errors: {stats['total_429s']}")
        print(f"  Backoff time: {stats['backoff_seconds']:.1f}s")
        limiter.save_stats("rate_limit_stats.json")
        print("  Stats salvas em: rate_limit_stats.json")


if __name__ == "__main__":
    main()
