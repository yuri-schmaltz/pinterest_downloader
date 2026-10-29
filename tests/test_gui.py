#!/usr/bin/env python3
"""Testes da GUI PyQt6.

A GUI tinha 0 % de cobertura. Estes testes exercitam a camada de
apresentacao -- a construcao da janela, o preenchimento da lista de
quadros, o controle de selecao e os slots de progresso.

Rodam com o platform plugin "offscreen", entao nao precisam de display
nem de xvfb:

    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui.py

Se o PyQt6 nao estiver instalado, a suite inteira e pulada (skip) em vez
de quebrar -- a GUI e opcional em runtime no scraper.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 nao instalado")

# O platform plugin offscreen deixa a GUI subir sem display.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402

import pinterest_board_gui as gui  # noqa: E402


class _FakeFlag:
    """Enum do Qt: a GUI combina icones e botoes com '|' (bitwise or)."""

    def __init__(self, name):
        self.name = name

    def __or__(self, other):
        return self

    def __ror__(self, other):
        return self

    def __repr__(self):
        return f"<{self.name}>"


class _FakeStandardButton:
    Ok = _FakeFlag("Ok")
    Cancel = _FakeFlag("Cancel")
    Yes = _FakeFlag("Yes")
    No = _FakeFlag("No")


class _FakeIcon:
    Warning = _FakeFlag("Warning")
    Critical = _FakeFlag("Critical")
    Information = _FakeFlag("Information")


class _FakeMessageBox:
    """Duble do QMessageBox: em modo offscreen um dialogo modal travaria o
    teste para sempre, porque exec() fica esperando o usuario clicar."""

    Icon = _FakeIcon
    StandardButton = _FakeStandardButton
    Critical = _FakeFlag("Critical")
    Warning = _FakeFlag("Warning")

    @staticmethod
    def critical(parent, title, text, *args, **kwargs):
        return 0

    @staticmethod
    def information(parent, title, text, *args, **kwargs):
        return 0

    def __init__(self, *args, **kwargs):
        self.text = ""
        self.window_title = ""
        self.icon = None
        self.buttons = None

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, title):
        self.window_title = title

    def setText(self, text):
        self.text = text

    def setStandardButtons(self, buttons):
        self.buttons = buttons

    def setInformativeText(self, text):
        pass

    def setDefaultButton(self, button):
        pass

    def setCheckBox(self, checkbox):
        pass

    def button(self, which):
        return None

    def clickedButton(self):
        return None

    def exec(self):
        return 0

    def show(self):
        pass


@pytest.fixture(scope="module")
def app():
    """QApplication de sessao (so uma instance e permitida por processo)."""
    from PyQt6.QtWidgets import QApplication

    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def window(app):
    """MainWindow nova a cada teste."""
    w = gui.MainWindow()
    yield w
    w.close()


def _board(url="https://www.pinterest.com/usuario/decoracao/", title="Decoração", pin_count="1,2 mil", thumb=""):
    """BoardMetadata no formato que a GUI recebe."""
    return {
        "url": url,
        "title": title,
        "thumbnail_url": thumb,
        "pin_count": pin_count,
        "pin_count_int": 1200,
    }


class TestMainWindow:
    def test_window_builds(self, window):
        assert window.windowTitle().startswith("Pinterest Board Downloader")

    def test_has_the_two_columns(self, window):
        """A GUI e um layout de duas colunas: configuracao/progresso/log a
        esquerda, selecao de quadros a direita. Nao ha abas."""
        assert window.selection_panel is not None
        assert window.user_edit is not None
        assert window.selection_list is not None

    def test_start_button_is_disabled_until_a_board_is_chosen(self, window):
        """Sem quadro selecionado, iniciar tem de estar bloqueado -- senao o
        usuario clica e nao acontece nada."""
        window.on_boards_found([])
        assert not window.start_button.isEnabled()


class TestBoardList:
    def test_lists_the_boards_found(self, window):
        window.on_boards_found([_board(), _board("/b2/", "Culinária", "340 pins")])
        assert window.selection_list.count() == 2

    def test_shows_title_and_pin_count(self, window):
        window.on_boards_found([_board()])
        assert window.selection_list.item(0).text() == "Decoração (1,2 mil)"

    def test_normalizes_the_url_for_the_mapping(self, window):
        """A URL e normalizada com barra final para casar com o mapeamento
        do historico."""
        window.on_boards_found([_board(url="https://www.pinterest.com/usuario/decoracao")])
        item = window.selection_list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == "https://www.pinterest.com/usuario/decoracao/"

    def test_keeps_the_title_in_the_mapping(self, window):
        window.on_boards_found([_board()])
        assert window.url_to_title["https://www.pinterest.com/usuario/decoracao/"] == "Decoração"

    def test_cleans_newlines_from_the_title(self, window):
        window.on_boards_found([_board(title="Decoração\n  Minimalista")])
        assert window.selection_list.item(0).text() == "Decoração Minimalista (1,2 mil)"

    def test_cleans_extra_spaces_from_the_title(self, window):
        window.on_boards_found([_board(title="Decoração   Minimalista")])
        assert window.selection_list.item(0).text() == "Decoração Minimalista (1,2 mil)"

    def test_strips_a_leading_comma_from_the_pin_count(self, window):
        window.on_boards_found([_board(pin_count=",15")])
        assert window.selection_list.item(0).text() == "Decoração (15)"

    def test_omits_the_count_when_there_is_none(self, window):
        window.on_boards_found([_board(pin_count="")])
        assert window.selection_list.item(0).text() == "Decoração"

    def test_empty_list_disables_the_start_button(self, window):
        window.on_boards_found([_board()])
        window.on_boards_found([])
        assert window.selection_list.count() == 0
        assert not window.start_button.isEnabled()

    def test_clears_the_selection_when_the_list_is_reloaded(self, window):
        window.on_boards_found([_board()])
        window.on_boards_found([_board()])
        assert window.selected_urls == []


class TestProgressSlots:
    def test_board_started_shows_the_title_not_the_url(self, window):
        window.url_to_title["https://www.pinterest.com/usuario/decoracao/"] = "Decoração"
        window.on_board_started("https://www.pinterest.com/usuario/decoracao/", "/tmp/out")
        assert "Decoração" in window.current_board_label.text()

    def test_board_started_falls_back_to_the_url(self, window):
        window.on_board_started("https://www.pinterest.com/usuario/desconhecido/", "/tmp/out")
        assert "desconhecido" in window.current_board_label.text()

    def test_download_started_sets_the_maximum(self, window):
        window.on_download_started("https://www.pinterest.com/u/b/", 42)
        assert window.board_progress.maximum() == 42
        assert window.board_progress.value() == 0

    def test_download_started_with_zero_sets_a_sane_maximum(self, window):
        """Com total 0 a barra nao pode ficar com maximum 0 -- isso trava o
        progresso em alguns temas."""
        window.on_download_started("https://www.pinterest.com/u/b/", 0)
        assert window.board_progress.maximum() == 1

    def test_download_progress_updates_the_value(self, window):
        window.on_download_started("https://www.pinterest.com/u/b/", 10)
        window.on_download_progress("https://www.pinterest.com/u/b/", 4, 10, 4)
        assert window.board_progress.value() == 4

    def test_download_progress_never_exceeds_the_total(self, window):
        window.on_download_started("https://www.pinterest.com/u/b/", 10)
        window.on_download_progress("https://www.pinterest.com/u/b/", 99, 10, 99)
        assert window.board_progress.value() <= 10

    def test_board_finished_completes_the_bar(self, window):
        window.on_download_started("https://www.pinterest.com/u/b/", 10)
        window.on_download_progress("https://www.pinterest.com/u/b/", 10, 10, 10)
        window.on_board_finished("https://www.pinterest.com/u/b/", 10, 10, "/tmp/out", verified=10, expected=10)
        assert window.board_progress.value() == window.board_progress.maximum()

    def test_pins_collected_updates_the_item(self, window):
        """A contagem de pins aparece no item da lista do quadro."""
        window.on_boards_found([_board()])
        window.on_pins_collected("https://www.pinterest.com/usuario/decoracao/", 7)
        assert "7" in window.selection_list.item(0).text()

    def test_pins_collected_for_an_unknown_board_is_ignored(self, window):
        window.on_boards_found([_board()])
        before = window.selection_list.item(0).text()
        window.on_pins_collected("https://www.pinterest.com/outro/quadro/", 7)
        assert window.selection_list.item(0).text() == before

    def test_error_does_not_crash(self, window, monkeypatch):
        """on_error abre um QMessageBox modal -- em teste isso travaria
        para sempre, entao o dialogo e substituido por um duble."""
        monkeypatch.setattr(gui, "QMessageBox", _FakeMessageBox)
        window.on_error("algo deu errado")

    def test_error_for_a_private_profile_asks_to_enable_manual_login(self, window, monkeypatch):
        monkeypatch.setattr(gui, "QMessageBox", _FakeMessageBox)
        window.on_error("O perfil 'x' é privado. Marque a opção 'Login Manual'")

    def test_cancelled_reenables_the_controls(self, window):
        window.on_cancelled()
        assert window.start_button.isEnabled()
        assert window.list_boards_button.isEnabled()
        assert not window.cancel_button.isEnabled()


class TestSelectionState:
    def test_boards_start_unchecked(self, window):
        window.on_boards_found([_board()])
        # checkState() devolve um enum: CheckState.Unchecked tem valor 0 mas
        # continua sendo um membro verdadeiro, entao a comparacao tem de ser
        # explicita.
        assert window.selection_list.item(0).checkState() == Qt.CheckState.Unchecked

    def test_checking_a_board_enables_the_start_button(self, window):
        window.on_boards_found([_board()])
        item = window.selection_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        assert window.start_button.isEnabled()

    def test_unchecking_the_last_board_disables_the_start_button(self, window):
        window.on_boards_found([_board()])
        item = window.selection_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        item.setCheckState(Qt.CheckState.Unchecked)
        assert not window.start_button.isEnabled()

    def test_selected_urls_follows_the_checkboxes(self, window):
        window.on_boards_found([_board(), _board("/b2/", "Culinária", "340 pins")])
        window.selection_list.item(0).setCheckState(Qt.CheckState.Checked)
        assert window.selected_urls == ["https://www.pinterest.com/usuario/decoracao/"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
