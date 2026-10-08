# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from . import model, styles, theme
from .strip_widgets import BadgeHeight

_SEVERITY_ORDER = {"FAIL": 0, "WARN": 1, "OK": 2}
ROW_NAME = "checkRow"
ROW_MARGINS = (8, 6, 8, 6)
ROW_SPACING = 12
SEPARATOR_INSET = 8
DETAIL_NUDGE = 2


def worst_first(lines: list[model.DoctorLine]) -> list[model.DoctorLine]:
    return sorted(lines, key=lambda line: _SEVERITY_ORDER.get(line.status, 3))


def summarise(report: model.DoctorReport, stderr: str = "") -> str:
    if not report.lines:
        return (
            "Doctor: could not run"
            if report.exit_code != 0 or stderr.strip()
            else "Doctor: produced no results"
        )
    return f"Doctor: {report.failures} failure(s), {report.warnings} warning(s)"


def report_text(report: model.DoctorReport, stderr: str = "", machine: str = "") -> str:
    head = ["legion-powerctl doctor report"]
    if machine:
        head.append(machine)
    verdict = summarise(report, stderr)
    if report.exit_code != 0:
        verdict = f"{verdict} (exit {report.exit_code})"
    head.append(verdict)

    parts = ["\n".join(head)]
    body = report.text.strip("\n")
    if body:
        parts.append(body)
    if stderr.strip():
        parts.append(f"Errors reported by the command:\n{stderr.strip()}")
    return "\n\n".join(parts) + "\n"


def checks_chip(report: model.DoctorReport | None) -> tuple[str, str]:
    if report is None:
        return ("Checks", "NEUTRAL")
    if report.failures:
        return (f"Checks {report.failures}", "FAIL")
    if report.warnings:
        return (f"Checks {report.warnings}", "WARN")
    return ("Checks", "OK")


class CheckRow(QFrame):
    def __init__(self, line: model.DoctorLine, palette: QPalette, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(ROW_NAME)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(*ROW_MARGINS)
        layout.setSpacing(ROW_SPACING)

        self.chip = QLabel(f"{line.status} {line.label}")
        self.chip.setProperty("severity", line.status)
        self.chip.setFont(theme.font("caption"))
        BadgeHeight(self.chip)
        self.chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail = QLabel(line.detail)
        self.detail.setWordWrap(True)
        self.detail.setContentsMargins(0, DETAIL_NUDGE, 0, 0)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.detail, 1)

        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(f"{line.status}: {line.label}. {line.detail}")
        self.restyle(palette)

    def restyle(self, palette: QPalette) -> None:
        plane = palette.color(QPalette.ColorRole.Window)
        self.setStyleSheet(styles.focus_ring_style(palette, f"QFrame#{ROW_NAME}"))
        self.chip.setStyleSheet(
            styles.badge_style(palette, self.chip.property("severity"), background=plane)
        )
        self.detail.setStyleSheet(f"color: {theme.secondary_color(palette, plane).name()};")


def separator(palette: QPalette) -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    restyle_separator(line, palette)
    return line


def restyle_separator(line: QFrame, palette: QPalette) -> None:
    line.setStyleSheet(
        f"QFrame {{ background-color: {theme.edge_color(palette).name()};"
        f" margin: 0px {SEPARATOR_INSET}px; }}"
    )
