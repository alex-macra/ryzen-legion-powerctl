# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import fields, strip_widgets, styles, theme

FIGURE_V_PAD = 2
RING_SPACE = 3
RING_WIDTH = 2
RING_RADIUS = 6
RULE = 1
CAPTION_GAP = 2
DELTA_GAP = 6
DELTA = "delta"


class FigureSpin(fields.ValueSpin):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(theme.font("readout"))
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setFrame(False)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def figure_top(self) -> int:
        return strip_widgets.figure_top(self.fontMetrics())

    def sizeHint(self) -> QSize:
        padding = 2 * (fields.FIGURE_PADDING - fields.VALUE_PADDING)
        return QSize(super().sizeHint().width() + padding, self.figure_top() + 2 * FIGURE_V_PAD)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class DeltaLabel(QLabel):
    def __init__(self, widest: str, height: int, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setObjectName(DELTA)
        self.setFont(theme.font("detail-mono"))
        self.setFixedHeight(height)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.hide()
        self._widest = widest

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._widest), self.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event) -> None:
        rect = self.rect()
        rect.setTop(self.height() - FIGURE_V_PAD + 1 - self.fontMetrics().ascent())
        painter = QPainter(self)
        self.style().drawItemText(
            painter, rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            self.palette(), self.isEnabled(), self.text(), self.foregroundRole(),
        )
        painter.end()


class ValueTile(QWidget):
    def __init__(self, caption: str, low: int, high: int, suffix: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spin = FigureSpin()
        self.spin.setRange(low, high)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.installEventFilter(self)
        self.spin.lineEdit().installEventFilter(self)
        self._unit = suffix.strip()
        self.delta = DeltaLabel(f"+{high - low}", self.spin.sizeHint().height())
        self.swatch: QLabel | None = None
        self.caption: QLabel | None = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        column = QVBoxLayout(self)
        column.setContentsMargins(RING_SPACE, RING_SPACE, RING_SPACE, 0 if caption else RING_SPACE)
        column.setSpacing(RING_SPACE + CAPTION_GAP)
        figure = QHBoxLayout()
        figure.setContentsMargins(0, 0, 0, 0)
        figure.setSpacing(DELTA_GAP)
        figure.addWidget(self.spin)
        figure.addWidget(self.delta, 0, Qt.AlignmentFlag.AlignTop)
        figure.addStretch(1)
        column.addLayout(figure)
        if not caption:
            return
        self.swatch = QLabel()
        self.swatch.setFixedSize(fields.SWATCH_SIZE, fields.SWATCH_SIZE)
        self.caption = QLabel(caption)
        self.caption.setObjectName(fields.LEGEND)
        self.caption.setFont(theme.font("eyebrow"))
        label = QHBoxLayout()
        label.setContentsMargins(0, 0, 0, 0)
        label.setSpacing(fields.ENTRY_SPACING)
        label.addWidget(self.swatch)
        label.addWidget(self.caption)
        label.addStretch(1)
        column.addLayout(label)

    def set_delta(self, delta: int | None) -> bool:
        text = f"{delta:+d}" if delta else ""
        if text == self.delta.text():
            return False
        self.delta.setText(text)
        self.delta.setAccessibleName(f"{text} {self._unit} vs running" if text else "")
        self.delta.setVisible(bool(text))
        return True

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.StyleChange:
            self._keep_surface(watched, self.palette().color(QPalette.ColorRole.Base))
        elif watched is self.spin:
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self.update()
            elif event.type() == QEvent.Type.FontChange:
                self.delta.setFixedHeight(self.spin.sizeHint().height())
        return False

    def paintEvent(self, _event) -> None:
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        box = self.spin.geometry()
        painter = QPainter(self)
        if self.spin.hasFocus():
            ring = theme.fit_contrast(theme.focus_color(palette), base, theme.MIN_NON_TEXT_CONTRAST)
            reach = RING_SPACE - RING_WIDTH / 2
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(ring, RING_WIDTH))
            painter.drawRoundedRect(
                QRectF(box).adjusted(-reach, -reach, reach, reach), RING_RADIUS, RING_RADIUS
            )
        else:
            enabled = self.spin.isEnabled()
            rule = theme.edge_strong_color(palette, base) if enabled else theme.edge_color(palette)
            top = box.bottom() + 1 + (RING_SPACE - RULE) // 2
            painter.fillRect(QRect(box.left(), top, box.width(), RULE), rule)
        painter.end()

    def restyle(self, palette: QPalette, step: float) -> None:
        if self.swatch is not None:
            base = palette.color(QPalette.ColorRole.Base)
            self.swatch.setStyleSheet(styles.swatch_style(palette, base, step))
            self.caption.setStyleSheet(styles.caption_style(palette))
        self.delta.setStyleSheet(fields.label_style(palette))
        self.update()

    @staticmethod
    def _keep_surface(widget: QWidget, base: QColor) -> None:
        quiet = QPalette(widget.palette())
        quiet.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, base)
        widget.setPalette(quiet)
