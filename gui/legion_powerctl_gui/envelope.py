# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import a11y, fields, styles, theme, tiles

RADIUS = 6
MARKER_WIDTH = 3
OVERHANG = 3
HALO = 1
RING_GAP = 2
RING_WIDTH = 2
EDGE = OVERHANG + HALO + RING_GAP + RING_WIDTH
GAP = 2
LINE_SPACING = 8
TICK_WIDTH = 7
TICK_HEIGHT = 5
TICK_GAP = 2


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
        self.reference: tuple[int, ...] = ()
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

    def set_reference(self, values: Iterable[int] | None) -> None:
        values = tuple(values or ())
        if values != self.reference:
            self.reference = values
            self.update()

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

        self._draw_reference(painter, bar)
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

    def _draw_reference(self, painter: QPainter, bar: QRect) -> None:
        palette = self.palette()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.secondary_color(palette, palette.color(QPalette.ColorRole.Base)))
        top = bar.bottom() + 1 + TICK_GAP
        half = TICK_WIDTH / 2
        for value in dict.fromkeys(self.reference):
            if not self._low <= value <= self._high:
                continue
            x = self.x_for(value) + 0.5
            painter.drawPolygon(QPolygonF([
                QPointF(x, top), QPointF(x - half, top + TICK_HEIGHT),
                QPointF(x + half, top + TICK_HEIGHT),
            ]))

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
        plate = box.adjusted(-1, -1, 1, marker.bottom() - box.bottom()) if stop.hasFocus() else halo
        painter.drawRoundedRect(plate, 3, 3)
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
                 note: str = "", captions: tuple[str, ...] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._low = low
        self._suffix = suffix
        self._unit = unit
        self._note = note
        self._tier_labels = dict(tiers)
        self._measured = True
        self.bar = EnvelopeBar(low, high)
        self.stops: dict[str, _Stop] = {}
        self.spins: dict[str, QSpinBox] = {}
        self.tiles: dict[str, tiles.ValueTile] = {}
        self.scale = (
            fields.scale_label(f"{low}{suffix}"),
            fields.scale_label(f"{high}{suffix}", Qt.AlignmentFlag.AlignLeft),
        )

        captions = captions or tuple(label for _key, label in tiers)
        for index, (key, label) in enumerate(tiers):
            stop = self.bar.add_stop(label)
            tile = tiles.ValueTile(captions[index] if len(tiers) > 1 else "", low, high, suffix)
            spin = tile.spin
            stop.valueChanged.connect(lambda value, k=key: self.tier_changed.emit(k, value))
            spin.valueChanged.connect(lambda value, k=key: self.tier_changed.emit(k, value))
            spin.valueChanged.connect(self._show_deltas)
            spin.lineEdit().textEdited.connect(self.edited)
            self.stops[key] = stop
            self.spins[key] = spin
            self.tiles[key] = tile
            self._name(key)

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(LINE_SPACING)
        line.addWidget(self.scale[0])
        line.addWidget(self.bar, 1)
        line.addWidget(self.scale[1])
        entries = list(self.tiles.values())
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

    def set_high(self, high: int) -> None:
        self.bar._high = high
        self.scale[1].setText(f"{high}{self._suffix}")
        for key, stop in self.stops.items():
            stop.setMaximum(high)
            self.spins[key].setMaximum(high)
            self._name(key)
        self.bar.update()

    def set_reference(self, values: Iterable[int] | None, measured: bool = True) -> None:
        self.bar.set_reference(values)
        self._measured = measured
        self._show_deltas()

    def _show_deltas(self) -> None:
        reference = dict(zip(self.stops, self.bar.reference)) if self._measured else {}
        for key, tile in self.tiles.items():
            running = reference.get(key)
            if tile.set_delta(None if running is None else self.spins[key].value() - running):
                self._name(key)

    def _name(self, key: str) -> None:
        a11y.name_range(
            self.stops[key], self.spins[key], self._tier_labels[key], self._unit,
            self._low, self.stops[key].maximum(), self._note, self.tiles[key].delta.accessibleName(),
        )

    def restyle(self, palette: QPalette) -> None:
        for index, tile in enumerate(self.tiles.values()):
            tile.restyle(palette, theme.tier_step(index))
        for label in self.scale:
            label.setStyleSheet(styles.caption_style(palette))
        self.bar.update()
