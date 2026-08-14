# SPDX-License-Identifier: MIT

import os
import unittest
from pathlib import Path
from unittest import mock

from legion_powerctl_gui import model

FIXTURES = Path(__file__).parent / "fixtures"


class ParseStatusTest(unittest.TestCase):
    def test_parses_fixture_document(self):
        status = model.parse_status((FIXTURES / "status.json").read_text())
        self.assertEqual(status.active_profile, "balanced-plus")
        self.assertTrue(status.version, "version must be non-empty")
        self.assertEqual(status.power_profile, "balanced")
        self.assertEqual(status.service_enabled, "enabled")
        self.assertEqual(status.service_active, "active")
        self.assertEqual(status.last_apply["profile"], "balanced-plus")
        self.assertEqual(len(status.profiles), 4)

    def test_valid_profile_fields_are_typed(self):
        status = model.parse_status((FIXTURES / "status.json").read_text())
        quiet = next(p for p in status.profiles if p.name == "quiet")
        self.assertTrue(quiet.valid)
        self.assertEqual(quiet.stapm_w, 45)
        self.assertEqual(quiet.temp_c, 78)
        self.assertEqual(quiet.boost, "unchanged")
        self.assertEqual(quiet.summary(), "45/50/60 W, 78 C cap")

    def test_invalid_profile_entry_is_kept_but_flagged(self):
        status = model.parse_status((FIXTURES / "status.json").read_text())
        broken = next(p for p in status.profiles if p.name == "broken")
        self.assertFalse(broken.valid)
        self.assertEqual(broken.summary(), "invalid profile file")

    def test_rejects_wrong_schema_version(self):
        with self.assertRaisesRegex(model.StatusParseError, "schema"):
            model.parse_status('{"schema_version": 2, "profiles": []}')

    def test_rejects_invalid_json(self):
        with self.assertRaises(model.StatusParseError):
            model.parse_status("not json")

    def test_rejects_non_object(self):
        with self.assertRaises(model.StatusParseError):
            model.parse_status("[1, 2]")

    def test_profile_with_bad_numbers_becomes_invalid(self):
        payload = (
            '{"schema_version":1,"active_profile":"x","profiles":'
            '[{"name":"x","valid":true,"stapm_w":"garbage","slow_w":65,'
            '"fast_w":75,"temp_c":82}]}'
        )
        status = model.parse_status(payload)
        self.assertFalse(status.profiles[0].valid)

    def test_a_machine_with_nothing_configured_yet_still_parses(self):
        status = model.parse_status(
            '{"schema_version":1,"version":"0.3.0","active_profile":"balanced-plus",'
            '"power_profile":null,"cpu_driver":null,"cpu_epp":null,"ryzenadj":null,'
            '"service":null,"last_apply":null,"profiles":[]}'
        )
        self.assertEqual(status.profiles, [])
        self.assertIsNone(status.last_apply)
        self.assertIsNone(status.service_enabled)
        self.assertIsNone(status.service_active)
        self.assertIsNone(status.ryzenadj)
        self.assertEqual(status.active_profile, "balanced-plus")


class ParseDoctorTest(unittest.TestCase):
    def test_parses_fixture(self):
        report = model.parse_doctor((FIXTURES / "doctor.txt").read_text(), 0)
        self.assertEqual(report.failures, 0)
        self.assertEqual(report.warnings, 4)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(len(report.lines), 17)
        smu = next(line for line in report.lines if line.label == "SMU-backend")
        self.assertEqual(smu.status, "WARN")
        self.assertIn("/dev/mem", smu.detail)

    def test_summary_line_wins_over_counting(self):
        text = "FAIL  RyzenAdj  not found\n\nDoctor result: 4 failure(s), 2 warning(s).\n"
        report = model.parse_doctor(text, 1)
        self.assertEqual((report.failures, report.warnings), (4, 2))

    def test_counts_lines_when_summary_missing(self):
        text = "FAIL  RyzenAdj  not found\nWARN  System  unknown vendor\n"
        report = model.parse_doctor(text, 1)
        self.assertEqual(report.failures, 1)
        self.assertEqual(report.warnings, 1)


class EnforcePowerOrderTest(unittest.TestCase):
    def test_raising_stapm_pushes_slow_and_fast(self):
        self.assertEqual(model.enforce_power_order(90, 65, 75, "stapm"), (90, 90, 90))

    def test_lowering_fast_pulls_slow_and_stapm(self):
        self.assertEqual(model.enforce_power_order(60, 65, 50, "fast"), (50, 50, 50))

    def test_moving_slow_between_neighbours_keeps_them(self):
        self.assertEqual(model.enforce_power_order(60, 70, 75, "slow"), (60, 70, 75))

    def test_values_clamp_to_cli_guardrails(self):
        stapm, slow, fast = model.enforce_power_order(300, 65, 75, "stapm")
        self.assertEqual((stapm, slow, fast), (200, 200, 200))
        self.assertEqual(model.enforce_power_order(1, 65, 75, "stapm")[0], model.POWER_MIN_W)

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            model.enforce_power_order(60, 65, 75, "turbo")


class ValidateProfileTest(unittest.TestCase):
    def _profile(self, **overrides):
        profile = model.Profile(name="test")
        for key, value in overrides.items():
            setattr(profile, key, value)
        return profile

    def test_default_profile_is_valid(self):
        self.assertEqual(model.validate_profile(self._profile()), [])

    def test_bad_ordering_is_reported(self):
        problems = model.validate_profile(self._profile(stapm_w=80, slow_w=65, fast_w=75))
        self.assertTrue(any("STAPM <= Slow" in p for p in problems))

    def test_frequency_bounds(self):
        self.assertTrue(model.valid_frequency("stock"))
        self.assertTrue(model.valid_frequency("unchanged"))
        self.assertTrue(model.valid_frequency("100"))
        self.assertTrue(model.valid_frequency("10000"))
        self.assertFalse(model.valid_frequency("99"))
        self.assertFalse(model.valid_frequency("10001"))
        self.assertFalse(model.valid_frequency("fast"))

    def test_leading_zero_frequency_is_rejected_like_the_cli_does(self):
        self.assertFalse(model.valid_frequency("0700"))
        problems = model.validate_profile(self._profile(min_freq_mhz="0700"))
        self.assertTrue(any("frequency" in p for p in problems))

    def test_multiline_description_is_rejected(self):
        problems = model.validate_profile(self._profile(description="one\ntwo"))
        self.assertTrue(any("single line" in p for p in problems))

    def test_every_control_character_the_cli_refuses_is_refused_here(self):
        for character in ("\t", "\x1b", "\x00", "\x7f", "\x1b]0;pwned\x07"):
            with self.subTest(character=repr(character)):
                problems = model.validate_profile(
                    self._profile(description=f"a{character}b")
                )
                self.assertTrue(
                    any("control characters" in p for p in problems),
                    f"{character!r} reached the CLI: {problems}",
                )
        self.assertEqual(model.validate_profile(self._profile(description="a\x85b")), [])

    def test_min_freq_above_max_is_reported(self):
        problems = model.validate_profile(
            self._profile(min_freq_mhz="4000", max_freq_mhz="2000")
        )
        self.assertTrue(any("Minimum frequency cannot exceed" in p for p in problems))

    def test_bad_name_is_reported(self):
        problems = model.validate_profile(self._profile(name="-bad name"))
        self.assertTrue(any("name" in p.lower() for p in problems))


class CommandBuildingTest(unittest.TestCase):
    def test_configure_args_cover_every_field(self):
        profile = model.Profile(name="quiet", description="desc words", stapm_w=45,
                                slow_w=50, fast_w=60, temp_c=78,
                                power_profile="power-saver", min_freq_mhz="stock",
                                max_freq_mhz="stock", boost="off", epp="balance_power")
        args = model.build_configure_args(profile)
        self.assertEqual(args[:2], ["configure", "quiet"])
        self.assertEqual(args[args.index("--stapm") + 1], "45")
        self.assertEqual(args[args.index("--temp") + 1], "78")
        self.assertEqual(args[args.index("--epp") + 1], "balance_power")
        self.assertEqual(args[args.index("--description") + 1], "desc words")
        self.assertNotIn("--select", args)
        self.assertNotIn("--apply", args)

    def test_configure_args_apply_now(self):
        args = model.build_configure_args(model.Profile(name="p"), apply_now=True)
        self.assertIn("--apply", args)
        self.assertNotIn("--select", args)

    def test_configure_args_select(self):
        args = model.build_configure_args(model.Profile(name="p"), select=True)
        self.assertIn("--select", args)
        self.assertNotIn("--apply", args)

    def test_configure_args_can_select_and_apply_together(self):
        args = model.build_configure_args(model.Profile(name="p"), apply_now=True, select=True)
        self.assertIn("--select", args)
        self.assertIn("--apply", args)
        self.assertLess(args.index("--select"), args.index("--apply"))

    def test_apply_and_select_args(self):
        self.assertEqual(model.build_apply_args("p"), ["apply", "p"])
        self.assertEqual(model.build_select_args("p"), ["select", "p"])
        self.assertEqual(model.build_delete_args("p"), ["delete", "p"])

    def test_the_description_is_still_sent_though_nothing_edits_it(self):
        args = model.build_configure_args(model.Profile(name="p", description="kept"))
        self.assertEqual(args[args.index("--description") + 1], "kept")
        args = model.build_configure_args(model.Profile(name="p"))
        self.assertIn("--description", args)
        self.assertEqual(args[args.index("--description") + 1], "")


class ElevationTest(unittest.TestCase):
    def test_elevation_command_names_what_wraps_the_cli(self):
        with mock.patch.dict(os.environ, {"LEGION_POWERCTL_GUI_ELEVATE": "none"}):
            self.assertIsNone(model.elevation_command())
        with mock.patch.dict(os.environ, {"LEGION_POWERCTL_GUI_ELEVATE": "sudo"}):
            self.assertEqual(model.elevation_command(), "sudo")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEGION_POWERCTL_GUI_ELEVATE", None)
            with mock.patch("os.geteuid", return_value=1000):
                self.assertEqual(model.elevation_command(), "pkexec")
            with mock.patch("os.geteuid", return_value=0):
                self.assertIsNone(model.elevation_command())

    def test_cli_override_is_used(self):
        with mock.patch.dict(os.environ, {"LEGION_POWERCTL_GUI_CLI": "/tmp/fake"}):
            self.assertEqual(model.unprivileged_command(["status"]), ["/tmp/fake", "status"])

    def test_elevate_none_runs_directly(self):
        env = {"LEGION_POWERCTL_GUI_CLI": "/tmp/fake", "LEGION_POWERCTL_GUI_ELEVATE": "none"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(model.privileged_command(["enable"]), ["/tmp/fake", "enable"])

    def test_default_wraps_with_pkexec(self):
        env = {"LEGION_POWERCTL_GUI_CLI": "/tmp/fake"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("LEGION_POWERCTL_GUI_ELEVATE", None)
            with mock.patch("os.geteuid", return_value=1000):
                self.assertEqual(
                    model.privileged_command(["apply", "quiet"]),
                    ["pkexec", "/tmp/fake", "apply", "quiet"],
                )

    def test_custom_elevator_is_respected(self):
        env = {"LEGION_POWERCTL_GUI_CLI": "/tmp/fake", "LEGION_POWERCTL_GUI_ELEVATE": "sudo"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(
                model.privileged_command(["disable"]), ["sudo", "/tmp/fake", "disable"]
            )

    def test_root_runs_directly(self):
        with mock.patch.dict(os.environ, {"LEGION_POWERCTL_GUI_CLI": "/tmp/fake"}):
            os.environ.pop("LEGION_POWERCTL_GUI_ELEVATE", None)
            with mock.patch("os.geteuid", return_value=0):
                self.assertEqual(model.privileged_command(["enable"]), ["/tmp/fake", "enable"])


class ProfileIconNameTest(unittest.TestCase):
    def test_known_power_profiles_map_to_freedesktop_names(self):
        self.assertEqual(
            model.profile_icon_name("power-saver"), "power-profile-power-saver-symbolic"
        )
        self.assertEqual(
            model.profile_icon_name("balanced"), "power-profile-balanced-symbolic"
        )
        self.assertEqual(
            model.profile_icon_name("performance"), "power-profile-performance-symbolic"
        )

    def test_unchanged_and_unknown_map_to_no_icon(self):
        self.assertEqual(model.profile_icon_name("unchanged"), "")
        self.assertEqual(model.profile_icon_name("garbage"), "")


if __name__ == "__main__":
    unittest.main()
