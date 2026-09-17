#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export NO_COLOR=1

# shellcheck source=tests/lib.sh
source "$ROOT_DIR/tests/lib.sh"
# shellcheck source=tests/fixtures/make-fake-root.sh
source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$TMP"

CSV_HEADER='step,phase,elapsed_s,stapm_w,slow_w,fast_w,temp_c,tctl_c,tccd_c,pkg_w,bzy_mhz,busy_pct,fan_rpm,gpu_w,gpu_limit_w,gpu_temp_c,gpu_util_pct,throughput'
cp "$STATE/last-apply.env" "$TMP/known-last-apply.env"
cp "$PROFILES/balanced-plus.conf" "$TMP/known-balanced-plus.conf"
cp "$ETC/config.conf" "$TMP/known-config.conf"

reset_machine() {
    cp "$TMP/known-last-apply.env" "$STATE/last-apply.env"
    cp "$TMP/known-balanced-plus.conf" "$PROFILES/balanced-plus.conf"
    cp "$TMP/known-config.conf" "$ETC/config.conf"
    printf '55000\n' > "$HWMON/hwmon0/temp1_input"
    printf '65000\n' > "$HWMON/hwmon0/temp3_input"
    printf '63000\n' > "$HWMON/hwmon0/temp4_input"
    printf '3000\n' > "$HWMON/hwmon1/fan1_input"
    printf '0\n' > "$POWER_SUPPLY/BAT0/power_now"
    LEGION_BENCH_ENV=()
    : > "$LOG"
}

short_run() {
    local out="$1"
    shift
    run_bench run --ladder stapm --from 65 --to 65 \
        --workload none --soak 1 --cool 0 --interval 1 --out "$out" "$@"
}

package_source() {
    run_bench doctor 2>/dev/null | awk '$2 == "Package-power" { print $3 }' || true
}

assert_restored_once() {
    assert_eq '1' "$(grep -c -- '--tctl-temp=78' "$LOG" || true)" \
        'the previously applied profile was not restored exactly once'
    assert_file_contains 'PROFILE=balanced-plus' "$STATE/last-apply.env" \
        'the restored profile was not recorded'
    assert_eq '' "$(find "$PROFILES" -maxdepth 1 -name 'powerbench-*.conf' -print)" \
        'a scratch profile was left behind'
}

write_report() {
    local out="$1" temperature="$2" power="$3" early_temperature="${4:-55}" early_power="${5:-30}"
    local elapsed t p
    printf '%s\n' "$CSV_HEADER" > "$out"
    for (( elapsed = 5; elapsed <= 600; elapsed += 5 )); do
        t="$early_temperature" p="$early_power"
        if (( elapsed > 480 )); then t="$temperature"; p="$power"; fi
        printf 'stapm-65,load,%s,65,70,80,85,%s,65,%s,4200,99,3000,140.5,175,72,98,\n' \
            "$elapsed" "$t" "$p" >> "$out"
    done
    printf 'stapm-65,summary,600,65,70,80,85,%s,65,%s,4200,99,3000,140.5,175,72,98,\n' \
        "$temperature" "$power" >> "$out"
}

reset_machine

printf 'Test 1: a temperature sweep preserves all last-applied wattages\n'
sed -i 's/^ACTIVE_PROFILE=.*/ACTIVE_PROFILE=quiet/' "$ETC/config.conf"
sed -i -e 's/^STAPM_W=.*/STAPM_W=64/' -e 's/^SLOW_W=.*/SLOW_W=73/' \
    -e 's/^FAST_W=.*/FAST_W=89/' "$PROFILES/balanced-plus.conf" "$STATE/last-apply.env"
output="$(run_bench run --ladder temp --from 85 --to 90 --dry-run \
    --out "$TMP/temp-dry.csv" 2>&1)"
assert_contains '--stapm 64 --slow 73 --fast 89 --temp 85' "$output" \
    'the temperature sweep changed the running profile wattage'
assert_contains '--stapm 64 --slow 73 --fast 89 --temp 90' "$output" \
    'the second temperature step changed the running profile wattage'
assert_contains 'apply balanced-plus' "$output" 'the boot selection was used as the restoration profile'
assert_eq '' "$(<"$LOG")" 'dry-run invoked a privileged helper'
[[ ! -e "$TMP/temp-dry.csv" ]] || { printf 'FAIL: dry-run created an output file\n' >&2; exit 1; }
reset_machine

printf 'Test 2: doctor recognises command-mode turbostat output on stderr\n'
output="$(run_bench doctor 2>&1 || true)"
assert_contains 'Tctl' "$output" 'doctor did not report Tctl'
assert_contains 'k10temp' "$output" 'doctor did not name the k10temp hwmon'
assert_contains '55.0 C' "$output" 'doctor did not read the fixture temperature'
assert_contains 'Package-power' "$output" 'doctor did not report a package-power source'
assert_contains 'turbostat' "$output" 'doctor did not prefer turbostat'
assert_contains 'nvidia-smi, read only' "$output" 'doctor did not report the GPU as read only'
assert_contains "balanced-plus" "$output" 'doctor did not read the profile from the CLI'

printf 'Test 3: battery draw is never used as CPU package power\n'
LEGION_BENCH_ENV=(LEGION_FAKE_NO_TURBOSTAT=1)
assert_eq 'ryzenadj' "$(package_source)" 'ryzenadj was not the second choice'
LEGION_BENCH_ENV=(LEGION_FAKE_NO_TURBOSTAT=1 LEGION_FAKE_RYZENADJ_EMPTY_TABLE=1)
printf '45000000\n' > "$POWER_SUPPLY/BAT0/power_now"
assert_contains 'FAIL Package-power' "$(run_bench doctor 2>&1 || true)" \
    'battery-only telemetry was accepted as CPU package power'
run_bench sample --duration 1 --interval 1 --out "$TMP/battery.csv" >/dev/null 2>&1
assert_eq '' "$(awk -F, 'NR == 2 { print $10 }' "$TMP/battery.csv")" \
    'battery draw was recorded as CPU package power'
reset_machine

printf 'Test 4: a missing k10temp gives a diagnostic failure\n'
mv "$HWMON/hwmon0/name" "$HWMON/hwmon0/name.hidden"
assert_exit 2 'doctor did not exit 2 when a temperature source is missing' run_bench doctor
mv "$HWMON/hwmon0/name.hidden" "$HWMON/hwmon0/name"

printf 'Test 5: sampling reads reordered turbostat columns and keeps the CSV interface\n'
run_bench sample --duration 2 --interval 1 --out "$TMP/sample.csv" >/dev/null 2>&1
assert_eq "$CSV_HEADER" "$(head -n1 "$TMP/sample.csv")" 'the CSV header changed'
assert_eq '2' "$(grep -c ',sample,' "$TMP/sample.csv")" 'sample did not emit one row per interval'
assert_eq '55.0,65.0,30.0,4200,99.0' \
    "$(awk -F, 'NR == 2 { print $8 "," $9 "," $10 "," $11 "," $12 }' "$TMP/sample.csv")" \
    'real command-mode telemetry was not read by column name'

printf 'Test 6: a power dry-run changes no files or hardware\n'
: > "$LOG"
output="$(run_bench run --ladder stapm --from 65 --to 85 --step 10 --dry-run \
    --out "$TMP/dry.csv" 2>&1)"
assert_contains 'DRY-RUN' "$output" 'dry-run did not print the plan'
assert_contains '--stapm 85 --slow 90 --fast 100' "$output" 'dry-run did not print the final step'
assert_eq '' "$(<"$LOG")" 'dry-run invoked a privileged helper'
[[ ! -e "$TMP/dry.csv" ]] || { printf 'FAIL: dry-run created an output file\n' >&2; exit 1; }

printf 'Test 7: temperature steps restore the running profile and remove their scratch profile\n'
sed -i 's/^ACTIVE_PROFILE=.*/ACTIVE_PROFILE=quiet/' "$ETC/config.conf"
run_bench run --ladder temp --from 85 --to 90 --workload none \
    --soak 1 --cool 0 --interval 1 --out "$TMP/temp.csv" >/dev/null 2>&1
assert_file_contains 'ryzenadj --stapm-limit=65000 --slow-limit=70000 --fast-limit=80000 --tctl-temp=85' \
    "$LOG" 'the first temperature step changed CPU power limits'
assert_file_contains 'ryzenadj --stapm-limit=65000 --slow-limit=70000 --fast-limit=80000 --tctl-temp=90' \
    "$LOG" 'the second temperature step changed CPU power limits'
assert_restored_once
assert_eq 'quiet' "$(sed -n 's/^ACTIVE_PROFILE=//p' "$ETC/config.conf")" \
    'the benchmark changed the boot profile selection'
reset_machine

printf 'Test 8: scratch profiles preserve all optional policy settings\n'
run_cli configure balanced-plus --power-profile performance --min-mhz 1300 --max-mhz 4000 \
    --boost off --epp power --apply >/dev/null 2>&1
: > "$LOG"
printf -v policy_command \
    'grep -Fxq 1300000 %q && grep -Fxq 4000000 %q && grep -Fxq 0 %q && grep -Fxq power %q && printf checked > %q && sleep 300' \
    "$SYSFS/cpufreq/policy0/scaling_min_freq" "$SYSFS/cpufreq/policy0/scaling_max_freq" \
    "$SYSFS/cpufreq/boost" "$SYSFS/cpufreq/policy0/energy_performance_preference" "$TMP/policy-checked"
short_run "$TMP/policy.csv" --workload-cmd "$policy_command" >/dev/null 2>&1
assert_file_contains 'checked' "$TMP/policy-checked" 'the trial changed live frequency, boost, or EPP policy'
assert_eq '1' "$(grep -c '^powerprofilesctl set ' "$LOG" || true)" \
    'the trial changed the platform policy before restoration'
assert_restored_once
reset_machine

printf 'Test 9: unsafe restoration state is rejected before any writes\n'
for condition in missing-state failed-apply rejected-apply missing-profile invalid-profile edited-profile incomplete-state; do
    reset_machine
    case "$condition" in
        missing-state) rm "$STATE/last-apply.env" ;;
        failed-apply) sed -i 's/^RESULT=.*/RESULT=failed/' "$STATE/last-apply.env" ;;
        rejected-apply) sed -i 's/^VERIFIED=.*/VERIFIED=no/' "$STATE/last-apply.env" ;;
        missing-profile) rm "$PROFILES/balanced-plus.conf" ;;
        invalid-profile) printf 'TEMP_C=invalid\n' >> "$PROFILES/balanced-plus.conf" ;;
        edited-profile) sed -i 's/^BOOST=.*/BOOST=off/' "$PROFILES/balanced-plus.conf" ;;
        incomplete-state) sed -i '/^FAST_W=/d' "$STATE/last-apply.env" ;;
    esac
    assert_fails "$condition was accepted for a live run" short_run "$TMP/refused.csv"
    assert_fails "$condition was accepted for a dry-run" short_run "$TMP/refused.csv" --dry-run
    assert_eq '' "$(<"$LOG")" "$condition caused a hardware write"
    [[ ! -e "$TMP/refused.csv" ]] || { printf 'FAIL: rejected run created output\n' >&2; exit 1; }
done
reset_machine

printf 'Test 10: a successful apply with unavailable readback remains restorable\n'
sed -i 's/^VERIFIED=.*/VERIFIED=unknown/' "$STATE/last-apply.env"
short_run "$TMP/unknown.csv" --dry-run >/dev/null 2>&1
reset_machine

printf 'Test 11: a scratch-name collision cannot overwrite a saved profile\n'
LEGION_BENCH_ENV=(LEGION_POWERBENCH_PROFILE_NAME=balanced-plus)
assert_fails 'a colliding scratch name was accepted' short_run "$TMP/collision.csv"
assert_fails 'a dry-run accepted a colliding scratch name' short_run "$TMP/collision.csv" --dry-run
cmp "$TMP/known-balanced-plus.conf" "$PROFILES/balanced-plus.conf"
assert_eq '' "$(<"$LOG")" 'a scratch-name collision caused a hardware write'
reset_machine

printf 'Test 12: the final two minutes determine sustained power limits\n'
write_report "$TMP/power.csv" 55 64.5 84.5 30
output="$(run_bench report "$TMP/power.csv")"
assert_contains 'power limited by your own cap' "$output" 'warmup values diluted the sustained power limit'
assert_contains '64.5' "$output" 'the sustained package-power average was wrong'
assert_contains '55.0' "$output" 'the sustained temperature average was wrong'

printf 'Test 13: the final two minutes determine thermal limits\n'
write_report "$TMP/thermal.csv" 84.5 40 55 64.5
output="$(run_bench report "$TMP/thermal.csv")"
assert_contains 'thermally limited' "$output" 'the sustained thermal limit was not recognised'
refute_contains 'raise STAPM' "$output" 'a thermally limited machine was told to raise power'

printf 'Test 14: neither cap binding is inconclusive\n'
write_report "$TMP/neither.csv" 55 30
output="$(run_bench report "$TMP/neither.csv")"
assert_contains 'inconclusive' "$output" 'unbound caps produced a guessed limiter'
refute_contains 'a current or firmware limit' "$output" 'the report invented an unmeasured limiter'

printf 'Test 15: missing and invalid telemetry are inconclusive\n'
overflowing_decimal="$(printf '%0400d' 0 | tr '0' '9')"
for value in '' bad NaN inf -1 1e309 "$overflowing_decimal"; do
    write_report "$TMP/blind.csv" 55 "$value"
    output="$(run_bench report "$TMP/blind.csv")"
    assert_contains 'inconclusive' "$output" 'invalid package power produced a limiter verdict'
    write_report "$TMP/blind.csv" "$value" 64.5
    output="$(run_bench report "$TMP/blind.csv")"
    assert_contains 'inconclusive' "$output" 'invalid temperature produced a limiter verdict'
done
write_report "$TMP/sparse.csv" 55 64.5
awk -F, 'NR == 1 || $3 == 600' "$TMP/sparse.csv" > "$TMP/sparse-tail.csv"
assert_contains 'inconclusive' "$(run_bench report "$TMP/sparse-tail.csv")" \
    'a single final reading produced a sustained verdict'

printf 'Test 16: a short soak cannot establish sustained performance\n'
short_run "$TMP/short.csv" >/dev/null 2>&1
output="$(run_bench report "$TMP/short.csv")"
assert_contains 'inconclusive' "$output" 'a one-second run produced a sustained verdict'
assert_restored_once
reset_machine

printf 'Test 17: report rejects missing files and files without load samples\n'
printf 'step,phase\nidle,sample\n' > "$TMP/empty.csv"
assert_fails 'report accepted a file with no load phase' run_bench report "$TMP/empty.csv"
assert_fails 'report accepted a missing file' run_bench report "$TMP/does-not-exist.csv"

printf 'Test 18: invalid numeric arguments are rejected before creating output\n'
for option in '--from text' '--from 1+2' '--to 199' '--step 0' '--step -1' '--soak 0' \
    '--cool -1' '--interval 0' '--interval 1.5' '--temp NaN' '--temp 101'; do
    read -r flag value <<< "$option"
    assert_fails "$option was accepted" short_run "$TMP/invalid.csv" "$flag" "$value"
    [[ ! -e "$TMP/invalid.csv" ]] || { printf 'FAIL: invalid arguments created output\n' >&2; exit 1; }
done
assert_fails 'a run without a ladder was accepted' run_bench run --from 65 --to 75
assert_fails 'an unknown ladder was accepted' run_bench run --ladder volts --from 1 --to 2
assert_fails 'an inverted range was accepted' run_bench run --ladder stapm --from 85 --to 65
assert_fails 'an unknown workload was accepted' short_run "$TMP/invalid.csv" --workload unknown
assert_fails 'a temp ladder accepted a second temperature setting' \
    run_bench run --ladder temp --from 85 --to 90 --temp 85
assert_fails 'sample accepted a zero interval' run_bench sample --duration 1 --interval 0 --out "$TMP/invalid.csv"
assert_fails 'sample accepted invalid duration' run_bench sample --duration bad --out "$TMP/invalid.csv"
assert_eq '' "$(<"$LOG")" 'a rejected command still invoked a hardware helper'
[[ ! -e "$TMP/invalid.csv" ]] || { printf 'FAIL: rejected command created output\n' >&2; exit 1; }

printf 'Test 19: invalid sensor values are omitted from sampled telemetry\n'
printf 'not-a-temperature\n' > "$HWMON/hwmon0/temp1_input"
LEGION_BENCH_ENV=(LEGION_FAKE_PKG_W=NaN LEGION_FAKE_GPU_W=-1)
run_bench sample --duration 1 --interval 1 --out "$TMP/invalid-telemetry.csv" >/dev/null 2>&1
assert_eq ',,' "$(awk -F, 'NR == 2 { print $8 "," $10 "," $14 }' "$TMP/invalid-telemetry.csv")" \
    'invalid sensor readings were emitted as measurements'
reset_machine

printf 'Test 20: custom workload log numbers are never guessed as throughput\n'
short_run "$TMP/custom.csv" --workload-cmd "printf 'pid 1234 elapsed 500 score 42\\n'; sleep 300" >/dev/null 2>&1
assert_eq '' "$(awk -F, '$2 == "summary" { print $18 }' "$TMP/custom.csv")" \
    'a custom workload log number was guessed as throughput'
reset_machine

printf 'Test 21: stress-ng throughput uses the real-time metrics column\n'
LEGION_BENCH_ENV=(LEGION_POWERBENCH_STRESS_NG_BIN="$FAKEBIN/stress-ng")
short_run "$TMP/stress.csv" --workload cpu >/dev/null 2>&1
assert_eq '1200.50' "$(awk -F, '$2 == "summary" { print $18 }' "$TMP/stress.csv")" \
    'stress-ng throughput did not use bogo ops per real elapsed second'
reset_machine

printf 'Test 22: every power step runs with zero cooldown\n'
run_bench run --ladder stapm --from 65 --to 85 --step 10 --workload none \
    --soak 1 --cool 0 --interval 1 --out "$TMP/nocool.csv" >/dev/null 2>&1
assert_eq '3' "$(grep -c ',summary,' "$TMP/nocool.csv")" 'zero cooldown ended the ladder early'
assert_restored_once
reset_machine

printf 'Test 23: a failing workload restores the previous profile\n'
assert_fails 'a failed workload was reported as successful' short_run "$TMP/failed-load.csv" --workload-cmd 'exit 7'
assert_restored_once
reset_machine

printf 'Test 24: a failing apply restores the previous profile\n'
LEGION_BENCH_ENV=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=85)
assert_fails 'a failed apply was reported as successful' short_run "$TMP/failed-apply.csv"
assert_restored_once
reset_machine

printf 'Test 25: expiry and interrupts stop workload descendants and restore once\n'
for signal_name in none SIGINT SIGTERM; do
    reset_machine
    python3 - "$BENCH_CLI" "$TMP" "$signal_name" "${BENCH_ENV[@]}" <<'PY'
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

bench, root, signal_name, *environment = sys.argv[1:]
env = os.environ | dict(item.split("=", 1) for item in environment)
root = Path(root)
leader_file = root / f"{signal_name}.leader"
child_file = root / f"{signal_name}.child"
command = (
    f"printf '%s\\n' \"$$\" > {shlex.quote(str(leader_file))}; "
    f"sleep 300 & printf '%s\\n' \"$!\" > {shlex.quote(str(child_file))}; wait"
)
process = subprocess.Popen(
    [bench, "run", "--ladder", "stapm", "--from", "65", "--to", "65",
     "--workload-cmd", command, "--soak", "1" if signal_name == "none" else "30",
     "--cool", "0", "--interval", "1", "--out", str(root / f"{signal_name}.csv")],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
)
pids = []


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


try:
    deadline = time.monotonic() + 15
    while not (leader_file.exists() and child_file.exists() and child_file.stat().st_size):
        if process.poll() is not None or time.monotonic() >= deadline:
            raise AssertionError(f"{signal_name}: workload did not start")
        time.sleep(0.02)
    pids = [int(path.read_text()) for path in (leader_file, child_file)]
    if signal_name != "none":
        process.send_signal(getattr(signal, signal_name))
    stdout, stderr = process.communicate(timeout=10)
    expected_success = signal_name == "none"
    assert (process.returncode == 0) == expected_success, (process.returncode, stdout, stderr)
    deadline = time.monotonic() + 3
    while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not any(alive(pid) for pid in pids), f"{signal_name}: workload descendants survived"
finally:
    if process.poll() is None:
        process.kill()
        process.communicate()
    for pid in pids:
        if alive(pid):
            os.kill(pid, signal.SIGKILL)
PY
    assert_restored_once
done
reset_machine

printf 'Test 26: restoration failure is returned to the caller\n'
LEGION_BENCH_ENV=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=78)
assert_fails 'a failed restoration was reported as successful' short_run "$TMP/failed-restore.csv"
assert_eq '1' "$(grep -c -- '--tctl-temp=78' "$LOG" || true)" 'restoration was attempted more than once'
rm -f -- "$PROFILES"/powerbench-*.conf
reset_machine

printf 'Test 27: the GPU is only ever read\n'
assert_eq '' "$(grep -n 'nvidia-smi.*-pl\|nvidia-smi.*--power-limit\|--lock-gpu-clocks' \
    "$ROOT_DIR/tools/legion-powerbench" || true)" \
    'the harness contains a GPU write'

printf 'Test 28: losing turbostat after detection preserves sampling intervals\n'
reset_machine
LEGION_BENCH_ENV=(LEGION_FAKE_TURBOSTAT_READ_COUNTER="$TMP/turbostat-reads" LEGION_FAKE_TURBOSTAT_FAIL_AFTER=1)
run_bench sample --duration 2 --interval 1 --out "$TMP/lost-turbostat.csv" >/dev/null 2>&1
rows="$(awk -F, '$2 == "sample" { count++ } END { print count + 0 }' "$TMP/lost-turbostat.csv")"
if (( rows < 1 || rows > 2 )); then
    printf 'FAIL: failed telemetry produced %s rows in two sampling intervals\n' "$rows" >&2
    exit 1
fi
assert_eq "$(( rows + 1 ))" "$(<"$TMP/turbostat-reads")" 'failed telemetry was retried without pacing'
awk -F, 'NR > 1 { if ($3 <= previous || $10 != "") exit 1; previous = $3 }
    END { if (previous < 2) exit 1 }' "$TMP/lost-turbostat.csv" || {
    printf 'FAIL: failed telemetry did not retain blank package power and advancing sample-end times\n' >&2
    cat "$TMP/lost-turbostat.csv" >&2
    exit 1
}
reset_machine

printf 'Test 29: sampling to stdout retains the header and every row\n'
output="$(run_bench sample --duration 2 --interval 1 2>"$TMP/stdout.stderr")"
assert_eq "$CSV_HEADER" "$(head -n1 <<< "$output")" 'stdout sampling lost the CSV header'
assert_eq '2' "$(awk -F, '$2 == "sample" { count++ } END { print count + 0 }' <<< "$output")" \
    'stdout sampling lost a sample row'
assert_eq '3' "$(wc -l <<< "$output")" 'stdout sampling mixed diagnostics with CSV data'

printf 'Test 30: an existing CSV cannot be overwritten or trigger an apply\n'
printf 'preserved benchmark measurements\n' > "$TMP/existing.csv"
cp "$TMP/existing.csv" "$TMP/existing.expected"
assert_fails 'sample overwrote an existing CSV' \
    run_bench sample --duration 1 --interval 1 --out "$TMP/existing.csv"
assert_fails 'run overwrote an existing CSV' short_run "$TMP/existing.csv"
cmp "$TMP/existing.expected" "$TMP/existing.csv"
assert_eq '' "$(<"$LOG")" 'an output-file collision still applied hardware limits'

printf 'Test 31: a successful workload cannot end early within the final sample interval\n'
reset_machine
assert_fails 'a workload that finished before the soak was reported as successful' \
    short_run "$TMP/early-success.csv" --soak 3 --interval 3 --workload-cmd 'sleep 0.1'
assert_eq '0' "$(grep -c ',summary,' "$TMP/early-success.csv" || true)" \
    'an early workload exit produced a completed-step summary'
assert_restored_once
reset_machine

printf 'Test 32: a report needs coverage across the final two minutes\n'
write_report "$TMP/covered.csv" 55 64.5
awk -F, 'BEGIN { OFS = "," }
    NR == 1 || $2 == "summary" { print }
    $2 == "load" && $3 == 600 { $3 = 599; print; $3 = 600; print }' \
    "$TMP/covered.csv" > "$TMP/missing-history.csv"
assert_contains 'inconclusive' "$(run_bench report "$TMP/missing-history.csv")" \
    'two final readings were presented as sustained performance'
awk -F, '$2 != "load" || $3 <= 500 || $3 >= 540' \
    "$TMP/covered.csv" > "$TMP/gapped-history.csv"
assert_contains 'inconclusive' "$(run_bench report "$TMP/gapped-history.csv")" \
    'a 40-second gap was accepted as continuous sustained measurements'

printf 'Test 33: duplicate sample timestamps make a report inconclusive\n'
write_report "$TMP/covered.csv" 55 64.5
awk -F, '$2 == "load" && $3 == 595 { print } { print }' \
    "$TMP/covered.csv" > "$TMP/duplicate-time.csv"
assert_contains 'inconclusive' "$(run_bench report "$TMP/duplicate-time.csv")" \
    'duplicate timestamps were accepted as continuous sustained measurements'

printf '\nAll legion-powerbench tests passed.\n'
