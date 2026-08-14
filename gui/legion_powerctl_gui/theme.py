# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

SEVERITIES = ("OK", "WARN", "FAIL", "NEUTRAL")

MIN_CONTRAST = 4.5
MIN_NON_TEXT_CONTRAST = 3.0

SEVERITY_HUE = {"OK": 145.0, "WARN": 35.0, "FAIL": 2.0}
SEVERITY_SATURATION = 0.70
SEED_LIGHTNESS = 0.45

_NEUTRAL_LUMINANCE = 0.1791


def _linearize(channel: float) -> float:
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: QColor) -> float:
    return (
        0.2126 * _linearize(color.redF())
        + 0.7152 * _linearize(color.greenF())
        + 0.0722 * _linearize(color.blueF())
    )


def contrast_ratio(one: QColor, other: QColor) -> float:
    first = relative_luminance(one)
    second = relative_luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def fit_contrast(color: QColor, background: QColor, target: float = MIN_CONTRAST) -> QColor:
    if contrast_ratio(color, background) >= target:
        return color
    hue, saturation, lightness, alpha = color.getHslF()
    if hue < 0:
        hue, saturation = 0.0, 0.0
    step = -0.02 if relative_luminance(background) > _NEUTRAL_LUMINANCE else 0.02
    candidate = color
    for _ in range(51):
        lightness = min(1.0, max(0.0, lightness + step))
        candidate = _quantize(QColor.fromHslF(hue, saturation, lightness, alpha))
        if contrast_ratio(candidate, background) >= target:
            break
        if lightness in (0.0, 1.0):
            break
    return candidate


def _quantize(color: QColor) -> QColor:
    return QColor(color.red(), color.green(), color.blue(), color.alpha())


def severity_color(palette: QPalette, severity: str) -> QColor:
    background = palette.color(QPalette.ColorRole.Window)
    hue = SEVERITY_HUE.get(severity)
    if hue is None:
        return fit_contrast(palette.color(QPalette.ColorRole.WindowText), background)
    seed = QColor.fromHslF(hue / 360.0, SEVERITY_SATURATION, SEED_LIGHTNESS, 1.0)
    return fit_contrast(seed, background)


def accent_color(palette: QPalette) -> QColor:
    return fit_contrast(
        palette.color(QPalette.ColorRole.Highlight),
        palette.color(QPalette.ColorRole.Window),
        MIN_NON_TEXT_CONTRAST,
    )


def focus_color(palette: QPalette) -> QColor:
    return accent_color(palette)


def on_accent_color(palette: QPalette) -> QColor:
    accent = accent_color(palette)
    return fit_contrast(palette.color(QPalette.ColorRole.HighlightedText), accent, MIN_CONTRAST)


def blend(color: QColor, other: QColor, amount: float) -> QColor:
    keep = 1.0 - amount
    return QColor(
        round(color.red() * keep + other.red() * amount),
        round(color.green() * keep + other.green() * amount),
        round(color.blue() * keep + other.blue() * amount),
    )


def muted_color(palette: QPalette, background: QColor) -> QColor:
    stepped = blend(palette.color(QPalette.ColorRole.Text), background, 0.38)
    return fit_contrast(stepped, background, MIN_CONTRAST)


def edge_color(palette: QPalette) -> QColor:
    return blend(
        palette.color(QPalette.ColorRole.Window),
        palette.color(QPalette.ColorRole.WindowText),
        0.22,
    )


def track_color(palette: QPalette, background: QColor) -> QColor:
    return blend(background, palette.color(QPalette.ColorRole.Text), 0.18)


TIER_STEPS = (1.0, 0.62, 0.34)


def tier_step(index: int) -> float:
    return TIER_STEPS[min(index, len(TIER_STEPS) - 1)]


def tier_color(palette: QPalette, background: QColor, step: float) -> QColor:
    return blend(track_color(palette, background), accent_color(palette), step)


def marker_color(palette: QPalette, background: QColor) -> QColor:
    return fit_contrast(
        palette.color(QPalette.ColorRole.Text), background, MIN_NON_TEXT_CONTRAST
    )


def wash_color(palette: QPalette, background: QColor) -> QColor:
    return blend(background, accent_color(palette), 0.16)


def swatch_style(palette: QPalette, background: QColor, step: float) -> str:
    return (
        f"background-color: {tier_color(palette, background, step).name()};"
        f" border: 1px solid {track_color(palette, background).name()};"
        f" border-radius: 2px;"
    )


def caption_style(palette: QPalette) -> str:
    return f"color: {muted_color(palette, palette.color(QPalette.ColorRole.Base)).name()};"


def card_style(palette: QPalette) -> str:
    return (
        f"QGroupBox {{ background-color: {palette.color(QPalette.ColorRole.Base).name()};"
        f" border: 1px solid {edge_color(palette).name()}; border-radius: 6px;"
        f" margin-top: 10px; padding: 12px 12px 8px 12px; }}"
        f" QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;"
        f" left: 10px; padding: 0 4px; }}"
    )


def primary_button_style(palette: QPalette) -> str:
    accent = accent_color(palette)
    on_accent = on_accent_color(palette)
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    return (
        f"QPushButton {{ background-color: {accent.name()}; color: {on_accent.name()};"
        f" border: 1px solid {accent.name()}; border-radius: 3px; padding: 5px 14px; }}"
        f" QPushButton:hover {{ background-color: {blend(accent, on_accent, 0.12).name()}; }}"
        f" QPushButton:pressed {{ background-color: {blend(accent, on_accent, 0.24).name()}; }}"
        f" QPushButton:focus {{ border: 2px solid {on_accent.name()}; padding: 4px 13px; }}"
        f" QPushButton:disabled {{ background-color: {palette.color(QPalette.ColorRole.Button).name()};"
        f" color: {disabled.name()}; border: 1px solid {edge_color(palette).name()}; }}"
    )


def focus_ring_style(palette: QPalette, selector: str = "QFrame") -> str:
    return (
        f"{selector} {{ border: 2px solid transparent; border-radius: 4px; }}"
        f" {selector}:focus {{ border: 2px solid {focus_color(palette).name()}; }}"
    )


def text_style(palette: QPalette, severity: str) -> str:
    return f"color: {severity_color(palette, severity).name()};"


def chip_style(palette: QPalette, severity: str, selector: str = "QLabel") -> str:
    color = severity_color(palette, severity).name()
    hover = blend(
        palette.color(QPalette.ColorRole.Window), severity_color(palette, severity), 0.12
    )
    return (
        f"{selector} {{ background-color: transparent;"
        f" border: 1px solid {color}; border-radius: 9px;"
        f" padding: 2px 8px; color: {color}; }}"
        f" {selector}:hover {{ background-color: {hover.name()}; }}"
        f" {selector}:focus {{ border: 2px solid {focus_color(palette).name()};"
        f" padding: 1px 7px; }}"
    )
