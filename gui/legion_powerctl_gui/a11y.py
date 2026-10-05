# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QAccessible, QAccessibleEvent, QPainter, QPen
from PySide6.QtWidgets import QSlider, QSpinBox, QWidget

from . import theme

try:  # pragma: no cover - one branch per PySide6 version
    from PySide6.QtGui import QAccessibleAnnouncementEvent
except ImportError:  # pragma: no cover
    QAccessibleAnnouncementEvent = None


def announce(widget, message: str, interrupt: bool = False) -> None:
    if QAccessibleAnnouncementEvent is not None:
        event = QAccessibleAnnouncementEvent(widget, message)
        event.setPoliteness(
            QAccessible.AnnouncementPoliteness.Assertive if interrupt
            else QAccessible.AnnouncementPoliteness.Polite
        )
        QAccessible.updateAccessibility(event)
        return
    previous = widget.accessibleName()
    widget.setAccessibleName(message)
    QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.Event.Alert))
    widget.setAccessibleName(previous)


def name_range(
    slider: QSlider, spin: QSpinBox, label: str, unit: str, low: int, high: int,
    note: str = "", aside: str = "",
) -> None:
    slider.setAccessibleName(label)
    spin.setAccessibleName(f"{label} in {unit}")
    described = f"{low} to {high} {unit}"
    slider.setAccessibleDescription(f"{described}{note}")
    spin.setAccessibleDescription(f"{described}; {aside}" if aside else described)


class FocusRing(QWidget):
    WIDTH = 2
    RADIUS = 8

    def __init__(self, target: QWidget) -> None:
        super().__init__(target)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        target.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.Resize):
            self.setGeometry(watched.rect())
            self.raise_()
            focused = watched.hasFocus() if kind == QEvent.Type.Resize else kind == QEvent.Type.FocusIn
            self.setVisible(focused)
        return False

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(theme.focus_color(self.palette()), self.WIDTH))
        half = self.WIDTH / 2
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(half, half, -half, -half), self.RADIUS, self.RADIUS
        )
