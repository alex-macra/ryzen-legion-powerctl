# SPDX-License-Identifier: MIT

import unittest

try:
    import PySide6  # noqa: F401

    HAVE_PYSIDE6 = True
except ImportError:
    HAVE_PYSIDE6 = False

LEGACY_CHIP_COLORS = {"OK": "#27ae60", "WARN": "#f39c12", "FAIL": "#da4453", "NEUTRAL": "#888888"}

AA_TEXT = 4.5
AA_NON_TEXT = 3.0

BREEZE_LIGHT = ("#eff0f1", "#232629", "#fcfcfc")
BREEZE_DARK = ("#232629", "#eff0f1", "#1b1e20")
WORST_CASE = "worst case grey"
PALETTES = {
    "breeze light": BREEZE_LIGHT,
    "breeze dark": BREEZE_DARK,
    "pure white": ("#ffffff", "#000000", "#ffffff"),
    "pure black": ("#000000", "#ffffff", "#000000"),
    "worst case grey": ("#757575", "#000000", "#757575"),
    "cachyos emerald": ("#1b1e20", "#e3e5e6", "#232629"),
}


def wcag_ratio(first_hex: str, second_hex: str) -> float:
    def luminance(value: str) -> float:
        value = value.lstrip("#")
        channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    one, other = luminance(first_hex), luminance(second_hex)
    return (max(one, other) + 0.05) / (min(one, other) + 0.05)


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class SeverityContrastTest(unittest.TestCase):
    @staticmethod
    def palette(window: str, text: str, base: str | None = None):
        from PySide6.QtGui import QColor, QPalette

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#3daee9"))
        palette.setColor(QPalette.ColorRole.Base, QColor(base or window))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(window))
        return palette

    def test_every_severity_clears_aa_on_every_palette(self):
        from legion_powerctl_gui import theme

        for name, (window, text, base_hex) in PALETTES.items():
            palette = self.palette(window, text, base_hex)
            for severity in theme.SEVERITIES:
                with self.subTest(palette=name, severity=severity):
                    color = theme.severity_color(palette, severity).name()
                    self.assertGreaterEqual(
                        wcag_ratio(color, window), AA_TEXT,
                        f"{severity} is {color} on {window}, below WCAG AA",
                    )

    def test_the_focus_ring_clears_the_non_text_floor(self):
        from legion_powerctl_gui import theme

        self.assertEqual((theme.MIN_CONTRAST, theme.MIN_NON_TEXT_CONTRAST),
                         (AA_TEXT, AA_NON_TEXT), "theme.py aims at something other than AA")
        for name, (window, text, base_hex) in PALETTES.items():
            with self.subTest(palette=name):
                ring = theme.focus_color(self.palette(window, text, base_hex)).name()
                self.assertGreaterEqual(wcag_ratio(ring, window), AA_NON_TEXT)

    def test_the_fit_keeps_the_hue_that_carries_the_meaning(self):
        from legion_powerctl_gui import theme

        for name, (window, text, base_hex) in PALETTES.items():
            if name == WORST_CASE:
                continue
            palette = self.palette(window, text, base_hex)
            for severity, wanted in theme.SEVERITY_HUE.items():
                color = theme.severity_color(palette, severity)
                hue = color.getHslF()[0]
                with self.subTest(palette=name, severity=severity):
                    self.assertGreaterEqual(
                        hue, 0.0, f"{severity} fitted to {color.name()}, which has no hue",
                    )
                    measured = hue * 360.0
                    self.assertLessEqual(
                        min(abs(measured - wanted), 360.0 - abs(measured - wanted)), 1.0,
                        f"{severity} fitted to {color.name()}, hue {measured:.1f} "
                        f"rather than {wanted}",
                    )

    def test_the_hardest_background_converges_and_that_is_the_price(self):
        from legion_powerctl_gui import theme

        window = PALETTES[WORST_CASE][0]
        palette = self.palette(*PALETTES[WORST_CASE])
        colors = [theme.severity_color(palette, s).name() for s in ("OK", "WARN", "FAIL")]
        for one, other in ((0, 1), (1, 2), (0, 2)):
            self.assertLess(
                wcag_ratio(colors[one], colors[other]), 1.1,
                f"{colors[one]} and {colors[other]} no longer converge here - if the "
                f"fit improved, this test should say so",
            )
        for color in colors:
            self.assertGreaterEqual(wcag_ratio(color, window), AA_TEXT)

    def test_the_ratio_theme_computes_is_the_ratio_wcag_defines(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QColor

        for first, second, expected in (
            ("#ffffff", "#000000", 21.0),
            ("#777777", "#777777", 1.0),
            ("#eff0f1", "#27ae60", 2.52),
        ):
            self.assertAlmostEqual(
                theme.contrast_ratio(QColor(first), QColor(second)),
                wcag_ratio(first, second),
                places=6,
            )
            self.assertAlmostEqual(wcag_ratio(first, second), expected, places=2)

    def test_the_colours_this_replaced_really_did_fail(self):
        for severity, legacy in LEGACY_CHIP_COLORS.items():
            with self.subTest(severity=severity, palette="breeze light"):
                self.assertLess(wcag_ratio(legacy, BREEZE_LIGHT[0]), 4.5)
        self.assertLess(wcag_ratio(LEGACY_CHIP_COLORS["FAIL"], BREEZE_DARK[0]), 4.5)

    def test_chip_style_carries_the_fitted_colour_and_a_focus_ring(self):
        from legion_powerctl_gui import styles, theme

        palette = self.palette(*BREEZE_LIGHT)
        style = styles.chip_style(palette, "FAIL")
        self.assertIn(theme.severity_color(palette, "FAIL").name(), style)
        self.assertIn(theme.focus_color(palette).name(), style)
        self.assertIn(":focus", style)

    def test_the_accent_clears_the_non_text_floor_on_every_palette(self):
        from legion_powerctl_gui import theme

        for name, (window, text, base_hex) in PALETTES.items():
            with self.subTest(palette=name):
                accent = theme.accent_color(self.palette(window, text, base_hex)).name()
                self.assertGreaterEqual(wcag_ratio(accent, window), AA_NON_TEXT)

    def test_text_on_the_accent_is_fitted_to_the_accent(self):
        from legion_powerctl_gui import theme

        for name, (window, text, base_hex) in PALETTES.items():
            palette = self.palette(window, text, base_hex)
            with self.subTest(palette=name):
                accent = theme.accent_color(palette).name()
                self.assertGreaterEqual(
                    wcag_ratio(theme.on_accent_color(palette).name(), accent), AA_TEXT
                )

    def test_muted_text_is_dimmer_than_the_text_and_still_readable(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QPalette

        for name, (_window, text, base_hex) in PALETTES.items():
            palette = self.palette(_window, text, base_hex)
            muted = theme.muted_color(palette, palette.color(QPalette.ColorRole.Base)).name()
            with self.subTest(palette=name):
                self.assertGreaterEqual(wcag_ratio(muted, base_hex), AA_TEXT)
                if name == WORST_CASE:
                    continue
                self.assertLess(
                    wcag_ratio(muted, base_hex), wcag_ratio(text, base_hex),
                    "the second line of a row is the same weight as the first, so if "
                    "it is also the same colour there is no hierarchy at all",
                )

    def test_a_stop_marker_clears_the_non_text_floor_on_every_palette(self):
        from legion_powerctl_gui import theme

        for name, (window, text, base_hex) in PALETTES.items():
            palette = self.palette(window, text, base_hex)
            base = palette.color(self.base_role())
            with self.subTest(palette=name):
                marker = theme.marker_color(palette, base).name()
                self.assertGreaterEqual(wcag_ratio(marker, base.name()), AA_NON_TEXT)

    def test_the_tiers_step_away_from_the_accent_in_order(self):
        from legion_powerctl_gui import theme

        def distance(one, other):
            return sum(abs(a - b) for a, b in zip(one.getRgb()[:3], other.getRgb()[:3]))

        for name, (window, text, base_hex) in PALETTES.items():
            palette = self.palette(window, text, base_hex)
            base = palette.color(self.base_role())
            track = theme.track_color(palette, base)
            steps = [
                distance(theme.tier_color(palette, base, theme.tier_step(index)), track)
                for index in range(3)
            ]
            with self.subTest(palette=name):
                self.assertEqual(
                    steps, sorted(steps, reverse=True),
                    f"the fill ramp runs backwards on {name}: {steps}",
                )
                self.assertEqual(len(set(steps)), len(steps), "two tiers are the same colour")

    @staticmethod
    def base_role():
        from PySide6.QtGui import QPalette

        return QPalette.ColorRole.Base

    def test_the_row_marks_are_measured_against_the_row_and_not_the_window(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QPalette

        for name, (window, text, base_hex) in PALETTES.items():
            palette = self.palette(window, text, base_hex)
            base = palette.color(QPalette.ColorRole.Base)
            for surface, label in (
                (base, "an ordinary row"),
                (theme.wash_color(palette, base), "the running row's wash"),
                (palette.color(QPalette.ColorRole.Highlight), "a selected row"),
            ):
                fitted = theme.fit_contrast(
                    theme.accent_color(palette), surface, theme.MIN_NON_TEXT_CONTRAST
                )
                with self.subTest(palette=name, surface=label):
                    self.assertGreaterEqual(
                        wcag_ratio(fitted.name(), surface.name()), AA_NON_TEXT,
                        f"the accent is invisible on {label} under {name}",
                    )

    def test_a_focusable_row_shows_something_when_it_is_focused(self):
        from legion_powerctl_gui import styles, theme

        palette = self.palette(*BREEZE_LIGHT)
        style = styles.focus_ring_style(palette)
        self.assertIn(":focus", style)
        self.assertIn(theme.focus_color(palette).name(), style)
        self.assertIn("transparent", style)

    def test_the_styles_carry_only_colours_that_were_measured(self):
        from legion_powerctl_gui import styles, theme

        palette = self.palette(*BREEZE_DARK)
        button = styles.primary_button_style(palette)
        self.assertIn(theme.accent_color(palette).name(), button)
        self.assertIn(theme.on_accent_color(palette).name(), button)
        self.assertIn(":disabled", button)
        self.assertIn(theme.edge_color(palette).name(), styles.card_style(palette))

    def test_a_colour_that_already_passes_is_left_alone(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QColor

        black = QColor("#000000")
        self.assertEqual(
            theme.fit_contrast(black, QColor("#ffffff")).name(), black.name()
        )


LEGION_SEVERITIES = {
    "legion light": {"OK": "#167e1a", "WARN": "#8f6419", "FAIL": "#c32d22"},
    "legion dark": {"OK": "#5ae25f", "WARN": "#e2b05a", "FAIL": "#e2635a"},
}


def hue_distance(one: float, other: float) -> float:
    gap = abs(one - other) % 360.0
    return min(gap, 360.0 - gap)


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class DerivedTokenContrastTest(unittest.TestCase):
    @staticmethod
    def legion():
        from legion_powerctl_gui import scheme

        return {"legion light": scheme.palette(False), "legion dark": scheme.palette(True)}

    def every_palette(self):
        palettes = {
            name: SeverityContrastTest.palette(*colours) for name, colours in PALETTES.items()
        }
        palettes.update(self.legion())
        return palettes

    @staticmethod
    def roles(palette):
        from PySide6.QtGui import QPalette

        return (
            palette.color(QPalette.ColorRole.Window),
            palette.color(QPalette.ColorRole.Base),
            palette.color(QPalette.ColorRole.Text),
        )

    def test_the_legion_scheme_clears_every_floor_the_desktop_palettes_do(self):
        from legion_powerctl_gui import theme

        for name, palette in self.legion().items():
            window, base, text = self.roles(palette)
            accent = theme.accent_color(palette)
            with self.subTest(palette=name):
                for severity in theme.SEVERITIES:
                    color = theme.severity_color(palette, severity)
                    self.assertGreaterEqual(theme.contrast_ratio(color, window), AA_TEXT)
                self.assertGreaterEqual(theme.contrast_ratio(accent, window), AA_NON_TEXT)
                self.assertGreaterEqual(theme.contrast_ratio(accent, base), AA_NON_TEXT)
                self.assertGreaterEqual(
                    theme.contrast_ratio(theme.on_accent_color(palette), accent), AA_TEXT
                )
                muted = theme.muted_color(palette, base)
                self.assertGreaterEqual(theme.contrast_ratio(muted, base), AA_TEXT)
                self.assertLess(theme.contrast_ratio(muted, base), theme.contrast_ratio(text, base))
                marker = theme.marker_color(palette, base)
                self.assertGreaterEqual(theme.contrast_ratio(marker, base), AA_NON_TEXT)
                track = theme.track_color(palette, base)
                steps = [
                    theme.contrast_ratio(theme.tier_color(palette, base, theme.tier_step(i)), track)
                    for i in range(3)
                ]
                self.assertEqual(steps, sorted(steps, reverse=True), steps)
                self.assertEqual(len(set(steps)), 3, "two tiers are the same colour")

    def test_the_legion_states_are_the_ones_the_spec_measured(self):
        from legion_powerctl_gui import theme

        for name, palette in self.legion().items():
            for severity, wanted in LEGION_SEVERITIES[name].items():
                with self.subTest(palette=name, severity=severity):
                    color = theme.severity_color(palette, severity)
                    self.assertEqual(color.name(), wanted)
                    self.assertLessEqual(
                        hue_distance(color.getHslF()[0] * 360.0, theme.SEVERITY_HUE[severity]),
                        1.0,
                    )

    def test_a_dark_plane_seeds_its_states_lighter_than_a_light_one(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QColor

        self.assertGreater(theme.SEED_LIGHTNESS_DARK, theme.SEED_LIGHTNESS)
        dark = self.legion()["legion dark"]
        for severity, hue in theme.SEVERITY_HUE.items():
            seed = QColor.fromHslF(
                hue / 360.0, theme.SEVERITY_SATURATION, theme.SEED_LIGHTNESS_DARK, 1.0
            )
            with self.subTest(severity=severity):
                self.assertEqual(
                    theme.severity_color(dark, severity).name(), seed.name(),
                    "the dark seed already clears AA, so the fit should leave it a pastel",
                )

    def test_ok_is_never_mistaken_for_the_accent(self):
        from legion_powerctl_gui import theme

        for name, palette in self.legion().items():
            accent = theme.accent_color(palette).getHslF()[0] * 360.0
            ok = theme.severity_color(palette, "OK").getHslF()[0] * 360.0
            with self.subTest(palette=name):
                self.assertGreaterEqual(hue_distance(accent, ok), 40.0)

    def test_secondary_text_sits_between_muted_and_full_text(self):
        from legion_powerctl_gui import theme

        for name, palette in self.every_palette().items():
            window, base, text = self.roles(palette)
            for surface, label in ((base, "card"), (window, "plane")):
                secondary = theme.secondary_color(palette, surface)
                muted = theme.muted_color(palette, surface)
                with self.subTest(palette=name, surface=label):
                    self.assertGreaterEqual(theme.contrast_ratio(secondary, surface), AA_TEXT)
                    if name == WORST_CASE:
                        continue
                    self.assertLessEqual(
                        theme.contrast_ratio(muted, surface),
                        theme.contrast_ratio(secondary, surface),
                    )
                    self.assertLess(
                        theme.contrast_ratio(secondary, surface),
                        theme.contrast_ratio(text, surface),
                    )

    def test_an_input_border_clears_the_non_text_floor(self):
        from legion_powerctl_gui import theme

        for name, palette in self.every_palette().items():
            _window, base, _text = self.roles(palette)
            with self.subTest(palette=name):
                edge = theme.edge_strong_color(palette, base)
                self.assertGreaterEqual(theme.contrast_ratio(edge, base), AA_NON_TEXT)

    def test_the_hairline_sits_between_the_plane_and_the_ink(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QPalette

        for name, palette in self.every_palette().items():
            window = palette.color(QPalette.ColorRole.Window)
            ink = palette.color(QPalette.ColorRole.WindowText)
            hairline = theme.edge_color(palette)
            with self.subTest(palette=name):
                low, high = sorted(
                    (theme.relative_luminance(window), theme.relative_luminance(ink))
                )
                self.assertLess(low, theme.relative_luminance(hairline))
                self.assertLess(theme.relative_luminance(hairline), high)
                self.assertLess(
                    theme.contrast_ratio(hairline, window), theme.contrast_ratio(ink, window)
                )

    def test_a_selected_row_keeps_its_text_and_its_rail_readable(self):
        from legion_powerctl_gui import theme

        for name, palette in self.every_palette().items():
            _window, base, text = self.roles(palette)
            selection = theme.selection_color(palette)
            accent = theme.accent_color(palette)
            with self.subTest(palette=name):
                self.assertNotEqual(selection.name(), base.name(), "selection is invisible")
                self.assertGreaterEqual(
                    theme.contrast_ratio(theme.fit_contrast(text, selection), selection), AA_TEXT
                )
                rail = theme.fit_contrast(accent, selection, theme.MIN_NON_TEXT_CONTRAST)
                self.assertGreaterEqual(theme.contrast_ratio(rail, selection), AA_NON_TEXT)
        for name, palette in self.legion().items():
            _window, _base, text = self.roles(palette)
            selection = theme.selection_color(palette)
            with self.subTest(palette=name, unfitted=True):
                self.assertGreaterEqual(theme.contrast_ratio(text, selection), AA_TEXT)
                self.assertGreaterEqual(
                    theme.contrast_ratio(theme.accent_color(palette), selection), AA_NON_TEXT
                )

    def test_a_badge_word_stays_readable_on_its_own_tint_at_rest_and_on_hover(self):
        from legion_powerctl_gui import styles, theme

        for name, palette in self.every_palette().items():
            for severity in theme.SEVERITIES:
                style = styles.badge_style(palette, severity)
                fill, text = self.rule(style, "QLabel", "background-color", "color")
                (hover,) = self.rule(style, "QLabel:hover", "background-color")
                with self.subTest(palette=name, severity=severity):
                    self.assertIn(theme.focus_color(palette).name(), style)
                    for surface in (fill, hover):
                        self.assertGreaterEqual(wcag_ratio(text, surface), AA_TEXT)
                    if severity != "NEUTRAL":
                        self.assertIn(theme.severity_color(palette, severity).name(), style)

    def test_the_readout_inks_clear_the_text_floor_on_every_palette(self):
        from legion_powerctl_gui import styles, theme

        for name, palette in self.every_palette().items():
            _window, base, _text = self.roles(palette)
            for severity in ("OK", "FAIL"):
                colours = styles.readout_colors(palette, severity)
                for part, colour in colours._asdict().items():
                    with self.subTest(palette=name, severity=severity, part=part):
                        self.assertGreaterEqual(theme.contrast_ratio(colour, base), AA_TEXT)
            if name == WORST_CASE:
                continue
            fail = styles.readout_colors(palette, "FAIL").value
            with self.subTest(palette=name, hue="FAIL"):
                self.assertLessEqual(
                    hue_distance(fail.getHslF()[0] * 360.0, theme.SEVERITY_HUE["FAIL"]), 1.0,
                    f"figures that did not take are {fail.name()}, which no longer reads as FAIL",
                )

    def test_a_callout_is_readable_and_still_names_its_severity(self):
        from legion_powerctl_gui import styles, theme

        for name, palette in self.every_palette().items():
            for style, severity in (
                (styles.problem_style(palette), "FAIL"),
                (styles.callout_style(palette, "WARN"), "WARN"),
            ):
                fill, text = self.rule(style, "QLabel", "background-color", "color")
                with self.subTest(palette=name, severity=severity):
                    self.assertGreaterEqual(wcag_ratio(text, fill), AA_TEXT)
                    self.assertIn(theme.severity_color(palette, severity).name(), style)

    def test_the_buttons_and_the_status_bar_carry_measured_colours(self):
        from legion_powerctl_gui import styles, theme

        for name, palette in self.every_palette().items():
            window, base, _text = self.roles(palette)
            secondary = styles.secondary_button_style(palette)
            (ghost,) = self.rule(styles.ghost_button_style(palette), "QPushButton", "color")
            bar = styles.status_bar_style(palette)
            (message,) = self.rule(bar, "QStatusBar", "color")
            with self.subTest(palette=name):
                self.assertIn(theme.edge_strong_color(palette, base).name(), secondary)
                (label,) = self.rule(secondary, "QPushButton", "color")
                self.assertGreaterEqual(wcag_ratio(label, base.name()), AA_TEXT)
                self.assertGreaterEqual(wcag_ratio(ghost, window.name()), AA_TEXT)
                self.assertGreaterEqual(wcag_ratio(message, window.name()), AA_TEXT)
                self.assertIn(theme.edge_color(palette).name(), bar)

    def test_the_app_sheet_styles_buttons_and_leaves_native_inputs_alone(self):
        from legion_powerctl_gui import styles, theme

        for name, palette in self.legion().items():
            sheet = styles.app_qss(palette)
            with self.subTest(palette=name):
                self.assertIn('QPushButton[kind="primary"]', sheet)
                self.assertIn(theme.accent_color(palette).name(), sheet)
                for native in ("QSpinBox", "QComboBox", "QScrollBar", "QCheckBox", "QSlider"):
                    self.assertNotIn(native, sheet, f"{native} would be half-styled")

    @staticmethod
    def rule(style: str, selector: str, *properties: str) -> list:
        import re

        block = re.search(r"(?:^|\}\s*)" + re.escape(selector) + r" \{([^}]*)\}", style)
        if block is None:
            raise AssertionError(f"no {selector} rule in {style!r}")
        values = []
        for prop in properties:
            found = re.search(r"(?:^|[;{\s])" + re.escape(prop) + r":\s*(#[0-9a-f]{6})", block[1])
            if found is None:
                raise AssertionError(f"{selector} sets no {prop}: {block[1]!r}")
            values.append(found[1])
        return values


if __name__ == "__main__":
    unittest.main()
