# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(
        self, parent=None, spacing: int = 6, line_spacing: int | None = None,
        min_spacing: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self._line_spacing = spacing if line_spacing is None else line_spacing
        self._min_spacing = spacing if min_spacing is None else min_spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def spacing(self) -> int:
        return self._spacing

    def _lines(self, width: int) -> list[list]:
        lines, used = [[]], 0
        for item in self._items:
            hint = item.sizeHint().width()
            gap = self._min_spacing if lines[-1] else 0
            if lines[-1] and used + gap + hint > width:
                lines.append([])
                used, gap = 0, 0
            used += gap + hint
            lines[-1].append(item)
        return lines

    def _lay_out(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        y = area.y()
        for index, line in enumerate(self._lines(area.width())):
            if index:
                y += self._line_spacing
            hints = [item.sizeHint() for item in line]
            spacing = self._spacing
            if len(line) > 1:
                spare = area.width() - sum(hint.width() for hint in hints)
                spacing = min(spacing, spare // (len(line) - 1))
            x = area.x()
            for item, hint in zip(line, hints):
                if apply:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + spacing
            y += max((hint.height() for hint in hints), default=0)
        return y - rect.y() + margins.bottom()
