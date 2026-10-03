# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import a11y, checks_view, model, runstate, styles, theme
from .strip_widgets import DOT, DOT_GAP, Badge, BadgeHeight, Switch, dot_icon

STRIP_HEIGHT = 72
BOOT_CELL_WIDTH = 176
WRAP_WIDTH = 860 - 2 * styles.GUTTER
LINE_GAP = 6
ITEM_GAP = 10
ACTIONS_GAP = 12
ACTIONS_MARGINS = (styles.CELL_MARGINS[0] - Switch.RING, *styles.CELL_MARGINS[1:])
WRAPPED_ACTIONS_MARGINS = (ACTIONS_MARGINS[0], 4, ACTIONS_MARGINS[2], 4)
RAIL_SIZE = (3, 18)


def _set_sheet(widget: QWidget, sheet: str) -> None:
    if widget.styleSheet() != sheet:
        widget.setStyleSheet(sheet)


class MachineHeader(QFrame):
    service_toggled = Signal(bool)
    checks_requested = Signal()

    def __init__(self, gui_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusStrip")
        self._gui_version = gui_version
        self._updating = False
        self._mark_severity = "NEUTRAL"
        self._service_severity = "NEUTRAL"
        self._checks_severity = "NEUTRAL"
        self._checks_dot = ""
        self._checks_summary = ""
        self._service_available = False
        self._running_applied = False
        self._wrapped = False

        self.run_caption = self._label("RUNNING NOW", "eyebrow")
        self.when_label = self._label("", "caption")
        self.rail = QFrame()
        self.rail.setFixedSize(*RAIL_SIZE)
        self.running_label = self._label("-", "headline")
        self.envelope_label = self._label("", "detail-mono")
        self.mark_label = Badge()
        self._running = self._cell(
            (self.run_caption, None, self.when_label),
            (self.rail, self.running_label, self.envelope_label, None, self.mark_label),
        )

        self.boot_caption = self._label("AT BOOT", "eyebrow")
        self.boot_label = self._label("-", "strong")
        self.same_label = self._label("", "caption")
        self._boot = self._cell((self.boot_caption,), (self.boot_label, self.same_label, None))
        self._boot.setMinimumWidth(BOOT_CELL_WIDTH)
        self._boot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        for cell in (self._running, self._boot):
            cell.setMinimumHeight(STRIP_HEIGHT - 2)

        self.service_check = Switch("&Re-apply at every boot")
        self.service_check.toggled.connect(self._on_service_toggled)
        self.service_label = QLabel("")
        self.checks_button = QPushButton("Checks")
        self.checks_button.clicked.connect(self.checks_requested)
        for chip in (self.service_label, self.checks_button):
            chip.setFont(theme.font("badge"))
            BadgeHeight(chip)
        self.checks_button.setIconSize(QSize(DOT + DOT_GAP, DOT))
        self._actions = self._cell(
            (self.service_check, self.service_label, self.checks_button), spacing=ACTIONS_GAP
        )
        self._actions.layout().setContentsMargins(*ACTIONS_MARGINS)

        self.volatile_note = QLabel(
            "Limits are cleared by a power cycle and will not come back on their own."
        )
        self.volatile_note.setFont(theme.font("caption"))
        self.volatile_note.setWordWrap(True)
        self.volatile_note.hide()

        self._dividers = [self._divider(QFrame.Shape.VLine) for _ in range(2)]
        self._wrap_rule = self._divider(QFrame.Shape.HLine)
        self._wrap_rule.hide()
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(1, 1, 1, 1)
        self._grid.setSpacing(0)
        for column, widget in enumerate(
            (self._running, self._dividers[0], self._boot, self._dividers[1], self._actions)
        ):
            self._grid.addWidget(widget, 0, column)
        self._grid.addWidget(self._wrap_rule, 1, 0, 1, 5)
        self._grid.addWidget(self.volatile_note, 3, 0, 1, 5)
        self._grid.setColumnStretch(0, 1)

        self.machine_label = QLabel(f"legion-powerctl GUI {gui_version}")
        self.machine_label.setFont(theme.font("detail-mono"))
        self.restyle(self.palette())

    @staticmethod
    def _label(text: str, role: str) -> QLabel:
        label = QLabel(text)
        label.setFont(theme.font(role))
        return label

    @staticmethod
    def _cell(*lines, spacing: int = ITEM_GAP) -> QFrame:
        cell = QFrame()
        column = QVBoxLayout(cell)
        column.setContentsMargins(*styles.CELL_MARGINS)
        column.setSpacing(LINE_GAP)
        column.addStretch(1)
        for line in lines:
            row = QHBoxLayout()
            row.setSpacing(spacing)
            for widget in line:
                if widget is None:
                    row.addStretch(1)
                else:
                    row.addWidget(widget)
            column.addLayout(row)
        column.addStretch(1)
        return cell

    @staticmethod
    def _divider(shape: QFrame.Shape) -> QFrame:
        line = QFrame()
        line.setFrameShape(shape)
        line.setFrameShadow(QFrame.Shadow.Plain)
        return line

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
        self._show_state(self.palette())

    def show_checks(self, report: model.DoctorReport | None, stderr: str = "") -> None:
        text, severity = checks_view.checks_chip(report)
        self.checks_button.setText(text)
        self._checks_severity = severity
        summary = (
            checks_view.summarise(report, stderr) if report else "System checks: not run yet"
        )
        self.checks_button.setAccessibleName(summary)
        if summary != self._checks_summary:
            self._checks_summary = summary
            a11y.announce(self.checks_button, summary)
        self._show_state(self.palette())

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
        muted = styles.caption_style(palette)
        for label in (
            self.run_caption, self.boot_caption, self.when_label, self.envelope_label,
            self.same_label,
        ):
            label.setStyleSheet(muted)
        for line in (*self._dividers, self._wrap_rule):
            line.setStyleSheet(styles.cell_style(palette))
        self.volatile_note.setStyleSheet(
            styles.callout_style(palette)
            + f" QLabel {{ margin: 0px {styles.GUTTER}px {styles.GAP}px {styles.GUTTER}px; }}"
        )
        plane = palette.color(QPalette.ColorRole.Window)
        self.machine_label.setStyleSheet(
            f"color: {theme.muted_color(palette, plane).name()};"
        )
        self.service_check.update()
        self._checks_dot = ""
        self._show_state(palette)

    def _show_state(self, palette: QPalette) -> None:
        muted = theme.muted_color(palette, palette.color(QPalette.ColorRole.Base))
        rail = theme.accent_color(palette) if self._running_applied else muted
        _set_sheet(self.rail, f"background-color: {rail.name()}; border-radius: 1px;")
        _set_sheet(
            self.mark_label,
            styles.badge_style(palette, self._mark_severity)
            + f" QLabel {{ padding-left: {Badge.PADDING}px; }}",
        )
        self.mark_label.dot = theme.severity_color(palette, self._mark_severity)
        self.mark_label.setVisible(bool(self.mark_label.text()))
        _set_sheet(self.service_label, styles.chip_style(palette, self._service_severity))
        self.service_label.setVisible(bool(self.service_label.text()))
        _set_sheet(
            self.checks_button,
            styles.chip_style(palette, self._checks_severity, "QPushButton"),
        )
        dot = theme.severity_color(palette, self._checks_severity)
        if self._checks_severity == "NEUTRAL":
            dot = theme.secondary_color(palette, palette.color(QPalette.ColorRole.Base))
        if dot.name() != self._checks_dot:
            self._checks_dot = dot.name()
            self.checks_button.setIcon(dot_icon(dot, self.devicePixelRatioF()))
        self._reflow()

    def _one_row_width(self) -> int:
        cells = (self._running, self._boot)
        width = sum(cell.minimumSizeHint().expandedTo(cell.minimumSize()).width() for cell in cells)
        return width + self._actions.sizeHint().width() + len(self._dividers) + 2

    def _reflow(self) -> None:
        wrapped = self.width() < max(WRAP_WIDTH, self._one_row_width())
        if wrapped == self._wrapped:
            return
        self._wrapped = wrapped
        self._grid.removeWidget(self._actions)
        margins = WRAPPED_ACTIONS_MARGINS if wrapped else ACTIONS_MARGINS
        self._actions.layout().setContentsMargins(*margins)
        if wrapped:
            self._grid.addWidget(self._actions, 2, 0, 1, 5, Qt.AlignmentFlag.AlignRight)
        else:
            self._grid.addWidget(self._actions, 0, 4)
        self._dividers[1].setVisible(not wrapped)
        self._wrap_rule.setVisible(wrapped)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(theme.edge_color(self.palette()), 1))
        painter.setBrush(self.palette().color(QPalette.ColorRole.Base))
        radius = styles.CARD_RADIUS - 0.5
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
