#!/usr/bin/env python3
"""Testes da resolucao de imagens (a parte que decide qual arquivo baixar).

`resolve_images` era uma funcao de complexidade 16, com o cache, a
interceptacao e o worker adaptativo misturados no mesmo corpo. O
refactor separou as tres partes, e sao elas que estes testes exercitam.

O que eles cobrem:
  1. a particao dos pins entre cache, interceptacao e "vai buscar"
  2. a contagem de acertos de cache
  3. a resolucao de um pin, com o fallback para o dominio mobile

Nenhum teste toca a rede: `fetch_pin_media` e substituido por um duble.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import pinterest_board_dl
from pinterest_board_dl import (
    _count_cache_hits,
    _partition_links,
    _resolve_single_pin,
)

PIN_A = "https://www.pinterest.com/pin/111/"
PIN_B = "https://www.pinterest.com/pin/222/"
PIN_C = "https://www.pinterest.com/pin/333/"


class TestPartitionLinks:
    def test_sem_cache_nem_interceptacao_tudo_vai_buscar(self):
        out, to_fetch = _partition_links([PIN_A, PIN_B], {}, {})
        assert out == {}
        assert to_fetch == [PIN_A, PIN_B]

    def test_pin_no_cache_vai_para_o_resolvido(self):
        out, to_fetch = _partition_links([PIN_A], {PIN_A: "http://img/a.jpg"}, {})
        assert out == {PIN_A: "http://img/a.jpg"}
        assert to_fetch == []

    def test_pin_interceptado_tem_prioridade_sobre_o_cache(self):
        # o metadado interceptado veio da pagina que o usuario esta vendo
        # agora -- e mais fresco que o que esta em disco
        intercepted = {PIN_A: {"image_url": "http://img/fresco.jpg"}}
        out, to_fetch = _partition_links([PIN_A], {PIN_A: "http://img/velho.jpg"}, intercepted)
        assert out == {PIN_A: "http://img/fresco.jpg"}
        assert to_fetch == []

    def test_mistura_os_tres_caminhos(self):
        cache = {PIN_A: "http://img/a.jpg"}
        intercepted = {PIN_B: {"image_url": "http://img/b.jpg"}}
        out, to_fetch = _partition_links([PIN_A, PIN_B, PIN_C], cache, intercepted)
        assert out == {PIN_A: "http://img/a.jpg", PIN_B: "http://img/b.jpg"}
        assert to_fetch == [PIN_C]

    def test_entrada_vazia(self):
        out, to_fetch = _partition_links([], {}, {})
        assert out == {}
        assert to_fetch == []

    def test_aceita_qualquer_iteravel(self):
        out, to_fetch = _partition_links(iter([PIN_A]), {}, {})
        assert to_fetch == [PIN_A]


class TestCountCacheHits:
    def test_conta_cache_e_interceptacao(self):
        out = {PIN_A: "x", PIN_B: "y"}
        intercepted = {PIN_B: {"image_url": "y"}}
        cache_hits, intercept_hits = _count_cache_hits(out, intercepted)
        assert intercept_hits == 1
        assert cache_hits == 1

    def test_tudo_do_cache(self):
        out = {PIN_A: "x", PIN_B: "y"}
        cache_hits, intercept_hits = _count_cache_hits(out, {})
        assert cache_hits == 2
        assert intercept_hits == 0

    def test_vazio(self):
        assert _count_cache_hits({}, {}) == (0, 0)


class FakeManager:
    def __init__(self):
        self.success = 0
        self.failure = 0

    def record_success(self, latency_ms):
        self.success += 1

    def record_failure(self):
        self.failure += 1


class TestResolveSinglePin:
    @pytest.fixture
    def calls(self, monkeypatch):
        """Substitui fetch_pin_media e registra as URLs pedidas."""
        recorded = []

        def fake_fetch(link, session, use_rate_limit=False):
            recorded.append((link, use_rate_limit))
            return "http://img/ok.jpg" if link.endswith("www.pinterest.com/pin/111/") else None

        monkeypatch.setattr(pinterest_board_dl, "fetch_pin_media", fake_fetch)
        return recorded

    def test_resolve_na_primeira_tentativa(self, calls):
        link, img = _resolve_single_pin(PIN_A, session=None, use_rate_limit=False)
        assert link == PIN_A
        assert img == "http://img/ok.jpg"
        assert len(calls) == 1

    def test_fallback_para_o_dominio_mobile(self, calls):
        link, img = _resolve_single_pin(PIN_B, session=None, use_rate_limit=False)
        assert link == PIN_B
        assert img is None
        assert len(calls) == 2
        assert calls[1][0] == "https://br.pinterest.com/pin/222/"

    def test_o_rate_limiting_chega_ao_fetch(self, calls):
        _resolve_single_pin(PIN_A, session=None, use_rate_limit=True)
        assert calls[0][1] is True

    def test_registra_sucesso_no_manager(self, calls):
        manager = FakeManager()
        _resolve_single_pin(PIN_A, session=None, use_rate_limit=False, manager=manager)
        assert manager.success == 1
        assert manager.failure == 0

    def test_registra_falha_no_manager(self, calls):
        manager = FakeManager()
        _resolve_single_pin(PIN_B, session=None, use_rate_limit=False, manager=manager)
        assert manager.success == 0
        assert manager.failure == 1

    def test_sem_manager_nao_quebra(self, calls):
        link, img = _resolve_single_pin(PIN_A, session=None, use_rate_limit=False)
        assert img == "http://img/ok.jpg"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
