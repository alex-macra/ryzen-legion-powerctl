# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import styles, theme
from .flow import FlowLayout

CAPTION = "caption"
FORM_LABEL = "formLabel"
LEGEND = "legend"
EYEBROW_TOP = 12
CARD_SPACING = 6
FORM_SPACING = 12
ROW_SPACING = 8
LEGEND_SPACING = 16
# Room to absorb a scroll bar, so its arrival alone cannot wrap the legend and keep itself shown.
LEGEND_MIN_SPACING = 8
LEGEND_LINE_SPACING = 6
ENTRY_SPACING = 6
SWATCH_SIZE = 10
VALUE_PADDING = 8


class Card(QGroupBox):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.eyebrow = title
        self.setProperty("card", True)
        self.setTitle("")
        self.setAccessibleName(title)
        self.column = QVBoxLayout(self)
        self.column.setSpacing(CARD_SPACING)
        self._fit_margins()

    def eyebrow_font(self) -> QFont:
        return theme.font("eyebrow", self.font())

    def eyebrow_rect(self) -> QRect:
        left, _top, right, _bottom = styles.CARD_MARGINS
        frame = self.contentsRect()
        height = QFontMetrics(self.eyebrow_font()).height()
        return QRect(
            frame.left() + left, frame.top() + EYEBROW_TOP,
            max(0, frame.width() - left - right), height,
        )

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fit_margins()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        palette = self.palette()
        painter = QPainter(self)
        painter.setFont(self.eyebrow_font())
        painter.setPen(theme.muted_color(palette, palette.color(QPalette.ColorRole.Base)))
        painter.drawText(
            self.eyebrow_rect(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.eyebrow,
        )
        painter.end()

    def _fit_margins(self) -> None:
        left, top, right, bottom = styles.CARD_MARGINS
        height = QFontMetrics(self.eyebrow_font()).height()
        self.column.setContentsMargins(left, top + height + styles.EYEBROW_GAP, right, bottom)


class ValueSpin(QSpinBox):
    # Under any style sheet Qt counts the arrows twice, so size to the widest value instead.
    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        option.rect = QRect(QPoint(0, 0), hint)
        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxEditField, self
        )
        metrics = self.fontMetrics()
        widest = max(
            metrics.horizontalAdvance(f"{self.textFromValue(value)}{self.suffix()}")
            for value in (self.minimum(), self.maximum())
        )
        return QSize(hint.width() - field.width() + widest + 2 * VALUE_PADDING, hint.height())


def card(title: str, caption: str = "") -> tuple[Card, QFormLayout]:
    group = Card(title)
    if caption:
        note = QLabel(caption)
        note.setObjectName(CAPTION)
        note.setWordWrap(True)
        note.setFont(theme.font("caption"))
        group.column.addWidget(note)
    form = form_layout()
    group.column.addLayout(form)
    return group, form


def form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setHorizontalSpacing(FORM_SPACING)
    form.setVerticalSpacing(ROW_SPACING)
    return form


def add_row(form: QFormLayout, text: str, field: QWidget) -> QLabel:
    label = QLabel(text)
    label.setObjectName(FORM_LABEL)
    label.setBuddy(field)
    form.addRow(label, field)
    return label


def align_labels(labels) -> None:
    width = max((label.sizeHint().width() for label in labels), default=0)
    for label in labels:
        label.setMinimumWidth(width)


def label_style(palette: QPalette) -> str:
    base = palette.color(QPalette.ColorRole.Base)
    return f"color: {theme.secondary_color(palette, base).name()};"


def scale_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(theme.font("detail-mono"))
    return label


def value_row() -> FlowLayout:
    return FlowLayout(
        spacing=LEGEND_SPACING, line_spacing=LEGEND_LINE_SPACING, min_spacing=LEGEND_MIN_SPACING
    )


def value_entry(caption: str, low: int, high: int, suffix: str):
    host = QWidget()
    line = QHBoxLayout(host)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(ENTRY_SPACING)
    swatch = QLabel()
    swatch.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
    spin = ValueSpin()
    spin.setRange(low, high)
    spin.setSuffix(suffix)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    spin.setKeyboardTracking(False)
    line.addWidget(swatch)
    if caption:
        legend = QLabel(caption)
        legend.setObjectName(LEGEND)
        line.addWidget(legend)
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
