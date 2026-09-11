#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# legion-powerbench tests. Every case runs against the fake root, so the whole limiter
# table in docs/TUNING.md section 2 is exercised on a machine with no Legion in it.

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export NO_COLOR=1

# shellcheck source=tests/lib.sh
source "$ROOT_DIR/tests/lib.sh"
# shellcheck source=tests/fixtures/make-fake-root.sh
source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$TMP"

# Reset every sensor to the neutral idle machine: cool, well under any cap.
reset_sensors() {
    printf '55000\n' > "$HWMON/hwmon0/temp1_input"
    printf '65000\n' > "$HWMON/hwmon0/temp3_input"
    printf '63000\n' > "$HWMON/hwmon0/temp4_input"
    printf '3000\n' > "$HWMON/hwmon1/fan1_input"
    printf '0\n' > "$POWER_SUPPLY/BAT0/power_now"
    LEGION_BENCH_ENV=()
    : > "$LOG"
}

# A ladder short enough to run in a test but shaped exactly like a real one.
short_run() {
    local out="$1"
    shift
    run_bench run --ladder stapm --from 65 --to 65 \
        --workload none --soak 2 --cool 0 --interval 1 --out "$out" "$@" >/dev/null 2>&1
}

package_source() {
    run_bench doctor 2>/dev/null | awk '$2 == "Package-power" { print $3 }' || true
}

reset_sensors

printf 'Test 1: doctor names every source it found\n'
output="$(run_bench doctor 2>&1 || true)"
assert_contains 'Tctl' "$output" 'doctor did not report Tctl'
assert_contains 'k10temp' "$output" 'doctor did not name the k10temp hwmon'
assert_contains '55.0 C' "$output" 'doctor did not read the fixture temperature'
assert_contains 'Package-power' "$output" 'doctor did not report a package-power source'
assert_contains 'turbostat' "$output" 'doctor did not prefer turbostat'
assert_contains 'nvidia-smi, read only' "$output" 'doctor did not report the GPU as read only'
assert_contains "active profile 'balanced-plus'" "$output" 'doctor did not read the active profile from the CLI'

printf 'Test 2: package-power sources fall back in documented order\n'
assert_eq 'turbostat' "$(package_source)" 'turbostat was not preferred'
LEGION_BENCH_ENV=(LEGION_FAKE_NO_TURBOSTAT=1)
assert_eq 'ryzenadj' "$(package_source)" 'ryzenadj was not the second choice'
LEGION_BENCH_ENV=(LEGION_FAKE_NO_TURBOSTAT=1 LEGION_FAKE_RYZENADJ_EMPTY_TABLE=1)
printf '45000000\n' > "$POWER_SUPPLY/BAT0/power_now"
assert_eq 'battery' "$(package_source)" 'the battery fallback was not reached'
printf '0\n' > "$POWER_SUPPLY/BAT0/power_now"
assert_contains 'FAIL Package-power    no source' "$(run_bench doctor 2>&1 || true)" \
    'a machine with no power source did not report one'
reset_sensors

printf 'Test 3: a missing k10temp is fatal to doctor, not a crash\n'
mv "$HWMON/hwmon0/name" "$HWMON/hwmon0/name.hidden"
output="$(run_bench doctor 2>&1 || true)"
assert_contains 'FAIL Tctl' "$output" 'doctor did not fail on a missing k10temp'
assert_exit 2 'doctor did not exit 2 when a source is missing' run_bench doctor
mv "$HWMON/hwmon0/name.hidden" "$HWMON/hwmon0/name"
reset_sensors

printf 'Test 4: sample writes the documented CSV header and one row per interval\n'
run_bench sample --duration 3 --interval 1 --out "$TMP/sample.csv" >/dev/null 2>&1
assert_eq 'step,phase,elapsed_s,stapm_w,slow_w,fast_w,temp_c,tctl_c,tccd_c,pkg_w,bzy_mhz,busy_pct,fan_rpm,gpu_w,gpu_limit_w,gpu_temp_c,gpu_util_pct,throughput' \
    "$(head -n1 "$TMP/sample.csv")" 'the CSV header changed'
assert_eq '3' "$(grep -c ',sample,' "$TMP/sample.csv")" 'sample did not emit one row per interval'
assert_contains '55.0,65.0' "$(<"$TMP/sample.csv")" 'Tctl and Tccd were not both recorded'

printf 'Test 5: dry-run applies nothing and loads nothing\n'
: > "$LOG"
output="$(run_bench run --ladder stapm --from 65 --to 85 --step 10 --dry-run \
    --out "$TMP/dry.csv" 2>&1)"
assert_contains 'DRY-RUN' "$output" 'dry-run did not print the plan'
assert_contains '--stapm 85 --slow 90 --fast 100' "$output" 'dry-run did not print the final step'
assert_eq '' "$(<"$LOG")" 'dry-run invoked a privileged helper'
assert_eq '1' "$(wc -l < "$TMP/dry.csv")" 'dry-run wrote sample rows'

printf 'Test 6: a run applies each step and restores the previous profile\n'
: > "$LOG"
short_run "$TMP/run.csv"
assert_file_contains 'ryzenadj --stapm-limit=65000 --slow-limit=70000 --fast-limit=80000 --tctl-temp=85' \
    "$LOG" 'the ladder step was not applied through the CLI'
assert_file_contains 'ryzenadj --stapm-limit=65000 --slow-limit=70000 --fast-limit=80000 --tctl-temp=78' \
    "$LOG" 'the previously active profile was not restored'
assert_eq 'balanced-plus' "$(sed -n 's/^ACTIVE_PROFILE=//p' "$ETC/config.conf")" \
    'the scratch profile was left selected'

printf 'Test 7: power limited by your own cap\n'
reset_sensors
# Package power sitting at the cap with the ceiling far away is the headroom case.
LEGION_BENCH_ENV=(LEGION_FAKE_PKG_W=64.5)
short_run "$TMP/power.csv"
output="$(run_bench report "$TMP/power.csv")"
assert_contains 'power limited by your own cap' "$output" 'the headroom case was not recognised'

printf 'Test 8: thermally limited\n'
reset_sensors
printf '84500\n' > "$HWMON/hwmon0/temp1_input"
LEGION_BENCH_ENV=(LEGION_FAKE_PKG_W=40.0)
short_run "$TMP/thermal.csv"
output="$(run_bench report "$TMP/thermal.csv")"
assert_contains 'thermally limited' "$output" 'the thermal ceiling case was not recognised'
refute_contains 'raise STAPM' "$output" 'a thermally limited machine was told to raise power'

printf 'Test 9: neither cap binds\n'
reset_sensors
LEGION_BENCH_ENV=(LEGION_FAKE_PKG_W=30.0)
short_run "$TMP/neither.csv"
output="$(run_bench report "$TMP/neither.csv")"
assert_contains 'neither cap binds' "$output" 'a machine below both caps was misclassified'

printf 'Test 10: missing telemetry is reported as inconclusive, not guessed\n'
reset_sensors
LEGION_BENCH_ENV=(LEGION_FAKE_NO_TURBOSTAT=1 LEGION_FAKE_RYZENADJ_EMPTY_TABLE=1)
short_run "$TMP/blind.csv"
output="$(run_bench report "$TMP/blind.csv")"
assert_contains 'inconclusive' "$output" 'a run with no power source produced a verdict anyway'
reset_sensors

printf 'Test 11: report refuses a file with no load samples\n'
printf 'step,phase\nidle,sample\n' > "$TMP/empty.csv"
assert_fails 'report accepted a file with no load phase' run_bench report "$TMP/empty.csv"
assert_fails 'report accepted a missing file' run_bench report "$TMP/does-not-exist.csv"

printf 'Test 12: invalid ladder arguments are rejected before anything is applied\n'
: > "$LOG"
assert_fails 'a run without a ladder was accepted' run_bench run --from 65 --to 75
assert_fails 'an unknown ladder was accepted' run_bench run --ladder volts --from 1 --to 2
assert_fails 'an inverted range was accepted' run_bench run --ladder stapm --from 85 --to 65
assert_fails 'a zero step was accepted' run_bench run --ladder stapm --from 65 --to 85 --step 0
assert_fails 'an unknown option was accepted' run_bench run --ladder stapm --from 65 --to 75 --turbo
assert_eq '' "$(<"$LOG")" 'a rejected run still invoked a helper'

printf 'Test 13: every ladder step runs even with no cooldown between them\n'
run_bench run --ladder stapm --from 65 --to 85 --step 10 --workload none \
    --soak 1 --cool 0 --interval 1 --out "$TMP/nocool.csv" >/dev/null 2>&1
assert_eq '3' "$(grep -c ',summary,' "$TMP/nocool.csv")" \
    'a zero cooldown stopped the ladder after the first step'

printf 'Test 14: the GPU is only ever read\n'
assert_eq '' "$(grep -n 'nvidia-smi.*-pl\|nvidia-smi.*--power-limit\|--lock-gpu-clocks' \
    "$ROOT_DIR/tools/legion-powerbench" || true)" \
    'the harness contains a GPU write; docs/WHY.md promises it never will'

printf '\nAll legion-powerbench tests passed.\n'
