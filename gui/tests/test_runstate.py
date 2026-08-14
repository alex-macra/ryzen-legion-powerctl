# SPDX-License-Identifier: MIT

import json
import unittest
from datetime import datetime
from pathlib import Path

from legion_powerctl_gui import model, runstate

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


def status_with(last_apply, active="balanced-plus"):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["last_apply"] = last_apply
    document["active_profile"] = active
    return model.parse_status(json.dumps(document))


class RunStateTest(unittest.TestCase):
    def test_the_fixture_machine_is_running_what_it_last_applied(self):
        state = runstate.run_state(model.parse_status(FIXTURE.read_text(encoding="utf-8")))
        self.assertTrue(state.applied)
        self.assertEqual(state.profile, "balanced-plus")
        self.assertEqual(state.headline(), "balanced-plus")
        self.assertEqual(state.summary(), "65/70/80 W, 78 C cap")

    def test_values_arrive_as_strings_and_come_out_as_numbers(self):
        state = runstate.run_state(model.parse_status(FIXTURE.read_text(encoding="utf-8")))
        for value in (state.stapm_w, state.slow_w, state.fast_w, state.temp_c):
            self.assertIsInstance(value, int)

    def test_nothing_applied_since_boot_says_so(self):
        state = runstate.run_state(status_with(None))
        self.assertFalse(state.applied)
        self.assertEqual(state.headline(), "Firmware defaults")
        self.assertEqual(state.summary(), "nothing applied since this boot")
        self.assertEqual(state.mark(), ("", "NEUTRAL"))

    def test_a_partial_apply_is_a_failure_in_words_not_only_in_colour(self):
        state = runstate.run_state(
            status_with({"profile": "quiet", "result": "partial", "verified": "no"})
        )
        self.assertIn("PARTIALLY APPLIED", state.headline())
        self.assertEqual(state.mark(), ("limits did not take", "FAIL"))

    def test_an_unverifiable_apply_is_not_reported_as_confirmed(self):
        unknown = runstate.run_state(
            status_with({"profile": "quiet", "result": "ok", "verified": "unknown"})
        )
        self.assertEqual(unknown.mark(), ("unverified", "WARN"))
        confirmed = runstate.run_state(
            status_with({"profile": "quiet", "result": "ok", "verified": "yes"})
        )
        self.assertEqual(confirmed.mark(), ("confirmed", "OK"))

    def test_a_record_written_by_an_older_cli_still_parses(self):
        state = runstate.run_state(status_with({"profile": "quiet", "result": "ok"}))
        self.assertTrue(state.applied)
        self.assertEqual(state.mark(), ("unverified", "WARN"))
        self.assertEqual(state.summary(), "")

    def test_the_time_is_relative_only_on_the_day_it_happened(self):
        state = runstate.RunState(
            profile="quiet", applied_at="2026-08-12T12:04:00+03:00"
        )
        same_day = datetime.fromisoformat("2026-08-12T18:00:00+03:00")
        self.assertEqual(state.when(same_day), "applied 12:04 today")
        later = datetime.fromisoformat("2026-08-14T09:00:00+03:00")
        self.assertEqual(state.when(later), "applied 2026-08-12 12:04")

    def test_an_unparseable_timestamp_is_shown_rather_than_dropped(self):
        state = runstate.RunState(profile="quiet", applied_at="whenever")
        self.assertEqual(state.when(), "applied whenever")


class RaisingDeltasTest(unittest.TestCase):
    RUNNING = runstate.RunState(
        profile="quiet", stapm_w=45, slow_w=50, fast_w=60, temp_c=78
    )

    def test_a_profile_that_raises_limits_reports_each_one(self):
        profile = model.Profile(
            name="performance-capped", stapm_w=65, slow_w=70, fast_w=75, temp_c=85
        )
        deltas = runstate.raising_deltas(self.RUNNING, profile)
        self.assertEqual(
            [(d.label, d.was, d.now) for d in deltas],
            [("Sustained", 45, 65), ("Slow PPT", 50, 70), ("Fast PPT", 60, 75),
             ("Ceiling", 78, 85)],
        )

    def test_capping_is_silent(self):
        profile = model.Profile(
            name="quieter", stapm_w=35, slow_w=40, fast_w=45, temp_c=70
        )
        self.assertEqual(runstate.raising_deltas(self.RUNNING, profile), [])

    def test_an_equal_profile_is_silent(self):
        profile = model.Profile(
            name="same", stapm_w=45, slow_w=50, fast_w=60, temp_c=78
        )
        self.assertEqual(runstate.raising_deltas(self.RUNNING, profile), [])

    def test_only_the_limits_that_rose_are_listed(self):
        profile = model.Profile(
            name="mixed", stapm_w=45, slow_w=50, fast_w=60, temp_c=90
        )
        deltas = runstate.raising_deltas(self.RUNNING, profile)
        self.assertEqual([d.label for d in deltas], ["Ceiling"])

    def test_nothing_running_means_nothing_to_confirm(self):
        profile = model.Profile(name="anything", stapm_w=200, temp_c=100)
        self.assertEqual(runstate.raising_deltas(runstate.RunState(), profile), [])


class ServiceBadgeTest(unittest.TestCase):
    def test_enabled_active_is_ok(self):
        self.assertEqual(
            runstate.service_badge("enabled", "active"),
            ("Boot service: enabled / active", "OK"),
        )

    def test_mixed_states_warn(self):
        for enabled, active in (
            ("enabled", "inactive"),
            ("disabled", "active"),
            ("masked", "inactive"),
            ("static", "activating"),
        ):
            with self.subTest(enabled=enabled, active=active):
                text, severity = runstate.service_badge(enabled, active)
                self.assertEqual(severity, "WARN")
                self.assertEqual(text, f"Boot service: {enabled} / {active}")

    def test_failed_is_fail(self):
        for enabled in ("enabled", "disabled"):
            with self.subTest(enabled=enabled):
                self.assertEqual(runstate.service_badge(enabled, "failed")[1], "FAIL")

    def test_disabled_inactive_is_neutral(self):
        for active in ("inactive", "dead", "", None):
            with self.subTest(active=active):
                self.assertEqual(runstate.service_badge("disabled", active)[1], "NEUTRAL")

    def test_unavailable_is_neutral(self):
        self.assertEqual(
            runstate.service_badge(None, None),
            ("Boot service: unavailable", "NEUTRAL"),
        )
        self.assertEqual(runstate.service_badge("", "active")[1], "NEUTRAL")


if __name__ == "__main__":
    unittest.main()
