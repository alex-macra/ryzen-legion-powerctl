# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPalette, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import theme

RUNNING_ROLE = Qt.ItemDataRole.UserRole + 1
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 2
BOOT_ROLE = Qt.ItemDataRole.UserRole + 3

RAIL_WIDTH = 3
DOT_DIAMETER = 8
PADDING = 8
GAP = 8

PIN_TEXT = "BOOT"
PIN_ACTION_TEXT = "SET BOOT"
PIN_PAD = 5


class ProfileDelegate(QStyledItemDelegate):
    boot_requested = Signal(str)

    def sizeHint(self, option, index) -> QSize:
        metrics = option.fontMetrics
        return QSize(200, metrics.height() * 2 + metrics.leading() + PADDING * 2)

    def paint(self, painter, option, index) -> None:
        profile = index.data(Qt.ItemDataRole.UserRole)
        if profile is None:
            super().paint(painter, option, index)
            return

        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        running = bool(index.data(RUNNING_ROLE))
        background = self._background(palette, selected, running)
        accent = theme.fit_contrast(
            theme.accent_color(palette), background, theme.MIN_NON_TEXT_CONTRAST
        )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(option.rect, background)
        if running:
            rail = QRect(option.rect.topLeft(), QSize(RAIL_WIDTH, option.rect.height()))
            painter.fillRect(rail, theme.on_accent_color(palette) if selected else accent)
        painter.setPen(QPen(theme.edge_color(palette), 1))
        painter.drawLine(
            option.rect.left(), option.rect.bottom(), option.rect.right(), option.rect.bottom()
        )

        left = self._draw_marker(painter, option, index, background, accent, running, selected)
        right = self._draw_watts(painter, option, profile, palette, background, selected)
        pin_left = self._draw_pin(
            painter, option, index, profile, palette, background, selected, accent
        )
        self._draw_text(
            painter, option, index, profile, palette, background, selected, left, right, pin_left
        )

        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(accent, 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()

    @staticmethod
    def pin_rect(option, pinned: bool = False) -> QRect:
        metrics = option.fontMetrics
        width = metrics.horizontalAdvance(PIN_TEXT if pinned else PIN_ACTION_TEXT)
        width += PIN_PAD * 2
        height = metrics.height()
        return QRect(
            option.rect.right() - PADDING - width,
            option.rect.bottom() - PADDING - height + 1,
            width,
            height,
        )

    @staticmethod
    def pinnable(profile) -> bool:
        return profile is not None and profile.valid

    def editorEvent(self, event, item_model, option, index) -> bool:
        profile = index.data(Qt.ItemDataRole.UserRole)
        if (
            event.type() == event.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.pinnable(profile)
            and not index.data(BOOT_ROLE)
            and self.pin_rect(option, pinned=False).contains(event.position().toPoint())
        ):
            self.boot_requested.emit(profile.name)
            return True
        return super().editorEvent(event, item_model, option, index)

    def _draw_pin(
        self, painter, option, index, profile, palette, background, selected, accent
    ) -> int:
        edge = option.rect.right() - PADDING
        if not self.pinnable(profile):
            return edge
        pinned = bool(index.data(BOOT_ROLE))
        hovered = bool(
            option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected)
        )
        if not pinned and not hovered:
            return edge
        rect = self.pin_rect(option, pinned)
        ink = theme.on_accent_color(palette) if selected else accent
        painter.setPen(Qt.PenStyle.NoPen)
        if pinned:
            painter.setBrush(ink)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(
                theme.fit_contrast(background if selected else theme.on_accent_color(palette), ink)
            )
        else:
            outline = theme.fit_contrast(
                theme.muted_color(palette, background), background, theme.MIN_NON_TEXT_CONTRAST
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(outline, 1))
            painter.drawRoundedRect(rect, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        font = QFont(option.font)
        font.setPointSizeF(max(1.0, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignCenter, PIN_TEXT if pinned else PIN_ACTION_TEXT
        )
        painter.setFont(QFont(option.font))
        return rect.left() - GAP

    @staticmethod
    def _background(palette: QPalette, selected: bool, running: bool):
        if selected:
            return palette.color(QPalette.ColorRole.Highlight)
        base = palette.color(QPalette.ColorRole.Base)
        return theme.wash_color(palette, base) if running else base

    @staticmethod
    def _text_colors(palette: QPalette, background, selected: bool, valid: bool):
        if selected:
            primary = theme.fit_contrast(
                palette.color(QPalette.ColorRole.HighlightedText), background
            )
            return primary, primary
        primary = theme.fit_contrast(palette.color(QPalette.ColorRole.Text), background)
        if not valid:
            primary = theme.fit_contrast(theme.severity_color(palette, "FAIL"), background)
        return primary, theme.muted_color(palette, background)

    def _draw_marker(self, painter, option, index, background, accent, active, selected) -> int:
        left = option.rect.left() + RAIL_WIDTH + PADDING
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        size = option.decorationSize
        if icon is not None and not icon.isNull():
            icon.paint(
                painter,
                QRect(
                    left,
                    option.rect.center().y() - size.height() // 2 + 1,
                    size.width(),
                    size.height(),
                ),
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Selected if selected else QIcon.Mode.Normal,
            )
            return left + size.width() + GAP
        dot = QRect(
            left + 2, option.rect.center().y() - DOT_DIAMETER // 2, DOT_DIAMETER, DOT_DIAMETER
        )
        painter.setPen(Qt.PenStyle.NoPen)
        if active:
            painter.setBrush(theme.on_accent_color(option.palette) if selected else accent)
        else:
            painter.setBrush(theme.muted_color(option.palette, background))
        painter.drawEllipse(dot)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        return left + DOT_DIAMETER + GAP + 2

    def _draw_watts(self, painter, option, profile, palette, background, selected) -> int:
        if not profile.valid:
            return option.rect.right() - PADDING
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(QFont(option.font).pointSizeF())
        painter.setFont(font)
        text = f"{profile.stapm_w} W"
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text)
        right = option.rect.right() - PADDING - width
        painter.setPen(self._text_colors(palette, background, selected, True)[1])
        painter.drawText(
            QRect(right, option.rect.top() + PADDING, width, metrics.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            text,
        )
        painter.setFont(QFont(option.font))
        return right - GAP

    def _draw_text(
        self, painter, option, index, profile, palette, background, selected, left, right, pin_left
    ) -> None:
        primary, secondary = self._text_colors(palette, background, selected, profile.valid)
        width = max(0, right - left)
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        metrics = painter.fontMetrics()
        top = option.rect.top() + PADDING
        painter.setPen(primary)
        painter.drawText(
            QRect(left, top, width, metrics.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(profile.name, Qt.TextElideMode.ElideRight, width),
        )
        detail_font = QFont(option.font)
        detail_font.setBold(False)
        painter.setFont(detail_font)
        detail_metrics = painter.fontMetrics()
        painter.setPen(secondary)
        detail_width = max(0, pin_left - left)
        painter.drawText(
            QRect(left, top + metrics.height(), detail_width, detail_metrics.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            detail_metrics.elidedText(
                str(index.data(DETAIL_ROLE) or ""), Qt.TextElideMode.ElideRight, detail_width
            ),
        )
