# SPDX-License-Identifier: MIT

import os
import unittest

import test_theme
from test_app_offscreen import DESKTOP_POINT_SIZE, HAVE_PYSIDE6, OffscreenGuiTest, wait_until

WIDTH = 262
HEIGHT = 52


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class RailTestCase(OffscreenGuiTest):
    def setUp(self):
        from legion_powerctl_gui import model, scheme
        from legion_powerctl_gui.sidebar import ProfileList

        self.light = scheme.palette(False)
        self.dark = scheme.palette(True)
        self.sidebar = ProfileList()
        self.addCleanup(self.close_sidebar)
        self.use(self.light)
        self.sidebar.resize(WIDTH + 2, 420)
        self.sidebar.show()
        profiles = [
            model.Profile(name="quiet", stapm_w=45, slow_w=50, fast_w=60, temp_c=78),
            model.Profile(name="balanced-plus", stapm_w=87, slow_w=92, fast_w=102, temp_c=80),
            model.Profile(name="broken", valid=False),
        ]
        self.sidebar.set_profiles(profiles, boot="balanced-plus", select="", running="quiet")
        self.app.processEvents()

    def use(self, palette):
        sidebar = self.sidebar
        for widget in (sidebar, sidebar.header, sidebar.list, sidebar.list.viewport()):
            widget.setPalette(palette)
        sidebar.restyle(palette)
        self.app.processEvents()

    def close_sidebar(self):
        self.sidebar.close()
        self.sidebar.deleteLater()
        self.app.processEvents()

    def index(self, name):
        model = self.sidebar.list.model()
        for row in range(model.rowCount()):
            if self.sidebar.list.item(row).text() == name:
                return model.index(row, 0)
        raise AssertionError(f"{name} is not in the rail")

    def state(self, *flags):
        from PySide6.QtWidgets import QStyle

        result = QStyle.StateFlag.State_Enabled
        for flag in flags:
            result |= getattr(QStyle.StateFlag, f"State_{flag}")
        return result

    def option(self, palette=None, state=None, font=None):
        from legion_powerctl_gui.profile_delegate import ICON_SIZE
        from PySide6.QtCore import QRect, QSize
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QStyleOptionViewItem

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, WIDTH, HEIGHT)
        option.state = self.state() if state is None else state
        option.palette = QPalette(palette or self.light)
        option.font = font or self.app.font()
        option.decorationSize = QSize(ICON_SIZE, ICON_SIZE)
        return option

    def paint(self, name, palette=None, state=None):
        from PySide6.QtGui import QColor, QImage, QPainter

        option = self.option(palette, state)
        image = QImage(option.rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("magenta"))
        painter = QPainter(image)
        self.sidebar.delegate.paint(painter, option, self.index(name))
        painter.end()
        return image

    @staticmethod
    def colour(image, x, y):
        from PySide6.QtGui import QColor

        return QColor(image.pixel(x, y))

    @staticmethod
    def role(name):
        from PySide6.QtGui import QPalette

        return getattr(QPalette.ColorRole, name)


class RowGeometryTest(RailTestCase):
    def test_a_row_is_52_tall(self):
        from legion_powerctl_gui.profile_delegate import ROW_HEIGHT

        self.assertEqual(ROW_HEIGHT, 52)
        for row in range(self.sidebar.list.count()):
            item = self.sidebar.list.item(row)
            with self.subTest(row=item.text()):
                self.assertEqual(self.sidebar.list.visualItemRect(item).height(), 52)

    def test_a_row_grows_with_the_font_rather_than_clipping_it(self):
        from PySide6.QtGui import QFont

        font = QFont(self.app.font())
        font.setPointSizeF(24.0)
        self.sidebar.list.setFont(font)
        self.app.processEvents()
        item = self.sidebar.list.item(0)
        self.assertGreater(self.sidebar.list.visualItemRect(item).height(), 52)

    def test_the_rail_is_one_card_with_its_buttons_in_the_footer(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame

        sidebar = self.sidebar
        self.assertTrue(sidebar.property("card"))
        self.assertTrue(sidebar.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
        self.assertEqual(sidebar.list.frameShape(), QFrame.Shape.NoFrame)
        self.assertTrue(sidebar.footer.isAncestorOf(sidebar.new_button))
        self.assertTrue(sidebar.footer.isAncestorOf(sidebar.delete_button))
        self.assertGreaterEqual(sidebar.footer.height(), 44)
        self.assertEqual(sidebar.header.height(), 36)
        self.assertLess(sidebar.header.geometry().bottom(), sidebar.list.geometry().top())
        self.assertLess(sidebar.list.geometry().bottom(), sidebar.footer.geometry().top())

    def test_the_tab_chain_through_the_rail_is_the_list_then_the_two_buttons(self):
        from PySide6.QtCore import Qt

        sidebar = self.sidebar
        chain, widget = [], sidebar.list
        for _ in range(12):
            if widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
                chain.append(widget)
            widget = widget.nextInFocusChain()
        self.assertEqual(chain[:3], [sidebar.list, sidebar.new_button, sidebar.delete_button])


class RowPaintTest(RailTestCase):
    def test_nothing_is_painted_between_the_rail_and_the_text(self):
        for name in ("quiet", "balanced-plus", "broken"):
            for flags in ((), ("Selected",)):
                image = self.paint(name, state=self.state(*flags))
                background = image.pixel(20, 3)
                for x in range(4, 14):
                    for y in range(4, 48):
                        self.assertEqual(
                            image.pixel(x, y), background,
                            f"{name} {flags} paints a marker at {x},{y}",
                        )

    def test_a_theme_icon_is_drawn_in_the_secondary_ink_on_the_name_line_before_the_watts(self):
        from legion_powerctl_gui import theme
        from legion_powerctl_gui.profile_delegate import GAP, ICON_SIZE, RowLines
        from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPixmap

        pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
        pixmap.fill(QColor("black"))
        self.sidebar.list.item(1).setIcon(QIcon(pixmap))
        image = self.paint("balanced-plus")
        lines = RowLines(self.option())
        right = lines.right - QFontMetrics(lines.detail_font).horizontalAdvance("87 W") - GAP
        middle = lines.name_top + lines.name_height // 2
        base = self.light.color(self.role("Base"))
        ink = theme.secondary_color(self.light, base).rgb()
        self.assertEqual(image.pixel(right - 1, middle), ink)
        self.assertEqual(image.pixel(right - ICON_SIZE, middle), ink)
        self.assertEqual(image.pixel(right, middle), base.rgb())
        self.assertEqual(image.pixel(right - ICON_SIZE - 1, middle), base.rgb())
        self.assertNotEqual(image.pixel(right - ICON_SIZE // 2, lines.detail_top + 1), ink)

    def test_the_selected_row_is_a_twelve_percent_accent_tint(self):
        from legion_powerctl_gui import theme

        for label, palette in (("light", self.light), ("dark", self.dark)):
            image = self.paint("balanced-plus", palette, self.state("Selected"))
            with self.subTest(scheme=label):
                self.assertEqual(image.pixel(20, 3), theme.selection_color(palette).rgb())

    def test_a_hovered_row_is_a_faint_ink_tint_and_selection_wins_over_it(self):
        from legion_powerctl_gui import theme

        base = self.light.color(self.role("Base"))
        ink = self.light.color(self.role("Text"))
        image = self.paint("balanced-plus", state=self.state("MouseOver"))
        self.assertEqual(image.pixel(20, 3), theme.tint_color(base, ink, 0.04).rgb())
        image = self.paint("balanced-plus", state=self.state("MouseOver", "Selected"))
        self.assertEqual(image.pixel(20, 3), theme.selection_color(self.light).rgb())

    def test_the_running_rail_is_the_accent_on_a_plain_row_and_only_there(self):
        from legion_powerctl_gui import theme

        accent = theme.accent_color(self.light).rgb()
        image = self.paint("quiet")
        self.assertEqual(image.pixel(1, 26), accent)
        image = self.paint("balanced-plus")
        self.assertNotEqual(image.pixel(1, 26), accent)

    def test_the_rail_is_inset_from_the_top_and_bottom_of_its_row(self):
        from legion_powerctl_gui import theme

        image = self.paint("quiet")
        accent = theme.accent_color(self.light).rgb()
        self.assertNotEqual(image.pixel(1, 2), accent)
        self.assertEqual(image.pixel(1, 12), accent)
        self.assertEqual(image.pixel(1, 40), accent)
        self.assertNotEqual(image.pixel(1, 50), accent)
        self.assertNotEqual(image.pixel(4, 26), accent)

    def test_the_rail_keeps_three_to_one_against_the_selection_tint_on_every_palette(self):
        from legion_powerctl_gui import theme

        palettes = {"legion light": self.light, "legion dark": self.dark}
        for name, (window, text, base) in test_theme.PALETTES.items():
            palettes[name] = test_theme.SeverityContrastTest.palette(window, text, base)
        for name, palette in palettes.items():
            image = self.paint("quiet", palette, self.state("Selected"))
            tint = self.colour(image, 20, 3)
            rail = self.colour(image, 1, 26)
            with self.subTest(palette=name):
                self.assertEqual(tint.rgb(), theme.selection_color(palette).rgb())
                self.assertGreaterEqual(
                    theme.contrast_ratio(rail, tint), theme.MIN_NON_TEXT_CONTRAST,
                    f"the running rail {rail.name()} vanishes on the selection {tint.name()}",
                )

    def test_the_separator_is_inset_on_both_sides_and_painted_in_the_hairline(self):
        from legion_powerctl_gui import theme

        image = self.paint("balanced-plus")
        bottom = HEIGHT - 1
        hairline = theme.edge_color(self.light).rgb()
        base = self.light.color(self.role("Base")).rgb()
        self.assertEqual(image.pixel(14, bottom), base)
        self.assertEqual(image.pixel(15, bottom), hairline)
        self.assertEqual(image.pixel(WIDTH - 17, bottom), hairline)
        self.assertEqual(image.pixel(WIDTH - 16, bottom), base)

    def test_the_watts_sit_on_the_right_margin(self):
        image = self.paint("balanced-plus")
        base = self.light.color(self.role("Base")).rgb()
        ink = [
            x for x in range(WIDTH)
            if any(image.pixel(x, y) != base for y in range(9, 27))
        ]
        self.assertLessEqual(max(ink), WIDTH - 16)
        self.assertGreaterEqual(max(ink), WIDTH - 20)

    def test_an_invalid_profile_shows_no_watts_and_no_pin_even_when_hovered(self):
        image = self.paint("broken", state=self.state("MouseOver"))
        hover = image.pixel(20, 3)
        for x in range(WIDTH - 80, WIDTH - 16):
            for y in range(4, 48):
                self.assertEqual(image.pixel(x, y), hover, f"ink at {x},{y}")

    def test_a_focused_row_draws_a_two_pixel_ring_inset_two(self):
        from legion_powerctl_gui import theme

        image = self.paint("balanced-plus", state=self.state("HasFocus"))
        base = self.light.color(self.role("Base"))
        ring = theme.fit_contrast(
            theme.focus_color(self.light), base, theme.MIN_NON_TEXT_CONTRAST
        )
        middle = WIDTH // 2
        self.assertEqual(image.pixel(middle, 1), base.rgb())
        self.assertEqual(image.pixel(middle, 2), ring.rgb())
        self.assertEqual(image.pixel(middle, 3), ring.rgb())
        self.assertEqual(image.pixel(middle, 4), base.rgb())

    def test_a_disabled_rail_paints_every_word_in_the_disabled_ink(self):
        from legion_powerctl_gui import theme
        from PySide6.QtWidgets import QStyle

        image = self.paint("balanced-plus", state=QStyle.StateFlag.State_None)
        base = self.light.color(self.role("Base"))
        disabled = theme.disabled_text_color(self.light).rgb()
        ink = theme.fit_contrast(self.light.color(self.role("Text")), base).rgb()
        colours = {
            image.pixel(x, y) for x in range(15, WIDTH - 15) for y in range(8, 46)
        }
        self.assertIn(disabled, colours)
        self.assertNotIn(ink, colours)


class PinTest(RailTestCase):
    def test_the_boot_pin_is_ink_on_the_surface_and_never_the_accent(self):
        from legion_powerctl_gui import theme

        for label, palette in (("light", self.light), ("dark", self.dark)):
            for flags in ((), ("Selected",), ("MouseOver",)):
                image = self.paint("balanced-plus", palette, self.state(*flags))
                rect = self.sidebar.delegate.pin_rect(self.option(), pinned=True)
                background = self.colour(image, 20, 3)
                ink = theme.fit_contrast(
                    palette.color(self.role("Text")), background, theme.MIN_NON_TEXT_CONTRAST
                )
                fill = self.colour(image, rect.left() + 2, rect.center().y())
                with self.subTest(scheme=label, state=flags):
                    self.assertEqual(fill.rgb(), ink.rgb())
                    self.assertNotEqual(fill.rgb(), theme.accent_color(palette).rgb())
                    self.assertGreaterEqual(
                        theme.contrast_ratio(fill, background), theme.MIN_NON_TEXT_CONTRAST
                    )

    def test_the_boot_pin_is_eighteen_tall_and_sits_on_the_detail_line(self):
        rect = self.sidebar.delegate.pin_rect(self.option(), pinned=True)
        self.assertEqual(rect.height(), 18)
        self.assertEqual(rect.right() + 1, WIDTH - 16)
        self.assertGreater(rect.top(), HEIGHT // 2 - 9)
        self.assertLess(rect.bottom(), HEIGHT - 2)

    def test_the_set_boot_pin_is_an_outline_that_shows_on_hover_and_selection_only(self):
        from legion_powerctl_gui import theme

        base = self.light.color(self.role("Base"))
        resting = self.paint("quiet")
        rect = self.sidebar.delegate.pin_rect(self.option(), pinned=False)
        self.assertEqual(resting.pixel(rect.left(), rect.center().y()), base.rgb())
        for flags in (("MouseOver",), ("Selected",)):
            image = self.paint("quiet", state=self.state(*flags))
            background = self.colour(image, 20, 3)
            edge = theme.edge_strong_color(self.light, background)
            with self.subTest(state=flags):
                self.assertEqual(image.pixel(rect.left(), rect.center().y()), edge.rgb())
                self.assertEqual(
                    image.pixel(rect.left() + 1, rect.center().y()), background.rgb()
                )
                self.assertNotEqual(edge.rgb(), theme.accent_color(self.light).rgb())

    def test_a_click_on_the_set_boot_pin_pins_and_a_click_elsewhere_does_not(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        seen = []
        self.sidebar.boot_requested.connect(seen.append)
        view = self.sidebar.list
        option = self.option()
        option.rect = view.visualItemRect(view.item(0))
        pin = self.sidebar.delegate.pin_rect(option, pinned=False)
        click = Qt.MouseButton.LeftButton
        QTest.mouseClick(view.viewport(), click, pos=QPoint(40, option.rect.center().y()))
        self.assertEqual(seen, [])
        QTest.mouseClick(view.viewport(), click, pos=pin.center())
        self.assertEqual(seen, ["quiet"])
        option.rect = view.visualItemRect(view.item(1))
        pinned = self.sidebar.delegate.pin_rect(option, pinned=True)
        QTest.mouseClick(view.viewport(), click, pos=pinned.center())
        self.assertEqual(seen, ["quiet"], "the boot profile is already pinned")


def recording_painter(image):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFontMetrics, QPainter

    class Recorder(QPainter):
        def __init__(self, device):
            super().__init__(device)
            self.texts = {}
            self.icons = []

        def drawText(self, rect, flags, text):
            self.texts[text] = QFontMetrics(self.font()).boundingRect(rect, flags, text)
            super().drawText(rect, flags, text)

        def drawPixmap(self, x, y, pixmap):
            ratio = pixmap.devicePixelRatio()
            self.icons.append(
                QRect(x, y, round(pixmap.width() / ratio), round(pixmap.height() / ratio))
            )
            super().drawPixmap(x, y, pixmap)

    return Recorder(image)


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class RowFitTest(OffscreenGuiTest):
    def setUp(self):
        os.environ.pop("FAKE_CLI_LOG", None)

    def open_window(self):
        from legion_powerctl_gui.app import MainWindow

        window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.resize(960, 620)
        window.show()
        self.assertTrue(
            wait_until(self.app, lambda: window.refresh_count >= 1),
            f"window never loaded; errors: {list(window.errors)}",
        )
        self.settle(5)
        return window

    def assert_every_row_is_drawn_whole_beside_an_icon(self):
        from legion_powerctl_gui.profile_delegate import BOOT_ROLE, DETAIL_ROLE, ICON_SIZE
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

        view = self.open_window().sidebar.list
        pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
        pixmap.fill(QColor("black"))
        font = self.app.font()
        for row in range(view.count()):
            item = view.item(row)
            item.setIcon(QIcon(pixmap))
            profile = item.data(Qt.ItemDataRole.UserRole)
            detail = item.data(DETAIL_ROLE)
            for pinned in (False, True):
                item.setData(BOOT_ROLE, pinned)
                option = QStyleOptionViewItem()
                option.rect = view.visualItemRect(item)
                option.font = view.font()
                option.palette = view.palette()
                option.decorationSize = view.iconSize()
                option.state = (
                    QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
                    | QStyle.StateFlag.State_MouseOver
                )
                image = QImage(view.viewport().size(), QImage.Format.Format_ARGB32_Premultiplied)
                painter = recording_painter(image)
                view.itemDelegate().paint(painter, option, view.model().index(row, 0))
                painter.end()
                where = f"{profile.name} {'BOOT' if pinned else 'SET BOOT'} in {font.family()} "
                where += f"{font.pointSizeF():g} pt, {option.rect.width()} px wide"
                with self.subTest(row=where):
                    self.assertIn(profile.name, painter.texts, "the name was cut")
                    self.assertIn(detail, painter.texts, f"the detail was cut: {painter.texts}")
                    first = {"name": painter.texts[profile.name]}
                    second = {"detail": painter.texts[detail]}
                    if profile.valid:
                        first["watts"] = painter.texts[f"{profile.stapm_w} W"]
                        second["pin"] = view.itemDelegate().pin_rect(option, pinned)
                        self.assertIn("BOOT" if pinned else "SET BOOT", painter.texts)
                    self.assertEqual(len(painter.icons), 1, "the icon was not drawn")
                    icon = painter.icons[0]
                    for name, box in {**first, **second, "icon": icon}.items():
                        self.assertTrue(option.rect.contains(box), f"the {name} leaves the row")
                        if name != "icon":
                            self.assertFalse(box.intersects(icon), f"the icon covers the {name}")
                    for line in (first, second):
                        (name, box), *rest = line.items()
                        for other, beside in rest:
                            self.assertFalse(
                                box.intersects(beside), f"the {name} runs into the {other}"
                            )

    def test_every_row_fits_the_default_rail_at_960_with_its_icon(self):
        self.assert_every_row_is_drawn_whole_beside_an_icon()

    def test_and_at_the_kde_default_size(self):
        self.use_app_font_size(DESKTOP_POINT_SIZE)
        self.assert_every_row_is_drawn_whole_beside_an_icon()


class HeaderTest(RailTestCase):
    def test_the_header_carries_the_eyebrow_and_the_number_of_rows(self):
        self.assertEqual(self.sidebar.header.title.text(), "PROFILES")
        self.assertEqual(self.sidebar.header.count, 3)
        self.sidebar.create_draft("fresh")
        self.assertEqual(self.sidebar.header.count, 4)
        self.sidebar.discard_draft("fresh")
        self.assertEqual(self.sidebar.header.count, 3)
        self.sidebar.set_profiles([], boot="", select="")
        self.assertEqual(self.sidebar.header.count, 0)

    def count_region(self, image, ink=None):
        from legion_powerctl_gui import theme
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter

        header = self.sidebar.header
        reference = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        reference.fill(self.colour(image, image.width() // 2, 2))
        painter = QPainter(reference)
        painter.setFont(theme.font("detail-mono"))
        painter.setPen(ink)
        painter.drawText(
            header.rect().adjusted(0, 0, -16, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            str(header.count),
        )
        painter.end()
        left = image.width() - 60
        return (
            image.copy(left, 0, 60, image.height()),
            reference.copy(left, 0, 60, image.height()),
        )

    def test_the_count_is_painted_at_the_right_of_the_header_in_the_muted_ink(self):
        from legion_powerctl_gui import theme

        base = self.light.color(self.role("Base"))
        shown, expected = self.count_region(
            self.sidebar.header.grab().toImage(), theme.muted_color(self.light, base)
        )
        self.assertEqual(shown, expected)
        empty = self.sidebar.header.grab().toImage()
        self.sidebar.header.set_count(0)
        zero = self.sidebar.header.grab().toImage()
        self.assertNotEqual(empty, zero)

    def test_a_busy_rail_dims_the_count_with_the_rows(self):
        from legion_powerctl_gui import theme

        self.sidebar.setEnabled(False)
        self.app.processEvents()
        shown, expected = self.count_region(
            self.sidebar.header.grab().toImage(), theme.disabled_text_color(self.light)
        )
        self.assertEqual(shown, expected)

    def test_the_accessibility_tree_gains_one_eyebrow_and_no_second_text_node(self):
        from PySide6.QtGui import QAccessible

        found = []

        def walk(interface, depth=0):
            found.append(
                (depth, interface.role(), interface.text(QAccessible.Text.Name))
            )
            for index in range(interface.childCount()):
                walk(interface.child(index), depth + 1)

        walk(QAccessible.queryAccessibleInterface(self.sidebar))
        roles = QAccessible.Role
        self.assertEqual(
            [name for _, role, name in found if role == roles.StaticText], ["PROFILES"]
        )
        self.assertIn((1, roles.List, "Profiles"), [(d, r, n) for d, r, n in found if d == 1])
        self.assertEqual(
            [name for _, role, name in found if role == roles.PushButton],
            ["New profile", "Delete"],
        )
        self.assertEqual(
            [name for _, role, name in found if role == roles.ListItem],
            [
                "quiet, running now, 45/50/60 W, 78 C cap",
                "balanced-plus, boot profile, 87/92/102 W, 80 C cap",
                "broken, invalid profile file",
            ],
        )


class RestyleTest(RailTestCase):
    def sheets(self, palette):
        from legion_powerctl_gui import styles, theme

        footer = (
            f"{styles.footer_style(palette, 'QFrame#railFooter')}"
            f" {styles.secondary_button_style(palette)}"
        )
        title = (
            f"QLabel {{ {styles.caption_style(palette)} }}"
            f" QLabel:disabled {{ color: {theme.disabled_text_color(palette).name()}; }}"
        )
        return styles.surface_style(palette), title, footer

    def test_restyle_rebuilds_every_sheet_from_the_palette_it_is_given(self):
        sidebar = self.sidebar
        self.assertEqual(
            (sidebar.styleSheet(), sidebar.header.title.styleSheet(),
             sidebar.footer.styleSheet()),
            self.sheets(self.light),
        )
        sidebar.restyle(self.dark)
        self.assertEqual(
            (sidebar.styleSheet(), sidebar.header.title.styleSheet(),
             sidebar.footer.styleSheet()),
            self.sheets(self.dark),
        )
        self.assertNotEqual(self.sheets(self.light), self.sheets(self.dark))

    def test_a_palette_flip_repaints_the_card_the_rows_and_the_count(self):
        from legion_powerctl_gui import theme

        light = self.sidebar.grab().toImage()
        self.use(self.dark)
        dark = self.sidebar.grab().toImage()
        self.assertNotEqual(light, dark)
        base = self.dark.color(self.role("Base"))
        self.assertEqual(
            dark.pixel(WIDTH // 2, 330), base.rgb(), "the card kept the old surface"
        )
        image = self.paint("quiet", self.dark, self.state("Selected"))
        self.assertEqual(image.pixel(20, 3), theme.selection_color(self.dark).rgb())
        self.assertEqual(image.pixel(1, 26), theme.accent_color(self.dark).rgb())

    def test_the_window_restyle_chain_reaches_the_rail(self):
        from legion_powerctl_gui import styles
        from legion_powerctl_gui.app import MainWindow

        window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        self.assertIn(window.sidebar, window.regions())
        window.restyle(self.dark)
        self.assertEqual(window.sidebar.styleSheet(), styles.surface_style(self.dark))


if __name__ == "__main__":
    unittest.main()
