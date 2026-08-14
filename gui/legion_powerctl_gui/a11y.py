# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QSlider, QSpinBox

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
    note: str = "",
) -> None:
    slider.setAccessibleName(label)
    spin.setAccessibleName(f"{label} in {unit}")
    described = f"{low} to {high} {unit}"
    slider.setAccessibleDescription(f"{described}{note}")
    spin.setAccessibleDescription(described)
