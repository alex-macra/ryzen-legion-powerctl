# SPDX-License-Identifier: MIT

import unittest

from test_app_offscreen import HAVE_PYSIDE6, OffscreenGuiTest

LOW, HIGH = 5, 200
TIERS = (("stapm", "Sustained (STAPM)"), ("slow", "Slow PPT"), ("fast", "Fast PPT"))


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class EnvelopeTest(OffscreenGuiTest):
    def setUp(self):
        from legion_powerctl_gui.envelope import Envelope
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.envelope = Envelope(TIERS, LOW, HIGH, " W", "watts")
        self.envelope.restyle(self.app.palette())
        layout.addWidget(self.envelope)
        self.host.resize(700, 160)
        self.host.show()
        self.app.processEvents()
        self.bar = self.envelope.bar
        self.stops = list(self.envelope.stops.values())
        self.set_values(60, 120, 150)

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()

    def set_values(self, *values):
        for stop, value in zip(self.stops, values):
            stop.setValue(value)
        self.app.processEvents()

    def image(self):
        self.app.processEvents()
        return self.bar.grab().toImage()

    def base(self):
        from PySide6.QtGui import QPalette

        return self.bar.palette().color(QPalette.ColorRole.Base)


    def test_a_stop_is_still_a_slider_to_the_accessibility_tree(self):
        from PySide6.QtGui import QAccessible

        for stop in self.stops:
            with self.subTest(stop=stop.accessibleName()):
                interface = QAccessible.queryAccessibleInterface(stop)
                self.assertIsNotNone(interface, "the stop is invisible to a screen reader")
                self.assertEqual(interface.role(), QAccessible.Role.Slider)
                self.assertEqual(interface.text(QAccessible.Text.Name), stop.accessibleName())
                values = interface.valueInterface()
                self.assertIsNotNone(values, "the stop reports no value at all")
                self.assertEqual(values.currentValue(), stop.value())
                self.assertEqual((values.minimumValue(), values.maximumValue()), (LOW, HIGH))

    def test_the_keyboard_still_does_everything_a_slider_did(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        stop = self.stops[1]
        stop.setFocus()
        self.assertIs(self.app.focusWidget(), stop, "a stop that paints nothing took no focus")
        for key, expected in (
            (Qt.Key.Key_Right, 121),
            (Qt.Key.Key_Left, 120),
            (Qt.Key.Key_PageUp, 120 + stop.pageStep()),
            (Qt.Key.Key_Home, LOW),
            (Qt.Key.Key_End, HIGH),
        ):
            QTest.keyClick(stop, key)
            with self.subTest(key=key):
                self.assertEqual(stop.value(), expected)

    def test_tab_walks_the_stops_and_then_the_values(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        order = []
        self.stops[0].setFocus()
        for _ in range(6):
            order.append(self.app.focusWidget())
            QTest.keyClick(self.host, Qt.Key.Key_Tab)
        self.assertEqual(order, self.stops + list(self.envelope.spins.values()))


    def test_a_click_on_the_bar_moves_the_stop_nearest_it(self):
        target = self.bar.x_for(130)
        self.assertIsNone(
            self.bar.childAt(target, self.bar.height() // 2),
            "a stop is intercepting the press the bar has to hit-test for every stop",
        )
        self.click(target)
        self.assertEqual([stop.value() for stop in self.stops], [60, 130, 150])
        self.assertTrue(self.stops[1].hasFocus(), "clicking a stop did not focus it")

    def test_a_click_beside_two_stacked_stops_takes_the_one_that_can_move(self):
        for offset, moved in ((60, 2), (-60, 0)):
            with self.subTest(offset=offset):
                self.set_values(100, 100, 100)
                self.click(self.bar.x_for(100) + offset)
                values = [stop.value() for stop in self.stops]
                self.assertEqual(
                    [index for index, value in enumerate(values) if value != 100], [moved],
                    f"the click took the wrong stop of the stack: {values}",
                )
                self.assertEqual(values[moved] > 100, offset > 0)

    def click(self, x: int):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        QTest.mouseClick(
            self.bar, Qt.MouseButton.LeftButton, pos=QPoint(x, self.bar.height() // 2)
        )
        self.app.processEvents()


    def test_the_fills_step_down_from_the_sustained_tier_outwards(self):
        from legion_powerctl_gui import theme

        self.set_values(60, 120, 150)
        image = self.image()
        palette, base = self.bar.palette(), self.base()
        bounds = [self.bar.x_for(LOW)]
        bounds += [self.bar.x_for(stop.value()) for stop in self.stops]
        bounds.append(self.bar.x_for(HIGH))
        expected = [theme.tier_color(palette, base, theme.tier_step(i)) for i in range(3)]
        expected.append(theme.track_color(palette, base))
        y = self.bar.height() // 2
        for index, want in enumerate(expected):
            x = (bounds[index] + bounds[index + 1]) // 2
            with self.subTest(band=index):
                self.assertEqual(image.pixelColor(x, y).name(), want.name())

    def test_the_focused_stop_is_the_one_wearing_the_ring(self):
        ring = self.ring_color()
        self.assertNotIn(
            ring, self.colors_around(self.stops[1]), "an unfocused stop is already ringed"
        )
        self.stops[1].setFocus()
        self.assertIn(ring, self.colors_around(self.stops[1]), "the focused stop shows nothing")
        self.assertNotIn(
            ring, self.colors_around(self.stops[2]), "every stop is ringed at once"
        )

    def test_the_ring_closes_on_all_four_sides_of_the_stop(self):
        from legion_powerctl_gui import envelope

        self.stops[1].setFocus()
        image = self.image()
        ring = self.ring_color()
        centre_x, centre_y = self.bar.x_for(self.stops[1].value()), self.bar.height() // 2
        reach = envelope.MARKER_WIDTH // 2 + envelope.HALO + envelope.RING_GAP + 1
        edge = envelope.EDGE - envelope.OVERHANG - envelope.HALO - envelope.RING_GAP
        for side, (x, y) in (
            ("left", (centre_x - reach, centre_y)),
            ("right", (centre_x + reach, centre_y)),
            ("top", (centre_x, edge)),
            ("bottom", (centre_x, self.bar.height() - 1 - edge)),
        ):
            with self.subTest(side=side):
                self.assertTrue(0 <= x < image.width() and 0 <= y < image.height(),
                                f"the {side} of the ring falls outside the widget")
                self.assertEqual(image.pixelColor(x, y).name(), ring)
        for row in (0, image.height() - 1):
            with self.subTest(row=row):
                self.assertNotEqual(image.pixelColor(centre_x, row).name(), ring)

    def test_the_marks_are_drawn_on_the_card_and_not_on_the_fills(self):
        from legion_powerctl_gui import envelope

        self.stops[1].setFocus()
        image = self.image()
        base, y = self.base().name(), self.bar.height() // 2
        halo = envelope.MARKER_WIDTH // 2 + envelope.HALO
        for stop in self.stops:
            centre = self.bar.x_for(stop.value())
            with self.subTest(stop=stop.accessibleName()):
                self.assertEqual(
                    image.pixelColor(centre + halo, y).name(), base,
                    "the marker sits straight on the fill, so its contrast is two numbers",
                )
        centre = self.bar.x_for(self.stops[1].value())
        for offset in (-(halo + 1), halo + 1):
            with self.subTest(offset=offset):
                self.assertEqual(
                    image.pixelColor(centre + offset, y).name(), base,
                    "the focus ring is drawn on a tier fill, which nothing measured it against",
                )

    def test_the_scale_ends_are_labels_on_the_card_not_text_on_the_fill(self):
        from legion_powerctl_gui import theme

        low, high = self.envelope.scale
        self.assertEqual((low.text(), high.text()), ("5 W", "200 W"))
        palette = self.envelope.palette()
        muted = theme.muted_color(palette, self.base())
        for label in self.envelope.scale:
            with self.subTest(label=label.text()):
                self.assertIn(muted.name(), label.styleSheet())
                self.assertGreaterEqual(
                    theme.contrast_ratio(muted, self.base()), theme.MIN_CONTRAST
                )

    def test_the_legend_row_lays_its_entries_out_side_by_side(self):
        entries = [spin.parentWidget() for spin in self.envelope.spins.values()]
        self.assertEqual(len({entry.x() for entry in entries}), len(entries))
        for entry in entries:
            with self.subTest(entry=entry.x()):
                self.assertGreater(entry.height(), 0, "the legend row measured itself empty")
                self.assertGreater(entry.width(), 0)

    def ring_color(self) -> str:
        from legion_powerctl_gui import theme

        return theme.fit_contrast(
            theme.focus_color(self.bar.palette()), self.base(), theme.MIN_NON_TEXT_CONTRAST
        ).name()

    def colors_around(self, stop) -> set:
        image = self.image()
        centre, y = self.bar.x_for(stop.value()), self.bar.height() // 2
        return {
            image.pixelColor(x, y).name()
            for x in range(max(0, centre - 8), min(image.width(), centre + 9))
        }

    def test_the_bar_grows_with_the_font_rather_than_clipping_it(self):
        before = self.bar.sizeHint().height()
        font = self.bar.font()
        font.setPointSize(font.pointSize() * 2)
        self.bar.setFont(font)
        self.assertGreater(self.bar.sizeHint().height(), before)
        self.assertGreaterEqual(self.bar.bar_height(), self.bar.fontMetrics().height())


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class EnvelopeInTheEditorTest(OffscreenGuiTest):
    def setUp(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        self.editor = ProfileEditor()
        self.editor.load(model.Profile(name="lab", stapm_w=60, slow_w=65, fast_w=75))

    def tearDown(self):
        self.editor.deleteLater()
        self.app.processEvents()

    def values(self):
        return [
            self.editor.stapm_spin.value(),
            self.editor.slow_spin.value(),
            self.editor.fast_spin.value(),
        ]

    def test_a_stop_pushed_past_its_neighbour_takes_the_neighbour_with_it(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.keyClick(self.editor.stapm_slider, Qt.Key.Key_End)
        self.assertEqual(self.values(), [200, 200, 200])
        QTest.keyClick(self.editor.fast_slider, Qt.Key.Key_Home)
        self.assertEqual(self.values(), [5, 5, 5])

    def test_the_stops_and_the_spin_boxes_show_the_same_number(self):
        self.editor.stapm_spin.setValue(58)
        self.assertEqual(self.editor.stapm_slider.value(), 58)
        self.editor.fast_slider.setValue(140)
        self.assertEqual(self.editor.fast_spin.value(), 140)

    def test_the_stops_say_the_constraint_the_bar_draws(self):
        for slider in (self.editor.stapm_slider, self.editor.slow_slider, self.editor.fast_slider):
            with self.subTest(stop=slider.accessibleName()):
                self.assertIn("5 to 200 watts", slider.accessibleDescription())
                self.assertIn("neighbour", slider.accessibleDescription())

    def test_the_editor_column_still_fits_a_720_pixel_window(self):
        self.assertLess(self.editor.minimumSizeHint().width(), 400)


if __name__ == "__main__":
    unittest.main()
