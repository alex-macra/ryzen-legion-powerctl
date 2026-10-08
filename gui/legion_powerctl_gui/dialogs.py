# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import a11y, checks_view, model, styles, theme
from .checks_view import report_text, summarise, worst_first

COPIED_MS = 2000
DIALOG_SIZE = (640, 480)
HEADER_SPACING = 8
SCROLLBAR_ROOM = 8


class ChecksDialog(QDialog):
    rerun_requested = Signal()
    repair_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("System checks")
        self.resize(*DIALOG_SIZE)
        self.rows: list[checks_view.CheckRow] = []
        self.chips: list[QLabel] = []
        self._separators: list[QFrame] = []
        self._report: model.DoctorReport | None = None
        self._stderr = ""
        self._machine = ""

        layout = QVBoxLayout(self)
        gutter = styles.GUTTER
        layout.setContentsMargins(gutter, gutter, gutter, gutter)
        layout.setSpacing(styles.GAP)
        header = QHBoxLayout()
        header.setSpacing(HEADER_SPACING)
        self.summary = QLabel("Doctor: not run yet")
        self.summary.setFont(theme.font("strong"))
        header.addWidget(self.summary)
        header.addStretch(1)
        self.copy_button = QPushButton("&Copy report")
        # Otherwise the first autoDefault button created takes Enter from "Run again".
        self.copy_button.setAutoDefault(False)
        self.copy_button.setEnabled(False)
        self.copy_button.setMinimumWidth(self.copy_button.sizeHint().width())
        self.copy_button.clicked.connect(self._copy)
        header.addWidget(self.copy_button)
        self.rerun_button = QPushButton("Run &again")
        self.rerun_button.clicked.connect(self.rerun_requested)
        header.addWidget(self.rerun_button)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setAccessibleName("System checks")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._rows_layout = QVBoxLayout(self._host)
        self._rows_layout.setContentsMargins(0, 0, SCROLLBAR_ROOM, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch(1)
        self.scroll.setWidget(self._host)
        self.focus_ring = a11y.FocusRing(self.scroll)
        layout.addWidget(self.scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.repair_button = buttons.addButton(
            "&Repair balanced-plus", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.repair_button.setAutoDefault(False)
        self.repair_button.clicked.connect(self.repair_requested)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._copied_timer = QTimer(self)
        self._copied_timer.setSingleShot(True)
        self._copied_timer.setInterval(COPIED_MS)
        self._copied_timer.timeout.connect(self._reset_copy_label)

    def show_report(
        self, report: model.DoctorReport, stderr: str = "", machine: str = ""
    ) -> None:
        self._report = report
        self._stderr = stderr
        self._machine = machine
        self._reset_copy_label()
        self.copy_button.setEnabled(True)
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = []
        self.chips = []
        self._separators = []
        palette = self.palette()
        for line in worst_first(report.lines):
            if self.rows:
                self._separators.append(checks_view.separator(palette))
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, self._separators[-1])
            row = checks_view.CheckRow(line, palette)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
            self.rows.append(row)
            self.chips.append(row.chip)
        self.summary.setText(summarise(report, stderr))

    def _copy(self) -> None:
        if self._report is None:
            return
        QGuiApplication.clipboard().setText(
            report_text(self._report, self._stderr, self._machine)
        )
        self.copy_button.setText("&Copied")
        self._copied_timer.start()
        a11y.announce(self.copy_button, "Report copied to the clipboard.")

    def _reset_copy_label(self) -> None:
        self._copied_timer.stop()
        self.copy_button.setText("&Copy report")

    def restyle(self, palette: QPalette) -> None:
        for row in self.rows:
            row.restyle(palette)
        for line in self._separators:
            checks_view.restyle_separator(line, palette)


class ChecksController(QObject):
    def __init__(self, window, runner, header, timeout_ms: int) -> None:
        super().__init__(window)
        self._window = window
        self._runner = runner
        self._header = header
        self._timeout_ms = timeout_ms
        self.count = 0
        self.report: model.DoctorReport | None = None
        self.stderr = ""
        self.dialog = ChecksDialog(window)
        self.dialog.rerun_requested.connect(self.run)

    def run(self) -> None:
        self._runner.run(
            model.unprivileged_command(["doctor"]), self._done, timeout_ms=self._timeout_ms
        )

    def show(self) -> None:
        if self.report is not None:
            self.dialog.show_report(self.report, self.stderr, self._machine())
        if self._window.dialogs:
            self.dialog.show()

    def _machine(self) -> str:
        return self._header.machine_label.text()

    def restyle(self, palette: QPalette) -> None:
        self.dialog.restyle(palette)

    def _done(self, code: int, stdout: str, stderr: str) -> None:
        self.count += 1
        self.report = model.parse_doctor(stdout, code)
        self.stderr = stderr
        self._header.show_checks(self.report, stderr)
        if self.dialog.isVisible():
            self.dialog.show_report(self.report, stderr, self._machine())


def _primary(button: QPushButton) -> QPushButton:
    button.setProperty("kind", "primary")
    theme.repolish(button)
    return button


def ask_profile_name(parent: QWidget) -> str | None:
    name, ok = QInputDialog.getText(parent, "New profile", "Profile name:")
    if not ok or not name:
        return None
    return name.strip()


def confirm_raise(parent: QWidget, name: str, deltas: list) -> bool:
    rows = "\n".join(
        f"    {delta.label:<12} {delta.was} {delta.unit}  ->  {delta.now} {delta.unit}"
        for delta in deltas
    )
    box = QMessageBox(parent)
    box.setWindowTitle("Raise the limits?")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(f"'{name}' raises what the machine is allowed to draw:")
    box.setInformativeText(
        f"{rows}\n\nHigher limits raise heat, noise and power draw.\n"
        "Limits are volatile: a power cycle clears them, and nothing here puts them back."
    )
    apply_button = _primary(box.addButton("Apply anyway", QMessageBox.ButtonRole.AcceptRole))
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is apply_button


def confirm_enable(parent: QWidget, boot_profile: str) -> bool:
    name = boot_profile or "the boot profile"
    box = QMessageBox(parent)
    box.setWindowTitle("Apply at every boot?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(f"Apply '{name}' at every boot?")
    box.setInformativeText("This also applies it right now.")
    accept = _primary(box.addButton("Enable", QMessageBox.ButtonRole.AcceptRole))
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(accept)
    box.exec()
    return box.clickedButton() is accept


def confirm_repair(parent: QWidget, dirty_profile: str = "") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("Repair balanced-plus")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText("Reset and apply balanced-plus at 87/92/102 W and 80 C?")
    detail = (
        "Restore balanced mode, stock CPU frequency limits, boost on and "
        "balance_performance EPP. Save a backup of the existing profile and module settings.\n\n"
        "If ryzen_smu is incomplete and blocks RyzenAdj, unload it before applying. "
        "Disable its automatic loading only after a successful apply. A working driver is kept."
    )
    if dirty_profile:
        detail += f"\n\nDiscard unsaved changes to '{dirty_profile}' after repair succeeds."
    box.setInformativeText(detail)
    accept = _primary(box.addButton("Repair and apply", QMessageBox.ButtonRole.AcceptRole))
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is accept


def confirm_discard(parent: QWidget, name: str, target: str) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setWindowTitle("Discard unsaved changes?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(f"'{name}' has unsaved changes. Discard them and open '{target}'?")
    _primary(box.addButton(QMessageBox.StandardButton.Discard))
    box.addButton(QMessageBox.StandardButton.Save)
    box.setDefaultButton(box.addButton(QMessageBox.StandardButton.Cancel))
    box.exec()
    return box.standardButton(box.clickedButton())


def confirm_delete(parent: QWidget, name: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("Delete profile")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(f"Delete profile '{name}'? This cannot be undone.")
    delete = _primary(box.addButton(QMessageBox.StandardButton.Yes))
    box.setDefaultButton(box.addButton(QMessageBox.StandardButton.Cancel))
    box.exec()
    return box.clickedButton() is delete


def offer_force_enable(parent: QWidget, detail: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("Checks failed")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText("The boot service was not enabled because a system check failed.")
    box.setInformativeText(f"{detail}\n\nEnable it anyway, or close and fix the check first.")
    force = _primary(box.addButton("Enable anyway", QMessageBox.ButtonRole.DestructiveRole))
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is force
