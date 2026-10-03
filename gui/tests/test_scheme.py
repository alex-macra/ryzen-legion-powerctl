# SPDX-License-Identifier: MIT

import contextlib
import os
import unittest
import unittest.mock

from test_app_offscreen import HAVE_PYSIDE6, OffscreenGuiTest, wait_until

SCHEME_VARIABLE = "LEGION_POWERCTL_GUI_SCHEME"


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class SchemeTestCase(OffscreenGuiTest):
    def setUp(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtGui import QPalette

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.saved_palette = QPalette(self.app.palette())
        self.saved_sheet = self.app.styleSheet()
        self.saved_style = self.app.style().name() or "fusion"
        self.addCleanup(self.restore)

    def restore(self):
        from legion_powerctl_gui import scheme
        from shiboken6 import delete

        for controller in self.app.findChildren(scheme.LegionScheme):
            delete(controller)
        self.app.setStyleSheet(self.saved_sheet)
        self.app.setStyle(self.saved_style)
        self.app.setPalette(self.saved_palette)
        self.app.processEvents()

    def start_from(self, window_hex: str, text_hex: str, style: str = "Windows"):
        from PySide6.QtGui import QColor, QPalette

        self.app.setStyle(style)
        palette = QPalette(self.app.palette())
        palette.setColor(QPalette.ColorRole.Window, QColor(window_hex))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text_hex))
        self.app.setPalette(palette)
        return QPalette(self.app.palette())

    def install(self, value):
        from legion_powerctl_gui import scheme

        environment = {} if value is None else {SCHEME_VARIABLE: value}
        with unittest.mock.patch.dict(os.environ, environment):
            if value is None:
                os.environ.pop(SCHEME_VARIABLE, None)
            return scheme.install(self.app)

    def window_colour(self, palette=None) -> str:
        from PySide6.QtGui import QPalette

        return (palette or self.app.palette()).color(QPalette.ColorRole.Window).name()


class SchemeInstallTest(SchemeTestCase):
    def test_desktop_leaves_the_style_the_palette_and_the_sheet_alone(self):
        before = self.start_from("#3a3b3c", "#fafafa")
        for value in ("desktop", "Desktop", " desktop "):
            with self.subTest(value=value):
                self.assertIsNone(self.install(value))
                self.assertEqual(self.app.style().name(), "windows")
                self.assertEqual(self.app.palette(), before)
                self.assertEqual(self.app.styleSheet(), "")

    def test_legion_is_the_default_and_brings_fusion_its_palette_and_its_sheet(self):
        from legion_powerctl_gui import scheme, styles

        for value in (None, "", "legion", "something-else"):
            with self.subTest(value=value):
                self.restore()
                self.start_from("#f0f0f0", "#101010")
                controller = self.install(value)
                self.assertIsNotNone(controller)
                light = scheme.palette(False)
                self.assertFalse(controller.dark)
                self.assertEqual(self.window_colour(), self.window_colour(light))
                self.assertEqual(self.app.styleSheet(), styles.app_qss(light))
                self.app.setStyleSheet("")
                self.assertEqual(self.app.style().name(), "fusion")

    def test_an_unknown_desktop_scheme_falls_back_to_the_palette_it_found(self):
        from legion_powerctl_gui import scheme
        from PySide6.QtCore import Qt

        self.assertEqual(self.app.styleHints().colorScheme(), Qt.ColorScheme.Unknown)
        self.start_from("#101418", "#f0f0f0")
        controller = self.install(None)
        self.assertTrue(controller.dark, "a dark desktop palette came up light")
        self.assertEqual(self.window_colour(), self.window_colour(scheme.palette(True)))

    def edges_card(self):
        from legion_powerctl_gui import fields, styles
        from PySide6.QtWidgets import QLabel, QScrollArea

        card = fields.Card("Edges")
        self.addCleanup(card.deleteLater)
        card.setStyleSheet(styles.card_style(self.app.palette()))
        spin = fields.ValueSpin()
        spin.setRange(5, 200)
        spin.setSuffix(" W")
        area = QScrollArea()
        area.setWidget(QLabel("\n".join("row" for _ in range(200))))
        area.setFixedHeight(160)
        inputs = (spin, fields.combo(("balanced", "performance")), fields.combo(("stock",), True))
        for widget in (*inputs, area):
            card.column.addWidget(widget)
        card.resize(320, 360)
        card.show()
        self.settle(5)
        focused = self.app.focusWidget()
        if focused is not None:
            focused.clearFocus()
        self.settle(3)
        return card, inputs, area.verticalScrollBar()

    def test_the_new_profile_name_field_is_framed_at_three_to_one_on_the_dialog(self):
        from legion_powerctl_gui import dialogs, theme
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QLineEdit, QWidget

        controller = self.install(None)
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        for dark in (False, True):
            controller.apply(dark)
            seen = {}

            def measure(seen=seen):
                dialog = self.app.activeModalWidget()
                field = dialog.findChild(QLineEdit)
                field.clearFocus()
                dialog.setFocus()
                self.settle(3)
                image = dialog.grab().toImage()
                corner = field.mapTo(dialog, QPoint(0, 0))
                middle = corner.y() + field.height() // 2
                plane = dialog.palette().window().color()
                edge = max(
                    (image.pixelColor(x, middle) for x in range(corner.x(), corner.x() + 3)),
                    key=lambda colour: theme.contrast_ratio(colour, plane),
                )
                seen["plane"] = theme.contrast_ratio(edge, plane)
                seen["fill"] = theme.contrast_ratio(edge, image.pixelColor(corner.x() + 8, middle))
                dialog.reject()

            QTimer.singleShot(0, measure)
            self.assertIsNone(dialogs.ask_profile_name(parent))
            for surface, ratio in seen.items():
                with self.subTest(dark=dark, against=surface):
                    self.assertGreaterEqual(ratio, theme.MIN_NON_TEXT_CONTRAST)
            self.assertEqual(len(seen), 2, "the dialog was never measured")

    def test_input_frames_and_scroll_thumbs_clear_three_to_one_as_drawn(self):
        from legion_powerctl_gui import scheme, theme
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPalette

        controller = self.install(None)
        for dark in (False, True):
            controller.apply(dark)
            palette = scheme.palette(dark)
            base = palette.color(QPalette.ColorRole.Base)
            self.assertNotEqual(
                palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text),
                palette.color(QPalette.ColorRole.Text),
            )
            card, inputs, bar = self.edges_card()
            image = card.grab().toImage()
            for widget in inputs:
                corner = widget.mapTo(card, QPoint(0, 0))
                middle = corner.y() + widget.height() // 2
                edge = max(
                    (image.pixelColor(x, middle) for x in range(corner.x(), corner.x() + 3)),
                    key=lambda colour: theme.contrast_ratio(colour, base),
                )
                with self.subTest(dark=dark, widget=type(widget).__name__):
                    self.assertGreaterEqual(
                        theme.contrast_ratio(edge, base), theme.MIN_NON_TEXT_CONTRAST,
                        f"the frame {edge.name()} fades into the card {base.name()}",
                    )
            column = bar.grab().toImage()
            x = column.width() // 2
            runs = []
            for y in range(column.height()):
                colour = column.pixelColor(x, y)
                if runs and runs[-1][0] == colour:
                    runs[-1][2] += 1
                else:
                    runs.append([colour, y, 1])
            groove, start, _length = max(runs, key=lambda run: run[2])
            outline = column.pixelColor(x, start - 1)
            with self.subTest(dark=dark, widget="scroll bar"):
                self.assertGreaterEqual(
                    theme.contrast_ratio(outline, groove), theme.MIN_NON_TEXT_CONTRAST,
                    f"the thumb's edge {outline.name()} fades into its groove {groove.name()}",
                )


class SchemeSwitchTest(SchemeTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("FAKE_CLI_LOG", None)
        self.start_from("#f0f0f0", "#101010", style="Fusion")
        self.controller = self.install(None)
        self.window = self.open_window()

    def open_window(self):
        from legion_powerctl_gui.app import MainWindow

        window = MainWindow()
        self.addCleanup(self.close_window, window)
        self.assertTrue(
            wait_until(self.app, lambda: window.refresh_count >= 1 and window.checks.count >= 1),
            f"window never loaded; errors: {list(window.errors)}",
        )
        return window

    def close_window(self, window):
        window.checks.dialog.close()
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def painted(self, window, flip=None) -> dict:
        window.resize(960, 620)
        window.show()
        window.editor.stapm_spin.setValue(window.editor.stapm_spin.value() - 1)
        window.editor._on_edited()
        window.checks.show()
        window.checks.dialog.show()
        self.settle()
        if flip is not None:
            flip()
            self.settle()
        self.assertEqual(window.editor.dirty_label.text(), "Unsaved changes")
        painted = {
            "window": window.grab().toImage(),
            "checks dialog": window.checks.dialog.grab().toImage(),
        }
        window.checks.dialog.hide()
        window.hide()
        return painted

    def switch(self, colour_scheme):
        self.app.styleHints().colorSchemeChanged.emit(colour_scheme)
        self.app.processEvents()

    def test_the_chain_names_every_region_of_the_window(self):
        regions = self.window.regions()
        for region in (
            self.window.header, self.window.sidebar, self.window.editor_column,
            self.window.editor, self.window.checks, self.window.reports,
        ):
            self.assertIn(region, regions)

    def test_a_desktop_scheme_change_repaints_every_region_in_the_new_palette(self):
        from legion_powerctl_gui import scheme, styles, theme
        from PySide6.QtCore import Qt

        for colour_scheme, dark in ((Qt.ColorScheme.Dark, True), (Qt.ColorScheme.Light, False)):
            wanted = scheme.palette(dark)
            with contextlib.ExitStack() as stack, self.subTest(dark=dark):
                spies = [
                    stack.enter_context(
                        unittest.mock.patch.object(region, "restyle", wraps=region.restyle)
                    )
                    for region in self.window.regions()
                    if hasattr(region, "restyle")
                ]
                self.assertGreaterEqual(len(spies), 4, "the chain restyles almost nothing")
                self.switch(colour_scheme)
                self.assertEqual(self.controller.dark, dark)
                self.assertEqual(self.window_colour(), self.window_colour(wanted))
                self.assertEqual(self.window_colour(self.window.palette()), self.window_colour(wanted))
                self.assertEqual(self.app.styleSheet(), styles.app_qss(wanted))
                for spy in spies:
                    self.assertTrue(spy.called, "a region kept the old palette")
                    restyled = spy.call_args[0][0]
                    self.assertEqual(self.window_colour(restyled), self.window_colour(wanted))
                palette = self.window.palette()
                self.assertIn(
                    theme.severity_color(palette, "WARN").name(),
                    self.window.header.checks_button.styleSheet(),
                )
                self.assertEqual(
                    self.window.statusBar().styleSheet(), styles.status_bar_style(palette)
                )

    def test_a_live_flip_paints_what_a_fresh_start_in_that_scheme_paints(self):
        from PySide6.QtCore import Qt

        window = self.window
        for colour_scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            flipped = self.painted(window, lambda scheme=colour_scheme: self.switch(scheme))
            window = self.open_window()
            fresh = self.painted(window)
            window = self.open_window()
            for name, image in flipped.items():
                with self.subTest(scheme=colour_scheme.name, surface=name):
                    self.assertEqual(
                        image, fresh[name], f"part of the {name} kept the scheme it flipped from"
                    )

    def test_apply_stays_outside_the_scroll_area(self):
        editor = self.window.editor
        self.assertTrue(self.window.editor_scroll.isAncestorOf(editor.stapm_spin))
        for widget in (editor.apply_button, editor.dirty_label, editor.profile_title):
            with self.subTest(widget=widget.text()):
                self.assertFalse(self.window.editor_scroll.isAncestorOf(widget))
                self.assertTrue(self.window.editor_column.isAncestorOf(widget))


class ThemeHelpersTest(OffscreenGuiTest):
    def test_a_font_role_scales_with_the_desktop_font(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QFont, QFontDatabase

        base = QFont(self.app.font())
        base.setPointSizeF(10.0)
        title = theme.font("title", base)
        self.assertAlmostEqual(title.pointSizeF(), 14.0)
        self.assertEqual(title.weight(), QFont.Weight.DemiBold)
        eyebrow = theme.font("eyebrow", base)
        self.assertEqual(eyebrow.capitalization(), QFont.Capitalization.AllUppercase)
        self.assertEqual(eyebrow.weight(), QFont.Weight.ExtraBold)
        self.assertAlmostEqual(eyebrow.letterSpacing(), 110.0)
        self.assertGreaterEqual(theme.font("eyebrow", QFont(base.family(), 8)).pointSizeF(), 7.0)
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono = theme.font("detail-mono", base)
        self.assertEqual(mono.family(), fixed.family())
        self.assertAlmostEqual(mono.pointSizeF(), 9.0)
        bigger = QFont(base)
        bigger.setPointSizeF(15.0)
        self.assertAlmostEqual(theme.font("body", bigger).pointSizeF(), 15.0)
        with self.assertRaises(KeyError):
            theme.font("headline-xl", base)

    def test_light_or_dark_comes_from_the_desktop_first_and_the_palette_second(self):
        from legion_powerctl_gui import scheme, theme
        from PySide6.QtCore import Qt

        light, dark = scheme.palette(False), scheme.palette(True)
        self.assertTrue(theme.is_dark(Qt.ColorScheme.Dark, light))
        self.assertFalse(theme.is_dark(Qt.ColorScheme.Light, dark))
        self.assertTrue(theme.is_dark(Qt.ColorScheme.Unknown, dark))
        self.assertFalse(theme.is_dark(Qt.ColorScheme.Unknown, light))

    def test_repolish_applies_a_property_the_sheet_selects_on(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QLabel

        label = QLabel("state")
        self.addCleanup(label.deleteLater)
        label.setProperty("severity", "OK")
        label.setStyleSheet(
            'QLabel[severity="OK"] { color: #00aa00; } QLabel[severity="FAIL"] { color: #aa0000; }'
        )
        label.ensurePolished()
        label.setProperty("severity", "FAIL")
        theme.repolish(label)
        self.assertEqual(label.palette().color(QPalette.ColorRole.WindowText).name(), "#aa0000")


if __name__ == "__main__":
    unittest.main()
