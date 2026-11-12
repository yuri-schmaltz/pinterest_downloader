"""A captura real do Pinterest nao pode carregar dado de pessoa.

O aceito do plano e claro: uma captura real nao contem cookie, token nem
dado privado. Estes testes exercitam o sanitizador com uma pagina que
carrega tudo isso e conferem que nada sobrevive.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SANITIZER_PATH = ROOT / "scripts" / "capture_pinterest.py"


def _load_sanitizer():
    """Carrega o script de captura sem executar a linha de comando."""
    spec = importlib.util.spec_from_file_location("capture_pinterest", SANITIZER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


capture = _load_sanitizer()


HTML_COM_REDACOES = """
<html><head>
<meta content="https://www.pinterest.com/pinterestbr/aesthetic-de-poeta/" name="pinterestapp:pinner">
<link href="ios-app://429047995/pinterest/board/pinterestbr/aesthetic-de-poeta" rel="alternate">
<script id="__PWS_DATA__">{"context":{
  "csp_nonce":"abc123cspnoncevalue0000000000",
  "unauth_id":"99999999999999999999999999999999",
  "analysis_ua":{"ua":"x"},
  "user":{"unauth_id":"11111111111111111111111111111111","full_name":"Pessoa Real"},
  "country":"BR","locale":"pt_BR"},
 "pins":[{"id":"987654321","images":{"orig":{"url":"https://i.pinimg.com/originals/aa/bb/cc/987654321.jpg"}}}]}</script>
</head><body>
<a href="/pinterestbr/aesthetic-de-poeta/">Quadro</a>
<a href="/pin/987654321/">Pin</a>
<img src="https://i.pinimg.com/originals/aa/bb/cc/987654321.jpg">
<script>document.cookie="csrftoken=SEGREDO; path=/";</script>
<script>var t="eyJhbGciOiJIUzI1NiJ9.eyJvcmlnaW4iOiJzZWNyZXQifQ.sig";</script>
</body></html>
"""

SEGREDO_TOKEN = "abc123cspnoncevalue0000000000"
SEGREDO_ANON = "99999999999999999999999999999999"
SEGREDO_COOKIE = "SEGREDO"
SEGREDO_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJvcmlnaW4iOiJzZWNyZXQifQ.sig"
NOME_PESSOA = "Pessoa Real"


@pytest.fixture()
def sanitizada() -> str:
    """A pagina depois de passar pelo sanitizador."""
    san = capture.Sanitizer()
    html = capture.sanitize_pws_script(HTML_COM_REDACOES, san)
    html = capture.sanitize_text(html, san)
    return capture.apply_known_names(html, san)


def test_nenhum_token_de_sessao_sobrevive(sanitizada: str) -> None:
    for segredo in (SEGREDO_TOKEN, SEGREDO_ANON, SEGREDO_COOKIE, SEGREDO_JWT):
        assert segredo not in sanitizada, f"o segredo {segredo!r} ficou na captura"


def test_o_nome_da_pessoa_nao_sobrevive(sanitizada: str) -> None:
    assert NOME_PESSOA not in sanitizada


def test_o_nome_do_quadro_e_trocado(sanitizada: str) -> None:
    assert "pinterestbr" not in sanitizada
    assert "aesthetic-de-poeta" not in sanitizada
    assert "USUARIO_" in sanitizada
    assert "QUADRO_" in sanitizada


def test_o_id_do_pin_e_trocado(sanitizada: str) -> None:
    assert "987654321" not in sanitizada
    assert "PIN_" in sanitizada


def test_a_url_da_midia_e_trocada(sanitizada: str) -> None:
    assert "i.pinimg.com" not in sanitizada
    assert "MIDIA_" in sanitizada


def test_o_contexto_continua_legivel(sanitizada: str) -> None:
    # O contexto sem sessao pode ficar: o que nao pode ficar e a sessao.
    bloco = re.search(r"(?is)<script[^>]*__PWS_DATA__[^>]*>(.*?)</script", sanitizada)
    assert bloco, "o bloco PWS sumiu da captura"
    dados = json.loads(bloco.group(1))
    contexto = dados["context"]
    assert "country" in contexto
    assert "csp_nonce" not in contexto
    assert "unauth_id" not in contexto
    assert "analysis_ua" not in contexto


def test_o_payload_sanitizado_perde_as_chaves_de_sessao() -> None:
    san = capture.Sanitizer()
    payload = {
        "context": {"csp_nonce": "x", "unauth_id": "y", "country": "BR"},
        "user": {"unauth_id": "z", "full_name": NOME_PESSOA},
        "resource_response": {
            "data": [
                {
                    "id": "987654321",
                    "images": {"orig": {"url": "https://i.pinimg.com/x.jpg"}},
                }
            ]
        },
    }
    limpo = capture.scrub_strings(capture.sanitize_value(payload, san), san)
    texto = json.dumps(limpo)
    assert "csp_nonce" not in texto
    assert "unauth_id" not in texto
    assert NOME_PESSOA not in texto
    assert "987654321" not in texto
    assert "i.pinimg.com" not in texto


def test_o_caminho_de_recurso_nao_vira_usuario() -> None:
    san = capture.Sanitizer()
    texto = capture.sanitize_text("https://www.pinterest.com/resource/BoardFeedResource/get/", san)
    assert "BoardFeedResource" in texto
    assert "USUARIO_" not in texto


def test_a_captura_que_esta_no_repositorio_nao_tem_segredo() -> None:
    """A captura versionada passa pelas mesmas regras."""
    pasta = ROOT / "tests" / "fixtures" / "real"
    if not pasta.is_dir():
        pytest.skip("a captura real ainda nao foi gravada")
    for arquivo in pasta.iterdir():
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        for segredo in (SEGREDO_TOKEN, SEGREDO_ANON, SEGREDO_COOKIE, SEGREDO_JWT):
            assert segredo not in texto, f"{arquivo.name} carrega {segredo!r}"
        assert "pinterestbr" not in texto, f"{arquivo.name} carrega o nome real"
        assert "i.pinimg.com" not in texto, f"{arquivo.name} carrega url de midia"


def test_o_manifesto_registra_data_origem_e_limites() -> None:
    pasta = ROOT / "tests" / "fixtures" / "real"
    manifesto = pasta / "manifest.json"
    if not manifesto.is_file():
        pytest.skip("a captura real ainda nao foi gravada")
    dados = json.loads(manifesto.read_text(encoding="utf-8"))
    assert dados["captured_at"]
    assert dados["origin"].startswith("https://www.pinterest.com/")
    assert dados["limits"], "a captura precisa registrar o que ela nao cobre"
    assert dados["observed"]["selectors"], "a captura precisa registrar o que viu"
