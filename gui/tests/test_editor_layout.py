# SPDX-License-Identifier: MIT

import os
import unittest

from test_app_offscreen import DESKTOP_POINT_SIZE, HAVE_PYSIDE6, OffscreenGuiTest, wait_until

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

    def test_at_a_large_font_the_editor_scrolls_sideways_rather_than_clipping(self):
        self.use_app_font_size(16.0)
        self.open_window()
        self.show_at(720, 480)
        self.assert_every_part_of_the_editor_can_be_reached()

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
                    room - needed, 2 * fields.VALUE_PADDING, "the box is wider than its value"
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


if __name__ == "__main__":
    unittest.main()
