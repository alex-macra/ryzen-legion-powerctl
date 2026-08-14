# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QPushButton, QStatusBar

from . import a11y

ERROR_MS = 10000
NOTE_MS = 8000
WARNING_MS = 15000


class ReportArea(QObject):
    go_back_requested = Signal()

    def __init__(self, status_bar: QStatusBar, dialogs: bool, parent=None) -> None:
        super().__init__(parent)
        self._bar = status_bar
        self._dialogs = dialogs
        self.last_warning = ""

        self.go_back_button = QPushButton("Go back")
        self.go_back_button.setFlat(True)
        self.go_back_button.hide()
        self.go_back_button.clicked.connect(self.go_back_requested)
        self.details_button = QPushButton("Details")
        self.details_button.setFlat(True)
        self.details_button.hide()
        self.details_button.clicked.connect(self.show_details)
        status_bar.addWidget(self.go_back_button)
        status_bar.addWidget(self.details_button)

    def clear_offers(self) -> None:
        self.go_back_button.hide()
        self.details_button.hide()

    def error(self, message: str) -> None:
        self.clear_offers()
        if self._dialogs:
            QMessageBox.critical(self._bar.window(), "legion-powerctl", message)
        self._bar.showMessage(message, ERROR_MS)
        a11y.announce(self._bar, message, interrupt=True)

    def note(self, message: str) -> None:
        self._bar.showMessage(message, NOTE_MS)
        a11y.announce(self._bar, message)

    def success(self, message: str, go_back_to: str = "") -> None:
        self.clear_offers()
        self.note(message)
        if go_back_to:
            self.go_back_button.setText(f"Go back to '{go_back_to}'")
            self.go_back_button.show()

    def warning(self, message: str, detail: str) -> None:
        self.last_warning = detail
        self.clear_offers()
        first = detail.splitlines()[0] if detail else ""
        text = f"{message} {first}".strip()
        self._bar.showMessage(text, WARNING_MS)
        a11y.announce(self._bar, text, interrupt=True)
        self.details_button.show()

    def show_details(self) -> None:
        if self._dialogs and self.last_warning:
            QMessageBox.information(
                self._bar.window(), "What the command reported", self.last_warning
            )
