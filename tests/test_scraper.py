#!/usr/bin/env python3
"""Testes do scraper de verdade -- o nucleo do projeto ate aqui nao tinha
nenhum teste.

O que estes testes cobrem:
  1. a aritmetica de estabilidade do scroll (funcao pura, sem browser)
  2. a coleta de pins de um quadro, contra um HTML local
  3. a extracao de quadros de um perfil, contra um HTML local

Os testes 2 e 3 abrem um Chromium de verdade, mas NAO tocam a rede: o
conteudo vem de tests/fixtures/*.html servido por file://. Se o Chromium
nao estiver instalado, esses testes sao pulados (skip) em vez de quebrar a
suite -- de proposito, para que `pytest tests/` continue funcionando em
qualquer maquina.

Para instalar o browser:
    python -m playwright install chromium
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pinterest_board_dl import (
    _compute_scroll_stability,
    _extract_boards_from_page,
    collect_pin_links,
    parse_pin_count,
)

FIXTURES = Path(__file__).parent / "fixtures"
BOARD_FIXTURE = FIXTURES / "pinterest_board.html"
PROFILE_FIXTURE = FIXTURES / "pinterest_profile.html"

# O mesmo set que collect_board_urls usa internamente.
EXCLUDE = {
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


# ======================================================================
# 1. Estabilidade do scroll -- funcao pura, sem browser
# ======================================================================


class TestScrollStability:
    """A regra que decide quando o scroll parou de trazer pins novos."""

    def test_progress_resets_the_counter(self):
        rounds, last_count, last_height = _compute_scroll_stability(
            stable_rounds=7,
            last_count=10,
            last_height=1000,
            current_count=15,
            current_height=2000,
            has_more_like_this=False,
            is_bottom=False,
        )
        assert rounds == 0, "com pins novos o contador tem de zerar"
        assert last_count == 15
        assert last_height == 2000

    def test_stable_height_counts_one(self):
        rounds, _, _ = _compute_scroll_stability(
            stable_rounds=0,
            last_count=10,
            last_height=1000,
            current_count=10,
            current_height=1000,
            has_more_like_this=False,
            is_bottom=False,
        )
        assert rounds == 1

    def test_changed_height_gives_partial_credit(self):
        """A altura mudou mas os pins nao: a pagina pode estar carregando
        outra coisa. Conta meio round, nao um inteiro."""
        rounds, _, _ = _compute_scroll_stability(
            stable_rounds=0,
            last_count=10,
            last_height=1000,
            current_count=10,
            current_height=1500,
            has_more_like_this=False,
            is_bottom=False,
        )
        assert rounds == 0.5

    def test_more_like_this_at_the_bottom_counts_two(self):
        """ "Mais como esse" visivel no fim da pagina e sinal forte de fim."""
        rounds, _, _ = _compute_scroll_stability(
            stable_rounds=0,
            last_count=10,
            last_height=1000,
            current_count=10,
            current_height=1000,
            has_more_like_this=True,
            is_bottom=True,
        )
        assert rounds == 2

    def test_more_like_this_mid_page_is_not_a_signal(self):
        """A secao aparece no meio da rolagem tambem -- so conta se estiver
        no fim da pagina."""
        rounds, _, _ = _compute_scroll_stability(
            stable_rounds=0,
            last_count=10,
            last_height=1000,
            current_count=10,
            current_height=1000,
            has_more_like_this=True,
            is_bottom=False,
        )
        assert rounds == 1, "no meio da pagina vale o caso normal"

    def test_last_height_is_kept_when_there_is_no_progress(self):
        """Sem pins novos, a altura de referencia NAO e atualizada -- e o que
        permite repetir o credito parcial enquanto a pagina muda."""
        _, last_count, last_height = _compute_scroll_stability(
            stable_rounds=0,
            last_count=10,
            last_height=1000,
            current_count=10,
            current_height=1500,
            has_more_like_this=False,
            is_bottom=False,
        )
        assert last_height == 1000
        assert last_count == 10

    def test_counter_accumulates_across_rounds(self):
        rounds = 0.0
        for _ in range(5):
            rounds, _, _ = _compute_scroll_stability(
                stable_rounds=rounds,
                last_count=10,
                last_height=1000,
                current_count=10,
                current_height=1000,
                has_more_like_this=False,
                is_bottom=False,
            )
        assert rounds == 5


# ======================================================================
# Browser -- fixture de sessao
# ======================================================================


@pytest.fixture(scope="module")
def browser():
    """Chromium de sessao. Pula o teste se o browser nao estiver instalado."""
    pw = pytest.importorskip("playwright.sync_api", reason="playwright nao instalado")
    try:
        with pw.sync_playwright() as p:
            try:
                b = p.chromium.launch(headless=True)
            except Exception as exc:  # browser nao baixado
                pytest.skip(f"Chromium indisponivel (rode 'playwright install chromium'): {exc}")
            yield b
            b.close()
    except Exception as exc:
        pytest.skip(f"playwright indisponivel: {exc}")


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


@pytest.fixture(scope="module")
def collected_links(browser):
    """Links do quadro, coletados uma vez e reusados pelos testes.

    Cada coleta custa alguns segundos (o scraper espera a pagina assentar
    antes de rolar), entao coletar uma vez e reaproveitar deixa a suite
    rapida sem perder cobertura.
    """
    return collect_pin_links(
        board_url=_file_url(BOARD_FIXTURE),
        headless=True,
        manual_login=False,
        scroll_pause=0.05,
        max_pins=None,
        browser=browser,
    )


# ======================================================================
# 2. Coleta de pins
# ======================================================================


class TestCollectPinLinks:
    def test_finds_every_pin_of_the_fixture(self, collected_links):
        links = collected_links
        assert len(links) == 8, f"esperava 8 pins, veio {len(links)}: {links}"
        # O Pinterest usa hrefs com e sem barra final, entao o invariante
        # testado e QUAIS pins foram achados, nao a forma exata da URL.
        ids = {link.rstrip("/").rsplit("/", 1)[-1] for link in links}
        assert ids == {str(1000 + i) for i in range(1, 9)}

    def test_ignores_links_that_are_not_pins(self, collected_links):
        """O fixture tem um <a href="/usuario/quadro/"> que nao e pin."""
        assert not any("/usuario/" in link for link in collected_links)

    def test_respects_max_pins(self, browser):
        links = collect_pin_links(
            board_url=_file_url(BOARD_FIXTURE),
            headless=True,
            manual_login=False,
            scroll_pause=0.05,
            max_pins=3,
            browser=browser,
        )
        assert len(links) == 3, f"max_pins nao foi respeitado: {links}"

    def test_returns_absolute_pinterest_urls(self, collected_links):
        assert all(link.startswith("https://www.pinterest.com/pin/") for link in collected_links)


# ======================================================================
# 3. Extracao de quadros
# ======================================================================


@pytest.fixture(scope="module")
def profile_page(browser):
    """Pagina de perfil pronta, com o fixture carregado."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(_file_url(PROFILE_FIXTURE), wait_until="load")
    yield page
    ctx.close()


class TestExtractBoards:
    def test_finds_the_user_boards(self, profile_page):
        boards = _extract_boards_from_page(profile_page, "usuario", EXCLUDE)
        urls = {b["url"] for b in boards}
        assert "https://www.pinterest.com/usuario/decoracao/" in urls
        assert "https://www.pinterest.com/usuario/culinaria/" in urls
        assert "https://www.pinterest.com/usuario/fotografia/" in urls
        assert "https://www.pinterest.com/usuario/viagens/" in urls

    def test_excludes_navigation_slugs(self, profile_page):
        """boards, pins, created etc. sao abas de navegacao, nao quadros."""
        boards = _extract_boards_from_page(profile_page, "usuario", EXCLUDE)
        slugs = {b["url"].rstrip("/").split("/")[-1] for b in boards}
        for slug in ("boards", "pins", "created", "followers"):
            assert slug not in slugs

    def test_excludes_underscore_slugs(self, profile_page):
        """Slugs comecados com '_' sao privados/ocultos do Pinterest."""
        boards = _extract_boards_from_page(profile_page, "usuario", EXCLUDE)
        slugs = {b["url"].rstrip("/").split("/")[-1] for b in boards}
        assert "_criados" not in slugs

    def test_ignores_other_users(self, profile_page):
        boards = _extract_boards_from_page(profile_page, "usuario", EXCLUDE)
        assert not any("/outro_usuario/" in b["url"] for b in boards)

    def test_reads_the_title(self, profile_page):
        boards = {b["url"]: b for b in _extract_boards_from_page(profile_page, "usuario", EXCLUDE)}
        assert boards["https://www.pinterest.com/usuario/decoracao/"]["title"] == "Decoração"
        assert boards["https://www.pinterest.com/usuario/culinaria/"]["title"] == "Culinária"

    def test_falls_back_to_first_line_when_there_is_no_h2(self, profile_page):
        boards = {b["url"]: b for b in _extract_boards_from_page(profile_page, "usuario", EXCLUDE)}
        assert boards["https://www.pinterest.com/usuario/viagens/"]["title"] == "Viagens"

    def test_reads_the_thumbnail(self, profile_page):
        boards = {b["url"]: b for b in _extract_boards_from_page(profile_page, "usuario", EXCLUDE)}
        assert (
            boards["https://www.pinterest.com/usuario/decoracao/"]["thumbnail_url"]
            == "https://i.pinimg.com/thumbs/decoracao.jpg"
        )

    def test_reads_the_pin_count(self, profile_page):
        boards = {b["url"]: b for b in _extract_boards_from_page(profile_page, "usuario", EXCLUDE)}
        # O regex captura a unidade junto com o numero.
        assert boards["https://www.pinterest.com/usuario/decoracao/"]["pin_count"] == "1,2 mil"
        assert boards["https://www.pinterest.com/usuario/culinaria/"]["pin_count"] == "340 pins"
        assert boards["https://www.pinterest.com/usuario/fotografia/"]["pin_count"] == "15 pins"

    def test_parses_the_pin_count_into_an_int(self, profile_page):
        boards = {b["url"]: b for b in _extract_boards_from_page(profile_page, "usuario", EXCLUDE)}
        assert boards["https://www.pinterest.com/usuario/decoracao/"]["pin_count_int"] == 1200
        assert boards["https://www.pinterest.com/usuario/culinaria/"]["pin_count_int"] == 340
        assert boards["https://www.pinterest.com/usuario/fotografia/"]["pin_count_int"] == 15

    def test_pin_count_int_is_none_when_the_count_is_missing(self, profile_page):
        """Um quadro sem contagem visivel nao pode virar 0 -- seria mentira."""
        boards = _extract_boards_from_page(profile_page, "usuario", EXCLUDE)
        for board in boards:
            if not board["pin_count"]:
                assert board["pin_count_int"] is None

    def test_pin_count_parser_agrees_with_the_extraction(self, profile_page):
        """O pin_count_int tem de bater com o que parse_pin_count devolve
        para o mesmo texto -- sao duas fontes de verdade que nao podem
        divergir."""
        for board in _extract_boards_from_page(profile_page, "usuario", EXCLUDE):
            assert board["pin_count_int"] == parse_pin_count(board["pin_count"])


# ======================================================================
# 4. Helpers de download de mídia e pós-verificação (refatoração P2.4)
# ======================================================================


class TestDownloadMediaHelpers:
    """Valida o funcionamento dos novos helpers modulares de download e integridade."""

    def test_detect_media_extension(self):
        from pinterest_board_dl import _detect_media_extension

        assert _detect_media_extension("video/mp4; charset=binary") == ".mp4"
        assert _detect_media_extension("image/png") == ".png"
        assert _detect_media_extension("image/gif") == ".gif"
        assert _detect_media_extension("image/webp") == ".webp"
        assert _detect_media_extension("image/jpeg") == ".jpg"
        assert _detect_media_extension("unknown/type") == ".jpg"

    def test_is_media_already_downloaded(self, tmp_path):
        from pinterest_board_dl import _is_media_already_downloaded

        target_file = tmp_path / "pin123.jpg"
        assert not _is_media_already_downloaded(str(tmp_path), "pin123")

        # Arquivo de 0 bytes não deve contar como baixado
        target_file.touch()
        assert not _is_media_already_downloaded(str(tmp_path), "pin123")

        # Arquivo com conteúdo válido conta como baixado
        target_file.write_bytes(b"data")
        assert _is_media_already_downloaded(str(tmp_path), "pin123")

    def test_verify_downloaded_pins(self, tmp_path):
        from pinterest_board_dl import _verify_downloaded_pins

        (tmp_path / "101.jpg").write_bytes(b"image 101")
        pin_img = {
            "https://www.pinterest.com/pin/101/": "https://i.pinimg.com/101.jpg",
            "https://www.pinterest.com/pin/102/": "https://i.pinimg.com/102.jpg",
        }
        verified, missing = _verify_downloaded_pins(pin_img, str(tmp_path))
        assert verified == 1
        assert missing == ["https://www.pinterest.com/pin/102/"]


def test_download_media_success_and_skip_existing(tmp_path):
    from pinterest_board_dl import download_media

    class MockResponse:
        def __init__(self, content=b"fake image data", content_type="image/jpeg"):
            self.content = content
            self.headers = {"Content-Type": content_type}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=1024):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            return MockResponse()

    sess = MockSession()
    # 1. Download inicial
    ok = download_media("https://i.pinimg.com/orig/pin1.jpg", str(tmp_path), sess, filename_hint="pin1")
    assert ok is True
    assert sess.calls == 1
    downloaded = list(tmp_path.glob("*.jpg"))
    assert len(downloaded) == 1
    assert downloaded[0].read_bytes() == b"fake image data"

    # 2. Segunda tentativa: deve reaproveitar do disco sem fazer request
    ok2 = download_media("https://i.pinimg.com/orig/pin1.jpg", str(tmp_path), sess, filename_hint="pin1")
    assert ok2 is True
    assert sess.calls == 1  # não incrementou


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
