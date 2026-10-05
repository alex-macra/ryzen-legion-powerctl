# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QPalette
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

HEADER_GAP = 8
TITLE_HEIGHT = 26
TITLE_GAP = 10


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
        header_row.setSpacing(TITLE_GAP)
        bottom = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        editor.profile_title.setFont(theme.font("title"))
        editor.profile_title.setMinimumHeight(TITLE_HEIGHT)
        editor.profile_title.setAlignment(bottom)
        editor.title_aside.setAlignment(bottom)
        header_row.addWidget(editor.profile_title)
        header_row.addWidget(editor.title_aside, 0, Qt.AlignmentFlag.AlignBottom)
        header_row.addStretch(1)
        self._fit_aside()
        for label in (editor.profile_title, editor.title_aside):
            label.installEventFilter(self)
        layout.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setAccessibleName("Profile settings")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(editor)
        self.focus_ring = a11y.FocusRing(self.scroll)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._fit_gap)
        for watched in (self.scroll, editor):
            watched.installEventFilter(self)
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
        kind = event.type()
        if watched in (self.scroll, self.editor):
            if kind in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
                self._fit_bar()
        elif kind == QEvent.Type.FontChange:
            self._fit_aside()
        elif watched is self.editor.problems_label and kind in (
            QEvent.Type.Show, QEvent.Type.Hide
        ):
            QTimer.singleShot(0, self, self._keep_focus_in_view)
        return False

    def _fit_aside(self) -> None:
        title, aside = self.editor.profile_title, self.editor.title_aside
        drop = QFontMetrics(title.font()).descent() - QFontMetrics(aside.font()).descent()
        aside.setContentsMargins(0, 0, 0, max(0, drop))

    def _fit_bar(self) -> None:
        # Qt measures at the current viewport, so a bar that wraps the tiles would justify itself.
        room = self.scroll.contentsRect().size()
        beside = room.width() - self.scroll.verticalScrollBar().sizeHint().width()
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if self.editor.height_beside_a_bar(beside) > room.height()
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        if self.scroll.verticalScrollBarPolicy() != policy:
            self.scroll.setVerticalScrollBarPolicy(policy)
        self._fit_gap()

    def _fit_gap(self, *_range) -> None:
        kept = self.scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        self.editor.set_scrollbar_gap(kept or self.scroll.verticalScrollBar().maximum() > 0)

    def _keep_focus_in_view(self) -> None:
        focused = QApplication.focusWidget()
        if focused is not None and self.editor.isAncestorOf(focused):
            self.scroll.ensureWidgetVisible(focused)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        return QSize(max(hint.width(), self.editor.width_beside_a_bar() + bar), hint.height())

    def restyle(self, palette: QPalette) -> None:
        window = palette.color(QPalette.ColorRole.Window)
        self.footer.setStyleSheet(styles.footer_style(palette))
        muted = f"color: {theme.muted_color(palette, window).name()};"
        self.editor.dirty_label.setStyleSheet(muted)
        self.editor.title_aside.setStyleSheet(muted)
        self.editor.apply_button.setStyleSheet(styles.primary_button_style(palette))
