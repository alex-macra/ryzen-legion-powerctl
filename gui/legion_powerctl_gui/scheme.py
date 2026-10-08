# SPDX-License-Identifier: MIT

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import styles, theme

ENVIRONMENT = "LEGION_POWERCTL_GUI_SCHEME"
DESKTOP = "desktop"
LEGION = "legion"
STYLE = "Fusion"
FRAMED = ("QAbstractSpinBox", "QComboBox", "QLineEdit")

_R = QPalette.ColorRole
_TEXT_ROLES = (_R.Text, _R.WindowText, _R.ButtonText)
_ACCENT_ROLES = (_R.Highlight, _R.Accent, _R.Link, _R.LinkVisited)
_ON_ACCENT_ROLES = (_R.HighlightedText, _R.BrightText)

LIGHT = {
    _R.Window: "#F6F5F1",
    _R.Base: "#FDFDFB",
    _R.AlternateBase: "#EFEEE9",
    **dict.fromkeys(_TEXT_ROLES, "#15181C"),
    _R.Button: "#FDFDFB",
    **dict.fromkeys(_ACCENT_ROLES, "#0B6F68"),
    **dict.fromkeys(_ON_ACCENT_ROLES, "#FFFFFF"),
    _R.PlaceholderText: "#6D6F71",
    _R.Light: "#FFFFFF",
    _R.Midlight: "#EFEEE9",
    _R.Mid: "#D3D4D3",
    _R.Dark: "#8E8F8F",
    _R.Shadow: "#000000",
    _R.ToolTipBase: "#15181C",
    _R.ToolTipText: "#F6F5F1",
}

DARK = {
    _R.Window: "#0A1220",
    _R.Base: "#111B2B",
    _R.AlternateBase: "#0C1524",
    **dict.fromkeys(_TEXT_ROLES, "#EEF3F8"),
    _R.Button: "#16223A",
    **dict.fromkeys(_ACCENT_ROLES, "#5FD8BE"),
    **dict.fromkeys(_ON_ACCENT_ROLES, "#04201B"),
    _R.PlaceholderText: "#9AA1AA",
    _R.Light: "#1C2A3F",
    _R.Midlight: "#16223A",
    _R.Mid: "#394250",
    _R.Dark: "#616B79",
    _R.Shadow: "#000000",
    _R.ToolTipBase: "#EEF3F8",
    _R.ToolTipText: "#0A1220",
}

LIGHT_DISABLED = {
    **dict.fromkeys(_TEXT_ROLES, "#8A9099"),
    _R.Base: "#EFEEE9",
    _R.Button: "#EFEEE9",
}

DARK_DISABLED = {
    **dict.fromkeys(_TEXT_ROLES, "#6F7A89"),
    _R.Base: "#0C1524",
    _R.Button: "#0C1524",
}


def requested() -> str:
    value = os.environ.get(ENVIRONMENT, "").strip().lower()
    return DESKTOP if value == DESKTOP else LEGION


def palette(dark: bool) -> QPalette:
    result = QPalette()
    for role, value in (DARK if dark else LIGHT).items():
        result.setColor(QPalette.ColorGroup.All, role, QColor(value))
    for role, value in (DARK_DISABLED if dark else LIGHT_DISABLED).items():
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(value))
    return result


def framed_palettes(chosen: QPalette) -> dict[str, QPalette]:
    framed = QPalette(chosen)
    edge = theme.edge_strong_color(chosen, chosen.color(_R.Base))
    edge = theme.fit_contrast(edge, chosen.color(_R.Window), theme.MIN_NON_TEXT_CONTRAST)
    framed.setColor(_R.Window, theme.fusion_window(edge))
    scrolled = QPalette(chosen)
    scrolled.setColor(_R.Window, theme.fusion_window(theme.scroll_outline_color(chosen)))
    return {**dict.fromkeys(FRAMED, framed), "QScrollBar": scrolled}


class LegionScheme(QObject):
    def __init__(self, app: QApplication, fallback: QPalette) -> None:
        super().__init__(app)
        self._app = app
        self._fallback = QPalette(fallback)
        self.dark = False
        app.styleHints().colorSchemeChanged.connect(self.follow)

    def follow(self, scheme: Qt.ColorScheme) -> None:
        self.apply(theme.is_dark(scheme, self._fallback))

    def apply(self, dark: bool) -> None:
        self.dark = dark
        chosen = palette(dark)
        self._app.setPalette(chosen)
        for name, framed in framed_palettes(chosen).items():
            self._app.setPalette(framed, name)
        self._app.setStyleSheet(styles.app_qss(chosen))


def install(app: QApplication) -> LegionScheme | None:
    if requested() == DESKTOP:
        return None
    fallback = QPalette(app.palette())
    app.setStyle(STYLE)
    controller = LegionScheme(app, fallback)
    controller.follow(app.styleHints().colorScheme())
    return controller
