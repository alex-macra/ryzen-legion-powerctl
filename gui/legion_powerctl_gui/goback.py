# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import model

SCRATCH_PREFIX = "powerbench-"

REAPPLY = "reapply"
SELECT_AND_APPLY = "select-and-apply"
APPLY_THEN_RESTORE_BOOT = "apply-then-restore-boot"


@dataclass(frozen=True)
class GoBack:
    profile: str = ""
    boot: str = ""
    applied: str = ""

    def invalid_name(self) -> str | None:
        for candidate in (self.profile, self.boot):
            if candidate and not model.valid_profile_name(candidate):
                return candidate
        return None

    def plan(self) -> str:
        if self.boot and self.boot == self.applied:
            return REAPPLY
        if not self.boot or self.boot == self.profile:
            return SELECT_AND_APPLY
        return APPLY_THEN_RESTORE_BOOT

    def half_done(self) -> GoBack:
        return GoBack(self.profile, self.boot)

    def half_done_message(self, reason: str) -> str:
        return (
            f"Applied '{self.profile}', but could not set '{self.boot}' back as the boot "
            f"profile: {reason}"
        )


NO_OFFER = GoBack()


def offer_for(running: str, boot: str, applying: str) -> GoBack:
    if running in ("", applying) or running.startswith(SCRATCH_PREFIX):
        return NO_OFFER
    return GoBack(running, "" if boot.startswith(SCRATCH_PREFIX) else boot, applying)


def _lines(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


@dataclass(frozen=True)
class Steps:
    offer: GoBack = NO_OFFER
    withdraw: bool = False
    on_fail: Callable[[str, str], bool] | None = None
    on_success: Callable[[], object] | None = None
    then: Callable[[str], None] | None = None
    on_output: Callable[[int, str, str], str] | None = None
    after: Callable[[], object] | None = None
    on_error: Callable[[str], None] | None = None
    carried: str = ""

    def finish(
        self, code: int, stdout: str, stderr: str, cancelled: bool,
        report: Callable[[int, str, str], None],
    ) -> None:
        if code != 0 and self.on_error is not None:
            reason = "authorisation was cancelled." if cancelled else (
                stderr.strip() or stdout.strip() or "the command failed."
            )
            self.on_error(_lines(reason, self.carried.strip()))
            return
        stderr = _lines(self.carried.strip(), stderr.strip())
        if code == 0 and self.then is not None:
            self.then(stderr)
            return
        if self.on_output is not None:
            stderr = self.on_output(code, stdout, stderr)
        if code == 0 and self.on_success is not None:
            self.on_success()
        report(code, stdout, stderr)
        if self.after is not None:
            self.after()


NO_STEPS = Steps()
