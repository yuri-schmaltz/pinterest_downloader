"""Interface gráfica em PyQt6 para o downloader de quadros do Pinterest."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
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

from pinterest_board_dl import DownloadOptions, download_board, download_user_boards


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
        mode: str,
        options: DownloadOptions,
        board_url: str | None = None,
        username_or_url: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.options = options
        self.board_url = board_url
        self.username_or_url = username_or_url
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
            if self.mode == "board" and self.board_url:
                result = download_board(
                    self.board_url,
                    self.options,
                    status_cb=self._status_callback,
                    manual_login_handler=self._manual_login_wait if self.options.manual_login else None,
                )
                totals[0] += result.downloaded
                totals[1] += result.total
            elif self.mode == "user" and self.username_or_url:
                results = download_user_boards(
                    self.username_or_url,
                    self.options,
                    status_cb=self._status_callback,
                    manual_login_handler=self._manual_login_wait if self.options.manual_login else None,
                )
                for res in results:
                    totals[0] += res.downloaded
                    totals[1] += res.total
                    if self._cancelled:
                        raise DownloadCancelled()
            else:
                raise ValueError("Modo ou parâmetros inválidos para download.")

            if self._cancelled:
                self.cancelled.emit()
            else:
                self.finished_with_totals.emit(totals[0], totals[1])
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as exc:  # pragma: no cover - exibição no GUI
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pinterest Board Downloader")
        self.setMinimumSize(1000, 700)
        self.worker: DownloadWorker | None = None
        self.board_items: dict[str, QListWidgetItem] = {}

        self._build_ui()

    # --- UI helpers ---
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_board_tab(), "Quadro único")
        self.tabs.addTab(self._build_user_tab(), "Todos os quadros do usuário")
        layout.addWidget(self.tabs)

        layout.addWidget(self._build_options_group())
        layout.addWidget(self._build_progress_group())
        layout.addWidget(self._build_log_widget())
        layout.addLayout(self._build_buttons())

        self.status_label = QLabel("Pronto.")
        layout.addWidget(self.status_label)

        self.setCentralWidget(central)

    def _build_board_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.board_url_edit = QLineEdit()
        self.board_url_edit.setPlaceholderText("https://www.pinterest.com/<usuario>/<quadro>/")
        form.addRow("URL do quadro", self.board_url_edit)
        return widget

    def _build_user_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("usuario_pinterest")
        form.addRow("Usuário ou URL", self.user_edit)
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

    def start_download(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Download em andamento", "Aguarde o término antes de iniciar outro download.")
            return

        mode = "board" if self.tabs.currentIndex() == 0 else "user"
        board_url = self.board_url_edit.text().strip()
        username = self.user_edit.text().strip()

        if mode == "board" and not board_url:
            QMessageBox.warning(self, "Dados incompletos", "Informe a URL do quadro a ser baixado.")
            return
        if mode == "user" and not username:
            QMessageBox.warning(self, "Dados incompletos", "Informe o usuário ou URL do perfil do Pinterest.")
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
        self.board_items.clear()
        self.status_label.setText("Iniciando…")

        self.worker = DownloadWorker(
            mode=mode,
            options=options,
            board_url=board_url if mode == "board" else None,
            username_or_url=username if mode == "user" else None,
        )
        self._connect_worker_signals()
        self.worker.start()

        self.start_button.setEnabled(False)
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

    def on_boards_found(self, boards: List[str]) -> None:
        self.overall_progress.setMaximum(max(len(boards), 1))
        self.overall_progress.setValue(0)
        self.append_log(f"{len(boards)} quadros encontrados.")

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
