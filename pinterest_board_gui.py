"""Interface gráfica em PyQt6 para o downloader de quadros do Pinterest."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pinterest_board_dl import (
    DownloadOptions,
    download_board,
    download_user_boards,
    BoardMetadata,
    collect_board_urls,
)


class DownloadCancelled(Exception):
    """Sinaliza cancelamento manual do usuário."""


class DownloadWorker(QThread):
    log_message = pyqtSignal(str)
    board_started = pyqtSignal(str, str)
    download_started = pyqtSignal(str, int)
    download_progress = pyqtSignal(str, int, int, int)
    board_finished = pyqtSignal(str, int, int, str)
    boards_found = pyqtSignal(list)
    overall_progress = pyqtSignal(int, int)
    finished_with_totals = pyqtSignal(int, int)
    manual_login_requested = pyqtSignal(str, str)
    error = pyqtSignal(str)
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
        except Exception as exc:  # pragma: no cover - exibição no GUI
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pinterest Board Downloader - Seleção Visual")
        self.resize(1100, 750)
        self.worker: DownloadWorker | None = None
        self.boards_metadata: List[BoardMetadata] = []
        self.selected_urls: List[str] = []
        self.board_items: Dict[str, QListWidgetItem] = {}

        # Set application icon
        self._set_window_icon()
        self._build_ui()

    # --- UI helpers ---
    def _set_window_icon(self) -> None:
        """Define o ícone da aplicação."""
        icon_path = Path(__file__).parent / "icon.svg"
        
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
            QApplication.instance().setWindowIcon(icon)
    
    def _build_ui(self) -> None:
        central = QWidget()
        main_layout = QHBoxLayout(central)

        # Coluna Esquerda: Configurações, Progresso e Log
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(self._build_user_input())
        left_layout.addWidget(self._build_options_group())
        left_layout.addWidget(self._build_progress_group())
        left_layout.addWidget(self._build_log_widget())
        left_layout.addLayout(self._build_buttons())

        self.status_label = QLabel("Pronto.")
        left_layout.addWidget(self.status_label)

        # Coluna Direita: Seleção de Quadros
        self.selection_panel = self._build_selection_panel()

        main_layout.addWidget(left_widget, stretch=1)
        main_layout.addWidget(self.selection_panel, stretch=1)

        self.setCentralWidget(central)

    def _build_user_input(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Usuário ou URL:"))
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("ex: yuri_schmaltz")
        layout.addWidget(self.user_edit)

        self.list_boards_button = QPushButton("Listar Quadros")
        self.list_boards_button.clicked.connect(self.start_discovery)
        layout.addWidget(self.list_boards_button)
        return widget

    def _build_options_group(self) -> QGroupBox:
        group = QGroupBox("Opções de download")
        layout = QGridLayout(group)

        self.output_edit = QLineEdit(str(Path("pins").resolve()))
        select_button = QPushButton("Selecionar…")
        select_button.clicked.connect(self._select_output_dir)

        self.headful_check = QCheckBox("Exibir navegador")
        self.manual_login_check = QCheckBox("Pausar para login manual")

        self.max_pins_spin = QSpinBox()
        self.max_pins_spin.setRange(0, 1000000)
        self.max_pins_spin.setSpecialValueText("Sem limite")
        self.max_pins_spin.setValue(0)

        self.scroll_pause_spin = QDoubleSpinBox()
        self.scroll_pause_spin.setDecimals(2)
        self.scroll_pause_spin.setRange(0.1, 10.0)
        self.scroll_pause_spin.setValue(1.2)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(16)

        self.boards_workers_spin = QSpinBox()
        self.boards_workers_spin.setRange(1, 8)
        self.boards_workers_spin.setValue(1)

        layout.addWidget(QLabel("Pasta de saída"), 0, 0)
        layout.addWidget(self.output_edit, 0, 1)
        layout.addWidget(select_button, 0, 2)

        layout.addWidget(self.headful_check, 1, 0)
        layout.addWidget(self.manual_login_check, 1, 1)

        layout.addWidget(QLabel("Máximo de pins por quadro"), 2, 0)
        layout.addWidget(self.max_pins_spin, 2, 1)

        layout.addWidget(QLabel("Pausa entre rolagens (s)"), 3, 0)
        layout.addWidget(self.scroll_pause_spin, 3, 1)

        layout.addWidget(QLabel("Workers por quadro"), 4, 0)
        layout.addWidget(self.workers_spin, 4, 1)

        layout.addWidget(QLabel("Quadros em paralelo"), 5, 0)
        layout.addWidget(self.boards_workers_spin, 5, 1)

        layout.setColumnStretch(1, 1)
        return group

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("Progresso")
        layout = QVBoxLayout(group)

        self.board_progress = QProgressBar()
        self.board_progress.setFormat("%v / %m imagens")
        self.board_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.overall_progress = QProgressBar()
        self.overall_progress.setFormat("%v / %m quadros")
        self.overall_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.board_list = QListWidget()
        self.board_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout.addWidget(QLabel("Quadro atual"))
        layout.addWidget(self.board_progress)
        layout.addWidget(QLabel("Total de quadros"))
        layout.addWidget(self.overall_progress)
        layout.addWidget(QLabel("Histórico de quadros"))
        layout.addWidget(self.board_list)
        return group

    def _build_selection_panel(self) -> QGroupBox:
        group = QGroupBox("Seleção de Quadros")
        layout = QVBoxLayout(group)

        self.select_all_check = QCheckBox("Selecionar Todos")
        self.select_all_check.stateChanged.connect(self._toggle_select_all)
        layout.addWidget(self.select_all_check)

        self.selection_list = QListWidget()
        self.selection_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.selection_list.itemChanged.connect(self._update_selection_state)
        layout.addWidget(self.selection_list)

        self.info_selection_label = QLabel("Nenhum quadro carregado.")
        layout.addWidget(self.info_selection_label)

        return group

    def _build_log_widget(self) -> QGroupBox:
        group = QGroupBox("Log detalhado")
        layout = QVBoxLayout(group)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log_edit)
        return group

    def _build_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addStretch()
        self.start_button = QPushButton("Iniciar download")
        self.start_button.clicked.connect(self.start_download)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        layout.addWidget(self.start_button)
        layout.addWidget(self.cancel_button)
        return layout

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
            headless=not self.headful_check.isChecked(),
            manual_login=self.manual_login_check.isChecked(),
            scroll_pause=self.scroll_pause_spin.value(),
        )

        self.log_edit.clear()
        self.selection_list.clear()
        self.boards_metadata = []
        self.info_selection_label.setText("Buscando quadros…")
        
        self.worker = DownloadWorker(
            options=options,
            username_or_url=username,
            discovery_mode=True
        )
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
            headless=not self.headful_check.isChecked(),
            manual_login=self.manual_login_check.isChecked(),
            max_pins=self.max_pins_spin.value() or None,
            scroll_pause=self.scroll_pause_spin.value(),
            workers=self.workers_spin.value(),
            boards_workers=self.boards_workers_spin.value(),
        )

        self.log_edit.clear()
        self.board_progress.reset()
        self.overall_progress.reset()
        self.board_list.clear()
        # Não limpar board_items pois eles são usados no histórico agora? 
        # Na verdade self.board_items no código original parece ser usado para o QListWidget de histórico.
        
        self.status_label.setText("Iniciando…")

        self.worker = DownloadWorker(
            options=options,
            username_or_url=username,
            selected_boards=self.selected_urls
        )
        self._connect_worker_signals()
        self.worker.start()

        self.start_button.setEnabled(False)
        self.list_boards_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

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
        item = QListWidgetItem(f"{board_url} → {output_dir}")
        self.board_list.addItem(item)
        self.board_items[board_url] = item
        item.setData(Qt.ItemDataRole.UserRole, {"downloaded": 0, "total": 0})
        self.status_label.setText(f"Processando quadro: {board_url}")

    def on_download_started(self, board_url: str, total: int) -> None:
        if total <= 0:
            self.board_progress.setMaximum(1)
            self.board_progress.setValue(0)
        else:
            self.board_progress.setMaximum(total)
            self.board_progress.setValue(0)
        item = self.board_items.get(board_url)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            data.update({"total": total})
            item.setData(Qt.ItemDataRole.UserRole, data)
            item.setText(f"{board_url} → {data.get('total', 0)} imagens")

    def on_download_progress(self, board_url: str, current: int, total: int, downloaded: int) -> None:
        self.board_progress.setMaximum(max(total, 1))
        self.board_progress.setValue(min(current, total))
        item = self.board_items.get(board_url)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            data.update({"downloaded": downloaded, "total": total})
            item.setData(Qt.ItemDataRole.UserRole, data)
            item.setText(f"{board_url} → {downloaded}/{total} imagens")

    def on_board_finished(self, board_url: str, downloaded: int, total: int, output_dir: str) -> None:
        item = self.board_items.get(board_url)
        if item:
            item.setText(f"{board_url} → {downloaded}/{total} imagens (em {output_dir})")
        self.board_progress.setValue(self.board_progress.maximum())

    def on_boards_found(self, boards: List[BoardMetadata]) -> None:
        self.boards_metadata = boards
        self.selection_list.clear()
        self.selected_urls = []
        
        if not boards:
            self.info_selection_label.setText("Nenhum quadro encontrado.")
            self.list_boards_button.setEnabled(True)
            self.start_button.setEnabled(False)
            return

        import requests
        for b in boards:
            # Texto do item: Título + (N Pins) na linha 1, URL na linha 2
            pin_text = f" ({b['pin_count']})" if b.get('pin_count') else ""
            item = QListWidgetItem(f"{b['title']}{pin_text}\n{b['url']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            
            # Thumbnail (simples requests; pode travar levemente se muitos)
            if b['thumbnail_url']:
                try:
                    resp = requests.get(b['thumbnail_url'], timeout=3)
                    if resp.status_code == 200:
                        pix = QPixmap()
                        pix.loadFromData(resp.content)
                        item.setIcon(QIcon(pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio)))
                except Exception:
                    pass
            
            self.selection_list.addItem(item)
            
        self.info_selection_label.setText(f"{len(boards)} quadros encontrados.")
        self.list_boards_button.setEnabled(True)
        self.start_button.setEnabled(False)

    def _toggle_select_all(self, state: int) -> None:
        cs = Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
        for i in range(self.selection_list.count()):
            self.selection_list.item(i).setCheckState(cs)
        self._update_selection_state()

    def _update_selection_state(self) -> None:
        self.selected_urls = []
        for i in range(self.selection_list.count()):
            item = self.selection_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                # Recuperar URL da segunda linha
                url = item.text().split('\n')[-1]
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
        self.cancel_button.setEnabled(False)
        self.worker = None

    def on_cancelled(self) -> None:
        self.status_label.setText("Operação cancelada.")
        self.append_log("Operação cancelada pelo usuário.")
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None

    def on_error(self, message: str) -> None:
        QMessageBox.critical(self, "Erro durante o download", message)
        self.status_label.setText("Erro.")
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.worker = None

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
