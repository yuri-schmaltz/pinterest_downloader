"""Interface gráfica em PyQt6 para o downloader de quadros do Pinterest."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List

from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pinterest_board_dl import (
    BoardMetadata,
    DownloadOptions,
    PrivateProfileError,
    collect_board_urls,
    download_user_boards,
)


class DownloadCancelled(Exception):
    """Sinaliza cancelamento manual do usuário."""


class DownloadWorker(QThread):
    log_message = pyqtSignal(str)
    board_started = pyqtSignal(str, str)
    download_started = pyqtSignal(str, int)
    download_progress = pyqtSignal(str, int, int, int)
    board_finished = pyqtSignal(str, int, int, str, int, int)
    boards_found = pyqtSignal(list)
    overall_progress = pyqtSignal(int, int)
    finished_with_totals = pyqtSignal(int, int)
    manual_login_requested = pyqtSignal(str, str)
    error = pyqtSignal(str)
    pins_collected = pyqtSignal(str, int)
    cancelled = pyqtSignal()

    def __init__(
        self,
        options: DownloadOptions,
        username_or_url: str,
        discovery_mode: bool = False,
        selected_boards: List[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.options = options
        self.username_or_url = username_or_url
        self.discovery_mode = discovery_mode
        self.selected_boards = selected_boards
        self._manual_event = threading.Event()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._manual_event.set()

    def resume_manual_login(self) -> None:
        self._manual_event.set()

    # --- callbacks ---
    def _manual_login_wait(self, board_url: str) -> None:
        if self._cancelled:
            raise DownloadCancelled()
        self._manual_event.clear()
        message = (
            "Faça login na janela do navegador aberta pelo Playwright e confirme que está no quadro correto. "
            "Quando concluir o login, clique em 'Continuar' na aplicação."
        )
        self.manual_login_requested.emit(board_url, message)
        self._manual_event.wait()
        if self._cancelled:
            raise DownloadCancelled()

    def _status_callback(self, stage: str, data: dict) -> None:
        if self._cancelled:
            raise DownloadCancelled()
        if stage == "log":
            message = data.get("message")
            if message:
                self.log_message.emit(message)
        elif stage == "board_start":
            self.board_started.emit(data.get("board_url", ""), data.get("output_dir", ""))
        elif stage == "download_start":
            self.download_started.emit(data.get("board_url", ""), data.get("total", 0))
        elif stage == "download_progress":
            self.download_progress.emit(
                data.get("board_url", ""),
                data.get("current", 0),
                data.get("total", 0),
                data.get("downloaded", 0),
            )
        elif stage == "board_complete":
            self.board_finished.emit(
                data.get("board_url", ""),
                data.get("downloaded", 0),
                data.get("total", 0),
                data.get("output_dir", ""),
                data.get("verified", 0),
                data.get("expected", 0) or 0,
            )
        elif stage == "boards_found":
            boards = data.get("boards", [])
            self.boards_found.emit(list(boards))
        elif stage == "overall_progress":
            self.overall_progress.emit(data.get("current", 0), data.get("total", 0))
        elif stage == "manual_login_required":
            message = data.get("message")
            if message:
                self.log_message.emit(message)
        elif stage == "resolve_start":
            total = data.get("total", 0)
            if total:
                self.log_message.emit(f"Resolvendo imagens (total: {total})…")
        elif stage == "resolve_complete":
            found = data.get("found", 0)
            total = data.get("total", 0)
            self.log_message.emit(f"Resolução concluída ({found}/{total}).")
        elif stage == "pins_collected":
            self.pins_collected.emit(data.get("board_url", ""), data.get("count", 0))

    def run(self) -> None:
        try:
            totals = [0, 0]
            if not self.username_or_url:
                raise ValueError("Usuário ou URL não informado.")

            if self.discovery_mode:
                self.log_message.emit(f"Buscando quadros de: {self.username_or_url}…")
                boards = collect_board_urls(
                    self.username_or_url,
                    headless=self.options.headless,
                    scroll_pause=self.options.scroll_pause,
                    manual_login=self.options.manual_login,
                    manual_login_handler=lambda: self._manual_login_wait(self.username_or_url),
                )
                self.boards_found.emit(boards)
                return

            if self.selected_boards:
                # Seletivos: ignorar busca automática
                boards_to_process = self.selected_boards
            else:
                # Comportamento padrão: busca automática de todos os quadros
                results = download_user_boards(
                    self.username_or_url,
                    self.options,
                    status_cb=self._status_callback,
                    manual_login_handler=self._manual_login_wait if self.options.manual_login else None,
                )
                for res in results:
                    totals[0] += res.downloaded
                    totals[1] += res.total
                self.finished_with_totals.emit(totals[0], totals[1])
                return

            # Se chegamos aqui, temos boards_to_process (selecionados)
            from pinterest_board_dl import create_session, download_board, sync_playwright

            with sync_playwright() as p:
                browser_shared = p.chromium.launch(headless=self.options.headless)
                try:
                    self.overall_progress.emit(0, len(boards_to_process))
                    session = create_session()
                    for idx, board in enumerate(boards_to_process, 1):
                        if self._cancelled:
                            raise DownloadCancelled()

                        res = download_board(
                            board,
                            self.options,
                            session=session,
                            status_cb=self._status_callback,
                            manual_login_handler=self._manual_login_wait if self.options.manual_login else None,
                            browser_shared=browser_shared,
                        )
                        totals[0] += res.downloaded
                        totals[1] += res.total
                        self.overall_progress.emit(idx, len(boards_to_process))
                finally:
                    browser_shared.close()

            self.finished_with_totals.emit(totals[0], totals[1])
        except DownloadCancelled:
            self.cancelled.emit()
        except PrivateProfileError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # pragma: no cover - exibição no GUI
            self.error.emit(str(exc))


# ---------- UI Constants ----------

# Lado da miniatura do quadro. A capa e sempre quadrada.
THUMBNAIL_SIZE = 150

# O app e escuro. Nao ha tema claro: uma unica paleta, aplicada por
# folha de estilo, para que nenhum widget fique com a cor do sistema.

DARK_QSS = """
/* ---------- base ---------- */
QWidget {
    background-color: #1A1D23;
    color: #E6E8EC;
    font-size: 13px;
}
QToolTip {
    background-color: #2A2F38;
    color: #E6E8EC;
    border: 1px solid #3A414D;
    padding: 4px;
}

/* ---------- campos ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit {
    background-color: #22262E;
    border: 1px solid #3A414D;
    border-radius: 4px;
    padding: 5px;
    color: #E6E8EC;
    selection-background-color: #E60023;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border: 1px solid #E60023;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: #1E222A;
    color: #6B7280;
}
QLineEdit::placeholder { color: #6B7280; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #2A2F38;
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover { background-color: #3A414D; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #9AA1AC;
    width: 0; height: 0;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #9AA1AC;
    width: 0; height: 0;
}

/* ---------- botoes ---------- */
QPushButton {
    border: none;
    border-radius: 5px;
    padding: 8px 15px;
    color: #FFFFFF;
    font-weight: bold;
    background-color: #3A414D;
}
QPushButton:hover { background-color: #4A5261; }
QPushButton:pressed { background-color: #2A2F38; }
QPushButton:disabled {
    background-color: #262B33;
    color: #6B7280;
}
#btn_start { background-color: #E60023; }
#btn_start:hover { background-color: #FF2E4D; }
#btn_start:disabled { background-color: #5C2027; color: #8A7075; }
#btn_list { background-color: #0076D3; }
#btn_list:hover { background-color: #2E8FE8; }
#btn_list:disabled { background-color: #1E3A52; color: #6B8AA5; }
#btn_cancel { background-color: #3A414D; color: #E6E8EC; }
#btn_cancel:hover { background-color: #4A5261; }
#btn_cancel:enabled { background-color: #FF4D4D; color: #FFFFFF; }
#btn_cancel:enabled:hover { background-color: #FF6B6B; }
#btn_back { background-color: #2A2F38; color: #E6E8EC; }
#btn_back:hover { background-color: #3A414D; }
#btn_back:disabled { background-color: #22262E; color: #6B7280; }

/* ---------- caixas de selecao ---------- */
QCheckBox { color: #E6E8EC; spacing: 8px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4A5261;
    border-radius: 3px;
    background-color: #22262E;
}
QCheckBox::indicator:hover { border: 1px solid #E60023; }
QCheckBox::indicator:checked {
    background-color: #E60023;
    border: 1px solid #E60023;
    image: none;
}
QCheckBox:disabled { color: #6B7280; }
QCheckBox::indicator:disabled { border: 1px solid #313640; background-color: #1E222A; }

/* ---------- barras de rolagem ---------- */
QScrollBar:vertical {
    background: #1A1D23;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3A414D;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #4A5261; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1A1D23;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #3A414D;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---------- barra de etapas ---------- */
#stepsBar {
    background-color: #22262E;
    border-bottom: 1px solid #313640;
}
#stepNum {
    background-color: #313640;
    color: #9AA1AC;
    border-radius: 13px;
    font-weight: bold;
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
}
#stepNumActive {
    background-color: #E60023;
    color: #FFFFFF;
    border-radius: 13px;
    font-weight: bold;
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
}
#stepNumDone {
    background-color: #1E4D2B;
    color: #5FD37E;
    border-radius: 13px;
    font-weight: bold;
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
}
#stepLabel { color: #9AA1AC; }
#stepLabelActive { color: #E6E8EC; font-weight: bold; }
#stepLabelDone { color: #5FD37E; }
#stepLine { background-color: #313640; max-height: 1px; min-height: 1px; border: none; }
#statusText { color: #9AA1AC; }
QToolButton#btn_link {
    background: transparent;
    border: none;
    color: #4DA3F0;
    font-weight: bold;
    padding: 2px 4px;
    text-align: left;
}
QToolButton#btn_link:hover { color: #7CBEFF; }

/* ---------- corpo ---------- */
#stepTitle { color: #E6E8EC; font-size: 15px; font-weight: bold; }
#stepHint { color: #9AA1AC; }
#optionsStrip { background-color: #22262E; border: 1px solid #313640; border-radius: 10px; }
#stripLabel { color: #9AA1AC; font-size: 11px; font-weight: bold; }
#footerBar { background-color: #22262E; border-top: 1px solid #313640; }
#progressCard { background-color: #22262E; border: 1px solid #313640; border-radius: 10px; }
#logCard { background-color: #22262E; border: 1px solid #313640; border-radius: 10px; }
QToolButton#disclosure {
    border: none;
    background: transparent;
    color: #E6E8EC;
    font-weight: bold;
    padding: 4px 0;
    text-align: left;
}
QToolButton#disclosure:hover { color: #4DA3F0; }

/* ---------- progresso ---------- */
QProgressBar {
    background-color: #1A1D23;
    border: 1px solid #3A414D;
    border-radius: 10px;
    text-align: center;
    font-weight: bold;
    color: #E6E8EC;
}
QProgressBar::chunk {
    background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #E60023, stop:1 #FF2E4D);
    border-radius: 9px;
}

/* ---------- lista de quadros ---------- */
QListWidget {
    background-color: #1A1D23;
    border: 1px solid #313640;
    border-radius: 10px;
    color: #E6E8EC;
    padding: 6px;
}
QListWidget::item { color: #E6E8EC; border-radius: 6px; }
QListWidget::item:hover { background-color: #262B33; }
QListWidget::item:selected { background-color: #3A1F24; color: #FFFFFF; }

/* ---------- menus ---------- */
QMenu {
    background-color: #22262E;
    border: 1px solid #3A414D;
    color: #E6E8EC;
}
QMenu::item:selected { background-color: #E60023; }
"""


def square_thumbnail(pixmap: QPixmap, size: int, background: str = "#22262E") -> QPixmap:
    """Capa do quadro num quadrado, sem alterar as proporcoes da imagem.

    A imagem e escalada para CABER no quadrado (KeepAspectRatio), o que
    preserva a proporcao original; o que sobra nas laterais ou em cima e
    embaixo fica com a cor de fundo. Escalar preenchendo (ByExpanding)
    cortaria a foto -- e a miniatura do quadro e a primeira coisa que o
    usuario ve, entao nao pode perder informacao.
    """
    square = QPixmap(size, size)
    square.fill(QColor(background))

    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(square)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return square


# O layout em etapas: barra de passos no topo, uma tela por passo, e
# um rodape com as acoes.
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pinterest Board Downloader")
        self.resize(1100, 750)
        self.worker: DownloadWorker | None = None
        self.boards_metadata: List[BoardMetadata] = []
        self.selected_urls: List[str] = []
        self.board_items: dict[str, QListWidgetItem] = {}
        self.url_to_title: dict[str, str] = {}

        # Aplicar estilos
        self.setStyleSheet(DARK_QSS)

        # Set application icon
        self._set_window_icon()
        self._build_ui()

    # --- UI helpers ---
    def _set_window_icon(self) -> None:
        """Define o ícone da aplicação."""
        icon_path = Path(__file__).parent.parent / "assets" / "icon.svg"

        if icon_path.exists():
            # Renderizar SVG para QPixmap
            renderer = QSvgRenderer(str(icon_path))
            pixmap = QPixmap(256, 256)
            pixmap.fill(Qt.GlobalColor.transparent)

            from PyQt6.QtGui import QPainter

            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()

            # Definir ícone
            icon = QIcon(pixmap)
            self.setWindowIcon(icon)

            # Definir também para o QApplication (barra de tarefas)
            app_instance = QApplication.instance()
            if isinstance(app_instance, QApplication):
                app_instance.setWindowIcon(icon)

    # --- layout em etapas -------------------------------------------
    #
    # A janela tem tres passos: 1) perfil, 2) escolher quadros,
    # 3) baixar. Cada passo e uma tela propria; a barra do topo mostra
    # onde voce esta, e o rodape traz as acoes do passo atual.
    #
    # Os nomes dos widgets nao mudaram -- e o que a GUI inteira (e os
    # testes) usa: user_edit, selection_list, start_button, log_edit...
    # So a organizacaovisual muda.

    STEP_PROFILE = 1
    STEP_BOARDS = 2
    STEP_DOWNLOAD = 3

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_steps_bar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.step_profile_panel = self._build_step_profile()
        self.step_boards_panel = self._build_step_boards()
        self.step_download_panel = self._build_step_download()

        self._step_panels = {
            self.STEP_PROFILE: self.step_profile_panel,
            self.STEP_BOARDS: self.step_boards_panel,
            self.STEP_DOWNLOAD: self.step_download_panel,
        }
        # O painel de selecao e o passo 2. O atributo continua existindo
        # porque e o que a GUI inteira (e os testes) referencia.
        self.selection_panel = self.step_boards_panel
        for panel in self._step_panels.values():
            body_layout.addWidget(panel)
            panel.hide()

        root.addWidget(body, 1)
        root.addWidget(self._build_footer())

        self.setCentralWidget(central)
        self._set_step(self.STEP_PROFILE)

    def _build_steps_bar(self) -> QWidget:
        """Barra de etapas no topo."""
        bar = QFrame()
        bar.setObjectName("stepsBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(0)

        self._step_badges: list[QLabel] = []
        self._step_labels: list[QLabel] = []
        self._step_buttons: list[QToolButton] = []

        steps = (("1", "Perfil"), ("2", "Escolher quadros"), ("3", "Baixar"))
        for i, (num, name) in enumerate(steps):
            if i:
                line = QFrame()
                line.setObjectName("stepLine")
                line.setFixedHeight(1)
                line.setMinimumWidth(40)
                layout.addWidget(line, 1)
                layout.addSpacing(14)

            badge = QLabel(num)
            badge.setObjectName("stepNum")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(28, 28)
            layout.addWidget(badge)
            layout.addSpacing(8)

            # Os passos 1 e 2 sao clicaveis; o 3 e o resultado, entao
            # nao faz sentido pular para ele antes da hora.
            label = QLabel(name)
            label.setObjectName("stepLabel")
            if i < 2:
                button = QToolButton()
                button.setText(name)
                button.setObjectName("btn_link")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                button.clicked.connect(lambda _checked=False, target=i + 1: self._go_to_step(target))
                layout.addWidget(button)
                self._step_buttons.append(button)
            else:
                layout.addWidget(label)
                self._step_buttons.append(None)  # type: ignore[arg-type]

            self._step_badges.append(badge)
            self._step_labels.append(label)

        layout.addSpacing(28)
        layout.addStretch()

        # O perfil fica na barra, e nao no corpo: assim ele continua
        # visivel em todas as etapas -- voce ve o que esta baixando sem
        # precisar voltar. Dar Enter no campo refaz a busca.
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Usuário ou link do perfil")
        self.user_edit.setFixedWidth(260)
        self.user_edit.returnPressed.connect(self.start_discovery)
        layout.addWidget(self.user_edit)

        layout.addSpacing(16)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("statusText")
        self.status_label.setMinimumWidth(120)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.status_label)
        return bar

    def _build_step_profile(self) -> QWidget:
        """Passo 1: de qual perfil vamos buscar os quadros."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 56, 24, 24)
        layout.setSpacing(10)
        layout.addStretch()

        title = QLabel("De qual perfil do Pinterest?")
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        hint = QLabel("Escreva o usuário ou a URL do perfil no campo acima, à direita.\n" "Aceita as duas formas.")
        hint.setObjectName("stepHint")
        layout.addWidget(hint)
        layout.addSpacing(16)

        self.list_boards_button = QPushButton("Listar Quadros")
        self.list_boards_button.setObjectName("btn_list")
        self.list_boards_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list_boards_button.setMinimumHeight(44)
        self.list_boards_button.setFixedWidth(220)
        self.list_boards_button.clicked.connect(self.start_discovery)
        layout.addWidget(self.list_boards_button, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addStretch()
        return panel

    def _build_step_boards(self) -> QWidget:
        """Passo 2: a grade de quadros e as opcoes de download."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 18, 24, 10)
        layout.setSpacing(10)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Escolha os quadros que quer baixar")
        title.setObjectName("stepTitle")
        head_layout.addWidget(title)
        head_layout.addStretch()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar quadro…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(240)
        self.search_edit.textChanged.connect(self._filter_boards)
        head_layout.addWidget(self.search_edit)

        self.select_all_check = QCheckBox("Selecionar Todos")
        self.select_all_check.stateChanged.connect(self._toggle_select_all)
        head_layout.addWidget(self.select_all_check)

        layout.addWidget(head)

        self.selection_list = QListWidget()
        self.selection_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.selection_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.selection_list.setMovement(QListWidget.Movement.Static)
        self.selection_list.setFlow(QListWidget.Flow.LeftToRight)
        self.selection_list.setWrapping(True)
        self.selection_list.setWordWrap(True)
        self.selection_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.selection_list.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.selection_list.setGridSize(QSize(THUMBNAIL_SIZE + 36, THUMBNAIL_SIZE + 62))
        self.selection_list.setSpacing(12)
        self.selection_list.itemChanged.connect(self._update_selection_state)
        layout.addWidget(self.selection_list, 1)

        layout.addWidget(self._build_options_strip())

        self.info_selection_label = QLabel("Nenhum quadro carregado.")
        layout.addWidget(self.info_selection_label)
        return panel

    def _build_options_strip(self) -> QWidget:
        """Faixa de opcoes abaixo da grade: destino e os ajustes."""
        strip = QFrame()
        strip.setObjectName("optionsStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        layout.addWidget(self._strip_label("Destino"))
        self.output_edit = QLineEdit(str(Path("pins").resolve()))
        self.output_edit.setMinimumWidth(220)
        layout.addWidget(self.output_edit, 3)

        select_button = QPushButton("Selecionar…")
        select_button.clicked.connect(self._select_output_dir)
        layout.addWidget(select_button)

        layout.addWidget(self._strip_label("Workers"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(16)
        self.workers_spin.setToolTip(
            "Número de downloads simultâneos dentro de um mesmo quadro.\n"
            "Recomendado: 16-32. Valores muito altos podem causar erros de rede."
        )
        layout.addWidget(self.workers_spin)

        layout.addWidget(self._strip_label("Máx. pins"))
        self.max_pins_spin = QSpinBox()
        self.max_pins_spin.setRange(0, 1000000)
        self.max_pins_spin.setSpecialValueText("Sem limite")
        layout.addWidget(self.max_pins_spin)

        # O resto fica escondido ate o usuario pedir.
        more = QWidget()
        more_layout = QHBoxLayout(more)
        more_layout.setContentsMargins(0, 0, 0, 0)
        more_layout.setSpacing(12)

        self.scroll_pause_spin = QDoubleSpinBox()
        self.scroll_pause_spin.setDecimals(2)
        self.scroll_pause_spin.setRange(0.1, 10.0)
        self.scroll_pause_spin.setValue(1.2)
        more_layout.addWidget(self._strip_field("Pausa (s)", self.scroll_pause_spin))

        self.boards_workers_spin = QSpinBox()
        self.boards_workers_spin.setRange(1, 8)
        self.boards_workers_spin.setValue(1)
        self.boards_workers_spin.setToolTip(
            "Número de quadros baixados ao mesmo tempo.\n" "Recomendado: 1-2. Aumentar muito consome muita CPU/RAM."
        )
        more_layout.addWidget(self._strip_field("Quadros em paralelo", self.boards_workers_spin))

        self.manual_login_check = QCheckBox("Login Manual (perfis privados)")
        more_layout.addWidget(self.manual_login_check)
        more_layout.addStretch()

        layout.addWidget(self._build_disclosure("Mais opções", more), 1)
        return strip

    def _build_disclosure(self, title: str, content: QWidget) -> QWidget:
        """Bloco que abre e fecha (o 'Mais opções')."""
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(2)

        toggle = QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.RightArrow)
        toggle.setObjectName("disclosure")

        def on_toggle(checked: bool) -> None:
            content.setVisible(checked)
            toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        toggle.toggled.connect(on_toggle)
        content.setVisible(False)

        holder_layout.addWidget(toggle)
        holder_layout.addWidget(content)
        return holder

    def _build_step_download(self) -> QWidget:
        """Passo 3: o andamento e o log."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Baixando")
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("progressCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        self.current_board_label = QLabel("Quadro atual")
        card_layout.addWidget(self.current_board_label)

        self.board_progress = QProgressBar()
        self.board_progress.setFormat("%v / %m imagens")
        self.board_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.board_progress)

        total_label = QLabel("Total de quadros")
        total_label.setStyleSheet("color: #6B7280;")
        card_layout.addWidget(total_label)

        self.overall_progress = QProgressBar()
        self.overall_progress.setFormat("%v / %m quadros")
        self.overall_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.overall_progress)
        layout.addWidget(card)

        log_card = QFrame()
        log_card.setObjectName("logCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 12, 16, 12)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        log_layout.addWidget(self.log_edit)
        layout.addWidget(log_card, 1)
        return panel

    def _build_footer(self) -> QWidget:
        """Rodape com as acoes do passo atual."""
        footer = QFrame()
        footer.setObjectName("footerBar")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(10)

        self.back_button = QPushButton("← Voltar")
        self.back_button.setObjectName("btn_back")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self._go_back)
        layout.addWidget(self.back_button)

        layout.addStretch()

        self.start_button = QPushButton("Iniciar download")
        self.start_button.setObjectName("btn_start")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setMinimumWidth(170)
        self.start_button.clicked.connect(self.start_download)
        layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setObjectName("btn_cancel")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setMinimumWidth(110)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        layout.addWidget(self.cancel_button)
        return footer

    def _strip_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("stripLabel")
        return label

    def _strip_field(self, label: str, widget: QWidget) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        caption = QLabel(label)
        caption.setObjectName("stripLabel")
        column.addWidget(caption)
        column.addWidget(widget)
        return box

    # --- navegacao entre passos -------------------------------------

    def _set_step(self, step: int) -> None:
        """Mostra um passo e atualiza a barra e o rodape."""
        self._step = step
        for number, panel in self._step_panels.items():
            panel.setVisible(number == step)

        for index, badge in enumerate(self._step_badges):
            number = index + 1
            if number == step:
                badge.setObjectName("stepNumActive")
                self._step_labels[index].setObjectName("stepLabelActive")
            elif number < step:
                badge.setObjectName("stepNumDone")
                self._step_labels[index].setObjectName("stepLabelDone")
            else:
                badge.setObjectName("stepNum")
                self._step_labels[index].setObjectName("stepLabel")
            # setObjectName troca o estilo: e preciso reaplicar.
            badge.style().unpolish(badge)
            badge.style().polish(badge)
            self._step_labels[index].style().unpolish(self._step_labels[index])
            self._step_labels[index].style().polish(self._step_labels[index])

        # O rotulo do passo ativo precisa acompanhar o botao, que tem
        # estilo proprio.
        for index, button in enumerate(self._step_buttons):
            if button is None:
                continue
            active = index + 1 == step
            button.setStyleSheet(
                f"color: {'#E6E8EC' if active else '#4DA3F0'}; font-weight: {'bold' if active else 'normal'};"
            )
            self._step_labels[index].setText(button.text())

        running = bool(self.worker and self.worker.isRunning())
        self.back_button.setVisible(step != self.STEP_PROFILE)
        self.back_button.setEnabled(step == self.STEP_BOARDS or not running)
        self.start_button.setVisible(step == self.STEP_BOARDS)
        self.cancel_button.setVisible(step == self.STEP_DOWNLOAD)

    def _go_to_step(self, step: int) -> None:
        """Vai para um passo, respeitando o que ja foi feito."""
        if step == self.STEP_BOARDS and not self.boards_metadata:
            self.status_label.setText("Busque os quadros primeiro.")
            return
        if step == self.STEP_DOWNLOAD and self.worker and self.worker.isRunning():
            return
        self._set_step(step)

    def _go_back(self) -> None:
        """O botao 'Voltar'."""
        if self._step == self.STEP_DOWNLOAD:
            if self.worker and self.worker.isRunning():
                return
            self._set_step(self.STEP_BOARDS)
        elif self._step == self.STEP_BOARDS:
            self._set_step(self.STEP_PROFILE)

    def _filter_boards(self, text: str) -> None:
        """Esconde os quadros que nao casam com a busca."""
        needle = text.strip().lower()
        for i in range(self.selection_list.count()):
            item = self.selection_list.item(i)
            if item is None:
                continue
            item.setHidden(bool(needle) and needle not in item.text().lower())

    # --- actions ---
    def _select_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Selecione a pasta de saída", self.output_edit.text())
        if directory:
            self.output_edit.setText(directory)

    def start_discovery(self) -> None:
        if self.worker and self.worker.isRunning():
            return

        username = self.user_edit.text().strip()
        if not username:
            QMessageBox.warning(self, "Dados incompletos", "Informe o usuário ou URL do perfil.")
            return

        out_root = self.output_edit.text().strip() or str(Path("pins").resolve())
        options = DownloadOptions(
            out_root=out_root,
            headless=not self.manual_login_check.isChecked(),
            manual_login=self.manual_login_check.isChecked(),
            scroll_pause=self.scroll_pause_spin.value(),
        )

        self.log_edit.clear()
        self.selection_list.clear()
        self.boards_metadata = []
        self.info_selection_label.setText("Buscando quadros…")

        self.worker = DownloadWorker(options=options, username_or_url=username, discovery_mode=True)
        self._connect_worker_signals()
        self.worker.start()

        self.list_boards_button.setEnabled(False)
        self.start_button.setEnabled(False)

    def start_download(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Download em andamento", "Aguarde o término antes de iniciar outro download.")
            return

        username = self.user_edit.text().strip()
        if not username:
            QMessageBox.warning(self, "Dados incompletos", "Informe o usuário ou URL do perfil do Pinterest.")
            return

        # Verificar se algo foi selecionado
        if not self.selected_urls:
            QMessageBox.warning(self, "Seleção vazia", "Selecione ao menos um quadro para baixar.")
            return

        out_root = self.output_edit.text().strip() or str(Path("pins").resolve())
        os.makedirs(out_root, exist_ok=True)

        options = DownloadOptions(
            out_root=out_root,
            headless=not self.manual_login_check.isChecked(),
            manual_login=self.manual_login_check.isChecked(),
            max_pins=self.max_pins_spin.value() or None,
            scroll_pause=self.scroll_pause_spin.value(),
            workers=self.workers_spin.value(),
            boards_workers=self.boards_workers_spin.value(),
        )

        self.log_edit.clear()
        self.board_progress.reset()
        self.overall_progress.reset()

        self.status_label.setText("Iniciando…")

        self.worker = DownloadWorker(options=options, username_or_url=username, selected_boards=self.selected_urls)
        self._connect_worker_signals()
        self.worker.start()

        self.start_button.setEnabled(False)
        self.list_boards_button.setEnabled(False)
        self.user_edit.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._set_step(self.STEP_DOWNLOAD)

    def _connect_worker_signals(self) -> None:
        assert self.worker is not None
        self.worker.log_message.connect(self.append_log)
        self.worker.board_started.connect(self.on_board_started)
        self.worker.download_started.connect(self.on_download_started)
        self.worker.download_progress.connect(self.on_download_progress)
        self.worker.board_finished.connect(self.on_board_finished)
        self.worker.boards_found.connect(self.on_boards_found)
        self.worker.overall_progress.connect(self.on_overall_progress)
        self.worker.finished_with_totals.connect(self.on_finished_with_totals)
        self.worker.error.connect(self.on_error)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.manual_login_requested.connect(self.on_manual_login_requested)
        self.worker.pins_collected.connect(self.on_pins_collected)

    def cancel_download(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.append_log("Cancelamento solicitado. Aguarde o término do processo atual…")
            self.status_label.setText("Cancelando…")
            self.cancel_button.setEnabled(False)

    # --- slots ---
    def append_log(self, message: str) -> None:
        self.log_edit.append(message)

    def on_board_started(self, board_url: str, output_dir: str) -> None:
        norm_url = board_url.rstrip("/") + "/"
        title = self.url_to_title.get(norm_url, board_url)
        self.current_board_label.setText(f"Quadro atual ({title})")
        self.status_label.setText(f"Processando quadro: {title}")

    def on_download_started(self, board_url: str, total: int) -> None:
        if total <= 0:
            self.board_progress.setMaximum(1)
            self.board_progress.setValue(0)
        else:
            self.board_progress.setMaximum(total)
            self.board_progress.setValue(0)

    def on_download_progress(self, board_url: str, current: int, total: int, downloaded: int) -> None:
        self.board_progress.setMaximum(max(total, 1))
        self.board_progress.setValue(min(current, total))

    def on_board_finished(
        self, board_url: str, downloaded: int, total: int, output_dir: str, verified: int = 0, expected: int = 0
    ) -> None:
        # Update selection list as well
        self._update_selection_item_count(board_url, verified)

        self.board_progress.setValue(self.board_progress.maximum())

    def on_pins_collected(self, board_url: str, count: int) -> None:
        self.append_log(f"  Confirmados {count} pins reais no quadro.")
        self._update_selection_item_count(board_url, count)

    def _update_selection_item_count(self, board_url: str, count: int) -> None:
        norm_url = board_url.strip().rstrip("/").lower()
        for i in range(self.selection_list.count()):
            item = self.selection_list.item(i)
            if item is None:
                continue
            stored_url = item.data(Qt.ItemDataRole.UserRole) or ""
            stored_norm = stored_url.strip().rstrip("/").lower()

            if stored_norm == norm_url:
                title = self.url_to_title.get(stored_url, board_url)
                # Ensure title is not just url if we have a better one
                if title == stored_url and self.url_to_title:
                    # Try to find original title from board metadata list if needed
                    for b in self.boards_metadata:
                        if b["url"] == stored_url:
                            title = b["title"]
                            break

                item.setText(f"{title}\n({count} Pins)")
                # Force update visual
                item.setData(Qt.ItemDataRole.DisplayRole, f"{title}\n({count} Pins)")
                break

    def on_boards_found(self, boards: List[BoardMetadata]) -> None:
        self.boards_metadata = boards
        self.selection_list.clear()
        self.selected_urls = []

        if not boards:
            self.info_selection_label.setText("Nenhum quadro encontrado.")
            self.list_boards_button.setEnabled(True)
            self.user_edit.setEnabled(True)
            self.start_button.setEnabled(False)
            # Sem quadro nao ha o que escolher: fica no passo 1.
            self._set_step(self.STEP_PROFILE)
            return

        import requests

        for b in boards:
            # Limpeza do título (remover quebras de linha e espaços extras).
            # O Pinterest devolve títulos com "\n" e espaços duplicados;
            # " ".join(split()) colapsa qualquer sequência de espaço em uma.
            title = " ".join(b["title"].split())

            # Limpeza do pin_count (garantir que não tenha caracteres como "," no início)
            pin_count = b.get("pin_count", "").strip()
            if pin_count.startswith(","):
                pin_count = pin_count[1:].strip()

            # Texto do item: Título + (N Pins)
            pin_text = f" ({pin_count})" if pin_count else ""
            item = QListWidgetItem(f"{title}{pin_text}")

            # Normalizar URL para garantir mapeamento correto no histórico
            norm_url = b["url"].rstrip("/") + "/"
            item.setData(Qt.ItemDataRole.UserRole, norm_url)  # Guardar URL internamente
            self.url_to_title[norm_url] = title  # Armazenar para o histórico
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)

            # Thumbnail quadrada, sem distorcer a foto original
            if b["thumbnail_url"]:
                try:
                    resp = requests.get(b["thumbnail_url"], timeout=3)
                    if resp.status_code == 200:
                        pix = QPixmap()
                        pix.loadFromData(resp.content)
                        if not pix.isNull():
                            item.setIcon(QIcon(square_thumbnail(pix, THUMBNAIL_SIZE)))
                except Exception:
                    pass

            self.selection_list.addItem(item)

        self.info_selection_label.setText(f"{len(boards)} quadros encontrados.")
        self.list_boards_button.setEnabled(True)
        self.user_edit.setEnabled(True)
        self.start_button.setEnabled(False)
        # Ha quadros para escolher: vai para o passo 2.
        self._set_step(self.STEP_BOARDS)

    def _toggle_select_all(self, state: int) -> None:
        cs = Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
        for i in range(self.selection_list.count()):
            item = self.selection_list.item(i)
            # Com uma busca ativa, "selecionar todos" marca so o que
            # esta visivel -- marcar o que o usuario nao ve seria
            # surpreendente.
            if item is not None and not item.isHidden():
                item.setCheckState(cs)
        self._update_selection_state()

    def _update_selection_state(self) -> None:
        self.selected_urls = []
        for i in range(self.selection_list.count()):
            item = self.selection_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                # Recuperar URL dos dados do usuário
                url = item.data(Qt.ItemDataRole.UserRole)
                if url:
                    self.selected_urls.append(url)

        sel_count = len(self.selected_urls)
        total_count = len(self.boards_metadata)
        self.info_selection_label.setText(f"{sel_count} selecionados de {total_count}")
        self.start_button.setEnabled(sel_count > 0)

    def on_overall_progress(self, current: int, total: int) -> None:
        self.overall_progress.setMaximum(max(total, 1))
        self.overall_progress.setValue(current)

    def on_finished_with_totals(self, downloaded: int, total: int) -> None:
        self.status_label.setText(f"Concluído: {downloaded}/{total} imagens baixadas.")
        self.append_log(f"Total geral: {downloaded}/{total} imagens.")
        self.start_button.setEnabled(True)
        self.list_boards_button.setEnabled(True)
        self.user_edit.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None
        self._set_step(self.STEP_DOWNLOAD)

    def on_cancelled(self) -> None:
        self.status_label.setText("Operação cancelada.")
        self.append_log("Operação cancelada pelo usuário.")
        self.start_button.setEnabled(True)
        self.list_boards_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None

    def on_error(self, message: str) -> None:
        # Detectar se é erro de perfil privado para dar tratamento especial
        is_private = "privado" in message.lower() or "private" in message.lower()

        if is_private:
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Icon.Warning)
            dlg.setWindowTitle("Perfil Privado Detectado")
            dlg.setText(
                "🔒 O perfil informado é <b>privado</b>.<br><br>"
                "Para acessar quadros de um perfil privado, você precisa "
                "fazer login no Pinterest.<br><br>"
                "Deseja ativar o <b>Login Manual</b> e tentar novamente?"
            )
            dlg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dlg.setDefaultButton(QMessageBox.StandardButton.Yes)
            result = dlg.exec()

            if result == QMessageBox.StandardButton.Yes:
                self.manual_login_check.setChecked(True)
                self.status_label.setText("Login Manual ativado. Clique em 'Listar Quadros' novamente.")
                self.info_selection_label.setText("Perfil privado — Login Manual necessário.")
            else:
                self.status_label.setText("Perfil privado. Ative 'Login Manual' para acessar.")
                self.info_selection_label.setText("Perfil privado — nenhum quadro acessível.")
        else:
            QMessageBox.critical(self, "Erro durante o download", message)
            self.status_label.setText("Erro.")

        self.start_button.setEnabled(True)
        self.list_boards_button.setEnabled(True)
        self.user_edit.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None
        # Um erro devolve o usuario para onde a acao acontece.
        self._set_step(self.STEP_BOARDS if self.boards_metadata else self.STEP_PROFILE)

    def on_manual_login_requested(self, board_url: str, message: str) -> None:
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setWindowTitle("Login necessário")
        dlg.setText(f"Quadro: {board_url}\n\n{message}")
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()
        if self.worker:
            self.worker.resume_manual_login()


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
