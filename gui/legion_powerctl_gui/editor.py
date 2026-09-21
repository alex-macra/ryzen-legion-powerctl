# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import a11y, fields, model, theme
from .advanced import AdvancedFields
from .envelope import Envelope


class ProfileEditor(QWidget):
    armed = Signal(bool)
    apply_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editing: model.Profile | None = None
        self.current_name = ""
        self.dirty = False
        self._updating = False
        self._busy = False
        self._last_problem_text = ""

        layout = QVBoxLayout(self)
        self.profile_title = QLabel("No profile selected")
        title_font = self.profile_title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        self.profile_title.setFont(title_font)
        layout.addWidget(self.profile_title)

        power, power_form = fields.card(
            "Power envelope", "Sustained <= slow <= fast: moving one past a neighbour moves it too."
        )
        self.power_envelope = Envelope(
            (("stapm", "Sustained (STAPM)"), ("slow", "Slow PPT"), ("fast", "Fast PPT")),
            model.POWER_MIN_W, model.POWER_MAX_W, " W", "watts",
            note="; a limit cannot pass its neighbour, which moves instead",
        )
        power_form.addRow(self.power_envelope)
        self.stapm_slider, self.slow_slider, self.fast_slider = self.power_envelope.stops.values()
        self.stapm_spin, self.slow_spin, self.fast_spin = self.power_envelope.spins.values()

        thermal, thermal_form = fields.card("Thermal ceiling")
        self.thermal_envelope = Envelope(
            (("temp", "Temperature ceiling"),),
            model.TEMP_MIN_C, model.TEMP_MAX_C, " °C", "degrees Celsius",
        )
        thermal_form.addRow(self.thermal_envelope)
        self.temp_slider = self.thermal_envelope.stops["temp"]
        self.temp_spin = self.thermal_envelope.spins["temp"]
        self.envelopes = [self.power_envelope, self.thermal_envelope]
        self.power_envelope.tier_changed.connect(self._on_power_changed)
        self.thermal_envelope.tier_changed.connect(self._on_temp_changed)
        for envelope in self.envelopes:
            envelope.edited.connect(self._on_edited)

        policy, policy_form = fields.card("CPU policy")
        self.power_profile_combo = fields.combo(model.POWER_PROFILES)
        self.power_profile_combo.activated.connect(self._on_edited)
        policy_form.addRow("Linux power profile", self.power_profile_combo)

        self.advanced = AdvancedFields()
        self.advanced.edited.connect(self._on_edited)

        self.cards = [power, thermal, policy]
        for group in self.cards:
            layout.addWidget(group)
        layout.addWidget(self.advanced)

        self.problems_label = QLabel("")
        self.problems_label.setWordWrap(True)
        layout.addWidget(self.problems_label)

        self.dirty_label = QLabel("")
        self.apply_button = QPushButton("&Apply now")
        self.apply_button.clicked.connect(self.apply_requested)
        self.buttons = [self.apply_button]
        actions = QHBoxLayout()
        actions.addWidget(self.dirty_label)
        actions.addStretch(1)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.fields = [
            self.stapm_slider, self.stapm_spin,
            self.slow_slider, self.slow_spin, self.fast_slider, self.fast_spin,
            self.temp_slider, self.temp_spin, self.power_profile_combo,
        ]
        self.restyle(self.palette())

    def load(self, profile: model.Profile) -> None:
        self._updating = True
        self.editing = model.Profile(**vars(profile))
        self.current_name = profile.name
        self._set_enabled(True)
        self.profile_title.setText(profile.name)
        self.thermal_envelope.set_high(
            model.BALANCED_PLUS_MAX_TEMP_C if profile.name == "balanced-plus"
            else model.TEMP_MAX_C
        )
        for slider, spin, value in (
            (self.stapm_slider, self.stapm_spin, profile.stapm_w),
            (self.slow_slider, self.slow_spin, profile.slow_w),
            (self.fast_slider, self.fast_spin, profile.fast_w),
            (self.temp_slider, self.temp_spin, profile.temp_c),
        ):
            slider.setValue(value)
            spin.setValue(value)
        fields.set_combo_value(self.power_profile_combo, profile.power_profile)
        self.advanced.load(profile)
        self.dirty = False
        self._set_problem_text("")
        self._updating = False
        self._update_actions()

    def collect(self) -> model.Profile:
        assert self.editing is not None
        return model.Profile(
            name=self.editing.name,
            description=self.editing.description,
            stapm_w=self.stapm_spin.value(),
            slow_w=self.slow_spin.value(),
            fast_w=self.fast_spin.value(),
            temp_c=self.temp_spin.value(),
            power_profile=fields.combo_value(self.power_profile_combo),
            **self.advanced.values(),
        )

    def problems(self) -> list[str]:
        return model.validate_profile(self.collect()) if self.editing is not None else []

    def show_invalid(self, name: str) -> None:
        self.editing = None
        self.current_name = name
        self.dirty = False
        self.profile_title.setText(name)
        self._set_enabled(False)
        self._update_actions()
        self._set_problem_text(
            f"Problem: '{name}' is not a readable profile. Run legion-powerctl "
            f"doctor to see why, or use New profile with the same name to replace it."
        )

    def clear(self) -> None:
        self.editing = None
        self.current_name = ""

    def mark_saved(self, profile: model.Profile) -> None:
        if self.editing is not None and self.collect() == profile:
            self.dirty = False
            self._update_actions()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.apply_button.setText("Applying..." if busy else "&Apply now")
        self._update_actions()

    def restyle(self, palette: QPalette) -> None:
        self.problems_label.setStyleSheet(theme.text_style(palette, "FAIL"))
        self.dirty_label.setStyleSheet(
            f"color: {theme.muted_color(palette, palette.color(QPalette.ColorRole.Window)).name()};"
        )
        self.apply_button.setStyleSheet(theme.primary_button_style(palette))
        surface = theme.card_style(palette)
        for group in self.cards:
            group.setStyleSheet(surface)
        for envelope in self.envelopes:
            envelope.restyle(palette)
        for note in self.findChildren(QLabel, fields.CAPTION):
            note.setStyleSheet(theme.caption_style(palette))

    def _set_enabled(self, enabled: bool) -> None:
        for widget in self.fields:
            widget.setEnabled(enabled)
        self.advanced.set_enabled(enabled)
        self.armed.emit(enabled)

    def _update_actions(self) -> None:
        problems = self.problems()
        self.apply_button.setEnabled(
            self.editing is not None and not problems and not self._busy
        )
        self.dirty_label.setText("Unsaved changes" if self.dirty and not problems else "")

    def _set_problem_text(self, message: str) -> None:
        self.problems_label.setText(message)
        if message and message != self._last_problem_text:
            a11y.announce(self.problems_label, message)
        self._last_problem_text = message

    def _on_power_changed(self, field: str, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        stapm = self.stapm_spin.value()
        slow = self.slow_spin.value()
        fast = self.fast_spin.value()
        if field == "stapm":
            stapm = value
        elif field == "slow":
            slow = value
        elif field == "fast":
            fast = value
        stapm, slow, fast = model.enforce_power_order(stapm, slow, fast, field)
        for slider, spin, new in (
            (self.stapm_slider, self.stapm_spin, stapm),
            (self.slow_slider, self.slow_spin, slow),
            (self.fast_slider, self.fast_spin, fast),
        ):
            slider.setValue(new)
            spin.setValue(new)
        self._updating = False
        self._on_edited()

    def _on_temp_changed(self, _field: str, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.temp_slider.setValue(value)
        self.temp_spin.setValue(value)
        self._updating = False
        self._on_edited()

    def _on_edited(self, *_args) -> None:
        if self._updating or self.editing is None:
            return
        self.dirty = True
        self._set_problem_text("\n".join(f"Problem: {p}" for p in self.problems()))
        self._update_actions()
