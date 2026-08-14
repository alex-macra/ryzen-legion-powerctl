# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import a11y, dialogs, model, runstate, theme


class MachineHeader(QFrame):
    service_toggled = Signal(bool)
    checks_requested = Signal()

    def __init__(self, gui_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._gui_version = gui_version
        self._updating = False
        self._mark_severity = "NEUTRAL"
        self._service_severity = "NEUTRAL"
        self._checks_severity = "NEUTRAL"
        self._checks_summary = ""
        self._service_available = False
        self._running_applied = False

        column = QVBoxLayout(self)

        eyebrow = QHBoxLayout()
        self.run_caption = QLabel("RUNNING NOW")
        self.when_label = QLabel("")
        eyebrow.addWidget(self.run_caption)
        eyebrow.addStretch(1)
        eyebrow.addWidget(self.when_label)
        column.addLayout(eyebrow)

        running = QHBoxLayout()
        self.rail = QFrame()
        self.rail.setFrameShape(QFrame.Shape.NoFrame)
        self.rail.setFixedWidth(3)
        self.rail.setMinimumHeight(20)
        self.running_label = QLabel("-")
        running_font = self.running_label.font()
        running_font.setBold(True)
        self.running_label.setFont(running_font)
        self.envelope_label = QLabel("")
        self.mark_label = QLabel("")
        running.addWidget(self.rail)
        running.addWidget(self.running_label)
        running.addWidget(self.envelope_label)
        running.addStretch(1)
        running.addWidget(self.mark_label)
        column.addLayout(running)

        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFrameShadow(QFrame.Shadow.Plain)
        self._rule = rule
        column.addWidget(rule)

        boot = QHBoxLayout()
        self.boot_caption = QLabel("AT BOOT")
        self.boot_label = QLabel("-")
        self.same_label = QLabel("")
        self.service_check = QCheckBox("&Re-apply at every boot")
        self.service_check.toggled.connect(self._on_service_toggled)
        self.service_label = QLabel("")
        self.checks_button = QPushButton("Checks")
        self.checks_button.clicked.connect(self.checks_requested)
        boot.addWidget(self.boot_caption)
        boot.addWidget(self.boot_label)
        boot.addWidget(self.same_label)
        boot.addStretch(1)
        boot.addWidget(self.service_check)
        boot.addWidget(self.service_label)
        boot.addWidget(self.checks_button)
        column.addLayout(boot)

        self.volatile_note = QLabel(
            "Limits are cleared by a power cycle and will not come back on their own."
        )
        self.volatile_note.setWordWrap(True)
        self.volatile_note.hide()
        column.addWidget(self.volatile_note)

        self.machine_label = QLabel(f"legion-powerctl GUI {gui_version}")
        self.restyle(self.palette())

    def show_status(self, status: model.Status) -> None:
        state = runstate.run_state(status)
        self.running_label.setText(state.headline())
        self.envelope_label.setText(state.summary())
        self.when_label.setText(state.when())
        mark, severity = state.mark()
        self.mark_label.setText(mark)
        self._mark_severity = severity
        self.running_label.setAccessibleName(self._running_name(state, mark))

        self.boot_label.setText(status.active_profile or "-")
        same = bool(status.active_profile) and status.active_profile == state.profile
        self.same_label.setText("(same)" if same else "")

        badge, service_severity = runstate.service_badge(
            status.service_enabled, status.service_active
        )
        enabled = status.service_enabled == "enabled"
        self._updating = True
        self.service_check.setChecked(enabled)
        self._updating = False
        self._service_available = status.service_enabled is not None
        self._running_applied = state.applied
        self.service_check.setEnabled(self._service_available)
        self.service_check.setToolTip(
            "" if status.service_enabled is not None else "No systemd on this system."
        )
        self.service_label.setText(
            f"{service_severity} {badge}" if service_severity in ("FAIL", "WARN") else ""
        )
        self.service_label.setProperty("severity", service_severity)
        self._service_severity = service_severity
        self.volatile_note.setVisible(status.service_enabled == "disabled")

        parts = [f"legion-powerctl {status.version}", f"GUI {self._gui_version}"]
        if not status.ryzenadj:
            parts.append("ryzenadj missing")
        self.machine_label.setText(" | ".join(parts))
        self.restyle(self.palette())

    def show_checks(self, report: model.DoctorReport | None, stderr: str = "") -> None:
        text, severity = dialogs.checks_chip(report)
        self.checks_button.setText(text)
        self._checks_severity = severity
        summary = dialogs.summarise(report, stderr) if report else "System checks: not run yet"
        self.checks_button.setAccessibleName(summary)
        if summary != self._checks_summary:
            self._checks_summary = summary
            a11y.announce(self.checks_button, summary)
        self.restyle(self.palette())

    def set_busy(self, busy: bool) -> None:
        self.service_check.setEnabled(self._service_available and not busy)
        self.checks_button.setEnabled(not busy)

    @staticmethod
    def _running_name(state: runstate.RunState, mark: str) -> str:
        if not state.applied:
            return "Running now: firmware defaults, nothing applied since this boot"
        detail = state.summary()
        tail = f", {mark}" if mark else ""
        return f"Running now: {state.headline()}{', ' + detail if detail else ''}{tail}"

    def _on_service_toggled(self, checked: bool) -> None:
        if not self._updating:
            self.service_toggled.emit(checked)

    def set_service_checked(self, checked: bool) -> None:
        self._updating = True
        self.service_check.setChecked(checked)
        self._updating = False

    def restyle(self, palette: QPalette) -> None:
        background = palette.color(QPalette.ColorRole.Window)
        muted = theme.muted_color(palette, background)
        for label in (self.run_caption, self.boot_caption):
            label.setStyleSheet(f"color: {muted.name()}; font-size: 9pt; letter-spacing: 1px;")
        for label in (self.envelope_label, self.when_label, self.same_label):
            label.setStyleSheet(f"color: {muted.name()};")
        self.volatile_note.setStyleSheet(f"color: {muted.name()};")
        self._rule.setStyleSheet(f"color: {theme.edge_color(palette).name()};")
        rail = theme.accent_color(palette) if self._running_applied else muted
        self.rail.setStyleSheet(f"background-color: {rail.name()};")
        self.mark_label.setStyleSheet(theme.text_style(palette, self._mark_severity))
        self.service_label.setStyleSheet(theme.chip_style(palette, self._service_severity))
        self.service_label.setVisible(bool(self.service_label.text()))
        self.checks_button.setStyleSheet(
            theme.chip_style(palette, self._checks_severity, "QPushButton")
        )
