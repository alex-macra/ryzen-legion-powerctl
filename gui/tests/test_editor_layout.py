# SPDX-License-Identifier: MIT

import json
import os
import unittest
from pathlib import Path

from test_app_offscreen import (
    DESKTOP_POINT_SIZE,
    HAVE_PYSIDE6,
    OffscreenGuiTest,
    VariantFixtureTest,
    wait_until,
)

CARD_NAMES = ["Power envelope", "Thermal ceiling", "CPU policy"]
LINE_EDIT_MARGIN = 2


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class EditorLayoutTest(OffscreenGuiTest):
    def setUp(self):
        os.environ.pop("FAKE_CLI_LOG", None)
        self.open_window()

    def open_window(self) -> None:
        from legion_powerctl_gui.app import MainWindow

        window = MainWindow()
        self.addCleanup(self.close_window, window)
        self.assertTrue(
            wait_until(
                self.app,
                lambda: window.refresh_count >= 1 and window.checks.count >= 1,
            ),
            f"window never loaded; errors: {list(window.errors)}",
        )
        self.window = window
        self.editor = window.editor
        self.scroll = window.editor_scroll

    def close_window(self, window):
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def show_at(self, width: int, height: int) -> None:
        self.window.resize(width, height)
        self.window.show()
        self.settle(5)

    def open_profile(self, name: str) -> None:
        self.window.sidebar.select_by_name(name)
        self.settle(3)
        self.assertEqual(self.editor.current_name, name)

    def base(self, widget) -> str:
        from PySide6.QtGui import QPalette

        return widget.palette().color(QPalette.ColorRole.Base).name()

    def test_apply_stays_on_screen_with_advanced_open_at_the_minimum_size(self):
        from PySide6.QtCore import QPoint, QRect

        self.show_at(720, 480)
        self.editor.advanced.button.setChecked(True)
        self.settle(3)
        bar = self.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "nothing overflowed, so nothing here is proven")
        button = self.editor.apply_button
        self.assertFalse(self.scroll.isAncestorOf(button), "Apply scrolls with the fields")
        places = []
        for position in (bar.minimum(), bar.maximum()):
            bar.setValue(position)
            self.app.processEvents()
            place = QRect(button.mapTo(self.window, QPoint(0, 0)), button.size())
            with self.subTest(scrolled_to=position):
                self.assertTrue(button.isVisible())
                self.assertTrue(
                    self.window.centralWidget().geometry().contains(place),
                    f"Apply at {place} is cut off by a {self.window.size()} window",
                )
                self.assertEqual(
                    button.visibleRegion().boundingRect(), button.rect(),
                    "something covers part of Apply",
                )
            places.append(place)
        self.assertEqual(places[0], places[1], "Apply moved when the fields scrolled")

    def test_the_advanced_fields_sit_in_a_card_like_the_others(self):
        from legion_powerctl_gui import theme
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAccessible

        self.show_at(960, 620)
        advanced = self.editor.advanced
        self.assertIs(advanced.property("card"), True)
        self.assertTrue(advanced.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
        for inside in (advanced.button, advanced.boost_combo, advanced.max_freq_edit):
            self.assertTrue(advanced.isAncestorOf(inside), "the disclosure left its card")
        self.assertEqual(
            QAccessible.queryAccessibleInterface(advanced.button).role(),
            QAccessible.Role.CheckBox,
        )
        hairline = theme.edge_color(self.window.palette()).name()
        for card in (advanced, *self.editor.cards):
            image = card.grab().toImage()
            with self.subTest(card=card.accessibleName() or "Advanced"):
                self.assertEqual(image.pixelColor(card.width() // 2, 0).name(), hairline)
                self.assertEqual(
                    image.pixelColor(card.width() - 6, card.height() // 2).name(),
                    self.base(card),
                    "the envelope pixels are measured against Base, so cards must be Base",
                )

    def test_the_problem_callout_shows_only_while_there_is_a_problem(self):
        from legion_powerctl_gui import theme

        self.show_at(960, 620)
        label = self.editor.problems_label
        self.assertEqual(label.text(), "")
        self.assertFalse(label.isVisible(), "an empty callout still takes a row of the editor")
        self.editor.advanced.min_freq_edit.setCurrentText("99")
        self.editor._on_edited()
        self.settle(3)
        self.assertTrue(label.isVisible(), "the problem is not on screen")
        self.assertTrue(label.text().startswith("Problem:"))
        fail = theme.severity_color(label.palette(), "FAIL").name()
        self.assertIn(fail, label.styleSheet())
        image = label.grab().toImage()
        self.assertEqual(
            image.pixelColor(1, label.height() // 2).name(), fail,
            "the callout's rail is not drawn in the FAIL colour",
        )
        self.editor.advanced.min_freq_edit.setCurrentText("unchanged")
        self.editor._on_edited()
        self.settle(3)
        self.assertFalse(label.isVisible(), "the callout outlived the problem")

    def test_the_problem_callout_ends_where_apply_ends(self):
        from legion_powerctl_gui.editor import CALLOUT_GAP
        from PySide6.QtCore import QPoint

        def right(widget) -> int:
            return widget.mapTo(self.window, QPoint(widget.width(), 0)).x()

        self.show_at(960, 620)
        label = self.editor.problems_label
        self.editor.advanced.min_freq_edit.setCurrentText("99")
        self.editor._on_edited()
        self.settle(3)
        self.assertTrue(label.isVisible(), "no problem was raised")
        self.assertEqual(right(label), right(self.editor.apply_button))
        image = label.grab().toImage()
        self.assertEqual(
            image.pixelColor(label.width() - 1, (label.height() + CALLOUT_GAP) // 2).name(),
            image.pixelColor(label.width() // 2, CALLOUT_GAP).name(),
            "the callout's edge stops short of Apply's",
        )

    def test_both_scroll_areas_show_where_the_keyboard_is(self):
        from legion_powerctl_gui import theme
        from PySide6.QtCore import Qt

        self.show_at(960, 620)
        dialog = self.window.checks.dialog
        self.window.checks.show()
        dialog.show()
        self.addCleanup(dialog.close)
        for scroll in (self.scroll, dialog.scroll):
            scroll.window().activateWindow()
            self.settle(3)
            ring = theme.focus_color(scroll.palette()).name()
            middle = scroll.height() // 2
            scroll.setFocus(Qt.FocusReason.TabFocusReason)
            self.settle(3)
            focused = scroll.grab().toImage()
            scroll.clearFocus()
            self.settle(3)
            resting = scroll.grab().toImage()
            with self.subTest(scroll=scroll.accessibleName()):
                for x in (0, 1):
                    self.assertEqual(focused.pixelColor(x, middle).name(), ring)
                    self.assertNotEqual(resting.pixelColor(x, middle).name(), ring)

    def test_the_field_being_typed_in_stays_in_view_when_the_callout_appears(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        for size in ((960, 620), (720, 480)):
            self.show_at(*size)
            self.window.activateWindow()
            self.editor.advanced.button.setChecked(True)
            self.settle(3)
            field = self.editor.advanced.max_freq_edit
            field.setFocus(Qt.FocusReason.TabFocusReason)
            self.scroll.ensureWidgetVisible(field)
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            self.settle(3)
            self.assertFalse(self.editor.problems_label.isVisible())
            field.lineEdit().selectAll()
            QTest.keyClicks(field.lineEdit(), "abc")
            self.settle(3)
            with self.subTest(size=size):
                self.assertTrue(self.editor.problems_label.isVisible(), "no problem was raised")
                self.assertTrue(field.hasFocus())
                self.assertEqual(
                    field.visibleRegion().boundingRect().height(), field.height(),
                    "the callout pushed the field being typed in out of view",
                )
            field.setCurrentText("unchanged")
            self.editor._on_edited()
            self.settle(3)

    def assert_the_callout_is_on_screen(self, case: str) -> None:
        from PySide6.QtCore import QPoint, QRect

        label = self.editor.problems_label
        footer = self.window.editor_column.footer
        place = QRect(label.mapTo(self.window, QPoint(0, 0)), label.size())
        with self.subTest(case=case):
            self.assertTrue(label.isVisible(), "the problem is not shown")
            self.assertFalse(self.editor.apply_button.isEnabled())
            self.assertFalse(self.scroll.isAncestorOf(label), "the callout scrolls with the cards")
            self.assertEqual(
                label.visibleRegion().boundingRect(), label.rect(), "part of the callout is hidden"
            )
            self.assertTrue(self.window.centralWidget().geometry().contains(place))
            self.assertLessEqual(
                place.bottom(), footer.mapTo(self.window, QPoint(0, 0)).y(),
                "the callout is not above Apply",
            )

    def test_the_reason_apply_is_off_stays_on_screen_at_960_by_620(self):
        self.show_at(960, 620)
        self.open_profile("broken")
        self.settle(3)
        self.assert_the_callout_is_on_screen("unreadable profile")
        self.open_profile("quiet")
        self.editor.advanced.button.setChecked(True)
        self.editor.advanced.min_freq_edit.setCurrentText("abc")
        self.editor._on_edited()
        self.settle(3)
        self.assert_the_callout_is_on_screen("invalid input with Advanced open")

    def assert_the_cards_fit_at_960_by_620(self) -> None:
        bar = self.scroll.verticalScrollBar()
        font = self.app.font()
        self.assertEqual(
            bar.maximum(), 0,
            f"in {font.family()} {font.pointSizeF():g} pt the editor column is "
            f"{self.window.editor_column.height()} px under a {self.window.header.height()} px "
            f"strip and its cards still scroll",
        )
        self.assertFalse(bar.isVisible(), "a scroll bar is shown with nothing to scroll")
        entries = [spin.parentWidget() for spin in self.editor.power_envelope.spins.values()]
        self.assertEqual(
            len({entry.y() for entry in entries}), 1, "the power legend wrapped onto two lines"
        )
        viewport = self.scroll.viewport()
        bottom = self.editor.advanced.mapTo(viewport, self.editor.advanced.rect().bottomLeft())
        self.assertLess(bottom.y(), viewport.height(), "the Advanced card is cut off")

    def assert_no_scroll_at_960_by_620(self) -> None:
        self.show_at(960, 620)
        self.open_profile("quiet")
        self.assertFalse(self.editor.advanced.button.isChecked())
        self.assert_the_cards_fit_at_960_by_620()
        self.show_at(720, 480)
        self.assertGreater(self.scroll.verticalScrollBar().maximum(), 0)
        self.show_at(960, 620)
        self.assert_the_cards_fit_at_960_by_620()

    def test_with_advanced_closed_the_editor_does_not_scroll_at_960_by_620(self):
        self.assert_no_scroll_at_960_by_620()

    def test_nor_does_it_scroll_at_the_kde_default_size(self):
        self.use_app_font_size(DESKTOP_POINT_SIZE)
        self.open_window()
        self.assert_no_scroll_at_960_by_620()

    def assert_every_part_of_the_editor_can_be_reached(self) -> None:
        bar = self.scroll.horizontalScrollBar()
        self.assertGreaterEqual(
            self.scroll.viewport().width() + bar.maximum(), self.editor.minimumSizeHint().width(),
            "part of the editor is cut off with no way to scroll to it",
        )
        if bar.maximum():
            self.assertTrue(bar.isVisible(), "the editor overflows with no scroll bar to reach it")

    def test_a_wide_rail_cannot_squeeze_the_editor_at_the_minimum_size(self):
        from legion_powerctl_gui.app import SIDEBAR_MAX_WIDTH

        self.show_at(720, 480)
        self.window.splitter.setSizes([SIDEBAR_MAX_WIDTH, 300])
        self.settle(3)
        self.assertEqual(
            self.scroll.horizontalScrollBar().maximum(), 0, "the rail took the editor's room"
        )
        self.assert_every_part_of_the_editor_can_be_reached()

    def test_a_scroll_bar_arriving_beside_a_squeezed_column_cannot_push_it_sideways(self):
        from legion_powerctl_gui.app import SIDEBAR_MAX_WIDTH

        self.show_at(720, 1000)
        self.window.splitter.setSizes([SIDEBAR_MAX_WIDTH, 300])
        self.settle(3)
        column, bar = self.window.editor_column, self.scroll.verticalScrollBar()
        floor = column.minimumSizeHint().width()
        self.assertEqual(column.width(), floor, "the rail did not squeeze the column to its stop")
        heights = []
        for advanced in (True, False):
            self.editor.advanced.button.setChecked(advanced)
            self.settle(3)
            heights.append(self.editor.heightForWidth(self.scroll.viewport().width()))
        opened, closed = heights
        self.show_at(720, 1000 - self.scroll.viewport().height() + (opened + closed) // 2)
        self.assertFalse(bar.isVisible(), "the closed form already scrolls, so nothing is proven")
        self.editor.advanced.button.setChecked(True)
        self.settle(5)
        self.assertTrue(bar.isVisible(), "the open form does not scroll, so nothing is proven")
        self.assertEqual(column.minimumSizeHint().width(), floor, "the bar moved the column's stop")
        self.assertEqual(
            self.scroll.horizontalScrollBar().maximum(), 0,
            "the bar's arrival left the editor wider than its viewport",
        )

    def test_a_scroll_bar_cannot_keep_itself_shown_by_wrapping_the_tiles(self):
        from legion_powerctl_gui import fields, model
        from legion_powerctl_gui.editor import SCROLLBAR_GAP, ProfileEditor
        from legion_powerctl_gui.editor_column import EditorColumn

        self.use_app_font_size(DESKTOP_POINT_SIZE)
        editor = ProfileEditor()
        column = EditorColumn(editor)
        self.addCleanup(self.close_window, column)
        editor.load(model.Profile(name="quiet"))
        column.resize(column.minimumSizeHint().width(), 1000)
        column.show()
        self.settle(3)
        envelope, bar = editor.power_envelope, column.scroll.verticalScrollBar()
        self.assertFalse(bar.isVisible())
        tiles = list(envelope.tiles.values())
        one_line = sum(tile.width() for tile in tiles) + (len(tiles) - 1) * fields.LEGEND_MIN_SPACING
        band = bar.sizeHint().width() + SCROLLBAR_GAP
        low, high = max(one_line, envelope.width()), one_line + band - 1
        self.assertLessEqual(low, high, "the column's stop keeps the tiles clear of the wrap")
        column.resize(column.width() + (low + high) // 2 - envelope.width(), 1000)
        self.settle(3)
        self.assertLessEqual(one_line, envelope.width(), "the tiles wrap even without a bar")
        self.assertGreater(one_line, envelope.width() - band, "a bar would not wrap the tiles")

        def state(height: int) -> tuple:
            column.resize(column.width(), height)
            for _ in range(4):
                self.app.processEvents()
            return bar.isVisible(), len({tile.y() for tile in tiles})

        heights = range(300, 1000, 4)
        shrinking = {height: state(height) for height in reversed(heights)}
        growing = {height: state(height) for height in heights}
        self.assertEqual(
            set(shrinking.values()), {(False, 1), (True, 2)},
            f"the sweep never crossed the wrap: {shrinking}",
        )
        self.assertEqual(
            {h: v for h, v in shrinking.items() if v != growing[h]}, {},
            "the same size settles differently depending on the way it was reached",
        )

    def test_at_a_large_font_the_editor_scrolls_sideways_rather_than_clipping(self):
        self.use_app_font_size(16.0)
        self.open_window()
        self.show_at(720, 480)
        self.assert_every_part_of_the_editor_can_be_reached()

    def test_at_a_large_font_a_squeezed_editor_shows_a_bar_only_for_real_overflow(self):
        self.use_app_font_size(14.0)
        self.open_window()
        bar = self.scroll.verticalScrollBar()
        for advanced in (False, True):
            self.editor.advanced.button.setChecked(advanced)
            for height in range(480, 820, 12):
                self.show_at(720, height)
                with self.subTest(advanced=advanced, height=height):
                    overflow = max(0, self.editor.height() - self.scroll.viewport().height())
                    self.assertEqual(bar.maximum(), overflow, "the bar's range is not the overflow")
                    if bar.isVisible():
                        self.assertGreater(bar.maximum(), 0, "a bar is shown with nothing to scroll")

    def test_a_value_box_is_as_wide_as_its_widest_value_and_no_wider(self):
        from legion_powerctl_gui import fields

        self.show_at(960, 620)
        for spin in (*self.editor.power_envelope.spins.values(), self.editor.temp_spin):
            spin.setValue(spin.maximum())
            self.app.processEvents()
            room = spin.lineEdit().contentsRect().width() - 2 * LINE_EDIT_MARGIN
            needed = spin.fontMetrics().horizontalAdvance(spin.text())
            with self.subTest(value=spin.text()):
                self.assertGreaterEqual(room, needed, "the widest value is cut off")
                self.assertLessEqual(
                    room - needed, 2 * fields.FIGURE_PADDING, "the box is wider than its value"
                )

    def test_the_cards_paint_their_eyebrow_and_keep_a_mixed_case_name(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QAccessible, QColor, QFont

        self.show_at(960, 620)
        self.assertEqual([card.accessibleName() for card in self.editor.cards], CARD_NAMES)
        for card, name in zip(self.editor.cards, CARD_NAMES):
            with self.subTest(card=name):
                self.assertEqual(card.title(), "", "a native title would add a StaticText node")
                interface = QAccessible.queryAccessibleInterface(card)
                self.assertEqual(interface.role(), QAccessible.Role.Grouping)
                self.assertEqual(interface.text(QAccessible.Text.Name), name)
                spoken = [
                    interface.child(index).text(QAccessible.Text.Name).lower()
                    for index in range(interface.childCount())
                    if interface.child(index).role() == QAccessible.Role.StaticText
                ]
                self.assertNotIn(name.lower(), spoken, "the eyebrow is read out twice")
                self.assertEqual(
                    card.eyebrow_font().capitalization(), QFont.Capitalization.AllUppercase
                )
                muted = theme.muted_color(card.palette(), QColor(self.base(card))).name()
                image = card.grab().toImage()
                rect = card.eyebrow_rect()
                inked = sum(
                    image.pixelColor(x, y).name() == muted
                    for y in range(rect.top(), rect.bottom() + 1)
                    for x in range(rect.left(), rect.right() + 1)
                )
                self.assertGreater(inked, 0, "no eyebrow was painted in the muted colour")
                first = min(child.y() for child in card.children() if child.isWidgetType())
                self.assertGreater(first, rect.bottom(), "the card's content covers its eyebrow")

    def test_the_two_bars_share_a_left_edge(self):
        from PySide6.QtCore import QPoint

        for size in ((960, 620), (720, 480)):
            self.show_at(*size)
            power, thermal = (
                envelope.bar.mapTo(self.window, QPoint(0, 0)) for envelope in self.editor.envelopes
            )
            with self.subTest(size=size):
                self.assertEqual(power.x(), thermal.x(), "the bars start at different places")

    def test_the_power_card_has_no_caption_row_and_says_the_rule_on_hover(self):
        self.show_at(960, 620)
        power = self.editor.cards[0]
        self.assertEqual(
            [child for child in power.children() if child.isWidgetType()],
            [self.editor.power_envelope], "the ordering rule still takes a row",
        )
        tip = self.editor.power_envelope.toolTip()
        self.assertIn("neighbour", tip)
        self.assertIn("≤", tip)
        first = min(child.y() for child in power.children() if child.isWidgetType())
        self.assertGreater(first, power.eyebrow_rect().bottom(), "the bar covers the eyebrow")

    def test_the_figures_in_the_editor_match_the_strip_s_figures(self):
        from legion_powerctl_gui import theme

        for size in (None, DESKTOP_POINT_SIZE):
            if size is not None:
                self.use_app_font_size(size)
                self.open_window()
            self.show_at(960, 620)
            strip = theme.font("readout", self.window.header.envelope_label.font())
            for spin in (*self.editor.power_envelope.spins.values(), self.editor.temp_spin):
                with self.subTest(size=size, spin=spin.accessibleName()):
                    self.assertEqual(spin.font().pointSizeF(), strip.pointSizeF())
        self.assertIsNone(
            self.editor.thermal_envelope.tiles["temp"].caption, "the lone ceiling grew a legend"
        )


class RunningReferenceTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"].update(
            profile="quiet", stapm_w="45", slow_w="50", fast_w="60", temp_c="78"
        )
        document["active_profile"] = "balanced-plus"

    def setUp(self):
        super().setUp()
        self.editor = self.window.editor
        self.show_at(960, 620)

    def show_at(self, width: int, height: int) -> None:
        self.window.resize(width, height)
        self.window.show()
        self.settle(5)

    def open_profile(self, name: str) -> None:
        self.window.sidebar.select_by_name(name)
        self.settle(3)
        self.assertEqual(self.editor.current_name, name)

    def record(self, **limits) -> None:
        document = json.loads(Path(self.fixture.name).read_text())
        document["last_apply"].update(limits)
        Path(self.fixture.name).write_text(json.dumps(document))
        before = self.window.refresh_count
        self.window.refresh()
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count > before))
        self.settle(3)

    @staticmethod
    def on_base(widget, derive) -> str:
        from PySide6.QtGui import QPalette

        palette = widget.palette()
        return derive(palette, palette.color(QPalette.ColorRole.Base)).name()

    def muted_in(self, card, left: int) -> int:
        from legion_powerctl_gui import theme

        image = card.grab().toImage()
        rect = card.eyebrow_rect()
        muted = self.on_base(card, theme.muted_color)
        return sum(
            image.pixelColor(x, y).name() == muted
            for y in range(max(0, rect.top() - 4), rect.bottom() + 1)
            for x in range(left, rect.right() + 1)
        )

    def test_the_envelope_cards_name_the_running_limits_beside_their_eyebrow(self):
        from PySide6.QtGui import QAccessible

        self.open_profile("quiet")
        cards = self.editor.cards
        self.assertEqual(
            [card.aside for card in cards], ["running 45/50/60 W", "running 78 °C", ""]
        )
        power = cards[0]
        right = power.eyebrow_rect().center().x()
        self.assertGreater(self.muted_in(power, right), 0, "the running limits are not painted")
        for card, name in zip(cards, CARD_NAMES):
            interface = QAccessible.queryAccessibleInterface(card)
            with self.subTest(card=name):
                self.assertEqual(interface.role(), QAccessible.Role.Grouping)
                self.assertEqual(interface.text(QAccessible.Text.Name), name)
                spoken = []
                pending = [interface.child(index) for index in range(interface.childCount())]
                while pending:
                    node = pending.pop()
                    spoken.append(node.text(QAccessible.Text.Name))
                    pending += [node.child(index) for index in range(node.childCount())]
                self.assertFalse(
                    [text for text in spoken if "running" in text],
                    "the painted aside became a node the strip already speaks for",
                )
        power.set_aside("")
        self.assertEqual(self.muted_in(power, right), 0, "something else is painted there")

    def test_the_bars_carry_the_running_limits_and_the_editor_cannot_move_them(self):
        from legion_powerctl_gui import theme

        self.open_profile("quiet")
        bar = self.editor.power_envelope.bar
        self.assertEqual(bar.reference, (45, 50, 60))
        self.assertEqual(self.editor.thermal_envelope.bar.reference, (78,))
        self.editor.stapm_spin.setValue(35)
        self.editor._on_edited()
        self.settle(3)
        self.assertTrue(self.editor.dirty)
        self.assertEqual(bar.reference, (45, 50, 60), "an edit moved the mark of what runs")
        image = bar.grab().toImage()
        self.assertEqual(
            image.pixelColor(bar.x_for(45), bar.height() - 2).name(),
            self.on_base(bar, theme.secondary_color),
        )
        self.assertEqual(
            image.pixelColor(bar.x_for(35), bar.height() // 2).name(),
            self.on_base(bar, theme.marker_color),
        )

    def test_a_new_apply_record_moves_the_marks_and_an_unchanged_one_repaints_nothing(self):
        import unittest.mock

        self.open_profile("performance-capped")
        power, thermal = self.editor.cards[:2]
        bar = self.editor.power_envelope.bar
        with unittest.mock.patch.object(bar, "update") as repaint, unittest.mock.patch.object(
            power, "update"
        ) as reword:
            self.record()
            repaint.assert_not_called()
            reword.assert_not_called()
        self.record(stapm_w="65", slow_w="70", fast_w="75", temp_c="85")
        self.assertEqual(bar.reference, (65, 70, 75))
        self.assertEqual(self.editor.thermal_envelope.bar.reference, (85,))
        self.assertEqual((power.aside, thermal.aside), ("running 65/70/75 W", "running 85 °C"))
        self.assertEqual(self.editor.title_aside.text(), "")

    def deltas(self) -> list:
        return [
            tile.delta.text()
            for envelope in self.editor.envelopes
            for tile in envelope.tiles.values()
        ]

    def test_each_tile_says_how_far_it_is_from_what_runs(self):
        self.open_profile("quiet")
        self.assertEqual(self.deltas(), ["", "", "", ""], "the running profile differs from itself")
        self.open_profile("performance-capped")
        self.assertEqual(self.deltas(), ["+20", "+20", "+15", "+7"])
        self.open_profile("quiet")
        bar = self.editor.power_envelope.bar
        self.editor.stapm_spin.setValue(35)
        self.editor._on_edited()
        self.settle(3)
        self.assertEqual(self.deltas(), ["-10", "", "", ""])
        self.assertEqual(bar.reference, (45, 50, 60), "an edit moved what the delta measures")
        self.record(stapm_w="35")
        self.assertEqual(self.editor.stapm_spin.value(), 35)
        self.assertEqual(self.deltas(), ["", "", "", ""], "the delta did not follow the apply")

    def test_an_unreadable_profile_measures_nothing_against_what_runs(self):
        self.open_profile("performance-capped")
        self.assertEqual(self.deltas(), ["+20", "+20", "+15", "+7"])
        self.open_profile("broken")
        self.assertIsNone(self.editor.editing)
        self.assertEqual(
            self.deltas(), ["", "", "", ""], "a profile with no values claims what Apply would do"
        )
        for envelope in self.editor.envelopes:
            for key, tile in envelope.tiles.items():
                with self.subTest(tile=key):
                    self.assertEqual(tile.delta.accessibleName(), "")
                    self.assertNotIn("vs running", envelope.spins[key].accessibleDescription())
        self.assertEqual(
            self.editor.power_envelope.bar.reference, (45, 50, 60), "the ticks left with the file"
        )
        self.open_profile("performance-capped")
        self.assertEqual(self.deltas(), ["+20", "+20", "+15", "+7"])

    def test_a_figure_is_described_with_its_delta_and_an_empty_delta_is_not_shown(self):
        from PySide6.QtGui import QAccessible

        editor = self.editor
        spins = (editor.stapm_spin, editor.slow_spin, editor.fast_spin, editor.temp_spin)

        def described() -> list:
            return [spin.accessibleDescription() for spin in spins]

        def hidden() -> list:
            return [
                tile.delta.isHidden()
                and QAccessible.queryAccessibleInterface(tile.delta).state().invisible
                for envelope in self.editor.envelopes
                for tile in envelope.tiles.values()
            ]

        self.open_profile("quiet")
        self.assertEqual(
            described(), ["5 to 200 watts"] * 3 + ["50 to 100 degrees Celsius"]
        )
        self.assertEqual(hidden(), [True] * 4, "an empty delta is still a node")
        self.open_profile("performance-capped")
        self.assertEqual(described(), [
            "5 to 200 watts; +20 W vs running", "5 to 200 watts; +20 W vs running",
            "5 to 200 watts; +15 W vs running", "50 to 100 degrees Celsius; +7 °C vs running",
        ])
        self.assertEqual(hidden(), [False] * 4)
        self.open_profile("balanced-plus")
        self.assertEqual(
            described()[3], "50 to 80 degrees Celsius; +2 °C vs running",
            "the capped scale dropped the delta from the description",
        )
        self.open_profile("quiet")
        self.assertEqual(
            described(), ["5 to 200 watts"] * 3 + ["50 to 100 degrees Celsius"]
        )

    def test_a_running_ceiling_above_a_capped_scale_is_named_but_not_marked(self):
        from legion_powerctl_gui import theme

        self.record(temp_c="85")
        self.open_profile("balanced-plus")
        bar = self.editor.thermal_envelope.bar
        self.assertEqual(bar.reference, (85,))
        self.assertEqual(self.editor.cards[1].aside, "running 85 °C")
        image = bar.grab().toImage()
        self.assertNotIn(
            self.on_base(bar, theme.secondary_color),
            self.colours_in_rows(image, bar.height() // 2 + 1, bar.height()),
            "a mark is drawn for a ceiling the scale cannot show",
        )
        power = self.editor.power_envelope.bar
        self.assertEqual(
            power.grab().toImage().pixelColor(power.x_for(45), power.height() - 2).name(),
            self.on_base(power, theme.secondary_color),
        )

    def baseline(self, label) -> int:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QFontMetrics

        bottom = label.height() - label.contentsMargins().bottom()
        header = self.window.editor_column.header
        return label.mapTo(header, QPoint(0, bottom)).y() - QFontMetrics(label.font()).descent()

    def test_the_title_says_how_the_profile_relates_to_the_machine(self):
        from legion_powerctl_gui.editor_column import HEADER_GAP, TITLE_HEIGHT
        from PySide6.QtCore import Qt

        title, aside = self.editor.profile_title, self.editor.title_aside
        for name, words in (
            ("quiet", "running now"), ("balanced-plus", "boot profile"), ("performance-capped", "")
        ):
            self.open_profile(name)
            with self.subTest(profile=name):
                self.assertEqual(aside.text(), words)
                self.assertEqual(aside.isVisible(), bool(words))
        for size in ((960, 620), (720, 480)):
            self.show_at(*size)
            self.open_profile("quiet")
            with self.subTest(size=size):
                header = self.window.editor_column.header
                self.assertEqual(header.height(), TITLE_HEIGHT + HEADER_GAP)
                for label in (title, aside):
                    self.assertTrue(label.alignment() & Qt.AlignmentFlag.AlignBottom)
                self.assertLessEqual(abs(self.baseline(title) - self.baseline(aside)), 1)
                self.assertEqual(aside.width(), aside.sizeHint().width(), "the aside was cut short")
                self.assertGreater(aside.x(), title.geometry().right(), "the aside covers the title")

    def test_the_title_and_its_aside_keep_one_baseline_when_either_font_changes(self):
        from PySide6.QtGui import QFont, QFontMetrics

        self.open_profile("quiet")
        title, aside = self.editor.profile_title, self.editor.title_aside
        for label in (title, aside):
            font = QFont(label.font())
            font.setPointSizeF(font.pointSizeF() * 2)
            label.setFont(font)
            self.settle(3)
            drop = QFontMetrics(title.font()).descent() - QFontMetrics(aside.font()).descent()
            with self.subTest(grown=label.text()):
                self.assertEqual(aside.contentsMargins().bottom(), max(0, drop))
                self.assertLessEqual(abs(self.baseline(title) - self.baseline(aside)), 1)

    def test_the_title_aside_is_inked_in_the_muted_colour_of_the_plane_in_both_schemes(self):
        from legion_powerctl_gui import scheme, theme
        from PySide6.QtGui import QColor, QPalette

        self.open_profile("quiet")
        aside = self.editor.title_aside
        self.addCleanup(self.app.setPalette, QPalette(self.app.palette()))
        for dark in (False, True, False):
            self.app.setPalette(scheme.palette(dark))
            self.app.setStyleSheet(self.app.styleSheet())
            self.settle(3)
            plane = self.window.palette().color(QPalette.ColorRole.Window)
            muted = theme.muted_color(self.window.palette(), plane)
            image = aside.grab().toImage()
            inks = {
                image.pixelColor(x, y).name()
                for y in range(image.height())
                for x in range(image.width())
            }
            with self.subTest(dark=dark):
                self.assertGreaterEqual(theme.contrast_ratio(muted, plane), theme.MIN_CONTRAST)
                self.assertEqual(
                    max(inks, key=lambda ink: theme.contrast_ratio(QColor(ink), plane)),
                    muted.name(),
                    "the aside is not inked in the muted colour of the plane it sits on",
                )

    def painted_aside(self, card, text: str):
        from legion_powerctl_gui import theme
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QFontMetrics, QPainter

        rect = card.eyebrow_rect()
        font = theme.font("detail-mono", card.font())
        left = rect.right() + 1 - QFontMetrics(font).horizontalAdvance(text)
        card.set_aside("")
        pixmap = card.grab()
        painter = QPainter(pixmap)
        painter.setFont(font)
        painter.setPen(QColor(self.on_base(card, theme.muted_color)))
        painter.drawText(
            QPointF(left, rect.top() + QFontMetrics(card.eyebrow_font()).ascent()), text
        )
        painter.end()
        return pixmap.toImage()

    def test_the_card_aside_ends_flush_right_on_the_eyebrow_baseline_and_elides_from_the_left(self):
        from legion_powerctl_gui import fields, styles, theme
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFontMetrics

        self.open_profile("quiet")
        power = self.editor.cards[0]
        words = power.aside
        whole = self.painted_aside(power, words)
        power.set_aside(words)
        self.assertTrue(power.grab().toImage() == whole, "the aside is off the eyebrow's line")

        chrome = power.width() - power.eyebrow_rect().width()
        eyebrow = QFontMetrics(power.eyebrow_font()).horizontalAdvance(power.eyebrow)
        mono = QFontMetrics(theme.font("detail-mono", power.font()))
        room = mono.horizontalAdvance(words) // 2
        narrow = fields.Card(power.eyebrow)
        self.addCleanup(narrow.deleteLater)
        narrow.setStyleSheet(styles.card_style(self.window.palette()))
        narrow.resize(chrome + eyebrow + fields.ASIDE_GAP + room, power.height())
        shown = mono.elidedText(words, Qt.TextElideMode.ElideLeft, room)
        self.assertTrue(shown.startswith("\u2026") and shown.endswith("60 W"), shown)
        cut = self.painted_aside(narrow, shown)
        narrow.set_aside(words)
        image = narrow.grab().toImage()
        self.assertTrue(image == cut, f"a narrow card does not read {shown!r}")
        band = image.copy(narrow.eyebrow_rect().adjusted(0, -4, 0, 0))
        self.assertEqual(
            len(self.ink_spans(band, 0, band.height(), fields.ASIDE_GAP)), 2,
            "the aside runs into the eyebrow",
        )

        narrow.resize(chrome + eyebrow, power.height())
        narrow.set_aside("")
        bare = narrow.grab().toImage()
        narrow.set_aside(words)
        self.assertTrue(narrow.grab().toImage() == bare, "an aside with no room was painted")

    def test_the_title_aside_is_one_text_node_shown_only_while_it_says_something(self):
        from PySide6.QtGui import QAccessible

        text = QAccessible.Role.StaticText
        header = self.window.editor_column.header
        for name, shown in (
            ("quiet", [(text, "quiet"), (text, "running now")]),
            ("performance-capped", [(text, "performance-capped")]),
        ):
            self.open_profile(name)
            interface = QAccessible.queryAccessibleInterface(header)
            children = [interface.child(index) for index in range(interface.childCount())]
            with self.subTest(profile=name):
                self.assertEqual(len(children), 2, "the header gained more than the aside")
                self.assertEqual(
                    [
                        (child.role(), child.text(QAccessible.Text.Name))
                        for child in children
                        if not child.state().invisible
                    ],
                    shown,
                )

    def test_the_title_aside_uses_the_words_its_row_already_speaks(self):
        from PySide6.QtCore import Qt

        for name in ("quiet", "balanced-plus"):
            self.open_profile(name)
            row = self.window.sidebar.list.currentItem()
            with self.subTest(profile=name):
                self.assertIn(
                    f", {self.editor.title_aside.text()}, ",
                    row.data(Qt.ItemDataRole.AccessibleTextRole),
                )

    def test_a_long_title_cuts_the_aside_short_before_it_widens_the_header(self):
        from legion_powerctl_gui.editor_column import TITLE_GAP
        from legion_powerctl_gui.fields import Aside
        from PySide6.QtCore import Qt

        self.show_at(720, 480)
        self.open_profile("quiet")
        title, aside = self.editor.profile_title, self.editor.title_aside
        header = self.window.editor_column.header
        room = header.width() - TITLE_GAP - aside.sizeHint().width() // 2
        name = "quiet-"
        while title.fontMetrics().horizontalAdvance(f"{name}q") < room:
            name += "q"
        title.setText(name)
        self.settle(3)
        self.assertEqual(title.width(), title.sizeHint().width(), "the title gave way first")
        self.assertEqual(
            header.minimumSizeHint().width(), title.minimumSizeHint().width() + TITLE_GAP,
            "the aside raised the width the header needs",
        )
        self.assertGreater(aside.width(), 0)
        self.assertLess(aside.width(), aside.sizeHint().width(), "the aside still fits whole")
        shown = aside.fontMetrics().elidedText(
            aside.text(), Qt.TextElideMode.ElideRight, aside.contentsRect().width()
        )
        twin = Aside(shown, aside.parentWidget())
        self.addCleanup(twin.deleteLater)
        twin.setFont(aside.font())
        twin.setStyleSheet(aside.styleSheet())
        twin.setAlignment(aside.alignment())
        twin.setContentsMargins(aside.contentsMargins())
        twin.setGeometry(aside.geometry())
        twin.show()
        self.assertNotEqual(shown, aside.text())
        self.assertTrue(
            twin.grab().toImage() == aside.grab().toImage(),
            f"{aside.text()!r} is clipped at its edge instead of reading {shown!r}",
        )
        twin.hide()



class NoBootPinVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"] = None
        document["active_profile"] = ""

    def test_a_cleared_editor_claims_neither_running_nor_booting(self):
        editor = self.window.editor
        self.assertTrue(wait_until(self.app, lambda: self.window.checks.count >= 1))
        editor.clear()
        self.settle(3)
        self.assertEqual(editor.current_name, "")
        self.assertEqual(editor.title_aside.text(), "")
        self.assertTrue(editor.title_aside.isHidden())

    def test_a_cleared_editor_takes_the_edited_mark_with_the_edits(self):
        editor = self.window.editor
        self.assertTrue(wait_until(self.app, lambda: self.window.checks.count >= 1))
        editor.stapm_spin.setValue(52)
        editor._on_edited()
        self.assertEqual(editor.title_aside.text(), "edited")
        editor.clear()
        self.settle(3)
        self.assertEqual(editor.title_aside.text(), "", "the title claims edits to nothing at all")
        self.assertTrue(editor.title_aside.isHidden())


if __name__ == "__main__":
    unittest.main()
