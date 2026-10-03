# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMessageBox, QPushButton, QStatusBar, QWidget

from . import a11y, styles

ERROR_MS = 10000
NOTE_MS = 8000
WARNING_MS = 15000
OFFER_GAP = 8


class ReportArea(QObject):
    go_back_requested = Signal()

    def __init__(self, status_bar: QStatusBar, dialogs: bool, parent=None) -> None:
        super().__init__(parent)
        self._bar = status_bar
        self._dialogs = dialogs
        self.last_warning = ""
        self._sheet = ""

        self.go_back_button = self._ghost("Go back")
        self.go_back_button.clicked.connect(self.go_back_requested)
        self.details_button = self._ghost("Details")
        self.details_button.clicked.connect(self.show_details)
        self._offers = (self.go_back_button, self.details_button)
        self._margins = dict.fromkeys(self._offers, 0)
        status_bar.addWidget(self.go_back_button)
        status_bar.addWidget(self.details_button)
        status_bar.messageChanged.connect(self._place_offers)
        status_bar.installEventFilter(self)
        self.restyle(status_bar.palette())

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self, self._place_offers)
        return False

    @staticmethod
    def _ghost(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setFlat(True)
        button.setProperty("kind", "ghost")
        button.hide()
        return button

    def restyle(self, palette: QPalette) -> None:
        plane = palette.color(QPalette.ColorRole.Window).name()
        self._sheet = (
            f"{styles.ghost_button_style(palette)} QPushButton {{ background-color: {plane}; }}"
        )
        self._place_offers()

    def _place_offers(self, *_args) -> None:
        shown = [button for button in self._offers if not button.isHidden()]
        message = self._bar.currentMessage()
        room = 0
        if message and shown:
            needed = sum(button.sizeHint().width() - self._margins[button] for button in shown)
            room = self._bar.fontMetrics().horizontalAdvance(message) + OFFER_GAP
            room = max(0, min(room, self._permanent_edge() - needed - OFFER_GAP))
        for button in self._offers:
            self._margins[button] = room if shown and button is shown[0] else 0
            sheet = f"{self._sheet} QPushButton {{ margin-left: {self._margins[button]}px; }}"
            if button.styleSheet() != sheet:
                button.setStyleSheet(sheet)

    def _permanent_edge(self) -> int:
        children = self._bar.findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
        edges = [child.x() for child in children if child.isVisible() and child not in self._offers]
        return min(edges, default=self._bar.width())

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
            self._place_offers()

    def warning(self, message: str, detail: str) -> None:
        self.last_warning = detail
        self.clear_offers()
        first = detail.splitlines()[0] if detail else ""
        text = f"{message} {first}".strip()
        self._bar.showMessage(text, WARNING_MS)
        a11y.announce(self._bar, text, interrupt=True)
        self.details_button.show()
        self._place_offers()

    def offer_repair_backup(self, backup: str) -> None:
        if self.details_button.isHidden():
            self.last_warning = backup
        else:
            self.last_warning += f"\n\n{backup}"
        self.details_button.show()
        self._place_offers()

    def show_details(self) -> None:
        if self._dialogs and self.last_warning:
            QMessageBox.information(
                self._bar.window(), "What the command reported", self.last_warning
            )
