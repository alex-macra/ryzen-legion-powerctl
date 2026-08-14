# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from . import fields, model

FIELD_NAMES = ("boost", "epp", "min_freq_mhz", "max_freq_mhz")


class AdvancedFields(QWidget):
    edited = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)

        self.button = QToolButton()
        self.button.setText("Advanced (boost, EPP, frequency range)")
        self.button.setCheckable(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.toggled.connect(self._on_toggled)
        column.addWidget(self.button)

        self.panel = QWidget()
        form = fields.form_layout()
        self.panel.setLayout(form)
        self.panel.setVisible(False)
        self.boost_combo = self._combo(model.BOOST_VALUES)
        form.addRow("CPU boost", self.boost_combo)
        self.epp_combo = self._combo(model.EPP_VALUES)
        form.addRow("Energy preference (EPP)", self.epp_combo)
        self.min_freq_edit = self._combo(("stock", "unchanged"), editable=True)
        self.max_freq_edit = self._combo(("stock", "unchanged"), editable=True)
        form.addRow("Minimum frequency (MHz)", self.min_freq_edit)
        form.addRow("Maximum frequency (MHz)", self.max_freq_edit)
        column.addWidget(self.panel)

        self.combos = [
            self.boost_combo, self.epp_combo, self.min_freq_edit, self.max_freq_edit
        ]

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
