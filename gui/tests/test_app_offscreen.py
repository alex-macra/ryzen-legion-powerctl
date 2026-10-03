# SPDX-License-Identifier: MIT

import atexit
import json
import os
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).parent
FAKE_CLI = HERE / "fake-legion-powerctl"
STATUS_FIXTURE = HERE / "fixtures" / "status.json"
DESKTOP_POINT_SIZE = 10.0

try:
    import PySide6  # noqa: F401

    HAVE_PYSIDE6 = True
except ImportError:
    HAVE_PYSIDE6 = False


def wait_until(app, predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


GRAYSCALE_FONTCONFIG = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">{base}</include>
  <match target="font"><edit name="rgba" mode="assign"><const>none</const></edit></match>
</fontconfig>
"""


def render_text_in_grayscale() -> None:
    # Subpixel antialiasing tints every glyph edge, so a test that reads a text
    # colour back would pass or fail with the machine's LCD setting.
    base = os.environ.get("FONTCONFIG_FILE") or "/etc/fonts/fonts.conf"
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
    handle.write(GRAYSCALE_FONTCONFIG.format(base=base))
    handle.close()
    atexit.register(os.unlink, handle.name)
    os.environ["FONTCONFIG_FILE"] = handle.name


@unittest.skipUnless(HAVE_PYSIDE6, "PySide6 is not installed")
class OffscreenGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        overrides = unittest.mock.patch.dict(
            os.environ,
            {
                "LEGION_POWERCTL_GUI_CLI": str(FAKE_CLI),
                "LEGION_POWERCTL_GUI_ELEVATE": "none",
                "LEGION_POWERCTL_GUI_NO_DIALOGS": "1",
            },
        )
        overrides.start()
        cls.addClassCleanup(overrides.stop)

        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            render_text_in_grayscale()
        cls.app = QApplication.instance() or QApplication([])

    def settle(self, rounds: int = 20) -> None:
        for _ in range(rounds):
            self.app.processEvents()
            time.sleep(0.01)

    def use_app_font_size(self, size: float) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtGui import QFont

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        font = QFont(self.app.font())
        self.addCleanup(self.app.setFont, QFont(font))
        font.setPointSizeF(size)
        self.app.setFont(font)

    @staticmethod
    def accessible_name(widget) -> str:
        from PySide6.QtGui import QAccessible

        interface = QAccessible.queryAccessibleInterface(widget)
        return interface.text(QAccessible.Text.Name) if interface else ""

    @classmethod
    def accessible_label(cls, widget) -> str:
        from PySide6.QtGui import QAccessible

        interface = QAccessible.queryAccessibleInterface(widget)
        if interface is None:
            return ""
        for other, relation in interface.relations():
            if relation & QAccessible.RelationFlag.Label and other.text(QAccessible.Text.Name):
                return other.text(QAccessible.Text.Name)
        return widget.accessibleName()

    @staticmethod
    def announcements():
        return unittest.mock.patch("legion_powerctl_gui.a11y.announce")

    @staticmethod
    def spoken(call) -> str:
        return call[0][1]

    @staticmethod
    def colours_in_rows(image, top: int, bottom: int) -> set:
        return {
            image.pixelColor(x, y).name()
            for y in range(max(0, top), min(bottom, image.height()))
            for x in range(image.width())
        }

    @staticmethod
    def ink_spans(image, top: int, bottom: int, parting: int) -> list:
        from collections import Counter

        plane = Counter(
            image.pixel(x, y) for y in range(image.height()) for x in range(image.width())
        ).most_common(1)[0][0]
        rows = range(max(0, top), min(bottom, image.height()))
        spans, blank = [], parting
        for x in range(image.width()):
            if any(image.pixel(x, y) != plane for y in rows):
                if blank >= parting:
                    spans.append([x, x])
                spans[-1][1] = x
                blank = 0
            else:
                blank += 1
        return spans

    @staticmethod
    def caption_rows(readout) -> tuple:
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QFontMetrics

        eyebrow = QFontMetrics(theme.font("eyebrow", readout.font())).height()
        return readout.height() - eyebrow, readout.height()

    @staticmethod
    def readout_inks(readout):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QFontMetrics, QPalette

        palette = readout.palette()
        base = palette.color(QPalette.ColorRole.Base)
        ink = theme.fit_contrast(palette.color(QPalette.ColorRole.Text), base)
        fail = theme.fit_contrast(theme.severity_color(palette, "FAIL"), base)
        cap = QFontMetrics(theme.font("readout", readout.font())).capHeight()
        return ink.name(), fail.name(), theme.muted_color(palette, base).name(), cap


class MainWindowTest(OffscreenGuiTest):
    def setUp(self):
        self.log = tempfile.NamedTemporaryFile(mode="r", suffix=".log", delete=False)
        os.environ["FAKE_CLI_LOG"] = self.log.name

        from legion_powerctl_gui.app import MainWindow

        self.window = MainWindow()
        self.editor = self.window.editor
        self.sidebar = self.window.sidebar
        self.header = self.window.header
        self.checks = self.window.checks.dialog
        loaded = wait_until(
            self.app,
            lambda: self.window.refresh_count >= 1 and self.window.checks.count >= 1,
        )
        self.assertTrue(loaded, f"window never loaded; errors: {list(self.window.errors)}")

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.log.close()
        os.unlink(self.log.name)

    def read_log(self):
        with open(self.log.name, encoding="utf-8") as handle:
            return handle.read().splitlines()

    def test_profiles_populate_and_the_running_profile_is_loaded(self):
        self.assertEqual(self.sidebar.list.count(), 4)
        self.assertIn("balanced-plus", self.header.running_label.text())
        self.assertIn("balanced-plus", self.header.boot_label.text())
        self.assertEqual(self.editor.profile_title.text(), "balanced-plus")
        self.assertEqual(self.editor.stapm_spin.value(), 87)
        self.assertEqual(self.editor.slow_spin.value(), 92)
        self.assertEqual(self.editor.fast_spin.value(), 102)
        self.assertEqual(self.editor.temp_spin.value(), 80)
        self.assertFalse(self.window.errors)

    def _item(self, name):
        from PySide6.QtCore import Qt

        for row in range(self.sidebar.list.count()):
            item = self.sidebar.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole).name == name:
                return item
        raise AssertionError(f"{name} not in the sidebar")

    def _row_of(self, name: str) -> int:
        from PySide6.QtCore import Qt

        for row in range(self.sidebar.list.count()):
            profile = self.sidebar.list.item(row).data(Qt.ItemDataRole.UserRole)
            if profile is not None and profile.name == name:
                return row
        raise AssertionError(f"{name} not in the sidebar")

    def test_invalid_profile_row_stays_reachable_by_keyboard(self):
        from PySide6.QtCore import Qt

        broken = self._item("broken")
        self.assertTrue(
            broken.flags() & Qt.ItemFlag.ItemIsEnabled,
            "a disabled row is skipped by arrow-key navigation, which hid "
            "'invalid profile file' from everyone but a sighted mouse user",
        )
        self.assertTrue(broken.flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_selecting_an_invalid_profile_explains_it_and_arms_nothing(self):
        self.sidebar.list.setCurrentRow(self._row_of("broken"))
        self.assertIsNone(
            self.editor.editing,
            "a broken profile must not become the target of Save; it would write "
            "defaults over a file whose real contents are unknown",
        )
        self.assertIn("Problem:", self.editor.problems_label.text())
        self.assertIn("broken", self.editor.problems_label.text())
        self.assertFalse(self.editor.apply_button.isEnabled())
        self.assertFalse(self.editor.stapm_spin.isEnabled())
        self.assertFalse(
            self.sidebar.delete_button.isEnabled(),
            "Delete sits in the sidebar but acts on what the editor has open",
        )
        self.window.refresh()
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count >= 2))
        current = self.sidebar.list.currentItem()
        self.assertEqual(self._item("broken"), current)

    def test_leaving_an_invalid_profile_re_arms_the_editor(self):
        self.sidebar.list.setCurrentRow(self._row_of("broken"))
        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        self.assertEqual(self.editor.profile_title.text(), "quiet")
        self.assertTrue(self.editor.apply_button.isEnabled())
        self.assertTrue(self.editor.stapm_spin.isEnabled())
        self.assertTrue(self.sidebar.delete_button.isEnabled())

    def test_both_row_marks_are_spelled_out_for_a_screen_reader(self):
        from PySide6.QtCore import Qt

        spoken = self._item("balanced-plus").data(Qt.ItemDataRole.AccessibleTextRole)
        self.assertIn("balanced-plus", spoken)
        self.assertIn("running now", spoken)
        self.assertIn("boot profile", spoken)
        self.assertNotIn("●", spoken)
        quiet = self._item("quiet").data(Qt.ItemDataRole.AccessibleTextRole)
        self.assertNotIn("running now", quiet)
        self.assertNotIn("boot profile", quiet)

    def test_the_editor_measures_every_profile_against_what_runs(self):
        cards = self.editor.cards
        self.assertEqual(self.editor.title_aside.text(), "running now, boot profile")
        self.assertEqual(self.editor.power_envelope.bar.reference, (87, 92, 102))
        self.assertEqual(self.editor.thermal_envelope.bar.reference, (80,))
        self.assertEqual(
            [card.aside for card in cards], ["running 87/92/102 W", "running 80 °C", ""]
        )
        self.sidebar.list.setCurrentRow(self._row_of("broken"))
        self.assertEqual(self.editor.title_aside.text(), "")
        self.assertFalse(self.editor.title_aside.isVisibleTo(self.window))
        self.assertEqual(self.editor.power_envelope.bar.reference, (87, 92, 102))
        self.assertEqual(
            cards[0].aside, "running 87/92/102 W", "the machine's facts left with the file"
        )

    def test_slider_order_is_enforced_live(self):
        self.editor.stapm_spin.setValue(110)
        self.assertEqual(self.editor.stapm_spin.value(), 110)
        self.assertEqual(self.editor.slow_spin.value(), 110)
        self.assertEqual(self.editor.fast_spin.value(), 110)
        self.editor.fast_spin.setValue(70)
        self.assertEqual(self.editor.stapm_spin.value(), 70)
        self.assertEqual(self.editor.slow_spin.value(), 70)

    def test_apply_invokes_configure_with_editor_values(self):
        self.editor.stapm_spin.setValue(55)
        self.editor.apply_button.click()
        self.assertTrue(
            wait_until(self.app, lambda: any("configure" in line for line in self.read_log()))
        )
        line = next(line for line in self.read_log() if line.startswith("configure"))
        self.assertIn("configure balanced-plus --stapm 55 --slow 92 --fast 102 --temp 80", line)
        self.assertIn("--power-profile balanced", line)
        self.assertIn("--apply", line)

    def test_ctrl_s_saves_without_applying(self):
        self.editor.stapm_spin.setValue(55)
        self.window.profile_actions.save()
        self.assertTrue(
            wait_until(self.app, lambda: any("configure" in line for line in self.read_log()))
        )
        line = next(line for line in self.read_log() if line.startswith("configure"))
        self.assertIn("--stapm 55", line)
        self.assertNotIn("--apply", line)
        self.assertNotIn("--select", line)

    def test_the_checks_chip_counts_what_the_doctor_found(self):
        report = self.window.checks.report
        self.assertEqual(report.failures, 0)
        self.assertEqual(report.warnings, 2)
        self.assertIn("2", self.header.checks_button.text())
        self.assertIn("0 failure(s), 2 warning(s)", self.header.checks_button.accessibleName())

    def test_the_checks_chip_is_painted_in_the_severity_it_reports(self):
        from legion_powerctl_gui import model, theme

        palette = self.header.palette()
        sheet = self.header.checks_button.styleSheet()
        self.assertIn(
            "QPushButton", sheet,
            "the chip is styled for a class it is not, so nothing is applied",
        )
        self.assertIn(theme.severity_color(palette, "WARN").name(), sheet)

        failing = model.DoctorReport(
            lines=[model.DoctorLine("FAIL", "ryzenadj", "not installed")],
            failures=1,
            warnings=0,
            exit_code=1,
        )
        self.header.show_checks(failing)
        failed_sheet = self.header.checks_button.styleSheet()
        self.assertIn(theme.severity_color(palette, "FAIL").name(), failed_sheet)
        self.assertNotEqual(
            sheet, failed_sheet,
            "a failure and a warning reach the screen as the same chip",
        )

    def test_the_checks_dialog_lists_every_check_on_request(self):
        self.window.checks.show()
        self.assertEqual(len(self.checks.rows), len(self.window.checks.report.lines))
        self.assertIn("0 failure(s), 2 warning(s)", self.checks.summary.text())

    def click_repair(self, accept=True):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        captured = []

        def answer():
            box = self.app.activeModalWidget()
            if isinstance(box, QMessageBox):
                captured.append(box.text() + "\n" + box.informativeText())
                button = next(
                    button for button in box.buttons()
                    if button.text() == "Repair and apply"
                ) if accept else box.button(QMessageBox.StandardButton.Cancel)
                button.click()

        self.window.dialogs = True
        self.window.checks.show()
        QTimer.singleShot(0, answer)
        self.checks.repair_button.click()
        self.window.dialogs = False
        self.assertEqual(len(captured), 1, "repair must explain and confirm the reset")
        return captured[0]

    def test_checks_repair_replaces_an_invalid_profile_and_refreshes_the_results(self):
        data = json.loads(STATUS_FIXTURE.read_text(encoding="utf-8"))
        repaired = json.loads(json.dumps(data))
        data["profiles"][0] = {"name": "balanced-plus", "valid": False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, after, doctor, healthy = [
                root / name for name in ("status.json", "after.json", "doctor.txt", "ok.txt")
            ]
            status.write_text(json.dumps(data), encoding="utf-8")
            after.write_text(json.dumps(repaired), encoding="utf-8")
            doctor.write_text("FAIL  Profile  balanced-plus is invalid\n", encoding="utf-8")
            healthy.write_text("OK  Profile  balanced-plus\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {
                "FAKE_CLI_STATUS_FIXTURE": str(status),
                "FAKE_CLI_REPAIR_STATUS_FIXTURE": str(after),
                "FAKE_CLI_DOCTOR_FIXTURE": str(doctor),
                "FAKE_CLI_REPAIR_DOCTOR_FIXTURE": str(healthy),
            }):
                self.window.refresh()
                self.window.checks.run()
                self.assertTrue(wait_until(self.app, lambda: not self.window.runner.processes))
                self.assertIsNone(self.editor.editing)
                refreshes, checks = self.window.refresh_count, self.window.checks.count
                confirmation = self.click_repair()
                self.assertTrue(wait_until(self.app, lambda: (
                    self.window.refresh_count > refreshes and self.window.checks.count > checks
                    and not self.window.runner.processes
                )))
                self.assertIn("80 C", confirmation)
                self.assertIn("87/92/102 W", confirmation)
                self.assertIn("backup", confirmation.lower())
                self.assertIn("ryzen_smu", confirmation)
                self.assertIn("unload it before applying", confirmation)
                self.assertIn("only after a successful apply", confirmation)
                self.assertIn("repair balanced-plus", self.read_log())
                self.assertEqual(self.editor.collect().stapm_w, 87)
                self.assertEqual(self.editor.collect().slow_w, 92)
                self.assertEqual(self.editor.collect().fast_w, 102)
                self.assertEqual(self.editor.collect().temp_c, 80)
                self.assertFalse(self.editor.dirty)
                self.assertEqual(self.window.checks.report.failures, 0)
                self.assertIn("0 failure(s)", self.checks.summary.text())
                self.assertFalse(self.window.reports.details_button.isHidden())
                self.assertEqual(
                    self.window.reports.last_warning,
                    "Recovery backup: /var/lib/legion-powerctl/repair/example",
                )

    def test_cancelling_checks_repair_preserves_dirty_edits(self):
        self.editor.stapm_spin.setValue(55)
        self.editor._on_edited()
        confirmation = self.click_repair(accept=False)
        self.assertIn("unsaved", confirmation.lower())
        self.assertNotIn("repair balanced-plus", self.read_log())
        self.assertTrue(self.editor.dirty)
        self.assertEqual(self.editor.stapm_spin.value(), 55)

    def test_failed_checks_repair_surfaces_the_error_and_preserves_dirty_edits(self):
        self.editor.stapm_spin.setValue(55)
        self.editor._on_edited()
        with unittest.mock.patch.dict(os.environ, {
            "FAKE_CLI_REPAIR_ERROR": "ryzen_smu is in use; repair was rolled back"
        }):
            self.click_repair()
            self.assertTrue(wait_until(self.app, lambda: bool(self.window.errors)))
        self.assertIn("ryzen_smu is in use", self.window.errors[-1])
        self.assertIn("Recovery backup: /var/lib/legion-powerctl/repair/example",
                      self.window.errors[-1])
        self.assertFalse(self.window.reports.details_button.isHidden())
        self.assertIn("Recovery backup: /var/lib/legion-powerctl/repair/example",
                      self.window.reports.last_warning)
        self.assertTrue(self.editor.dirty)
        self.assertEqual(self.editor.stapm_spin.value(), 55)

    def test_confirmed_checks_repair_discards_edits_and_opens_the_repaired_profile(self):
        self.sidebar.select_by_name("quiet")
        self.editor.stapm_spin.setValue(40)
        self.editor._on_edited()
        refreshes, checks = self.window.refresh_count, self.window.checks.count
        confirmation = self.click_repair()
        self.assertIn("unsaved changes to 'quiet'", confirmation)
        self.assertTrue(wait_until(self.app, lambda: (
            self.window.refresh_count > refreshes and self.window.checks.count > checks
            and not self.window.runner.processes
        )))
        self.assertEqual(self.editor.current_name, "balanced-plus")
        self.assertFalse(self.editor.dirty)

    def test_checks_repair_warning_details_include_the_backup_path(self):
        with unittest.mock.patch.dict(os.environ, {
            "FAKE_CLI_REPAIR_WARNING": "Applied, but limit readback is unavailable."
        }):
            self.checks.repair_button.click()
            self.assertTrue(wait_until(self.app, lambda: (
                "limit readback is unavailable" in self.window.reports.last_warning
            )))
        self.assertIn("Recovery backup: /var/lib/legion-powerctl/repair/example",
                      self.window.reports.last_warning)
        self.assertNotIn("balanced-plus repaired and applied", self.window.reports.last_warning)
        self.assertFalse(self.window.reports.details_button.isHidden())

    def test_copying_puts_the_whole_report_on_the_clipboard(self):
        from PySide6.QtGui import QGuiApplication

        self.window.checks.show()
        self.checks.copy_button.click()

        pasted = QGuiApplication.clipboard().text()
        body = self.window.checks.report.text.strip("\n")
        self.assertTrue(body, "the report kept no raw text, so the next assertion proves nothing")
        self.assertIn(body, pasted, "the clipboard lost lines the dialog was showing")
        self.assertIn(self.header.machine_label.text(), pasted)

    def test_copying_says_it_copied_and_then_offers_to_copy_again(self):
        self.window.checks.show()
        self.checks._copied_timer.setInterval(0)
        self.checks.copy_button.click()

        self.assertIn("Copied", self.checks.copy_button.text())
        wait_until(self.app, lambda: "Copy report" in self.checks.copy_button.text())

    def test_the_copy_is_announced_to_a_screen_reader(self):
        self.window.checks.show()
        with self.announcements() as announce:
            self.checks.copy_button.click()
            self.settle(5)
            spoken = [self.spoken(call) for call in announce.call_args_list]
        self.assertEqual(
            1, sum("clipboard" in message for message in spoken),
            f"expected exactly one clipboard announcement, got {spoken}",
        )

    def test_a_check_detail_can_be_selected_without_stealing_the_row_s_tab_stop(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        self.window.checks.show()
        self.assertTrue(self.checks.rows, "no rows to check")
        for row in self.checks.rows:
            self.assertEqual(row.focusPolicy(), Qt.FocusPolicy.TabFocus)
            for label in row.findChildren(QLabel):
                self.assertTrue(
                    label.textInteractionFlags()
                    & Qt.TextInteractionFlag.TextSelectableByMouse
                )
                self.assertEqual(
                    label.focusPolicy(), Qt.FocusPolicy.ClickFocus,
                    "TextSelectableByKeyboard would add two tab stops per row",
                )

    def test_every_button_in_the_checks_dialog_claims_a_different_mnemonic(self):
        from PySide6.QtWidgets import QPushButton

        self.window.checks.show()
        mnemonics = [
            text[text.index("&") + 1].lower()
            for button in self.checks.findChildren(QPushButton)
            for text in [button.text()]
            if "&" in text
        ]
        self.assertEqual(sorted(mnemonics), sorted(set(mnemonics)), mnemonics)

    def test_typing_a_power_value_does_not_drag_the_other_limits(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        self.assertFalse(self.editor.fast_spin.keyboardTracking())
        self.editor.fast_spin.selectAll()
        QTest.keyClicks(self.editor.fast_spin, "110")
        QTest.keyClick(self.editor.fast_spin, Qt.Key.Key_Return)
        self.assertEqual(self.editor.fast_spin.value(), 110)
        self.assertEqual(self.editor.stapm_spin.value(), 87)
        self.assertEqual(self.editor.slow_spin.value(), 92)

    def test_failed_action_keeps_unsaved_edits(self):
        self.editor.stapm_spin.setValue(58)
        self.editor.advanced.min_freq_edit.setCurrentText("2400")
        self.editor._on_edited()
        refreshes = self.window.refresh_count
        self.window.profile_actions.handle_result(
            126, "", "Request dismissed", saved=self.editor.collect()
        )
        self.settle()
        self.assertEqual(
            self.window.refresh_count, refreshes,
            "a failed action must not refresh; the reload discards the edits",
        )
        self.assertTrue(self.editor.dirty)
        self.assertEqual(self.editor.stapm_spin.value(), 58)
        self.assertEqual(self.editor.advanced.min_freq_edit.currentText(), "2400")

    def test_edits_made_while_a_save_is_in_flight_survive(self):
        self.editor.stapm_spin.setValue(55)
        self.editor._on_edited()
        in_flight = self.editor.collect()
        self.editor.advanced.min_freq_edit.setCurrentText("3200")
        self.editor._on_edited()
        self.window.profile_actions.handle_result(0, "", "", saved=in_flight)
        self.assertTrue(self.editor.dirty, "later edits must stay dirty")
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count >= 2))
        self.assertEqual(self.editor.advanced.min_freq_edit.currentText(), "3200")

    def test_successful_save_clears_dirty(self):
        self.editor.stapm_spin.setValue(56)
        self.editor._on_edited()
        self.window.profile_actions.handle_result(0, "", "", saved=self.editor.collect())
        self.assertFalse(self.editor.dirty)

    def test_refresh_does_not_reset_a_dirty_editor(self):
        self.editor.stapm_spin.setValue(57)
        self.editor._on_edited()
        self.window.refresh()
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count >= 2))
        self.assertEqual(self.editor.stapm_spin.value(), 57)

    def test_new_profile_rejects_an_existing_name(self):
        before = self.sidebar.list.count()
        self.assertIn("quiet", self.sidebar.valid_names(), "status had not loaded yet")
        with unittest.mock.patch.object(
            self.window.profile_actions, "ask_profile_name", return_value="quiet"
        ):
            self.window.profile_actions.new_profile()
        self.assertEqual(self.sidebar.list.count(), before)
        self.assertNotIn("quiet", self.sidebar.drafts)
        self.assertTrue(any("already exists" in e for e in self.window.errors))

    def test_an_invalid_value_disables_apply_rather_than_failing_after_the_click(self):
        self.editor.advanced.min_freq_edit.setCurrentText("99")
        self.editor._on_edited()
        self.assertFalse(self.editor.apply_button.isEnabled())
        self.assertIn("frequency", self.editor.problems_label.text())
        self.window.profile_actions.apply()
        self.app.processEvents()
        self.assertTrue(any("frequency" in e for e in self.window.errors))
        self.assertFalse(any("configure" in line for line in self.read_log()))

    def _cancel_discard(self, side_effect=None):
        from PySide6.QtWidgets import QMessageBox

        self.window.dialogs = True
        kwargs = {"side_effect": side_effect} if side_effect else {
            "return_value": QMessageBox.StandardButton.Cancel
        }
        return unittest.mock.patch(
            "legion_powerctl_gui.dialogs.confirm_discard", **kwargs
        )

    def test_cancel_on_discard_keeps_editor_and_sidebar_in_agreement(self):
        from PySide6.QtCore import Qt

        self.editor.stapm_spin.setValue(57)
        self.editor._on_edited()
        try:
            with self._cancel_discard():
                self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        finally:
            self.window.dialogs = False
        self.assertEqual(self.editor.profile_title.text(), "balanced-plus")
        self.assertEqual(self.editor.stapm_spin.value(), 57)
        current = self.sidebar.list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.assertEqual(
            current.name, "balanced-plus",
            "Cancel must put the highlight back, or Save acts on a profile "
            "other than the highlighted one",
        )
        self.assertFalse(self.sidebar.list.signalsBlocked())

    def _save_on_discard(self):
        from PySide6.QtWidgets import QMessageBox

        return self._cancel_discard(
            side_effect=lambda *_a, **_k: QMessageBox.StandardButton.Save
        )

    def test_save_on_the_discard_prompt_holds_the_switch_until_the_write_lands(self):
        self.editor.stapm_spin.setValue(57)
        self.editor._on_edited()
        try:
            with self._save_on_discard():
                self.sidebar.list.setCurrentRow(self._row_of("quiet"))
            self.assertEqual(
                self.editor.profile_title.text(), "balanced-plus",
                "the editor moved on while the write was still in the air",
            )
            self.assertEqual(self.editor.stapm_spin.value(), 57)
            self.assertEqual(self.window._pending_open, "quiet")
            self.assertTrue(
                wait_until(self.app, lambda: self.editor.profile_title.text() == "quiet"),
                "the profile the user asked for never opened",
            )
        finally:
            self.window.dialogs = False
        self.assertEqual(self.window._pending_open, "")
        line = next(line for line in self.read_log() if line.startswith("configure"))
        self.assertIn("--stapm 57", line)
        self.assertNotIn("--apply", line)

    def test_a_refused_write_from_the_discard_prompt_leaves_the_edits_where_they_are(self):
        with unittest.mock.patch.object(self.window.runner, "run") as run:
            self.editor.stapm_spin.setValue(57)
            self.editor._on_edited()
            try:
                with self._save_on_discard():
                    self.sidebar.list.setCurrentRow(self._row_of("quiet"))
            finally:
                self.window.dialogs = False
            self.assertTrue(run.called, "the discard prompt's Save started no write")
        with unittest.mock.patch.dict(
            os.environ, {"LEGION_POWERCTL_GUI_ELEVATE": "pkexec"}
        ):
            self.window.profile_actions.handle_result(126, "", "")
        self.settle()
        self.assertEqual(self.window._pending_open, "")
        self.assertEqual(self.editor.profile_title.text(), "balanced-plus")
        self.assertEqual(self.editor.stapm_spin.value(), 57)
        self.assertTrue(self.editor.dirty, "the edits were dropped by a write that never ran")

    def test_refresh_inside_the_discard_dialog_leaves_the_sidebar_alive(self):
        from legion_powerctl_gui import model
        from PySide6.QtWidgets import QMessageBox

        self.editor.stapm_spin.setValue(57)
        self.editor._on_edited()
        status = model.parse_status(STATUS_FIXTURE.read_text())

        def rebuild_then_cancel(*_args, **_kwargs):
            self.sidebar.set_profiles(
                status.profiles, status.active_profile, self.editor.current_name
            )
            return QMessageBox.StandardButton.Cancel

        try:
            with self._cancel_discard(side_effect=rebuild_then_cancel):
                self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        finally:
            self.window.dialogs = False
        self.assertFalse(
            self.sidebar.list.signalsBlocked(),
            "signals left blocked; the sidebar would be silently dead",
        )
        self.assertEqual(self.editor.stapm_spin.value(), 57)
        self.editor.dirty = False
        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        self.assertEqual(self.editor.profile_title.text(), "quiet")

    def test_invalid_profile_name_never_reaches_a_privileged_command(self):
        from legion_powerctl_gui import model

        self.editor.editing = model.Profile(name="--force")
        self.window.profile_actions.pin_boot("--force")
        self.window.profile_actions.apply_saved("--force")
        self.window.profile_actions.delete()
        self.settle(5)
        log = "\n".join(self.read_log())
        self.assertNotIn("select", log)
        self.assertNotIn("delete", log)
        self.assertNotIn("apply", log)
        self.assertTrue(any("Refusing" in e for e in self.window.errors))

    def test_pinning_an_open_draft_writes_the_profile_and_selects_it_at_once(self):
        self.sidebar.create_draft("draft")
        self.assertEqual(self.editor.editing.name, "draft", "the new draft was not opened")
        self.window.profile_actions.pin_boot("draft")
        self.assertTrue(
            wait_until(self.app, lambda: any("configure" in line for line in self.read_log())),
            f"errors: {list(self.window.errors)}",
        )
        line = next(line for line in self.read_log() if line.startswith("configure"))
        self.assertIn("configure draft", line)
        self.assertIn("--select", line)
        self.assertNotIn("--apply", line)
        self.assertFalse(any("Save 'draft'" in e for e in self.window.errors))

    def test_pinning_a_saved_profile_moves_only_the_boot_pointer(self):
        self.window.profile_actions.pin_boot("quiet")
        self.assertTrue(
            wait_until(self.app, lambda: any("select" in line for line in self.read_log()))
        )
        log = "\n".join(self.read_log())
        self.assertIn("select quiet", log)
        self.assertNotIn("configure", log)

    def test_pinning_the_open_profile_while_it_is_dirty_saves_what_is_on_screen(self):
        self.editor.stapm_spin.setValue(52)
        self.editor._on_edited()
        self.window.profile_actions.pin_boot("balanced-plus")
        self.assertTrue(
            wait_until(self.app, lambda: any("configure" in line for line in self.read_log()))
        )
        line = next(line for line in self.read_log() if line.startswith("configure"))
        self.assertIn("--stapm 52", line)
        self.assertIn("--select", line)

    def test_pinning_a_draft_that_is_not_open_is_refused(self):
        self.sidebar.create_draft("draft")
        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        self.window.profile_actions.pin_boot("draft")
        self.settle(5)
        self.assertNotIn("select draft", "\n".join(self.read_log()))
        self.assertTrue(any("Open 'draft'" in e for e in self.window.errors))

    def test_deleting_a_draft_removes_the_row_without_authorisation(self):
        self.sidebar.create_draft("draft")
        self.window.profile_actions.delete()
        self.settle(5)
        self.assertNotIn("draft", self.sidebar.drafts)
        self.assertNotIn("delete draft", "\n".join(self.read_log()))

    def test_discarding_a_draft_does_not_ask_about_discarding_it(self):
        self.sidebar.create_draft("draft")
        self.editor.advanced.min_freq_edit.setCurrentText("2800")
        self.editor.dirty = True
        self.window.dialogs = True
        try:
            with unittest.mock.patch(
                "legion_powerctl_gui.dialogs.confirm_discard"
            ) as question:
                self.window.profile_actions.delete()
                self.settle(5)
        finally:
            self.window.dialogs = False
        question.assert_not_called()
        self.assertNotIn("draft", self.sidebar.drafts)

    def test_invalid_profile_name_can_be_recreated_to_repair_it(self):
        from PySide6.QtCore import Qt

        with unittest.mock.patch.object(
            self.window.profile_actions, "ask_profile_name", return_value="broken"
        ):
            self.window.profile_actions.new_profile()
        self.assertIn("broken", self.sidebar.drafts)
        current = self.sidebar.list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.assertEqual(current.name, "broken")
        self.assertTrue(
            current.valid, "the highlighted 'broken' row is the one that cannot be opened",
        )
        self.assertEqual(self.editor.editing.name, "broken")
        self.assertTrue(
            self.editor.apply_button.isEnabled(),
            "the draft opened without arming Apply, so the repair cannot be written",
        )

    def test_invalid_profile_repair_draft_survives_status_refresh_until_saved(self):
        from PySide6.QtCore import Qt

        self.sidebar.create_draft("broken")
        refreshes = self.window.refresh_count
        self.window.refresh()
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count > refreshes))
        self.assertIn("broken", self.sidebar.drafts)
        current = self.sidebar.list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.assertTrue(current.valid, "refresh replaced the repair draft with its invalid saved row")
        self.assertIsNotNone(self.editor.editing)
        self.assertEqual(self.editor.editing.name, "broken")
        self.assertTrue(self.editor.stapm_spin.isEnabled())
        self.assertTrue(self.editor.apply_button.isEnabled())
        self.editor.stapm_spin.setValue(55)
        self.assertEqual(self.editor.collect().stapm_w, 55)

        status = json.loads(STATUS_FIXTURE.read_text())
        repaired = next(profile for profile in status["profiles"] if profile["name"] == "broken")
        repaired.update(vars(self.editor.collect()))
        with tempfile.TemporaryDirectory() as fixture_dir:
            fixture = Path(fixture_dir) / "saved-status.json"
            fixture.write_text(json.dumps(status))
            with unittest.mock.patch.dict(os.environ, {"FAKE_CLI_STATUS_FIXTURE": str(fixture)}):
                refreshes = self.window.refresh_count
                self.window.refresh()
                self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count > refreshes))
        self.assertNotIn("broken", self.sidebar.drafts)
        names = [
            self.sidebar.list.item(row).data(Qt.ItemDataRole.UserRole).name
            for row in range(self.sidebar.list.count())
        ]
        self.assertEqual(names.count("broken"), 1)

    def test_a_profile_deleted_while_open_keeps_the_edits_and_a_row_to_hold_them(self):
        from legion_powerctl_gui import model
        from PySide6.QtCore import Qt

        self.editor.stapm_spin.setValue(57)
        self.editor._on_edited()
        remaining = [
            model.Profile(name="quiet", power_profile="power-saver"),
            model.Profile(name="performance-capped", power_profile="performance"),
        ]
        try:
            with self._cancel_discard():
                self.sidebar.set_profiles(remaining, boot="quiet", select="quiet")
        finally:
            self.window.dialogs = False
        self.assertEqual(self.editor.editing.name, "balanced-plus")
        self.assertEqual(self.editor.stapm_spin.value(), 57)
        current = self.sidebar.list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.assertEqual(
            current.name, "balanced-plus",
            "the sidebar highlights a profile the editor is not editing",
        )
        self.assertIn("balanced-plus", self.sidebar.drafts)

    def test_a_healthy_boot_service_is_a_ticked_box_and_nothing_else(self):
        self.assertTrue(self.header.service_check.isChecked())
        self.assertTrue(self.header.service_check.isEnabled())
        self.assertEqual(self.header.service_label.text(), "")
        self.assertFalse(self.header.volatile_note.isVisible())

    def test_a_palette_change_re_derives_every_severity_colour(self):
        from legion_powerctl_gui import theme
        from PySide6.QtGui import QColor, QPalette

        before = self.header.checks_button.styleSheet()
        dark = QPalette(self.window.palette())
        dark.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        dark.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        self.window.setPalette(dark)
        self.app.processEvents()
        after = self.header.checks_button.styleSheet()
        self.assertNotEqual(before, after, "a high-contrast scheme has to actually take effect")
        self.assertIn(theme.severity_color(dark, "WARN").name(), after)
        self.assertIn(
            theme.severity_color(dark, "FAIL").name(),
            self.editor.problems_label.styleSheet(),
            "the panels each restyle, so a missed one leaves that panel illegible",
        )
        self.window.checks.show()
        self.window.checks.dialog.restyle(dark)
        for chip in self.checks.chips:
            self.assertIn(
                theme.severity_color(dark, chip.property("severity")).name(),
                chip.styleSheet(),
            )

    def test_refresh_timer_is_armed(self):
        self.assertTrue(self.window._refresh_timer.isActive())
        self.assertGreaterEqual(self.window._refresh_timer.interval(), 5000)

    def test_close_stops_the_refresh_timer(self):
        self.window.close()
        self.assertFalse(self.window._refresh_timer.isActive())

    def test_profile_icons_use_the_power_profile_mapping(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui import sidebar as sidebar_module
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon, QPixmap

        pixmap = QPixmap(16, 16)
        pixmap.fill()
        requested = []
        present = {model.POWER_PROFILE_ICON_NAMES["balanced"]}

        class PartialTheme:
            @staticmethod
            def hasThemeIcon(name):
                return name in present

            @staticmethod
            def fromTheme(name):
                requested.append(name)
                return QIcon(pixmap)

        with unittest.mock.patch.object(sidebar_module, "QIcon", PartialTheme):
            self.sidebar._rebuild(self.sidebar._running)
        wanted, skipped = [], 0
        for row in range(self.sidebar.list.count()):
            item = self.sidebar.list.item(row)
            profile = item.data(Qt.ItemDataRole.UserRole)
            icon_name = model.profile_icon_name(profile.power_profile) if profile.valid else ""
            has_icon = icon_name in present
            if has_icon:
                wanted.append(icon_name)
            elif icon_name:
                skipped += 1
            self.assertEqual(
                not item.icon().isNull(), has_icon,
                f"row {profile.name}: icon presence does not follow the theme lookup",
            )
        self.assertEqual(requested, wanted, "the theme was asked for the wrong names")
        self.assertTrue(wanted, "no row exercised the mapping at all")
        self.assertTrue(
            skipped, "no row had a mapped icon the theme lacks, so the guard is untested",
        )
        self.sidebar._rebuild(self.sidebar._running)
        for row in range(self.sidebar.list.count()):
            self.assertTrue(self.sidebar.list.item(row).icon().isNull())

    def test_screenshot_renders(self):
        target = Path(tempfile.gettempdir()) / "legion-powerctl-gui-offscreen.png"
        image = self.window.grab()
        self.assertFalse(image.size().isEmpty())
        self.assertTrue(image.save(str(target)))

    def test_the_row_carries_everything_the_delegate_paints(self):
        from legion_powerctl_gui.profile_delegate import BOOT_ROLE, DETAIL_ROLE, RUNNING_ROLE

        running = self._item("balanced-plus")
        self.assertTrue(running.data(RUNNING_ROLE))
        self.assertTrue(running.data(BOOT_ROLE))
        self.assertEqual(running.data(DETAIL_ROLE), "87/92/102 W, 80 C cap")
        self.assertFalse(self._item("quiet").data(RUNNING_ROLE))
        self.assertFalse(self._item("quiet").data(BOOT_ROLE))
        self.assertEqual(self._item("broken").data(DETAIL_ROLE), "invalid profile file")

    def test_the_rail_follows_what_is_running_not_what_boots(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.profile_delegate import BOOT_ROLE, RUNNING_ROLE

        profiles = [model.Profile(name="quiet"), model.Profile(name="balanced-plus")]
        self.sidebar.set_profiles(profiles, boot="balanced-plus", select="", running="quiet")
        quiet = self._item("quiet")
        balanced = self._item("balanced-plus")
        self.assertTrue(quiet.data(RUNNING_ROLE))
        self.assertFalse(quiet.data(BOOT_ROLE))
        self.assertFalse(balanced.data(RUNNING_ROLE))
        self.assertTrue(balanced.data(BOOT_ROLE))

    def test_the_running_profile_is_marked_in_the_desktop_s_own_accent(self):
        from legion_powerctl_gui import model, theme

        self.window.resize(960, 620)
        self.window.show()
        profiles = [model.Profile(name="quiet"), model.Profile(name="balanced-plus")]
        self.sidebar.set_profiles(profiles, boot="balanced-plus", select="", running="quiet")
        self.sidebar.list.clearSelection()
        self.sidebar.list.setCurrentItem(None)
        self.app.processEvents()
        image = self.sidebar.list.viewport().grab().toImage()
        accent = theme.accent_color(self.sidebar.list.palette()).rgb()

        def rail(name):
            rect = self.sidebar.list.visualItemRect(self._item(name))
            return image.pixel(rect.left() + 1, rect.center().y())

        self.assertEqual(rail("quiet"), accent, "the running row has no accent rail")
        self.assertNotEqual(
            rail("balanced-plus"), accent,
            "the rail is on the boot profile, which is the bug this round removed",
        )

    def test_the_checks_worth_reading_are_the_ones_the_dialog_shows_first(self):
        from legion_powerctl_gui.dialogs import worst_first
        from legion_powerctl_gui.model import DoctorLine

        order = {"FAIL": 0, "WARN": 1, "OK": 2}
        lines = [
            DoctorLine("OK", "cpu", ""), DoctorLine("WARN", "smu", ""),
            DoctorLine("FAIL", "ryzenadj", ""), DoctorLine("OK", "config", ""),
        ]
        self.assertEqual(
            [line.label for line in worst_first(lines)],
            ["ryzenadj", "smu", "cpu", "config"],
            "sorted() is stable, so two checks of one severity keep the doctor's order",
        )
        self.window.checks.show()
        severities = [chip.property("severity") for chip in self.checks.chips]
        self.assertEqual(
            severities, sorted(severities, key=lambda status: order.get(status, 3)),
            "a reader starts at the top, so a FAIL below ten OKs is a FAIL nobody sees",
        )


    def _wrapped_controls(self):
        return {
            "stapm slider": self.editor.stapm_slider, "stapm spin": self.editor.stapm_spin,
            "slow slider": self.editor.slow_slider, "slow spin": self.editor.slow_spin,
            "fast slider": self.editor.fast_slider, "fast spin": self.editor.fast_spin,
            "temp slider": self.editor.temp_slider, "temp spin": self.editor.temp_spin,
        }

    def _form_controls(self):
        controls = dict(self._wrapped_controls())
        controls.update({
            "power profile": self.editor.power_profile_combo,
            "boost": self.editor.advanced.boost_combo,
            "epp": self.editor.advanced.epp_combo,
            "min freq": self.editor.advanced.min_freq_edit,
            "max freq": self.editor.advanced.max_freq_edit,
        })
        return controls

    def test_every_form_control_is_labelled(self):
        labels = {}
        for name, widget in self._form_controls().items():
            label = self.accessible_label(widget)
            with self.subTest(control=name):
                self.assertTrue(label, f"{name} announces with no label of any kind")
            labels[name] = label
        self.assertEqual(
            len(set(labels.values())), len(labels),
            f"two controls are labelled identically, so they cannot be told apart: {labels}",
        )

    def test_the_wrapped_controls_carry_an_explicit_name(self):
        names = {}
        for name, widget in self._wrapped_controls().items():
            with self.subTest(control=name):
                self.assertTrue(widget.accessibleName(), f"{name} has no accessible name")
                self.assertEqual(self.accessible_name(widget), widget.accessibleName())
            names[name] = widget.accessibleName()
        self.assertEqual(len(set(names.values())), len(names), names)

    def test_the_power_controls_say_which_limit_they_set(self):
        for widget, expected in (
            (self.editor.stapm_slider, "Sustained (STAPM)"),
            (self.editor.slow_slider, "Slow PPT"),
            (self.editor.fast_slider, "Fast PPT"),
            (self.editor.temp_slider, "Temperature ceiling"),
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.accessible_name(widget))
        self.assertIn("watts", self.accessible_name(self.editor.stapm_spin))
        self.assertIn("5 to 200", self.editor.stapm_spin.accessibleDescription())

    def test_every_check_is_focusable_and_carries_its_own_detail(self):
        from PySide6.QtCore import Qt

        self.window.checks.show()
        self.assertTrue(self.checks.rows, "the dialog rendered no rows")
        self.assertEqual(len(self.checks.rows), len(self.window.checks.report.lines))
        for row in self.checks.rows:
            with self.subTest(row=row.accessibleName()):
                self.assertNotEqual(row.focusPolicy(), Qt.FocusPolicy.NoFocus)
        named = [row.accessibleName() for row in self.checks.rows]
        for line in self.window.checks.report.lines:
            with self.subTest(check=line.label):
                self.assertTrue(
                    any(line.label in name and line.status in name for name in named),
                    f"{line.label} is not announced with its severity",
                )
                if line.detail:
                    self.assertTrue(
                        any(line.detail in name for name in named),
                        f"the detail for {line.label} reaches nobody",
                    )

    def test_the_boot_pin_has_a_keyboard_route(self):
        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        self.assertIn(self.sidebar.boot_action, self.sidebar.list.actions())
        self.assertTrue(self.sidebar.boot_action.text())
        seen = []
        self.sidebar.boot_requested.connect(seen.append)
        self.sidebar.boot_action.trigger()
        self.assertEqual(seen, ["quiet"])

    def test_the_editor_does_not_scroll_in_two_directions(self):
        self.window.resize(720, 480)
        self.window.show()
        self.app.processEvents()
        viewport = self.window.editor_scroll.viewport()
        self.assertLessEqual(
            self.editor.minimumSizeHint().width(), viewport.width(),
            "the editor cannot be made as narrow as the space it is given",
        )
        self.assertEqual(
            self.window.editor_scroll.horizontalScrollBar().maximum(), 0,
            "there is something to the right of the editor's own viewport",
        )

    def test_the_window_fits_a_scaled_desktop(self):
        self.assertLessEqual(self.window.minimumHeight(), 540)
        self.assertLessEqual(self.window.minimumWidth(), 960)

    def test_every_control_with_a_mnemonic_claims_a_different_letter(self):
        controls = [
            self.sidebar.new_button, self.sidebar.delete_button,
            self.editor.apply_button, self.header.service_check,
            self.sidebar.boot_action,
        ]
        letters = []
        for control in controls:
            text = control.text()
            marks = text.replace("&&", "")
            index = marks.find("&")
            with self.subTest(control=text):
                self.assertNotEqual(index, -1, f"{text!r} has no mnemonic")
                letters.append(marks[index + 1].lower())
        self.assertEqual(
            len(set(letters)), len(letters),
            f"two controls claim the same Alt- key, so it cycles instead of acting: {letters}",
        )

    def test_a_validation_error_is_announced_once_per_change(self):
        with self.announcements() as announce:
            self.editor.advanced.min_freq_edit.setCurrentText("99")
            self.editor._on_edited()
            self.assertEqual(announce.call_count, 1, "the problem was never announced")
            self.assertIn("frequency", self.spoken(announce.call_args))
            self.editor._on_edited()
            self.assertEqual(
                announce.call_count, 1,
                "the same problem announced twice interrupts the user mid-edit",
            )

    def test_an_unchanged_problem_is_not_re_announced_by_the_refresh_poll(self):
        with self.announcements() as announce:
            self.sidebar.list.setCurrentRow(self._row_of("broken"))
            self.assertEqual(announce.call_count, 1, "the problem was never announced")
            for expected in (2, 3):
                self.window.refresh()
                self.assertTrue(
                    wait_until(self.app, lambda n=expected: self.window.refresh_count >= n)
                )
                self.settle(5)
            self.assertEqual(
                announce.call_count, 1,
                "an idle refresh repeated the same message; at fifteen-second "
                "intervals that is an interruption with no new information",
            )

    def test_announcing_leaves_no_name_contradicting_what_is_on_screen(self):
        from legion_powerctl_gui import a11y

        for announcement_event in (a11y.QAccessibleAnnouncementEvent, None):
            with self.subTest(announcement_event=announcement_event):
                with unittest.mock.patch.object(
                    a11y, "QAccessibleAnnouncementEvent", announcement_event
                ):
                    self.editor.advanced.min_freq_edit.setCurrentText("99")
                    self.editor._on_edited()
                    self.assertIn("frequency", self.editor.problems_label.text())
                    self.editor.advanced.min_freq_edit.setCurrentText("unchanged")
                    self.editor._on_edited()
                self.assertEqual(self.editor.problems_label.text(), "")
                self.assertEqual(
                    self.accessible_name(self.editor.problems_label), "",
                    "the label announces a problem that is neither on screen nor true",
                )

    def test_the_problems_label_says_problem(self):
        self.editor.advanced.min_freq_edit.setCurrentText("99")
        self.editor._on_edited()
        self.assertTrue(self.editor.problems_label.text().startswith("Problem:"))

    def test_a_changed_doctor_verdict_is_announced_and_an_unchanged_one_is_not(self):
        from legion_powerctl_gui import model

        with self.announcements() as announce:
            self.window.checks.run()
            self.assertTrue(wait_until(self.app, lambda: self.window.checks.count >= 2))
            self.settle(5)
            self.assertFalse(
                any("Doctor:" in self.spoken(call) for call in announce.call_args_list),
                "the same verdict was announced twice",
            )
            self.header.show_checks(
                model.DoctorReport(
                    lines=[model.DoctorLine("FAIL", "RyzenAdj", "not installed")],
                    failures=1, warnings=0, exit_code=1,
                )
            )
            self.assertTrue(
                any("1 failure(s)" in self.spoken(call) for call in announce.call_args_list),
                "a machine that just started failing said nothing",
            )

    def test_a_success_message_survives_the_refresh_that_follows_it(self):
        self.window.profile_actions.handle_result(
            0, "", "", message="Saved profile 'quiet'."
        )
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count >= 2))
        self.settle()
        self.assertEqual(
            self.window.statusBar().currentMessage(), "Saved profile 'quiet'.",
            "the refresh overwrote the message about the thing that just happened",
        )
        self.assertIn("legion-powerctl", self.window.header.machine_label.text())

    def test_go_back_is_offered_by_an_apply_and_withdrawn_by_everything_else(self):
        offer = self.window.reports.go_back_button
        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        self.assertEqual(self.editor.profile_title.text(), "quiet")
        self.window.profile_actions.apply()
        self.assertTrue(wait_until(self.app, lambda: not offer.isHidden()))
        self.assertIn("balanced-plus", offer.text())

        self.window.profile_actions.save()
        self.assertTrue(
            wait_until(self.app, lambda: offer.isHidden()),
            "a save offers to go back to a profile it did not stop running",
        )
        self.assertEqual(self.window.profile_actions.previous_profile, "")

    def test_go_back_re_applies_the_profile_that_was_displaced(self):
        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        self.window.profile_actions.apply()
        self.assertTrue(
            wait_until(self.app, lambda: not self.window.reports.go_back_button.isHidden())
        )
        self.window.reports.go_back_button.click()
        self.assertTrue(
            wait_until(self.app, lambda: any(
                line.startswith("apply balanced-plus") for line in self.read_log()
            ))
        )
        self.assertTrue(self.window.reports.go_back_button.isHidden())

    def test_a_successful_save_is_announced(self):
        with self.announcements() as announce:
            self.window.profile_actions.handle_result(
                0, "", "", message="Saved profile 'quiet'."
            )
            self.settle(5)
            self.assertIn(
                "Saved profile 'quiet'.",
                [self.spoken(call) for call in announce.call_args_list],
            )

    def test_delete_defaults_to_cancel(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QMessageBox

        seen = []

        def press_enter():
            box = self.app.activeModalWidget()
            seen.append([box.standardButton(button) for button in box.buttons()])
            seen.append(box.standardButton(box.defaultButton()))
            QTest.keyClick(box, Qt.Key.Key_Return)

        self.window.dialogs = True
        try:
            QTimer.singleShot(0, press_enter)
            self.window.profile_actions.delete()
        finally:
            self.window.dialogs = False
        self.assertEqual(len(seen), 2, "no confirmation was asked")
        self.assertIn(QMessageBox.StandardButton.Cancel, seen[0])
        self.assertEqual(
            seen[1], QMessageBox.StandardButton.Cancel,
            "Enter on the dialog deletes a profile with no undo",
        )
        self.settle(5)
        self.assertNotIn("delete", "\n".join(self.read_log()))

    def test_a_dismissed_pkexec_prompt_is_not_an_error(self):
        with unittest.mock.patch.dict(
            os.environ, {"LEGION_POWERCTL_GUI_ELEVATE": "pkexec"}
        ):
            refreshes = self.window.refresh_count
            self.editor.stapm_spin.setValue(58)
            self.editor._on_edited()
            self.window.profile_actions.handle_result(
                126, "", "", saved=self.editor.collect()
            )
        self.settle()
        self.assertFalse(self.window.errors, "Cancel raised a critical modal")
        self.assertIn("cancelled", self.window.statusBar().currentMessage().lower())
        self.assertEqual(self.window.refresh_count, refreshes)
        self.assertTrue(self.editor.dirty, "Cancel must not discard the edits")

    def test_the_same_code_from_the_cli_itself_is_still_an_error(self):
        with unittest.mock.patch.dict(os.environ, {"LEGION_POWERCTL_GUI_ELEVATE": "none"}):
            self.window.profile_actions.handle_result(126, "", "Request dismissed")
        self.assertTrue(self.window.errors)

    def test_a_crashed_child_is_not_a_success(self):
        seen = []
        self.window.runner.run(["sh", "-c", "kill -9 $$"], lambda *args: seen.append(args))
        self.assertTrue(wait_until(self.app, lambda: seen))
        code, _stdout, stderr = seen[0]
        self.assertNotEqual(code, 0, "a crash reporting 0 would clear the dirty flag")
        self.assertIn("crashed", stderr)

    def test_closing_ends_an_in_flight_command_instead_of_leaving_it(self):
        from PySide6.QtCore import QProcess

        self.window.runner.run(["sleep", "30"], lambda *args: None)
        self.app.processEvents()
        self.assertTrue(self.window.runner.processes)
        process = self.window.runner.processes[0]
        started = time.monotonic()
        self.window.close()
        elapsed = time.monotonic() - started
        self.assertEqual(self.window.runner.processes, [])
        self.assertEqual(
            process.state(), QProcess.ProcessState.NotRunning,
            "the child outlives the window, so ~QProcess kills it and then blocks "
            "the UI thread waiting - for as long as a pkexec prompt stays up",
        )
        self.assertLess(elapsed, 5.0, "closing took long enough to feel like a freeze")

    def test_closing_takes_the_child_out_of_the_window_it_would_block(self):
        self.window.runner.run(["sh", "-c", 'trap "" TERM; sleep 30'], lambda *args: None)
        self.app.processEvents()
        self.assertTrue(self.window.runner.processes)
        process = self.window.runner.processes[0]
        self.window.close()
        self.assertIsNone(
            process.parent(),
            "a child still parented to the runner is destroyed with the window",
        )
        process.waitForFinished(2000)

    def test_a_command_that_cannot_start_is_reported_by_the_window(self):
        missing = str(HERE / "there-is-no-such-binary")
        self.window.runner.run([missing], lambda *args: None)
        arrived = wait_until(self.app, lambda: any(missing in e for e in self.window.errors))
        self.assertTrue(arrived, f"never surfaced; errors: {list(self.window.errors)}")

    def test_a_warning_on_a_zero_exit_is_reported_rather_than_replaced(self):
        self.window.profile_actions.handle_result(
            0, "",
            "WARNING: Could not read the limits back from '/usr/bin/ryzenadj -i'; "
            "this apply is unverified.",
            message="Applied 'quiet'.",
        )
        self.settle(5)
        shown = self.window.statusBar().currentMessage()
        self.assertIn("Applied 'quiet'.", shown)
        self.assertIn("unverified", shown)
        self.assertFalse(
            self.window.reports.details_button.isHidden(),
            "the full output is offered nowhere",
        )
        self.assertIn("unverified", self.window.reports.last_warning)
        self.assertFalse(self.window.errors, "a warning is not an error modal")

    def test_a_clean_zero_exit_stays_a_plain_success(self):
        self.window.profile_actions.handle_result(0, "Profile applied.", "", message="Applied.")
        self.settle(5)
        self.assertEqual(self.window.statusBar().currentMessage(), "Applied.")
        self.assertTrue(self.window.reports.details_button.isHidden())

    def test_the_error_log_is_bounded(self):
        for index in range(120):
            self.window._show_error(f"failure {index}")
        self.assertLessEqual(len(self.window.errors), 50)
        self.assertIn("failure 119", self.window.errors)

    def test_the_poll_starts_again_after_one_of_them_hangs(self):
        from legion_powerctl_gui import app as app_module

        hang = Path(tempfile.mkdtemp()) / "hang"
        hang.write_text("#!/bin/sh\nsleep 30\n")
        hang.chmod(0o755)
        before = self.window.refresh_count
        with unittest.mock.patch.dict(os.environ, {"LEGION_POWERCTL_GUI_CLI": str(hang)}), \
                unittest.mock.patch.object(app_module, "POLL_TIMEOUT_MS", 300):
            self.window._refresh_timer.setInterval(50)
            self.window.refresh()
            advanced = wait_until(
                self.app, lambda: self.window.refresh_count >= before + 2, timeout=10.0
            )
        self.window._refresh_timer.setInterval(app_module.REFRESH_INTERVAL_MS)
        self.assertTrue(advanced, "the poll never resumed after a command hung")

    def test_both_polls_are_bounded_and_neither_privileged_command_is(self):
        polls, privileged = [], []

        def record(target):
            def run(argv, on_done, timeout_ms=None):
                target.append((argv, timeout_ms))
            return run

        with unittest.mock.patch.object(self.window.runner, "run", record(polls)):
            self.window.refresh()
            self.window.checks.run()
        self.assertEqual(len(polls), 2)
        for argv, timeout_ms in polls:
            self.assertIsNotNone(timeout_ms, f"{argv} can wedge the refresh for the session")

        with unittest.mock.patch.object(self.window.runner, "run", record(privileged)):
            self.window.profile_actions.set_service(False)
            self.window.profile_actions.pin_boot("quiet")
        for argv, timeout_ms in privileged:
            self.assertIsNone(
                timeout_ms, f"{argv} on a timer cancels the prompt the user is reading"
            )

    def test_the_new_profile_button_asks_nothing_when_dialogs_are_off(self):
        self.sidebar.new_button.click()
        self.settle()
        self.assertEqual(self.sidebar.drafts, set(), "a draft appeared with nothing to name it")

    def test_raising_a_limit_asks_first_and_cancelling_writes_nothing(self):
        from legion_powerctl_gui import actions as actions_module

        self.sidebar.list.setCurrentRow(self._row_of("quiet"))
        asked = {}

        def fake_confirm(parent, name, deltas):
            asked["name"] = name
            asked["deltas"] = [(d.label, d.was, d.now) for d in deltas]
            return False

        self.window.dialogs = True
        try:
            with unittest.mock.patch.object(
                actions_module.dialogs, "confirm_raise", fake_confirm
            ):
                self.editor.fast_spin.setValue(110)
                self.editor.temp_spin.setValue(88)
                self.editor._on_edited()
                self.window.profile_actions.apply()
                self.settle(5)
        finally:
            self.window.dialogs = False
        self.assertEqual(asked.get("name"), "quiet")
        self.assertIn(("Fast PPT", 102, 110), asked["deltas"])
        self.assertIn(("Ceiling", 80, 88), asked["deltas"])
        self.assertFalse(
            any("configure" in line for line in self.read_log()),
            "Cancel still wrote to the hardware",
        )

    def test_lowering_a_limit_is_not_confirmed(self):
        from legion_powerctl_gui import actions as actions_module

        self.window.dialogs = True
        try:
            with unittest.mock.patch.object(
                actions_module.dialogs, "confirm_raise"
            ) as confirm:
                self.editor.stapm_spin.setValue(40)
                self.editor._on_edited()
                self.window.profile_actions.apply()
                self.assertTrue(
                    wait_until(
                        self.app,
                        lambda: any("configure" in line for line in self.read_log()),
                    )
                )
        finally:
            self.window.dialogs = False
        confirm.assert_not_called()

    def test_the_containers_say_what_they_hold(self):
        containers = {
            "profile list": self.sidebar.list,
            "system checks": self.checks.scroll,
            "editor column": self.window.editor_scroll,
        }
        names = {}
        for what, widget in containers.items():
            name = self.accessible_name(widget)
            self.assertTrue(name, f"the {what} reaches a screen reader with no name at all")
            names[what] = name
        self.assertEqual(
            len(set(names.values())), len(names),
            f"two panes announce the same thing, so neither identifies itself: {names}",
        )

    def test_naming_a_pane_never_costs_the_value_it_displays(self):
        header = self.window.header
        for what, label in (
            ("the envelope summary", header.envelope_label),
            ("the boot profile", header.boot_label),
            ("the service badge", header.service_label),
            ("the machine summary", header.machine_label),
            ("the editor title", self.editor.profile_title),
        ):
            text = label.text()
            if not text:
                continue
            self.assertIn(
                text, self.accessible_name(label),
                f"{what} announces a static name instead of what it is showing",
            )
        spoken = self.accessible_name(header.running_label)
        self.assertIn(header.running_label.text(), spoken)
        self.assertIn("Running now", spoken)


    def _top(self, widget) -> int:
        from PySide6.QtCore import QPoint

        return widget.mapTo(self.header, QPoint(0, 0)).y()

    def test_the_strip_moves_its_actions_below_the_facts_on_a_narrow_window(self):
        header = self.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        running_bottom = self._top(header.running_label) + header.running_label.height()
        self.assertLess(
            self._top(header.checks_button), running_bottom,
            "at 960 the actions share the row with what is running",
        )
        wide = header.height()

        self.window.resize(720, 480)
        self.app.processEvents()
        running_bottom = self._top(header.running_label) + header.running_label.height()
        for control in (header.service_check, header.checks_button):
            with self.subTest(control=control.text()):
                self.assertGreaterEqual(
                    self._top(control), running_bottom,
                    "at 720 the actions cell still squeezes the running cell",
                )
        self.assertGreater(header.height(), wide)
        right = header.checks_button.mapTo(header, header.checks_button.rect().topRight()).x()
        self.assertGreater(right, header.width() * 3 // 4, "the wrapped actions are not right aligned")

        self.window.resize(960, 620)
        self.app.processEvents()
        self.assertEqual(header.height(), wide, "widening again does not restore one row")

    def test_the_strip_reflows_as_soon_as_a_longer_name_arrives(self):
        import dataclasses

        header = self.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        status = self.window.status
        partial = dict(status.last_apply, result="partial")
        for record, wrapped in ((partial, True), (status.last_apply, False)):
            header.show_status(dataclasses.replace(status, last_apply=record))
            self.app.processEvents()
            running_bottom = self._top(header.running_label) + header.running_label.height()
            with self.subTest(running=header.running_label.text()):
                self.assertEqual(
                    self._top(header.checks_button) >= running_bottom, wrapped,
                    "the strip kept the row it measured before the running name changed",
                )

    def test_the_strip_is_eighty_tall_at_the_default_size(self):
        from legion_powerctl_gui import styles

        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.header.height(), styles.STRIP_HEIGHT)

    def test_the_readout_paints_the_four_limits_and_keeps_the_summary_as_its_text(self):
        from legion_powerctl_gui.strip_widgets import Readout

        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        readout = self.header.envelope_label
        self.assertEqual(readout.text(), "87/92/102 W, 80 C cap")
        self.assertIn(readout.text(), self.accessible_name(readout))
        self.assertEqual(readout.tiles, [
            ("87", "W", "SUSTAINED"), ("92", "W", "SLOW PPT"),
            ("102", "W", "FAST PPT"), ("80", "°C", "CEILING"),
        ])
        self.assertEqual(readout.height(), readout.tile_height())
        widths = sum(readout.tile_widths())
        self.assertEqual(readout.sizeHint().width(), widths + 3 * Readout.GAP)
        self.assertEqual(readout.minimumSizeHint().width(), widths + 3 * Readout.MIN_GAP)
        ink, _fail, muted, cap = self.readout_inks(readout)
        image = readout.grab().toImage()
        self.assertIn(ink, self.colours_in_rows(image, 0, cap), "the figures are not in the ink")
        captions = self.colours_in_rows(image, cap + Readout.CAPTION_GAP, image.height())
        self.assertIn(muted, captions, "the captions are not in the muted ink")
        self.assertNotIn(ink, captions, "the captions are as loud as the figures")
        spans = self.ink_spans(image, *self.caption_rows(readout), Readout.MIN_GAP)
        self.assertEqual(len(spans), 4, f"the captions run into each other: {spans}")
        room = (readout.width() - widths) // 3
        for left, right in zip(spans, spans[1:]):
            self.assertGreaterEqual(
                right[0] - left[1] - 1, max(Readout.MIN_GAP, min(Readout.GAP, room)),
                "the tiles are crowded with room to spare",
            )
        right_edge = self.ink_spans(image, 0, image.height(), 1)[-1][1]
        self.assertGreaterEqual(right_edge, image.width() - 3, "the readout is not flush right")

    def test_the_readout_closes_its_gaps_before_it_cuts_a_figure(self):
        from legion_powerctl_gui import runstate
        from legion_powerctl_gui.strip_widgets import Readout

        readout = Readout()
        self.addCleanup(readout.deleteLater)
        readout.set_state(runstate.run_state(self.window.status), "OK")
        least = readout.minimumSizeHint()
        inked, gaps = {}, {}
        for width in (least.width() + 120, least.width()):
            readout.resize(width, least.height())
            bands = {"figures": (0, readout.tile_height() // 2), "captions": self.caption_rows(readout)}
            image = readout.grab().toImage()
            for band, rows in bands.items():
                spans = self.ink_spans(image, *rows, 1)
                inked[width, band] = sum(right - left + 1 for left, right in spans)
            captions = self.ink_spans(image, *bands["captions"], Readout.MIN_GAP)
            gaps[width] = [right[0] - left[1] - 1 for left, right in zip(captions, captions[1:])]
            with self.subTest(width=width):
                self.assertEqual(len(captions), 4, f"the captions run into each other: {captions}")
                right_edge = self.ink_spans(image, 0, image.height(), 1)[-1][1]
                self.assertGreaterEqual(right_edge, width - 3, "the readout is not flush right")
        roomy, tight = least.width() + 120, least.width()
        for band in bands:
            with self.subTest(band=band):
                self.assertEqual(
                    inked[tight, band], inked[roomy, band],
                    "at its minimum width the readout cut part of a tile off",
                )
        self.assertLess(max(gaps[tight]), Readout.GAP, "the gaps did not close")
        self.assertGreaterEqual(min(gaps[roomy]), Readout.GAP)

    def test_the_apply_record_sits_on_the_eyebrow_line_and_the_fact_below_it(self):
        header = self.header
        mark, when = header.mark_label, header.when_label
        name, readout = header.running_label, header.envelope_label
        self.window.show()
        for size in ((960, 620), (720, 480)):
            self.window.resize(*size)
            self.app.processEvents()
            with self.subTest(size=size):
                self.assertLess(self._top(mark), self._top(name))
                self.assertLessEqual(
                    abs(self._top(mark) + mark.height() // 2
                        - (self._top(when) + when.height() // 2)), 2,
                    "the badge and the time are not on one line",
                )
                self.assertLess(self._top(readout), self._top(name) + name.height())
                self.assertLess(self._top(name), self._top(readout) + readout.height())
                self.assertEqual(
                    readout.mapTo(header, readout.rect().topRight()).x(),
                    when.mapTo(header, when.rect().topRight()).x(),
                    "the readout is not flush with the time above it",
                )

    def test_the_badge_is_still_read_after_the_facts_it_qualifies(self):
        from PySide6.QtGui import QAccessible

        header = self.header
        cell = QAccessible.queryAccessibleInterface(header.run_caption.parentWidget())
        read = [cell.child(index).object() for index in range(cell.childCount())]
        self.assertEqual(read, [
            header.run_caption, header.when_label, header.rail,
            header.running_label, header.envelope_label, header.mark_label,
        ])

    def test_the_running_name_is_set_in_the_title_voice(self):
        from legion_powerctl_gui import theme

        header = self.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        title = theme.font("title")
        self.assertAlmostEqual(header.running_label.font().pointSizeF(), title.pointSizeF())
        self.assertEqual(header.running_label.font().weight(), title.weight())
        self.assertEqual(header.rail.height(), header.envelope_label.tile_height())
        self.assertEqual(self._top(header.rail), self._top(header.envelope_label))

    def test_the_readout_and_its_rail_follow_the_desktop_font(self):
        header = self.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        before = header.envelope_label.tile_height()
        self.use_app_font_size(self.app.font().pointSizeF() + 3)
        self.app.processEvents()
        self.assertGreater(header.envelope_label.tile_height(), before)
        self.assertEqual(header.rail.height(), header.envelope_label.tile_height())

    def test_a_palette_change_restyles_the_strip_the_status_bar_and_the_checks(self):
        from legion_powerctl_gui import scheme, theme
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtGui import QPalette

        self.window.resize(960, 620)
        self.window.show()
        self.window.checks.show()
        self.assertTrue(self.checks.rows, "no rows to restyle")
        dark = scheme.palette(True)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.addCleanup(self.app.setPalette, QPalette(self.app.palette()))
        self.app.setPalette(dark)
        self.app.setStyleSheet(self.app.styleSheet())
        self.app.processEvents()

        plane = dark.color(QPalette.ColorRole.Window)
        surface = self.header.grab().toImage().pixelColor(6, self.header.height() // 2)
        self.assertEqual(surface.name(), dark.color(QPalette.ColorRole.Base).name())
        self.assertIn(
            theme.muted_color(dark, plane).name(), self.header.machine_label.styleSheet()
        )
        link = theme.fit_contrast(theme.accent_color(dark), plane, theme.MIN_CONTRAST)
        for offer in (self.window.reports.go_back_button, self.window.reports.details_button):
            with self.subTest(offer=offer.text()):
                self.assertIn(link.name(), offer.styleSheet())
        for row in self.checks.rows:
            with self.subTest(row=row.accessibleName()):
                self.assertIn(
                    theme.severity_color(dark, row.chip.property("severity")).name(),
                    row.chip.styleSheet(),
                )
                self.assertIn(
                    theme.secondary_color(dark, plane).name(), row.detail.styleSheet()
                )

    def test_the_go_back_offer_makes_room_for_the_message_it_follows(self):
        bar = self.window.statusBar()
        offer = self.window.reports.go_back_button
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        self.window.reports.success("Applied 'quiet'.", "balanced-plus")
        self.app.processEvents()
        beside = offer.sizeHint().width()
        bar.clearMessage()
        self.app.processEvents()
        alone = offer.sizeHint().width()
        self.assertGreaterEqual(
            beside - alone, bar.fontMetrics().horizontalAdvance("Applied 'quiet'."),
            "the offer is drawn under the message instead of after it",
        )
        self.assertFalse(offer.isHidden(), "the offer went away with the message")

    def test_a_long_warning_keeps_its_offer_in_sight(self):
        reports = self.window.reports
        self.window.resize(720, 480)
        self.window.show()
        self.app.processEvents()
        reports.warning("Applied 'quiet'.", "WARNING: " + "the limits could not be read back " * 8)
        self.app.processEvents()
        details = reports.details_button
        machine = self.header.machine_label
        self.assertFalse(details.isHidden())
        self.assertGreaterEqual(
            details.width(), details.sizeHint().width(),
            "the room left for the message squeezes the Details offer out of sight",
        )
        self.assertLessEqual(
            details.geometry().right(), machine.geometry().left(),
            "the Details offer is drawn over the version it sits beside",
        )

    def test_the_switch_keeps_its_focus_ring_through_a_busy_spell(self):
        from PySide6.QtCore import Qt

        switch = self.header.service_check
        self.window.resize(960, 620)
        self.window.show()
        self.window.activateWindow()
        self.settle(5)
        opened = switch.grab().toImage()
        switch.clearFocus()
        self.settle(3)
        resting = switch.grab().toImage()
        self.assertEqual(opened, resting, "opening the window paints a keyboard ring")
        switch.setFocus(Qt.FocusReason.TabFocusReason)
        self.settle(3)
        ringed = switch.grab().toImage()
        self.assertNotEqual(ringed, resting, "keyboard focus draws no ring")
        self.window._set_busy(True)
        self.settle(3)
        self.window._set_busy(False)
        self.settle(3)
        self.assertTrue(switch.hasFocus(), "the focus did not come back after the command")
        self.assertEqual(switch.grab().toImage(), ringed, "the ring did not come back with it")
        switch.clearFocus()
        switch.setFocus(Qt.FocusReason.MouseFocusReason)
        self.settle(3)
        self.assertEqual(switch.grab().toImage(), resting, "a click draws the keyboard ring")
        self.window._set_busy(True)
        self.settle(3)
        self.window._set_busy(False)
        self.settle(3)
        self.assertTrue(switch.hasFocus())
        self.assertEqual(
            switch.grab().toImage(), resting, "the refocus after a clicked command draws the ring"
        )

    def test_the_switch_keeps_its_ring_or_its_absence_across_window_activation(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget

        switch = self.header.service_check
        other = QWidget()
        self.addCleanup(other.deleteLater)
        self.window.resize(960, 620)
        self.window.show()
        self.window.activateWindow()
        self.settle(5)
        for reason in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.MouseFocusReason):
            switch.clearFocus()
            switch.setFocus(reason)
            self.settle(3)
            before = switch.grab().toImage()
            other.show()
            other.activateWindow()
            self.settle(3)
            self.assertFalse(switch.hasFocus(), "the other window never took the focus")
            self.window.activateWindow()
            self.settle(3)
            with self.subTest(reason=reason.name):
                self.assertTrue(switch.hasFocus(), "activation did not hand the focus back")
                self.assertEqual(switch.grab().toImage(), before)
            other.hide()

    def test_an_offer_stays_in_sight_when_the_window_narrows(self):
        reports = self.window.reports
        machine = self.header.machine_label
        self.window.resize(1100, 620)
        self.window.show()
        self.settle(5)
        reports.warning("Applied 'quiet'.", "WARNING: " + "the limits could not be read back " * 8)
        self.settle(5)
        for offer, show in (
            (reports.details_button, lambda: None),
            (reports.go_back_button, lambda: reports.success("Applied 'quiet'.", "balanced-plus")),
        ):
            show()
            self.window.resize(1100, 620)
            self.settle(5)
            self.window.resize(720, 620)
            self.settle(5)
            with self.subTest(offer=offer.text()):
                self.assertFalse(offer.isHidden())
                self.assertGreaterEqual(
                    offer.width(), offer.sizeHint().width(),
                    "the offer keeps the margin it had in a wider window and draws out of sight",
                )
                self.assertLessEqual(offer.geometry().right(), machine.geometry().left())


class RunnerTimeoutTest(OffscreenGuiTest):
    def setUp(self):
        from legion_powerctl_gui.runner import CommandRunner

        self.runner = CommandRunner()
        self.tmp = Path(tempfile.mkdtemp())
        self.hang = self.tmp / "hang"
        self.hang.write_text("#!/bin/sh\nsleep 30\n")
        self.hang.chmod(0o755)

    def tearDown(self):
        self.runner.stop_all()
        self.app.processEvents()

    def test_a_hung_command_is_given_up_on_rather_than_waited_for_forever(self):
        from legion_powerctl_gui.runner import TIMED_OUT

        seen = []
        self.runner.run([str(self.hang)], lambda *args: seen.append(args), timeout_ms=200)
        self.assertTrue(
            wait_until(self.app, lambda: seen, timeout=10.0),
            "a command that never returns was never given up on",
        )
        code, _stdout, stderr = seen[0]
        self.assertEqual(code, TIMED_OUT)
        self.assertNotIn(code, (126, 127))
        self.assertIn("did not finish", stderr)

    def test_a_timed_out_process_is_not_left_running_behind_the_window(self):
        seen = []
        self.runner.run([str(self.hang)], lambda *args: seen.append(args), timeout_ms=200)
        self.assertTrue(wait_until(self.app, lambda: seen, timeout=10.0))
        self.assertEqual(
            self.runner.processes, [], "the timed-out child is still on the runner's list"
        )

    def test_a_command_that_finishes_in_time_is_not_reported_as_timed_out(self):
        seen = []
        self.runner.run(["sh", "-c", "exit 0"], lambda *args: seen.append(args), timeout_ms=300)
        self.assertTrue(wait_until(self.app, lambda: seen, timeout=10.0))
        self.assertEqual(seen[0][0], 0)
        self.settle(60)
        self.assertEqual(len(seen), 1, f"the deadline reported a finished command again: {seen}")

    def test_an_elevated_command_is_not_timed_out_while_the_prompt_is_up(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.actions import ProfileActions
        from PySide6.QtWidgets import QWidget

        calls = []

        class RecordingRunner:
            def run(self, argv, on_done, timeout_ms=None):
                calls.append((argv, timeout_ms))

        window = QWidget()
        window.dialogs = False
        editor = unittest.mock.MagicMock()
        editor.collect.return_value = model.Profile(
            name="quiet", stapm_w=40, slow_w=45, fast_w=50, temp_c=75,
            power_profile="power-saver", min_freq_mhz="stock", max_freq_mhz="stock",
            boost="off", epp="power", description="",
        )
        editor.problems.return_value = []
        actions = ProfileActions(window, RecordingRunner(), editor, unittest.mock.MagicMock())
        actions.save()
        self.assertTrue(calls, "save never reached the runner")
        argv, timeout_ms = calls[-1]
        self.assertIn("configure", argv)
        self.assertIsNone(
            timeout_ms, "a privileged command on a timer cancels the save being authorised"
        )


class PanelSeamTest(OffscreenGuiTest):
    def test_balanced_plus_editor_caps_both_temperature_controls_at_80(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="balanced-plus", temp_c=80))
            self.assertEqual(editor.temp_spin.maximum(), 80)
            self.assertEqual(editor.temp_slider.maximum(), 80)
            editor.temp_spin.setValue(90)
            self.assertEqual(editor.collect().temp_c, 80)
            self.assertEqual(editor.problems(), [])
        finally:
            editor.deleteLater()

    def test_temperature_range_follows_the_profile_when_switching(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="balanced-plus", temp_c=80))
            editor.load(model.Profile(name="trial", temp_c=90))
            self.assertEqual(editor.temp_spin.maximum(), model.TEMP_MAX_C)
            self.assertEqual(editor.temp_slider.maximum(), model.TEMP_MAX_C)
            self.assertEqual(editor.collect().temp_c, 90)
            editor.load(model.Profile(name="balanced-plus", temp_c=80))
            self.assertEqual(editor.temp_spin.maximum(), 80)
            self.assertEqual(editor.collect().temp_c, 80)
        finally:
            editor.deleteLater()

    def test_the_editor_reads_and_validates_without_a_window(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            self.assertEqual(editor.problems(), [], "nothing is open; there is nothing wrong")
            profile = model.Profile(name="lab", stapm_w=45, slow_w=50, fast_w=55, temp_c=90)
            editor.load(profile)
            self.assertEqual(editor.collect(), profile)
            self.assertFalse(editor.dirty)
            editor.advanced.min_freq_edit.setCurrentText("99")
            editor._on_edited()
            self.assertTrue(editor.dirty)
            self.assertIn("frequency", "\n".join(editor.problems()))
        finally:
            editor.deleteLater()

    def test_a_description_survives_an_edit_that_cannot_see_it(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="quiet", description="Cooler and quieter."))
            editor.stapm_spin.setValue(40)
            editor._on_edited()
            self.assertEqual(editor.collect().description, "Cooler and quieter.")
        finally:
            editor.deleteLater()

    def test_the_advanced_panel_opens_itself_for_a_profile_that_uses_it(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="plain"))
            self.assertFalse(editor.advanced.panel.isVisibleTo(editor))
            editor.load(model.Profile(name="widened", boost="on", max_freq_mhz="stock"))
            self.assertTrue(editor.advanced.button.isChecked())
            self.assertTrue(editor.advanced.panel.isVisibleTo(editor))
        finally:
            editor.deleteLater()

    def test_the_combos_read_as_words_and_still_send_the_cli_its_own_value(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="p", boost="unchanged"))
            self.assertEqual(editor.advanced.boost_combo.currentText(), "Leave as is")
            self.assertEqual(editor.collect().boost, "unchanged")
            self.assertEqual(editor.collect().power_profile, "balanced")

            editor.load(model.Profile(name="p", max_freq_mhz="stock"))
            self.assertIn("raises the limit", editor.advanced.max_freq_edit.currentText())
            self.assertEqual(editor.collect().max_freq_mhz, "stock")

            editor.advanced.max_freq_edit.setCurrentText("4200")
            self.assertEqual(editor.collect().max_freq_mhz, "4200")
        finally:
            editor.deleteLater()

    def test_the_sidebar_creates_a_draft_before_any_status_has_arrived(self):
        from legion_powerctl_gui.sidebar import ProfileList

        sidebar = ProfileList()
        refusals = []
        sidebar.refused.connect(refusals.append)
        try:
            sidebar.create_draft("fresh")
            self.assertEqual(refusals, [], "a first profile on an empty list is not a clash")
            self.assertIn("fresh", sidebar.drafts)
            self.assertEqual(sidebar.list.count(), 1)
            sidebar.create_draft("not a name")
            self.assertTrue(refusals)
            self.assertNotIn("not a name", sidebar.drafts)
        finally:
            sidebar.deleteLater()

    def test_the_header_renders_a_status_without_a_window(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.header import MachineHeader

        header = MachineHeader("9.9.9")
        try:
            header.show_status(model.Status(
                version="0.3.0", active_profile="quiet", power_profile="balanced",
                cpu_driver="amd-pstate-epp", cpu_epp="power", ryzenadj=None,
                service_enabled="enabled", service_active="failed", last_apply=None,
            ))
            self.assertEqual(header.running_label.text(), "Firmware defaults")
            self.assertIn("nothing applied", header.envelope_label.text())
            self.assertIn("quiet", header.boot_label.text())
            self.assertEqual(header.service_label.property("severity"), "FAIL")
            self.assertTrue(header.service_label.text().startswith("FAIL "))
            summary = header.machine_label.text()
            for part in ("0.3.0", "9.9.9", "ryzenadj missing"):
                with self.subTest(part=part):
                    self.assertIn(part, summary)
        finally:
            header.deleteLater()

    def test_the_header_separates_what_runs_from_what_boots(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.header import MachineHeader

        header = MachineHeader("9.9.9")
        try:
            header.show_status(model.Status(
                version="0.3.0", active_profile="balanced-plus", power_profile="balanced",
                cpu_driver="amd-pstate-epp", cpu_epp="power", ryzenadj="/usr/bin/ryzenadj",
                service_enabled="enabled", service_active="active",
                last_apply={
                    "profile": "quiet", "result": "ok", "verified": "yes",
                    "stapm_w": "45", "slow_w": "50", "fast_w": "60", "temp_c": "78",
                },
            ))
            self.assertEqual(header.running_label.text(), "quiet")
            self.assertEqual(header.envelope_label.text(), "45/50/60 W, 78 C cap")
            self.assertEqual(header.boot_label.text(), "balanced-plus")
            self.assertEqual(header.same_label.text(), "")
            self.assertEqual(header.mark_label.text(), "confirmed")
        finally:
            header.deleteLater()

    def test_the_checks_dialog_says_so_when_the_run_produced_nothing(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.dialogs import ChecksDialog

        dialog = ChecksDialog()
        try:
            self.assertFalse(
                dialog.copy_button.isEnabled(),
                "there is nothing to copy before the first run",
            )
            dialog.show_report(model.DoctorReport(
                lines=[model.DoctorLine("WARN", "RyzenAdj", "0.14.0 is older than 0.19.0")],
                failures=0, warnings=1, exit_code=1,
            ))
            self.assertTrue(dialog.copy_button.isEnabled())
            self.assertEqual(len(dialog.rows), 1)
            self.assertIn("0.14.0", dialog.rows[0].accessibleName())
            self.assertIn("0 failure(s), 1 warning(s)", dialog.summary.text())
            dialog.show_report(
                model.DoctorReport(lines=[], failures=0, warnings=0, exit_code=1)
            )
            self.assertEqual(dialog.rows, [])
            self.assertIn("could not run", dialog.summary.text())
            dialog.show_report(
                model.DoctorReport(lines=[], failures=0, warnings=0, exit_code=0)
            )
            self.assertIn("no results", dialog.summary.text())
        finally:
            dialog.deleteLater()

    def test_the_copied_report_names_the_tool_and_repeats_the_output_verbatim(self):
        from legion_powerctl_gui import dialogs, model

        raw = (
            "OK    CPU                      AMD processor detected\n"
            "WARN  SMU-backend              no /sys/kernel/ryzen_smu_drv and no ryzen_smu module\n"
            "\nDoctor result: 0 failure(s), 1 warning(s).\n"
        )
        report = model.parse_doctor(raw, 0)
        text = dialogs.report_text(report, "", "legion-powerctl 9.9.9 | GUI 9.9.9")

        self.assertTrue(text.startswith("legion-powerctl doctor report\n"))
        self.assertIn("legion-powerctl 9.9.9 | GUI 9.9.9", text)
        self.assertIn("Doctor: 0 failure(s), 1 warning(s)", text)
        self.assertIn(raw.strip("\n"), text, "the paste has to match what the terminal printed")
        self.assertNotIn("Errors reported", text)
        self.assertNotIn("(exit", text)

    def test_a_doctor_that_could_not_run_is_still_worth_copying(self):
        from legion_powerctl_gui import dialogs, model

        report = model.DoctorReport(lines=[], failures=0, warnings=0, exit_code=127, text="")
        text = dialogs.report_text(report, "legion-powerctl: command not found", "GUI 9.9.9")

        self.assertIn("could not run", text)
        self.assertIn("(exit 127)", text)
        self.assertIn("Errors reported by the command:", text)
        self.assertIn("legion-powerctl: command not found", text)

    def test_a_draft_stops_being_one_once_the_cli_reports_it(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.sidebar import ProfileList

        sidebar = ProfileList()
        try:
            sidebar.create_draft("fresh")
            sidebar.set_profiles([model.Profile(name="fresh")], "fresh", "")
            self.assertNotIn("fresh", sidebar.drafts)
            self.assertEqual(
                sidebar.list.count(), 1,
                "the saved profile and its own draft row are both listed, so the "
                "sidebar offers two rows with the same name",
            )
        finally:
            sidebar.deleteLater()

    def test_the_runner_reports_a_command_that_cannot_start(self):
        from legion_powerctl_gui.runner import CommandRunner
        from PySide6.QtCore import QObject

        owner = QObject()
        runner = CommandRunner(owner)
        seen = []
        runner.failed.connect(seen.append)
        runner.run([str(HERE / "no-such-binary"), "status"], lambda *args: None)
        self.assertTrue(wait_until(self.app, lambda: seen))
        self.assertIn("Could not run", seen[0])
        self.assertEqual(runner.processes, [])
        self.settle(3)


    def test_a_chip_keeps_its_height_on_a_row_that_wraps(self):
        from legion_powerctl_gui import model, styles
        from legion_powerctl_gui.dialogs import ChecksDialog
        from PySide6.QtWidgets import QSizePolicy

        dialog = ChecksDialog()
        try:
            dialog.resize(640, 480)
            dialog.show_report(model.DoctorReport(
                lines=[
                    model.DoctorLine("WARN", "SMU-backend", "no ryzen_smu module " * 12),
                    model.DoctorLine("OK", "CPU", "AMD processor detected"),
                ],
                failures=0, warnings=1, exit_code=0,
            ))
            dialog.show()
            self.settle(5)
            wrapped, single = dialog.rows
            self.assertGreater(wrapped.height(), single.height(), "the long detail did not wrap")
            for row in dialog.rows:
                with self.subTest(row=row.chip.text()):
                    self.assertEqual(row.chip.height(), styles.BADGE_HEIGHT)
                    self.assertEqual(
                        row.chip.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Fixed
                    )
            self.assertEqual(
                wrapped.chip.y(), single.chip.y(), "the chip on the long row is not at its top"
            )
        finally:
            dialog.deleteLater()

    def test_badges_and_chips_grow_with_their_font_rather_than_clipping_it(self):
        from legion_powerctl_gui import styles
        from legion_powerctl_gui.checks_view import CheckRow
        from legion_powerctl_gui.header import MachineHeader
        from legion_powerctl_gui.model import DoctorLine
        from PySide6.QtGui import QFont

        header = MachineHeader("9.9.9")
        row = CheckRow(DoctorLine("WARN", "Conflicts", "tlp.service is active"), self.app.palette())
        try:
            badges = (header.mark_label, header.service_label, header.checks_button, row.chip)
            for badge in badges:
                self.assertEqual(badge.height(), styles.BADGE_HEIGHT)
                large = QFont(badge.font())
                large.setPointSizeF(24.0)
                badge.setFont(large)
                with self.subTest(badge=type(badge).__name__):
                    self.assertGreater(badge.height(), styles.BADGE_HEIGHT)
                    self.assertGreaterEqual(
                        badge.height(), badge.fontMetrics().height() + styles.BADGE_CHROME,
                        "the text is taller than the badge drawn around it",
                    )
        finally:
            header.deleteLater()
            row.deleteLater()

    def test_a_message_box_marks_the_action_and_keeps_the_safe_default(self):
        from legion_powerctl_gui import dialogs, runstate
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox, QWidget

        parent = QWidget()
        seen = {}

        def answer(name):
            box = self.app.activeModalWidget()
            seen[name] = (
                [
                    b.text().replace("&", "") for b in box.buttons()
                    if b.property("kind") == "primary"
                ],
                box.defaultButton().text().replace("&", ""),
                box.focusWidget() is box.defaultButton(),
            )
            box.button(QMessageBox.StandardButton.Cancel).click()

        cases = {
            "raise": (lambda: dialogs.confirm_raise(
                parent, "quiet", [runstate.Delta("Fast PPT", 102, 110, "W")]
            ), "Apply anyway", "Cancel"),
            "enable": (lambda: dialogs.confirm_enable(parent, "quiet"), "Enable", "Enable"),
            "repair": (lambda: dialogs.confirm_repair(parent), "Repair and apply", "Cancel"),
            "force": (
                lambda: dialogs.offer_force_enable(parent, "doctor reported failures"),
                "Enable anyway", "Cancel",
            ),
            "discard": (
                lambda: dialogs.confirm_discard(parent, "quiet", "balanced-plus")
                != QMessageBox.StandardButton.Cancel,
                "Discard", "Cancel",
            ),
            "delete": (lambda: dialogs.confirm_delete(parent, "quiet"), "Yes", "Cancel"),
        }
        try:
            for name, (run, action, default) in cases.items():
                with self.subTest(dialog=name):
                    QTimer.singleShot(0, lambda name=name: answer(name))
                    self.assertFalse(run(), "Cancel was taken as a yes")
                    primary, chosen, focused = seen[name]
                    self.assertEqual(primary, [action])
                    self.assertEqual(chosen, default, "the default moved to a riskier button")
                    self.assertTrue(focused, "the default button does not hold the focus")
        finally:
            parent.deleteLater()

    def test_the_boot_switch_is_still_a_check_box_to_everyone_but_the_eye(self):
        from legion_powerctl_gui.header import MachineHeader
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QAccessible

        header = MachineHeader("9.9.9")
        try:
            switch = header.service_check
            switch.resize(switch.sizeHint())
            interface = QAccessible.queryAccessibleInterface(switch)
            self.assertEqual(interface.role(), QAccessible.Role.CheckBox)
            self.assertEqual(interface.text(QAccessible.Text.Name), "Re-apply at every boot")
            self.assertTrue(switch.isCheckable())
            self.assertTrue(
                switch.hitButton(QPoint(switch.width() - 2, switch.height() // 2)),
                "the label beside the track does not toggle it",
            )
            self.assertGreaterEqual(switch.height(), 20)
        finally:
            header.deleteLater()


class VariantFixtureTest(OffscreenGuiTest):
    def mutate(self, document: dict) -> None:
        raise NotImplementedError

    def setUp(self):
        document = json.loads(STATUS_FIXTURE.read_text())
        self.mutate(document)
        self.fixture = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(document, self.fixture)
        self.fixture.close()
        os.environ["FAKE_CLI_STATUS_FIXTURE"] = self.fixture.name
        os.environ.pop("FAKE_CLI_LOG", None)

        from legion_powerctl_gui.app import MainWindow

        self.window = MainWindow()
        self.assertTrue(
            wait_until(self.app, lambda: self.window.refresh_count >= 1),
            f"window never loaded; errors: {list(self.window.errors)}",
        )

    def tearDown(self):
        os.environ.pop("FAKE_CLI_STATUS_FIXTURE", None)
        os.unlink(self.fixture.name)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def reopen_at_the_desktop_size(self) -> None:
        from legion_powerctl_gui.app import MainWindow

        self.window.close()
        self.window.deleteLater()
        self.use_app_font_size(DESKTOP_POINT_SIZE)
        self.window = MainWindow()
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count >= 1))

    def strip_is_one_row(self) -> bool:
        from PySide6.QtCore import QPoint

        header, name = self.window.header, self.window.header.running_label
        bottom = name.mapTo(header, QPoint(0, name.height())).y()
        return header.checks_button.mapTo(header, QPoint(0, 0)).y() < bottom

    def assert_nothing_in_the_strip_is_cut(self, *elided) -> None:
        header = self.window.header
        readout = header.envelope_label
        labels = (
            header.run_caption, header.mark_label, header.when_label, header.running_label,
            header.boot_label, header.same_label,
        )
        for label in labels:
            with self.subTest(label=label.text()):
                if label in elided:
                    floor = label.minimumWidth() or label.sizeHint().width()
                    self.assertGreaterEqual(label.width(), floor, "the layout clipped a name")
                    if label.width() < label.sizeHint().width():
                        self.assert_painted_with_an_ellipsis(label)
                elif label.isVisible():
                    self.assertGreaterEqual(label.width(), label.sizeHint().width())
        name = header.running_label
        if name.width() < name.sizeHint().width():
            self.assertEqual(
                readout.width(), readout.minimumSizeHint().width(),
                "the name lost letters while the readout still had width to give",
            )
        self.assertGreaterEqual(readout.width(), readout.minimumSizeHint().width())

    def assert_painted_with_an_ellipsis(self, label) -> None:
        from legion_powerctl_gui.strip_widgets import ElidedLabel
        from PySide6.QtCore import Qt

        room = label.contentsRect().width()
        shown = label.fontMetrics().elidedText(label.text(), Qt.TextElideMode.ElideRight, room)
        self.assertNotEqual(shown, label.text(), "the label has room for its whole text")
        twin = ElidedLabel(shown, label.parentWidget())
        twin.setFont(label.font())
        twin.setStyleSheet(label.styleSheet())
        twin.setGeometry(label.geometry())
        twin.show()
        try:
            self.assertTrue(
                twin.grab().toImage() == label.grab().toImage(),
                f"{label.text()!r} is clipped at its edge instead of reading {shown!r}",
            )
        finally:
            twin.hide()
            twin.deleteLater()


class BrokenFirstProfileTest(VariantFixtureTest):
    def mutate(self, document):
        document["profiles"].sort(key=lambda entry: entry.get("valid", False))
        self.assertFalse(document["profiles"][0]["valid"], "the reorder did not take")
        document["active_profile"] = "gone"

    def test_the_window_does_not_open_on_the_unreadable_profile(self):
        from PySide6.QtCore import Qt

        current = self.window.sidebar.list.currentItem()
        self.assertIsNotNone(current, "nothing was selected at all")
        profile = current.data(Qt.ItemDataRole.UserRole)
        self.assertTrue(
            profile.valid,
            "the GUI opened on a profile it cannot read, with a disabled editor and "
            "no profile loaded, because it fell back to row 0 without checking",
        )
        self.assertIsNotNone(self.window.editor.editing)
        self.assertTrue(self.window.editor.apply_button.isEnabled())


class ServiceBadgeVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["service"]["active"] = "inactive"

    def test_a_mixed_service_state_is_shown_in_words_beside_the_box(self):
        from legion_powerctl_gui import theme

        header = self.window.header
        self.assertTrue(header.service_check.isChecked())
        label = header.service_label
        self.assertEqual(label.text(), "WARN Boot service: enabled / inactive")
        self.assertEqual(label.property("severity"), "WARN")
        self.assertIn(
            theme.severity_color(self.window.palette(), "WARN").name(),
            label.styleSheet(),
        )


class ServiceOffVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["service"] = {"enabled": "disabled", "active": "inactive"}

    def test_a_disabled_boot_service_warns_that_the_limits_will_not_come_back(self):
        from legion_powerctl_gui import theme

        header = self.window.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        self.assertFalse(header.service_check.isChecked())
        self.assertEqual(header.service_label.text(), "", "an off service is not a fault")
        note = header.volatile_note
        self.assertTrue(note.isVisible())
        self.assertEqual(
            note.text(), "Limits are cleared by a power cycle and will not come back on their own."
        )
        self.assertIn(
            theme.severity_color(self.window.palette(), "WARN").name(), note.styleSheet(),
            "the note reads as plain text, not as a warning callout",
        )
        cells_bottom = header.running_label.mapTo(header, header.running_label.rect().bottomLeft())
        self.assertGreater(note.mapTo(header, note.rect().topLeft()).y(), cells_bottom.y())


class LimitsDidNotTakeVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"]["verified"] = "no"

    def test_limits_that_did_not_take_are_painted_in_the_fail_ink(self):
        header = self.window.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        readout = header.envelope_label
        self.assertEqual(header.mark_label.text(), "limits did not take")
        self.assertEqual(readout.severity, "FAIL")
        ink, fail, _muted, cap = self.readout_inks(readout)
        figures = self.colours_in_rows(readout.grab().toImage(), 0, cap)
        self.assertIn(fail, figures, "the figures that did not take are not in the FAIL ink")
        self.assertNotIn(ink, figures, "a figure that did not take is still in the plain ink")

    def test_at_the_kde_size_a_failure_never_pushes_the_cards_into_a_scroll(self):
        self.reopen_at_the_desktop_size()
        self.window.resize(960, 620)
        self.window.show()
        self.window.sidebar.select_by_name("quiet")
        self.settle(5)
        self.assertFalse(self.window.editor.advanced.button.isChecked())
        self.assertEqual(self.window.header.mark_label.text(), "limits did not take")
        self.assert_nothing_in_the_strip_is_cut()
        self.assertEqual(
            self.window.editor_scroll.verticalScrollBar().maximum(), 0,
            f"a {self.window.header.height()} px failed strip made the cards scroll",
        )

    def test_limits_that_did_not_take_are_not_marked_as_running_in_the_editor(self):
        editor = self.window.editor
        for name, words in (("balanced-plus", "running now, boot profile"), ("quiet", "")):
            self.window.sidebar.select_by_name(name)
            self.settle(3)
            with self.subTest(profile=name):
                self.assertEqual(editor.current_name, name)
                self.assertEqual(editor.power_envelope.bar.reference, ())
                self.assertEqual(editor.thermal_envelope.bar.reference, ())
                self.assertEqual([card.aside for card in editor.cards], ["", "", ""])
                self.assertEqual(editor.title_aside.text(), words, "the row and the title disagree")


class UnverifiedVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"]["verified"] = ""

    def test_an_unverified_apply_keeps_its_figures_in_the_plain_ink(self):
        header = self.window.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        readout = header.envelope_label
        self.assertEqual(header.mark_label.text(), "unverified")
        self.assertEqual(readout.severity, "WARN")
        ink, fail, _muted, cap = self.readout_inks(readout)
        figures = self.colours_in_rows(readout.grab().toImage(), 0, cap)
        self.assertIn(ink, figures, "an unverified figure is not in the plain ink")
        self.assertNotIn(fail, figures, "an unverified figure reads as a fault")


class QuietRunningVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"]["profile"] = "quiet"

    def test_at_the_kde_size_the_whole_figures_fit_an_eighty_pixel_strip(self):
        from legion_powerctl_gui import styles, theme
        from PySide6.QtGui import QFontMetrics

        self.reopen_at_the_desktop_size()
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        header = self.window.header
        readout = header.envelope_label
        self.assertTrue(self.strip_is_one_row())
        self.assertEqual(header.height(), styles.STRIP_HEIGHT)
        self.assertEqual(readout.height(), readout.tile_height())
        image = readout.grab().toImage()
        plane = image.pixel(0, image.height() - 1)
        inked = [any(image.pixel(x, y) != plane for x in range(image.width()))
                 for y in range(image.height())]
        top = inked.index(True)
        drawn = inked.index(False, top) - top
        metrics = QFontMetrics(theme.font("readout", readout.font()))
        tallest = max(-metrics.tightBoundingRect(value).top() for value, _u, _c in readout.tiles)
        self.assertGreaterEqual(
            drawn, tallest, "the readout box is shorter than its figures and cuts their tops off"
        )


class PartialApplyVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"]["result"] = "partial"

    def test_at_the_minimum_size_a_long_name_gives_way_before_the_figures(self):
        import dataclasses

        self.reopen_at_the_desktop_size()
        self.window.resize(720, 480)
        self.window.show()
        self.app.processEvents()
        header = self.window.header
        name, readout = header.running_label, header.envelope_label
        status = self.window.status
        for record in (status.last_apply, dict(status.last_apply, result="ok")):
            header.show_status(dataclasses.replace(status, last_apply=record))
            self.app.processEvents()
            with self.subTest(running=name.text()):
                self.assertGreaterEqual(
                    readout.width(), readout.minimumSizeHint().width(),
                    "the readout is cut off on its left, so a figure reads as another number",
                )
                self.assertIn(name.text(), self.accessible_name(name))
        self.assertGreaterEqual(
            name.width(), name.sizeHint().width(),
            "the name lost letters while the readout still had gaps to give",
        )
        header.show_status(status)
        self.app.processEvents()
        self.assertEqual(name.text(), "balanced-plus - PARTIALLY APPLIED")
        self.assertLess(name.width(), name.sizeHint().width(), "the long name did not give way")
        self.assertGreaterEqual(readout.width(), readout.minimumSizeHint().width())

    def test_the_name_gives_up_exactly_what_the_row_is_short_and_ends_in_an_ellipsis(self):
        self.reopen_at_the_desktop_size()
        self.window.resize(720, 480)
        self.window.show()
        self.settle(5)
        header = self.window.header
        name, readout, boot = header.running_label, header.envelope_label, header.boot_label
        short = name.sizeHint().width() - name.width()
        self.assertGreater(short, 0, "the long name fits whole at 720, so this pins nothing")
        self.assert_painted_with_an_ellipsis(name)
        self.assertEqual(
            boot.width(), boot.sizeHint().width(),
            "the boot name gave way while the running name still had letters to give",
        )
        for width, given in ((720 + short - 1, 1), (720 + short, 0)):
            self.window.resize(width, 480)
            self.settle(5)
            with self.subTest(width=width):
                self.assertFalse(self.strip_is_one_row())
                self.assertEqual(
                    name.sizeHint().width() - name.width(), given,
                    "the name gave up more than the row was short",
                )
                self.assertEqual(readout.width(), readout.minimumSizeHint().width())
                self.assertLess(readout.width(), readout.sizeHint().width())


class PerformanceCappedFailureVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"].update(profile="performance-capped", verified="no")
        document["active_profile"] = "performance-capped"

    def test_at_the_minimum_size_the_boot_name_gives_way_before_the_apply_record_is_cut(self):
        import dataclasses

        self.reopen_at_the_desktop_size()
        self.window.resize(720, 480)
        self.window.show()
        self.settle(5)
        header = self.window.header
        status = self.window.status
        partial = dict(status.last_apply, result="partial")
        long_boot = "performance-capped-on-battery-saver"
        for record, boot in (
            (status.last_apply, status.active_profile),
            (partial, status.active_profile),
            (status.last_apply, long_boot),
            (dict(status.last_apply, profile="quiet"), long_boot),
        ):
            header.show_status(dataclasses.replace(status, last_apply=record, active_profile=boot))
            self.settle(5)
            with self.subTest(running=header.running_label.text(), boot=boot):
                self.assertEqual(header.mark_label.text(), "limits did not take")
                self.assertTrue(header.when_label.text().startswith("applied 2026-08-07"))
                self.assert_nothing_in_the_strip_is_cut(header.running_label, header.boot_label)
                self.assertEqual(header.boot_label.text(), boot)
                self.assertEqual(self.accessible_name(header.boot_label), boot)


class NothingAppliedVariantTest(VariantFixtureTest):
    def mutate(self, document):
        document["last_apply"] = None

    def test_before_the_first_apply_the_readout_is_the_sentence_and_the_strip_keeps_its_height(
        self,
    ):
        from legion_powerctl_gui import styles, theme
        from PySide6.QtGui import QFontMetrics

        header = self.window.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        readout = header.envelope_label
        self.assertEqual(readout.tiles, [])
        self.assertEqual(readout.text(), "nothing applied since this boot")
        self.assertFalse(header.mark_label.isVisible())
        self.assertEqual(header.height(), styles.STRIP_HEIGHT)
        caption = QFontMetrics(theme.font("caption", readout.font()))
        self.assertEqual(readout.height(), caption.height(), "the sentence is set at figure size")
        ink, _fail, muted, _cap = self.readout_inks(readout)
        image = readout.grab().toImage()
        painted = self.colours_in_rows(image, 0, image.height())
        self.assertIn(muted, painted)
        self.assertNotIn(ink, painted, "the sentence is painted as loud as a figure")
        self.assertIn(muted, header.rail.styleSheet(), "the rail claims something is running")

    def test_before_the_first_apply_the_editor_has_nothing_to_measure_against(self):
        editor = self.window.editor
        self.assertEqual(editor.current_name, "balanced-plus")
        self.assertEqual(editor.power_envelope.bar.reference, ())
        self.assertEqual(editor.thermal_envelope.bar.reference, ())
        self.assertEqual([card.aside for card in editor.cards], ["", "", ""])
        self.assertEqual(editor.title_aside.text(), "boot profile")

    def test_at_the_kde_size_the_boot_cell_narrows_before_the_actions_wrap(self):
        from legion_powerctl_gui import styles
        from legion_powerctl_gui.header import BOOT_CELL_WIDTH, WRAP_WIDTH

        self.reopen_at_the_desktop_size()
        header = self.window.header
        self.window.resize(960, 620)
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.strip_is_one_row(), "before the first apply the strip wraps at 960")
        self.assertEqual(header.height(), styles.STRIP_HEIGHT)
        self.assert_nothing_in_the_strip_is_cut()

        narrow, wide = 720, 960
        while wide - narrow > 1:
            middle = (narrow + wide) // 2
            self.window.resize(middle, 620)
            self.app.processEvents()
            narrow, wide = (narrow, middle) if self.strip_is_one_row() else (middle, wide)
        self.window.resize(wide, 620)
        self.app.processEvents()
        self.assertGreater(header.width(), WRAP_WIDTH, "the wrap floor, not the cells, set this width")
        self.assert_nothing_in_the_strip_is_cut()
        self.assertLess(
            header.boot_label.parentWidget().width(), BOOT_CELL_WIDTH,
            "the actions wrapped while the boot cell still had width to give",
        )


class LongBootNameVariantTest(VariantFixtureTest):
    LONG = "performance-capped-overnight-render-queue"

    def mutate(self, document):
        document["last_apply"].update(profile="quiet", verified="no")
        document["active_profile"] = self.LONG

    def boot_next(self, name: str) -> None:
        document = json.loads(Path(self.fixture.name).read_text())
        document["active_profile"] = name
        Path(self.fixture.name).write_text(json.dumps(document))
        before = self.window.refresh_count
        self.window.refresh()
        self.assertTrue(wait_until(self.app, lambda: self.window.refresh_count > before))

    def test_a_squeezed_boot_name_gives_its_width_back_once_the_name_is_short(self):
        self.reopen_at_the_desktop_size()
        label = self.window.header.boot_label
        self.window.resize(720, 480)
        self.window.show()
        self.app.processEvents()
        self.assertGreater(label.given(), 0, "the long name was never squeezed, so this proves nothing")

        self.boot_next("quiet")
        self.window.resize(960, 620)
        self.app.processEvents()
        self.assertEqual(label.minimumSizeHint().width(), label.sizeHint().width())
        self.assertTrue(self.strip_is_one_row(), "the strip kept the long name's width after it left")
        self.assert_nothing_in_the_strip_is_cut()
        widened = self.settled_strip()

        self.reopen_at_the_desktop_size()
        self.window.resize(960, 620)
        self.window.show()
        self.assertTrue(
            self.settled_strip() == widened,
            "the strip remembers a name that left instead of matching a fresh window",
        )

    def settled_strip(self):
        self.assertTrue(wait_until(self.app, lambda: self.window.checks.count >= 1))
        for _ in range(5):
            self.app.processEvents()
        return self.window.header.grab().toImage()

    def test_an_empty_strip_label_measures_the_same_before_and_after_it_held_text(self):
        from legion_powerctl_gui.header import MachineHeader

        fresh = MachineHeader._label("", "caption")
        used = MachineHeader._label("", "caption")
        used.setText("(same)")
        used.setText("")
        self.assertEqual(fresh.sizeHint(), used.sizeHint(), "an emptied label and a new one size apart")


if __name__ == "__main__":
    unittest.main()
