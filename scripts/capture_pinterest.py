#!/usr/bin/env python3
"""Captura sanitizada de uma pagina real do Pinterest.

A captura existe para provar, contra o Pinterest de verdade, que os
seletores e os formatos de payload que o projeto assume continuam valendo.
Nada do que for capturado pode carregar dado de pessoa: o arquivo de
saida nao tem cookie, token, nome de usuario nem identificador de pin.

O uso e:

    python scripts/capture_pinterest.py https://www.pinterest.com/alice/board/ \\
        --out tests/fixtures/real/board

O resultado e um diretorio com a pagina, os payloads de rede e um
`manifest.json` que registra a data, a origem, o que foi observado e o
que a captura nao cobre.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Chave do PWS que carrega os dados da pagina.
PWS_RE = re.compile(r'(?is)<script\b[^>]*\bid\s*=\s*["\']__PWS_DATA__["\'][^>]*>(.*?)</script\s*>')
# Chaves que nunca podem ser gravadas: identificam a sessao ou a pessoa.
FORBIDDEN_KEYS = {
    "analysis_ua",
    "authorization",
    "cookie",
    "cookies",
    "csrf_token",
    "csrf_token_expires_at",
    "csp_nonce",
    "email",
    "facebook_token",
    "id_token",
    "impersonator_user_id",
    "password",
    "refresh_token",
    "session_id",
    "session_token",
    "set-cookie",
    "token",
    "unauth_id",
    "user_agent",
}
# Substrings que indicam que o payload carrega recomendacoes.
RECOMMENDATION_HINTS = ("recommend", "related", "more_like_this", "morelikethis", "suggest")
# Primeiros segmentos de caminho que nao sao usuario nem quadro. Sem esta
# lista o sanitizador trocaria `/resource/BoardFeedResource/get/` por um
# usuario e um quadro que nao existem.
RESERVED_PATHS = {
    "_",
    "api",
    "assets",
    "business",
    "categories",
    "cdn",
    "done",
    "download",
    "ideas",
    "login",
    "news_hub",
    "pin",
    "pinimg",
    "resource",
    "search",
    "secure",
    "settings",
    "signup",
    "static",
    "today",
    "topics",
    "v3",
    "widgets",
}
# Nomes que o proprio sanitizador usa. Eles nao podem ser trocados de novo.
PLACEHOLDER_RE = re.compile(r"^(?:USUARIO|QUADRO|PIN|MIDIA)_\d+$")
# Token em base64 no formato de JWT.
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_.\-]{20,}")
# Nonce ou hash de sessao.
HASH_RE = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)


@dataclass
class Sanitizer:
    """Troca identificadores e URLs por nomes estaveis e sem informacao real."""

    users: dict[str, str] = field(default_factory=dict)
    boards: dict[str, str] = field(default_factory=dict)
    pins: dict[str, str] = field(default_factory=dict)
    media: dict[str, str] = field(default_factory=dict)

    def _named(self, store: dict[str, str], prefix: str, name: str) -> str:
        if not name or PLACEHOLDER_RE.match(name):
            return name
        if name not in store:
            store[name] = f"{prefix}_{len(store) + 1:03d}"
        return store[name]

    def user(self, name: str) -> str:
        return self._named(self.users, "USUARIO", name)

    def board(self, name: str) -> str:
        return self._named(self.boards, "QUADRO", name)

    def pin(self, identifier: str) -> str:
        return self._named(self.pins, "PIN", identifier)

    def media_url(self, url: str) -> str:
        if not url or PLACEHOLDER_RE.match(url):
            return url
        if url not in self.media:
            self.media[url] = f"MIDIA_{len(self.media) + 1:03d}"
        return self.media[url]

    def summary(self) -> dict[str, int]:
        return {
            "usuarios": len(self.users),
            "quadros": len(self.boards),
            "pins": len(self.pins),
            "midias": len(self.media),
        }


def strip_query(url: str) -> str:
    """Tira a query string: ela carrega token de rastreio."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def sanitize_text(text: str, sanitizer: Sanitizer) -> str:
    """Troca usuario, ids de pin, midias e tokens no texto."""
    text = JWT_RE.sub("TOKEN_REMOVIDO", text)
    text = HASH_RE.sub("NONCE_REMOVIDO", text)
    text = re.sub(
        r"""(?i)document\.cookie\s*=\s*(?:"[^"]*"|'[^']*'|[^;]*)""",
        "document.cookie=''",
        text,
    )
    text = re.sub(
        r"https?://(?:[a-z]{2,3}\.)?pinterest\.[a-z.]{2,6}/pin/(\d+)",
        lambda match: f"https://www.pinterest.com/pin/{sanitizer.pin(match.group(1))}/",
        text,
    )
    text = re.sub(
        r"(?<![\w./-])/pin/(\d+)",
        lambda match: f"/pin/{sanitizer.pin(match.group(1))}/",
        text,
    )
    text = re.sub(
        r"https?://(?:[a-z]{2,3}\.)?pinterest\.[a-z.]{2,6}" r"/([A-Za-z0-9_~-]+)/([A-Za-z0-9_.~-]+)",
        lambda match: "https://www.pinterest.com" + board_path(sanitizer, match.group(1), match.group(2)),
        text,
    )
    text = re.sub(
        r"(?<![\w./-])/([A-Za-z0-9_~-]+)/([A-Za-z0-9_.~-]+)",
        lambda match: board_path(sanitizer, match.group(1), match.group(2)),
        text,
    )
    text = re.sub(
        r"https?://i\.pinimg\.com/[^\s\"'\\<>]+",
        lambda match: sanitizer.media_url(match.group(0)),
        text,
    )
    return text


def board_path(sanitizer: Sanitizer, user: str, board: str) -> str:
    """Troca o par usuario/quadro, se o caminho for mesmo um par.

    Um caminho que comeca por um nome reservado, como `/resource/...`, nao
    e um par de usuario e quadro e fica como esta.
    """
    if user.lower() in RESERVED_PATHS:
        return f"/{user}/{board}"
    return f"/{sanitizer.user(user)}/{sanitizer.board(board)}"


def sanitize_value(value: Any, sanitizer: Sanitizer) -> Any:
    """Percorre um payload JSON e troca identificadores por nomes estaveis."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                continue
            if key == "user" and isinstance(item, dict):
                # A pessoa que esta logada nao entra na captura: a estrutura
                # fica, os valores nao.
                clean[key] = {
                    name: ("str" if isinstance(inner, str) else inner)
                    for name, inner in item.items()
                    if name.lower() not in FORBIDDEN_KEYS
                }
                continue
            if key in {"id", "entity_id", "entityId"} and isinstance(item, (str, int)):
                text = str(item)
                if text.isdigit():
                    clean[key] = sanitizer.pin(text)
                    continue
            if key == "url" and isinstance(item, str):
                clean[key] = strip_query(sanitize_text(item, sanitizer))
                continue
            if key == "username" and isinstance(item, str):
                clean[key] = sanitizer.user(item)
                continue
            clean[key] = sanitize_value(item, sanitizer)
        return clean
    if isinstance(value, list):
        return [sanitize_value(item, sanitizer) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, sanitizer)
    return value


def apply_known_names(text: str, sanitizer: Sanitizer) -> str:
    """Troca em todo o texto os nomes de usuario e de quadro ja vistos.

    A mesma pessoa aparece em varias formas: um link de perfil, um link
    profundo de aplicativo, um texto. Trocar o nome em todo o texto e a
    unica forma de garantir que ele nao fica em nenhum deles.
    """
    for name, placeholder in list(sanitizer.users.items()) + list(sanitizer.boards.items()):
        # Um nome curto pode ser uma palavra comum e trocar todo o texto
        # por ele estragaria a captura sem necessidade.
        if len(name) >= 5:
            text = text.replace(name, placeholder)
    return text


def scrub_strings(value: Any, sanitizer: Sanitizer) -> Any:
    """Aplica a troca de nomes em todas as strings de uma estrutura."""
    if isinstance(value, str):
        return apply_known_names(value, sanitizer)
    if isinstance(value, list):
        return [scrub_strings(item, sanitizer) for item in value]
    if isinstance(value, dict):
        return {key: scrub_strings(item, sanitizer) for key, item in value.items()}
    return value


def collect_keys(value: Any, found: set[str]) -> None:
    """Junta os nomes de chave de um payload, para registrar o que existe."""
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            collect_keys(item, found)
    elif isinstance(value, list):
        for item in value[:5]:
            collect_keys(item, found)


def sanitize_pws_script(html: str, sanitizer: Sanitizer) -> str:
    """Sanitiza o bloco __PWS_DATA__ olhando o JSON, e nao o texto.

    O bloco carrega o contexto da sessao: nonce, identificador anonimo,
    token de rastreio e, quando ha sessao, a pessoa. Tratar isso como
    texto deixaria o token passar.
    """

    def replace(match: "re.Match[str]") -> str:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(0)
        clean = sanitize_value(data, sanitizer)
        return (
            match.group(0)[: match.start(1) - match.start(0)]
            + json.dumps(clean, ensure_ascii=False)
            + match.group(0)[match.end(1) - match.start(0) :]
        )

    return PWS_RE.sub(replace, html)


def describe_shape(value: Any, depth: int = 0) -> Any:
    """Descreve o formato de um payload sem guardar o conteudo.

    O que interessa para a compatibilidade e o nome das chaves e o tipo de
    cada uma, nao os valores.
    """
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {key: describe_shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [describe_shape(value[0], depth + 1)]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return "str"


def recommendation_keys(keys: set[str]) -> list[str]:
    """As chaves cujo nome indica que o payload carrega recomendacoes."""
    found = []
    for key in sorted(keys):
        lower = key.lower()
        if any(hint in lower for hint in RECOMMENDATION_HINTS):
            found.append(key)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="endereco da pagina a capturar")
    parser.add_argument("--out", required=True, type=Path, help="diretorio de saida")
    parser.add_argument(
        "--surface",
        default="pagina",
        help="rotulo da superficie capturada (quadro, perfil, pin, busca)",
    )
    parser.add_argument("--wait", type=float, default=3.0, help="segundos de espera pela pagina")
    parser.add_argument("--headed", action="store_true", help="abre o browser visivel")
    parser.add_argument("--scrolls", type=int, default=3, help="quantas vezes rolar a pagina")
    parser.add_argument(
        "--trim",
        action="store_true",
        help="guarda o formato dos payloads em vez do corpo inteiro",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "a captura precisa do playwright: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    sanitizer = Sanitizer()
    payloads: list[dict[str, Any]] = []
    html = ""
    status = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        context = browser.new_context(locale="en-US")
        page = context.new_page()

        def on_response(response: Any) -> None:
            try:
                if "json" not in (response.headers or {}).get("content-type", ""):
                    return
                body = response.json()
            except Exception:  # noqa: BLE001 - payload invalido nao derruba a captura
                return
            payloads.append(
                {
                    "url": strip_query(response.url),
                    "status": response.status,
                    "body": body,
                }
            )

        page.on("response", on_response)
        response = page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        status = response.status if response else 0
        page.wait_for_timeout(int(args.wait * 1000))
        for _ in range(max(0, args.scrolls)):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(800)
        html = page.content()
        # O contexto tem a identidade da sessao: nao entra na captura.
        for payload in payloads:
            body = payload.get("body")
            if isinstance(body, dict) and isinstance(body.get("context"), dict):
                body["context"] = {
                    key: value for key, value in body["context"].items() if key.lower() not in FORBIDDEN_KEYS
                }
        context.close()
        browser.close()

    clean_html = sanitize_pws_script(html, sanitizer)
    clean_html = sanitize_text(clean_html, sanitizer)
    clean_html = apply_known_names(clean_html, sanitizer)
    if args.trim:
        # O estilo e o script da pagina ocupam a maior parte do arquivo e
        # nao dizem nada sobre o formato que a captura prova.
        clean_html = re.sub(r"(?is)<style[^>]*>.*?</style>", "<style></style>", clean_html)
        clean_html = re.sub(r"(?is)<script(?![^>]*__PWS_DATA__)[^>]*>.*?</script>", "", clean_html)
    (args.out / f"{args.surface}.html").write_text(clean_html, encoding="utf-8")

    clean_payloads = []
    all_keys: set[str] = set()
    for payload in payloads:
        body = scrub_strings(sanitize_value(payload["body"], sanitizer), sanitizer)
        collect_keys(body, all_keys)
        clean_payloads.append(
            {
                "url": sanitize_text(payload["url"], sanitizer),
                "status": payload["status"],
                "body": body,
            }
        )
    if args.trim:
        # O corpo inteiro de um payload pode ter centenas de kilobytes e nao
        # interessa para o que a captura prova: interessa o formato. O que
        # fica e a arvore de chaves com o tipo de cada uma.
        trimmed = [
            {
                "url": payload["url"],
                "status": payload["status"],
                "shape": describe_shape(payload["body"]),
            }
            for payload in clean_payloads
        ]
        (args.out / f"{args.surface}-payloads.json").write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        (args.out / f"{args.surface}-payloads.json").write_text(
            json.dumps(clean_payloads, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    pws_match = PWS_RE.search(clean_html)
    pws_keys: set[str] = set()
    if pws_match:
        try:
            collect_keys(json.loads(pws_match.group(1)), pws_keys)
        except json.JSONDecodeError:
            pass

    selectors = sorted(
        set(re.findall(r'data-test-id="([^"]+)"', clean_html)) | set(re.findall(r'data-parity="([^"]+)"', clean_html))
    )
    manifest = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "surface": args.surface,
        "origin": sanitize_text(strip_query(args.url), sanitizer),
        "http_status": status,
        "sanitized": True,
        "sanitization": {
            "usuarios": "trocados por USUARIO_NNN",
            "quadros": "trocados por QUADRO_NNN",
            "pins": "trocados por PIN_NNN",
            "midias": "trocados por MIDIA_NNN",
            "query_string": "removida",
            "contexto_de_sessao": "removido (cookie, token, nonce, identificador anonimo)",
        },
        "observed": {
            "selectors": selectors,
            "payload_keys": sorted(all_keys),
            "pws_keys": sorted(pws_keys),
            "recommendation_keys": recommendation_keys(all_keys | pws_keys),
            "payload_count": len(clean_payloads),
        },
        "counts": sanitizer.summary(),
        "limits": [
            "captura feita sem sessao: nao cobre a superficie logada",
            "nao cobre quadros privados nem contas de teste",
            "os seletores observados valem para a data da captura",
            "a captura nao prova completude de nenhum quadro",
            "as superficies publicas podem entregar os pins bloqueados " "(gated) em vez dos pins, com o feed vazio",
            "nenhuma superficie observada traz um marcador explicito de " "fim de feed",
        ],
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"captura gravada em {args.out}")
    print(f"  seletores observados: {len(selectors)}")
    print(f"  chaves de payload: {len(all_keys)}")
    print(f"  chaves de recomendacao: {len(manifest['observed']['recommendation_keys'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
