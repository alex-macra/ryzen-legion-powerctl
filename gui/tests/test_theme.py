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
        from legion_powerctl_gui import theme

        palette = self.palette(*BREEZE_LIGHT)
        style = theme.chip_style(palette, "FAIL")
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
        from legion_powerctl_gui import theme

        palette = self.palette(*BREEZE_LIGHT)
        style = theme.focus_ring_style(palette)
        self.assertIn(":focus", style)
        self.assertIn(theme.focus_color(palette).name(), style)
        self.assertIn("transparent", style)

    def test_the_styles_carry_only_colours_that_were_measured(self):
        from legion_powerctl_gui import theme

        palette = self.palette(*BREEZE_DARK)
        button = theme.primary_button_style(palette)
        self.assertIn(theme.accent_color(palette).name(), button)
        self.assertIn(theme.on_accent_color(palette).name(), button)
        self.assertIn(":disabled", button)
        self.assertIn(theme.edge_color(palette).name(), theme.card_style(palette))

    def test_a_colour_that_already_passes_is_left_alone(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QColor

        black = QColor("#000000")
        self.assertEqual(
            theme.fit_contrast(black, QColor("#ffffff")).name(), black.name()
        )


if __name__ == "__main__":
    unittest.main()
