#!/usr/bin/env python3
"""Testes do cache de metadados e do paralelismo adaptativo.

Dois defeitos reais que a auditoria encontrou:

  1. `--cache-dir` era aceito pela CLI e ignorado: `resolve_images`
     carregava e gravava o cache sempre no caminho do sistema, porque
     `load_pin_cache()`/`save_pin_cache()` eram chamados sem argumento.
  2. Com `--adaptive-workers`, o gerenciador recalculava o numero de
     workers e o log registrava a mudanca, mas o `ThreadPoolExecutor`
     ja havia sido criado com o valor inicial: o paralelismo real nunca
     mudava.

Nenhum teste toca a rede: `fetch_pin_media` e substituido por um duble.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import adaptive_workers
import pinterest_board_dl
from pinterest_board_dl import DownloadOptions, build_arg_parser, resolve_images

PIN_A = "https://www.pinterest.com/pin/111/"


@pytest.fixture
def fake_media(monkeypatch):
    """Substitui `fetch_pin_media` por um duble que sempre resolve."""

    def fake_fetch(url, session, use_rate_limit=False):
        return f"http://img/{url.rsplit('/', 2)[-2]}.jpg"

    monkeypatch.setattr("pinterest_board_dl.fetch_pin_media", fake_fetch)
    return fake_fetch


@pytest.fixture(autouse=True)
def isolated_manager():
    """O gerenciador adaptativo e um singleton global; isola cada teste."""
    adaptive_workers.reset_adaptive_manager()
    yield
    adaptive_workers.reset_adaptive_manager()


class TestCacheDirIsHonored:
    def test_cache_e_gravado_no_diretorio_informado(self, tmp_path, fake_media):
        cache_dir = tmp_path / "meu-cache"
        cache_dir.mkdir()

        resolve_images(
            [PIN_A],
            session=object(),
            workers=2,
            use_cache=True,
            cache_dir=str(cache_dir),
        )

        written = cache_dir / ".pinterest_cache.json"
        assert written.is_file(), "o cache nao foi gravado no diretorio informado"
        assert PIN_A in written.read_text(encoding="utf-8")

    def test_cache_do_diretorio_informado_e_reaproveitado(self, tmp_path, fake_media):
        cache_dir = tmp_path / "meu-cache"
        cache_dir.mkdir()
        (cache_dir / ".pinterest_cache.json").write_text(
            '{"%s": "http://img/cacheado.jpg"}' % PIN_A,
            encoding="utf-8",
        )

        calls = []
        original = pinterest_board_dl.fetch_pin_media
        pinterest_board_dl.fetch_pin_media = lambda *a, **k: calls.append(a) or original(*a, **k)
        try:
            resolved = resolve_images(
                [PIN_A],
                session=object(),
                workers=2,
                use_cache=True,
                cache_dir=str(cache_dir),
            )
        finally:
            pinterest_board_dl.fetch_pin_media = original

        assert resolved == {PIN_A: "http://img/cacheado.jpg"}
        assert calls == [], "o pin veio do cache e nao devia ser buscado de novo"

    def test_sem_cache_dir_o_padrao_do_sistema_e_usado(self, tmp_path, monkeypatch, fake_media):
        usado = {}

        def fake_load(cache_dir=None, ttl_days=0):
            usado["load"] = cache_dir
            usado["ttl"] = ttl_days
            return {}

        def fake_save(cache, cache_dir=None):
            usado["save"] = cache_dir

        monkeypatch.setattr("pinterest_board_dl.load_pin_cache", fake_load)
        monkeypatch.setattr("pinterest_board_dl.save_pin_cache", fake_save)

        resolve_images([PIN_A], session=object(), workers=2, use_cache=True)

        assert usado["load"] is None
        assert usado["save"] is None

    def test_cli_default_eh_o_cache_do_sistema(self):
        parser = build_arg_parser()
        assert parser.parse_args(["usuario"]).cache_dir is None
        assert parser.parse_args(["usuario", "--cache-dir", "/tmp/x"]).cache_dir == "/tmp/x"

    def test_download_options_default_eh_o_cache_do_sistema(self):
        assert DownloadOptions().cache_dir is None


class TestAdaptiveWorkersResizeThePool:
    def test_paralelismo_real_acompanha_o_gerenciador(self, tmp_path, monkeypatch):
        """O numero de tarefas em voo tem de crescer junto com o ajuste."""
        lock = threading.Lock()
        in_flight = 0
        peak = 0

        def fake_fetch(url, session, use_rate_limit=False):
            nonlocal in_flight, peak
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(0.02)
            with lock:
                in_flight -= 1
            return f"http://img/{url.rsplit('/', 2)[-2]}.jpg"

        monkeypatch.setattr("pinterest_board_dl.fetch_pin_media", fake_fetch)

        def fake_adjust(self):
            self.current_workers = min(self.current_workers + 4, self.max_workers)
            return self.current_workers

        monkeypatch.setattr(adaptive_workers.AdaptiveWorkerManager, "adjust_workers", fake_adjust)

        manager = adaptive_workers.get_adaptive_manager(min_workers=2, max_workers=16)
        manager.metrics_file = tmp_path / "metrics.json"

        links = [f"https://www.pinterest.com/pin/{index}/" for index in range(40)]
        resolved = resolve_images(links, session=object(), workers=16, use_cache=False, adaptive=True)

        assert len(resolved) == len(links)
        # A janela inicial e 2 workers; o ajuste so vale se o paralelismo
        # real passou disso.
        assert peak > 2, f"o paralelismo real nao acompanhou o ajuste (pico={peak})"
        assert manager.current_workers > 2
