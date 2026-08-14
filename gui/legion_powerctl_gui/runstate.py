# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import model

_LIMITS = ("stapm_w", "slow_w", "fast_w", "temp_c")


@dataclass
class RunState:
    profile: str = ""
    stapm_w: int | None = None
    slow_w: int | None = None
    fast_w: int | None = None
    temp_c: int | None = None
    result: str = ""
    verified: str = ""
    applied_at: str = ""

    @property
    def applied(self) -> bool:
        return bool(self.profile)

    @property
    def partial(self) -> bool:
        return self.result == "partial"

    def headline(self) -> str:
        if not self.applied:
            return "Firmware defaults"
        return f"{self.profile} - PARTIALLY APPLIED" if self.partial else self.profile

    def summary(self) -> str:
        if not self.applied:
            return "nothing applied since this boot"
        if None in (self.stapm_w, self.slow_w, self.fast_w, self.temp_c):
            return ""
        return f"{self.stapm_w}/{self.slow_w}/{self.fast_w} W, {self.temp_c} C cap"

    def mark(self) -> tuple[str, str]:
        if not self.applied:
            return ("", "NEUTRAL")
        if self.partial:
            return ("limits did not take", "FAIL")
        if self.verified == "yes":
            return ("confirmed", "OK")
        if self.verified == "no":
            return ("limits did not take", "FAIL")
        return ("unverified", "WARN")

    def when(self, now: datetime | None = None) -> str:
        if not self.applied_at:
            return ""
        try:
            stamp = datetime.fromisoformat(self.applied_at)
        except ValueError:
            return f"applied {self.applied_at}"
        reference = now or datetime.now(tz=stamp.tzinfo)
        if stamp.date() == reference.date():
            return f"applied {stamp:%H:%M} today"
        return f"applied {stamp:%Y-%m-%d %H:%M}"


def run_state(status: model.Status) -> RunState:
    record = status.last_apply or {}
    state = RunState(
        profile=str(record.get("profile", "")),
        result=str(record.get("result", "")),
        verified=str(record.get("verified", "")),
        applied_at=str(record.get("applied_at", "")),
    )
    for key in _LIMITS:
        raw = record.get(key)
        try:
            setattr(state, key, int(str(raw)))
        except (TypeError, ValueError):
            setattr(state, key, None)
    return state


@dataclass
class Delta:
    label: str
    was: int
    now: int
    unit: str


def raising_deltas(running: RunState, profile: model.Profile) -> list[Delta]:
    if not running.applied:
        return []
    deltas = []
    for label, key, target, unit in (
        ("Sustained", "stapm_w", profile.stapm_w, "W"),
        ("Slow PPT", "slow_w", profile.slow_w, "W"),
        ("Fast PPT", "fast_w", profile.fast_w, "W"),
        ("Ceiling", "temp_c", profile.temp_c, "C"),
    ):
        was = getattr(running, key)
        if was is not None and target > was:
            deltas.append(Delta(label, was, target, unit))
    return deltas


def service_badge(enabled: str | None, active: str | None) -> tuple[str, str]:
    if not enabled:
        return ("Boot service: unavailable", "NEUTRAL")
    text = f"Boot service: {enabled} / {active}"
    if active == "failed":
        return (text, "FAIL")
    if enabled == "enabled" and active == "active":
        return (text, "OK")
    if enabled == "disabled" and active in (None, "", "inactive", "dead"):
        return (text, "NEUTRAL")
    return (text, "WARN")
