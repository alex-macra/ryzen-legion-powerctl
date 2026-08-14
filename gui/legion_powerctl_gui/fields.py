# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .flow import FlowLayout

CAPTION = "caption"


def card(title: str, caption: str = "") -> tuple[QGroupBox, QFormLayout]:
    group = QGroupBox(title)
    column = QVBoxLayout(group)
    column.setContentsMargins(0, 0, 0, 0)
    if caption:
        note = QLabel(caption)
        note.setObjectName(CAPTION)
        note.setWordWrap(True)
        column.addWidget(note)
    form = form_layout()
    column.addLayout(form)
    return group, form


def form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setVerticalSpacing(4)
    return form


def scale_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSizeF(QLabel().font().pointSizeF())
    label.setFont(font)
    return label


def value_row() -> FlowLayout:
    return FlowLayout(spacing=10)


def value_entry(caption: str, low: int, high: int, suffix: str):
    host = QWidget()
    line = QHBoxLayout(host)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(6)
    swatch = QLabel()
    swatch.setFixedSize(10, 10)
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setSuffix(suffix)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    spin.setKeyboardTracking(False)
    line.addWidget(swatch)
    if caption:
        line.addWidget(QLabel(caption))
    line.addWidget(spin)
    return host, swatch, spin


VALUE_LABELS = {
    "unchanged": "Leave as is",
    "stock": "Hardware maximum (raises the limit)",
    "balanced": "Balanced",
    "performance": "Performance",
    "power-saver": "Power saver",
    "balance_performance": "Balance, favour performance",
    "balance_power": "Balance, favour power saving",
    "power": "Power saving",
    "on": "On",
    "off": "Off",
}


LABEL_VALUES = {label: value for value, label in VALUE_LABELS.items()}


def value_label(value: str) -> str:
    return VALUE_LABELS.get(value, value)


def combo(values: tuple[str, ...], editable: bool = False) -> QComboBox:
    box = QComboBox()
    box.setEditable(editable)
    for value in values:
        box.addItem(value_label(value), value)
    return box


def combo_value(box: QComboBox) -> str:
    if box.isEditable():
        text = box.currentText().strip()
        return LABEL_VALUES.get(text, text)
    data = box.currentData()
    return str(data) if data is not None else box.currentText()


def set_combo_value(box: QComboBox, value: str) -> None:
    index = box.findData(value)
    if index >= 0:
        box.setCurrentIndex(index)
    else:
        box.setCurrentText(value)
