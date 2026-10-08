# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget

from . import theme

GUTTER = 16
GAP = 12
CARD_RADIUS = 12
CONTROL_RADIUS = 8
BADGE_HEIGHT = 22
BADGE_CHROME = 6
FOOTER_HEIGHT = 44
STATUS_BAR_HEIGHT = 26
CARD_MARGINS = (16, 14, 16, 14)
CELL_MARGINS = (16, 10, 16, 10)
EYEBROW_GAP = 6
STRIP_HEIGHT = 80

CARD_SELECTOR = 'QFrame[card="true"], QWidget[card="true"], QGroupBox[card="true"]'

HOVER_TINT = 0.18
PRESSED_TINT = 0.26
CALLOUT_TINT = 0.08
CALLOUT_EDGE_TINT = 0.35


class SwitchColors(NamedTuple):
    track_off: QColor
    track_off_border: QColor
    track_on: QColor
    knob_off: QColor
    knob_on: QColor
    track_disabled: QColor
    knob_disabled: QColor
    label: QColor
    label_disabled: QColor
    focus: QColor


class ReadoutColors(NamedTuple):
    value: QColor
    unit: QColor
    caption: QColor


def set_sheet(widget: QWidget, sheet: str) -> None:
    if widget.styleSheet() != sheet:
        widget.setStyleSheet(sheet)


def _base(palette: QPalette) -> QColor:
    return palette.color(QPalette.ColorRole.Base)


def _severity_stroke(palette: QPalette, severity: str, surface: QColor) -> QColor:
    if severity in theme.SEVERITY_HUE:
        return theme.severity_color(palette, severity)
    return theme.secondary_color(palette, surface)


def swatch_style(palette: QPalette, background: QColor, step: float) -> str:
    return (
        f"background-color: {theme.tier_color(palette, background, step).name()};"
        f" border: 1px solid {theme.track_color(palette, background).name()};"
        f" border-radius: 3px;"
    )


def caption_style(palette: QPalette) -> str:
    return f"color: {theme.muted_color(palette, _base(palette)).name()};"


def text_style(palette: QPalette, severity: str) -> str:
    return f"color: {theme.severity_color(palette, severity).name()};"


def surface_style(palette: QPalette, selector: str = CARD_SELECTOR) -> str:
    return (
        f"{selector} {{ background-color: {_base(palette).name()};"
        f" border: 1px solid {theme.edge_color(palette).name()};"
        f" border-radius: {CARD_RADIUS}px; }}"
    )


def card_style(palette: QPalette) -> str:
    return (
        f"{surface_style(palette, f'QGroupBox, {CARD_SELECTOR}')}"
        f" QGroupBox {{ margin-top: 0px; padding: 0px; }}"
    )


def cell_style(palette: QPalette) -> str:
    return f"color: {theme.edge_color(palette).name()};"


def footer_style(palette: QPalette, selector: str = "QFrame#editorFooter") -> str:
    return (
        f"{selector} {{ background-color: transparent; border: 0px;"
        f" border-top: 1px solid {theme.edge_color(palette).name()}; }}"
    )


def splitter_style() -> str:
    return "QSplitter::handle { background-color: transparent; }"


def status_bar_style(palette: QPalette) -> str:
    window = palette.color(QPalette.ColorRole.Window)
    return (
        f"QStatusBar {{ background-color: {window.name()};"
        f" border-top: 1px solid {theme.edge_color(palette).name()};"
        f" color: {theme.secondary_color(palette, window).name()}; }}"
        f" QStatusBar::item {{ border: 0px; }}"
    )


def primary_button_style(palette: QPalette, selector: str = "QPushButton") -> str:
    accent = theme.accent_color(palette)
    on_accent = theme.on_accent_color(palette)
    hover = theme.blend(accent, on_accent, 0.12).name()
    pressed = theme.blend(accent, on_accent, 0.24).name()
    return (
        f"{selector} {{ background-color: {accent.name()}; color: {on_accent.name()};"
        f" border: 1px solid {accent.name()}; border-radius: {CONTROL_RADIUS}px;"
        f" padding: 6px 16px; min-height: 18px; font-weight: 600; outline: none; }}"
        f" {selector}:hover {{ background-color: {hover}; border-color: {hover}; }}"
        f" {selector}:pressed {{ background-color: {pressed}; border-color: {pressed}; }}"
        f" {selector}:focus {{ border: 2px solid {on_accent.name()}; padding: 5px 15px; }}"
        f" {selector}:disabled {{"
        f" background-color: {palette.color(QPalette.ColorRole.AlternateBase).name()};"
        f" color: {theme.disabled_text_color(palette).name()};"
        f" border: 1px solid {theme.edge_color(palette).name()}; }}"
    )


def secondary_button_style(palette: QPalette, selector: str = "QPushButton") -> str:
    base = _base(palette)
    sunken = palette.color(QPalette.ColorRole.AlternateBase)
    text = theme.fit_contrast(palette.color(QPalette.ColorRole.Text), base)
    pressed = theme.blend(sunken, text, 0.08)
    return (
        f"{selector} {{ background-color: {base.name()}; color: {text.name()};"
        f" border: 1px solid {theme.edge_strong_color(palette, base).name()};"
        f" border-radius: {CONTROL_RADIUS}px; padding: 6px 14px; min-height: 18px;"
        f" outline: none; }}"
        f" {selector}:hover {{ background-color: {sunken.name()}; }}"
        f" {selector}:pressed {{ background-color: {pressed.name()}; }}"
        f" {selector}:focus {{ border: 2px solid {theme.focus_color(palette).name()};"
        f" padding: 5px 13px; }}"
        f" {selector}:disabled {{ color: {theme.disabled_text_color(palette).name()};"
        f" border-color: {theme.edge_color(palette).name()}; }}"
    )


def ghost_button_style(
    palette: QPalette, selector: str = "QPushButton", background: QColor | None = None
) -> str:
    surface = background if background is not None else palette.color(QPalette.ColorRole.Window)
    link = theme.fit_contrast(theme.accent_color(palette), surface, theme.MIN_CONTRAST)
    return (
        f"{selector} {{ background-color: transparent; color: {link.name()};"
        f" border: 2px solid transparent; border-radius: 6px; padding: 0px 4px;"
        f" min-height: 0px; outline: none; }}"
        f" {selector}:hover {{ text-decoration: underline; }}"
        f" {selector}:pressed {{ text-decoration: underline; }}"
        f" {selector}:focus {{ border-color: {theme.focus_color(palette).name()}; }}"
        f" {selector}:disabled {{ color: {theme.disabled_text_color(palette).name()}; }}"
    )


def badge_style(
    palette: QPalette, severity: str, selector: str = "QLabel", background: QColor | None = None
) -> str:
    surface = background if background is not None else _base(palette)
    stroke = _severity_stroke(palette, severity, surface)
    border = stroke if severity in theme.SEVERITY_HUE else theme.edge_color(palette)
    fill = theme.tint_color(surface, stroke)
    hover = theme.tint_color(surface, stroke, HOVER_TINT)
    text = theme.fit_contrast(theme.fit_contrast(stroke, hover), fill)
    return (
        f"{selector} {{ background-color: {fill.name()}; border: 1px solid {border.name()};"
        f" border-radius: {BADGE_HEIGHT // 2}px; padding: 2px 10px;"
        f" min-height: {BADGE_HEIGHT - BADGE_CHROME}px;"
        f" color: {text.name()}; font-weight: 700; outline: none; }}"
        f" {selector}:hover {{ background-color: {hover.name()}; }}"
        f" {selector}:pressed {{"
        f" background-color: {theme.tint_color(surface, stroke, PRESSED_TINT).name()}; }}"
        f" {selector}:focus {{ border: 2px solid {theme.focus_color(palette).name()};"
        f" padding: 1px 9px; }}"
        f" {selector}:disabled {{ color: {theme.disabled_text_color(palette).name()};"
        f" border-color: {theme.edge_color(palette).name()}; background-color: transparent; }}"
    )


def chip_style(palette: QPalette, severity: str, selector: str = "QLabel") -> str:
    return badge_style(palette, severity, selector)


def focus_ring_style(palette: QPalette, selector: str = "QFrame") -> str:
    return (
        f"{selector} {{ border: 2px solid transparent; border-radius: {CONTROL_RADIUS}px; }}"
        f" {selector}:focus {{ border: 2px solid {theme.focus_color(palette).name()}; }}"
    )


def callout_style(
    palette: QPalette, severity: str = "WARN", selector: str = "QLabel", text: QColor | None = None
) -> str:
    surface = _base(palette)
    stroke = _severity_stroke(palette, severity, surface)
    fill = theme.tint_color(surface, stroke, CALLOUT_TINT)
    ink = theme.secondary_color(palette, fill) if text is None else theme.fit_contrast(text, fill)
    return (
        f"{selector} {{ color: {ink.name()}; background-color: {fill.name()};"
        f" border: 1px solid {theme.tint_color(surface, stroke, CALLOUT_EDGE_TINT).name()};"
        f" border-left: 3px solid {stroke.name()}; border-radius: {CONTROL_RADIUS}px;"
        f" padding: 8px 12px; }}"
    )


def problem_style(palette: QPalette, selector: str = "QLabel") -> str:
    return callout_style(palette, "FAIL", selector, theme.severity_color(palette, "FAIL"))


def switch_colors(palette: QPalette) -> SwitchColors:
    base = _base(palette)
    sunken = palette.color(QPalette.ColorRole.AlternateBase)
    disabled = theme.disabled_text_color(palette)
    return SwitchColors(
        track_off=sunken,
        track_off_border=theme.edge_strong_color(palette, base),
        track_on=theme.accent_color(palette),
        knob_off=base,
        knob_on=theme.on_accent_color(palette),
        track_disabled=sunken,
        knob_disabled=disabled,
        label=theme.fit_contrast(palette.color(QPalette.ColorRole.Text), base),
        label_disabled=disabled,
        focus=theme.focus_color(palette),
    )


def readout_colors(palette: QPalette, severity: str) -> ReadoutColors:
    base = _base(palette)
    value = palette.color(QPalette.ColorRole.Text)
    if severity == "FAIL":
        value = theme.severity_color(palette, "FAIL")
    muted = theme.muted_color(palette, base)
    return ReadoutColors(theme.fit_contrast(value, base), muted, muted)


def app_qss(palette: QPalette) -> str:
    return " ".join((
        secondary_button_style(palette, "QPushButton"),
        primary_button_style(palette, 'QPushButton[kind="primary"]'),
        ghost_button_style(palette, 'QPushButton[kind="ghost"]'),
        ghost_button_style(palette, "QPushButton:flat"),
    ))
