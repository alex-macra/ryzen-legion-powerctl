# SPDX-License-Identifier: MIT

import os
import subprocess
import tempfile
import time
from pathlib import Path

import harness
from harness import CLI, DESKTOP_ENTRY, E2ETest, Session, wait_until, x


class DesktopSessionTest(E2ETest):
    @classmethod
    def setUpClass(cls):
        cls.session = Session().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.session.__exit__(None, None, None)

    def test_the_window_wm_class_is_the_desktop_entry_s_startupwmclass(self):
        entry = dict(
            line.split("=", 1)
            for line in DESKTOP_ENTRY.read_text().splitlines()
            if "=" in line and not line.startswith("[")
        )
        expected = entry.get("StartupWMClass")
        self.assertTrue(expected, "the desktop entry sets no StartupWMClass")

        windows = wait_until(self.session.window_id, "the window to be mapped")
        classes = []
        for window in windows:
            text = x("xprop", "-id", window, "WM_CLASS")
            classes.append(text.strip())
            if expected in text:
                return
        self.fail(f"no mapped window carries WM_CLASS {expected!r}; X was told: {classes}")

    def test_the_installed_icon_is_what_the_window_carries(self):
        windows = wait_until(self.session.window_id, "the window to be mapped")
        for window in windows:
            if "_NET_WM_ICON" in x("xprop", "-id", window):
                return
        self.fail("the window carries no icon; the taskbar entry would be blank")

    def test_tab_order_through_a_real_x_server_is_the_reading_order(self):
        windows = wait_until(self.session.window_id, "the window to be mapped")
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", windows[0]], timeout=15, check=False
        )
        wait_until(self.session.focused, "the window to take the keyboard focus")

        seen, unnamed = [], []
        for _ in range(20):
            subprocess.run(["xdotool", "key", "Tab"], timeout=15, check=False)
            time.sleep(0.15)
            node = self.session.focused()
            if node is None:
                continue
            key = (node.getRoleName(), node.name or harness.labelled_by(node))
            if seen and key == seen[-1]:
                continue
            if key in seen:
                break
            if not key[1]:
                unnamed.append(node.getRoleName())
            seen.append(key)

        self.assertGreaterEqual(
            len(seen), 5, f"Tab barely moves; something is eating the key: {seen}"
        )
        self.assertEqual(
            unnamed, [],
            f"Tab reaches {unnamed} which announce nothing; the stops were: {seen}",
        )

    def test_delete_raises_a_real_modal_that_escape_dismisses(self):
        profiles_dir = Path(os.environ["LEGION_POWERCTL_ETC_DIR"]) / "profiles.d"
        before = sorted(p.name for p in profiles_dir.glob("*.conf"))

        delete = self.session.button("Delete")
        self.assertIsNotNone(delete, "no Delete button in the tree")
        self.session.do_action(delete)

        dialog = wait_until(
            lambda: next(
                (n for n in self.session.nodes()
                 if n.getRoleName() in ("dialog", "alert")), None
            ),
            "the delete confirmation to appear",
        )
        self.assertNamed(dialog, "the confirmation dialog")
        subprocess.run(["xdotool", "key", "Escape"], timeout=15, check=False)
        wait_until(
            lambda: not any(
                n.getRoleName() in ("dialog", "alert") for n in self.session.nodes()
            ),
            "the dialog to close",
        )
        self.assertEqual(
            sorted(p.name for p in profiles_dir.glob("*.conf")), before,
            "a dismissed confirmation still deleted the profile",
        )


class ElevationArgvTest(E2ETest):
    def test_the_argv_handed_to_the_elevation_helper(self):
        tmp = Path(tempfile.mkdtemp())
        log = tmp / "argv.log"
        shim = tmp / "fake-pkexec"
        shim.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\nexec "$@"\n')
        shim.chmod(0o755)

        with Session(env={"LEGION_POWERCTL_GUI_ELEVATE": str(shim)}) as session:
            apply_now = session.button("Apply now")
            self.assertIsNotNone(apply_now, "no Apply now button in the tree")
            session.do_action(apply_now)
            wait_until(
                lambda: log.exists() and log.read_text().strip(),
                "the apply to reach pkexec",
            )

        argv = log.read_text().split()
        self.assertEqual(
            argv[0], str(CLI),
            "argv[0] is not the installed CLI, which is what the policy pins exec.path to",
        )
        self.assertEqual(
            argv[1], "configure",
            "argv[1] is not the subcommand the policy pins exec.argv1 to",
        )


class InstalledCliWriteTest(E2ETest):
    STAPM_ON_DISK = 60

    def test_an_apply_reaches_the_installed_cli_and_writes_the_profile(self):
        profiles_dir = Path(os.environ["LEGION_POWERCTL_ETC_DIR"]) / "profiles.d"
        written = profiles_dir / "balanced-plus.conf"
        before = written.read_text()
        self.assertIn(f"STAPM_W={self.STAPM_ON_DISK}", before, "the fixture profile changed")
        target = self.STAPM_ON_DISK - 3

        with Session() as session:
            spin = wait_until(
                lambda: next(
                    (n for n in session.nodes()
                     if n.getRoleName() == "spin button"
                     and n.name.startswith("Sustained")
                     and int(n.queryValue().currentValue) == self.STAPM_ON_DISK),
                    None,
                ),
                f"the sustained limit to load its saved value ({self.STAPM_ON_DISK})",
            )
            spin.queryValue().currentValue = target

            apply_now = session.button("Apply now")
            self.assertIsNotNone(apply_now)
            session.do_action(apply_now)
            wait_until(
                lambda: written.read_text() != before,
                "the installed CLI to rewrite the profile",
            )

        self.assertIn(
            f"STAPM_W={target}", written.read_text(),
            f"the value set on the bus ({target}) is not what the CLI wrote",
        )
