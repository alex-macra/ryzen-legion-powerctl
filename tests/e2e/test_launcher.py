# SPDX-License-Identifier: MIT

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import harness
from harness import LAUNCHER, TREE

STUB_GUI = Path(__file__).parent / "stub-gui"


def run_launcher(env=None, cwd=None, args=(), path_prefix=None):
    merged = dict(os.environ)
    merged.pop("LEGION_POWERCTL_GUI_CLI", None)
    if path_prefix:
        merged["PATH"] = f"{path_prefix}:{merged['PATH']}"
    if env:
        merged.update(env)
    return subprocess.run(
        [str(LAUNCHER), *args],
        env=merged, cwd=cwd, capture_output=True, text=True, timeout=60, check=False,
    )


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_the_launcher_hands_the_app_a_pinned_cli_and_a_clean_sys_path(self):
        decoy = self.tmp / "legion_powerctl_gui.py"
        decoy.write_text("raise SystemExit('the decoy on the launch path was imported')\n")

        proc = run_launcher(
            env={"LEGION_POWERCTL_GUI_ROOT": str(STUB_GUI)},
            cwd=self.tmp,
            args=("--flag", "value"),
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
        report = json.loads(proc.stdout)

        self.assertEqual(report["cwd"], "/", "the launcher did not leave the launch directory")
        self.assertEqual(report["env"].get("PYTHONSAFEPATH"), "1")
        self.assertEqual(report["env"].get("PYTHONDONTWRITEBYTECODE"), "1")
        self.assertEqual(
            report["env"].get("LEGION_POWERCTL_GUI_CLI"),
            str(TREE / "usr" / "bin" / "legion-powerctl"),
            "the CLI handed to pkexec was not pinned to the one beside the launcher",
        )
        self.assertEqual(report["env"]["PYTHONPATH"].split(":")[0], str(STUB_GUI))
        self.assertEqual(report["argv"][1:], ["--flag", "value"], "extra arguments were dropped")
        self.assertNotIn(
            str(self.tmp), report["sys_path"],
            "the launch directory is on sys.path, so a file named after a module there wins",
        )

    def test_a_missing_gui_root_fails_loudly_and_visibly(self):
        shim_dir = self.tmp / "shim"
        shim_dir.mkdir()
        log = self.tmp / "zenity.log"
        zenity = shim_dir / "zenity"
        zenity.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {log}\n')
        zenity.chmod(0o755)

        proc = run_launcher(
            env={
                "LEGION_POWERCTL_GUI_ROOT": str(self.tmp / "no-such-root"),
                "DISPLAY": os.environ.get("DISPLAY", ":99"),
            },
            path_prefix=str(shim_dir),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no-such-root", proc.stderr)
        self.assertTrue(log.exists(), "no dialog was raised; a menu launch would fail in silence")
        raised = log.read_text()
        self.assertIn("--error", raised)
        self.assertIn("no-such-root", raised)

    def test_a_missing_pyside6_is_reported_not_a_traceback(self):
        shim_dir = self.tmp / "nopyside"
        shim_dir.mkdir()
        python3 = shim_dir / "python3"
        python3.write_text(
            '#!/bin/sh\ncase "$*" in *"import PySide6"*) exit 1 ;; esac\nexit 0\n'
        )
        python3.chmod(0o755)

        proc = run_launcher(path_prefix=str(shim_dir))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("PySide6 is not installed", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_the_installed_desktop_entry_points_at_something_that_exists(self):
        entry = dict(
            line.split("=", 1)
            for line in harness.DESKTOP_ENTRY.read_text().splitlines()
            if "=" in line and not line.startswith("[")
        )
        def installed(value):
            target = Path(value.split()[0])
            if target.is_absolute():
                return TREE / target.relative_to("/")
            return TREE / "usr" / "bin" / target

        for key in ("Exec", "TryExec"):
            if key not in entry:
                continue
            path = installed(entry[key])
            self.assertTrue(
                os.access(path, os.X_OK),
                f"the desktop entry's {key} names {entry[key]}, "
                f"which this install does not provide at {path}",
            )
