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

    def test_a_narrow_legend_wraps_onto_a_second_line(self):
        from legion_powerctl_gui import fields

        entries = [spin.parentWidget() for spin in self.envelope.spins.values()]
        one_line = self.envelope.height()
        self.host.resize(sum(entry.width() for entry in entries[:2]) + 60, 220)
        self.app.processEvents()
        rows = sorted({entry.y() for entry in entries})
        self.assertEqual(len(rows), 2, f"the legend did not wrap to two lines: {rows}")
        self.assertEqual(entries[2].x(), entries[0].x(), "the wrapped entry is not left aligned")
        self.assertEqual(rows[1] - rows[0], entries[0].height() + fields.LEGEND_LINE_SPACING)
        self.assertGreater(self.envelope.height(), one_line, "the wrapped line overlaps the bar")

    def test_a_legend_just_short_of_room_closes_its_gaps_before_it_wraps(self):
        from legion_powerctl_gui import fields

        entries = [spin.parentWidget() for spin in self.envelope.spins.values()]
        margins = self.host.layout().contentsMargins()
        tight = sum(entry.width() for entry in entries) + 2 * fields.LEGEND_MIN_SPACING
        for room, lines in ((tight + 4, 1), (tight - 1, 2)):
            self.host.resize(room + margins.left() + margins.right(), 220)
            self.app.processEvents()
            with self.subTest(room=room):
                self.assertEqual(self.envelope.width(), room)
                self.assertEqual(len({entry.y() for entry in entries}), lines)
        self.host.resize(tight + 4 + margins.left() + margins.right(), 220)
        self.app.processEvents()
        gaps = [after.x() - before.x() - before.width() for before, after in zip(entries, entries[1:])]
        for gap in gaps:
            self.assertGreaterEqual(gap, fields.LEGEND_MIN_SPACING)
            self.assertLess(gap, fields.LEGEND_SPACING)

    def secondary(self) -> str:
        from legion_powerctl_gui import theme

        return theme.secondary_color(self.bar.palette(), self.base()).name()

    def test_a_reference_mark_hangs_under_the_bar_at_the_running_value(self):
        from legion_powerctl_gui import theme

        self.envelope.set_reference((60, 90, 150))
        self.assertEqual(self.bar.reference, (60, 90, 150))
        image = self.image()
        x, height = self.bar.x_for(90), self.bar.height()
        empty = image.pixelColor(x, 0).name()
        tier = theme.tier_color(self.bar.palette(), self.base(), theme.tier_step(1)).name()
        self.assertEqual(
            image.pixelColor(x, height - 2).name(), self.secondary(), "no mark at the running value"
        )
        self.assertEqual(image.pixelColor(x, height // 2).name(), tier, "the mark is on the fill")
        self.assertEqual(
            image.pixelColor(x, height - 1).name(), empty, "the mark spills out of the bar's margin"
        )
        self.envelope.set_reference(None)
        self.assertEqual(self.bar.reference, ())
        self.assertEqual(
            self.image().pixelColor(x, height - 2).name(), empty, "the mark outlived its reference"
        )

    def test_a_reference_under_a_stop_keeps_the_plate_and_the_ring(self):
        self.envelope.set_reference((60, 120, 150))
        self.test_the_ring_closes_on_all_four_sides_of_the_stop()
        self.test_the_marks_are_drawn_on_the_card_and_not_on_the_fills()
        self.test_the_fills_step_down_from_the_sustained_tier_outwards()
        self.stops[1].setFocus()
        image = self.image()
        for stop in (self.stops[0], self.stops[2]):
            with self.subTest(foot=stop.accessibleName()):
                self.assertEqual(
                    image.pixelColor(self.bar.x_for(stop.value()), self.bar.height() - 2).name(),
                    self.secondary(), "the stop hides the mark it sits on",
                )

    def test_a_reference_mark_is_a_foot_wider_than_the_plate_of_a_stop(self):
        from legion_powerctl_gui import envelope

        bare = self.image()
        self.envelope.set_reference((90,))
        image = self.image()
        x, row = self.bar.x_for(90), self.bar.height() - 2
        half = envelope.TICK_WIDTH // 2
        inked = [
            column for column in range(image.width())
            if image.pixel(column, row) != bare.pixel(column, row)
        ]
        self.assertEqual(inked, list(range(x - half, x + half + 1)))
        self.assertGreater(
            len(inked), envelope.MARKER_WIDTH + 2 * envelope.HALO,
            "a foot no wider than the plate reads as the stem running on",
        )

    def test_running_limits_that_coincide_draw_one_mark_not_a_heavier_one(self):
        self.envelope.set_reference((90,))
        single = self.image()
        self.envelope.set_reference((90, 90, 90))
        self.assertEqual(self.bar.reference, (90, 90, 90))
        self.assertTrue(self.image() == single, "coincident limits darken the mark they share")

    def mark_ink(self, value: int) -> float:
        from legion_powerctl_gui import envelope

        self.envelope.set_reference(())
        bare = self.image()
        self.envelope.set_reference((value,))
        image = self.image()
        x, reach = self.bar.x_for(value), envelope.TICK_WIDTH // 2 + 1
        return sum(
            abs(image.pixelColor(column, y).lightnessF() - bare.pixelColor(column, y).lightnessF())
            for y in range(self.bar.height() - envelope.EDGE, self.bar.height())
            for column in range(x - reach, x + reach + 1)
        )

    def test_a_focused_stop_leaves_the_running_mark_it_is_nudged_around_in_sight(self):
        from legion_powerctl_gui import envelope

        free = self.mark_ink(90)
        stop = self.stops[1]
        stop.setFocus()
        ring_row = self.bar.height() - 1 - (
            envelope.EDGE - envelope.OVERHANG - envelope.HALO - envelope.RING_GAP
        )
        for nudge in (-1, 0, 1):
            with self.subTest(nudge=nudge):
                self.assertGreater(
                    self.mark_ink(stop.value() + nudge), free / 4,
                    "the focused stop wipes the running mark under its ring",
                )
                self.assertTrue(stop.hasFocus())
                self.assertEqual(
                    self.image().pixelColor(self.bar.x_for(stop.value()), ring_row).name(),
                    self.ring_color(),
                )

    def test_a_reference_beyond_the_scale_is_not_drawn(self):
        from legion_powerctl_gui import envelope

        bare = self.image()
        self.envelope.set_reference((LOW - 1, HIGH + 50))
        self.assertEqual(self.bar.reference, (LOW - 1, HIGH + 50))
        image = self.image()
        rows = envelope.TICK_GAP + envelope.TICK_HEIGHT + 1
        height = image.height()
        self.assertNotIn(self.secondary(), self.colours_in_rows(image, height - rows, height))
        self.assertTrue(image == bare, "a reference off the scale left a mark")
        self.envelope.set_reference((HIGH,))
        self.assertEqual(
            self.image().pixelColor(self.bar.x_for(HIGH), height - 2).name(), self.secondary(),
            "the end of the scale is still on it",
        )

    def test_an_unchanged_reference_does_not_repaint_the_bar(self):
        import unittest.mock

        self.envelope.set_reference([60, 120])
        with unittest.mock.patch.object(self.bar, "update") as update:
            self.envelope.set_reference((60, 120))
            update.assert_not_called()
            self.envelope.set_reference((60,))
            update.assert_called_once_with()

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

    def set_figures(self, *values):
        for spin, value in zip(self.envelope.spins.values(), values):
            spin.setValue(value)
        self.app.processEvents()

    @staticmethod
    def dominant(image) -> str:
        from collections import Counter

        return Counter(
            image.pixelColor(x, y).name() for y in range(image.height()) for x in range(image.width())
        ).most_common(1)[0][0]

    def inked_rows(self, widget) -> list:
        image = widget.grab().toImage()
        plane = self.dominant(image)
        rows = [
            y for y in range(image.height())
            if any(image.pixelColor(x, y).name() != plane for x in range(image.width()))
        ]
        self.assertTrue(rows, f"{widget.metaObject().className()} painted nothing")
        return rows

    def last_inked_row(self, widget) -> int:
        return widget.y() + self.inked_rows(widget)[-1]

    def test_the_figures_are_the_spins_set_in_the_readout_voice(self):
        from legion_powerctl_gui import theme, tiles
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QAbstractSpinBox, QSpinBox

        self.set_figures(60, 120, 150)
        for spin in self.envelope.spins.values():
            with self.subTest(spin=spin.accessibleName()):
                self.assertIsInstance(spin, QSpinBox)
                self.assertEqual(spin.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.NoButtons)
                self.assertFalse(spin.hasFrame(), "the figure is boxed like a form field")
                self.assertEqual(spin.font().pointSizeF(), theme.font("readout").pointSizeF())
                self.assertEqual(spin.height(), spin.figure_top() + 2 * tiles.FIGURE_V_PAD)
                before = spin.value()
                QTest.keyClick(spin, Qt.Key.Key_Up)
                self.assertEqual(spin.value(), before + 1, "the arrow key no longer steps the figure")

    def test_a_tile_names_its_limit_in_the_strip_s_words_and_wears_its_tier_swatch(self):
        from legion_powerctl_gui import theme
        from legion_powerctl_gui.envelope import Envelope
        from PySide6.QtGui import QFont

        tiles = list(self.envelope.tiles.values())
        self.assertEqual([tile.caption.text() for tile in tiles], [label for _key, label in TIERS])
        palette, base = self.bar.palette(), self.base()
        eyebrow = theme.font("eyebrow")
        for index, tile in enumerate(tiles):
            image = tile.grab().toImage()
            swatch = tile.swatch.geometry().center()
            with self.subTest(tile=tile.caption.text()):
                font = tile.caption.font()
                self.assertEqual(font.capitalization(), QFont.Capitalization.AllUppercase)
                self.assertEqual(font.pointSizeF(), eyebrow.pointSizeF())
                self.assertEqual(
                    image.pixelColor(swatch).name(),
                    theme.tier_color(palette, base, theme.tier_step(index)).name(),
                )
                for below in (tile.swatch, tile.caption):
                    self.assertGreater(below.y(), tile.spin.geometry().bottom())
        named = Envelope(TIERS, LOW, HIGH, " W", "watts", captions=("Sustained", "Slow", "Fast"))
        self.addCleanup(named.deleteLater)
        self.assertEqual(
            [tile.caption.text() for tile in named.tiles.values()], ["Sustained", "Slow", "Fast"]
        )
        self.assertEqual(
            [stop.accessibleName() for stop in named.stops.values()],
            [label for _key, label in TIERS], "the caption renamed the control",
        )
        single = Envelope(TIERS[:1], LOW, HIGH, " W", "watts", captions=("Sustained",))
        self.addCleanup(single.deleteLater)
        self.assertIsNone(single.tiles["stapm"].caption, "a lone figure grew a legend")
        self.assertIsNone(single.tiles["stapm"].swatch)

    def test_a_delta_is_shown_only_against_a_reference_and_only_when_it_differs(self):
        tiles = self.envelope.tiles
        widths = []

        def deltas():
            self.app.processEvents()
            widths.append([tile.width() for tile in tiles.values()])
            return [tile.delta.text() for tile in tiles.values()]

        self.set_figures(60, 120, 150)
        self.envelope.set_reference((60, 120, 150))
        self.assertEqual(deltas(), ["", "", ""], "a figure equal to what runs shows a change")
        self.envelope.spins["slow"].setValue(137)
        self.assertEqual(deltas(), ["", "+17", ""])
        self.assertEqual(
            [tile.delta.isVisibleTo(tile) for tile in tiles.values()], [False, True, False]
        )
        self.assertEqual(tiles["slow"].delta.accessibleName(), "+17 W vs running")
        self.envelope.spins["slow"].setValue(100)
        self.assertEqual(deltas(), ["", "-20", ""])
        self.assertEqual(tiles["slow"].delta.accessibleName(), "-20 W vs running")
        self.envelope.set_reference((60, 120, 150), measured=False)
        self.assertEqual(deltas(), ["", "", ""], "a figure that cannot be applied claims a change")
        self.assertEqual(self.bar.reference, (60, 120, 150), "the ticks went with the deltas")
        self.envelope.set_reference((60, 120, 150))
        self.assertEqual(deltas(), ["", "-20", ""])
        self.envelope.set_reference(None)
        self.assertEqual(deltas(), ["", "", ""], "a delta outlived the reference it measured")
        self.assertEqual(tiles["slow"].delta.accessibleName(), "")
        self.assertEqual(len({tuple(row) for row in widths}), 1, f"a delta moved its tile: {widths}")

    def test_a_figure_is_described_by_its_scale_and_its_delta(self):
        self.set_figures(60, 120, 150)
        self.envelope.set_reference((60, 120, 150))
        self.envelope.spins["slow"].setValue(137)
        self.envelope.set_high(150)

        def described() -> list:
            return [spin.accessibleDescription() for spin in self.envelope.spins.values()]

        self.assertEqual(
            described(), ["5 to 150 watts", "5 to 150 watts; +17 W vs running", "5 to 150 watts"],
            "a new scale dropped the delta, or a delta kept the old scale",
        )
        self.assertEqual(
            [stop.accessibleDescription() for stop in self.stops], ["5 to 150 watts"] * 3
        )
        self.envelope.set_reference(None)
        self.assertEqual(described(), ["5 to 150 watts"] * 3)

    def test_the_delta_sits_on_the_figure_s_baseline(self):
        self.set_figures(62, 120, 150)
        self.envelope.set_reference((45, 120, 150))
        tile = self.envelope.tiles["stapm"]
        self.assertEqual(tile.delta.text(), "+17")
        for grown in (False, True):
            if grown:
                font = tile.spin.font()
                font.setPointSizeF(font.pointSizeF() * 1.5)
                tile.spin.setFont(font)
                self.settle(3)
            figure, delta = self.last_inked_row(tile.spin), self.last_inked_row(tile.delta)
            with self.subTest(grown=grown):
                self.assertEqual(tile.delta.height(), tile.spin.height())
                self.assertLessEqual(
                    abs(figure - delta), 1, f"the figure ends on row {figure} and its delta on {delta}"
                )
                self.assertLess(
                    delta - tile.delta.y(), tile.delta.height() - 1,
                    "the delta is inked down to its last row, so its foot may be cut off",
                )

    def test_a_figure_shows_a_rule_at_rest_and_a_ring_when_it_has_the_keyboard(self):
        import unittest.mock

        from legion_powerctl_gui import theme, tiles
        from PySide6.QtGui import QPalette

        tile = self.envelope.tiles["slow"]
        spin, box = tile.spin, tile.spin.geometry()
        palette = tile.palette()
        base = palette.color(QPalette.ColorRole.Base)
        ring = theme.fit_contrast(
            theme.focus_color(palette), base, theme.MIN_NON_TEXT_CONTRAST
        ).name()
        rule = theme.edge_strong_color(palette, base).name()
        centre = box.center()
        band = box.adjusted(-tiles.RING_SPACE, -tiles.RING_SPACE, tiles.RING_SPACE, tiles.RING_SPACE)

        def at_rest():
            image = tile.grab().toImage()
            self.assertEqual(image.pixelColor(centre.x(), box.bottom() + 2).name(), rule)
            self.assertNotIn(ring, {
                image.pixelColor(x, y).name()
                for y in range(band.top(), band.bottom() + 1)
                for x in range(band.left(), band.right() + 1)
                if not box.contains(x, y)
            }, "a figure without the keyboard is ringed")

        at_rest()
        with unittest.mock.patch.object(tile, "update") as repaint:
            spin.setFocus()
            self.app.processEvents()
            repaint.assert_called_with()
        self.assertTrue(spin.hasFocus())
        image = tile.grab().toImage()
        for side, (x, y) in (
            ("top", (centre.x(), box.top() - 2)),
            ("bottom", (centre.x(), box.bottom() + 2)),
            ("left", (box.left() - 2, centre.y())),
            ("right", (box.right() + 2, centre.y())),
        ):
            with self.subTest(side=side):
                self.assertEqual(image.pixelColor(x, y).name(), ring)
        with unittest.mock.patch.object(tile, "update") as repaint:
            spin.clearFocus()
            self.app.processEvents()
            repaint.assert_called_with()
        at_rest()

    def test_a_disabled_figure_keeps_the_card_surface_behind_it(self):
        from legion_powerctl_gui import scheme, theme
        from PySide6.QtGui import QPalette
        from shiboken6 import delete

        self.addCleanup(self.app.setPalette, QPalette(self.app.palette()))
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        controller = scheme.LegionScheme(self.app, QPalette(self.app.palette()))
        self.addCleanup(delete, controller)
        self.set_figures(60, 120, 150)
        for spin in self.envelope.spins.values():
            spin.setEnabled(False)
        for dark in (False, True):
            controller.apply(dark)
            self.envelope.restyle(self.app.palette())
            self.app.processEvents()
            base = self.app.palette().color(QPalette.ColorRole.Base)
            for key, tile in self.envelope.tiles.items():
                box = tile.spin.geometry()
                with self.subTest(dark=dark, tile=key):
                    self.assertEqual(
                        self.dominant(tile.spin.grab().toImage()), base.name(),
                        "a figure that cannot be edited sits in a grey well",
                    )
                    self.assertEqual(
                        tile.grab().toImage().pixelColor(box.center().x(), box.bottom() + 2).name(),
                        theme.edge_color(tile.palette()).name(),
                    )

    def test_both_scale_labels_share_one_gutter(self):
        from legion_powerctl_gui import fields, theme
        from legion_powerctl_gui.envelope import Envelope
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QFontMetrics

        gutter = QFontMetrics(theme.font("detail-mono")).horizontalAdvance(fields.SCALE_TEMPLATE)
        low, high = self.envelope.scale
        for label in (low, high):
            with self.subTest(label=label.text()):
                self.assertEqual(label.minimumWidth(), gutter)
        self.assertTrue(low.alignment() & Qt.AlignmentFlag.AlignRight, "the low end is not flush")
        self.assertTrue(high.alignment() & Qt.AlignmentFlag.AlignLeft)
        thermal = Envelope(
            (("temp", "Temperature ceiling"),), 50, 100, " °C", "degrees Celsius"
        )
        thermal.restyle(self.app.palette())
        self.host.layout().addWidget(thermal)
        self.app.processEvents()
        self.assertEqual(
            thermal.bar.mapTo(self.host, QPoint(0, 0)).x(),
            self.bar.mapTo(self.host, QPoint(0, 0)).x(),
            "the two bars start at different places",
        )


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
