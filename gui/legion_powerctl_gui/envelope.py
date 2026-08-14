# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import a11y, fields, theme

RADIUS = 4
MARKER_WIDTH = 3
OVERHANG = 3
HALO = 1
RING_GAP = 2
RING_WIDTH = 2
EDGE = OVERHANG + HALO + RING_GAP + RING_WIDTH
GAP = 4


class _Stop(QSlider):
    def paintEvent(self, event) -> None:
        pass

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.parentWidget().update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.parentWidget().update()


class EnvelopeBar(QWidget):
    def __init__(self, low: int, high: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._low = low
        self._high = high
        self.stops: list[_Stop] = []
        self._dragging: _Stop | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def add_stop(self, label: str) -> _Stop:
        stop = _Stop(Qt.Orientation.Horizontal, self)
        stop.setRange(self._low, self._high)
        stop.setAccessibleName(label)
        stop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        stop.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        stop.valueChanged.connect(self.update)
        stop.setGeometry(self._bar_rect())
        self.stops.append(stop)
        return stop

    def bar_height(self) -> int:
        return self.fontMetrics().height()

    def sizeHint(self) -> QSize:
        return QSize(240, EDGE * 2 + self.bar_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(120, self.sizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for stop in self.stops:
            stop.setGeometry(self._bar_rect())

    def paintEvent(self, event) -> None:
        palette = self.palette()
        background = palette.color(QPalette.ColorRole.Base)
        bar = self._bar_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        path = QPainterPath()
        path.addRoundedRect(QRectF(bar), RADIUS, RADIUS)
        painter.fillPath(path, theme.track_color(palette, background))
        painter.setClipPath(path)
        for index in reversed(range(len(self.stops))):
            right = self.x_for(self.stops[index].value())
            painter.fillRect(
                QRect(bar.left(), bar.top(), right - bar.left(), bar.height()),
                theme.tier_color(palette, background, theme.tier_step(index)),
            )
        painter.setClipping(False)

        for stop in self.stops:
            self._draw_marker(painter, stop, background)
        painter.end()

    def mousePressEvent(self, event) -> None:
        stop = self._nearest(round(event.position().x()))
        if stop is None:
            return
        self._dragging = stop
        stop.setFocus(Qt.FocusReason.MouseFocusReason)
        stop.setValue(self._value_at(round(event.position().x())))

    def mouseMoveEvent(self, event) -> None:
        if self._dragging is not None:
            self._dragging.setValue(self._value_at(round(event.position().x())))

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = None

    def _bar_rect(self) -> QRect:
        return QRect(EDGE, EDGE, max(1, self.width() - EDGE * 2), self.bar_height())

    def x_for(self, value: int) -> int:
        bar = self._bar_rect()
        span = max(1, self._high - self._low)
        return bar.left() + round((value - self._low) / span * (bar.width() - 1))

    def _value_at(self, x: int) -> int:
        bar = self._bar_rect()
        span = self._high - self._low
        fraction = (x - bar.left()) / max(1, bar.width() - 1)
        return max(self._low, min(self._high, self._low + round(fraction * span)))

    def _nearest(self, x: int) -> _Stop | None:
        if not self.stops:
            return None
        distances = [abs(self.x_for(stop.value()) - x) for stop in self.stops]
        closest = min(distances)
        tied = [index for index, distance in enumerate(distances) if distance == closest]
        if len(tied) == 1:
            return self.stops[tied[0]]
        return self.stops[tied[-1] if x >= self.x_for(self.stops[tied[0]].value()) else tied[0]]

    def _draw_marker(self, painter: QPainter, stop: _Stop, background) -> None:
        centre = self.x_for(stop.value())
        bar = self._bar_rect()
        half = MARKER_WIDTH // 2
        top, height = bar.top() - OVERHANG, bar.height() + OVERHANG * 2
        marker = QRect(centre - half, top, MARKER_WIDTH, height)
        halo = marker.adjusted(-HALO, -HALO, HALO, HALO)
        box = halo.adjusted(-RING_GAP, -RING_GAP, RING_GAP, RING_GAP)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(box.adjusted(-1, -1, 1, 1) if stop.hasFocus() else halo, 3, 3)
        painter.setBrush(theme.marker_color(self.palette(), background))
        painter.drawRoundedRect(marker, 1, 1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if stop.hasFocus():
            ring = theme.fit_contrast(
                theme.focus_color(self.palette()), background, theme.MIN_NON_TEXT_CONTRAST
            )
            painter.setPen(QPen(ring, RING_WIDTH))
            painter.drawRoundedRect(box, 3, 3)


class Envelope(QWidget):
    tier_changed = Signal(str, int)
    edited = Signal()

    def __init__(self, tiers, low: int, high: int, suffix: str, unit: str,
                 note: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bar = EnvelopeBar(low, high)
        self.stops: dict[str, _Stop] = {}
        self.spins: dict[str, QSpinBox] = {}
        self._swatches: list = []
        self.scale = (fields.scale_label(f"{low}{suffix}"), fields.scale_label(f"{high}{suffix}"))

        entries = []
        for index, (key, label) in enumerate(tiers):
            stop = self.bar.add_stop(label)
            entry, swatch, spin = fields.value_entry(
                label if len(tiers) > 1 else "", low, high, suffix
            )
            stop.valueChanged.connect(lambda value, k=key: self.tier_changed.emit(k, value))
            spin.valueChanged.connect(lambda value, k=key: self.tier_changed.emit(k, value))
            spin.lineEdit().textEdited.connect(self.edited)
            a11y.name_range(stop, spin, label, unit, low, high, note)
            entries.append(entry)
            self.stops[key] = stop
            self.spins[key] = spin
            self._swatches.append((swatch, theme.tier_step(index)))

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.scale[0])
        line.addWidget(self.bar, 1)
        line.addWidget(self.scale[1])
        if len(entries) == 1:
            line.addWidget(entries[0])
            self.setLayout(line)
            return
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP)
        column.addLayout(line)
        row = fields.value_row()
        column.addLayout(row)
        for entry in entries:
            row.addWidget(entry)

    def restyle(self, palette: QPalette) -> None:
        background = palette.color(QPalette.ColorRole.Base)
        for swatch, step in self._swatches:
            swatch.setStyleSheet(theme.swatch_style(palette, background, step))
        for label in self.scale:
            label.setStyleSheet(theme.caption_style(palette))
        self.bar.update()
