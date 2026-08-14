# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import model
from .profile_delegate import BOOT_ROLE, DETAIL_ROLE, RUNNING_ROLE, ProfileDelegate


class ProfileList(QWidget):
    profile_chosen = Signal(object)
    new_requested = Signal()
    delete_requested = Signal()
    boot_requested = Signal(str)
    refused = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles: list[model.Profile] = []
        self._boot = ""
        self._running = ""
        self._drafts: set[str] = set()
        self._rendered: tuple | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setAccessibleName("Profiles")
        self.list.setIconSize(QSize(18, 18))
        self.delegate = ProfileDelegate(self)
        self.delegate.boot_requested.connect(self.boot_requested)
        self.list.setItemDelegate(self.delegate)
        self.list.setMouseTracking(True)
        self.list.setSpacing(0)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.boot_action = QAction("Set as &boot profile", self)
        self.boot_action.triggered.connect(self._on_boot_action)
        self.list.addAction(self.boot_action)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.new_button = QPushButton("&New profile")
        self.new_button.clicked.connect(self.new_requested)
        self.delete_button = QPushButton("De&lete")
        self.delete_button.clicked.connect(self.delete_requested)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

    def set_delete_enabled(self, enabled: bool) -> None:
        self.delete_button.setEnabled(enabled)

    @property
    def drafts(self) -> set[str]:
        return self._drafts

    def valid_names(self) -> set[str]:
        return {profile.name for profile in self._profiles if profile.valid}

    def set_profiles(
        self, profiles: list[model.Profile], boot: str, select: str, running: str = ""
    ) -> None:
        self._drafts -= {profile.name for profile in profiles}
        drawn = (list(profiles), boot, running, sorted(self._drafts), select)
        if drawn == self._rendered:
            return
        self._profiles = profiles
        self._boot = boot
        self._running = running
        self._rebuild(select or running or boot)
        self._rendered = drawn

    def create_draft(self, name: str) -> None:
        if not model.valid_profile_name(name):
            self.refused.emit("Profile name may use letters, numbers, dot, underscore, dash.")
            return
        if name in self.valid_names() or name in self._drafts:
            self.refused.emit(f"Profile '{name}' already exists; opening it for editing.")
            self.select_by_name(name)
            return
        self._drafts.add(name)
        self._rebuild(name)

    def discard_draft(self, name: str) -> None:
        self._drafts.discard(name)
        self._rebuild(self._running or self._boot)

    def select_by_name(self, name: str) -> None:
        broken_row = None
        for row in range(self.list.count()):
            profile = self.list.item(row).data(Qt.ItemDataRole.UserRole)
            if profile is not None and profile.name == name:
                if profile.valid:
                    self.list.setCurrentRow(row)
                    return
                if broken_row is None:
                    broken_row = row
        if broken_row is not None:
            self.list.setCurrentRow(broken_row)
            return
        for row in range(self.list.count()):
            profile = self.list.item(row).data(Qt.ItemDataRole.UserRole)
            if profile is not None and profile.valid:
                self.list.setCurrentRow(row)
                return

    def restore_selection(self, name: str) -> bool:
        self.list.blockSignals(True)
        try:
            for row in range(self.list.count()):
                profile = self.list.item(row).data(Qt.ItemDataRole.UserRole)
                if profile is not None and profile.name == name:
                    self.list.setCurrentRow(row)
                    return True
            return False
        finally:
            self.list.blockSignals(False)

    def _rebuild(self, select: str) -> None:
        self._rendered = None
        self.list.blockSignals(True)
        self.list.clear()
        for profile in self._profiles:
            item = QListWidgetItem(profile.name)
            item.setData(Qt.ItemDataRole.UserRole, profile)
            item.setData(DETAIL_ROLE, profile.summary())
            item.setData(RUNNING_ROLE, profile.name == self._running)
            item.setData(BOOT_ROLE, profile.name == self._boot)
            self._name_row(
                item,
                profile,
                running=profile.name == self._running,
                boot=profile.name == self._boot,
            )
            if profile.valid:
                self._set_profile_icon(item, profile)
            self.list.addItem(item)
        for name in sorted(self._drafts):
            item = QListWidgetItem(name)
            draft = model.Profile(name=name)
            item.setData(Qt.ItemDataRole.UserRole, draft)
            item.setData(DETAIL_ROLE, "unsaved")
            item.setData(RUNNING_ROLE, False)
            item.setData(BOOT_ROLE, False)
            self._name_row(item, draft, running=False, boot=False, state="unsaved")
            self._set_profile_icon(item, draft)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.select_by_name(select)

    def _on_current_changed(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        profile = current.data(Qt.ItemDataRole.UserRole)
        if profile is not None:
            self.profile_chosen.emit(profile)

    def _on_boot_action(self) -> None:
        current = self.list.currentItem()
        if current is None:
            return
        profile = current.data(Qt.ItemDataRole.UserRole)
        if self.delegate.pinnable(profile) and not current.data(BOOT_ROLE):
            self.boot_requested.emit(profile.name)

    def _on_context_menu(self, point) -> None:
        item = self.list.itemAt(point)
        if item is None:
            return
        self.list.setCurrentItem(item)
        profile = item.data(Qt.ItemDataRole.UserRole)
        self.boot_action.setEnabled(
            self.delegate.pinnable(profile) and not item.data(BOOT_ROLE)
        )
        menu = QMenu(self.list)
        menu.addAction(self.boot_action)
        menu.exec(self.list.viewport().mapToGlobal(point))

    @staticmethod
    def _name_row(
        item: QListWidgetItem,
        profile: model.Profile,
        running: bool,
        boot: bool,
        state: str = "",
    ) -> None:
        parts = [profile.name]
        if running:
            parts.append("running now")
        if boot:
            parts.append("boot profile")
        parts.append(state or profile.summary())
        item.setData(Qt.ItemDataRole.AccessibleTextRole, ", ".join(parts))

    @staticmethod
    def _set_profile_icon(item: QListWidgetItem, profile: model.Profile) -> None:
        icon_name = model.profile_icon_name(profile.power_profile)
        if icon_name and QIcon.hasThemeIcon(icon_name):
            item.setIcon(QIcon.fromTheme(icon_name))
