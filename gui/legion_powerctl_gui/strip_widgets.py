# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QLabel, QSizePolicy, QStyle, QWidget

from . import runstate, styles, theme

DOT = 8
DOT_GAP = 3
READOUT_UNITS = {"C": "°C"}
DIGITS = "0123456789"
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


class ElidedLabel(QLabel):
    def sizeHint(self) -> QSize:
        chrome = self.rect().width() - self.contentsRect().width()
        width = self.fontMetrics().size(0, self.text()).width() + chrome
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def shrink_by(self, short: int, room: int) -> int:
        give = max(0, min(short, room))
        self.setMinimumWidth(max(1, self.sizeHint().width() - give) if give else 0)
        return short - give

    def given(self) -> int:
        return self.sizeHint().width() - (self.minimumWidth() or self.minimumSizeHint().width())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        self.drawFrame(painter)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        self.style().drawItemText(
            painter, rect, self.alignment().value, self.palette(), self.isEnabled(), text,
            self.foregroundRole(),
        )


class Readout(QLabel):
    GAP = 20
    MIN_GAP = 8
    UNIT_GAP = 3
    CAPTION_GAP = 2

    def __init__(self) -> None:
        super().__init__("")
        self.tiles: list[tuple[str, str, str]] = []
        self.severity = "NEUTRAL"
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_state(self, state: runstate.RunState, severity: str) -> None:
        self.severity = severity
        self.tiles = [
            (str(value), READOUT_UNITS.get(unit, unit), label.upper())
            for value, (label, _key, unit) in zip(state.limits() or [], runstate.LIMITS)
        ]
        self.setText(state.summary())
        self.updateGeometry()
        self.update()

    def _fonts(self) -> tuple[QFont, QFont, QFont]:
        return tuple(theme.font(role, self.font()) for role in ("readout", "caption", "eyebrow"))

    def tile_widths(self) -> list[int]:
        big, small, eyebrow = (QFontMetrics(font) for font in self._fonts())
        return [
            max(
                big.horizontalAdvance(value) + self.UNIT_GAP + small.horizontalAdvance(unit),
                eyebrow.horizontalAdvance(caption),
            )
            for value, unit, caption in self.tiles
        ]

    @staticmethod
    def _figure_top(metrics: QFontMetrics) -> int:
        return max(metrics.capHeight(), -metrics.tightBoundingRect(DIGITS).top())

    def tile_height(self) -> int:
        big, _small, eyebrow = self._fonts()
        top = self._figure_top(QFontMetrics(big))
        return top + self.CAPTION_GAP + QFontMetrics(eyebrow).height()

    def _size(self, gap: int) -> QSize:
        if not self.tiles:
            metrics = QFontMetrics(self._fonts()[1])
            return QSize(metrics.horizontalAdvance(self.text()), metrics.height())
        widths = self.tile_widths()
        return QSize(sum(widths) + gap * (len(widths) - 1), self.tile_height())

    def sizeHint(self) -> QSize:
        return self._size(self.GAP)

    def minimumSizeHint(self) -> QSize:
        return self._size(self.MIN_GAP)

    def paintEvent(self, _event) -> None:
        colours = styles.readout_colors(self.palette(), self.severity)
        big, small, eyebrow = self._fonts()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.tiles:
            painter.setFont(small)
            painter.setPen(colours.caption)
            flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(self.rect(), flags.value, self.text())
            painter.end()
            return
        metrics, eyebrow_metrics = QFontMetrics(big), QFontMetrics(eyebrow)
        widths = self.tile_widths()
        spare = self.width() - sum(widths)
        gap = max(self.MIN_GAP, min(self.GAP, spare // max(1, len(widths) - 1)))
        x = self.width() - (sum(widths) + gap * (len(widths) - 1))
        baseline = self._figure_top(metrics)
        for (value, unit, caption), width in zip(self.tiles, widths):
            painter.setFont(big)
            painter.setPen(colours.value)
            painter.drawText(x, baseline, value)
            painter.setFont(small)
            painter.setPen(colours.unit)
            painter.drawText(x + metrics.horizontalAdvance(value) + self.UNIT_GAP, baseline, unit)
            painter.setFont(eyebrow)
            painter.setPen(colours.caption)
            painter.drawText(x, baseline + self.CAPTION_GAP + eyebrow_metrics.ascent(), caption)
            x += width + gap
        painter.end()


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
