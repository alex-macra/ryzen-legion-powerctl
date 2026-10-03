# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QLabel, QSizePolicy, QStyle, QWidget

from . import styles, theme

DOT = 8
DOT_GAP = 3
POINTER_REASONS = (Qt.FocusReason.MouseFocusReason, Qt.FocusReason.PopupFocusReason)
RETURN_REASONS = (Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.OtherFocusReason)


def dot_icon(colour: QColor, ratio: float) -> QIcon:
    pixmap = QPixmap(round((DOT + DOT_GAP) * ratio), round(DOT * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(QRectF(0, 0, DOT, DOT))
    painter.end()
    return QIcon(pixmap)


class BadgeHeight(QObject):
    def __init__(self, badge: QWidget) -> None:
        super().__init__(badge)
        self.fit(badge)
        badge.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FontChange:
            self.fit(watched)
        return False

    @staticmethod
    def fit(badge: QWidget) -> None:
        badge.setFixedHeight(
            max(styles.BADGE_HEIGHT, badge.fontMetrics().height() + styles.BADGE_CHROME)
        )


class Badge(QLabel):
    PADDING = 22
    DOT_LEFT = 9

    def __init__(self) -> None:
        super().__init__("")
        self.dot = QColor()
        self.setFont(theme.font("badge"))
        BadgeHeight(self)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.dot)
        painter.drawEllipse(QRectF(self.DOT_LEFT, (self.height() - DOT) / 2, DOT, DOT))


class Switch(QCheckBox):
    TRACK = QSize(34, 20)
    KNOB = 14
    RING = 3
    TRAVEL = 14
    GAP = 10
    MOTION_MS = 140

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._position = 0.0
        self._keyboard = False
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(self.MOTION_MS)
        self._motion.valueChanged.connect(self._move)
        self.toggled.connect(self._slide)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._motion.stop()
        self._move(1.0 if checked else 0.0)

    def _slide(self, checked: bool) -> None:
        self._motion.stop()
        self._motion.setStartValue(self._position)
        self._motion.setEndValue(1.0 if checked else 0.0)
        self._motion.start()

    def _move(self, value) -> None:
        self._position = float(value)
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        text = metrics.horizontalAdvance(self.text().replace("&", ""))
        width = self.RING + self.TRACK.width() + self.GAP + text
        return QSize(width, max(self.TRACK.height() + 2 * self.RING, metrics.height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def focusInEvent(self, event) -> None:
        reason = event.reason()
        # Activation and the app's refocus after a command hand back the focus it had,
        # so they keep the ring that focus had.
        if reason not in RETURN_REASONS:
            self._keyboard = reason not in POINTER_REASONS
        super().focusInEvent(event)

    def paintEvent(self, _event) -> None:
        colours = styles.switch_colors(self.palette())
        enabled = self.isEnabled()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - self.TRACK.height()) / 2
        track = QRectF(self.RING + 0.5, top + 0.5, self.TRACK.width() - 1, self.TRACK.height() - 1)
        if enabled:
            fill = theme.blend(colours.track_off, colours.track_on, self._position)
            edge = theme.blend(colours.track_off_border, colours.track_on, self._position)
            knob = theme.blend(colours.knob_off, colours.knob_on, self._position)
        else:
            fill, edge = colours.track_disabled, theme.edge_color(self.palette())
            knob = colours.knob_disabled
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        left = self.RING + 3 + self.TRAVEL * self._position
        painter.drawEllipse(QRectF(left, top + 3, self.KNOB, self.KNOB))
        if self.hasFocus() and self._keyboard:
            painter.setPen(QPen(colours.focus, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            ring = track.adjusted(-2, -2, 2, 2)
            painter.drawRoundedRect(ring, ring.height() / 2, ring.height() / 2)
        underline = self.style().styleHint(QStyle.StyleHint.SH_UnderlineShortcut, None, self)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        mnemonic = Qt.TextFlag.TextShowMnemonic if underline else Qt.TextFlag.TextHideMnemonic
        painter.setPen(colours.label if enabled else colours.label_disabled)
        start = self.RING + self.TRACK.width() + self.GAP
        painter.drawText(
            QRectF(start, 0, self.width() - start, self.height()),
            flags.value | mnemonic.value, self.text(),
        )
