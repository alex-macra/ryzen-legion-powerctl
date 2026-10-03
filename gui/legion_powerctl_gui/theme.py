# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette, qGray

SEVERITIES = ("OK", "WARN", "FAIL", "NEUTRAL")

MIN_CONTRAST = 4.5
MIN_NON_TEXT_CONTRAST = 3.0

SEVERITY_HUE = {"OK": 122.0, "WARN": 38.0, "FAIL": 4.0}
SEVERITY_SATURATION = 0.70
SEED_LIGHTNESS = 0.45
SEED_LIGHTNESS_DARK = 0.62

EDGE_BLEND = 0.12
SECONDARY_BLEND = 0.24
MUTED_BLEND = 0.38
EDGE_STRONG_BLEND = 0.30
SELECTION_TINT = 0.12
SEVERITY_TINT = 0.10
FUSION_OUTLINE = 140
FUSION_SCROLL_ALPHA = 180 / 255

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


def _is_dark_background(background: QColor) -> bool:
    return relative_luminance(background) <= _NEUTRAL_LUMINANCE


def fit_contrast(color: QColor, background: QColor, target: float = MIN_CONTRAST) -> QColor:
    if contrast_ratio(color, background) >= target:
        return color
    hue, saturation, lightness, alpha = color.getHslF()
    if hue < 0:
        hue, saturation = 0.0, 0.0
    step = 0.02 if _is_dark_background(background) else -0.02
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
    seed_lightness = SEED_LIGHTNESS_DARK if _is_dark_background(background) else SEED_LIGHTNESS
    seed = QColor.fromHslF(hue / 360.0, SEVERITY_SATURATION, seed_lightness, 1.0)
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


def tint_color(background: QColor, color: QColor, amount: float = SEVERITY_TINT) -> QColor:
    return blend(background, color, amount)


def muted_color(palette: QPalette, background: QColor) -> QColor:
    stepped = blend(palette.color(QPalette.ColorRole.Text), background, MUTED_BLEND)
    return fit_contrast(stepped, background, MIN_CONTRAST)


def secondary_color(palette: QPalette, background: QColor) -> QColor:
    stepped = blend(palette.color(QPalette.ColorRole.Text), background, SECONDARY_BLEND)
    return fit_contrast(stepped, background, MIN_CONTRAST)


def disabled_text_color(palette: QPalette) -> QColor:
    return palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)


def edge_color(palette: QPalette) -> QColor:
    return blend(
        palette.color(QPalette.ColorRole.Window),
        palette.color(QPalette.ColorRole.WindowText),
        EDGE_BLEND,
    )


def edge_strong_color(palette: QPalette, background: QColor) -> QColor:
    stepped = blend(background, palette.color(QPalette.ColorRole.Text), EDGE_STRONG_BLEND)
    return fit_contrast(stepped, background, MIN_NON_TEXT_CONTRAST)


# Fusion draws input frames in Window.darker(140) and a scroll bar's edges at alpha 180
# over its groove; these invert that so what lands on screen is edge_strong_color.
def fusion_window(outline: QColor) -> QColor:
    return outline.lighter(FUSION_OUTLINE)


def fusion_groove_color(palette: QPalette, background: QColor) -> QColor:
    if max(background.red(), background.green(), background.blue()) < 128:
        return background.lighter(157)
    button = palette.color(QPalette.ColorRole.Button)
    tone = button.lighter(100 + max(1, (180 - qGray(button.rgb())) // 6))
    tone.setHsv(tone.hue(), int(tone.saturation() * 0.75), tone.value(), tone.alpha())
    return tone.darker(107)


def scroll_outline_color(palette: QPalette) -> QColor:
    groove = fusion_groove_color(palette, palette.color(QPalette.ColorRole.Base))
    shown = edge_strong_color(palette, groove)
    under = 1.0 - FUSION_SCROLL_ALPHA
    return QColor(*(
        max(0, min(255, round((wanted - under * behind) / FUSION_SCROLL_ALPHA)))
        for wanted, behind in zip(shown.getRgb()[:3], groove.getRgb()[:3])
    ))


def selection_color(palette: QPalette) -> QColor:
    return tint_color(
        palette.color(QPalette.ColorRole.Base), accent_color(palette), SELECTION_TINT
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


def is_dark(scheme: Qt.ColorScheme, palette: QPalette) -> bool:
    if scheme == Qt.ColorScheme.Unknown:
        return palette.color(QPalette.ColorRole.Window).lightness() < 128
    return scheme == Qt.ColorScheme.Dark


MIN_POINT_SIZE = 7.0
_W = QFont.Weight
FONT_ROLES = {
    "body": (1.0, _W.Normal, 100.0, False, False),
    "strong": (1.0, _W.DemiBold, 100.0, False, False),
    "title": (1.4, _W.DemiBold, 99.0, False, False),
    "readout": (1.7, _W.DemiBold, 98.0, False, False),
    "eyebrow": (0.75, _W.ExtraBold, 110.0, True, False),
    "caption": (0.9, _W.Normal, 100.0, False, False),
    "detail-mono": (0.9, _W.Normal, 100.0, False, True),
    "badge": (0.8, _W.Bold, 100.0, False, False),
    "pin": (0.75, _W.Bold, 106.0, True, False),
}


def font(role: str, base: QFont | None = None) -> QFont:
    scale, weight, spacing, uppercase, mono = FONT_ROLES[role]
    reference = QFont(base) if base is not None else QGuiApplication.font()
    size = reference.pointSizeF() if reference.pointSizeF() > 0 else 10.0
    if mono:
        result = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    else:
        result = QFont(reference)
    result.setPointSizeF(max(MIN_POINT_SIZE, size * scale) if scale < 1.0 else size * scale)
    result.setWeight(weight)
    if spacing != 100.0:
        result.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    if uppercase:
        result.setCapitalization(QFont.Capitalization.AllUppercase)
    return result


def repolish(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
