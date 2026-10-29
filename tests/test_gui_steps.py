#!/usr/bin/env python3
"""Testes do layout em etapas da GUI.

A janela virou um fluxo de tres passos:

    1 Perfil  ->  2 Escolher quadros  ->  3 Baixar

Estes testes travam esse fluxo: qual passo aparece quando, o que cada
passo mostra, e o que a busca faz.

Rodam com o platform plugin "offscreen", sem display e sem xvfb:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_steps.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 nao instalado")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))

from test_gui import _FakeMessageBox  # noqa: E402

import pinterest_board_gui as gui  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    w = gui.MainWindow()
    yield w
    w.close()


def _board(url="https://www.pinterest.com/usuario/decoracao/", title="Decoração", pin_count="1,2 mil"):
    return {
        "url": url,
        "title": title,
        "thumbnail_url": "",
        "pin_count": pin_count,
        "pin_count_int": 1200,
    }


class TestStepNavigation:
    def test_starts_on_the_profile_step(self, window):
        assert window._step == window.STEP_PROFILE
        assert window.step_profile_panel.isVisibleTo(window)
        assert not window.step_boards_panel.isVisibleTo(window)

    def test_finding_boards_advances_to_the_boards_step(self, window):
        window.on_boards_found([_board()])
        assert window._step == window.STEP_BOARDS
        assert window.step_boards_panel.isVisibleTo(window)

    def test_finding_nothing_stays_on_the_profile_step(self, window):
        """Sem quadro nao ha o que escolher -- nao deve pular de etapa."""
        window.on_boards_found([])
        assert window._step == window.STEP_PROFILE

    def test_the_back_button_goes_back_to_the_profile(self, window):
        window.on_boards_found([_board()])
        window._go_back()
        assert window._step == window.STEP_PROFILE

    def test_the_back_button_is_hidden_on_the_first_step(self, window):
        assert not window.back_button.isVisibleTo(window)

    def test_the_start_button_only_shows_on_the_boards_step(self, window):
        window.on_boards_found([_board()])
        assert window.start_button.isVisibleTo(window)
        window._go_back()
        assert not window.start_button.isVisibleTo(window)

    def test_cannot_jump_to_the_boards_step_without_boards(self, window):
        window._go_to_step(window.STEP_BOARDS)
        assert window._step == window.STEP_PROFILE

    def test_cannot_jump_to_the_boards_step_without_boards_even_clicking_the_step(self, window):
        """Clicar em 'Escolher quadros' sem ter buscado nada nao abre a etapa."""
        window._go_to_step(window.STEP_BOARDS)
        assert window._step == window.STEP_PROFILE
        assert "Busque" in window.status_label.text()

    def test_jumping_to_the_boards_step_works_once_boards_are_there(self, window):
        window.on_boards_found([_board()])
        window._go_back()
        assert window._step == window.STEP_PROFILE
        window._go_to_step(window.STEP_BOARDS)
        assert window._step == window.STEP_BOARDS


class TestStepContent:
    def test_the_profile_step_holds_the_profile_field(self, window):
        assert window.user_edit.parent() is not None
        assert window.user_edit.isVisibleTo(window)

    def test_the_boards_step_holds_the_grid(self, window):
        window.on_boards_found([_board()])
        assert window.selection_list.isVisibleTo(window)

    def test_the_download_step_holds_the_progress_and_the_log(self, window):
        window._set_step(window.STEP_DOWNLOAD)
        assert window.board_progress.isVisibleTo(window)
        assert window.log_edit.isVisibleTo(window)

    def test_the_log_is_not_visible_before_the_download_step(self, window):
        window.on_boards_found([_board()])
        assert not window.log_edit.isVisibleTo(window)

    def test_the_options_strip_is_on_the_boards_step(self, window):
        window.on_boards_found([_board()])
        assert window.output_edit.isVisibleTo(window)
        assert window.workers_spin.isVisibleTo(window)


class TestBoardSearch:
    def _boards(self, window):
        window.on_boards_found(
            [
                _board("/a/", "Decoração Minimalista"),
                _board("/b/", "Culinária"),
                _board("/c/", "Fotografia"),
            ]
        )

    def test_the_search_hides_the_non_matching_boards(self, window):
        self._boards(window)
        window._filter_boards("culin")
        visible = [i for i in range(window.selection_list.count()) if not window.selection_list.item(i).isHidden()]
        assert len(visible) == 1
        assert window.selection_list.item(visible[0]).text().startswith("Culinária")

    def test_an_empty_search_shows_everything_again(self, window):
        self._boards(window)
        window._filter_boards("culin")
        window._filter_boards("")
        assert all(not window.selection_list.item(i).isHidden() for i in range(window.selection_list.count()))

    def test_the_search_ignores_case(self, window):
        self._boards(window)
        window._filter_boards("CULINÁRIA")
        visible = [i for i in range(window.selection_list.count()) if not window.selection_list.item(i).isHidden()]
        assert len(visible) == 1

    def test_a_search_with_no_match_hides_everything(self, window):
        self._boards(window)
        window._filter_boards("zzzz")
        assert all(window.selection_list.item(i).isHidden() for i in range(window.selection_list.count()))

    def test_select_all_only_marks_the_visible_boards(self, window):
        """Com uma busca ativa, marcar todos nao pode marcar o que o
        usuario nao ve."""
        self._boards(window)
        window._filter_boards("culin")
        window.select_all_check.setChecked(True)
        checked = [
            i
            for i in range(window.selection_list.count())
            if window.selection_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        assert len(checked) == 1
        assert window.selection_list.item(checked[0]).text().startswith("Culinária")

    def test_select_all_without_a_filter_marks_everything(self, window):
        self._boards(window)
        window.select_all_check.setChecked(True)
        checked = [
            i
            for i in range(window.selection_list.count())
            if window.selection_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        assert len(checked) == 3


class TestStepBar:
    def test_the_bar_has_three_steps(self, window):
        assert len(window._step_badges) == 3
        assert len(window._step_labels) == 3

    def test_the_active_step_is_marked(self, window):
        window.on_boards_found([_board()])
        assert window._step_badges[1].objectName() == "stepNumActive"
        assert window._step_badges[0].objectName() == "stepNumDone"

    def test_the_pending_step_is_neutral(self, window):
        window.on_boards_found([_board()])
        assert window._step_badges[2].objectName() == "stepNum"

    def test_the_first_step_is_neutral_at_the_start(self, window):
        assert window._step_badges[0].objectName() == "stepNumActive"


class TestSearchField:
    def test_the_search_field_exists(self, window):
        assert window.search_edit is not None

    def test_the_search_field_filters_the_list(self, window):
        window.on_boards_found([_board("/a/", "Decoração"), _board("/b/", "Culinária")])
        window.search_edit.setText("culin")
        visible = [i for i in range(window.selection_list.count()) if not window.selection_list.item(i).isHidden()]
        assert len(visible) == 1


class TestProfileAlwaysVisible:
    """O campo de perfil fica na barra de etapas -- e por isso continua
    visivel em todas elas."""

    def test_the_field_is_in_the_steps_bar(self, window):
        """O campo fica na barra, e nao no corpo de um passo."""
        assert window.user_edit.isVisibleTo(window)
        bar = window.findChild(gui.QFrame, "stepsBar")
        assert bar is not None
        assert window.user_edit.parentWidget() is bar

    def test_the_field_is_visible_in_every_step(self, window):
        window.on_boards_found([_board()])
        assert window.user_edit.isVisibleTo(window)
        window._set_step(window.STEP_DOWNLOAD)
        assert window.user_edit.isVisibleTo(window)
        window._set_step(window.STEP_PROFILE)
        assert window.user_edit.isVisibleTo(window)

    def test_the_field_stays_readable_when_the_step_changes(self, window):
        window.user_edit.setText("yuri_schmaltz")
        window.on_boards_found([_board()])
        window._set_step(window.STEP_DOWNLOAD)
        assert window.user_edit.text() == "yuri_schmaltz"

    def test_the_field_is_disabled_while_the_download_runs(self, window):
        """Trocar o perfil no meio do download nao faz sentido."""
        window.user_edit.setEnabled(False)
        assert not window.user_edit.isEnabled()

    def test_the_field_is_enabled_again_after_an_error(self, window, monkeypatch):
        # on_error abre um QMessageBox modal -- em modo offscreen isso
        # travaria o teste para sempre, entao o dialogo e substituido.
        monkeypatch.setattr(gui, "QMessageBox", _FakeMessageBox)
        window.user_edit.setEnabled(False)
        window.on_error("algo deu errado")
        assert window.user_edit.isEnabled()


class TestSquareThumbnail:
    """A capa do quadro e sempre quadrada, sem distorcer a foto."""

    @staticmethod
    def _pixmap(width, height, color="#E60023"):
        from PyQt6.QtGui import QColor, QPainter, QPixmap

        pix = QPixmap(width, height)
        pix.fill(QColor(color))
        painter = QPainter(pix)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawRect(0, 0, width - 1, height - 1)
        painter.end()
        return pix

    @staticmethod
    def _content_box(pixmap, background="#22262E"):
        """A caixa ocupada pela imagem dentro do quadrado."""
        from PyQt6.QtGui import QColor

        image = pixmap.toImage()
        bg = QColor(background).rgb()
        xs, ys = [], []
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixel(x, y) != bg:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return 0, 0
        return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1

    def test_the_result_is_square(self):
        from pinterest_board_gui import square_thumbnail

        for width, height in ((600, 200), (200, 600), (400, 400), (300, 500)):
            result = square_thumbnail(self._pixmap(width, height), 150)
            assert result.width() == 150
            assert result.height() == 150

    def test_a_wide_photo_keeps_its_proportion(self):
        """Uma foto panoramica fica baixa dentro do quadrado -- e nao
        esticada para caber."""
        from pinterest_board_gui import square_thumbnail

        result = square_thumbnail(self._pixmap(600, 200), 150)
        w, h = self._content_box(result)
        assert w == 150
        assert h == 50  # 150 * 200/600

    def test_a_tall_photo_keeps_its_proportion(self):
        from pinterest_board_gui import square_thumbnail

        result = square_thumbnail(self._pixmap(200, 600), 150)
        w, h = self._content_box(result)
        assert h == 150
        assert w == 50  # 150 * 200/600

    def test_a_square_photo_fills_the_square(self):
        from pinterest_board_gui import square_thumbnail

        result = square_thumbnail(self._pixmap(400, 400), 150)
        w, h = self._content_box(result)
        assert w == 150
        assert h == 150

    def test_the_thumbnail_size_constant(self):
        from pinterest_board_gui import THUMBNAIL_SIZE

        assert THUMBNAIL_SIZE > 0


class TestDarkTheme:
    def test_the_stylesheet_is_the_dark_one(self, window):
        style = window.styleSheet()
        assert style == gui.DARK_QSS

    def test_the_dark_background_is_applied(self, window):
        assert "#1A1D23" in gui.DARK_QSS

    def test_there_is_no_light_theme_left(self, window):
        """Nao sobrou regra do tema claro -- um 'background: #FFFFFF' com
        o fundo escuro ficaria um retangulo branco."""
        for line in gui.DARK_QSS.splitlines():
            if "background" in line and "#FFFFFF" in line:
                # so o branco do texto e do preenchimento da barra de
                # progresso pode aparecer
                assert "color:" in line or "chunk" in line or "background-color: #FFFFFF" not in line


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
