# SPDX-License-Identifier: MIT

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

        cls.app = QApplication.instance() or QApplication([])

    def settle(self, rounds: int = 20) -> None:
        for _ in range(rounds):
            self.app.processEvents()
            time.sleep(0.01)

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
        self.assertEqual(self.editor.stapm_spin.value(), 65)
        self.assertEqual(self.editor.slow_spin.value(), 70)
        self.assertEqual(self.editor.fast_spin.value(), 80)
        self.assertEqual(self.editor.temp_spin.value(), 78)
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

    def test_slider_order_is_enforced_live(self):
        self.editor.stapm_spin.setValue(100)
        self.assertEqual(self.editor.stapm_spin.value(), 100)
        self.assertEqual(self.editor.slow_spin.value(), 100)
        self.assertEqual(self.editor.fast_spin.value(), 100)
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
        self.assertIn("configure balanced-plus --stapm 55 --slow 70 --fast 80 --temp 78", line)
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
        QTest.keyClicks(self.editor.fast_spin, "100")
        QTest.keyClick(self.editor.fast_spin, Qt.Key.Key_Return)
        self.assertEqual(self.editor.fast_spin.value(), 100)
        self.assertEqual(self.editor.stapm_spin.value(), 65)
        self.assertEqual(self.editor.slow_spin.value(), 70)

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
            "legion_powerctl_gui.app.QMessageBox.question", **kwargs
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
                "legion_powerctl_gui.app.QMessageBox.question"
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
        self.assertEqual(running.data(DETAIL_ROLE), "65/70/80 W, 78 C cap")
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
        from PySide6.QtWidgets import QMessageBox

        self.window.dialogs = True
        try:
            with unittest.mock.patch(
                "legion_powerctl_gui.actions.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Cancel,
            ) as question:
                self.window.profile_actions.delete()
        finally:
            self.window.dialogs = False
        args = question.call_args[0]
        self.assertGreaterEqual(
            len(args), 5,
            "the dialog names no buttons, so question() supplies Yes/No and defaults to Yes",
        )
        self.assertEqual(
            args[4], QMessageBox.StandardButton.Cancel,
            "Enter on the dialog deletes a profile with no undo",
        )
        self.assertTrue(args[3] & QMessageBox.StandardButton.Cancel)
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
                self.editor.fast_spin.setValue(90)
                self.editor.temp_spin.setValue(88)
                self.editor._on_edited()
                self.window.profile_actions.apply()
                self.settle(5)
        finally:
            self.window.dialogs = False
        self.assertEqual(asked.get("name"), "quiet")
        self.assertIn(("Fast PPT", 80, 90), asked["deltas"])
        self.assertIn(("Ceiling", 78, 88), asked["deltas"])
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
    def test_balanced_plus_editor_caps_both_temperature_controls_at_78(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="balanced-plus", temp_c=78))
            self.assertEqual(editor.temp_spin.maximum(), 78)
            self.assertEqual(editor.temp_slider.maximum(), 78)
            editor.temp_spin.setValue(90)
            self.assertEqual(editor.collect().temp_c, 78)
            self.assertEqual(editor.problems(), [])
        finally:
            editor.deleteLater()

    def test_temperature_range_follows_the_profile_when_switching(self):
        from legion_powerctl_gui import model
        from legion_powerctl_gui.editor import ProfileEditor

        editor = ProfileEditor()
        try:
            editor.load(model.Profile(name="balanced-plus", temp_c=78))
            editor.load(model.Profile(name="trial", temp_c=90))
            self.assertEqual(editor.temp_spin.maximum(), model.TEMP_MAX_C)
            self.assertEqual(editor.temp_slider.maximum(), model.TEMP_MAX_C)
            self.assertEqual(editor.collect().temp_c, 90)
            editor.load(model.Profile(name="balanced-plus", temp_c=78))
            self.assertEqual(editor.temp_spin.maximum(), 78)
            self.assertEqual(editor.collect().temp_c, 78)
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


if __name__ == "__main__":
    unittest.main()
