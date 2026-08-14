# SPDX-License-Identifier: MIT

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from legion_powerctl_gui import model

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "bin" / "legion-powerctl"
MAKE_FAKE_ROOT = REPO / "tests" / "fixtures" / "make-fake-root.sh"
FIXTURES = Path(__file__).parent / "fixtures"


def make_fake_root(root):
    proc = subprocess.run(
        ["bash", str(MAKE_FAKE_ROOT), str(root)],
        capture_output=True, text=True, check=True,
    )
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if line)


class CliContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = make_fake_root(self.tmp)
        self.profiles = Path(self.env["LEGION_POWERCTL_ETC_DIR"]) / "profiles.d"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, extra_env=None):
        env = dict(os.environ)
        env.update(self.env)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(CLI), *args], capture_output=True, text=True, env=env, check=False
        )

    def test_real_status_json_parses_into_the_model(self):
        proc = self.run_cli("status", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = model.parse_status(proc.stdout)
        self.assertEqual(status.active_profile, "balanced-plus")
        self.assertEqual(status.cpu_driver, "amd-pstate-epp")
        self.assertEqual(status.cpu_epp, "balance_performance")
        self.assertEqual({p.name for p in status.profiles}, {"balanced-plus", "quiet"})
        active = next(p for p in status.profiles if p.name == "balanced-plus")
        self.assertTrue(active.valid)
        self.assertIsInstance(active.stapm_w, int)
        self.assertLessEqual(active.stapm_w, active.slow_w)
        self.assertLessEqual(active.slow_w, active.fast_w)
        self.assertEqual(status.last_apply["profile"], "balanced-plus")

    def test_real_output_matches_the_fixture_value_for_value(self):
        real = json.loads(self.run_cli("status", "--json").stdout)
        fixture = json.loads((FIXTURES / "status.json").read_text())
        hint = "run gui/tests/fixtures/regenerate-status.sh"

        def without_paths(document):
            return {k: v for k, v in document.items() if k not in ("profiles", "ryzenadj")}

        self.assertEqual(set(real), set(fixture), f"top-level keys drifted; {hint}")
        self.assertEqual(without_paths(real), without_paths(fixture), hint)

        real_profiles = {p["name"]: p for p in real["profiles"]}
        fixture_profiles = {p["name"]: p for p in fixture["profiles"]}
        shared = sorted(set(real_profiles) & set(fixture_profiles))
        self.assertEqual(shared, ["balanced-plus", "quiet"], f"the two roots diverged; {hint}")
        for name in shared:
            self.assertEqual(real_profiles[name], fixture_profiles[name], f"{name} drifted; {hint}")

    def test_schema_version_is_the_one_the_gui_supports(self):
        real = json.loads(self.run_cli("status", "--json").stdout)
        self.assertEqual(real["schema_version"], model.SCHEMA_VERSION)

    def test_service_is_null_when_systemctl_is_missing(self):
        real = json.loads(self.run_cli("status", "--json", extra_env={
            "LEGION_POWERCTL_SYSTEMCTL_BIN": str(self.tmp / "absent-systemctl"),
        }).stdout)
        self.assertIsNone(real["service"])
        status = model.parse_status(json.dumps(real))
        self.assertIsNone(status.service_enabled)
        self.assertIsNone(status.service_active)

    def test_waybar_contract_is_json_with_the_documented_keys(self):
        proc = self.run_cli("status", "--waybar")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(set(doc), {"text", "alt", "class", "tooltip"})
        self.assertEqual(doc["alt"], "balanced-plus")
        self.assertEqual(doc["class"], "balanced-plus")
        self.assertIn("balanced-plus", doc["text"])

    def test_invalid_profile_does_not_break_the_document(self):
        (self.profiles / "broken.conf").write_text("STAPM_W=999\nSLOW_W=1\nFAST_W=1\nTEMP_C=82\n")
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        broken = next(p for p in status.profiles if p.name == "broken")
        self.assertFalse(broken.valid)
        self.assertTrue(next(p for p in status.profiles if p.name == "quiet").valid)

    def test_real_doctor_output_is_entirely_parseable(self):
        proc = self.run_cli("doctor")
        report = model.parse_doctor(proc.stdout, proc.returncode)
        for raw in proc.stdout.splitlines():
            if not raw.strip():
                continue
            self.assertTrue(
                model.DOCTOR_LINE_RE.match(raw) or model.DOCTOR_RESULT_RE.match(raw.strip()),
                f"doctor printed a line the GUI silently drops: {raw!r}",
            )
        self.assertTrue(report.lines, "doctor produced no check lines at all")
        self.assertEqual(report.failures, sum(1 for x in report.lines if x.status == "FAIL"))
        self.assertEqual(report.warnings, sum(1 for x in report.lines if x.status == "WARN"))

    def test_doctor_fixture_covers_every_check_the_cli_can_emit(self):
        emitted = set(re.findall(r"^\s*doctor_line \S+ (\S+)", CLI.read_text(), re.M))
        fixture = model.parse_doctor((FIXTURES / "doctor.txt").read_text(), 0)
        self.assertEqual(
            {line.label for line in fixture.lines}, emitted,
            "doctor.txt no longer matches the checks the CLI can print; "
            "run gui/tests/fixtures/regenerate-doctor.sh",
        )

    def test_model_constants_match_the_cli(self):
        text = CLI.read_text()

        def cli_bound(name):
            match = re.search(rf'^readonly {name}="\$\{{\w+:-(\d+)\}}"$', text, re.M)
            self.assertIsNotNone(match, f"{name} is no longer a readonly default in the CLI")
            return int(match.group(1))

        def cli_enum(name):
            match = re.search(rf"^readonly -a {name}=\((.*)\)$", text, re.M)
            self.assertIsNotNone(match, f"{name} is no longer a one-line array in the CLI")
            return tuple(match.group(1).split())

        self.assertEqual(model.POWER_MIN_W, cli_bound("MIN_POWER_W"))
        self.assertEqual(model.POWER_MAX_W, cli_bound("MAX_POWER_W"))
        self.assertEqual(model.TEMP_MIN_C, cli_bound("MIN_TEMP_C"))
        self.assertEqual(model.TEMP_MAX_C, cli_bound("MAX_TEMP_C"))
        self.assertEqual(model.POWER_PROFILES, cli_enum("POWER_PROFILE_VALUES"))
        self.assertEqual(model.BOOST_VALUES, cli_enum("BOOST_VALUES"))
        self.assertEqual(model.EPP_VALUES, cli_enum("EPP_VALUES"))
        self.assertIn(model.PROFILE_NAME_RE.pattern, text)

    def test_a_new_profile_starts_where_the_cli_would_start_it(self):
        block = re.search(r"^set_profile_defaults\(\) \{\n(.*?)^\}", CLI.read_text(), re.M | re.S)
        self.assertIsNotNone(block, "set_profile_defaults is no longer a plain block")
        cli_defaults = {
            key: value
            for key, _, value in re.findall(r'^\s*(\w+)=("?)(.*?)\2$', block.group(1), re.M)
        }
        self.assertEqual(len(cli_defaults), 10, cli_defaults)
        draft = model.Profile(name="draft")
        self.assertEqual(
            {
                "STAPM_W": str(draft.stapm_w),
                "SLOW_W": str(draft.slow_w),
                "FAST_W": str(draft.fast_w),
                "TEMP_C": str(draft.temp_c),
                "POWER_PROFILE": draft.power_profile,
                "MIN_FREQ_MHZ": draft.min_freq_mhz,
                "MAX_FREQ_MHZ": draft.max_freq_mhz,
                "BOOST": draft.boost,
                "EPP": draft.epp,
            },
            {key: value for key, value in cli_defaults.items() if key != "PROFILE_DESCRIPTION"},
        )

    def test_the_frequency_bounds_are_the_cli_bounds(self):
        text = CLI.read_text()
        self.assertIn("(( value >= 100 && value <= 10000 ))", text)
        self.assertTrue(model.valid_frequency("100"))
        self.assertTrue(model.valid_frequency("10000"))
        self.assertFalse(model.valid_frequency("99"))
        self.assertFalse(model.valid_frequency("10001"))

    def test_description_with_quotes_and_backslashes_round_trips(self):
        tricky = 'He said "hi" \\ and left'
        proc = self.run_cli(
            "configure", "tricky", "--stapm", "50", "--slow", "55",
            "--fast", "60", "--temp", "80", "--description", tricky,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertEqual(next(p for p in status.profiles if p.name == "tricky").description, tricky)

    def test_the_configure_argv_the_gui_builds_is_accepted_and_round_trips(self):
        profile = model.Profile(
            name="from-gui", stapm_w=48, slow_w=52, fast_w=61, temp_c=79,
            power_profile="power-saver", min_freq_mhz="1200", max_freq_mhz="4200",
            boost="off", epp="balance_power",
            description='He said "hi" and used a \\ backslash',
        )
        proc = self.run_cli(*model.build_configure_args(profile))
        self.assertEqual(proc.returncode, 0, proc.stderr)

        status = model.parse_status(self.run_cli("status", "--json").stdout)
        written = next(p for p in status.profiles if p.name == "from-gui")
        self.assertTrue(written.valid, "the CLI wrote a profile it then calls invalid")
        self.assertEqual(written, profile)
        self.assertEqual(
            status.active_profile, "balanced-plus",
            "configure without --select changed which profile boots",
        )

    def test_the_select_and_delete_argv_the_gui_builds_are_accepted_by_the_cli(self):
        self.assertEqual(self.run_cli(*model.build_select_args("quiet")).returncode, 0)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertEqual(status.active_profile, "quiet")

        proc = self.run_cli(*model.build_delete_args("balanced-plus"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertNotIn("balanced-plus", [p.name for p in status.profiles])

    def test_the_configure_select_argv_the_pin_builds_writes_and_selects_at_once(self):
        profile = model.Profile(name="pinned", stapm_w=40, slow_w=45, fast_w=50, temp_c=70)
        proc = self.run_cli(*model.build_configure_args(profile, select=True))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertEqual(status.active_profile, "pinned")
        written = next(p for p in status.profiles if p.name == "pinned")
        self.assertEqual((written.stapm_w, written.temp_c), (40, 70))

    def test_the_go_back_argv_re_applies_a_saved_profile(self):
        proc = self.run_cli(*model.build_apply_args("quiet"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertEqual(status.last_apply["profile"], "quiet")

    def test_a_new_profile_is_not_given_another_profiles_description(self):
        proc = self.run_cli("configure", "fresh", "--stapm", "40", "--slow", "45",
                            "--fast", "50", "--temp", "70")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertEqual(next(p for p in status.profiles if p.name == "fresh").description, "")

    def test_an_apply_records_whether_it_could_verify_the_limits(self):
        self.assertEqual(self.run_cli("apply", "quiet").returncode, 0)
        status = model.parse_status(self.run_cli("status", "--json").stdout)
        self.assertIn("verified", status.last_apply)
        self.assertIn(status.last_apply["verified"], ("yes", "no", "unknown"))


class DesktopEntryContractTest(unittest.TestCase):
    def setUp(self):
        self.entry = dict(
            line.split("=", 1)
            for line in (REPO / "desktop" / "legion-powerctl.desktop").read_text().splitlines()
            if "=" in line and not line.startswith("[")
        )

    def test_startup_wm_class_matches_the_application_name(self):
        app_name = re.search(
            r'setApplicationName\("([^"]+)"\)',
            (REPO / "gui" / "legion_powerctl_gui" / "__main__.py").read_text(),
        )
        self.assertIsNotNone(app_name, "the app no longer sets an application name")
        self.assertEqual(self.entry.get("StartupWMClass"), app_name.group(1))

    def test_exec_matches_the_installed_launcher(self):
        self.assertEqual(self.entry["Exec"], "legion-powerctl-gui")
        self.assertTrue((REPO / "bin" / "legion-powerctl-gui").exists())


if __name__ == "__main__":
    unittest.main()
