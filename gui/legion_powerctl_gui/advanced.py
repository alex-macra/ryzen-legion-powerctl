# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from . import fields, model, styles, theme

FIELD_NAMES = ("boost", "epp", "min_freq_mhz", "max_freq_mhz")
BORDER = 1
RING = 2
ARROW_INSET = 8
END_PADDING = 6
CLOSED_PADDING = 10
MARGINS = (
    styles.CARD_MARGINS[0] + BORDER - RING - ARROW_INSET, CLOSED_PADDING,
    styles.CARD_MARGINS[2] + BORDER, CLOSED_PADDING,
)
OPEN_BOTTOM = styles.CARD_MARGINS[3] + BORDER


def disclosure_style(palette: QPalette) -> str:
    base = palette.color(QPalette.ColorRole.Base)
    text = theme.fit_contrast(palette.color(QPalette.ColorRole.Text), base)
    hover = theme.fit_contrast(theme.accent_color(palette), base)
    return (
        f"QToolButton {{ border: {RING}px solid transparent; border-radius: 6px;"
        f" background-color: transparent; padding: 2px {END_PADDING}px 2px 0px; font-weight: 600;"
        f" color: {text.name()}; }}"
        f" QToolButton:hover {{ color: {hover.name()}; }}"
        f" QToolButton:focus {{ border-color: {theme.focus_color(palette).name()}; }}"
        f" QToolButton:disabled {{ color: {theme.disabled_text_color(palette).name()}; }}"
    )


class AdvancedFields(QWidget):
    edited = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column = QVBoxLayout(self)
        column.setContentsMargins(*MARGINS)
        column.setSpacing(fields.ROW_SPACING)

        self.button = QToolButton()
        self.button.setText("Advanced (boost, EPP, frequency range)")
        self.button.setCheckable(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.toggled.connect(self._on_toggled)
        column.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)

        self.panel = QWidget()
        form = fields.form_layout()
        form.setContentsMargins(RING + ARROW_INSET, 0, 0, 0)
        self.panel.setLayout(form)
        self.panel.setVisible(False)
        self.boost_combo = self._combo(model.BOOST_VALUES)
        fields.add_row(form, "CPU boost", self.boost_combo)
        self.epp_combo = self._combo(model.EPP_VALUES)
        fields.add_row(form, "Energy preference (EPP)", self.epp_combo)
        self.min_freq_edit = self._combo(("stock", "unchanged"), editable=True)
        self.max_freq_edit = self._combo(("stock", "unchanged"), editable=True)
        fields.add_row(form, "Minimum frequency (MHz)", self.min_freq_edit)
        fields.add_row(form, "Maximum frequency (MHz)", self.max_freq_edit)
        column.addWidget(self.panel)

        self.combos = [
            self.boost_combo, self.epp_combo, self.min_freq_edit, self.max_freq_edit
        ]
        self.restyle(self.palette())

    def load(self, profile: model.Profile) -> None:
        fields.set_combo_value(self.boost_combo, profile.boost)
        fields.set_combo_value(self.epp_combo, profile.epp)
        fields.set_combo_value(self.min_freq_edit, profile.min_freq_mhz)
        fields.set_combo_value(self.max_freq_edit, profile.max_freq_mhz)
        self.button.setChecked(
            any(getattr(profile, name) != "unchanged" for name in FIELD_NAMES)
        )

    def values(self) -> dict[str, str]:
        return {
            "boost": fields.combo_value(self.boost_combo),
            "epp": fields.combo_value(self.epp_combo),
            "min_freq_mhz": fields.combo_value(self.min_freq_edit),
            "max_freq_mhz": fields.combo_value(self.max_freq_edit),
        }

    def set_enabled(self, enabled: bool) -> None:
        self.button.setEnabled(enabled)
        for combo in self.combos:
            combo.setEnabled(enabled)

    def restyle(self, palette: QPalette) -> None:
        self.setStyleSheet(f"{styles.surface_style(palette)} {disclosure_style(palette)}")

    def _combo(self, values: tuple[str, ...], editable: bool = False):
        box = fields.combo(values, editable)
        box.activated.connect(self.edited)
        if editable:
            box.editTextChanged.connect(self.edited)
        return box

    def _on_toggled(self, open_: bool) -> None:
        self.panel.setVisible(open_)
        self.button.setArrowType(
            Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow
        )
        left, top, right, bottom = MARGINS
        self.layout().setContentsMargins(left, top, right, OPEN_BOTTOM if open_ else bottom)
