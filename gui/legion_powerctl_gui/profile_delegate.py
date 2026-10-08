# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import theme

RUNNING_ROLE = Qt.ItemDataRole.UserRole + 1
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 2
BOOT_ROLE = Qt.ItemDataRole.UserRole + 3

ROW_HEIGHT = 52
ROW_PADDING = 8
RAIL_WIDTH = 3
RAIL_INSET = 8
RAIL_RADIUS = 1.5
PADDING = 12
EDGE_PADDING = 16
GAP = 8
ICON_SIZE = 16
HOVER_TINT = 0.04

PIN_TEXT = "BOOT"
PIN_ACTION_TEXT = "SET BOOT"
PIN_PAD = 6
PIN_HEIGHT = 18
PIN_RADIUS = 4

FOCUS_INSET = 2
FOCUS_WIDTH = 2
FOCUS_RADIUS = 6


class RowLines:
    def __init__(self, option) -> None:
        self.name_font = theme.font("strong", option.font)
        self.detail_font = theme.font("detail-mono", option.font)
        self.name_height = max(
            QFontMetrics(self.name_font).height(), option.decorationSize.height()
        )
        self.detail_height = max(QFontMetrics(self.detail_font).height(), PIN_HEIGHT)
        spare = option.rect.height() - self.name_height - self.detail_height
        self.name_top = option.rect.top() + spare // 2
        self.detail_top = self.name_top + self.name_height
        self.left = option.rect.left() + RAIL_WIDTH + PADDING
        self.right = option.rect.right() + 1 - EDGE_PADDING

    @property
    def content_height(self) -> int:
        return self.name_height + self.detail_height


class ProfileDelegate(QStyledItemDelegate):
    boot_requested = Signal(str)

    def sizeHint(self, option, index) -> QSize:
        lines = RowLines(option)
        return QSize(200, max(ROW_HEIGHT, lines.content_height + ROW_PADDING * 2))

    def paint(self, painter, option, index) -> None:
        profile = index.data(Qt.ItemDataRole.UserRole)
        if profile is None:
            super().paint(painter, option, index)
            return

        palette = QPalette(option.palette)
        palette.setCurrentColorGroup(QPalette.ColorGroup.Active)
        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        background = self._background(palette, selected, hovered)
        lines = RowLines(option)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(option.rect, background)
        if index.data(RUNNING_ROLE):
            self._draw_rail(painter, option, palette, background)
        painter.fillRect(
            QRect(lines.left, option.rect.bottom(), max(0, lines.right - lines.left), 1),
            theme.edge_color(palette),
        )

        right = self._draw_watts(painter, profile, palette, background, enabled, lines)
        right = self._draw_icon(painter, option, index, palette, background, enabled, lines, right)
        pin_left = self._draw_pin(
            painter, option, index, profile, palette, background, enabled, lines
        )
        self._draw_text(
            painter, index, profile, palette, background, enabled, lines, right, pin_left
        )
        if state & QStyle.StateFlag.State_HasFocus:
            self._draw_focus(painter, option, palette, background)
        painter.restore()

    @staticmethod
    def pin_rect(option, pinned: bool = False, lines: RowLines | None = None) -> QRect:
        lines = lines or RowLines(option)
        metrics = QFontMetrics(theme.font("pin", option.font))
        width = metrics.horizontalAdvance(PIN_TEXT if pinned else PIN_ACTION_TEXT)
        width += PIN_PAD * 2
        top = lines.detail_top + (lines.detail_height - PIN_HEIGHT) // 2
        return QRect(lines.right - width, top, width, PIN_HEIGHT)

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

    @staticmethod
    def _background(palette: QPalette, selected: bool, hovered: bool) -> QColor:
        if selected:
            return theme.selection_color(palette)
        base = palette.color(QPalette.ColorRole.Base)
        if hovered:
            return theme.tint_color(base, palette.color(QPalette.ColorRole.Text), HOVER_TINT)
        return base

    @staticmethod
    def _draw_rail(painter, option, palette, background) -> None:
        accent = theme.fit_contrast(
            theme.accent_color(palette), background, theme.MIN_NON_TEXT_CONTRAST
        )
        rail = QRectF(
            option.rect.left(),
            option.rect.top() + RAIL_INSET,
            RAIL_WIDTH,
            option.rect.height() - RAIL_INSET * 2,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(rail, RAIL_RADIUS, RAIL_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def _draw_focus(painter, option, palette, background) -> None:
        ring = theme.fit_contrast(
            theme.focus_color(palette), background, theme.MIN_NON_TEXT_CONTRAST
        )
        inset = FOCUS_INSET + FOCUS_WIDTH / 2
        painter.setPen(QPen(ring, FOCUS_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            QRectF(option.rect).adjusted(inset, inset, -inset, -inset),
            FOCUS_RADIUS,
            FOCUS_RADIUS,
        )

    @staticmethod
    def _tinted(icon: QIcon, size: QSize, color: QColor, ratio: float) -> QPixmap:
        pixmap = icon.pixmap(size, ratio)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
        painter.end()
        return pixmap

    def _draw_icon(
        self, painter, option, index, palette, background, enabled, lines, right
    ) -> int:
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is None or icon.isNull():
            return right
        size = option.decorationSize
        color = (
            theme.secondary_color(palette, background)
            if enabled
            else theme.disabled_text_color(palette)
        )
        pixmap = self._tinted(icon, size, color, painter.device().devicePixelRatioF())
        left = right - size.width()
        painter.drawPixmap(
            left, lines.name_top + (lines.name_height - size.height()) // 2, pixmap
        )
        return left - GAP

    @staticmethod
    def _draw_watts(painter, profile, palette, background, enabled, lines) -> int:
        if not profile.valid:
            return lines.right
        text = f"{profile.stapm_w} W"
        width = QFontMetrics(lines.detail_font).horizontalAdvance(text)
        painter.setFont(lines.detail_font)
        painter.setPen(
            theme.fit_contrast(palette.color(QPalette.ColorRole.Text), background)
            if enabled
            else theme.disabled_text_color(palette)
        )
        painter.drawText(
            QRect(lines.right - width, lines.name_top, width, lines.name_height),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            text,
        )
        return lines.right - width - GAP

    def _draw_pin(
        self, painter, option, index, profile, palette, background, enabled, lines
    ) -> int:
        if not self.pinnable(profile):
            return lines.right
        pinned = bool(index.data(BOOT_ROLE))
        shown = option.state & (
            QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected
        )
        if not pinned and not shown:
            return lines.right
        rect = self.pin_rect(option, pinned, lines)
        disabled = theme.disabled_text_color(palette)
        painter.setFont(theme.font("pin", option.font))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if pinned:
            fill = (
                theme.fit_contrast(
                    palette.color(QPalette.ColorRole.Text),
                    background,
                    theme.MIN_NON_TEXT_CONTRAST,
                )
                if enabled
                else disabled
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, PIN_RADIUS, PIN_RADIUS)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(theme.fit_contrast(palette.color(QPalette.ColorRole.Base), fill))
        else:
            outline = (
                theme.edge_strong_color(palette, background)
                if enabled
                else theme.edge_color(palette)
            )
            painter.setPen(QPen(outline, 1))
            painter.drawRoundedRect(
                QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), PIN_RADIUS, PIN_RADIUS
            )
            painter.setPen(
                theme.secondary_color(palette, background) if enabled else disabled
            )
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignCenter, PIN_TEXT if pinned else PIN_ACTION_TEXT
        )
        return rect.left() - GAP

    @staticmethod
    def _draw_text(
        painter, index, profile, palette, background, enabled, lines, right, pin_left
    ) -> None:
        disabled = theme.disabled_text_color(palette)
        if not enabled:
            primary = secondary = disabled
        elif profile.valid:
            primary = theme.fit_contrast(palette.color(QPalette.ColorRole.Text), background)
            secondary = theme.secondary_color(palette, background)
        else:
            primary = theme.fit_contrast(theme.severity_color(palette, "FAIL"), background)
            secondary = theme.secondary_color(palette, background)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        left = lines.left
        name_width = max(0, right - left)
        painter.setFont(lines.name_font)
        painter.setPen(primary)
        painter.drawText(
            QRect(left, lines.name_top, name_width, lines.name_height),
            align,
            QFontMetrics(lines.name_font).elidedText(
                profile.name, Qt.TextElideMode.ElideRight, name_width
            ),
        )
        detail_width = max(0, pin_left - left)
        painter.setFont(lines.detail_font)
        painter.setPen(secondary)
        painter.drawText(
            QRect(left, lines.detail_top, detail_width, lines.detail_height),
            align,
            QFontMetrics(lines.detail_font).elidedText(
                str(index.data(DETAIL_ROLE) or ""), Qt.TextElideMode.ElideRight, detail_width
            ),
        )

