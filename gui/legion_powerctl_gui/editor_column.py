# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import a11y, styles, theme
from .editor import ProfileEditor

HEADER_GAP = 10
TITLE_HEIGHT = 28


class EditorColumn(QFrame):
    def __init__(self, editor: ProfileEditor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("editorHeader")
        header_row = QHBoxLayout(self.header)
        header_row.setContentsMargins(0, 0, 0, HEADER_GAP)
        editor.profile_title.setFont(theme.font("title"))
        editor.profile_title.setMinimumHeight(TITLE_HEIGHT)
        header_row.addWidget(editor.profile_title)
        layout.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setAccessibleName("Profile settings")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(editor)
        self.focus_ring = a11y.FocusRing(self.scroll)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(editor.problems_label)
        editor.problems_label.installEventFilter(self)

        self.footer = QFrame()
        self.footer.setObjectName("editorFooter")
        self.footer.setMinimumHeight(styles.FOOTER_HEIGHT)
        footer_row = QHBoxLayout(self.footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        editor.dirty_label.setFont(theme.font("caption"))
        footer_row.addWidget(editor.dirty_label)
        footer_row.addStretch(1)
        footer_row.addWidget(editor.apply_button)
        layout.addWidget(self.footer)

        self.restyle(self.palette())

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            QTimer.singleShot(0, self, self._keep_focus_in_view)
        return False

    def _keep_focus_in_view(self) -> None:
        focused = QApplication.focusWidget()
        if focused is not None and self.editor.isAncestorOf(focused):
            self.scroll.ensureWidgetVisible(focused)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        return QSize(max(hint.width(), self.editor.minimumSizeHint().width() + bar), hint.height())

    def restyle(self, palette: QPalette) -> None:
        window = palette.color(QPalette.ColorRole.Window)
        self.footer.setStyleSheet(styles.footer_style(palette))
        self.editor.dirty_label.setStyleSheet(
            f"color: {theme.muted_color(palette, window).name()};"
        )
        self.editor.apply_button.setStyleSheet(styles.primary_button_style(palette))
