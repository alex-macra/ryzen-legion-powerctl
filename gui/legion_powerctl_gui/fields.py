# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import styles, theme
from .flow import FlowLayout
from .strip_widgets import ElidedLabel

FORM_LABEL = "formLabel"
LEGEND = "legend"
EYEBROW_TOP = 12
ASIDE_GAP = 12
CARD_SPACING = 6
FORM_SPACING = 12
ROW_SPACING = 8
LEGEND_SPACING = 16
LEGEND_MIN_SPACING = 8
LEGEND_LINE_SPACING = 6
ENTRY_SPACING = 6
SWATCH_SIZE = 10
VALUE_PADDING = 8
FIGURE_PADDING = 2
SCALE_TEMPLATE = "100 °C"


class Card(QGroupBox):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.eyebrow = title
        self.aside = ""
        self.setProperty("card", True)
        self.setTitle("")
        self.setAccessibleName(title)
        self.column = QVBoxLayout(self)
        self.column.setSpacing(CARD_SPACING)
        self._fit_margins()

    def set_aside(self, text: str) -> None:
        if text != self.aside:
            self.aside = text
            self.update()

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
        rect = self.eyebrow_rect()
        painter = QPainter(self)
        painter.setFont(self.eyebrow_font())
        painter.setPen(theme.muted_color(palette, palette.color(QPalette.ColorRole.Base)))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.eyebrow,
        )
        eyebrow = QFontMetrics(self.eyebrow_font())
        room = rect.width() - eyebrow.horizontalAdvance(self.eyebrow) - ASIDE_GAP
        if self.aside and room > 0:
            font = theme.font("detail-mono", self.font())
            metrics = QFontMetrics(font)
            text = metrics.elidedText(self.aside, Qt.TextElideMode.ElideLeft, room)
            painter.setFont(font)
            painter.drawText(
                QPointF(rect.right() + 1 - metrics.horizontalAdvance(text),
                        rect.top() + eyebrow.ascent()),
                text,
            )
        painter.end()

    def _fit_margins(self) -> None:
        left, top, right, bottom = styles.CARD_MARGINS
        height = QFontMetrics(self.eyebrow_font()).height()
        self.column.setContentsMargins(left, top + height + styles.EYEBROW_GAP, right, bottom)


class Aside(ElidedLabel):
    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.sizeHint().height())


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


def card(title: str) -> tuple[Card, QFormLayout]:
    group = Card(title)
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


def scale_label(text: str, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignRight) -> QLabel:
    label = QLabel(text)
    label.setFont(theme.font("detail-mono"))
    label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    label.setMinimumWidth(QFontMetrics(label.font()).horizontalAdvance(SCALE_TEMPLATE))
    return label


def value_row() -> FlowLayout:
    return FlowLayout(
        spacing=LEGEND_SPACING, line_spacing=LEGEND_LINE_SPACING, min_spacing=LEGEND_MIN_SPACING
    )


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
