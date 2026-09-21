#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT_DIR/bin/legion-powerctl"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=tests/lib.sh
source "$ROOT_DIR/tests/lib.sh"
# shellcheck source=tests/fixtures/make-fake-root.sh
source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$TMP"

printf 'Test 1: configure, select, and apply a profile\n'
run_cli configure dev \
    --stapm 55 --slow 60 --fast 70 --temp 80 \
    --power-profile balanced --min-mhz stock --max-mhz stock \
    --boost on --epp balance_performance --select --apply >/dev/null

assert_file_contains 'ACTIVE_PROFILE=dev' "$ETC/config.conf" 'profile was not selected'
assert_file_contains 'STAPM_W=55' "$PROFILES/dev.conf" 'profile was not written'
assert_file_contains 'ryzenadj --stapm-limit=55000 --slow-limit=60000 --fast-limit=70000 --tctl-temp=80' "$LOG" 'RyzenAdj arguments are wrong'
assert_file_contains 'powerprofilesctl set balanced' "$LOG" 'power profile was not requested'
assert_eq '1200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" 'stock minimum was not restored'
assert_eq '5460000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" 'stock maximum was not restored'
assert_eq '1' "$(<"$SYSFS/cpufreq/boost")" 'boost was not enabled'
assert_eq 'balance_performance' "$(<"$SYSFS/cpufreq/policy0/energy_performance_preference")" 'EPP was not applied'
assert_file_contains 'PROFILE=dev' "$STATE/last-apply.env" 'runtime state was not recorded'

printf 'Test 2: status reads the configured profile\n'
assert_contains 'Active profile:  dev' "$(run_cli status)" 'status did not show the active profile'

printf 'Test 3: invalid power ordering is rejected\n'
assert_fails 'invalid profile was accepted' \
    run_cli configure bad --stapm 80 --slow 60 --fast 70 --temp 80

printf 'Test 4: dry-run does not modify CPUFreq or invoke helpers\n'
printf '2200000\n' > "$SYSFS/cpufreq/policy0/scaling_min_freq"
printf '3200000\n' > "$SYSFS/cpufreq/policy0/scaling_max_freq"
printf '0\n' > "$SYSFS/cpufreq/boost"
: > "$LOG"
run_cli apply dev --dry-run >/dev/null
assert_eq '2200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" 'dry-run changed minimum frequency'
assert_eq '3200000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" 'dry-run changed maximum frequency'
assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'dry-run changed boost'
assert_eq '' "$(<"$LOG")" 'dry-run invoked an external helper'

printf 'Test 5: unknown profile keys are rejected\n'
cat > "$PROFILES/unknown.conf" <<'EOF_PROFILE'
STAPM_W=50
SLOW_W=55
FAST_W=60
TEMP_C=80
TYPO_POWER=1
EOF_PROFILE
assert_fails 'unknown profile key was accepted' run_cli show unknown

printf 'Test 6: profile data is not evaluated as shell code\n'
cat > "$PROFILES/data-only.conf" <<EOF_PROFILE
DESCRIPTION="\$(touch $TMP/should-not-exist)"
STAPM_W=50
SLOW_W=55
FAST_W=60
TEMP_C=80
POWER_PROFILE=unchanged
MIN_FREQ_MHZ=unchanged
MAX_FREQ_MHZ=unchanged
BOOST=unchanged
EPP=unchanged
EOF_PROFILE
run_cli show data-only >/dev/null
[[ ! -e "$TMP/should-not-exist" ]] || { echo 'FAIL: profile content was evaluated' >&2; exit 1; }

printf 'Test 7: active profiles are protected from accidental deletion\n'
assert_fails 'active profile was deleted without --force' run_cli delete dev
run_cli delete data-only >/dev/null
[[ ! -e "$PROFILES/data-only.conf" ]] || { echo 'FAIL: inactive profile was not deleted' >&2; exit 1; }

printf 'Test 8: doctor passes in the fake hardware environment\n'
run_cli doctor >/dev/null || { echo 'FAIL: doctor reported failures in a healthy environment' >&2; exit 1; }

printf 'Test 9: enable runs doctor first and refuses on failures\n'
: > "$LOG"
run_cli enable >/dev/null
assert_file_contains 'systemctl enable legion-powerctl.service' "$LOG" 'enable did not enable the service'
assert_file_contains 'systemctl restart legion-powerctl.service' "$LOG" 'enable did not restart the service'

printf 'ACTIVE_PROFILE=missing\n' > "$ETC/config.conf"
: > "$LOG"
assert_fails 'enable proceeded although doctor reports a missing active profile' run_cli enable
refute_contains 'systemctl enable legion-powerctl.service' "$(<"$LOG")" 'the refused enable run still enabled the service'
run_cli enable --force >/dev/null
assert_file_contains 'systemctl enable legion-powerctl.service' "$LOG" 'enable --force did not bypass the doctor gate'
printf 'ACTIVE_PROFILE=dev\n' > "$ETC/config.conf"

printf 'Test 10: doctor reads SecureBoot state, RyzenAdj version, and conflicting services\n'
doctor_out="$(run_cli doctor || true)"
assert_contains 'RyzenAdj-version' "$doctor_out" 'doctor did not report a RyzenAdj version line'
assert_contains '0.19.0' "$doctor_out" 'doctor did not report the RyzenAdj version'
assert_match "$doctor_out" "*SecureBoot*disabled or not applicable*" 'doctor did not report SecureBoot as disabled'
assert_contains 'tlp.service is active' "$doctor_out" 'doctor did not flag the active tlp.service conflict'

doctor_out="$(RYZENADJ_FAKE_VERSION=0.18.0 run_cli doctor || true)"
assert_contains '0.18.0 is older than 0.19.0' "$doctor_out" 'doctor accepted a ryzenadj older than the required floor'

printf '\x06\x00\x00\x00\x01' > "$EFIVARS/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
doctor_out="$(run_cli doctor || true)"
assert_match "$doctor_out" "*SecureBoot*MOK key enrolled*" 'doctor missed the enabled SecureBoot warning'

printf '\x06\x00\x00\x00\x00' > "$EFIVARS/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
doctor_out="$(run_cli doctor || true)"
assert_match "$doctor_out" "*SecureBoot*disabled or not applicable*" 'doctor treated a zero SecureBoot byte as enabled'
rm -f "$EFIVARS/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"

printf 'Test 11: status --json emits valid schema-1 JSON\n'
run_cli configure esc --stapm 50 --slow 55 --fast 60 --temp 80 \
    --description 'He said "hi" and used a \ backslash' >/dev/null
json_out="$(run_cli status --json)"
assert_eq '1' "$(printf '%s\n' "$json_out" | wc -l)" 'status --json must be a single line'
if command -v python3 >/dev/null 2>&1; then
    python3 -c '
import json, sys
doc = json.loads(sys.argv[1])
assert doc["schema_version"] == 1, doc
assert doc["active_profile"] == "dev", doc
assert doc["service"] == {"enabled": "enabled", "active": "active"}, doc
assert doc["last_apply"]["profile"] == "dev", doc
profiles = {p["name"]: p for p in doc["profiles"]}
assert doc["version"], doc
assert doc["power_profile"] == "balanced", doc
assert doc["cpu_driver"] == "amd-pstate-epp", doc
assert doc["cpu_epp"] == "balance_performance", doc
assert doc["ryzenadj"] and doc["ryzenadj"].endswith("/ryzenadj"), doc
assert profiles["dev"] == {
    "name": "dev", "active": True, "valid": True, "description": "",
    "stapm_w": 55, "slow_w": 60, "fast_w": 70, "temp_c": 80,
    "power_profile": "balanced", "min_freq_mhz": "stock", "max_freq_mhz": "stock",
    "boost": "on", "epp": "balance_performance",
}, profiles["dev"]
assert profiles["unknown"] == {"name": "unknown", "active": False, "valid": False}, profiles
assert profiles["esc"]["description"] == sys.argv[2], profiles
' "$json_out" 'He said "hi" and used a \ backslash'
    assert_contains 'He said "hi" and used a \ backslash' "$(run_cli show esc)" \
        'description did not round-trip through write_profile and load_profile'
else
    assert_contains '"schema_version":1' "$json_out" 'status --json is missing schema_version'
    assert_contains '"active_profile":"dev"' "$json_out" 'status --json is missing active_profile'
fi

printf 'Test 12: status --waybar emits a Waybar custom module object\n'
waybar_out="$(run_cli status --waybar)"
assert_eq '{"text":"dev 55W 80°C","alt":"dev","class":"dev","tooltip":"dev: 55/60/70 W, 80 C cap"}' \
    "$waybar_out" 'unexpected waybar output'
if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json, sys; json.loads(sys.argv[1])' "$waybar_out"
fi

printf 'Test 13: unknown status options are rejected\n'
assert_fails 'status accepted an unknown option' run_cli status --nope

printf 'Test 14: leading zeros are rejected so JSON numbers stay valid\n'
assert_fails 'configure accepted zero-padded values that bash reads as octal' \
    run_cli configure octal --stapm 060 --slow 065 --fast 075 --temp 077
[[ ! -e "$PROFILES/octal.conf" ]] || { echo 'FAIL: octal profile was written' >&2; exit 1; }

printf 'Test 15: status --json survives an invalid hand-edited profile\n'
cat > "$PROFILES/handedited.conf" <<'EOF_PROFILE'
STAPM_W=060
SLOW_W=65
FAST_W=75
TEMP_C=82
EOF_PROFILE
json_out="$(run_cli status --json)"
if command -v python3 >/dev/null 2>&1; then
    python3 -c '
import json, sys
doc = json.loads(sys.argv[1])
bad = {p["name"]: p for p in doc["profiles"]}["handedited"]
assert bad["valid"] is False, bad
' "$json_out"
fi
rm -f "$PROFILES/handedited.conf"

printf 'Test 16: last_apply keys survive a locale where [A-Z] excludes I\n'
if locale -a 2>/dev/null | grep -qi '^tr_TR\.utf8$'; then
    json_out="$(LC_ALL=tr_TR.UTF-8 run_cli status --json)"
    if command -v python3 >/dev/null 2>&1; then
        python3 -c '
import json, sys
doc = json.loads(sys.argv[1])
assert doc["last_apply"]["profile"] == "dev", doc["last_apply"]
assert "applied_at" in doc["last_apply"], doc["last_apply"]
' "$json_out"
    fi
else
    printf '  (tr_TR.utf8 locale unavailable; skipped)\n'
fi

printf 'Test 17: select without --apply exits zero\n'
run_cli select dev >/dev/null || { echo 'FAIL: select exited nonzero on success' >&2; exit 1; }

printf 'Test 18: multi-line descriptions are rejected\n'
assert_fails 'configure accepted a description containing a newline' \
    run_cli configure multiline --description "$(printf 'one\ntwo')"

printf 'Test 19: pre-0.3.0 profiles keep literal backslashes\n'
cat > "$PROFILES/legacy.conf" <<'EOF_PROFILE'
# legion-powerctl profile: legacy
DESCRIPTION="share at \\nas\media"
STAPM_W=50
SLOW_W=55
FAST_W=60
TEMP_C=80
EOF_PROFILE
assert_contains 'share at \\nas\media' "$(run_cli show legacy)" \
    'legacy profile description was unescaped and corrupted'
rm -f "$PROFILES/legacy.conf"

printf 'Test 20a: doctor reads the ryzen_smu sysfs interface and kernel lockdown\n'
doctor_out="$(run_cli doctor || true)"
assert_match "$doctor_out" "*WARN  SMU-backend *no *ryzen_smu_drv*no ryzen_smu module*" \
    'doctor did not fold the missing module into the SMU-backend check'
assert_contains 'install ryzen_smu-dkms-git' "$doctor_out" \
    'the merged SMU-backend warning lost its fix instruction'
assert_match "$doctor_out" "*Kernel-lockdown*not reported by this kernel*" 'doctor did not report kernel lockdown state'

fake_add_smu_interface
doctor_out="$(run_cli doctor || true)"
assert_match "$doctor_out" "*OK*SMU-backend*ryzen_smu_drv*" \
    'doctor did not detect the ryzen_smu sysfs interface'
refute_contains '/dev/ryzen_smu_drv' "$doctor_out" 'doctor still expects a nonexistent SMU device node'

rm -rf "$SMU_SYSFS_DIR"
printf 'none [integrity] confidentiality\n' > "$LOCKDOWN"
doctor_out="$(run_cli doctor || true)"
assert_contains 'integrity - this blocks the' "$doctor_out" 'doctor did not warn that lockdown blocks the /dev/mem fallback'

fake_add_smu_interface
doctor_out="$(run_cli doctor || true)"
assert_match "$doctor_out" "*OK*Kernel-lockdown*integrity;*" \
    'doctor warned about lockdown despite an available SMU sysfs interface'
rm -f "$LOCKDOWN"
rm -rf "$SMU_SYSFS_DIR" "$MODULES/ryzen_smu"

printf 'Test 20: invalid UTF-8 in a description stays out of the JSON document\n'
{
    printf '# legion-powerctl profile: latin1\n# profile-format: 2\n'
    printf 'DESCRIPTION="B\xfcro-Modus"\n'
    printf 'STAPM_W=50\nSLOW_W=55\nFAST_W=60\nTEMP_C=80\n'
} > "$PROFILES/latin1.conf"
json_out="$(run_cli status --json)"
if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$json_out" > "$TMP/latin1.json"
    python3 -c '
import json, sys
raw = open(sys.argv[1], "rb").read()
doc = json.loads(raw.decode("utf-8"))
p = {x["name"]: x for x in doc["profiles"]}["latin1"]
assert p["description"] == "Bro-Modus", repr(p["description"])
' "$TMP/latin1.json"
fi
rm -f "$PROFILES/latin1.conf"

printf 'Test 21: valid UTF-8 descriptions round-trip untouched\n'
run_cli configure utf8 --stapm 50 --slow 55 --fast 60 --temp 80 \
    --description 'café ünïcode 82°C' >/dev/null
json_out="$(run_cli status --json)"
if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$json_out" > "$TMP/utf8.json"
    python3 -c '
import json, sys
doc = json.loads(open(sys.argv[1], "rb").read().decode("utf-8"))
p = {x["name"]: x for x in doc["profiles"]}["utf8"]
assert p["description"] == "café ünïcode 82°C", repr(p["description"])
' "$TMP/utf8.json"
fi

printf 'Test 22: control characters are refused in descriptions\n'
assert_fails 'configure accepted a terminal escape sequence in a description' \
    run_cli configure escseq --description "$(printf 'X\033]0;pwned\aY')"

printf 'Test 23: the wizard frequency validator matches the profile validator\n'
assert_fails 'configure accepted a zero-padded frequency' \
    run_cli configure freq --stapm 50 --slow 55 --fast 60 --temp 80 --min-mhz 0700

printf 'Test 24: DMI detection is case-insensitive and reads the model name\n'
doctor_out="$(run_cli doctor 2>&1 || true)"
assert_contains 'OK    System' "$doctor_out" 'uppercase LENOVO vendor was not recognised as a Legion'
assert_contains 'Legion Pro 7 16ARX10 (83RU)' "$doctor_out" 'doctor did not report the model name and machine-type code'

printf 'Test 24a: a non-Legion Lenovo warns, and DMI placeholders are ignored\n'
printf 'ThinkPad X1\n' > "$DMI/product_family"
printf 'To Be Filled By O.E.M.\n' > "$DMI/product_version"
doctor_out="$(run_cli doctor 2>&1 || true)"
assert_contains 'WARN  System' "$doctor_out" 'a Lenovo that is not a Legion should warn'
assert_contains 'a Lenovo, but not identified as a Legion' "$doctor_out" 'the Lenovo-not-Legion branch did not fire'
refute_contains 'To Be Filled By O.E.M.' "$doctor_out" 'doctor printed a DMI placeholder string as the model name'
printf 'Legion Pro 7 16ARX10\n' > "$DMI/product_family"
printf 'Legion Pro 7 16ARX10\n' > "$DMI/product_version"

printf 'Test 25: doctor reports a CLI-only install and a missing Qt runtime\n'
doctor_out="$(LEGION_POWERCTL_GUI_LAUNCHER="$TMP/nonexistent-gui" run_cli doctor 2>&1 || true)"
assert_contains 'this is a CLI-only install' "$doctor_out" 'doctor did not flag a missing GUI launcher'

printf '#!/bin/sh\n' > "$FAKEBIN/legion-powerctl-gui"
chmod +x "$FAKEBIN/legion-powerctl-gui"
printf '#!/bin/sh\nexit 1\n' > "$FAKEBIN/python-no-qt"
chmod +x "$FAKEBIN/python-no-qt"
doctor_out="$(LEGION_POWERCTL_GUI_LAUNCHER="$FAKEBIN/legion-powerctl-gui" \
    LEGION_POWERCTL_PYTHON_BIN="$FAKEBIN/python-no-qt" run_cli doctor 2>&1 || true)"
assert_contains 'PySide6 is not' "$doctor_out" 'doctor did not flag a missing PySide6'

printf 'Test 26: make dist works without git and never leaves a partial tarball\n'
DISTTEST="$TMP/disttest"
mkdir -p "$DISTTEST"
tar -c -C "$ROOT_DIR" --exclude=./.git --exclude=./dist . | tar -x -C "$DISTTEST"
[[ ! -e "$DISTTEST/.git" ]] || { echo 'FAIL: the dist fixture is still a git checkout' >&2; exit 1; }
make -C "$DISTTEST" dist >/dev/null
version="$(make -C "$ROOT_DIR" -s print-version)"
tarball="$DISTTEST/dist/legion-powerctl-${version}.tar.gz"
[[ -s "$tarball" ]] || { echo "FAIL: make dist produced no tarball at $tarball" >&2; exit 1; }
if compgen -G "$DISTTEST/dist/*.part" >/dev/null; then
    echo 'FAIL: make dist left a .part file behind' >&2
    exit 1
fi
tar -tzf "$tarball" > "$TMP/dist-listing"
assert_file_contains "legion-powerctl-${version}/bin/legion-powerctl" "$TMP/dist-listing" 'the tarball is missing the CLI'
assert_file_contains "legion-powerctl-${version}/gui/legion_powerctl_gui/app.py" "$TMP/dist-listing" 'the tarball is missing the GUI'
assert_file_contains "legion-powerctl-${version}/Makefile" "$TMP/dist-listing" 'the tarball is missing the Makefile'

printf 'Test 27: the RyzenAdj version comes from the usage banner, not the help text\n'
doctor_out="$(RYZENADJ_FAKE_VERSION=0.14.0 run_cli doctor 2>&1 || true)"
assert_contains '0.14.0 is older than 0.19.0' "$doctor_out" 'the minimum-version gate did not fire'
refute_contains '1.55' "$doctor_out" 'doctor parsed 1.55 out of the --oc-volt help text as the version'

printf 'Test 28: a shadowed ryzenadj on PATH is reported\n'
mkdir -p "$TMP/pathB"
sed 's/0\.19\.0/0.18.0/' "$FAKEBIN/ryzenadj" > "$TMP/pathB/ryzenadj"
chmod +x "$TMP/pathB/ryzenadj"
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$FAKEBIN:$TMP/pathB:$PATH" run_cli doctor 2>&1 || true)"
assert_contains 'RyzenAdj-shadow' "$doctor_out" 'doctor did not report a second ryzenadj on PATH'
assert_contains "$TMP/pathB/ryzenadj" "$doctor_out" 'doctor did not name the shadowed binary'
assert_contains 'OK    RyzenAdj-shadow' "$doctor_out" \
    'a shadow the tool already resolved correctly is not a warning'
refute_contains 'WARN  RyzenAdj-shadow' "$doctor_out" 'the shadow warning came back'
assert_contains '(newest)' "$doctor_out" 'the shadow line no longer says which binary was chosen'
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$FAKEBIN:$PATH" run_cli doctor 2>&1 || true)"
refute_contains 'RyzenAdj-shadow' "$doctor_out" 'doctor reported a shadow with only one ryzenadj on PATH'
doctor_out="$(PATH="$FAKEBIN:$TMP/pathB:$PATH" run_cli doctor 2>&1 || true)"
refute_contains 'RyzenAdj-shadow' "$doctor_out" 'an explicit LEGION_POWERCTL_RYZENADJ_BIN override still reported shadows'

printf 'Test 28a: usr-merge PATH aliases are not counted as separate binaries\n'
mkdir -p "$TMP/merged/usr/bin"
cp "$FAKEBIN/ryzenadj" "$TMP/merged/usr/bin/ryzenadj"
ln -s usr/bin "$TMP/merged/bin"
ln -s usr/bin "$TMP/merged/sbin"
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$TMP/merged/bin:$TMP/merged/sbin:$TMP/merged/usr/bin:$PATH" run_cli doctor 2>&1 || true)"
refute_contains 'RyzenAdj-shadow' "$doctor_out" 'symlinked PATH aliases of one binary were reported as a shadow'

printf 'Test 28b: the newest ryzenadj wins over PATH order\n'
mkdir -p "$TMP/stale" "$TMP/fresh"
sed 's/0\.19\.0/0.14.0/' "$FAKEBIN/ryzenadj" > "$TMP/stale/ryzenadj"
cp "$FAKEBIN/ryzenadj" "$TMP/fresh/ryzenadj"
chmod +x "$TMP/stale/ryzenadj" "$TMP/fresh/ryzenadj"
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$TMP/stale:$TMP/fresh:$PATH" run_cli doctor 2>&1 || true)"
assert_contains "$TMP/fresh/ryzenadj" "$doctor_out" 'the older ryzenadj first on PATH was selected'
refute_contains '0.14.0 is older than' "$doctor_out" 'doctor reported the stale version, so the stale binary was selected'
assert_contains "Stale: $TMP/stale/ryzenadj 0.14.0" "$doctor_out" \
    'the shadow line did not name the losing binary and its version'

printf 'Test 28c: a candidate whose version cannot be read keeps the shadow warning\n'
mkdir -p "$TMP/noversion"
printf '#!/bin/sh\nprintf "Usage: ryzenadj\\n"\n' > "$TMP/noversion/ryzenadj"
chmod +x "$TMP/noversion/ryzenadj"
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$FAKEBIN:$TMP/noversion:$PATH" run_cli doctor 2>&1 || true)"
assert_contains 'WARN  RyzenAdj-shadow' "$doctor_out" \
    'an unreadable version was reported as a proven-newest selection'
assert_contains 'no version from' "$doctor_out" \
    'the warning did not say why the newest could not be confirmed'
assert_contains "$TMP/noversion/ryzenadj" "$doctor_out" \
    'doctor did not name the candidate it could not read'

mkdir -p "$TMP/noversion2"
cp "$TMP/noversion/ryzenadj" "$TMP/noversion2/ryzenadj"
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$TMP/noversion:$TMP/noversion2:$PATH" run_cli doctor 2>&1 || true)"
assert_contains "using $TMP/noversion/ryzenadj, but no version from" "$doctor_out" \
    'with no version anywhere the shadow line left a gap where the version would go'

printf 'Test 28d: two ryzenadj at the same version are not ranked against each other\n'
mkdir -p "$TMP/tieA" "$TMP/tieB"
cp "$FAKEBIN/ryzenadj" "$TMP/tieA/ryzenadj"
cp "$FAKEBIN/ryzenadj" "$TMP/tieB/ryzenadj"
chmod +x "$TMP/tieA/ryzenadj" "$TMP/tieB/ryzenadj"
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$TMP/tieA:$TMP/tieB:$PATH" run_cli doctor 2>&1 || true)"
assert_contains "Same version: $TMP/tieB/ryzenadj" "$doctor_out" \
    'an equal-version binary was not reported as a tie'
refute_contains '(newest)' "$doctor_out" \
    'a tie broken by PATH order was reported as the newest binary'
refute_contains 'safe to delete' "$doctor_out" \
    'doctor advised deleting a binary that is not older, which on a default PATH is the packaged one'

printf 'Test 29: doctor completes the report and exits nonzero on a corrupt active profile\n'
cp "$ETC/config.conf" "$TMP/config.conf.saved"
cat > "$PROFILES/corrupt.conf" <<'EOF_PROFILE'
STAPM_W=banana
SLOW_W=55
FAST_W=60
TEMP_C=80
EOF_PROFILE
printf 'ACTIVE_PROFILE=corrupt\n' > "$ETC/config.conf"
rc=0
doctor_out="$(run_cli doctor 2>&1)" || rc=$?
assert_eq '1' "$rc" 'doctor did not exit 1 although the active profile is corrupt'
assert_contains 'FAIL  Profile' "$doctor_out" 'doctor did not report the corrupt profile as FAIL'
assert_contains 'systemd' "$doctor_out" 'doctor stopped before the systemd check'
assert_contains 'Doctor result: 1 failure(s)' "$doctor_out" 'doctor did not finish the report with its summary line'
printf 'STAPM_W=50\nTYPO=1\n' > "$PROFILES/corrupt.conf"
rc=0
doctor_out="$(run_cli doctor 2>&1)" || rc=$?
assert_eq '1' "$rc" 'doctor did not exit 1 on an unparseable profile'
assert_contains 'Doctor result: 1 failure(s)' "$doctor_out" 'doctor aborted mid-report on an unparseable profile'
rm -f "$PROFILES/corrupt.conf"
mv "$TMP/config.conf.saved" "$ETC/config.conf"

printf 'Test 30: the doctor PySide6 probe does not run a module from the caller cwd\n'
INJECT="$TMP/inject"
mkdir -p "$INJECT"
cat > "$INJECT/PySide6.py" <<'EOF_INJECT'
import os, pathlib
pathlib.Path(os.environ["LEGION_TEST_INJECT_MARKER"]).write_text("executed")
EOF_INJECT
rm -f "$TMP/inject-marker"
(
    cd "$INJECT"
    LEGION_TEST_INJECT_MARKER="$TMP/inject-marker" \
    LEGION_POWERCTL_GUI_LAUNCHER="$FAKEBIN/legion-powerctl-gui" \
        run_cli doctor >/dev/null 2>&1 || true
)
if [[ -e "$TMP/inject-marker" ]]; then
    printf 'FAIL: doctor executed a PySide6.py planted in the working directory\n' >&2
    exit 1
fi

printf 'Test 31: a dry run never claims the profile was applied\n'
run_cli configure dryrun --stapm 50 --slow 55 --fast 60 --temp 80 >/dev/null
dry_out="$(run_cli apply dryrun --dry-run 2>&1)"
refute_contains 'applied successfully' "$dry_out" '--dry-run reported the profile as applied'
assert_contains 'was not applied' "$dry_out" 'dry run did not say it changed nothing'

printf 'Test 32: the completions extract profile names, not profile paths\n'
while read -r extracted; do
    [[ -n "$extracted" ]] || continue
    if [[ "$extracted" == /* ]]; then
        printf 'FAIL: the completion extractor yielded a path, not a name: %s\n' "$extracted" >&2
        exit 1
    fi
done < <(run_cli list | awk '{print $(NF-1)}')
for completion in "$ROOT_DIR/completions/legion-powerctl.bash" "$ROOT_DIR/completions/legion-powerctl.fish"; do
    assert_file_contains 'NF-1' "$completion" "$completion still uses a field index that breaks on inactive profiles"
done

printf 'Test 33: the bash completion offers flags for every subcommand that takes them\n'
# shellcheck source=/dev/null
source "$ROOT_DIR/completions/legion-powerctl.bash"
assert_completion() {
    local expected="$1" message="$2"
    shift 2
    COMP_WORDS=("$@") COMP_CWORD=$(( $# - 1 ))
    COMPREPLY=()
    _legion_powerctl_complete
    if [[ " ${COMPREPLY[*]} " != *" $expected "* ]]; then
        printf 'FAIL: %s\nWanted: %s\nGot:    %s\n' "$message" "$expected" "${COMPREPLY[*]-}" >&2
        exit 1
    fi
}
assert_completion '--dry-run' 'apply offers no --dry-run' legion-powerctl apply --
assert_completion '--boot' 'apply offers no --boot' legion-powerctl apply --
assert_completion '--apply' 'select offers no --apply' legion-powerctl select --
assert_completion '--force' 'delete offers no --force' legion-powerctl delete --
assert_completion 'balanced' 'the --power-profile enum is not offered' legion-powerctl configure dev --power-profile ''
assert_completion 'unchanged' 'the --boost enum is not offered' legion-powerctl apply --boost ''

printf 'Test 34: -h works for the subcommands that consume argv[1] as a profile name\n'
for subcommand in show list select delete configure wizard status doctor enable disable; do
    assert_contains 'Usage:' "$(run_cli "$subcommand" --help 2>&1 || true)" \
        "$subcommand --help did not print usage"
done

printf 'Test 35: a completed apply records its result in the runtime state file\n'
run_cli apply dryrun >/dev/null
assert_file_contains 'RESULT=ok' "$STATE/last-apply.env" 'apply did not record a successful result'

printf 'Test 36: version reports the same string the packaging gates read\n'
version="$(make -C "$ROOT_DIR" -s print-version)"
[[ -n "$version" ]] || { echo 'FAIL: make print-version printed nothing' >&2; exit 1; }
assert_eq "legion-powerctl $version" "$(run_cli version)" 'version printed something else'
assert_eq "legion-powerctl $version" "$(run_cli --version)" '--version disagrees with the version subcommand'

printf 'Test 37: list marks the active profile and keeps the name in its own column\n'
list_out="$(run_cli list)"
assert_contains 'dev' "$list_out" 'list did not print the profiles at all'
while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    read -r name path <<<"$(awk '{print $(NF-1), $NF}' <<<"$line")"
    assert_eq "$PROFILES/$name.conf" "$path" "list row '$line' pairs a name with someone else's path"
    if [[ "$name" == "dev" ]]; then
        assert_eq '*' "${line:0:1}" 'the active profile row does not start with the marker'
    else
        assert_eq ' ' "${line:0:1}" "the inactive row for $name carries an active marker"
    fi
done <<<"$list_out"

printf 'Test 38: disable stops and disables the unit in one call\n'
: > "$LOG"
run_cli disable >/dev/null
assert_file_contains 'systemctl disable --now legion-powerctl.service' "$LOG" \
    'disable did not stop the unit as well as disabling it'

printf 'Test 39: restore-frequency returns the stock range and honours --boost\n'
printf '2200000\n' > "$SYSFS/cpufreq/policy0/scaling_min_freq"
printf '3200000\n' > "$SYSFS/cpufreq/policy0/scaling_max_freq"
printf '1\n' > "$SYSFS/cpufreq/boost"
printf '1\n' > "$SYSFS/cpufreq/policy0/boost"
run_cli restore-frequency --boost off >/dev/null
assert_eq '1200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" 'restore-frequency did not restore the stock minimum'
assert_eq '5460000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" 'restore-frequency did not restore the stock maximum'
assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'restore-frequency ignored --boost off'
assert_eq '1' "$(<"$SYSFS/cpufreq/policy0/boost")" \
    'restore-frequency wrote the per-policy file despite the global control'
assert_fails 'restore-frequency accepted an invalid --boost value' \
    run_cli restore-frequency --boost maybe
assert_fails 'restore-frequency accepted an unknown option' \
    run_cli restore-frequency --nope

printf 'Test 40: the wizard writes only what it was answered\n'
cat > "$TMP/wizard-run.sh" <<EOF_WIZARD
#!/usr/bin/env bash
exec env $(printf '%q ' "${FAKE_ENV[@]}") \\
    LEGION_POWERCTL_RYZENADJ_BIN=$(printf '%q' "$FAKEBIN/ryzenadj") \\
    $(printf '%q' "$CLI") wizard wiz
EOF_WIZARD
chmod +x "$TMP/wizard-run.sh"
printf '52\n58\n64\n79\n\n\n\n\n\nn\nn\n' | timeout 30 script -qec "$TMP/wizard-run.sh" /dev/null >/dev/null
assert_file_contains 'STAPM_W=52' "$PROFILES/wiz.conf" 'the wizard did not write the answered STAPM value'
assert_file_contains 'TEMP_C=79' "$PROFILES/wiz.conf" 'the wizard did not write the answered temperature'
assert_file_contains 'ACTIVE_PROFILE=dev' "$ETC/config.conf" 'the wizard selected a profile after being answered no'

printf 'Test 41: the wizard refuses a non-interactive stdin instead of taking defaults\n'
rm -f "$PROFILES/scripted.conf"
assert_fails 'the wizard ran without a terminal' run_cli wizard scripted </dev/null
[[ ! -e "$PROFILES/scripted.conf" ]] || {
    echo 'FAIL: the refused wizard run still wrote a profile' >&2
    exit 1
}

printf 'Test 42: install is the union of install-files and install-config\n'
stage_manifest() {
    local target="$1" dir="$TMP/stage-$1"
    rm -rf "$dir"
    make -C "$ROOT_DIR" "$target" DESTDIR="$dir" PREFIX=/usr SYSCONFDIR=/etc >/dev/null
    (cd "$dir" && find . \( -type f -o -type l \) -print | sort)
}
manifest_all="$(stage_manifest install)"
manifest_files="$(stage_manifest install-files)"
manifest_config="$(stage_manifest install-config)"
assert_eq "$manifest_all" "$(printf '%s\n%s\n' "$manifest_files" "$manifest_config" | sort)" \
    'make install is no longer exactly install-files plus install-config'
assert_contains './usr/bin/legion-powerctl' "$manifest_files" 'install-files did not install the CLI'
assert_contains './usr/share/legion-powerctl/gui/legion_powerctl_gui/app.py' "$manifest_files" \
    'install-files did not install the GUI package'
assert_contains './usr/share/polkit-1/actions/io.github.alexmacra.legion-powerctl.policy' \
    "$manifest_files" 'install-files did not install the polkit policy'
assert_contains './etc/legion-powerctl/profiles.d/balanced-plus.conf' "$manifest_config" \
    'install-config did not install the shipped profiles'
refute_contains './etc/' "$manifest_files" 'install-files wrote into the configuration directory'
refute_contains '.png' "$manifest_all" 'the design screenshots are being shipped into DOCDIR again'

printf 'Test 43: uninstall removes everything install-files put down\n'
make -C "$ROOT_DIR" uninstall-files DESTDIR="$TMP/stage-install" PREFIX=/usr >/dev/null
leftovers="$(cd "$TMP/stage-install" && find usr \( -type f -o -type l \) -print | sort)"
assert_eq '' "$leftovers" 'make uninstall-files left files behind under PREFIX'
assert_file_contains 'STAPM_W' "$TMP/stage-install/etc/legion-powerctl/profiles.d/balanced-plus.conf" \
    'uninstall-files removed the configuration it is supposed to preserve'

printf 'Test 44: the enum values are declared once and the other copies still agree\n'
cli_enum() { sed -n "s/^readonly -a $1=(\(.*\))\$/\1/p" "$CLI"; }
usage_text="$(run_cli help)"
bash_completion="$(<"$ROOT_DIR/completions/legion-powerctl.bash")"
fish_completion="$(<"$ROOT_DIR/completions/legion-powerctl.fish")"
for enum in POWER_PROFILE_VALUES BOOST_VALUES EPP_VALUES; do
    enum_values="$(cli_enum "$enum")"
    [[ -n "$enum_values" ]] || {
        printf 'FAIL: could not read %s out of the CLI\n' "$enum" >&2
        exit 1
    }
    assert_contains "$enum_values" "$bash_completion" "the bash completion does not offer $enum verbatim"
    assert_contains "$enum_values" "$fish_completion" "the fish completion does not offer $enum verbatim"
    # shellcheck disable=SC2086
    for enum_value in $enum_values; do
        assert_contains "$enum_value" "$usage_text" "the usage text no longer mentions '$enum_value' from $enum"
    done
done

printf 'Test 45: one key table drives both the profile file and the runtime record\n'
mapfile -t declared_keys < <(
    sed -n '/^readonly -a PROFILE_KEYS=($/,/^)$/p' "$CLI" | sed -e '1d' -e '$d' | tr ' ' '\n' | grep -v '^$'
)
declared_keys_text="$(printf '%s\n' "${declared_keys[@]}")"
assert_contains 'STAPM_W' "$declared_keys_text" 'PROFILE_KEYS could not be read out of the CLI'

run_cli configure keytable --stapm 50 --slow 55 --fast 60 --temp 80 >/dev/null
written_keys="$(grep -o '^[A-Z_]*=' "$PROFILES/keytable.conf" | tr -d '=' | grep -v '^DESCRIPTION$')"
assert_eq "$declared_keys_text" "$written_keys" \
    'a written profile no longer carries exactly PROFILE_KEYS, in order'

run_cli apply keytable >/dev/null
state_keys="$(grep -o '^[A-Z_]*=' "$STATE/last-apply.env" | tr -d '=' | grep -vE '^(PROFILE|RESULT|VERIFIED|BOOST_APPLIED|APPLIED_AT)$')"
assert_eq "$declared_keys_text" "$state_keys" \
    'last-apply.env no longer carries exactly PROFILE_KEYS, in order'

printf 'Test 46: EOF in the wizard cancels instead of accepting every remaining default\n'
rm -f "$PROFILES/eof.conf"
cat > "$TMP/wizard-eof.sh" <<EOF_WIZARD
#!/usr/bin/env bash
exec env $(printf '%q ' "${FAKE_ENV[@]}") \\
    LEGION_POWERCTL_RYZENADJ_BIN=$(printf '%q' "$FAKEBIN/ryzenadj") \\
    $(printf '%q' "$CLI") wizard eof
EOF_WIZARD
chmod +x "$TMP/wizard-eof.sh"
wizard_eof_out="$(printf '52\n' | timeout 30 script -qec "$TMP/wizard-eof.sh" /dev/null 2>&1 || true)"
assert_contains 'Cancelled.' "$wizard_eof_out" 'the wizard did not report that it was cancelled'
[[ ! -e "$PROFILES/eof.conf" ]] || {
    printf 'FAIL: the wizard wrote a profile after EOF should have cancelled it\nOutput:\n%s\n' \
        "$wizard_eof_out" >&2
    exit 1
}

printf 'Test 47: a failed write removes its temporary file instead of leaking it\n'
leak_tmpdir="$TMP/leak-tmpdir"
mkdir -p "$leak_tmpdir"
leak_out="$(env "${FAKE_ENV[@]}" \
    LEGION_POWERCTL_RYZENADJ_BIN="$FAKEBIN/ryzenadj" \
    LEGION_POWERCTL_CONFIG_FILE=/proc/self/no-such-directory/config.conf \
    TMPDIR="$leak_tmpdir" \
    "$CLI" select dev 2>&1 || true)"
assert_contains 'config.conf' "$leak_out" 'select did not report the file it could not write'
refute_contains 'unbound variable' "$leak_out" \
    'select reported a broken cleanup trap instead of the write error'
assert_eq '' "$(find "$leak_tmpdir" -type f)" 'select left its temporary file behind'

printf 'Test 48: no em or en dashes anywhere in the tree\n'
dash_hits="$(cd "$ROOT_DIR" && git ls-files -z | xargs -0 grep -lP '[\x{2013}\x{2014}]' 2>/dev/null)" || true
assert_eq '' "$dash_hits" 'these tracked files contain an em or en dash'

printf 'Test 49: baseline reports honestly when nothing has been captured\n'
rm -rf "$LIB"
baseline_out="$(run_cli baseline 2>&1 || true)"
assert_contains 'No stock limits recorded' "$baseline_out" 'baseline did not say the capture is missing'
assert_exit 1 'baseline --show succeeded with nothing captured' run_cli baseline --show

printf 'Test 50: baseline captures the firmware limits once and never overwrites them\n'
rm -rf "$LIB"
rm -f "$RYZENADJ_STATE" "$STATE/last-apply.env"
run_cli baseline --capture >/dev/null
assert_file_contains 'STAPM_W=65.000' "$LIB/stock-limits.env" 'the firmware STAPM was not captured'
assert_file_contains 'TEMP_C=78.000' "$LIB/stock-limits.env" 'the firmware Tctl ceiling was not captured'
first_capture="$(<"$LIB/stock-limits.env")"
run_cli apply dev >/dev/null
run_cli baseline --capture >/dev/null
assert_eq "$first_capture" "$(<"$LIB/stock-limits.env")" 'a second capture overwrote the first'

printf 'Test 51: an apply captures the firmware limits before it overwrites them\n'
rm -rf "$LIB"
rm -f "$RYZENADJ_STATE" "$STATE/last-apply.env"
run_cli apply dev >/dev/null
assert_file_contains 'STAPM_W=65.000' "$LIB/stock-limits.env" \
    'apply recorded its own limits instead of the firmware ones'
refute_contains 'STAPM_W=55' "$(<"$LIB/stock-limits.env")" \
    'the baseline was captured after the apply, not before'

printf 'Test 52: a capture is refused once this boot has already applied a profile\n'
rm -rf "$LIB"
tainted_out="$(run_cli baseline --capture 2>&1 || true)"
assert_contains 'already applied this boot' "$tainted_out" \
    'baseline captured SMU values that a previous apply had already overwritten'
[[ ! -e "$LIB/stock-limits.env" ]] || {
    printf 'FAIL: a tainted capture was written anyway\n' >&2
    exit 1
}

printf 'All tests passed.\n'
