# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from collections import deque

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from . import __version__, dialogs, model
from .actions import ProfileActions
from .editor import ProfileEditor
from .header import MachineHeader
from .reports import ReportArea
from .runner import CommandRunner
from .sidebar import ProfileList

REFRESH_INTERVAL_MS = 15000
POLL_TIMEOUT_MS = 10000


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._built = False
        self.setWindowTitle("Legion Power Control")
        self.setWindowIcon(QIcon.fromTheme("legion-powerctl"))
        self.resize(960, 620)
        self.setMinimumSize(720, 480)

        self.dialogs = os.environ.get("LEGION_POWERCTL_GUI_NO_DIALOGS") != "1"
        self._status_inflight = False
        self._pending_open = ""
        self._focus_before_busy = None
        self.refresh_count = 0
        self.status: model.Status | None = None
        self.errors: deque[str] = deque(maxlen=50)

        self.runner = CommandRunner(self)
        self.runner.failed.connect(self._show_error)

        self._build_ui()
        self.refresh()
        self.checks.run()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)
        self._refresh_timer.start()

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        self.header = MachineHeader(__version__)
        outer.addWidget(self.header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        self.sidebar = ProfileList()
        splitter.addWidget(self.sidebar)
        self.editor = ProfileEditor()
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setAccessibleName("Profile settings")
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setWidget(self.editor)
        splitter.addWidget(self.editor_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])

        self.setCentralWidget(central)
        self.reports = ReportArea(self.statusBar(), self.dialogs, self)
        self.reports.go_back_requested.connect(self._on_go_back)
        self.statusBar().addPermanentWidget(self.header.machine_label)
        self.checks = dialogs.ChecksController(self, self.runner, self.header, POLL_TIMEOUT_MS)
        self.profile_actions = ProfileActions(self, self.runner, self.editor, self.sidebar)
        self._save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._save_shortcut.activated.connect(self.profile_actions.save)
        self._connect()
        self._built = True

    def _connect(self) -> None:
        self.sidebar.profile_chosen.connect(self._on_profile_chosen)
        self.sidebar.refused.connect(self._show_error)
        self.sidebar.new_requested.connect(self.profile_actions.new_profile)
        self.sidebar.delete_requested.connect(self.profile_actions.delete)
        self.sidebar.boot_requested.connect(self.profile_actions.pin_boot)
        self.editor.armed.connect(self.sidebar.set_delete_enabled)
        self.editor.apply_requested.connect(self.profile_actions.apply)
        self.header.service_toggled.connect(self.profile_actions.set_service)
        self.header.checks_requested.connect(self.checks.show)
        self.profile_actions.succeeded.connect(self._on_action_succeeded)
        self.profile_actions.warned.connect(self._on_action_warned)
        self.profile_actions.failed.connect(self._on_action_failed)
        self.profile_actions.cancelled.connect(self._on_action_cancelled)
        self.profile_actions.busy_changed.connect(self._set_busy)

    def _show_error(self, message: str) -> None:
        self.errors.append(message)
        self.reports.error(message)

    def _on_action_succeeded(self, message: str) -> None:
        self.reports.success(message, self.profile_actions.previous_profile)
        self.refresh()

    def _on_action_warned(self, message: str, detail: str) -> None:
        self.reports.warning(message, detail)
        self.refresh()

    def _on_action_failed(self, message: str) -> None:
        self._pending_open = ""
        self._show_error(message)

    def _on_action_cancelled(self, message: str) -> None:
        self._pending_open = ""
        self.reports.note(message)

    def _on_go_back(self) -> None:
        previous = self.profile_actions.previous_profile
        self.reports.clear_offers()
        if previous:
            self.profile_actions.apply_saved(previous)

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._focus_before_busy = QApplication.focusWidget()
        self.editor.set_busy(busy)
        self.header.set_busy(busy)
        self.sidebar.setEnabled(not busy)
        if not busy:
            widget, self._focus_before_busy = self._focus_before_busy, None
            if widget is not None and isValid(widget) and widget.isEnabled():
                widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh(self) -> None:
        self._status_inflight = True
        self.runner.run(
            model.unprivileged_command(["status", "--json"]),
            self._on_status_done,
            timeout_ms=POLL_TIMEOUT_MS,
        )

    def _on_refresh_timer(self) -> None:
        if self._status_inflight and self.runner.processes:
            return
        self.refresh()

    def _on_status_done(self, code: int, stdout: str, stderr: str) -> None:
        self._status_inflight = False
        self.refresh_count += 1
        if code != 0:
            self._show_error(stderr.strip() or "status --json failed.")
            return
        try:
            status = model.parse_status(stdout)
        except model.StatusParseError as exc:
            self._show_error(str(exc))
            return
        self.status = status
        self.header.show_status(status)
        running = str((status.last_apply or {}).get("profile", ""))
        self.sidebar.set_profiles(
            status.profiles, status.active_profile, self.editor.current_name, running
        )
        if self._pending_open:
            name, self._pending_open = self._pending_open, ""
            self.sidebar.select_by_name(name)

    def _on_profile_chosen(self, profile: model.Profile) -> None:
        if self.editor.dirty and self.editor.editing is not None:
            previous_name = self.editor.editing.name
            if profile.name == previous_name:
                return
            if not self._confirm_discard(profile.name):
                if not self.sidebar.restore_selection(previous_name):
                    self.sidebar.create_draft(previous_name)
                return
        if not profile.valid:
            self.editor.show_invalid(profile.name)
            return
        self.editor.load(profile)

    def _confirm_discard(self, target_name: str) -> bool:
        if not self.dialogs:
            return True
        answer = QMessageBox.question(
            self,
            "Discard unsaved changes?",
            f"'{self.editor.editing.name}' has unsaved changes. Discard them and open "
            f"'{target_name}'?",
            QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            self._pending_open = target_name
            self.profile_actions.save()
            return False
        return answer == QMessageBox.StandardButton.Discard

    def changeEvent(self, event) -> None:
        if self._built:
            if event.type() in (
                QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange
            ):
                palette = self.palette()
                self.header.restyle(palette)
                self.editor.restyle(palette)
                self.checks.restyle(palette)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self.runner.stop_all()
        super().closeEvent(event)
