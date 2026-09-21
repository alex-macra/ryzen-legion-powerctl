# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field

SCHEMA_VERSION = 1

POWER_MIN_W = 5
POWER_MAX_W = 200
TEMP_MIN_C = 50
TEMP_MAX_C = 100
BALANCED_PLUS_MAX_TEMP_C = 78

POWER_PROFILES = ("balanced", "performance", "power-saver", "unchanged")
POWER_PROFILE_ICON_NAMES = {
    "power-saver": "power-profile-power-saver-symbolic",
    "balanced": "power-profile-balanced-symbolic",
    "performance": "power-profile-performance-symbolic",
}
BOOST_VALUES = ("on", "off", "unchanged")
EPP_VALUES = (
    "performance",
    "balance_performance",
    "balance_power",
    "power",
    "unchanged",
)

CONTROL_CHARACTERS = frozenset(chr(code) for code in range(0x20)) | {chr(0x7F)}

PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FREQ_RE = re.compile(r"^(stock|unchanged|0|[1-9][0-9]*)$")

DOCTOR_LINE_RE = re.compile(r"^(OK|WARN|FAIL)\s+(\S+)\s+(.*)$")
DOCTOR_RESULT_RE = re.compile(r"^Doctor result: (\d+) failure\(s\), (\d+) warning\(s\)\.$")


class StatusParseError(ValueError):
    pass


@dataclass
class Profile:
    name: str
    valid: bool = True
    description: str = ""
    stapm_w: int = 60
    slow_w: int = 65
    fast_w: int = 75
    temp_c: int = 82
    power_profile: str = "balanced"
    min_freq_mhz: str = "unchanged"
    max_freq_mhz: str = "unchanged"
    boost: str = "unchanged"
    epp: str = "unchanged"

    def summary(self) -> str:
        if not self.valid:
            return "invalid profile file"
        return f"{self.stapm_w}/{self.slow_w}/{self.fast_w} W, {self.temp_c} C cap"


@dataclass
class Status:
    version: str
    active_profile: str
    power_profile: str | None
    cpu_driver: str | None
    cpu_epp: str | None
    ryzenadj: str | None
    service_enabled: str | None
    service_active: str | None
    last_apply: dict | None
    profiles: list[Profile] = field(default_factory=list)


@dataclass
class DoctorLine:
    status: str
    label: str
    detail: str


@dataclass
class DoctorReport:
    lines: list[DoctorLine]
    failures: int
    warnings: int
    exit_code: int
    text: str = ""


def parse_status(payload: str) -> Status:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StatusParseError(f"status --json produced invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StatusParseError("status --json did not produce a JSON object.")
    schema = data.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise StatusParseError(
            f"Unsupported status schema {schema!r}; this GUI understands "
            f"schema {SCHEMA_VERSION}. Update legion-powerctl and the GUI together."
        )

    profiles: list[Profile] = []
    for entry in data.get("profiles", []):
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        if not entry.get("valid", False):
            profiles.append(Profile(name=str(entry["name"]), valid=False))
            continue
        try:
            profiles.append(
                Profile(
                    name=str(entry["name"]),
                    valid=True,
                    description=str(entry.get("description", "")),
                    stapm_w=int(entry["stapm_w"]),
                    slow_w=int(entry["slow_w"]),
                    fast_w=int(entry["fast_w"]),
                    temp_c=int(entry["temp_c"]),
                    power_profile=str(entry.get("power_profile", "unchanged")),
                    min_freq_mhz=str(entry.get("min_freq_mhz", "unchanged")),
                    max_freq_mhz=str(entry.get("max_freq_mhz", "unchanged")),
                    boost=str(entry.get("boost", "unchanged")),
                    epp=str(entry.get("epp", "unchanged")),
                )
            )
        except (KeyError, TypeError, ValueError):
            profiles.append(Profile(name=str(entry["name"]), valid=False))

    service = data.get("service") or {}
    return Status(
        version=str(data.get("version", "")),
        active_profile=str(data.get("active_profile", "")),
        power_profile=data.get("power_profile"),
        cpu_driver=data.get("cpu_driver"),
        cpu_epp=data.get("cpu_epp"),
        ryzenadj=data.get("ryzenadj"),
        service_enabled=service.get("enabled") if isinstance(service, dict) else None,
        service_active=service.get("active") if isinstance(service, dict) else None,
        last_apply=data.get("last_apply") if isinstance(data.get("last_apply"), dict) else None,
        profiles=profiles,
    )


def parse_doctor(text: str, exit_code: int) -> DoctorReport:
    lines: list[DoctorLine] = []
    failures = warnings = None
    for raw in text.splitlines():
        match = DOCTOR_LINE_RE.match(raw)
        if match:
            lines.append(DoctorLine(match.group(1), match.group(2), match.group(3).strip()))
            continue
        match = DOCTOR_RESULT_RE.match(raw.strip())
        if match:
            failures = int(match.group(1))
            warnings = int(match.group(2))
    if failures is None:
        failures = sum(1 for line in lines if line.status == "FAIL")
    if warnings is None:
        warnings = sum(1 for line in lines if line.status == "WARN")
    return DoctorReport(
        lines=lines, failures=failures, warnings=warnings, exit_code=exit_code, text=text
    )


def profile_icon_name(power_profile: str) -> str:
    return POWER_PROFILE_ICON_NAMES.get(power_profile, "")


def clamp_power(value: int) -> int:
    return max(POWER_MIN_W, min(POWER_MAX_W, value))


def enforce_power_order(
    stapm: int, slow: int, fast: int, changed: str
) -> tuple[int, int, int]:
    stapm = clamp_power(stapm)
    slow = clamp_power(slow)
    fast = clamp_power(fast)
    if changed == "stapm":
        slow = max(slow, stapm)
        fast = max(fast, slow)
    elif changed == "slow":
        stapm = min(stapm, slow)
        fast = max(fast, slow)
    elif changed == "fast":
        slow = min(slow, fast)
        stapm = min(stapm, slow)
    else:
        raise ValueError(f"unknown slider {changed!r}")
    return stapm, slow, fast


def valid_profile_name(name: str) -> bool:
    return bool(PROFILE_NAME_RE.match(name))


def valid_frequency(value: str) -> bool:
    if not FREQ_RE.match(value):
        return False
    if value.isdigit():
        return 100 <= int(value) <= 10000
    return True


def validate_profile(profile: Profile) -> list[str]:
    problems: list[str] = []
    if not valid_profile_name(profile.name):
        problems.append("Profile name may use letters, numbers, dot, underscore, dash.")
    for label, value in (
        ("STAPM", profile.stapm_w),
        ("Slow PPT", profile.slow_w),
        ("Fast PPT", profile.fast_w),
    ):
        if not POWER_MIN_W <= value <= POWER_MAX_W:
            problems.append(f"{label} must be {POWER_MIN_W}-{POWER_MAX_W} W.")
    if not TEMP_MIN_C <= profile.temp_c <= TEMP_MAX_C:
        problems.append(f"Temperature must be {TEMP_MIN_C}-{TEMP_MAX_C} C.")
    elif profile.name == "balanced-plus" and profile.temp_c > BALANCED_PLUS_MAX_TEMP_C:
        problems.append(f"balanced-plus temperature must be at most {BALANCED_PLUS_MAX_TEMP_C} C.")
    if not profile.stapm_w <= profile.slow_w <= profile.fast_w:
        problems.append("Expected STAPM <= Slow PPT <= Fast PPT.")
    if profile.power_profile not in POWER_PROFILES:
        problems.append("Unknown Linux power profile.")
    if profile.boost not in BOOST_VALUES:
        problems.append("Boost must be on, off, or unchanged.")
    if profile.epp not in EPP_VALUES:
        problems.append("Unknown EPP preference.")
    for label, value in (("Minimum", profile.min_freq_mhz), ("Maximum", profile.max_freq_mhz)):
        if not valid_frequency(value):
            problems.append(f"{label} frequency must be stock, unchanged, or 100-10000 MHz.")
    if profile.min_freq_mhz.isdigit() and profile.max_freq_mhz.isdigit():
        if int(profile.min_freq_mhz) > int(profile.max_freq_mhz):
            problems.append("Minimum frequency cannot exceed maximum frequency.")
    if any(character in CONTROL_CHARACTERS for character in profile.description):
        problems.append("Description must be a single line with no control characters.")
    return problems


def cli_path() -> str:
    override = os.environ.get("LEGION_POWERCTL_GUI_CLI")
    if override:
        return override
    if os.path.exists("/usr/bin/legion-powerctl"):
        return "/usr/bin/legion-powerctl"
    found = shutil.which("legion-powerctl")
    return found or "/usr/bin/legion-powerctl"


def unprivileged_command(args: list[str]) -> list[str]:
    return [cli_path(), *args]


def elevation_command() -> str | None:
    elevate = os.environ.get("LEGION_POWERCTL_GUI_ELEVATE")
    if elevate == "none" or (elevate is None and os.geteuid() == 0):
        return None
    return elevate or "pkexec"


def privileged_command(args: list[str]) -> list[str]:
    elevate = elevation_command()
    command = [cli_path(), *args]
    return [elevate, *command] if elevate else command


def build_configure_args(
    profile: Profile, apply_now: bool = False, select: bool = False
) -> list[str]:
    args = [
        "configure",
        profile.name,
        "--stapm", str(profile.stapm_w),
        "--slow", str(profile.slow_w),
        "--fast", str(profile.fast_w),
        "--temp", str(profile.temp_c),
        "--power-profile", profile.power_profile,
        "--min-mhz", profile.min_freq_mhz,
        "--max-mhz", profile.max_freq_mhz,
        "--boost", profile.boost,
        "--epp", profile.epp,
        "--description", profile.description,
    ]
    if select:
        args.append("--select")
    if apply_now:
        args.append("--apply")
    return args


def build_apply_args(profile_name: str) -> list[str]:
    return ["apply", profile_name]


def build_select_args(profile_name: str) -> list[str]:
    return ["select", profile_name]


def build_delete_args(profile_name: str) -> list[str]:
    return ["delete", profile_name]
