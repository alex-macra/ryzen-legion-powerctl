# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from . import dialogs, model, runstate

if TYPE_CHECKING:
    from .app import MainWindow
    from .editor import ProfileEditor
    from .runner import CommandRunner
    from .sidebar import ProfileList

PKEXEC_DISMISSED = 126
PKEXEC_NOT_RUN = 127

SERVICE_ON = "Boot service on; the boot profile was applied."


class ProfileActions(QObject):
    succeeded = Signal(str)
    failed = Signal(str)
    warned = Signal(str, str)
    cancelled = Signal(str)
    busy_changed = Signal(bool)
    repaired = Signal()
    repair_backup = Signal(str)

    def __init__(
        self,
        window: MainWindow,
        runner: CommandRunner,
        editor: ProfileEditor,
        sidebar: ProfileList,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._runner = runner
        self._editor = editor
        self._sidebar = sidebar
        self._busy = False
        self.previous_profile = ""

    def save(self) -> None:
        profile = self._guard_editor()
        if profile is None:
            return
        self._run(
            model.build_configure_args(profile),
            f"Saved profile '{profile.name}'.",
            saved=profile,
        )

    def apply(self) -> None:
        profile = self._guard_editor()
        if profile is None:
            return
        running = runstate.run_state(self._window.status) if self._window.status else None
        go_back = ""
        if running is not None:
            deltas = runstate.raising_deltas(running, profile)
            if deltas and self._window.dialogs:
                if not dialogs.confirm_raise(self._window, profile.name, deltas):
                    return
            go_back = running.profile if running.profile != profile.name else ""
        self._run(
            model.build_configure_args(profile, apply_now=True),
            f"Applied '{profile.name}'.",
            saved=profile,
            go_back=go_back,
        )

    def apply_saved(self, name: str) -> None:
        if not model.valid_profile_name(name):
            self.failed.emit(f"Refusing to act on an invalid profile name: {name!r}")
            return
        self._run(model.build_apply_args(name), f"Applied '{name}'.")

    def repair_balanced_plus(self) -> None:
        if self._busy:
            return
        dirty = self._editor.current_name if self._editor.dirty else ""
        if self._window.dialogs and not dialogs.confirm_repair(self._window.checks.dialog, dirty):
            return
        self._run(
            ["repair", "balanced-plus"],
            "Repaired and applied 'balanced-plus'. The previous settings were backed up.",
            on_success=self.repaired.emit,
        )

    def pin_boot(self, name: str) -> None:
        if not model.valid_profile_name(name):
            self.failed.emit(f"Refusing to act on an invalid profile name: {name!r}")
            return
        editing = self._editor.editing
        draft = name in self._sidebar.drafts
        open_here = editing is not None and editing.name == name
        if open_here and (self._editor.dirty or draft):
            profile = self._guard_editor()
            if profile is None:
                return
            self._run(
                model.build_configure_args(profile, select=True),
                f"Saved '{name}' and set it as the boot profile.",
                saved=profile,
            )
            return
        if draft:
            self.failed.emit(f"Open '{name}' before setting it as the boot profile.")
            return
        self._run(model.build_select_args(name), f"'{name}' will be applied at boot.")

    def ask_profile_name(self) -> str | None:
        return dialogs.ask_profile_name(self._window) if self._window.dialogs else None

    def new_profile(self) -> None:
        name = self.ask_profile_name()
        if name:
            self._sidebar.create_draft(name)

    def delete(self) -> None:
        name = self._saved_name()
        if name is None:
            return
        if name in self._sidebar.drafts:
            self._editor.clear()
            self._sidebar.discard_draft(name)
            return
        if self._window.dialogs:
            answer = QMessageBox.question(
                self._window,
                "Delete profile",
                f"Delete profile '{name}'? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._run(model.build_delete_args(name), f"Deleted profile '{name}'.")

    def set_service(self, enabled: bool) -> None:
        if not enabled:
            self._run(["disable"], "Boot service off. The limits stay until a power cycle.")
            return
        boot = self._window.status.active_profile if self._window.status else ""
        if self._window.dialogs and not dialogs.confirm_enable(self._window, boot):
            self._window.header.set_service_checked(False)
            return
        self._run(["enable"], SERVICE_ON, on_fail=self._offer_force)

    def _offer_force(self, stdout: str, stderr: str) -> bool:
        detail = stderr.strip() or stdout.strip()
        if "doctor reported failures" not in detail:
            return False
        if not self._window.dialogs or not dialogs.offer_force_enable(self._window, detail):
            self._window.header.set_service_checked(False)
            return True
        self._run(["enable", "--force"], SERVICE_ON)
        return True

    def _guard_editor(self) -> model.Profile | None:
        if self._editor.editing is None:
            self.failed.emit("Select a profile first.")
            return None
        problems = self._editor.problems()
        if problems:
            self.failed.emit("Fix these first:\n" + "\n".join(problems))
            return None
        return self._editor.collect()

    def _saved_name(self) -> str | None:
        if self._editor.editing is None:
            self.failed.emit("Select a profile first.")
            return None
        name = self._editor.editing.name
        if not model.valid_profile_name(name):
            self.failed.emit(f"Refusing to act on an invalid profile name: {name!r}")
            return None
        return name

    def _run(
        self,
        args: list[str],
        message: str,
        saved: model.Profile | None = None,
        on_fail=None,
        go_back: str = "",
        on_success=None,
    ) -> None:
        self.previous_profile = go_back
        self._set_busy(True)

        def done(code: int, stdout: str, stderr: str) -> None:
            self._set_busy(False)
            backup = ""
            if args == ["repair", "balanced-plus"]:
                backup = next((line for line in stdout.splitlines()
                               if line.startswith("Recovery backup: ")), "")
                if backup and code != 0:
                    stderr = f"{stderr.strip() or 'Repair failed.'}\n{backup}"
            if code == 0 and on_success is not None:
                on_success()
            self.handle_result(
                code, stdout, stderr, saved=saved, message=message, on_fail=on_fail
            )
            if backup:
                self.repair_backup.emit(backup)

        self._runner.run(model.privileged_command(args), done)

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def handle_result(
        self,
        code: int,
        stdout: str,
        stderr: str,
        saved: model.Profile | None = None,
        message: str = "Done.",
        on_fail=None,
    ) -> None:
        if code != 0:
            if self._is_cancelled_elevation(code):
                self.cancelled.emit(
                    stderr.strip() or "Authorisation was cancelled; nothing changed."
                )
                return
            if on_fail is not None and on_fail(stdout, stderr):
                return
            self.failed.emit(stderr.strip() or stdout.strip() or "Command failed.")
            return
        if saved is not None:
            self._editor.mark_saved(saved)
        if stderr.strip():
            self.warned.emit(message, stderr.strip())
            return
        self.succeeded.emit(message)

    @staticmethod
    def _is_cancelled_elevation(code: int) -> bool:
        return (
            code in (PKEXEC_DISMISSED, PKEXEC_NOT_RUN)
            and model.elevation_command() == "pkexec"
        )
