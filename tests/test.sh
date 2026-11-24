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
assert_contains 'integrity blocks the' "$doctor_out" 'doctor did not warn that lockdown blocks the /dev/mem fallback'
assert_contains 'loaded ryzen_smu backend is not verified' "$doctor_out" \
    'doctor gave module-install advice despite a loaded ryzen_smu module'

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
assert_contains 'WARN  RyzenAdj-shadow' "$doctor_out" \
    'an older ryzenadj beside the selected one was reported as OK'
assert_contains "Stale: $TMP/pathB/ryzenadj 0.18.0" "$doctor_out" \
    'the shadow line did not name the older binary and its version'
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

printf 'Test 28e: with an unreadable candidate too, the stale one is still named\n'
doctor_out="$(LEGION_TEST_RYZENADJ_BIN='' PATH="$TMP/fresh:$TMP/stale:$TMP/noversion:$PATH" run_cli doctor 2>&1 || true)"
assert_contains 'WARN  RyzenAdj-shadow' "$doctor_out" 'three candidates with one unreadable were not a warning'
assert_contains "Stale: $TMP/stale/ryzenadj 0.14.0" "$doctor_out" \
    'an unreadable candidate hid the stale binary from the shadow line'
assert_contains "no version from $TMP/noversion/ryzenadj" "$doctor_out" \
    'the shadow line did not name the candidate without a version'

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
rm -f "$RYZENADJ_STATE" "$STATE/last-apply.env" "$STATE/smu-written"
run_cli baseline --capture >/dev/null
assert_file_contains 'STAPM_W=70.000' "$LIB/stock-limits.env" 'the firmware STAPM was not captured'
assert_file_contains 'TEMP_C=72.000' "$LIB/stock-limits.env" 'the firmware Tctl ceiling was not captured'
first_capture="$(<"$LIB/stock-limits.env")"
run_cli apply dev >/dev/null
run_cli baseline --capture >/dev/null
assert_eq "$first_capture" "$(<"$LIB/stock-limits.env")" 'a second capture overwrote the first'

printf 'Test 51: an apply captures the firmware limits before it overwrites them\n'
rm -rf "$LIB"
rm -f "$RYZENADJ_STATE" "$STATE/last-apply.env" "$STATE/smu-written"
run_cli apply dev >/dev/null
assert_file_contains 'STAPM_W=70.000' "$LIB/stock-limits.env" \
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

printf 'Test 53: every fresh-install path boots balanced; an existing pointer is kept\n'
fresh_boot_profile() {
    rm -f "$STATE/last-apply.env"
    : > "$LOG"
    run_cli apply --boot 2>&1 | sed -n "s/^Boot apply: profile '\(.*\)'$/\1/p"
}
cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
rm -f "$ETC/config.conf"
assert_eq 'balanced' "$(fresh_boot_profile)" 'with no config.conf the CLI does not fall back to balanced'

pacman_scriptlet="$TMP/legion-powerctl.install"
pacman_varlib="$TMP/pacstrap-var-lib"
mkdir -p "$TMP/pacstrap-run"
chmod 0555 "$TMP/pacstrap-run"
sed -e "s|/etc/legion-powerctl|$ETC|g" -e "s|/var/lib/legion-powerctl|$pacman_varlib|g" \
    -e "s|/run/|$TMP/pacstrap-run/|g" \
    -e "s|legion-powerctl select|$FAKEBIN/legion-powerctl select|g" \
    -e "s|legion-powerctl show|$FAKEBIN/legion-powerctl show|g" \
    "$ROOT_DIR/packaging/arch/legion-powerctl.install" > "$pacman_scriptlet"
# shellcheck disable=SC2329
pacman_install() {
    local extracted="$1"
    (
        # shellcheck source=/dev/null
        . "$pacman_scriptlet"
        pre_install
        if [[ -e "$ETC/config.conf" ]]; then
            [[ "$extracted" == unchanged ]] || cp "$ROOT_DIR/config/config.conf" "$ETC/config.conf.pacnew"
        else
            cp "$ROOT_DIR/config/config.conf" "$ETC/config.conf"
        fi
        post_install
    )
}
rm -f "$ETC/config.conf"
: > "$LOG"
post_install_out="$(pacman_install new)"
assert_contains 'The boot profile is balanced' "$post_install_out" 'post_install did not report the boot profile'
assert_eq '' "$(<"$LOG")" 'post_install applied something'
assert_file_contains 'ACTIVE_PROFILE=balanced' "$ETC/config.conf" 'post_install did not select balanced'
assert_eq 'balanced' "$(fresh_boot_profile)" 'a fresh package install does not boot balanced'
printf 'ACTIVE_PROFILE=quiet\n' > "$ETC/config.conf"
pacman_install new >/dev/null
assert_eq 'ACTIVE_PROFILE=quiet' "$(<"$ETC/config.conf")" 'post_install replaced a config.conf pacman kept'
cp "$ROOT_DIR/config/config.conf" "$ETC/config.conf"
pacman_install unchanged >/dev/null
assert_file_contains 'ACTIVE_PROFILE=balanced-plus' "$ETC/config.conf" 'post_install moved a config.conf that existed before the install'
rm -f "$ETC/config.conf"
pacman_install new >/dev/null
assert_file_contains 'ACTIVE_PROFILE=balanced' "$ETC/config.conf" 'a stale config.conf.pacnew stopped a fresh install from selecting balanced'
refute_contains 'balanced-plus' "$(<"$ETC/config.conf")" 'a stale config.conf.pacnew stopped a fresh install from selecting balanced'
[[ ! -e "$pacman_varlib/fresh-config" ]] || {
    printf 'FAIL: post_install left its fresh-install marker behind\n' >&2
    exit 1
}
rm -f "$ETC/config.conf.pacnew"

installer_functions="$TMP/installer-functions.sh"
awk '/^(install_preserving|install_config_files)\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" > "$installer_functions"
assert_contains 'install_config_files()' "$(<"$installer_functions")" 'install.sh no longer has install_config_files'
# shellcheck disable=SC2034,SC2329
run_script_install_config() {
    (
        SUDO=()
        FORCE_CONFIG="${1:-0}"
        CONFIG_DIR="$ETC"
        CLI_BIN="$FAKEBIN/legion-powerctl"
        info() { printf '%s\n' "$*"; }
        warn() { printf 'WARNING: %s\n' "$*" >&2; }
        # shellcheck source=/dev/null
        . "$installer_functions"
        install_config_files
    )
}
mv "$ETC" "$TMP/etc-before-script-install"
run_script_install_config >/dev/null
assert_file_contains 'ACTIVE_PROFILE=balanced' "$ETC/config.conf" 'a fresh script install did not select balanced'
assert_eq 'balanced' "$(fresh_boot_profile)" 'a fresh script install does not boot balanced'
printf 'ACTIVE_PROFILE=quiet\n' > "$ETC/config.conf"
run_script_install_config >/dev/null
assert_eq 'ACTIVE_PROFILE=quiet' "$(<"$ETC/config.conf")" 'a script reinstall moved the boot profile'
run_script_install_config 1 >/dev/null
assert_eq 'balanced' "$(fresh_boot_profile)" 'install.sh --force-config did not reset boot to balanced like a fresh install'
rm -rf "$ETC"
mv "$TMP/etc-before-script-install" "$ETC"
cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"

printf 'Test 54: the profile the GUI applies is the one the next boot applies\n'
run_cli select balanced-plus >/dev/null
for gui_argv in "select quiet --apply" "select balanced --apply"; do
    expected="$(cut -d' ' -f2 <<<"$gui_argv")"
    read -r -a argv <<<"$gui_argv"
    run_cli "${argv[@]}" >/dev/null
    assert_file_contains "ACTIVE_PROFILE=$expected" "$ETC/config.conf" "'$gui_argv' did not persist the boot profile"
    rm -f "$STATE/last-apply.env"
    boot_out="$(run_cli apply --boot 2>&1)"
    assert_contains "Boot apply: profile '$expected'" "$boot_out" "the next boot did not apply '$expected'"
    assert_eq "PROFILE=$expected" "$(grep '^PROFILE=' "$STATE/last-apply.env")" "the next boot recorded the wrong profile"
done

printf 'Test 55: the shipped config.conf still points at balanced-plus, so a pacman upgrade never flips boot\n'
assert_eq "$(printf '# Profile applied by legion-powerctl.service once at boot.\nACTIVE_PROFILE=balanced-plus\nx')" \
    "$(cat "$ROOT_DIR/config/config.conf"; printf x)" \
    'config/config.conf changed; pacman installs an unedited backup file silently and flips boot'

printf 'Test 56: every file make install puts under /etc is in the PKGBUILD backup array\n'
stage="$TMP/stage"
make -s -C "$ROOT_DIR" install DESTDIR="$stage" PREFIX=/usr SYSCONFDIR=/etc >/dev/null
staged="$(cd "$stage" && find etc -type f | LC_ALL=C sort)"
backed_up="$(
    # shellcheck source=/dev/null
    . "$ROOT_DIR/packaging/arch/PKGBUILD"
    # shellcheck disable=SC2154
    printf '%s\n' "${backup[@]}" | LC_ALL=C sort
)"
assert_eq "$staged" "$backed_up" 'PKGBUILD backup= does not match the files installed under /etc'

printf 'Test 57: moving to the package flow removes the script install only once every precondition passed\n'
pkg_root="$TMP/pkg-root"
mkdir -p "$pkg_root/packaging/arch"
: > "$pkg_root/packaging/arch/PKGBUILD"
: > "$pkg_root/packaging/arch/legion-powerctl.install"
printf '#!/usr/bin/env bash\nprintf "uninstall.sh\\n" >> %q\n[[ ! -e %q ]] || exit 1\nrm -f %q\n' \
    "$TMP/pkg-flow.log" "$TMP/uninstall-fails" "$TMP/modules-load.conf" > "$pkg_root/uninstall.sh"
chmod +x "$pkg_root/uninstall.sh"
: > "$TMP/script-installed-cli"
package_functions="$TMP/package-install.sh"
awk '/^package_install\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" > "$package_functions"
assert_contains 'package_install()' "$(<"$package_functions")" 'install.sh no longer has package_install'
# shellcheck disable=SC2034,SC2329
run_package_install() {
    local failing="$1"
    : > "$TMP/pkg-flow.log"
    (
        CLI_BIN="$TMP/script-installed-cli"
        REPLACE_SCRIPT_INSTALL=1
        FORCE_CONFIG=0
        info() { :; }
        warn() { :; }
        die() { printf 'died: %s\n' "$*" >> "$TMP/pkg-flow.log"; exit 1; }
        SUDO=()
        MODULES_LOAD_CONF="$TMP/modules-load.conf"
        confirm() { return 1; }
        persist_ryzen_smu() { printf 'persist_ryzen_smu\n' >> "$TMP/pkg-flow.log"; }
        SMU_BLACKLIST_FILE="$TMP/smu-blacklist.conf"
        ryzen_smu_usable() { [[ "${SMU_USABLE:-1}" == 1 ]]; }
        pacman() {
            [[ "$1" == -U ]] || return 1
            printf 'pacman %s %s %s\n' "$1" "$2" "${3##*/}" >> "$TMP/pkg-flow.log"
            [[ "$failing" != pacman ]]
        }
        make() { [[ " $* " != *' print-version '* ]] || printf '0.0.0\n'; }
        makepkg() {
            if [[ "$1" == --packagelist ]]; then
                printf '%s/legion-powerctl-debug-0.0.0-1-x86_64.pkg.tar.zst\n' "$BUILD_DIR"
                printf '%s/legion-powerctl-0.0.0-1-any.pkg.tar.zst\n' "$BUILD_DIR"
                return 0
            fi
            printf 'makepkg %s\n' "$*" >> "$TMP/pkg-flow.log"
            [[ "$failing" != makepkg ]] || return 1
            : > "$BUILD_DIR/legion-powerctl-0.0.0-1-any.pkg.tar.zst"
        }
        step() { [[ "$1" != "$failing" ]] || die "$1 failed"; }
        check_pacman_lock() { step check_pacman_lock; }
        ensure_ryzenadj_package() { step ensure_ryzenadj_package; }
        ensure_ryzen_smu() { step ensure_ryzen_smu; }
        migrate_legacy() { step migrate_legacy; }
        ensure_gui_runtime() { :; }
        enable_service() { :; }
        # shellcheck source=/dev/null
        . "$package_functions"
        ROOT_DIR="$pkg_root" package_install
    ) >/dev/null 2>&1 || true
}
for failing in check_pacman_lock ensure_ryzenadj_package migrate_legacy makepkg; do
    run_package_install "$failing"
    refute_contains 'uninstall.sh' "$(<"$TMP/pkg-flow.log")" \
        "a failing $failing still removed the script install first"
done
run_package_install none
assert_eq "$(printf 'makepkg -sf\nuninstall.sh\npacman -U --noconfirm legion-powerctl-0.0.0-1-any.pkg.tar.zst')" "$(<"$TMP/pkg-flow.log")" \
    'the script install was not removed between a finished (re)build and the pacman install'
: > "$TMP/modules-load.conf"
run_package_install pacman
assert_match "$(<"$TMP/pkg-flow.log")" "*$(printf 'uninstall.sh\npersist_ryzen_smu\npacman -U')*" \
    'moving to the package dropped the ryzen_smu boot entry the script install had written'
pkg_failure="$(<"$TMP/pkg-flow.log")"
: > "$TMP/modules-load.conf"
SMU_USABLE=0 run_package_install none
refute_contains 'persist_ryzen_smu' "$(<"$TMP/pkg-flow.log")" \
    'moving to the package rewrote a ryzen_smu boot entry for a module that does not work'
: > "$TMP/smu-blacklist.conf"
: > "$TMP/modules-load.conf"
run_package_install none
refute_contains 'persist_ryzen_smu' "$(<"$TMP/pkg-flow.log")" \
    'moving to the package rewrote a ryzen_smu boot entry while SMU recovery blacklists the module'
rm -f "$TMP/smu-blacklist.conf"
for recovery_step in 'sudo pacman -U ' 'legion-powerctl-0.0.0-1-any.pkg.tar.zst' 'then: sudo legion-powerctl enable'; do
    assert_contains "$recovery_step" "$pkg_failure" 'a failed pacman install after the script removal gave an incomplete recovery'
done
: > "$TMP/uninstall-fails"
run_package_install none
rm -f "$TMP/uninstall-fails"
uninstall_failure="$(<"$TMP/pkg-flow.log")"
assert_contains 'died: Removing the script install failed.' "$uninstall_failure" \
    'a failed script removal did not stop the move to the package'
refute_contains 'pacman -U --noconfirm' "$uninstall_failure" 'pacman ran after the script removal failed'
kept_package="$(sed -n 's/.*kept at \([^ ]*\.pkg\.tar\.zst\)\..*/\1/p' <<<"$uninstall_failure")"
[[ -n "$kept_package" && -f "$kept_package" ]] || {
    printf 'FAIL: a failed script removal deleted the built package its recovery names\n%s\n' "$uninstall_failure" >&2
    exit 1
}
rm -rf -- "${kept_package%/*}"

printf 'Test 58: make dist inside an enclosing git repository still packs this tree\n'
nested="$TMP/enclosing/legion-powerctl"
mkdir -p "$nested"
git -C "$TMP/enclosing" init -q
tar -C "$ROOT_DIR" --exclude=./.git --exclude=./dist -cf - . | tar -C "$nested" -xf -
make -s -C "$nested" dist DISTDIR="$TMP/nested-dist" >/dev/null 2>&1
dist_version="$(make -s -C "$ROOT_DIR" print-version)"
packed="$(tar -tzf "$TMP/nested-dist/legion-powerctl-$dist_version.tar.gz")"
for packed_file in bin/legion-powerctl Makefile packaging/arch/PKGBUILD profiles/balanced.conf; do
    assert_contains "legion-powerctl-$dist_version/$packed_file" "$packed" \
        "make dist under an enclosing repository left out $packed_file"
done

printf 'Test 59: make install keeps edited /etc files unless FORCE_CONFIG=1\n'
config_stage="$TMP/config-stage"
make -s -C "$ROOT_DIR" install-config DESTDIR="$config_stage" SYSCONFDIR=/etc >/dev/null
cmp -s "$ROOT_DIR/config/config.conf" "$config_stage/etc/legion-powerctl/config.conf" || {
    printf 'FAIL: a staged (DESTDIR) install changed the config.conf bytes pacman relies on\n' >&2
    exit 1
}
printf 'ACTIVE_PROFILE=quiet\n' > "$config_stage/etc/legion-powerctl/config.conf"
printf 'STAPM_W=1\n' > "$config_stage/etc/legion-powerctl/profiles.d/quiet.conf"
make -s -C "$ROOT_DIR" install-config DESTDIR="$config_stage" SYSCONFDIR=/etc >/dev/null
assert_eq 'ACTIVE_PROFILE=quiet' "$(<"$config_stage/etc/legion-powerctl/config.conf")" \
    'make install overwrote an edited config.conf'
assert_eq 'STAPM_W=1' "$(<"$config_stage/etc/legion-powerctl/profiles.d/quiet.conf")" \
    'make install overwrote an edited profile'
make -s -C "$ROOT_DIR" install-config DESTDIR="$config_stage" SYSCONFDIR=/etc FORCE_CONFIG=1 >/dev/null
cmp -s "$ROOT_DIR/config/config.conf" "$config_stage/etc/legion-powerctl/config.conf" || {
    printf 'FAIL: FORCE_CONFIG=1 did not reset config.conf\n' >&2
    exit 1
}
cmp -s "$ROOT_DIR/profiles/quiet.conf" "$config_stage/etc/legion-powerctl/profiles.d/quiet.conf" || {
    printf 'FAIL: FORCE_CONFIG=1 did not reset a profile\n' >&2
    exit 1
}

fresh_etc="$TMP/fresh-make-etc"
make -s -C "$ROOT_DIR" install-config DESTDIR= SYSCONFDIR="$fresh_etc" >/dev/null
assert_eq 'ACTIVE_PROFILE=balanced' "$(grep '^ACTIVE_PROFILE=' "$fresh_etc/legion-powerctl/config.conf")" \
    'a fresh make install does not boot balanced'
printf 'ACTIVE_PROFILE=quiet\n' > "$fresh_etc/legion-powerctl/config.conf"
make -s -C "$ROOT_DIR" install-config DESTDIR= SYSCONFDIR="$fresh_etc" >/dev/null
assert_eq 'ACTIVE_PROFILE=quiet' "$(<"$fresh_etc/legion-powerctl/config.conf")" \
    'make install moved the boot profile of an existing install'

printf 'Test 60: make uninstall disables the unit before removing it, and refuses when it cannot\n'
uninstall_prefix="$TMP/uninstall-prefix"
uninstall_bin="$TMP/uninstall-bin"
mkdir -p "$uninstall_bin"
cat > "$uninstall_bin/systemctl" <<EOF_FAKE
#!/usr/bin/env bash
printf 'systemctl %s\n' "\$*" >> $(printf '%q' "$TMP/uninstall.log")
[[ -z "\${FAKE_SYSTEMCTL_FAIL:-}" ]]
EOF_FAKE
chmod +x "$uninstall_bin/systemctl"
uninstall_make() {
    PATH="$uninstall_bin:$PATH" make -s -C "$ROOT_DIR" uninstall DESTDIR= \
        PREFIX="$uninstall_prefix" SYSCONFDIR="$uninstall_prefix/etc" \
        SYSTEMDUNITDIR="$uninstall_prefix/lib/systemd/system"
}
mkdir -p "$uninstall_prefix/lib/systemd/system"
: > "$uninstall_prefix/lib/systemd/system/legion-powerctl.service"
: > "$TMP/uninstall.log"
FAKE_SYSTEMCTL_FAIL=1 assert_fails 'make uninstall removed a unit it could not disable' uninstall_make
[[ -e "$uninstall_prefix/lib/systemd/system/legion-powerctl.service" ]] || {
    printf 'FAIL: make uninstall removed the unit after systemctl disable failed\n' >&2
    exit 1
}
uninstall_make >/dev/null
assert_file_contains 'systemctl disable legion-powerctl.service' "$TMP/uninstall.log" \
    'make uninstall did not disable the unit'
assert_eq 'systemctl daemon-reload' "$(tail -n1 "$TMP/uninstall.log")" \
    'make uninstall left systemd holding the removed unit'
[[ ! -e "$uninstall_prefix/lib/systemd/system/legion-powerctl.service" ]] || {
    printf 'FAIL: make uninstall left the unit behind\n' >&2
    exit 1
}

printf 'Test 61: uninstall.sh refreshes the desktop database and icon cache it leaves stale\n'
uninstall_sh_bin="$TMP/uninstall-sh-bin"
mkdir -p "$uninstall_sh_bin"
printf '#!/usr/bin/env bash\nprintf "sudo %%s\\n" "$*" >> %q\n' "$TMP/uninstall-sh.log" > "$uninstall_sh_bin/sudo"
printf '#!/usr/bin/env bash\nexit 1\n' > "$uninstall_sh_bin/pacman"
for tool in update-desktop-database gtk-update-icon-cache; do
    printf '#!/usr/bin/env bash\nexit 0\n' > "$uninstall_sh_bin/$tool"
done
chmod +x "$uninstall_sh_bin"/*
: > "$TMP/uninstall-sh.log"
PATH="$uninstall_sh_bin:$PATH" "$ROOT_DIR/uninstall.sh" >/dev/null
uninstall_sh_log="$(<"$TMP/uninstall-sh.log")"
assert_contains 'sudo update-desktop-database -q /usr/share/applications' "$uninstall_sh_log" \
    'uninstall.sh did not refresh the desktop database'
assert_contains 'sudo gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor' "$uninstall_sh_log" \
    'uninstall.sh did not refresh the icon cache'
assert_match "$uninstall_sh_log" '*uninstall-files*update-desktop-database*' \
    'uninstall.sh refreshed the caches before removing the files'

printf 'Test 62: the boot unit orders after power-profiles-daemon without pulling it in\n'
unit_text="$(<"$ROOT_DIR/systemd/legion-powerctl.service")"
assert_match "$(grep '^After=' <<<"$unit_text")" '*power-profiles-daemon.service*' \
    'the unit can apply before power-profiles-daemon resets the platform profile'
refute_contains 'Wants=power-profiles-daemon' "$unit_text" 'the unit pulls power-profiles-daemon in'
refute_contains 'Requires=power-profiles-daemon' "$unit_text" 'the unit requires power-profiles-daemon'

run_package_install pacman
assert_contains 'died: pacman could not install' "$(<"$TMP/pkg-flow.log")" \
    'a failed pacman -U did not say how to install the built package'

printf 'Test 63: install.sh trusts exactly the ryzenadj locations the CLI runs from\n'
cli_dirs="$(grep '^readonly -a RYZENADJ_DIRS=' "$ROOT_DIR/bin/legion-powerctl" | sed 's/^readonly -a RYZENADJ_DIRS=//')"
installer_dirs="$(grep '^readonly RYZENADJ_DIRS=' "$ROOT_DIR/install.sh" | sed 's/^readonly RYZENADJ_DIRS=//')"
bench_dirs="$(grep '^readonly -a TRUSTED_DIRS=' "$ROOT_DIR/tools/legion-powerbench" | sed 's/^readonly -a TRUSTED_DIRS=//')"
assert_contains '/usr/bin' "$cli_dirs" 'the CLI ryzenadj directory list was not found'
assert_eq "$cli_dirs" "$installer_dirs" 'install.sh and the CLI trust different ryzenadj directories'
assert_eq "$cli_dirs" "$bench_dirs" 'legion-powerbench and the CLI trust different directories'
ryzenadj_functions="$TMP/ryzenadj-functions.sh"
awk '/^(trusted_ryzenadj|ensure_ryzenadj_binary)\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" > "$ryzenadj_functions"
assert_contains 'ensure_ryzenadj_binary()' "$(<"$ryzenadj_functions")" 'install.sh no longer has ensure_ryzenadj_binary'
mkdir -p "$TMP/path-only" "$TMP/no-ryzenadj"
cp "$FAKEBIN/ryzenadj" "$TMP/path-only/ryzenadj"
installer_rc=0
# shellcheck disable=SC2034,SC2329
installer_out="$(
    RYZENADJ_DIRS=("$TMP/no-ryzenadj")
    ARCH_FAMILY=0
    info() { printf '%s\n' "$*"; }
    warn() { printf 'WARNING: %s\n' "$*"; }
    die() { printf 'ERROR: %s\n' "$*"; exit 1; }
    # shellcheck source=/dev/null
    . "$ryzenadj_functions"
    PATH="$TMP/path-only:$PATH" ensure_ryzenadj_binary
)" || installer_rc=$?
assert_eq '1' "$installer_rc" 'install.sh accepted a ryzenadj the CLI will never run'
assert_contains "$TMP/path-only/ryzenadj" "$installer_out" 'install.sh did not name the ryzenadj it cannot use'

printf 'Test 64: a pacman upgrade never moves the boot profile the old package left behind\n'
# shellcheck disable=SC2329
pacman_upgrade() {
    local rewrites="$1"
    (
        # shellcheck source=/dev/null
        . "$pacman_scriptlet"
        pre_upgrade
        [[ "$rewrites" != shipped ]] || cp "$ROOT_DIR/config/config.conf" "$ETC/config.conf"
        [[ "$rewrites" != user-selects-quiet ]] || printf 'ACTIVE_PROFILE=quiet\n' > "$ETC/config.conf"
        post_upgrade
    )
}
cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
printf '# Profile applied by legion-powerctl.service once at boot.\nACTIVE_PROFILE=balanced\n' > "$ETC/config.conf"
: > "$LOG"
upgrade_out="$(pacman_upgrade shipped)"
assert_file_contains 'ACTIVE_PROFILE=balanced' "$ETC/config.conf" 'the upgrade flipped boot to the shipped profile'
refute_contains 'balanced-plus' "$(<"$ETC/config.conf")" 'the upgrade flipped boot to the shipped profile'
assert_contains 'selected balanced again' "$upgrade_out" 'the upgrade did not say it restored the boot profile'
assert_eq '' "$(<"$LOG")" 'restoring the boot profile applied something'
[[ ! -e "$pacman_varlib/pre-upgrade-boot" ]] || {
    printf 'FAIL: post_upgrade left the saved boot profile behind\n' >&2
    exit 1
}
printf 'ACTIVE_PROFILE=quiet\n' > "$ETC/config.conf"
upgrade_out="$(pacman_upgrade kept)"
assert_eq 'ACTIVE_PROFILE=quiet' "$(<"$ETC/config.conf")" 'an upgrade that kept config.conf rewrote it'
refute_contains 'selected' "$upgrade_out" 'an unchanged boot profile was selected again'
cp "$ROOT_DIR/profiles/quiet.conf" "$PROFILES/quiet.conf"
printf 'ACTIVE_PROFILE=balanced\n' > "$ETC/config.conf"
: > "$LOG"
upgrade_out="$(pacman_upgrade user-selects-quiet)"
assert_eq 'ACTIVE_PROFILE=quiet' "$(<"$ETC/config.conf")" 'the upgrade undid a select made during the transaction'
refute_contains 'replaced' "$upgrade_out" 'the upgrade blamed itself for a select made during the transaction'
assert_eq '' "$(<"$LOG")" 'the upgrade applied something'
cp "$ROOT_DIR/profiles/quiet.conf" "$PROFILES/powerbench-old.conf"
printf 'ACTIVE_PROFILE=powerbench-old\n' > "$ETC/config.conf"
upgrade_out="$(pacman_upgrade shipped)"
assert_file_contains 'ACTIVE_PROFILE=balanced-plus' "$ETC/config.conf" 'the upgrade selected a benchmark scratch profile for boot'
assert_contains 'temporary benchmark profile, so it was not selected again' "$upgrade_out" \
    'the upgrade did not explain why the benchmark profile stayed unselected'
refute_contains 'select powerbench-old' "$upgrade_out" 'the upgrade advised a select that the CLI refuses'
rm -f "$PROFILES/powerbench-old.conf"
printf 'ACTIVE_PROFILE=gone\n' > "$ETC/config.conf"
pacman_upgrade shipped >/dev/null
assert_file_contains 'ACTIVE_PROFILE=balanced-plus' "$ETC/config.conf" \
    'the upgrade pointed boot back at a profile that no longer exists'
[[ ! -e "$pacman_varlib/pre-upgrade-boot" ]] || {
    printf 'FAIL: post_upgrade left the saved boot profile behind\n' >&2
    exit 1
}

printf 'Test 65: a root-owned binary in a directory others control is never trusted\n'
if ! unshare --map-root-user true >/dev/null 2>&1; then
    if [[ -n "${CI:-}" ]]; then
        printf 'FAIL: no unprivileged user namespace to become root in, so CI cannot run the trust check on a root-owned binary\n' >&2
        exit 1
    fi
    printf '  (skipped: no unprivileged user namespace to become root in)\n'
else
    unsafe_dir="$TMP/unsafe-dir"
    mkdir -p "$unsafe_dir"
    cp "$FAKEBIN/ryzenadj" "$unsafe_dir/ryzenadj"
    chmod 0755 "$unsafe_dir/ryzenadj"
    chmod 0777 "$unsafe_dir"
    assert_eq '0 755' "$(unshare --map-root-user stat -c '%u %a' "$unsafe_dir/ryzenadj")" \
        'the namespace does not show the planted ryzenadj as root-owned'
    awk '/^(root_controlled_path|trusted_executable)\(\) \{$/,/^}$/' "$ROOT_DIR/bin/legion-powerctl" > "$TMP/cli-trust.sh"
    awk '/^(root_controlled_path|trusted_executable)\(\) \{$/,/^}$/' "$ROOT_DIR/tools/legion-powerbench" > "$TMP/bench-trust.sh"
    awk '/^(root_controlled_path|trusted_ryzenadj)\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" > "$TMP/installer-trust.sh"
    # shellcheck disable=SC2016
    trust_check='TESTING=0; . "$1"; if [[ "$1" == *installer* ]]; then RYZENADJ_DIRS=("${2%/*}"); trusted_ryzenadj >/dev/null; else trusted_executable "$2"; fi'
    for trust in cli bench installer; do
        if unshare --map-root-user bash -c "$trust_check" _ "$TMP/$trust-trust.sh" "$unsafe_dir/ryzenadj"; then
            printf 'FAIL: the %s trusted a root-owned binary in a world-writable directory\n' "$trust" >&2
            exit 1
        fi
    done
    system_bash="$(readlink -f -- "$(command -v bash)")"
    for trust in cli bench; do
        bash -c "$trust_check" _ "$TMP/$trust-trust.sh" "$system_bash" || {
            printf 'FAIL: the %s no longer trusts %s, root-owned all the way up\n' "$trust" "$system_bash" >&2
            exit 1
        }
    done
    chmod 0755 "$unsafe_dir"
fi

awk '/^root_controlled_path\(\) \{$/,/^}$/' "$ROOT_DIR/bin/legion-powerctl" > "$TMP/cli-walk.sh"
awk '/^root_controlled_path\(\) \{$/,/^}$/' "$ROOT_DIR/tools/legion-powerbench" > "$TMP/bench-walk.sh"
awk '/^root_controlled_path\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" > "$TMP/installer-walk.sh"
printf 'Test 65b: outside the test harness the real lookup still finds a root-owned ryzenadj\n'
awk '/^(root_controlled_path|trusted_executable|ryzenadj_candidates)\(\) \{$/,/^}$/' "$ROOT_DIR/bin/legion-powerctl" > "$TMP/cli-lookup.sh"
lookup_bash="$(readlink -f -- "$(command -v bash)")"
lookup_dir="$TMP/lookup-bin"
mkdir -p "$lookup_dir"
ln -s "$lookup_bash" "$lookup_dir/ryzenadj"
# shellcheck disable=SC2016
lookup_check='TESTING=0; . "$1"; RYZENADJ_DIRS=("$2"); ryzenadj_candidates'
grep -q '^ryzenadj_candidates() {$' "$TMP/cli-lookup.sh" || {
    printf 'FAIL: could not extract ryzenadj_candidates from the CLI\n' >&2
    exit 1
}
lookup_root_owned=1
lookup_walk="$lookup_bash"
while true; do
    lookup_stat="$(stat -c '%u %a' -- "$lookup_walk")"
    [[ "${lookup_stat%% *}" == 0 ]] && (( (8#${lookup_stat##* } & 8#022) == 0 )) || lookup_root_owned=0
    [[ "$lookup_walk" != / ]] || break
    lookup_walk="${lookup_walk%/*}"
    lookup_walk="${lookup_walk:-/}"
done
for trust in bench installer; do
    cmp -s "$TMP/cli-walk.sh" "$TMP/$trust-walk.sh" || {
        printf 'FAIL: the %s ownership walk no longer matches the one in the CLI\n' "$trust" >&2
        exit 1
    }
done
if (( lookup_root_owned == 1 )); then
    assert_eq "$lookup_bash" "$(bash -c "$lookup_check" _ "$TMP/cli-lookup.sh" "$lookup_dir")" \
        'the real ryzenadj lookup rejects a binary that is root-owned all the way up'
    for trust in cli bench installer; do
        # shellcheck disable=SC2016
        bash -c '. "$1"; root_controlled_path "$2"' _ "$TMP/$trust-walk.sh" "$lookup_bash" || {
            printf 'FAIL: the %s ownership walk rejects a root-owned path\n' "$trust" >&2
            exit 1
        }
        # shellcheck disable=SC2016
        bash -c 'IFS=:; . "$1"; root_controlled_path "$2"' _ "$TMP/$trust-walk.sh" "$lookup_bash" || {
            printf 'FAIL: the %s ownership walk depends on the IFS of its caller\n' "$trust" >&2
            exit 1
        }
    done
elif [[ -n "${CI:-}" ]]; then
    printf 'FAIL: %s is not root-owned all the way up, so CI cannot run the real ryzenadj lookup\n' "$lookup_bash" >&2
    exit 1
else
    printf '  (skipped: %s is not root-owned all the way up on this machine)\n' "$lookup_bash"
fi

printf 'Test 65c: the installer does not call a failed enable a completed install\n'
installer_finish="$TMP/installer-finish.sh"
awk '/^(info|warn)\(\) \{.*\}$/; /^(enable_service|finish_install)\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" > "$installer_finish"
for installer_fn in 'enable_service()' 'finish_install()'; do
    assert_contains "$installer_fn" "$(<"$installer_finish")" "install.sh no longer has $installer_fn"
done
[[ "$(awk '/^main\(\) \{$/,/^}$/' "$ROOT_DIR/install.sh" | tail -n 2 | head -n 1)" == '    finish_install' ]] || {
    printf 'FAIL: install.sh main no longer ends on the status of finish_install\n' >&2
    exit 1
}
# shellcheck disable=SC2016
printf '#!/usr/bin/env bash\n[[ "$1" != enable ]] || exit "${FAKE_ENABLE_RC:-0}"\n' > "$TMP/installer-cli"
chmod +x "$TMP/installer-cli"
run_installer_finish() {
    FAKE_ENABLE_RC="$1" ENABLE_SERVICE="$2" bash -c '
        set -Eeuo pipefail
        . "$1"
        SUDO=() CLI_BIN="$2" ENABLE_FAILED=0
        enable_service || true
        finish_install
    ' _ "$installer_finish" "$TMP/installer-cli" 2>&1
}
installer_rc=0
installer_out="$(run_installer_finish 1 1)" || installer_rc=$?
assert_eq '1' "$installer_rc" 'install.sh exited 0 after the boot service could not be enabled'
assert_contains 'NOT working yet' "$installer_out" 'install.sh did not say the install is not working'
refute_contains 'Installation complete.' "$installer_out" 'install.sh called a failed enable a completed install'
installer_rc=0
installer_out="$(run_installer_finish 0 1)" || installer_rc=$?
assert_eq '0' "$installer_rc" 'install.sh failed although enable succeeded'
assert_contains 'Installation complete.' "$installer_out" 'install.sh did not report a completed install'
installer_rc=0
installer_out="$(run_installer_finish 1 0)" || installer_rc=$?
assert_eq '0' "$installer_rc" 'install.sh --no-enable failed on an enable it never ran'
assert_contains 'Installation complete.' "$installer_out" 'install.sh --no-enable did not report a completed install'

printf 'Test 66: a system command found through a symlink runs the target the trust walk checked\n'
plant_dir="$TMP/user-bin"
mkdir -p "$plant_dir"
system_bash="$(readlink -f -- "$(command -v bash)")"
ln -sfn "$system_bash" "$plant_dir/tool"
awk '/^(root_controlled_path|trusted_executable|resolve_system_command)\(\) \{$/,/^}$/' \
    "$ROOT_DIR/bin/legion-powerctl" > "$TMP/cli-resolve.sh"
grep -q 'for dir in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do' "$TMP/cli-resolve.sh" || {
    printf 'FAIL: resolve_system_command no longer has the directory list this test replaces\n' >&2
    exit 1
}
# shellcheck disable=SC2016
sed -i -e 's#^\( *\)if (( EUID != 0 )); then$#\1if false; then#' \
    -e 's#for dir in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do#for dir in "$PLANT_DIR"; do#' \
    "$TMP/cli-resolve.sh"
grep -q 'if false; then' "$TMP/cli-resolve.sh" || { printf 'FAIL: the root branch was not isolated\n' >&2; exit 1; }
awk '/^(root_controlled_path|trusted_executable|system_binary)\(\) \{$/,/^}$/' \
    "$ROOT_DIR/tools/legion-powerbench" > "$TMP/bench-resolve.sh"
# shellcheck disable=SC2016
cli_resolved="$(PLANT_DIR="$plant_dir" bash -c 'TESTING=0; . "$1"; resolve_system_command tool' _ "$TMP/cli-resolve.sh")"
# shellcheck disable=SC2016
bench_resolved="$(bash -c 'TESTING=0; TRUSTED_DIRS=("$2"); . "$1"; system_binary tool ""' _ \
    "$TMP/bench-resolve.sh" "$plant_dir")"
assert_eq "$system_bash" "$cli_resolved" 'the CLI returned a symlink in a user-owned directory instead of its checked target'
assert_eq "$system_bash" "$bench_resolved" 'legion-powerbench returned a symlink in a user-owned directory instead of its checked target'

gate_summary() {
    bash "$ROOT_DIR/tests/gate-summary.sh" "$@"
}
gate_skips() {
    grep '^SKIPPED' <<<"$1" || true
}
gate_marker() {
    sed -n "s/.*printf '\\($1 not installed;[^']*\\)\\\\n'.*/\\1/p" "$ROOT_DIR/Makefile"
}
# Under a hook or `rebase --exec` git exports GIT_DIR, and `-C` does not override it:
# without the scrub these calls would initialise and commit into the repository this
# suite runs from instead of the fixture.
gate_git() {
    local var
    local -a scrubbed=(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE)
    for var in $(git rev-parse --local-env-vars); do
        scrubbed+=(-u "$var")
    done
    "${scrubbed[@]}" git -C "$1" -c user.name=gate -c user.email=gate@example.invalid \
        -c commit.gpgsign=false "${@:2}"
}
gate_stub() {
    printf '#!/bin/sh\n%s\n' "$2" > "$1"
    chmod +x "$1"
}

printf 'Test 67: the gate summary names the commit, the machine, the tools and every skip\n'
fish_marker="$(gate_marker fish)"
ruff_marker="$(gate_marker ruff)"
shellcheck_marker="$(gate_marker shellcheck)"
for gate_tool in fish ruff shellcheck; do
    assert_eq '1' "$(gate_marker "$gate_tool" | grep -c .)" \
        "the Makefile no longer prints one skip line for $gate_tool in the shape the summary reads"
done
{
    printf 'bash -n bin/legion-powerctl\n%s\n' "$fish_marker"
    printf 'Test 1: configure, select, and apply a profile\n'
    printf 'test_a (test_theme.ThemeTest.test_a) ... ok\n'
    printf 'test_b (test_theme.ThemeTest.test_b) ... skipped %s\n' "'PySide6 is not installed'"
    printf 'test_c (test_theme.ThemeTest.test_c) ... skipped %s\n' "'PySide6 is not installed'"
    printf '\n%s\n' '----------------------------------------------------------------------'
    printf 'Ran 419 tests in 7.950s\n\nOK (skipped=309)\n'
    printf 'All checks passed!\n'
} > "$TMP/gate-box.log"
gate_out="$(gate_summary check "$TMP/gate-box.log" 0)"
mapfile -t gate_lines <<<"$gate_out"
assert_eq '10' "${#gate_lines[@]}" 'the summary is not the ten lines this transcript should give'
assert_eq '' "${gate_lines[0]}" 'the summary does not start on its own paragraph'
assert_eq '== Gate summary ==' "${gate_lines[1]}" 'the summary has no heading'
assert_eq 'target:  make check' "${gate_lines[2]}" 'the summary does not name the target'
[[ "${gate_lines[3]}" =~ ^commit:\ \ ([0-9a-f]{12,}(-dirty)?|not\ a\ git\ checkout)$ ]] || {
    printf 'FAIL: the commit line is neither a hash nor "not a git checkout": %s\n' "${gate_lines[3]}" >&2
    exit 1
}
assert_match "${gate_lines[4]}" 'machine: ?*; ?*; ?*' 'the machine line is not OS; kernel; hardware'
IFS=';' read -r _ gate_kernel _ <<<"${gate_lines[4]}"
assert_eq " $(uname -srm)" "$gate_kernel" \
    'the machine line carries more of uname than the system, the release and the architecture'
refute_contains '"' "${gate_lines[4]}" 'the machine line kept the quotes os-release puts around the name'
assert_match "${gate_lines[5]}" 'tools:   bash [0-9]*' 'the tools line does not start with the bash version'
assert_eq "$(printf 'SKIPPED: %s\n' 'fish completion syntax - fish not installed' \
    '309 of 419 GUI tests - PySide6 is not installed' 'end-to-end tier - not part of make check')" \
    "$(gate_skips "$gate_out")" 'the summary did not list exactly the three skips of this transcript'
assert_eq 'result:  PASSED WITH 3 SKIPS - not a full pass' "${gate_lines[9]}" \
    'the result does not count the skipped gates, or is not the last line'
gate_tools="$TMP/gate-tools"
gate_bare="$TMP/gate-bare"
mkdir -p "$gate_tools" "$gate_bare"
# shellcheck disable=SC2016
gate_stub "$gate_tools/python3" 'case "$*" in *PySide6*) echo 6.99.2 ;; *) echo "Python 3.99.1" ;; esac'
gate_stub "$gate_tools/shellcheck" 'printf "%s\n" "ShellCheck - shell script analysis tool" "version: 0.99.3" "license: none"'
gate_stub "$gate_tools/ruff" 'echo "ruff 0.99.4"'
gate_stub "$gate_tools/fish" 'echo "fish, version 3.99.5"'
for gate_tool in bash sed head cat uname dirname; do
    ln -s "$(command -v "$gate_tool")" "$gate_bare/$gate_tool"
done
# shellcheck disable=SC2016
gate_bash="$(bash -c 'printf %s "${BASH_VERSION%%(*}"')"
gate_out="$(PATH="$gate_tools:$PATH" gate_summary check "$TMP/gate-box.log" 0)"
assert_eq "tools:   bash $gate_bash, python 3.99.1, shellcheck 0.99.3, ruff 0.99.4, fish 3.99.5, PySide6 6.99.2" \
    "$(grep '^tools: ' <<<"$gate_out")" 'the tools line does not name every installed tool with its version'
gate_out="$(PATH="$gate_bare" gate_summary check "$TMP/gate-box.log" 0)"
assert_eq "tools:   bash $gate_bash" "$(grep '^tools: ' <<<"$gate_out")" \
    'the tools line names a tool that is not installed'
assert_contains 'commit:  not a git checkout' "$gate_out" 'a machine without git was given a commit'

printf 'Test 68: a strict run with nothing skipped says so, and a second unittest footer is the end-to-end tier\n'
{
    printf 'test_a (test_theme.ThemeTest.test_a) ... ok\n\n'
    printf 'Ran 419 tests in 31.204s\n\nOK\n'
    printf 'All checks passed!\n'
    printf 'test_window (test_desktop_session.SessionTest.test_window) ... ok\n\n'
    printf 'Ran 23 tests in 41.730s\n\nOK\n'
} > "$TMP/gate-strict.log"
gate_out="$(gate_summary check-strict "$TMP/gate-strict.log" 0)"
assert_contains 'target:  make check-strict' "$gate_out" 'the summary does not name the strict target'
assert_eq 'SKIPPED: none' "$(gate_skips "$gate_out")" 'a strict run with no skip did not say none'
assert_eq 'result:  PASSED - nothing skipped' "$(tail -n 1 <<<"$gate_out")" \
    'a strict run with no skip is not reported as a full pass'
{
    printf 'Ran 419 tests in 31.204s\n\nOK\n'
    printf 'test_window (test_desktop_session.SessionTest.test_window) ... skipped %s\n' "'no window manager'"
    printf 'test_tree (test_atspi_tree.TreeTest.test_tree) ... skipped %s\n' '"the bus is not up"'
    printf '\nRan 23 tests in 41.730s\n\nOK (skipped=2, expected failures=1)\n'
} > "$TMP/gate-strict-skips.log"
gate_out="$(gate_summary check-strict "$TMP/gate-strict-skips.log" 0)"
assert_eq 'SKIPPED: 2 of 23 end-to-end tests - no window manager; the bus is not up' "$(gate_skips "$gate_out")" \
    'skips in the second unittest footer were not reported as end-to-end tests with their reasons'
assert_eq 'result:  PASSED WITH 1 SKIP - not a full pass' "$(tail -n 1 <<<"$gate_out")" \
    'one skipped tier did not stop the result from being a full pass'
{
    printf 'test_a (test_theme.ThemeTest.test_a) ... skipped %s\n' "'/home/gatefixture/venv has no PySide6'"
    printf '\nRan 419 tests in 31.204s\r\n\r\nOK (skipped=1)\r\n'
    printf 'Ran 23 tests in 41.730s\n\nOK (skipped=3)'
} > "$TMP/gate-strict-bare.log"
gate_out="$(gate_summary check-strict "$TMP/gate-strict-bare.log" 0)"
assert_eq "$(printf 'SKIPPED: %s\n' '1 of 419 GUI tests - <path> has no PySide6' \
    '3 of 23 end-to-end tests - the transcript gives no reason')" "$(gate_skips "$gate_out")" \
    'carriage returns, a last line without a newline, a path in a reason or the reason of the tier before was misread'
refute_contains 'gatefixture' "$gate_out" 'a home directory from a skip reason reached the summary'

printf 'Test 69: a lint that did not run for a missing tool is a skip\n'
printf '%s\n' "$ruff_marker" "$shellcheck_marker" > "$TMP/gate-not-run.log"
gate_out="$(gate_summary check "$TMP/gate-not-run.log" 0)"
assert_eq "$(printf 'SKIPPED: %s\n' 'Python lint - ruff not installed' 'ShellCheck - shellcheck not installed' \
    'end-to-end tier - not part of make check')" "$(gate_skips "$gate_out")" \
    'the two lints that did not run are not both in the summary'
assert_eq 'result:  PASSED WITH 3 SKIPS - not a full pass' "$(tail -n 1 <<<"$gate_out")" \
    'the result does not count the lints that did not run'

printf 'Test 70: each case a suite skipped is quoted, and a path in it never reaches the summary\n'
{
    printf 'Test 16: last_apply keys survive a locale where [A-Z] excludes I\n'
    printf '  (tr_TR.utf8 locale unavailable; skipped)\n'
    printf 'Test B31: a read-only state file refuses the write\n'
    printf '  (skipped: running as root, where a read-only file cannot refuse a write)\n'
    printf 'Test 65b: outside the test harness the real lookup still finds a root-owned ryzenadj\n'
    printf '  (skipped: /home/gatefixture/.local/bin/bash is not root-owned all the way up on this machine)\n'
    printf 'Test 93: a path inside quotes and brackets\n'
    # shellcheck disable=SC2016
    printf '  (skipped: `/home/gatefixture/a`, [/home/gatefixture/b], </home/gatefixture/c>, {/home/gatefixture/d}, x|/home/gatefixture/e)\n'
    printf 'Test 94: a path with a bracket in it, beside text that is not a path\n'
    printf '  (skipped: "/home/gatefixture/f(g)h/i" is gone, and/or tests/test.sh is; HOME=/home/gatefixture)\n'
} > "$TMP/gate-suite.log"
gate_out="$(gate_summary check-strict "$TMP/gate-suite.log" 0)"
# shellcheck disable=SC2016
assert_eq "$(printf 'SKIPPED: %s\n' 'Test 16 - (tr_TR.utf8 locale unavailable; skipped)' \
    'Test B31 - (skipped: running as root, where a read-only file cannot refuse a write)' \
    'Test 65b - (skipped: <path> is not root-owned all the way up on this machine)' \
    'Test 93 - (skipped: `<path>`, [<path>], <<path>>, {<path>}, x|<path>)' \
    'Test 94 - (skipped: "<path>" is gone, and/or tests/test.sh is; HOME=<path>)')" \
    "$(gate_skips "$gate_out")" 'the suite skips are not quoted one per line with every path hidden'
refute_contains 'gatefixture' "$gate_out" 'a home directory from a skip line reached the summary'
assert_eq 'result:  PASSED WITH 5 SKIPS - not a full pass' "$(tail -n 1 <<<"$gate_out")" \
    'the result does not count the cases the suites skipped'

printf 'Test 71: a title or a warning that only mentions a skip adds nothing to the summary\n'
{
    printf 'Test B7: a policy that does not advertise the EPP is skipped, not fatal\n'
    printf 'Test 35: a --to off the step grid is refused, not silently skipped\n'
    printf 'Test 90: %s\n' "$fish_marker" "$ruff_marker" "$shellcheck_marker"
    printf 'Test 91: Ran 419 tests in 7.950s\n'
    printf 'Test 92: OK (skipped=309)\n'
    printf 'WARNING: boost control is unavailable, so BOOST=on was skipped.\n'
    printf 'WARNING: %s\n' "$fish_marker" "$ruff_marker" "$shellcheck_marker"
    printf 'WARNING: Ran 419 tests in 7.950s\n\nOK (skipped=309)\n'
    printf 'Ran 5 tests in 0.100s\n\nWARNING: OK (skipped=5)\n'
    printf '(skipped: not indented, so not a line a suite prints)\n'
    printf '    (skipped: indented deeper than a suite prints it)\n'
} > "$TMP/gate-titles.log"
gate_out="$(gate_summary check-strict "$TMP/gate-titles.log" 0)"
assert_eq 'SKIPPED: none' "$(gate_skips "$gate_out")" 'text that only mentions a skip was counted as one'
assert_eq 'result:  PASSED - nothing skipped' "$(tail -n 1 <<<"$gate_out")" \
    'text that only mentions a skip changed the result'

printf 'Test 72: a failing exit status is a failed result, whatever the transcript says\n'
gate_out="$(gate_summary check "$TMP/gate-box.log" 2)"
assert_eq 'result:  FAILED (exit 2)' "$(tail -n 1 <<<"$gate_out")" 'a failed run was not reported as failed'
refute_contains 'PASSED' "$gate_out" 'a failed run was called passed'
assert_contains 'SKIPPED: fish completion syntax - fish not installed' "$gate_out" \
    'a failed run dropped the skips it had seen'
assert_exit 2 'an exit status that is not a number was accepted' gate_summary check "$TMP/gate-box.log" passed
assert_exit 2 'an unknown target was accepted' gate_summary test "$TMP/gate-box.log" 0
assert_exit 2 'a transcript that does not exist was accepted' gate_summary check "$TMP/no-such-transcript" 0
assert_exit 2 'a call without an exit status was accepted' gate_summary check "$TMP/gate-box.log"
assert_exit 2 'a run without a command was accepted' gate_summary run check
assert_exit 2 'a run for an unknown target was accepted' gate_summary run test true

printf 'Test 73: the commit is a hash only for a tree that is its own git checkout\n'
gate_copy="$TMP/gate-copy"
gate_enclosing="$TMP/gate-enclosing"
gate_repo="$TMP/gate-repo"
for gate_tree in "$gate_copy" "$gate_enclosing/tree" "$gate_repo"; do
    mkdir -p "$gate_tree/tests"
    cp "$ROOT_DIR/tests/gate-summary.sh" "$gate_tree/tests/"
done
gate_git "$gate_enclosing" init -q
gate_git "$gate_enclosing" commit -q --no-verify --allow-empty -m 'enclosing repository'
gate_git "$gate_enclosing/tree" rev-parse --verify -q HEAD >/dev/null || {
    printf 'FAIL: the enclosing repository has no commit for the copy to inherit\n' >&2
    exit 1
}
for gate_tree in "$gate_copy" "$gate_enclosing/tree"; do
    assert_contains 'commit:  not a git checkout' \
        "$(bash "$gate_tree/tests/gate-summary.sh" check "$TMP/gate-box.log" 0)" \
        "the copy at ${gate_tree#"$TMP"/} was reported as a git checkout"
done
gate_git "$gate_repo" init -q
gate_git "$gate_repo" commit -q --no-verify --allow-empty -m 'empty tree'
gate_out="$(bash "$gate_repo/tests/gate-summary.sh" check "$TMP/gate-box.log" 0)"
assert_contains "commit:  $(gate_git "$gate_repo" rev-parse --short=12 HEAD)-dirty" "$gate_out" \
    'a checkout with an uncommitted file was not marked dirty'
gate_git "$gate_repo" add tests/gate-summary.sh
gate_git "$gate_repo" commit -q --no-verify -m 'track the summary'
gate_head="$(gate_git "$gate_repo" rev-parse --short=12 HEAD)"
gate_out="$(bash "$gate_repo/tests/gate-summary.sh" check "$TMP/gate-box.log" 0)"
assert_eq "commit:  $gate_head" "$(grep '^commit: ' <<<"$gate_out")" \
    'a clean checkout was not reported by its commit alone'
gate_out="$(GIT_DIR="$gate_enclosing/.git" bash "$gate_repo/tests/gate-summary.sh" check "$TMP/gate-box.log" 0)"
assert_eq "commit:  $gate_head" "$(grep '^commit: ' <<<"$gate_out")" \
    'a GIT_DIR left by a hook made the summary report the commit of another repository'
assert_contains 'commit:  not a git checkout' \
    "$(GIT_DIR="$gate_repo/.git" bash "$gate_copy/tests/gate-summary.sh" check "$TMP/gate-box.log" 0)" \
    'a GIT_DIR left by a hook made a copy without git look like a checkout'

printf 'Test 74: the machine line names the model before the machine-type code, and unknown without DMI\n'
gate_dmi="$TMP/gate-dmi"
mkdir -p "$gate_dmi"
printf 'LENOVO\n' > "$gate_dmi/sys_vendor"
printf '83RU\n' > "$gate_dmi/product_name"
printf 'Legion Pro 7 16ARX10\n' > "$gate_dmi/product_version"
gate_out="$(GATE_SUMMARY_DMI_ROOT="$gate_dmi" gate_summary check "$TMP/gate-box.log" 0)"
assert_match "$(grep '^machine: ' <<<"$gate_out")" '*; LENOVO Legion Pro 7 16ARX10' \
    'the machine line does not end with the vendor and the model'
printf 'To Be Filled By O.E.M.\n' > "$gate_dmi/product_version"
printf 'Legion Pro 7\n' > "$gate_dmi/product_family"
gate_out="$(GATE_SUMMARY_DMI_ROOT="$gate_dmi" gate_summary check "$TMP/gate-box.log" 0)"
assert_match "$(grep '^machine: ' <<<"$gate_out")" '*; LENOVO Legion Pro 7' \
    'a placeholder model did not fall back to the product family'
rm -f "$gate_dmi/product_family"
gate_out="$(GATE_SUMMARY_DMI_ROOT="$gate_dmi" gate_summary check "$TMP/gate-box.log" 0)"
assert_match "$(grep '^machine: ' <<<"$gate_out")" '*; LENOVO 83RU' \
    'a placeholder model without a family did not fall back to the product name'
gate_out="$(GATE_SUMMARY_DMI_ROOT="$TMP/gate-no-dmi" gate_summary check "$TMP/gate-box.log" 0)"
assert_match "$(grep '^machine: ' <<<"$gate_out")" '*; unknown' \
    'an unreadable DMI root was not reported as unknown hardware'

printf 'Test 75: a failing gate run through make check ends in a failed summary and removes its transcript\n'
gate_tmpdir="$TMP/gate-tmpdir"
mkdir -p "$gate_tmpdir"
gate_rc=0
gate_out="$(MAKEFLAGS='' TMPDIR="$gate_tmpdir" make -C "$ROOT_DIR" check \
    SHELL_SOURCES="$TMP/no-such-gate-file" 2>&1)" || gate_rc=$?
assert_eq '2' "$gate_rc" 'make check did not exit 2 when a gate failed'
assert_contains '== Gate summary ==' "$gate_out" 'a failed make check printed no summary'
assert_eq '1' "$(grep -c '^result:  FAILED (exit [1-9][0-9]*)$' <<<"$gate_out" || true)" \
    'a failed make check did not print one failed result'
refute_contains 'PASSED' "$gate_out" 'a failed make check was called passed'
assert_eq '' "$(find "$gate_tmpdir" -mindepth 1)" 'make check left its transcript behind'

printf 'Test 76: a refused strict run prints its two refusal lines and no summary\n'
gate_path="$TMP/gate-path"
mkdir -p "$gate_path"
for gate_tool in make sed; do
    ln -s "$(command -v "$gate_tool")" "$gate_path/$gate_tool"
done
gate_rc=0
gate_out="$(MAKEFLAGS='' PATH="$gate_path" make -C "$ROOT_DIR" check-strict 2>&1)" || gate_rc=$?
assert_eq '2' "$gate_rc" 'a refused make check-strict did not exit 2'
# shellcheck disable=SC2016
assert_eq "$(printf '%s\n' 'check-strict cannot run; not installed: shellcheck fish ruff PySide6' \
    'Install them, or run `make check` and accept that those gates are skipped.')" \
    "$(grep -v '^make' <<<"$gate_out")" 'the refusal of make check-strict changed, or something ran after it'

printf 'Test 77: both targets hand the summary what their gates print, on either stream\n'
assert_contains 'tests/gate-summary.sh' "$(make -s -C "$ROOT_DIR" print-shell-sources)" \
    'the summary script is not syntax-checked and linted with the other shell sources'
gate_stand="$TMP/gate-stand"
mkdir -p "$gate_stand"
# shellcheck disable=SC2016
gate_stub "$gate_stand/gate-stand-in" 'printf "stand-in gates: %s\n" "$*"; printf "%s\n" "$GATE_STAND_IN_ARG" >&2'
gate_make() {
    MAKEFLAGS='' TMPDIR="$gate_tmpdir" PATH="$gate_stand:$1" \
        make -C "$ROOT_DIR" "${@:2}" SHELL_SOURCES="$TMP/no-such-gate-file" 2>&1
}
gate_rc=0
gate_out="$(GATE_STAND_IN_ARG="$fish_marker" gate_make "$PATH" check GATE_MAKE=gate-stand-in)" || gate_rc=$?
assert_eq '0' "$gate_rc" 'make check did not exit with the status of its gates'
assert_contains 'stand-in gates: check-gates' "$gate_out" 'make check does not run the check-gates target'
assert_contains 'target:  make check' "$gate_out" 'make check does not name itself in the summary'
assert_eq "$(printf 'SKIPPED: %s\n' 'fish completion syntax - fish not installed' \
    'end-to-end tier - not part of make check')" "$(gate_skips "$gate_out")" \
    'a skip the gates printed on stderr did not reach the summary of make check'
assert_eq 'result:  PASSED WITH 2 SKIPS - not a full pass' "$(grep -v '^make' <<<"$gate_out" | tail -n 1)" \
    'make check did not end on a result that counts the skips of its own run'
gate_rc=0
gate_out="$(GATE_STAND_IN_ARG="$fish_marker" gate_make "$gate_tools:$PATH" check-strict GATE_MAKE=gate-stand-in)" || gate_rc=$?
assert_eq '0' "$gate_rc" 'make check-strict did not exit with the status of its gates'
assert_contains 'stand-in gates: check-strict-gates' "$gate_out" \
    'make check-strict does not run the check-strict-gates target'
assert_contains 'target:  make check-strict' "$gate_out" 'make check-strict does not name itself in the summary'
assert_eq 'SKIPPED: fish completion syntax - fish not installed' "$(gate_skips "$gate_out")" \
    'the summary of make check-strict is not exactly the skips its gates printed'
assert_eq 'result:  PASSED WITH 1 SKIP - not a full pass' "$(grep -v '^make' <<<"$gate_out" | tail -n 1)" \
    'make check-strict did not end on a result that counts the skips of its own run'
assert_eq '' "$(find "$gate_tmpdir" -mindepth 1)" 'a passing run left its transcript behind'
assert_eq "$(printf '%s\n' 'bash tests/test.sh' 'bash tests/e2e/run.sh')" \
    "$(gate_make "$PATH" -n check-strict-gates | grep -o -e '^bash tests/test\.sh$' -e 'bash tests/e2e/run\.sh')" \
    'the strict gates are not the gates of make check followed by the end-to-end tier'
gate_out="$(gate_make "$PATH" -n check)"
assert_contains 'tests/gate-summary.sh run check ' "$gate_out" 'a dry run of make check does not print its recipe'
refute_contains 'Gate summary' "$gate_out" 'a dry run of make check ran the gates and printed a result'

printf 'Test 78: a make check that is told to stop takes its gates with it and prints no summary\n'
# shellcheck disable=SC2016
gate_stub "$gate_stand/gate-slow" 'printf "%s\n" "$$" > "$GATE_STAND_IN_ARG"; exec sleep 120'
GATE_STAND_IN_ARG="$TMP/gate-slow.pid" MAKEFLAGS='' TMPDIR="$gate_tmpdir" PATH="$gate_stand:$PATH" \
    make -C "$ROOT_DIR" check GATE_MAKE=gate-slow SHELL_SOURCES="$TMP/no-such-gate-file" \
    > "$TMP/gate-slow.out" 2>&1 &
gate_make_pid=$!
for _ in $(seq 300); do [[ -s "$TMP/gate-slow.pid" ]] && break; sleep 0.1; done
[[ -s "$TMP/gate-slow.pid" ]] || {
    kill "$gate_make_pid" 2>/dev/null || true
    printf 'FAIL: the stand-in gates never started\n%s\n' "$(<"$TMP/gate-slow.out")" >&2
    exit 1
}
gate_slow_pid="$(<"$TMP/gate-slow.pid")"
gate_started="$SECONDS"
kill -TERM "$gate_make_pid"
gate_rc=0
wait "$gate_make_pid" || gate_rc=$?
if kill -0 "$gate_slow_pid" 2>/dev/null; then
    kill "$gate_slow_pid" 2>/dev/null || true
    printf 'FAIL: make check was terminated and its gates kept running\n' >&2
    exit 1
fi
assert_eq '143' "$gate_rc" 'a terminated make check did not die of the signal'
(( SECONDS - gate_started < 60 )) || {
    printf 'FAIL: a terminated make check waited for its gates to finish by themselves\n' >&2
    exit 1
}
refute_contains 'Gate summary' "$(<"$TMP/gate-slow.out")" 'a make check that was cut short printed a summary'
assert_eq '' "$(find "$gate_tmpdir" -mindepth 1)" 'a terminated make check left its transcript behind'

printf 'All tests passed.\n'
