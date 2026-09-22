#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SUITE_TMP="$(mktemp -d)"
trap 'rm -rf "$SUITE_TMP"' EXIT
FILTER="${1:-}"
CASE_NUMBER=0
FAILED=()

# shellcheck source=tests/lib.sh
source "$ROOT_DIR/tests/lib.sh"

setup_repair_fixture() {
    # shellcheck source=tests/fixtures/make-fake-root.sh
    source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$SUITE_TMP/case$CASE_NUMBER"
    REPAIR_MODULES_LOAD_CONF="$FAKE_ROOT/etc/modules-load.d/legion-powerctl.conf"
    REPAIR_BLACKLIST_FILE="$FAKE_ROOT/etc/modprobe.d/legion-powerctl-no-ryzen-smu.conf"
    mkdir -p "${REPAIR_MODULES_LOAD_CONF%/*}" "${REPAIR_BLACKLIST_FILE%/*}"
    printf '# Written by legion-powerctl install.sh --install-ryzen-smu.\n# Delete this file if you remove ryzen_smu-dkms-git.\nryzen_smu\n' \
        > "$REPAIR_MODULES_LOAD_CONF"
    printf '[none] integrity confidentiality\n' > "$LOCKDOWN"
    LEGION_TEST_ENV=(
        "PATH=$FAKEBIN:$PATH"
        "LEGION_POWERCTL_MODULES_LOAD_CONF=$REPAIR_MODULES_LOAD_CONF"
        "LEGION_POWERCTL_SMU_BLACKLIST_FILE=$REPAIR_BLACKLIST_FILE"
    )
    cat > "$FAKEBIN/modprobe" <<'EOF_MODPROBE'
#!/usr/bin/env bash
set -eu
printf 'modprobe %s\n' "$*" >> "${LEGION_TEST_LOG:?}"
if [[ "$#" != 2 || "$1" != -r || "$2" != ryzen_smu ]]; then
    printf 'Unexpected or forced module operation: %s\n' "$*" >&2
    exit 99
fi
[[ -z "${LEGION_FAKE_MODPROBE_FAIL:-}" ]] || exit 1
[[ -z "${LEGION_FAKE_MODPROBE_KEEP_INTERFACE:-}" ]] || exit 0
rm -rf -- "${LEGION_POWERCTL_SMU_SYSFS_DIR:?}" "${LEGION_POWERCTL_MODULES_ROOT:?}/ryzen_smu"
EOF_MODPROBE
    chmod +x "$FAKEBIN/modprobe"
}

run_case() {
    local fn="$1" description="$2" rc=0
    CASE_NUMBER=$(( CASE_NUMBER + 1 ))
    [[ -z "$FILTER" || "$fn" == *"$FILTER"* ]] || return 0
    printf 'Test R%d: %s\n' "$CASE_NUMBER" "$description"
    set +e
    (
        set -Eeuo pipefail
        setup_repair_fixture
        "$fn"
    )
    rc=$?
    set -e
    if (( rc != 0 )); then
        FAILED+=("R$CASE_NUMBER $fn")
        printf 'FAILED: %s (exit %s)\n' "$fn" "$rc" >&2
    fi
}

file_tree() {
    local directory="$1"
    find "$directory" -mindepth 1 -printf '%y %P\n' | sort
    find "$directory" -type f -print0 | sort -z | xargs -0 -r sha256sum
}

capture_originals() {
    cp "$PROFILES/balanced-plus.conf" "$FAKE_ROOT/profile.before"
    cp "$REPAIR_MODULES_LOAD_CONF" "$FAKE_ROOT/modules.before"
    cp "$STATE/last-apply.env" "$FAKE_ROOT/state.before"
    CPU_BEFORE="$(file_tree "$SYSFS")"
}

prepare_broken_repair() {
    fake_add_smu_interface
    rm "$SMU_SYSFS_DIR/pm_table"
    sed -i 's/^TEMP_C=.*/TEMP_C=90/' "$PROFILES/balanced-plus.conf"
    printf '# Preserve this original file exactly for recovery.\n\n' >> "$PROFILES/balanced-plus.conf"
    capture_originals
}

assert_originals_unchanged() {
    cmp "$FAKE_ROOT/profile.before" "$PROFILES/balanced-plus.conf"
    cmp "$FAKE_ROOT/modules.before" "$REPAIR_MODULES_LOAD_CONF"
    [[ ! -e "$REPAIR_BLACKLIST_FILE" ]] || {
        printf 'FAIL: an unsuccessful repair changed module persistence\n' >&2
        exit 1
    }
}

assert_no_apply_attempt() {
    refute_contains 'ryzenadj ' "$(<"$LOG")" 'a refused repair attempted to change CPU limits'
    refute_contains 'powerprofilesctl set ' "$(<"$LOG")" 'a refused repair changed the platform profile'
    assert_eq "$CPU_BEFORE" "$(file_tree "$SYSFS")" 'a refused repair changed CPU policy controls'
    cmp "$FAKE_ROOT/state.before" "$STATE/last-apply.env"
}

backup_directories() {
    [[ -d "$LIB/backups" ]] || return 0
    find "$LIB/backups" -mindepth 1 -maxdepth 1 -type d -name 'repair-*' | sort
}

assert_backup_contains() {
    local expected="$1" directory="$2" candidate
    while IFS= read -r -d '' candidate; do
        cmp -s "$expected" "$candidate" && return 0
    done < <(find "$directory" -type f -print0)
    printf 'FAIL: no exact backup of %s under %s\n' "$expected" "$directory" >&2
    exit 1
}

assert_repaired_profile() {
    local entry key
    for entry in STAPM_W=60 SLOW_W=65 FAST_W=75 TEMP_C=78 POWER_PROFILE=balanced \
        MIN_FREQ_MHZ=stock MAX_FREQ_MHZ=stock BOOST=on EPP=balance_performance; do
        key="${entry%%=*}"
        assert_eq "${entry#*=}" "$(sed -n "s/^$key=//p" "$PROFILES/balanced-plus.conf")" \
            "repair saved an unexpected $key"
    done
    assert_file_contains 'ryzenadj --stapm-limit=60000 --slow-limit=65000 --fast-limit=75000 --tctl-temp=78' \
        "$LOG" 'repair did not apply the requested gaming baseline'
    assert_eq '1200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" 'repair did not restore the stock minimum'
    assert_eq '5460000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" 'repair did not restore the stock maximum'
    assert_eq '1' "$(<"$SYSFS/cpufreq/boost")" 'repair did not enable CPU boost'
    assert_eq 'balance_performance' "$(<"$SYSFS/cpufreq/policy0/energy_performance_preference")" \
        'repair did not restore the performance EPP'
    assert_file_contains 'RESULT=ok' "$STATE/last-apply.env" 'a successful repair was not recorded'
}

case_apply_preflight_rejects_a_broken_compatible_module() {
    local version
    fake_add_smu_interface
    rm "$SMU_SYSFS_DIR/pm_table"
    capture_originals
    for version in 0.1.7 0.1.8; do
        printf '%s\n' "$version" > "$SMU_SYSFS_DIR/drv_version"
        assert_fails 'ordinary apply accepted a known unusable SMU backend' run_cli apply balanced-plus
        assert_eq '' "$(<"$LOG")" 'backend preflight ran a hardware or module helper'
        assert_no_apply_attempt
    done
}

case_apply_runtime_failure_records_partial_state() {
    LEGION_TEST_ENV+=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=78)
    assert_fails 'a failed RyzenAdj command was reported as successful' run_cli apply quiet
    assert_file_contains 'ryzenadj ' "$LOG" 'the runtime-failure scenario did not reach RyzenAdj'
    assert_file_contains 'PROFILE=quiet' "$STATE/last-apply.env" 'the failed apply retained the previous profile name'
    assert_file_contains 'STAPM_W=45' "$STATE/last-apply.env" 'the failed apply retained the previous limits'
    assert_file_contains 'RESULT=partial' "$STATE/last-apply.env" 'a failed apply left the previous successful state'
}

case_repair_dry_run_has_no_side_effects() {
    prepare_broken_repair
    local helper before output
    for helper in ryzenadj powerprofilesctl systemctl; do
        cat > "$FAKEBIN/$helper" <<'EOF_FORBIDDEN_HELPER'
#!/usr/bin/env bash
printf '%s %s\n' "${0##*/}" "$*" >> "${LEGION_TEST_LOG:?}"
exit 99
EOF_FORBIDDEN_HELPER
    done
    before="$(file_tree "$FAKE_ROOT")"
    output="$(run_cli repair balanced-plus --dry-run 2>&1)"
    assert_contains '60/65/75' "$output" 'dry-run did not name the recovery baseline'
    assert_contains '78' "$output" 'dry-run did not name the temperature ceiling'
    assert_eq '' "$(<"$LOG")" 'dry-run invoked a privileged helper'
    assert_eq "$before" "$(file_tree "$FAKE_ROOT")" 'dry-run changed the fake machine or created backups'
}

case_repair_applies_then_saves_with_exact_unique_backups() {
    prepare_broken_repair
    local -a backups=()
    run_cli repair balanced-plus >/dev/null
    assert_repaired_profile
    assert_eq '1' "$(grep -c '^modprobe -r ryzen_smu$' "$LOG")" 'repair did not unload the broken module exactly once'
    assert_eq 'modprobe -r ryzen_smu' "$(head -n1 "$LOG")" 'repair changed limits before unloading the broken module'
    [[ ! -e "$SMU_SYSFS_DIR" && ! -e "$MODULES/ryzen_smu" ]] || {
        printf 'FAIL: repair reported success with the broken interface still loaded\n' >&2
        exit 1
    }
    [[ ! -e "$REPAIR_MODULES_LOAD_CONF" ]] || { printf 'FAIL: owned boot entry survived recovery\n' >&2; exit 1; }
    assert_file_contains 'blacklist ryzen_smu' "$REPAIR_BLACKLIST_FILE" 'successful fallback was not persisted'
    mapfile -t backups < <(backup_directories)
    assert_eq '1' "${#backups[@]}" 'repair did not create one backup directory'
    assert_backup_contains "$FAKE_ROOT/profile.before" "${backups[0]}"
    assert_backup_contains "$FAKE_ROOT/modules.before" "${backups[0]}"
    cp "$PROFILES/balanced-plus.conf" "$FAKE_ROOT/profile.repaired"
    run_cli repair balanced-plus >/dev/null
    mapfile -t backups < <(backup_directories)
    assert_eq '2' "${#backups[@]}" 'a later repair reused its previous backup directory'
    assert_backup_contains "$FAKE_ROOT/profile.before" "$LIB/backups"
    assert_backup_contains "$FAKE_ROOT/modules.before" "$LIB/backups"
    assert_backup_contains "$FAKE_ROOT/profile.repaired" "$LIB/backups"
}

case_repair_refuses_lockdown_that_is_not_confirmed_none() {
    prepare_broken_repair
    local mode
    for mode in integrity confidentiality missing; do
        if [[ "$mode" == missing ]]; then
            rm "$LOCKDOWN"
        else
            printf 'none [%s]\n' "$mode" > "$LOCKDOWN"
        fi
        assert_fails "repair accepted lockdown $mode" run_cli repair balanced-plus
        assert_eq '' "$(<"$LOG")" 'repair unloaded a module without a confirmed usable fallback'
        assert_originals_unchanged
        assert_no_apply_attempt
    done
}

case_repair_requires_dev_mem_before_unloading() {
    prepare_broken_repair
    rm "$DEV_MEM"
    assert_fails 'repair unloaded the module without a /dev/mem fallback' run_cli repair balanced-plus
    assert_eq '' "$(<"$LOG")" 'repair ran a helper without a usable fallback'
    assert_originals_unchanged
    assert_no_apply_attempt
}

case_repair_stops_when_normal_unload_fails() {
    prepare_broken_repair
    LEGION_TEST_ENV+=(LEGION_FAKE_MODPROBE_FAIL=1)
    assert_fails 'repair continued after modprobe refused to unload' run_cli repair balanced-plus
    assert_eq 'modprobe -r ryzen_smu' "$(<"$LOG")" 'repair retried or forced a failed module removal'
    [[ -d "$SMU_SYSFS_DIR" ]] || { printf 'FAIL: refused unload removed the fake interface\n' >&2; exit 1; }
    assert_originals_unchanged
    assert_no_apply_attempt
}

case_repair_checks_the_interface_disappeared() {
    prepare_broken_repair
    LEGION_TEST_ENV+=(LEGION_FAKE_MODPROBE_KEEP_INTERFACE=1)
    assert_fails 'repair applied limits while the incompatible interface remained' run_cli repair balanced-plus
    assert_eq 'modprobe -r ryzen_smu' "$(<"$LOG")" 'repair changed settings after an ineffective unload'
    assert_originals_unchanged
    assert_no_apply_attempt
}

case_failed_repair_apply_preserves_persistent_originals() {
    prepare_broken_repair
    LEGION_TEST_ENV+=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=78)
    assert_fails 'repair persisted a baseline whose apply failed' run_cli repair balanced-plus
    assert_originals_unchanged
    assert_file_contains 'modprobe -r ryzen_smu' "$LOG" 'failure did not occur after module recovery'
    assert_file_contains '--stapm-limit=60000' "$LOG" 'the recovery baseline was never attempted'
    assert_file_contains 'RESULT=partial' "$STATE/last-apply.env" 'repair left the previous successful state after apply failed'
    assert_file_contains 'STAPM_W=60' "$STATE/last-apply.env" 'partial state does not describe the attempted baseline'
    assert_backup_contains "$FAKE_ROOT/profile.before" "$LIB/backups"
    assert_backup_contains "$FAKE_ROOT/modules.before" "$LIB/backups"
}

case_failed_repair_retry_persists_module_recovery() {
    prepare_broken_repair
    LEGION_TEST_ENV+=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=78)
    assert_fails 'the first recovery apply did not fail' run_cli repair balanced-plus
    assert_originals_unchanged
    LEGION_TEST_ENV+=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=)
    run_cli repair balanced-plus >/dev/null
    assert_repaired_profile
    assert_file_contains 'blacklist ryzen_smu' "$REPAIR_BLACKLIST_FILE" 'a successful retry lost the earlier module recovery'
    [[ ! -e "$REPAIR_MODULES_LOAD_CONF" ]] || { printf 'FAIL: retry retained the owned broken-module boot entry\n' >&2; exit 1; }
    assert_eq '1' "$(grep -c '^modprobe -r ryzen_smu$' "$LOG")" 'retry tried to unload the already removed module'
}

check_interrupted_repair() {
    local signal="$1" expected_exit="$2" output rc=0 helper_pid
    prepare_broken_repair
    cat > "$FAKEBIN/ryzenadj-interrupted" <<'EOF_INTERRUPTED'
#!/usr/bin/env bash
set -eu
printf 'ryzenadj %s\n' "$*" >> "${LEGION_TEST_LOG:?}"
printf '%s\n' "$$" > "${LEGION_TEST_HELPER_PID_FILE:?}"
kill -"${LEGION_TEST_APPLY_SIGNAL:?}" "$PPID"
EOF_INTERRUPTED
    chmod +x "$FAKEBIN/ryzenadj-interrupted"
    LEGION_TEST_ENV+=(
        "LEGION_TEST_APPLY_SIGNAL=$signal"
        "LEGION_TEST_HELPER_PID_FILE=$FAKE_ROOT/apply-helper.pid"
    )
    output="$(LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/ryzenadj-interrupted" run_cli repair balanced-plus 2>&1)" || rc=$?
    assert_eq "$expected_exit" "$rc" "repair did not preserve the $signal exit status"
    refute_contains 'applied successfully' "$output" 'interrupted repair reported success'
    assert_originals_unchanged
    assert_file_contains 'PROFILE=balanced-plus' "$STATE/last-apply.env" 'interrupted repair lost its profile name'
    assert_file_contains 'RESULT=partial' "$STATE/last-apply.env" 'interrupted repair left a successful state'
    assert_file_contains 'STAPM_W=60' "$STATE/last-apply.env" 'interrupted repair lost the attempted baseline'
    assert_eq "$CPU_BEFORE" "$(file_tree "$SYSFS")" 'repair continued changing CPU controls after interruption'
    helper_pid="$(<"$FAKE_ROOT/apply-helper.pid")"
    if kill -0 "$helper_pid" 2>/dev/null; then
        printf 'FAIL: interrupted repair left its RyzenAdj helper running\n' >&2
        exit 1
    fi
}

case_sigint_repair_records_partial_state() {
    check_interrupted_repair INT 130
}

case_sigterm_repair_retry_persists_module_recovery() {
    check_interrupted_repair TERM 143
    run_cli repair balanced-plus >/dev/null
    assert_repaired_profile
    assert_file_contains 'blacklist ryzen_smu' "$REPAIR_BLACKLIST_FILE" 'retry after TERM lost the earlier module recovery'
    [[ ! -e "$REPAIR_MODULES_LOAD_CONF" ]] || { printf 'FAIL: retry after TERM retained the broken-module boot entry\n' >&2; exit 1; }
    assert_eq '1' "$(grep -c '^modprobe -r ryzen_smu$' "$LOG")" 'retry after TERM unloaded an absent module'
}

case_unverified_success_is_a_legitimate_repair() {
    prepare_broken_repair
    LEGION_TEST_ENV+=(LEGION_FAKE_RYZENADJ_EMPTY_TABLE=1)
    run_cli repair balanced-plus >/dev/null
    assert_repaired_profile
    assert_file_contains 'VERIFIED=unknown' "$STATE/last-apply.env" 'unavailable readback was reported as verified'
    assert_file_contains 'blacklist ryzen_smu' "$REPAIR_BLACKLIST_FILE" 'an unverified but successful apply lost its recovery configuration'
}

case_healthy_module_is_untouched_by_profile_repair() {
    fake_add_smu_interface
    capture_originals
    local module_before
    module_before="$(file_tree "$SMU_SYSFS_DIR")"
    rm "$LOCKDOWN" "$DEV_MEM"
    run_cli repair balanced-plus >/dev/null
    assert_repaired_profile
    refute_contains 'modprobe' "$(<"$LOG")" 'repair unloaded a healthy module'
    assert_eq "$module_before" "$(file_tree "$SMU_SYSFS_DIR")" 'repair changed a healthy module interface'
    cmp "$FAKE_ROOT/modules.before" "$REPAIR_MODULES_LOAD_CONF"
    [[ ! -e "$REPAIR_BLACKLIST_FILE" ]] || { printf 'FAIL: repair blacklisted a healthy module\n' >&2; exit 1; }
}

case_absent_module_does_not_imply_a_recovery_request() {
    capture_originals
    run_cli repair balanced-plus >/dev/null
    assert_repaired_profile
    refute_contains 'modprobe' "$(<"$LOG")" 'profile repair attempted to unload an absent module'
    cmp "$FAKE_ROOT/modules.before" "$REPAIR_MODULES_LOAD_CONF"
    [[ ! -e "$REPAIR_BLACKLIST_FILE" ]] || { printf 'FAIL: profile repair blacklisted an absent module without prior recovery\n' >&2; exit 1; }
}

case_unrelated_modules_load_content_is_preserved_with_a_warning() {
    prepare_broken_repair
    printf 'kvm_amd\n' >> "$REPAIR_MODULES_LOAD_CONF"
    cp "$REPAIR_MODULES_LOAD_CONF" "$FAKE_ROOT/modules.before"
    local output
    output="$(run_cli repair balanced-plus 2>&1)"
    assert_repaired_profile
    cmp "$FAKE_ROOT/modules.before" "$REPAIR_MODULES_LOAD_CONF"
    assert_contains 'WARNING:' "$output" 'unrelated boot content was preserved without explaining it'
    assert_contains "$REPAIR_MODULES_LOAD_CONF" "$output" 'the warning did not identify the preserved boot configuration'
}

case_repair_rejects_other_profiles_and_unknown_options() {
    capture_originals
    assert_fails 'repair accepted no profile name' run_cli repair
    assert_fails 'repair accepted another named profile' run_cli repair quiet
    assert_fails 'repair accepted two profile names' run_cli repair balanced-plus balanced-plus
    assert_fails 'repair accepted a force option' run_cli repair balanced-plus --force
    assert_eq '' "$(<"$LOG")" 'invalid arguments ran a hardware helper'
    assert_originals_unchanged
    assert_no_apply_attempt
}

assert_incomplete_repair_keeps_originals() {
    assert_fails "$1" run_cli repair balanced-plus
    assert_originals_unchanged
    assert_file_contains 'RESULT=partial' "$STATE/last-apply.env" 'incomplete recovery was recorded as successful'
    assert_file_contains 'STAPM_W=60' "$STATE/last-apply.env" 'partial recovery lost its attempted baseline'
}

case_repair_requires_an_available_boost_control() {
    LEGION_FAKE_BOOST_SHAPE=epp-pre611 setup_repair_fixture
    prepare_broken_repair
    assert_incomplete_repair_keeps_originals 'repair saved its baseline without enabling boost'
}

case_repair_requires_an_available_platform_profile_helper() {
    prepare_broken_repair
    LEGION_TEST_ENV+=("LEGION_POWERCTL_POWERPROFILESCTL_BIN=$FAKEBIN/absent-powerprofilesctl")
    assert_incomplete_repair_keeps_originals 'repair saved its baseline without a platform-profile helper'
}

case_repair_requires_a_successful_platform_profile_change() {
    prepare_broken_repair
    cat > "$FAKEBIN/powerprofilesctl" <<'EOF_FAILED_PPD'
#!/usr/bin/env bash
printf 'powerprofilesctl %s\n' "$*" >> "${LEGION_TEST_LOG:?}"
exit 1
EOF_FAILED_PPD
    assert_incomplete_repair_keeps_originals 'repair saved its baseline after a failed platform-profile change'
    assert_file_contains 'powerprofilesctl set balanced' "$LOG" 'the platform-profile helper was not attempted'
}

case_repair_requires_epp_on_every_policy() {
    fake_add_policy 1 energy_performance_preference= >/dev/null
    prepare_broken_repair
    assert_incomplete_repair_keeps_originals 'repair saved its baseline while one CPU policy lacked EPP'
}

case_repair_requires_frequency_policy_controls() {
    rm -rf "$SYSFS/cpufreq/policy0"
    prepare_broken_repair
    assert_incomplete_repair_keeps_originals 'repair saved stock frequencies without CPUFreq policy controls'
}

case_normal_apply_keeps_optional_policy_behavior() {
    LEGION_FAKE_BOOST_SHAPE=epp-pre611 setup_repair_fixture
    rm "$SYSFS/cpufreq/policy0/energy_performance_preference"
    LEGION_TEST_ENV+=("LEGION_POWERCTL_POWERPROFILESCTL_BIN=$FAKEBIN/absent-powerprofilesctl")
    run_cli apply balanced-plus >/dev/null
    assert_file_contains 'RESULT=ok' "$STATE/last-apply.env" 'normal apply started requiring optional recovery settings'
    assert_file_contains 'BOOST_APPLIED=skipped' "$STATE/last-apply.env" 'normal apply misreported unavailable boost controls'
}

check_module_reappears_during_repair() {
    local module_health="$1"
    prepare_broken_repair
    cp -a "$SMU_SYSFS_DIR" "$FAKE_ROOT/reloaded-smu"
    if [[ "$module_health" == healthy ]]; then
        : > "$FAKE_ROOT/reloaded-smu/pm_table"
    fi
    cat > "$FAKEBIN/ryzenadj-reloads-module" <<'EOF_RELOAD_SMU'
#!/usr/bin/env bash
set -eu
"${LEGION_TEST_ORIGINAL_RYZENADJ:?}" "$@"
for arg in "$@"; do
    if [[ "$arg" == --stapm-limit=* ]]; then
        mkdir -p "${LEGION_POWERCTL_MODULES_ROOT:?}/ryzen_smu"
        cp -a "${LEGION_TEST_RELOADED_SMU:?}" "${LEGION_POWERCTL_SMU_SYSFS_DIR:?}"
        break
    fi
done
EOF_RELOAD_SMU
    chmod +x "$FAKEBIN/ryzenadj-reloads-module"
    LEGION_TEST_ENV+=(
        "LEGION_TEST_ORIGINAL_RYZENADJ=$FAKEBIN/ryzenadj"
        "LEGION_TEST_RELOADED_SMU=$FAKE_ROOT/reloaded-smu"
    )
    LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/ryzenadj-reloads-module" \
        assert_incomplete_repair_keeps_originals "repair persisted fallback after a $module_health module reappeared"
    assert_file_contains '--stapm-limit=60000' "$LOG" 'module reappearance did not occur after applying the recovery limits'
    [[ -d "$SMU_SYSFS_DIR" && -d "$MODULES/ryzen_smu" ]] || {
        printf 'FAIL: the module did not reappear during the recovery apply\n' >&2
        exit 1
    }
    if [[ "$module_health" == healthy ]]; then
        [[ -f "$SMU_SYSFS_DIR/pm_table" ]] || { printf 'FAIL: the returning module was not healthy\n' >&2; exit 1; }
    fi
}

case_repair_refuses_a_broken_module_reappearing_during_apply() {
    check_module_reappears_during_repair broken
}

case_repair_refuses_a_healthy_module_reappearing_during_apply() {
    check_module_reappears_during_repair healthy
}

# shellcheck disable=SC2034
load_installer_routines() {
    local routines="$FAKE_ROOT/installer-functions.sh"
    sed -n '/^[a-z_][a-z0-9_]*() {/,/^}/p' "$ROOT_DIR/install.sh" > "$routines"
    # shellcheck source=/dev/null
    source "$routines"
    RYZEN_SMU_SYSFS_DIR="$SMU_SYSFS_DIR"
    RYZEN_SMU_MODULE_DIR="$MODULES/ryzen_smu"
    RYZEN_SMU_PKG=ryzen_smu-dkms-git
    SMU_BLACKLIST_FILE="$REPAIR_BLACKLIST_FILE"
    INSTALL_RYZEN_SMU=1
    ARCH_FAMILY=0
    SUDO=()
}

# shellcheck disable=SC2317,SC2329
check_installer_unusable_module() {
    local already_loaded="$1"
    (( already_loaded == 0 )) || fake_add_smu_interface
    load_installer_routines
    modprobe() {
        printf 'modprobe %s\n' "$*" >> "$LOG"
        case "$*" in
            ryzen_smu)
                fake_add_smu_interface
                rm "$SMU_SYSFS_DIR/pm_table" ;;
            '-r ryzen_smu') rm -rf -- "$SMU_SYSFS_DIR" "$MODULES/ryzen_smu" ;;
            *) return 99 ;;
        esac
    }
    persist_ryzen_smu() { printf 'persist\n' >> "$LOG"; }
    load_ryzen_smu >/dev/null
    if (( already_loaded )); then
        assert_eq 'modprobe ryzen_smu' "$(<"$LOG")" 'the installer removed or persisted a pre-existing unusable module'
        [[ -d "$SMU_SYSFS_DIR" ]] || { printf 'FAIL: installer removed a pre-existing module\n' >&2; exit 1; }
    else
        assert_eq $'modprobe ryzen_smu\nmodprobe -r ryzen_smu' "$(<"$LOG")" \
            'the installer failed to roll back its own unusable module load'
        [[ ! -e "$SMU_SYSFS_DIR" && ! -e "$MODULES/ryzen_smu" ]] || {
            printf 'FAIL: installer left its unusable module loaded\n' >&2
            exit 1
        }
    fi
}

case_installer_rolls_back_a_new_unusable_module() {
    check_installer_unusable_module 0
}

case_installer_retains_a_pre_existing_unusable_module() {
    check_installer_unusable_module 1
}

# shellcheck disable=SC2317,SC2329
case_installer_respects_the_recovery_blacklist() {
    printf 'blacklist ryzen_smu\n' > "$REPAIR_BLACKLIST_FILE"
    load_installer_routines
    aur_install_ryzen_smu() { printf 'install\n' >> "$LOG"; }
    load_ryzen_smu() { printf 'load\n' >> "$LOG"; }
    local output
    output="$(ensure_ryzen_smu 2>&1)"
    assert_eq '' "$(<"$LOG")" 'the installer attempted to undo module recovery'
    assert_contains "$REPAIR_BLACKLIST_FILE" "$output" 'the installer did not explain the active recovery blacklist'
}

run_case case_apply_preflight_rejects_a_broken_compatible_module \
    'ordinary apply rejects an unusable compatible module before hardware writes'
run_case case_apply_runtime_failure_records_partial_state \
    'a runtime apply failure records partial state'
run_case case_repair_dry_run_has_no_side_effects \
    'repair dry-run creates no files and invokes no privileged helpers'
run_case case_repair_applies_then_saves_with_exact_unique_backups \
    'repair applies its baseline and preserves exact original files in unique backups'
run_case case_repair_refuses_lockdown_that_is_not_confirmed_none \
    'repair refuses restricted or unknown kernel lockdown'
run_case case_repair_requires_dev_mem_before_unloading \
    'repair requires a usable fallback before unloading'
run_case case_repair_stops_when_normal_unload_fails \
    'a refused unload cannot be forced or followed by an apply'
run_case case_repair_checks_the_interface_disappeared \
    'a successful modprobe exit must actually remove the broken interface'
run_case case_failed_repair_apply_preserves_persistent_originals \
    'failed recovery apply leaves persistent settings intact and records partial state'
run_case case_failed_repair_retry_persists_module_recovery \
    'a successful retry persists module recovery after an earlier apply failure'
run_case case_sigint_repair_records_partial_state \
    'SIGINT during recovery leaves partial state and preserves persistent settings'
run_case case_sigterm_repair_retry_persists_module_recovery \
    'a successful retry persists module recovery after SIGTERM'
run_case case_unverified_success_is_a_legitimate_repair \
    'successful recovery can legitimately have unavailable readback'
run_case case_healthy_module_is_untouched_by_profile_repair \
    'repair leaves a healthy module and its boot configuration intact'
run_case case_absent_module_does_not_imply_a_recovery_request \
    'profile repair alone does not blacklist an absent module'
run_case case_unrelated_modules_load_content_is_preserved_with_a_warning \
    'repair preserves unrelated content in an installer-marked boot file'
run_case case_repair_rejects_other_profiles_and_unknown_options \
    'repair accepts only its named profile and supported options'
run_case case_installer_rolls_back_a_new_unusable_module \
    'the installer unloads an unusable module it just loaded'
run_case case_installer_retains_a_pre_existing_unusable_module \
    'the installer preserves a module that was already loaded'
run_case case_installer_respects_the_recovery_blacklist \
    'the installer leaves active module recovery in place'
run_case case_repair_requires_an_available_boost_control \
    'repair refuses to save a baseline with unavailable boost controls'
run_case case_repair_requires_an_available_platform_profile_helper \
    'repair refuses to save a baseline without a platform-profile helper'
run_case case_repair_requires_a_successful_platform_profile_change \
    'repair refuses to save a baseline after a platform-profile change fails'
run_case case_repair_requires_epp_on_every_policy \
    'repair requires its EPP setting on every CPU policy'
run_case case_repair_requires_frequency_policy_controls \
    'repair requires CPUFreq policy controls for stock frequencies'
run_case case_normal_apply_keeps_optional_policy_behavior \
    'normal apply still permits optional policy controls to be unavailable'
run_case case_repair_refuses_a_broken_module_reappearing_during_apply \
    'repair refuses persistence when a broken module reappears during apply'
run_case case_repair_refuses_a_healthy_module_reappearing_during_apply \
    'repair refuses persistence when a healthy module reappears during apply'

if (( ${#FAILED[@]} )); then
    printf '\n%d repair cases failed:\n' "${#FAILED[@]}" >&2
    printf '  %s\n' "${FAILED[@]}" >&2
    exit 1
fi
printf 'All selected repair cases passed.\n'
