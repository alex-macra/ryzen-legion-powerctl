#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

# shellcheck disable=SC1090,SC2030,SC2031,SC2034,SC2317,SC2329

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SUITE_TMP="$(mktemp -d)"
trap 'rm -rf "$SUITE_TMP"' EXIT

# shellcheck source=tests/lib.sh
source "$ROOT_DIR/tests/lib.sh"

CASE_NUMBER=0
FAILED=()
FILTER="${1:-}"

run_case() {
    local fn="$1" description="$2" rc=0
    CASE_NUMBER=$((CASE_NUMBER + 1))
    [[ -z "$FILTER" || "$fn" == *"$FILTER"* ]] || return 0
    printf 'Test B%d: %s\n' "$CASE_NUMBER" "$description"
    set +e
    (
        set -Eeuo pipefail
        FAKE_ROOT_DIR="$SUITE_TMP/case$CASE_NUMBER"
        mkdir -p "$FAKE_ROOT_DIR"
        # shellcheck source=tests/fixtures/make-fake-root.sh
        source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$FAKE_ROOT_DIR"
        "$fn"
    )
    rc=$?
    set -e
    if (( rc != 0 )); then
        printf 'FAILED: Test B%d (%s) exited %d\n\n' "$CASE_NUMBER" "$fn" "$rc" >&2
        FAILED+=("B$CASE_NUMBER $fn")
    fi
}

assert_doctor_line() {
    local status="$1" label="$2" needle="$3" report="$4" message="$5" row
    row="$(grep -E "^(OK|WARN|FAIL) +${label} " <<<"$report" || true)"
    if [[ -z "$row" ]]; then
        printf 'FAIL: %s\nNo %s row at all in:\n%s\n' "$message" "$label" "$report" >&2
        exit 1
    fi
    assert_match "$row" "$status *" "$message (row: $row)"
    assert_contains "$needle" "$row" "$message"
}

case_config_rejects_malformed_and_unknown_and_traversing_values() {
    printf 'ACTIVE_PROFILE\n' > "$ETC/config.conf"
    assert_fails 'a config.conf line with no = was accepted' run_cli list
    assert_contains 'expected KEY=VALUE' "$(run_cli list 2>&1 || true)" \
        'the malformed config line was not named'

    printf 'ACTIVE_PROFIL=quiet\n' > "$ETC/config.conf"
    assert_contains "unknown key 'ACTIVE_PROFIL'" "$(run_cli list 2>&1 || true)" \
        'a misspelled config key was accepted'

    printf 'ACTIVE_PROFILE=../../etc/passwd\n' > "$ETC/config.conf"
    assert_contains 'invalid ACTIVE_PROFILE' "$(run_cli list 2>&1 || true)" \
        'a traversing ACTIVE_PROFILE was accepted'
}

case_the_boot_service_argv_applies_the_active_profile() {
    local exec_start argv
    exec_start="$(sed -n 's/^ExecStart=//p' "$ROOT_DIR/systemd/legion-powerctl.service")"
    assert_contains '/usr/bin/legion-powerctl apply --boot' "$exec_start" \
        'the unit no longer runs apply --boot; this case is testing the wrong argv'
    read -r -a argv <<<"${exec_start#/usr/bin/legion-powerctl }"

    printf 'ACTIVE_PROFILE=quiet\n' > "$ETC/config.conf"
    local out
    out="$(run_cli "${argv[@]}")"
    assert_contains "Boot apply: profile 'quiet'" "$out" \
        'the boot apply did not name the profile it took from the config'
    assert_contains "Profile 'quiet' applied successfully" "$out" \
        'the boot apply did not complete'
    assert_file_contains 'PROFILE=quiet' "$STATE/last-apply.env" \
        'the boot apply recorded a different profile than the active one'
    assert_file_contains 'ryzenadj --stapm-limit=' "$LOG" \
        'the boot apply never reached the hardware'
}

case_an_interrupted_apply_records_a_partial_result() {
    cat > "$FAKEBIN/ryzenadj-interrupted" <<'EOF_FAKE'
#!/usr/bin/env bash
printf 'ryzenadj %s\n' "$*" >> "${LEGION_TEST_LOG:?}"
kill -INT "$PPID"
EOF_FAKE
    chmod +x "$FAKEBIN/ryzenadj-interrupted"

    run_cli configure interrupted --stapm 50 --slow 55 --fast 60 --temp 80 \
        --boost on --min-mhz stock --max-mhz stock --epp power >/dev/null
    printf '0\n' > "$SYSFS/cpufreq/boost"
    printf '2200000\n' > "$SYSFS/cpufreq/policy0/scaling_min_freq"

    local out rc=0
    out="$(LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/ryzenadj-interrupted" \
        run_cli apply interrupted 2>&1)" || rc=$?

    assert_eq '130' "$rc" 'an interrupted apply did not exit 130'
    assert_contains 'partially applied' "$out" \
        'the interrupted run did not say the machine is in a mixed state'
    refute_contains 'applied successfully' "$out" 'the interrupted run reported success'
    assert_file_contains 'RESULT=partial' "$STATE/last-apply.env" \
        'the runtime record still claims the last apply succeeded'
    assert_file_contains 'PROFILE=interrupted' "$STATE/last-apply.env" \
        'the runtime record names a profile other than the interrupted one'
    assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'boost was applied after the interrupt'
    assert_eq '2200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'the frequency range was applied after the interrupt'
}

case_the_dry_run_environment_default_touches_nothing() {
    printf '0\n' > "$SYSFS/cpufreq/boost"
    : > "$LOG"
    local out
    out="$(LEGION_POWERCTL_DRY_RUN=1 run_cli apply balanced-plus)"
    assert_contains 'DRY RUN' "$out" 'LEGION_POWERCTL_DRY_RUN=1 did not make apply a dry run'
    refute_contains 'applied successfully' "$out" 'a dry run claimed the profile was applied'
    assert_eq '' "$(<"$LOG")" 'a dry run invoked a helper binary'
    assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'a dry run wrote to sysfs'
    [[ ! -e "$STATE/last-apply.env" ]] || [[ "$(grep -c 'RESULT=' "$STATE/last-apply.env")" == 1 ]] || \
        assert_eq 'unchanged' 'rewritten' 'a dry run rewrote the runtime record'
}

case_apply_refuses_before_touching_hardware_without_ryzenadj() {
    printf '0\n' > "$SYSFS/cpufreq/boost"
    : > "$LOG"
    local out rc=0
    out="$(LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/no-such-ryzenadj" \
        run_cli apply balanced-plus 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'apply without ryzenadj did not fail'
    assert_contains 'ryzenadj is not installed' "$out" 'apply did not name the missing binary'
    assert_eq '' "$(<"$LOG")" 'apply changed the power profile before finding ryzenadj missing'
}

case_every_cpu_policy_gets_the_frequency_range() {
    fake_add_policy 1 >/dev/null
    fake_add_policy 2 >/dev/null
    run_cli configure ranged --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz 1400 --max-mhz 4000 --boost unchanged --epp unchanged >/dev/null
    run_cli apply ranged >/dev/null

    local policy
    for policy in policy0 policy1 policy2; do
        assert_eq '1400000' "$(<"$SYSFS/cpufreq/$policy/scaling_min_freq")" \
            "$policy did not get the requested minimum"
        assert_eq '4000000' "$(<"$SYSFS/cpufreq/$policy/scaling_max_freq")" \
            "$policy did not get the requested maximum"
    done
}

case_a_policy_that_does_not_advertise_the_epp_is_skipped_not_fatal() {
    fake_add_policy 1 energy_performance_available_preferences='performance balance_performance' \
        energy_performance_preference=performance >/dev/null
    local out
    out="$(run_cli configure epptest --stapm 50 --slow 55 --fast 60 --temp 80 \
        --epp power --min-mhz unchanged --max-mhz unchanged --boost unchanged --apply 2>&1)"
    assert_contains "policy1 does not advertise EPP 'power'; skipped" "$out" \
        'a policy that cannot take the EPP was not reported'
    assert_contains 'AMD P-State EPP: power' "$out" \
        'one odd policy stopped the EPP being applied to the others'
    assert_eq 'power' "$(<"$SYSFS/cpufreq/policy0/energy_performance_preference")" \
        'the policy that does advertise the EPP did not get it'
    assert_eq 'performance' "$(<"$SYSFS/cpufreq/policy1/energy_performance_preference")" \
        'the skipped policy was written to anyway'
}

case_a_machine_with_no_epp_control_is_reported_not_written_to() {
    rm -f "$SYSFS/cpufreq/policy0/energy_performance_preference"
    local out
    out="$(run_cli configure noepp --stapm 50 --slow 55 --fast 60 --temp 80 \
        --epp power --min-mhz unchanged --max-mhz unchanged --boost unchanged --apply 2>&1)"
    assert_contains 'No compatible EPP controls were found' "$out" \
        'a machine with no EPP control was not reported'
    assert_contains 'applied successfully' "$out" \
        'a missing EPP control aborted the whole apply'
    [[ ! -e "$SYSFS/cpufreq/policy0/energy_performance_preference" ]] || \
        assert_eq 'absent' 'created' 'apply created an EPP control where the kernel exposes none'
}

case_the_global_boost_control_wins_and_per_policy_files_are_left_alone() {
    # Real kernels reject a per-policy boost write while global boost is off,
    # so the only sequence that works everywhere is writing the global file
    # and leaving the propagation to the kernel.
    fake_add_policy 1 >/dev/null
    printf '1\n' > "$SYSFS/cpufreq/policy0/boost"
    printf '1\n' > "$SYSFS/cpufreq/policy1/boost"
    mkdir -p "$SYSFS/cpu0/cpufreq"
    printf '1\n' > "$SYSFS/cpu0/cpufreq/boost"

    run_cli configure boostoff --stapm 50 --slow 55 --fast 60 --temp 80 \
        --boost off --min-mhz unchanged --max-mhz unchanged --epp unchanged --apply >/dev/null

    assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'BOOST=off did not write the global control'
    assert_eq '1' "$(<"$SYSFS/cpufreq/policy0/boost")" \
        'policy0/boost was written directly; on a real kernel that write returns EINVAL once global boost is off'
    assert_eq '1' "$(<"$SYSFS/cpufreq/policy1/boost")" \
        'policy1/boost was written directly instead of being left to kernel propagation'
    assert_eq '1' "$(<"$SYSFS/cpu0/cpufreq/boost")" \
        'the per-cpu boost file was written despite the global control existing'
    assert_file_contains 'BOOST_APPLIED=yes' "$STATE/last-apply.env" \
        'the runtime record does not say boost was applied'
}

case_per_policy_boost_is_the_fallback_when_there_is_no_global_file() {
    rm -f "$SYSFS/cpufreq/boost"
    run_cli configure fallback --stapm 50 --slow 55 --fast 60 --temp 80 \
        --boost on --min-mhz unchanged --max-mhz unchanged --epp unchanged --apply >/dev/null
    assert_eq '1' "$(<"$SYSFS/cpufreq/policy0/boost")" \
        'with no global control the per-policy file was not written'
}

case_a_rejected_boost_write_warns_and_the_apply_still_finishes() {
    if (( EUID == 0 )); then
        printf '  (skipped: running as root, where a read-only file cannot refuse a write)\n'
        return 0
    fi
    chmod 0444 "$SYSFS/cpufreq/boost"
    local out rc=0
    out="$(run_cli configure rejected --stapm 50 --slow 55 --fast 60 --temp 80 \
        --boost off --min-mhz stock --max-mhz stock --epp power --apply 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'a rejected boost write aborted the whole apply'
    assert_contains 'rejected writing BOOST' "$out" 'the rejected boost write was not reported'
    assert_contains 'applied successfully' "$out" 'the apply did not finish after the boost rejection'
    assert_eq '5460000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        'the frequency limits never ran after the boost rejection'
    assert_eq 'power' "$(<"$SYSFS/cpufreq/policy0/energy_performance_preference")" \
        'the EPP never ran after the boost rejection'
    assert_file_contains 'RESULT=ok' "$STATE/last-apply.env" \
        'the apply did not record its result'
    assert_file_contains 'BOOST_APPLIED=no' "$STATE/last-apply.env" \
        'the runtime record hides that boost was rejected'
}

case_restore_frequency_survives_a_rejected_boost_write() {
    if (( EUID == 0 )); then
        printf '  (skipped: running as root, where a read-only file cannot refuse a write)\n'
        return 0
    fi
    chmod 0444 "$SYSFS/cpufreq/boost"
    local out rc=0
    out="$(run_cli restore-frequency --boost on 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'restore-frequency died on a rejected boost write'
    assert_contains 'rejected writing BOOST' "$out" 'the rejected boost write was not reported'
    assert_eq '1200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'the frequency restore after the boost failure never ran'
}

case_a_kernel_with_no_boost_control_warns_instead_of_dying() {
    # The original dev machine: amd-pstate-epp before kernel 6.11 exposes no
    # boost files at all.
    LEGION_FAKE_BOOST_SHAPE=epp-pre611 \
        source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$FAKE_ROOT_DIR"
    local out
    out="$(run_cli configure noboost --stapm 50 --slow 55 --fast 60 --temp 80 \
        --boost off --min-mhz unchanged --max-mhz unchanged --epp unchanged --apply 2>&1)"
    assert_contains 'No CPU boost control was exposed' "$out" \
        'a kernel with no boost control was not reported'
    assert_contains 'applied successfully' "$out" \
        'a missing boost control aborted the whole apply'
    assert_file_contains 'BOOST_APPLIED=skipped' "$STATE/last-apply.env" \
        'the runtime record does not say boost was skipped'
}

case_no_cpufreq_policies_at_all_warns_and_continues() {
    rm -rf "$SYSFS/cpufreq/policy0"
    local out
    out="$(run_cli configure nopolicy --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz 1400 --max-mhz 4000 --boost unchanged --epp unchanged --apply 2>&1)"
    assert_contains 'No CPUFreq policy directories found' "$out" \
        'a machine with no CPUFreq policies was not reported'
    assert_contains 'applied successfully' "$out" \
        'a missing CPUFreq policy aborted the whole apply'
}

case_a_policy_missing_its_control_file_is_named_not_created() {
    fake_add_policy 1 scaling_max_freq= >/dev/null
    run_cli configure halfpolicy --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz 1400 --max-mhz 4000 --boost unchanged --epp unchanged >/dev/null
    local out rc=0
    out="$(run_cli apply halfpolicy 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'apply succeeded against a policy with no scaling_max_freq'
    assert_contains 'CPU control file does not exist' "$out" \
        'apply did not name the control file it could not write'
    [[ ! -e "$SYSFS/cpufreq/policy1/scaling_max_freq" ]] || \
        assert_eq 'absent' 'created' 'apply created a control file where the kernel exposes none'
}

case_a_frequency_below_the_hardware_minimum_is_refused() {
    run_cli configure toolow --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz 800 --max-mhz 4000 --boost unchanged --epp unchanged >/dev/null
    local before out rc=0
    before="$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")"
    out="$(run_cli apply toolow 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'a minimum below the hardware floor was accepted'
    assert_contains 'below hardware minimum 1200 MHz' "$out" \
        'the refusal did not name the hardware minimum'
    assert_eq "$before" "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'the refused minimum was written anyway'
}

case_a_frequency_above_the_hardware_maximum_is_refused() {
    run_cli configure toohigh --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz 1400 --max-mhz 6000 --boost unchanged --epp unchanged >/dev/null
    local before out rc=0
    before="$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")"
    out="$(run_cli apply toohigh 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'a maximum above the hardware ceiling was accepted'
    assert_contains 'exceeds hardware maximum 5460 MHz' "$out" \
        'the refusal did not name the hardware maximum'
    assert_eq "$before" "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        'the refused maximum was written anyway'
}

case_a_stock_minimum_above_a_fixed_maximum_is_refused() {
    run_cli configure inverted --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz stock --max-mhz 1000 --boost unchanged --epp unchanged >/dev/null
    local out rc=0
    out="$(run_cli apply inverted 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'a stock minimum above a fixed maximum was accepted'
    assert_contains 'Requested minimum exceeds maximum' "$out" \
        'the inverted range was not named as the reason'
}

case_the_stock_maximum_prefers_the_amd_pstate_ceiling() {
    printf '5900000\n' > "$SYSFS/cpufreq/policy0/amd_pstate_max_freq"
    run_cli configure boosted --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz unchanged --max-mhz stock --boost unchanged --epp unchanged >/dev/null
    run_cli apply boosted >/dev/null
    assert_eq '5900000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        'stock took cpuinfo_max_freq rather than the higher amd_pstate ceiling'
}

case_a_lower_range_is_applied_when_it_does_not_overlap() {
    printf '3000000\n' > "$SYSFS/cpufreq/policy0/scaling_min_freq"
    printf '5000000\n' > "$SYSFS/cpufreq/policy0/scaling_max_freq"
    run_cli configure lower --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz 1400 --max-mhz 2000 --boost unchanged --epp unchanged >/dev/null
    run_cli apply lower >/dev/null
    assert_eq '1400000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'the non-overlapping minimum was not applied'
    assert_eq '2000000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        'the non-overlapping maximum was not applied'
}

case_missing_powerprofilesctl_does_not_stop_the_cpu_limits() {
    : > "$LOG"
    local -a LEGION_TEST_ENV=(LEGION_POWERCTL_POWERPROFILESCTL_BIN="$FAKEBIN/no-such-ppctl")
    local out
    out="$(run_cli apply balanced-plus 2>&1)"
    assert_contains 'powerprofilesctl is unavailable' "$out" \
        'a machine without power-profiles-daemon was not told so'
    assert_contains 'applied successfully' "$out" \
        'a missing powerprofilesctl stopped the CPU limits being applied'
    assert_file_contains 'ryzenadj --stapm-limit=' "$LOG" \
        'RyzenAdj never ran on a machine without powerprofilesctl'
}

case_a_failing_power_profile_switch_does_not_stop_the_cpu_limits() {
    cat > "$FAKEBIN/ppctl-broken" <<'EOF_FAKE'
#!/usr/bin/env bash
[[ "${1:-}" == "get" ]] && { printf 'balanced\n'; exit 0; }
printf 'powerprofilesctl: no such profile\n' >&2
exit 1
EOF_FAKE
    chmod +x "$FAKEBIN/ppctl-broken"
    : > "$LOG"
    local -a LEGION_TEST_ENV=(LEGION_POWERCTL_POWERPROFILESCTL_BIN="$FAKEBIN/ppctl-broken")
    local out
    out="$(run_cli apply balanced-plus 2>&1)"
    assert_contains 'Could not set power profile' "$out" \
        'a failing power-profile switch was swallowed'
    assert_contains 'applied successfully' "$out" \
        'a failing power-profile switch stopped the CPU limits being applied'
    assert_file_contains 'ryzenadj --stapm-limit=' "$LOG" \
        'RyzenAdj never ran after the power-profile switch failed'
}

case_doctor_fails_on_a_non_amd_cpu_and_on_no_smu_backend() {
    printf 'vendor_id\t: GenuineIntel\n' > "$CPUINFO"
    rm -f "$DEV_MEM"
    rm -rf "$SMU_SYSFS_DIR"
    local out rc=0
    out="$(run_cli doctor)" || rc=$?
    assert_eq '1' "$rc" 'doctor passed on an Intel machine with no SMU backend'
    assert_doctor_line FAIL CPU 'GenuineIntel' "$out" 'doctor did not fail on a non-AMD CPU'
    assert_doctor_line FAIL SMU-backend 'neither' "$out" \
        'doctor did not fail with neither SMU backend available'
    assert_contains 'Doctor result: 2 failure(s)' "$out" 'doctor miscounted the failures'

    rm -f "$CPUINFO"
    rc=0
    out="$(run_cli doctor)" || rc=$?
    assert_eq '1' "$rc" 'doctor passed on a machine whose CPU it could not identify'
    assert_doctor_line FAIL CPU 'unknown' "$out" \
        'doctor claimed an AMD processor on a machine with no readable cpuinfo'
}

case_doctor_fails_without_ryzenadj_or_systemctl_and_exits_one() {
    local -a LEGION_TEST_ENV=(LEGION_POWERCTL_SYSTEMCTL_BIN="$FAKEBIN/no-such-systemctl")
    local out rc=0
    out="$(LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/no-such-ryzenadj" run_cli doctor)" || rc=$?
    assert_eq '1' "$rc" 'doctor passed without ryzenadj or systemctl'
    assert_doctor_line FAIL RyzenAdj 'not found' "$out" 'doctor did not fail on a missing ryzenadj'
    assert_doctor_line FAIL systemd 'systemctl not found' "$out" \
        'doctor reported OK for a systemctl that does not exist'
    assert_contains 'Doctor result:' "$out" 'doctor stopped before finishing its report'
}

case_doctor_reports_the_remaining_warning_branches() {
    printf 'none [integrity] confidentiality\n' > "$LOCKDOWN"
    mkdir -p "$MODULES/legion_laptop"
    rm -f "$SYSFS/cpufreq/policy0/scaling_driver"
    printf 'ACER\n' > "$DMI/sys_vendor"
    printf 'Predator\n' > "$DMI/product_name"
    printf 'Predator\n' > "$DMI/product_family"
    printf 'Predator\n' > "$DMI/product_version"

    local -a LEGION_TEST_ENV=(LEGION_POWERCTL_POWERPROFILESCTL_BIN="$FAKEBIN/no-such-ppctl")
    local out
    out="$(run_cli doctor || true)"
    assert_doctor_line WARN Kernel-lockdown 'integrity' "$out" \
        'doctor did not warn about kernel lockdown'
    assert_contains 'legion_laptop (LenovoLegionLinux) is loaded' "$out" \
        'doctor did not warn about the legion_laptop module'
    assert_doctor_line WARN CPUFreq 'driver unavailable' "$out" \
        'doctor did not warn about a missing CPUFreq driver'
    assert_doctor_line WARN powerprofilesctl 'not installed' "$out" \
        'doctor reported OK for a powerprofilesctl that does not exist'
    assert_doctor_line WARN System 'Not identified as a Lenovo Legion' "$out" \
        'doctor did not warn on a machine that is not a Lenovo at all'
}

case_doctor_reports_a_ready_gui_and_a_missing_polkit_policy() {
    printf '#!/bin/sh\n' > "$FAKEBIN/legion-powerctl-gui"
    cat > "$FAKEBIN/python3-ok" <<'EOF_FAKE'
#!/usr/bin/env bash
exit 0
EOF_FAKE
    chmod +x "$FAKEBIN/legion-powerctl-gui" "$FAKEBIN/python3-ok"

    local out
    out="$(LEGION_POWERCTL_GUI_LAUNCHER="$FAKEBIN/legion-powerctl-gui" \
        LEGION_POWERCTL_PYTHON_BIN="$FAKEBIN/python3-ok" \
        LEGION_POWERCTL_POLKIT_POLICY="$FAKE_ROOT/no-such-policy" run_cli doctor || true)"
    assert_doctor_line WARN GUI 'polkit policy is missing' "$out" \
        'doctor did not warn that privileged actions will get a generic prompt'

    out="$(LEGION_POWERCTL_GUI_LAUNCHER="$FAKEBIN/legion-powerctl-gui" \
        LEGION_POWERCTL_PYTHON_BIN="$FAKEBIN/python3-ok" \
        LEGION_POWERCTL_POLKIT_POLICY="$ROOT_DIR/packaging/polkit/io.github.alexmacra.legion-powerctl.policy" \
        run_cli doctor || true)"
    assert_doctor_line OK GUI 'PySide6 and polkit policy present' "$out" \
        'doctor did not report a fully installed GUI'
}

case_a_fresh_machine_reports_itself_without_dying() {
    rm -f "$PROFILES"/*.conf "$STATE/last-apply.env"

    local list_out
    list_out="$(run_cli list 2>&1)"
    assert_contains 'No profiles found' "$list_out" 'list did not report an empty profiles directory'

    local json
    json="$(run_cli status --json)"
    assert_contains '"profiles":[]' "$json" 'an empty profiles directory did not produce an empty array'
    assert_contains '"last_apply":null' "$json" 'a machine with no runtime record did not emit null'

    local text rc=0
    text="$(run_cli status)" || rc=$?
    assert_eq '0' "$rc" 'status exited nonzero on a machine whose active profile is missing'
    assert_contains 'No valid active profile' "$text" 'status did not say why it could not show a profile'
    assert_contains 'no runtime record' "$text" 'status did not report the missing runtime record'
}

case_waybar_still_emits_an_object_for_an_invalid_active_profile() {
    printf 'not a profile\n' > "$PROFILES/balanced-plus.conf"
    local out
    out="$(run_cli status --waybar)"
    assert_match "$out" '{*"text":*"alt":*"class":*"tooltip":*}' \
        'the waybar fallback stopped being a JSON object when the active profile broke'
    assert_contains '"alt":"balanced-plus"' "$out" \
        'the waybar fallback dropped the profile name'
}

case_profile_names_that_are_paths_or_flags_are_refused() {
    local name out rc
    for name in '../../etc/passwd' 'a b' '.hidden' '' 'has/slash'; do
        rc=0
        out="$(run_cli configure "$name" --stapm 50 2>&1)" || rc=$?
        assert_eq '1' "$rc" "the profile name '$name' was accepted"
        assert_contains 'Invalid profile name' "$out" \
            "the profile name '$name' was refused for some other reason than being invalid"
    done
    assert_eq '' "$(find "$FAKE_ROOT" -name '*.conf' -newer "$ETC/config.conf" -print 2>/dev/null)" \
        'a refused profile name still created a file'

    assert_fails 'a profile name starting with a dash was accepted' \
        run_cli configure -dashed --stapm 50
}

case_the_guardrail_bounds_and_the_unit_name_come_from_the_environment() {
    assert_fails 'a wattage above the default ceiling was accepted' \
        run_cli configure bounded --stapm 250 --slow 255 --fast 260 --temp 80
    local out
    out="$(LEGION_POWERCTL_MAX_POWER_W=300 run_cli configure bounded \
        --stapm 250 --slow 255 --fast 260 --temp 80 2>&1)"
    assert_contains "profile 'bounded'" "$out" 'raising MAX_POWER_W did not raise the guardrail'

    assert_fails 'a temperature below the default floor was accepted' \
        run_cli configure chilly --stapm 50 --slow 55 --fast 60 --temp 40
    out="$(LEGION_POWERCTL_MIN_TEMP_C=30 run_cli configure chilly \
        --stapm 50 --slow 55 --fast 60 --temp 40 2>&1)"
    assert_contains "profile 'chilly'" "$out" 'lowering MIN_TEMP_C did not lower the guardrail'

    : > "$LOG"
    local -a LEGION_TEST_ENV=(LEGION_POWERCTL_SERVICE_NAME=other-name.service)
    run_cli disable >/dev/null
    assert_file_contains 'systemctl disable --now other-name.service' "$LOG" \
        'disable ignored LEGION_POWERCTL_SERVICE_NAME'
}

case_a_value_that_wraps_the_arithmetic_is_refused() {
    local wrapped_temp=18446744073709551698
    local wrapped_watt=18446744073709551661
    local wrapped_mhz=18446744073709554616

    assert_fails 'a temperature that wraps to an in-range value was accepted' \
        run_cli configure wrapped --stapm 45 --slow 50 --fast 60 --temp "$wrapped_temp"
    assert_fails 'a wattage that wraps to an in-range value was accepted' \
        run_cli configure wrapped --stapm "$wrapped_watt" --slow 50 --fast 60 --temp 80
    assert_fails 'a frequency that wraps to an in-range value was accepted' \
        run_cli configure wrapped --stapm 45 --slow 50 --fast 60 --temp 80 \
        --max-mhz "$wrapped_mhz"

    [[ ! -e "$PROFILES/wrapped.conf" ]] || {
        printf 'FAIL: a wrapping value was written to a profile file\n%s\n' \
            "$(cat "$PROFILES/wrapped.conf")" >&2
        exit 1
    }

    local out
    out="$(run_cli configure wrapped --stapm 45 --slow 50 --fast 60 --temp "$wrapped_temp" 2>&1 || true)"
    assert_contains "$wrapped_temp" "$out" 'the refusal did not show the value it refused'
    assert_contains 'TEMP_C' "$out" 'the refusal did not name the field'
}

case_the_privileged_subcommands_refuse_to_run_unprivileged() {
    if (( EUID == 0 )); then
        printf '  (skipped: running as root, where require_root cannot refuse)\n'
        return 0
    fi
    local subcommand argv out rc
    for subcommand in "configure x --stapm 50" "select quiet" "delete quiet" \
                      "apply quiet" "enable" "disable" "restore-frequency"; do
        read -r -a argv <<<"$subcommand"
        rc=0
        out="$(env "${FAKE_ENV[@]}" LEGION_POWERCTL_TESTING=0 \
            LEGION_POWERCTL_RYZENADJ_BIN="$FAKEBIN/ryzenadj" \
            "$FAKE_CLI" "${argv[@]}" 2>&1)" || rc=$?
        assert_eq '1' "$rc" "'$subcommand' did not refuse to run unprivileged"
        assert_contains 'Run it with sudo' "$out" \
            "'$subcommand' refused without telling the user how to proceed"
    done
}

case_the_read_only_subcommands_take_their_defaults_from_the_config() {
    assert_fails 'select accepted a profile that does not exist' run_cli select nonexistent
    assert_contains 'balanced-plus' "$(run_cli show)" 'show with no argument did not use the active profile'
    assert_fails 'delete removed the active profile without --force' run_cli delete balanced-plus
    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    run_cli delete balanced-plus --force >/dev/null
    [[ ! -e "$PROFILES/balanced-plus.conf" ]] || \
        assert_eq 'removed' 'still present' 'delete --force left the active profile in place'
}

case_forced_delete_of_the_boot_profile_moves_boot_to_balanced() {
    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    local out
    out="$(run_cli delete balanced-plus --force 2>&1)"
    assert_contains "boot now uses 'balanced'" "$out" 'the forced delete did not say where boot went'
    assert_file_contains 'ACTIVE_PROFILE=balanced' "$ETC/config.conf" \
        'the forced delete left boot pointing at a deleted profile'
    refute_contains 'balanced-plus' "$(<"$ETC/config.conf")" 'the boot pointer still names the deleted profile'
    run_cli apply --boot >/dev/null 2>&1 || assert_eq 'boot apply passes' 'boot apply fails' \
        'boot is stranded after the forced delete'
}

case_forced_delete_of_the_boot_profile_refuses_without_a_valid_balanced() {
    local out rc=0
    out="$(run_cli delete balanced-plus --force 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'the boot profile was deleted with no balanced to fall back to'
    assert_contains "'balanced' is missing or invalid" "$out" 'the refusal did not say why'
    [[ -e "$PROFILES/balanced-plus.conf" ]] || assert_eq 'kept' 'deleted' 'the refused delete still removed the profile'

    printf 'STAPM_W=banana\n' > "$PROFILES/balanced.conf"
    assert_fails 'an invalid balanced was accepted as the fallback' run_cli delete balanced-plus --force
    assert_file_contains 'ACTIVE_PROFILE=balanced-plus' "$ETC/config.conf" 'a refused delete moved the boot pointer'

    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    printf 'ACTIVE_PROFILE=balanced\n' > "$ETC/config.conf"
    assert_fails 'balanced, the fallback itself, was force-deleted while it is the boot profile' \
        run_cli delete balanced --force
    [[ -e "$PROFILES/balanced.conf" ]] || assert_eq 'kept' 'deleted' 'balanced was deleted while it is the boot profile'
}

case_restore_frequency_honours_every_boost_value() {
    printf '0\n' > "$SYSFS/cpufreq/boost"
    printf '0\n' > "$SYSFS/cpufreq/policy0/boost"
    run_cli restore-frequency --boost on >/dev/null
    assert_eq '1' "$(<"$SYSFS/cpufreq/boost")" 'restore-frequency --boost on did not enable boost'
    assert_eq '0' "$(<"$SYSFS/cpufreq/policy0/boost")" \
        'restore-frequency wrote the per-policy file despite the global control'
    assert_eq '1200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'restore-frequency did not restore the stock minimum'

    printf '0\n' > "$SYSFS/cpufreq/boost"
    run_cli restore-frequency --boost unchanged >/dev/null
    assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'restore-frequency --boost unchanged wrote to the boost control'
}

case_restore_frequency_dry_run_preserves_controls() {
    printf '0\n' > "$SYSFS/cpufreq/boost"
    local before_min before_max before_state out
    before_min="$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")"
    before_max="$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")"
    before_state="$(<"$STATE/last-apply.env")"

    out="$(LEGION_POWERCTL_DRY_RUN=1 run_cli restore-frequency)"
    assert_contains 'DRY RUN' "$out" 'restore-frequency ignored the dry-run environment'
    out="$(run_cli restore-frequency --dry-run)"
    assert_contains 'DRY RUN' "$out" 'restore-frequency rejected --dry-run'
    if (( EUID != 0 )); then
        out="$(env "${FAKE_ENV[@]}" LEGION_POWERCTL_TESTING=0 \
            "$FAKE_CLI" restore-frequency --dry-run)"
        assert_contains 'DRY RUN' "$out" 'unprivileged restore-frequency preview was refused'
    fi
    assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" 'restore-frequency dry run changed boost'
    assert_eq "$before_min" "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'restore-frequency dry run changed minimum frequency'
    assert_eq "$before_max" "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        'restore-frequency dry run changed maximum frequency'
    assert_eq "$before_state" "$(<"$STATE/last-apply.env")" \
        'restore-frequency dry run changed the last apply record'
}

case_power_mutations_refuse_a_concurrent_operation() {
    local lock_fd out rc=0
    exec {lock_fd}> "$STATE/power.lock"
    flock -n "$lock_fd"
    : > "$LOG"

    out="$(exec {lock_fd}>&-; run_cli apply quiet 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'apply did not refuse a concurrent power operation'
    assert_contains 'Another power operation is already running' "$out" \
        'apply did not explain lock contention'
    assert_eq '' "$(<"$LOG")" 'apply invoked a hardware helper before taking the lock'

    rc=0
    out="$(exec {lock_fd}>&-; run_cli restore-frequency 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'restore-frequency did not refuse a concurrent operation'
    assert_eq '2200000' "$(<"$SYSFS/cpufreq/policy0/scaling_min_freq")" \
        'restore-frequency wrote a CPU control before taking the lock'

    rc=0
    out="$(exec {lock_fd}>&-; run_cli baseline --capture 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'baseline capture did not refuse a concurrent operation'
    [[ ! -e "$LIB/stock-limits.env" ]] || \
        assert_eq 'absent' 'created' 'baseline capture wrote while the lock was held'

    flock -u "$lock_fd"
    exec {lock_fd}>&-
    run_cli apply quiet >/dev/null
    assert_file_contains 'PROFILE=quiet' "$STATE/last-apply.env" \
        'apply could not proceed after the other operation ended'
}

case_a_blocked_apply_does_not_move_the_boot_profile() {
    local lock_fd out rc before
    before="$(<"$ETC/config.conf")"
    exec {lock_fd}>> "$STATE/power.lock"
    flock -n "$lock_fd"

    rc=0
    out="$(exec {lock_fd}>&-; run_cli configure blocked --stapm 40 --slow 45 --fast 50 --temp 70 \
        --select --apply 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'configure --select --apply did not refuse a held lock'
    assert_contains 'Another power operation is already running' "$out" \
        'configure did not explain the lock contention'
    assert_eq "$before" "$(<"$ETC/config.conf")" \
        'a blocked configure --select --apply moved the boot profile'

    rc=0
    out="$(exec {lock_fd}>&-; run_cli select quiet --apply 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'select --apply did not refuse a held lock'
    assert_eq "$before" "$(<"$ETC/config.conf")" 'a blocked select --apply moved the boot profile'

    flock -u "$lock_fd"
    exec {lock_fd}>&-
}

case_a_failed_apply_does_not_move_the_boot_profile() {
    local before
    before="$(<"$ETC/config.conf")"
    LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=78)
    assert_fails 'select --apply succeeded with a failing ryzenadj' run_cli select quiet --apply
    assert_eq "$before" "$(<"$ETC/config.conf")" 'a failed select --apply moved the boot profile'

    LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_FAIL_TEMP=77)
    assert_fails 'configure --select --apply succeeded with a failing ryzenadj' \
        run_cli configure failing --stapm 40 --slow 45 --fast 50 --temp 77 --select --apply
    assert_eq "$before" "$(<"$ETC/config.conf")" \
        'a failed configure --select --apply moved the boot profile'

    LEGION_TEST_ENV=()
    run_cli select quiet --apply >/dev/null
    assert_file_contains 'ACTIVE_PROFILE=quiet' "$ETC/config.conf" \
        'a successful select --apply did not move the boot profile'
}

case_select_refuses_an_invalid_profile() {
    local before
    before="$(<"$ETC/config.conf")"
    cat > "$PROFILES/inverted.conf" <<'EOF_PROFILE'
STAPM_W=80
SLOW_W=60
FAST_W=70
TEMP_C=80
EOF_PROFILE
    assert_fails 'an invalid profile was selected' run_cli select inverted
    assert_eq "$before" "$(<"$ETC/config.conf")" 'select wrote an invalid boot profile'
    assert_fails 'an invalid profile was selected and applied' run_cli select inverted --apply
    assert_eq "$before" "$(<"$ETC/config.conf")" 'select --apply wrote an invalid boot profile'
}

case_a_powerbench_scratch_profile_cannot_become_the_boot_profile() {
    local before out
    before="$(<"$ETC/config.conf")"
    cp "$PROFILES/quiet.conf" "$PROFILES/powerbench-4242.conf"
    out="$(run_cli select powerbench-4242 2>&1 || true)"
    assert_contains 'scratch profile' "$out" 'select did not explain why it refused a scratch profile'
    assert_fails 'select accepted a scratch profile' run_cli select powerbench-4242 --apply
    assert_fails 'configure --select accepted a scratch profile' \
        run_cli configure powerbench-4242 --stapm 40 --select --apply
    assert_eq "$before" "$(<"$ETC/config.conf")" 'a scratch profile became the boot profile'
    out="$(run_cli apply powerbench-4242 2>&1 || true)"
    assert_contains 'only legion-powerbench applies it' "$out" 'apply ran a scratch profile outside powerbench'
    [[ ! -e "$STATE/last-apply.env" ]] || refute_contains 'PROFILE=powerbench-4242' "$(<"$STATE/last-apply.env")" \
        'apply ran a scratch profile outside powerbench'
    run_cli configure powerbench-4242 --stapm 40 --apply >/dev/null
    assert_file_contains 'PROFILE=powerbench-4242' "$STATE/last-apply.env" \
        'powerbench can no longer apply its scratch profile without selecting it'
}

case_a_scratch_boot_pointer_cannot_be_written_and_boots_balanced_loudly() {
    local before out rc=0 report
    before="$(<"$ETC/config.conf")"
    out="$(run_wizard powerbench-77 '52\n58\n64\n79\n\n\n\n\n\ny\nn\n')"
    assert_contains 'scratch profile' "$out" 'the wizard did not refuse a scratch profile name'
    assert_eq "$before" "$(<"$ETC/config.conf")" 'the wizard made a scratch profile the boot profile'
    assert_eq '' "$(ls "$PROFILES"/powerbench-77.conf 2>/dev/null || true)" 'the refused wizard still wrote the scratch profile'

    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    cp "$PROFILES/quiet.conf" "$PROFILES/powerbench-77.conf"
    printf 'ACTIVE_PROFILE=powerbench-77\n' > "$ETC/config.conf"
    out="$(run_cli apply --boot 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'a scratch boot pointer booted silently'
    assert_contains "scratch profile 'powerbench-77'" "$out" 'the boot did not name the scratch pointer'
    assert_file_contains 'PROFILE=balanced' "$STATE/last-apply.env" \
        'a scratch boot pointer left the machine without limits'
    report="$(run_cli doctor 2>&1 || true)"
    assert_doctor_line WARN Profile "scratch profile 'powerbench-77'" "$report" \
        'doctor did not flag the scratch boot pointer'
    rm -f "$PROFILES/balanced.conf"
    report="$(run_cli doctor 2>&1 || true)"
    assert_doctor_line FAIL Profile "scratch profile 'powerbench-77'" "$report" \
        'with balanced missing, doctor no longer named the scratch boot pointer'
}

case_deleting_balanced_while_it_boots_says_why() {
    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    run_cli select balanced >/dev/null
    local out
    out="$(run_cli delete balanced --force 2>&1 || true)"
    assert_contains 'fallback a forced delete switches boot to' "$out" \
        'deleting the booting balanced blamed a missing balanced'
    refute_contains 'missing or invalid' "$out" 'deleting the booting balanced blamed a missing balanced'
    [[ -f "$PROFILES/balanced.conf" ]] || assert_eq 'kept' 'deleted' 'balanced was deleted'
}

case_delete_waits_for_the_power_lock() {
    local lock_fd rc=0 out
    cp "$PROFILES/quiet.conf" "$PROFILES/victim.conf"
    exec {lock_fd}>> "$STATE/power.lock"
    flock -n "$lock_fd"
    out="$(exec {lock_fd}>&-; run_cli delete victim 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'delete ran while another power operation held the lock'
    assert_contains 'Another power operation is already running' "$out" 'delete did not explain the lock'
    [[ -f "$PROFILES/victim.conf" ]] || assert_eq 'kept' 'deleted' 'delete removed a profile under a held lock'
    flock -u "$lock_fd"
    exec {lock_fd}>&-
    run_cli delete victim >/dev/null
    [[ ! -e "$PROFILES/victim.conf" ]] || assert_eq 'deleted' 'kept' 'delete failed once the lock was free'
}

case_select_never_points_boot_at_a_profile_deleted_during_its_apply() {
    local before rc=0 out
    cp "$PROFILES/quiet.conf" "$PROFILES/vanishing.conf"
    before="$(<"$ETC/config.conf")"
    cat > "$FAKEBIN/ryzenadj-deleting" <<EOF_FAKE
#!/usr/bin/env bash
rm -f "$PROFILES/vanishing.conf"
exec "$FAKEBIN/ryzenadj" "\$@"
EOF_FAKE
    chmod +x "$FAKEBIN/ryzenadj-deleting"
    out="$(LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/ryzenadj-deleting" run_cli select vanishing --apply 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'select reported success for a profile that no longer exists'
    assert_contains 'was deleted while this command ran' "$out" 'select did not say why boot was left alone'
    assert_eq "$before" "$(<"$ETC/config.conf")" 'select pointed boot at a deleted profile'

    cp "$PROFILES/quiet.conf" "$PROFILES/vanishing.conf"
    rc=0
    LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/ryzenadj-deleting" run_cli configure vanishing --stapm 40 \
        --select --apply >/dev/null 2>&1 || rc=$?
    assert_eq '1' "$rc" 'configure --select reported success for a profile that no longer exists'
    assert_eq "$before" "$(<"$ETC/config.conf")" 'configure --select pointed boot at a deleted profile'
}

case_per_cpu_boost_through_the_real_symlink_layout_is_written_once() {
    rm -f "$SYSFS/cpufreq/boost"
    [[ -L "$SYSFS/cpu0/cpufreq" ]] || assert_eq 'symlink' 'not' 'the fixture lost the real cpuN/cpufreq symlink'
    local out
    out="$(run_cli configure symboost --stapm 50 --slow 55 --fast 60 --temp 80 \
        --boost on --min-mhz unchanged --max-mhz unchanged --epp unchanged --apply 2>&1)"
    refute_contains 'Refusing to write' "$out" 'a per-policy boost write through cpuN/cpufreq was refused'
    assert_eq '1' "$(<"$SYSFS/cpufreq/policy0/boost")" 'the per-policy boost was not written'
    assert_file_contains 'BOOST_APPLIED=yes' "$STATE/last-apply.env" 'boost was not recorded as applied'
    out="$(run_cli apply symboost --dry-run 2>&1)"
    assert_eq '1' "$(grep -c 'DRY RUN: write 1 to .*boost' <<<"$out")" \
        'one policy boost file was written twice, once through its cpuN/cpufreq symlink'
}

case_the_power_lock_is_private_and_never_follows_a_symlink() {
    local target="$FAKE_ROOT/victim" fds="$FAKE_ROOT/child-fds"
    run_cli apply quiet >/dev/null
    assert_eq '600' "$(stat -c %a "$STATE/power.lock")" 'the power lock is readable by other users'

    printf 'keep\n' > "$target"
    rm -f "$STATE/power.lock"
    ln -s "$target" "$STATE/power.lock"
    assert_fails 'apply followed a symlinked lock' run_cli apply quiet
    assert_contains 'symlink' "$(run_cli apply quiet 2>&1 || true)" 'the symlinked lock was not named'
    assert_eq 'keep' "$(<"$target")" 'the symlinked lock target was changed'
    assert_eq '644' "$(stat -c %a "$target")" 'the symlinked lock target was chmodded'

    rm -f "$STATE/power.lock"
    cat > "$FAKEBIN/ryzenadj-fds" <<EOF_FAKE
#!/usr/bin/env bash
for fd in /proc/\$\$/fd/*; do readlink "\$fd"; done >> "$fds" 2>/dev/null
[[ "\${1:-}" != --help ]] || printf '%s\n' "\$1" >> "$FAKE_ROOT/help-calls"
exec "$FAKEBIN/ryzenadj" "\$@"
EOF_FAKE
    chmod +x "$FAKEBIN/ryzenadj-fds"
    LEGION_TEST_RYZENADJ_BIN="$FAKEBIN/ryzenadj-fds" run_cli apply quiet >/dev/null
    assert_file_contains "$FAKE_ROOT" "$fds" 'the fd probe recorded nothing'
    refute_contains 'power.lock' "$(<"$fds")" 'ryzenadj inherited the power lock'

    local dir
    : > "$fds"
    for dir in "$FAKE_ROOT/cand-a" "$FAKE_ROOT/cand-b"; do
        mkdir -p "$dir"
        cp "$FAKEBIN/ryzenadj-fds" "$dir/ryzenadj"
    done
    PATH="$FAKE_ROOT/cand-a:$FAKE_ROOT/cand-b:$PATH" LEGION_TEST_RYZENADJ_BIN='' run_cli apply quiet >/dev/null
    [[ "$(grep -c '^--help' "$FAKE_ROOT/help-calls" 2>/dev/null || true)" -ge 2 ]] || \
        assert_eq 'two or more' 'fewer' 'the two candidates were not both asked for their version'
    refute_contains 'power.lock' "$(<"$fds")" 'ryzenadj --help inherited the power lock'
}

case_configure_names_the_flag_it_could_not_parse() {
    local out rc=0
    out="$(run_cli configure flagtest --nope 5 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'configure accepted an unknown flag'
    assert_contains '--nope' "$out" 'configure did not name the flag it rejected'

    out="$(run_cli configure flagtest --stapm 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'configure accepted a flag with no value'
    assert_contains '--stapm' "$out" 'configure did not name the flag that was missing its value'
}

case_the_gui_launcher_refuses_before_it_execs_anything() {
    local launcher="$ROOT_DIR/bin/legion-powerctl-gui" out rc=0

    cat > "$FAKEBIN/python3" <<'EOF_FAKE'
#!/usr/bin/env bash
exit 0
EOF_FAKE
    chmod +x "$FAKEBIN/python3"
    out="$(DISPLAY='' WAYLAND_DISPLAY='' \
        LEGION_POWERCTL_GUI_ROOT="$FAKE_ROOT/no-such-gui-root" \
        PATH="$FAKEBIN:$PATH" bash "$launcher" 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'the launcher started with no GUI package to run'
    assert_contains 'no-such-gui-root' "$out" 'the launcher did not name the root it could not find'

    cat > "$FAKEBIN/python3" <<'EOF_FAKE'
#!/usr/bin/env bash
[[ "$*" == *"import PySide6"* ]] && exit 1
exit 0
EOF_FAKE
    chmod +x "$FAKEBIN/python3"
    rc=0
    out="$(DISPLAY='' WAYLAND_DISPLAY='' \
        PATH="$FAKEBIN:$PATH" bash "$launcher" 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'the launcher started without PySide6'
    assert_contains 'PySide6 is not installed' "$out" \
        'the launcher gave a traceback instead of naming the missing dependency'
}

case_the_launcher_tells_a_graphical_session_and_only_a_graphical_session() {
    local launcher="$ROOT_DIR/bin/legion-powerctl-gui" log="$FAKE_ROOT/notified" tool rc=0

    for tool in kdialog zenity notify-send; do
        cat > "$FAKEBIN/$tool" <<EOF_FAKE
#!/bin/sh
printf '%s\n' "$tool" >> "$log"
EOF_FAKE
        chmod +x "$FAKEBIN/$tool"
    done
    cat > "$FAKEBIN/python3" <<'EOF_FAKE'
#!/usr/bin/env bash
exit 0
EOF_FAKE
    chmod +x "$FAKEBIN/python3"

    : > "$log"
    DISPLAY='' WAYLAND_DISPLAY='' \
        LEGION_POWERCTL_GUI_ROOT="$FAKE_ROOT/no-such-gui-root" \
        PATH="$FAKEBIN:$PATH" bash "$launcher" >/dev/null 2>&1 || rc=$?
    assert_eq '1' "$rc" 'the launcher started with no GUI package to run'
    assert_eq '' "$(cat "$log")" 'the launcher raised a desktop notification with no session'

    rc=0
    DISPLAY=':99' WAYLAND_DISPLAY='' \
        LEGION_POWERCTL_GUI_ROOT="$FAKE_ROOT/no-such-gui-root" \
        PATH="$FAKEBIN:$PATH" bash "$launcher" >/dev/null 2>&1 || rc=$?
    assert_eq '1' "$rc" 'the launcher started with no GUI package to run'
    assert_eq 'kdialog' "$(cat "$log")" 'the launcher failed without telling the session'
}

case_the_installers_parse_their_arguments_before_they_touch_the_system() {
    local script out rc parse_end sudo_line
    for script in install.sh uninstall.sh; do
        sudo_line="$(grep -n 'command -v sudo' "$ROOT_DIR/$script" | head -1 | cut -d: -f1)"
        assert_match "$sudo_line" '[0-9]*' "$script no longer looks for sudo where this case expects"
        if [[ "$script" == "install.sh" ]]; then
            parse_end="$(grep -n '^done$' "$ROOT_DIR/$script" | head -1 | cut -d: -f1)"
        else
            parse_end="$(grep -n 'Usage: ./uninstall.sh' "$ROOT_DIR/$script" | head -1 | cut -d: -f1)"
        fi
        assert_eq 'before' \
            "$( (( parse_end < sudo_line )) && printf 'before' || printf 'after' )" \
            "$script starts using sudo before it has finished parsing its arguments"

        rc=0
        out="$(bash "$ROOT_DIR/$script" --definitely-not-an-option 2>&1)" || rc=$?
        assert_eq '2' "$rc" "$script did not exit 2 on an unknown option"
        assert_contains 'Usage' "$out" "$script rejected an option without printing its usage"
    done

    rc=0
    out="$(bash "$ROOT_DIR/install.sh" --help 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'install.sh --help did not exit 0'
    assert_contains '--no-gui' "$out" 'install.sh --help did not list its options'
    assert_contains 'definitely-not-an-option' \
        "$(bash "$ROOT_DIR/install.sh" --definitely-not-an-option 2>&1 || true)" \
        'install.sh did not name the option it rejected'
}

case_a_shipped_profile_leaves_the_ceiling_and_boost_alone() {
    printf '5900000\n' > "$SYSFS/cpufreq/policy0/amd_pstate_max_freq"
    printf '3200000\n' > "$SYSFS/cpufreq/policy0/scaling_max_freq"
    printf '0\n' > "$SYSFS/cpufreq/boost"
    run_cli apply quiet >/dev/null
    assert_eq '3200000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        "applying 'quiet' raised the frequency ceiling it was asked to cap"
    assert_eq '0' "$(<"$SYSFS/cpufreq/boost")" \
        "applying 'quiet' force-enabled boost"
    # balanced-plus deliberately does the opposite: boost on, stock ceiling.
    run_cli apply balanced-plus >/dev/null
    assert_eq '1' "$(<"$SYSFS/cpufreq/boost")" \
        "applying 'balanced-plus' did not enable boost"
    assert_eq '5900000' "$(<"$SYSFS/cpufreq/policy0/scaling_max_freq")" \
        "applying 'balanced-plus' did not restore the stock ceiling"
}

case_a_profile_that_raises_the_ceiling_says_so() {
    printf '5900000\n' > "$SYSFS/cpufreq/policy0/amd_pstate_max_freq"
    printf '3200000\n' > "$SYSFS/cpufreq/policy0/scaling_max_freq"
    run_cli configure widening --stapm 50 --slow 55 --fast 60 --temp 80 \
        --min-mhz unchanged --max-mhz stock --boost unchanged --epp unchanged >/dev/null
    local output
    output="$(run_cli apply widening 2>&1)"
    assert_contains 'raised the ceiling from 3200 MHz to 5900 MHz' "$output" \
        'raising the frequency ceiling was not reported'
}

case_apply_fails_when_the_limits_do_not_read_back() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_TCTL=95)
    local output rc=0
    output="$(run_cli apply balanced-plus 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'an apply whose limits did not take still exited 0'
    assert_contains 'Tctl wanted 72, reads 95' "$output" \
        'the drift was not named'
    if grep -q 'applied successfully' <<<"$output"; then
        printf 'FAIL: apply claimed success while the limits read back wrong:\n%s\n' "$output" >&2
        exit 1
    fi
    assert_contains 'RESULT=partial' "$(<"$STATE/last-apply.env")" \
        'the runtime record says the apply was complete'
}

case_doctor_reports_limits_that_drifted_from_the_profile() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_TCTL=95)
    local report rc=0
    report="$(run_cli doctor 2>&1)" || rc=$?
    assert_doctor_line FAIL Limits 'Tctl wanted 72, reads 95' "$report" \
        'doctor did not report the limits drifting from the active profile'
    assert_eq '1' "$rc" 'doctor exited 0 with the limits not in force'
}

case_an_unreadable_ryzenadj_table_is_unverified_not_fatal() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_EMPTY_TABLE=1 LEGION_FAKE_RYZENADJ_NO_SMU=1)
    local out rc=0
    out="$(run_cli apply balanced-plus 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'an unverifiable apply exited nonzero'
    assert_contains 'no compatible ryzen_smu kernel module found' "$out" \
        'the ryzenadj stderr about the missing module was swallowed'
    assert_contains 'this apply is unverified' "$out" \
        'an unreadable limits table did not produce the unverified warning'
    assert_contains 'applied successfully' "$out" 'an unverified apply was treated as a failure'
    assert_file_contains 'VERIFIED=unknown' "$STATE/last-apply.env" \
        'the runtime record claims the limits were verified'
}

fresh_boot() {
    rm -f "$STATE/last-apply.env" "$STATE/smu-written" "$RYZENADJ_STATE"
    rm -rf "$LIB"
}

counting_ryzenadj() {
    local calls="$FAKE_ROOT_DIR/ryzenadj-calls"
    : > "$calls"
    {
        printf '#!/usr/bin/env bash\n'
        printf 'printf "%%s\\n" "$*" >> %q\n' "$calls"
        printf 'exec %q "$@"\n' "$FAKEBIN/ryzenadj"
    } > "$FAKE_ROOT_DIR/counting-ryzenadj"
    chmod +x "$FAKE_ROOT_DIR/counting-ryzenadj"
    printf '%s' "$FAKE_ROOT_DIR/counting-ryzenadj"
}

run_wizard() {
    local name="$1" answers="$2"
    shift 2
    {
        printf '#!/usr/bin/env bash\n'
        printf 'exec env'
        printf ' %q' "${FAKE_ENV[@]}" "LEGION_POWERCTL_RYZENADJ_BIN=$FAKEBIN/ryzenadj" "$@"
        printf ' %q wizard %q\n' "$FAKE_CLI" "$name"
    } > "$FAKE_ROOT_DIR/wizard-run.sh"
    chmod +x "$FAKE_ROOT_DIR/wizard-run.sh"
    printf '%b' "$answers" | timeout 30 script -qec "$FAKE_ROOT_DIR/wizard-run.sh" /dev/null 2>&1 || true
}

case_a_partial_readback_is_not_reported_as_confirmed() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_OMIT='slow-limit fast-limit tctl-temp')
    local out rc=0
    out="$(run_cli apply balanced-plus 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'a partly read back apply exited nonzero'
    refute_contains 'RyzenAdj limits confirmed' "$out" \
        'apply said the limits were confirmed when only STAPM was read back'
    assert_contains 'did not read back Slow PPT, Fast PPT, Tctl' "$out" \
        'the limits that were not read back were not named'
    assert_file_contains 'VERIFIED=partial' "$STATE/last-apply.env" \
        'the runtime record does not say the readback was partial'
    assert_contains 'Last successful apply (limits only partly read back):' "$(run_cli status)" \
        'status did not say the readback was partial'

    local report
    report="$(run_cli doctor 2>&1 || true)"
    assert_doctor_line WARN Limits 'did not read back Slow PPT, Fast PPT, Tctl' "$report" \
        'doctor reported partly read back limits as in force'
}

case_a_child_exit_126_or_127_leaves_as_1() {
    local out rc code
    for code in 126 127; do
        local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_SET_RC="$code")
        rc=0
        out="$(run_cli configure partial --stapm 40 --slow 45 --fast 50 --temp 77 --apply 2>&1)" \
            || rc=$?
        assert_eq '1' "$rc" "a ryzenadj exit $code passed through, which pkexec callers read as cancelled"
        assert_contains 'Saved profile' "$out" 'the save before the failed apply was not reported'
    done

    printf '#!/bin/sh\nexit 127\n' > "$FAKEBIN/systemctl-127"
    chmod +x "$FAKEBIN/systemctl-127"
    local -a LEGION_TEST_ENV=(LEGION_POWERCTL_SYSTEMCTL_BIN="$FAKEBIN/systemctl-127")
    rc=0
    run_cli disable >/dev/null 2>&1 || rc=$?
    assert_eq '1' "$rc" 'a systemctl exit 127 passed through disable'
}

case_a_nan_readback_is_unread_not_drift() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NAN='tctl-temp')
    local out rc=0
    out="$(run_cli apply balanced-plus 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'a nan readback failed the apply, so the boot unit would fail every boot'
    refute_contains 'did not take' "$out" 'a nan readback was reported as drift'
    assert_contains 'did not read back Tctl' "$out" 'the nan limit was not named as unread'
    assert_file_contains 'RESULT=ok' "$STATE/last-apply.env" 'a nan readback recorded a partial apply'
    assert_file_contains 'VERIFIED=partial' "$STATE/last-apply.env" \
        'a nan readback was recorded as verified'

    LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NAN='stapm-limit slow-limit fast-limit tctl-temp')
    rc=0
    out="$(run_cli apply balanced-plus 2>&1)" || rc=$?
    assert_eq '0' "$rc" 'an all-nan readback failed the apply'
    assert_file_contains 'VERIFIED=unknown' "$STATE/last-apply.env" \
        'an all-nan readback was recorded as anything but unknown'
}

case_unprivileged_doctor_prints_no_limits_row_when_it_cannot_read_them() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NO_INFO=1)
    local report
    report="$(run_cli doctor 2>&1)"
    refute_contains 'Limits' "$report" \
        'an unprivileged doctor warned about the limits it needs root to read'
    assert_contains 'OK    Profile' "$report" 'the rest of the report did not survive'
}

case_a_partial_or_nan_capture_stores_nothing() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_OMIT='tctl-temp')
    local out
    fresh_boot
    out="$(run_cli baseline --capture 2>&1 || true)"
    assert_contains 'did not return a number for TEMP_C' "$out" 'the missing limit was not named'
    [[ ! -e "$LIB/stock-limits.env" ]] || assert_eq 'absent' 'written' 'a partial baseline was stored'

    LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NAN='slow-limit')
    out="$(run_cli baseline --capture 2>&1 || true)"
    assert_contains 'did not return a number for SLOW_W' "$out" 'the nan limit was not named'
    [[ ! -e "$LIB/stock-limits.env" ]] || assert_eq 'absent' 'written' 'a nan baseline was stored'

    LEGION_TEST_ENV=()
    mkdir -p "$LIB"
    printf '# Firmware SMU limits, captured before the first apply. Do not edit.\n' > "$LIB/stock-limits.env"
    assert_exit 1 'a header-only baseline was shown as recorded' run_cli baseline --show
    assert_contains 'does not hold all four numeric limits' "$(run_cli baseline 2>&1 || true)" \
        'baseline did not say the recorded file is incomplete'
    printf 'STAPM_W=70.000\nSLOW_W=nan\nFAST_W=85.000\nTEMP_C=72.000\n' > "$LIB/stock-limits.env"
    run_cli baseline --capture >/dev/null
    assert_file_contains 'SLOW_W=75.000' "$LIB/stock-limits.env" \
        'an incomplete baseline locked capture out instead of being replaced'
}

case_a_symlinked_stock_limits_file_is_never_read() {
    local target="$FAKE_ROOT_DIR/planted-limits"
    fresh_boot
    mkdir -p "$LIB"
    printf 'STAPM_W=1\nSLOW_W=1\nFAST_W=1\nTEMP_C=1\n' > "$target"
    ln -s "$target" "$LIB/stock-limits.env"
    local out
    out="$(run_cli baseline --show 2>&1 || true)"
    refute_contains 'STAPM_W=1' "$out" 'baseline --show read through a symlink'
    out="$(run_cli baseline --capture 2>&1 || true)"
    assert_contains 'symlink' "$out" 'capture did not refuse the symlinked baseline'
    assert_eq "$(printf 'STAPM_W=1\nSLOW_W=1\nFAST_W=1\nTEMP_C=1')" "$(<"$target")" \
        'capture wrote through the symlink'
}

case_apply_reports_a_failed_capture_once() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_OMIT='tctl-temp')
    local out
    local err="$FAKE_ROOT_DIR/capture-stderr"
    fresh_boot
    out="$(run_cli apply balanced-plus 2>"$err" || true)"
    assert_eq '1' "$(grep -c 'Stock limits not captured' <<<"$out")" \
        'the apply-time capture failure was not reported exactly once'
    refute_contains 'Stock limits' "$(<"$err")" \
        'the apply-time capture failure went to stderr, which the GUI shows as a warning on every boot'
    fresh_boot
    out="$(run_cli baseline --capture 2>&1 >/dev/null || true)"
    assert_contains 'Stock limits not captured' "$out" 'baseline --capture no longer warns when it fails'

    LEGION_TEST_ENV=()
    out="$(run_cli apply balanced-plus 2>&1)"
    refute_contains 'Stock limits' "$out" 'a second apply in the same boot warned about the baseline again'
}

case_baseline_rejects_capture_together_with_show() {
    fresh_boot
    local order out
    for order in '--capture --show' '--show --capture'; do
        local -a argv
        read -r -a argv <<<"$order"
        out="$(run_cli baseline "${argv[@]}" 2>&1 || true)"
        assert_contains 'not both' "$out" "baseline $order did not reject the conflicting flags"
        [[ ! -e "$LIB/stock-limits.env" ]] || assert_eq 'absent' 'written' "baseline $order captured anyway"
    done
}

case_a_killed_apply_still_blocks_the_baseline() {
    fresh_boot
    run_cli configure dev --stapm 55 --slow 60 --fast 70 --temp 80 >/dev/null
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NO_INFO=1 LEGION_FAKE_RYZENADJ_KILL_PARENT=1)
    local rc=0
    run_cli apply dev >/dev/null 2>&1 || rc=$?
    assert_eq '137' "$rc" 'the fake ryzenadj did not SIGKILL the apply'
    [[ ! -e "$STATE/last-apply.env" ]] || assert_eq 'absent' 'present' 'a SIGKILLed apply left a record'
    assert_file_contains 'stapm=55000' "$RYZENADJ_STATE" 'the SMU was not written before the kill'

    LEGION_TEST_ENV=()
    local out
    out="$(run_cli baseline --capture 2>&1 || true)"
    assert_contains 'already applied this boot' "$out" \
        'a capture after a SIGKILLed apply was not refused'
    [[ ! -e "$LIB/stock-limits.env" ]] || {
        printf 'FAIL: the profile limits were stored as the firmware baseline:\n%s\n' \
            "$(<"$LIB/stock-limits.env")" >&2
        exit 1
    }
}

case_the_boot_apply_captures_once_and_cheaply() {
    local calls
    calls="$(counting_ryzenadj)"
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NO_INFO=1)
    fresh_boot
    LEGION_TEST_RYZENADJ_BIN="$calls" run_cli apply --boot >/dev/null 2>&1 || true
    : > "$FAKE_ROOT_DIR/ryzenadj-calls"
    LEGION_TEST_RYZENADJ_BIN="$calls" run_cli apply --boot >/dev/null 2>&1 || true
    assert_eq '1' "$(grep -c '^-i$' "$FAKE_ROOT_DIR/ryzenadj-calls")" \
        'a later apply in the same boot read the SMU again to try a capture it must refuse'

    printf 'another-boot\n' > "$FAKE_ROOT_DIR/boot_id"
    LEGION_TEST_ENV=()
    rm -f "$RYZENADJ_STATE"
    run_cli apply --boot >/dev/null
    assert_file_contains 'STAPM_W=70.000' "$LIB/stock-limits.env" \
        'a marker and record left from an earlier boot in a persistent /run blocked the capture'
}

case_status_labels_the_last_apply_from_its_result() {
    sed -i 's/^RESULT=.*/RESULT=partial/' "$STATE/last-apply.env"
    local out
    out="$(run_cli status)"
    refute_contains 'Last successful apply' "$out" 'status called a partial apply successful'
    assert_contains 'Last apply, INCOMPLETE (RESULT=partial):' "$out" 'status did not label the partial apply'
}

case_restore_frequency_updates_the_runtime_record() {
    sed -i -e 's/^MAX_FREQ_MHZ=.*/MAX_FREQ_MHZ=3000/' -e 's/^BOOST=.*/BOOST=off/' "$STATE/last-apply.env"
    run_cli restore-frequency --boost on >/dev/null 2>&1
    assert_file_contains 'MAX_FREQ_MHZ=stock' "$STATE/last-apply.env" \
        'restore-frequency left the old ceiling in the runtime record'
    assert_file_contains 'BOOST=on' "$STATE/last-apply.env" \
        'restore-frequency left the old boost setting in the runtime record'
    assert_file_contains 'PROFILE=balanced-plus' "$STATE/last-apply.env" \
        'restore-frequency lost the rest of the runtime record'
}

case_duplicate_keys_are_rejected_with_a_line_number() {
    printf 'STAPM_W=50\nSLOW_W=55\nSTAPM_W=60\nFAST_W=70\nTEMP_C=80\n' > "$PROFILES/dup.conf"
    local out
    out="$(run_cli show dup 2>&1 || true)"
    assert_contains "dup.conf:3: duplicate key 'STAPM_W' (first set on line 1)" "$out" \
        'a duplicate profile key was not rejected with its line'
    printf 'ACTIVE_PROFILE=quiet\nACTIVE_PROFILE=balanced-plus\n' > "$ETC/config.conf"
    out="$(run_cli list 2>&1 || true)"
    assert_contains "config.conf:2: duplicate key 'ACTIVE_PROFILE'" "$out" \
        'a duplicate config key was not rejected with its line'
}

case_a_tab_in_a_description_is_named_correctly() {
    local out
    out="$(run_cli configure tabbed --stapm 50 --slow 55 --fast 60 --temp 80 \
        --description $'one\ttwo' 2>&1 || true)"
    assert_contains 'no control characters (tab, newline, carriage return)' "$out" \
        'a tab in DESCRIPTION was blamed on carriage returns'
}

case_an_empty_config_boots_balanced_and_fails_loudly() {
    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    : > "$ETC/config.conf"
    local out rc=0
    out="$(run_cli apply --boot 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'an empty config.conf booted silently'
    assert_contains 'sets no ACTIVE_PROFILE' "$out" 'the boot did not say why it fell back'
    assert_file_contains 'PROFILE=balanced' "$STATE/last-apply.env" \
        'an empty config.conf left the machine without limits'
    local report
    report="$(run_cli doctor 2>&1 || true)"
    assert_doctor_line WARN Profile 'sets no ACTIVE_PROFILE' "$report" \
        'doctor did not flag the empty config.conf'
}

case_the_wizard_rejects_each_bad_answer_where_it_is_given() {
    local out
    out="$(run_wizard wiz '60\n50\n65\n70\n79\n\n\n\n\n\nn\nn\n')"
    assert_contains 'slow cannot be below STAPM' "$out" 'a slow PPT below STAPM was not rejected at its prompt'
    assert_file_contains 'SLOW_W=65' "$PROFILES/wiz.conf" 'the corrected slow PPT was not saved'

    out="$(run_wizard balanced-plus '\n\n\n85\n80\n\n\n\n\n\nn\nn\n')"
    assert_contains 'Use 50-82 C.' "$out" 'balanced-plus took a ceiling above 82 C at its prompt'
    assert_file_contains 'TEMP_C=80' "$PROFILES/balanced-plus.conf" 'the corrected ceiling was not saved'
}

case_the_wizard_selects_only_after_a_successful_apply() {
    local out
    out="$(run_wizard wiz '52\n58\n64\n79\n\n\n\n\n\ny\ny\n' LEGION_FAKE_RYZENADJ_TCTL=95)"
    assert_contains 'did not take' "$out" 'the drifting apply did not fail'
    assert_file_contains 'ACTIVE_PROFILE=balanced-plus' "$ETC/config.conf" \
        'the wizard moved boot to a profile whose apply failed'
    out="$(run_wizard wiz2 '52\n58\n64\n79\n\n\n\n\n\ny\ny\n')"
    assert_file_contains 'ACTIVE_PROFILE=wiz2' "$ETC/config.conf" \
        'the wizard did not select a profile that applied cleanly'
}

case_doctor_reports_the_boost_control_it_found() {
    local out
    out="$(run_cli doctor || true)"
    assert_doctor_line OK Boost-control 'cpufreq/boost' "$out" \
        'doctor did not name the global boost control'

    rm -f "$SYSFS/cpufreq/boost" "$SYSFS"/cpufreq/policy*/boost
    out="$(run_cli doctor || true)"
    assert_doctor_line WARN Boost-control 'no boost control is exposed' "$out" \
        'doctor did not warn that BOOST profiles will be skipped on this kernel'
}

case_balanced_plus_rejects_saving_a_ceiling_above_82() {
    local before
    before="$(<"$PROFILES/balanced-plus.conf")"
    assert_fails 'balanced-plus accepted a saved 83 C ceiling' \
        run_cli configure balanced-plus --temp 83
    assert_eq "$before" "$(<"$PROFILES/balanced-plus.conf")" \
        'a rejected ceiling changed the saved balanced-plus profile'
    assert_eq '' "$(<"$LOG")" 'a rejected ceiling invoked a hardware helper'
}

case_balanced_plus_rejects_applying_a_hand_edited_high_ceiling() {
    sed -i 's/^TEMP_C=.*/TEMP_C=85/' "$PROFILES/balanced-plus.conf"
    assert_fails 'an edited balanced-plus ceiling above 82 C was applied' \
        run_cli apply balanced-plus
    assert_eq '' "$(<"$LOG")" 'an invalid balanced-plus ceiling reached a hardware helper'
}

case_balanced_plus_can_repair_an_existing_high_ceiling() {
    sed -i 's/^TEMP_C=.*/TEMP_C=90/' "$PROFILES/balanced-plus.conf"
    run_cli configure balanced-plus --temp 82 --apply >/dev/null
    assert_file_contains 'TEMP_C=82' "$PROFILES/balanced-plus.conf" \
        'configure could not correct an existing high balanced-plus ceiling'
    assert_file_contains 'ryzenadj --stapm-limit=70000 --slow-limit=75000 --fast-limit=85000 --tctl-temp=82' \
        "$LOG" 'the corrected balanced-plus profile was not applied at 82 C'
}

case_other_profiles_keep_their_temperature_range() {
    local ceiling
    for ceiling in 85 90; do
        run_cli configure "trial-$ceiling" --temp "$ceiling" --apply >/dev/null
        assert_file_contains "TEMP_C=$ceiling" "$PROFILES/trial-$ceiling.conf" \
            'the balanced-plus cap restricted another profile'
        assert_file_contains "--tctl-temp=$ceiling" "$LOG" \
            'another profile could not apply its requested ceiling'
    done
}

case_doctor_folds_the_ryzen_smu_module_state_into_the_smu_backend_check() {
    mkdir -p "$MODULES/ryzen_smu"
    local out
    out="$(run_cli doctor || true)"
    assert_doctor_line WARN SMU-backend 'is loaded but' "$out" \
        'doctor did not flag a loaded module whose sysfs interface is absent'

    rm -rf "${MODULES:?}/ryzen_smu"
    out="$(run_cli doctor || true)"
    assert_doctor_line WARN SMU-backend 'no ryzen_smu module' "$out" \
        'the not-loaded branch lost its distinct wording'
    assert_contains 'install ryzen_smu-dkms-git' "$out" \
        'the not-loaded branch lost its fix instruction'

    fake_add_smu_interface
    out="$(run_cli doctor || true)"
    assert_doctor_line OK SMU-backend "$SMU_SYSFS_DIR" "$out" \
        'doctor did not detect an available command interface and PM table'
    refute_contains '/dev/ryzen_smu_drv' "$out" 'doctor still expects a nonexistent SMU device node'

    rm "$SMU_SYSFS_DIR/pm_table"
    printf 'none [integrity] confidentiality\n' > "$LOCKDOWN"
    out="$(run_cli doctor || true)"
    assert_doctor_line FAIL SMU-backend 'pm_table' "$out" \
        'a compatible module missing its PM table was not flagged as unable to initialize'
    assert_doctor_line FAIL SMU-backend 'cannot initialize' "$out" \
        'the missing PM table was described as a readback-only problem'
    assert_doctor_line WARN Kernel-lockdown 'integrity' "$out" \
        'lockdown was reported safe despite the unusable module backend'
    assert_doctor_line WARN Kernel-lockdown 'SMU-backend' "$out" \
        'lockdown did not point to the already loaded module problem'
    refute_contains 'install ryzen_smu-dkms-git' \
        "$(grep -E '^WARN[[:space:]]+Kernel-lockdown' <<< "$out")" \
        'lockdown suggested reinstalling an already loaded incompatible module'

    printf '0.1.6\n' > "$SMU_SYSFS_DIR/drv_version"
    out="$(run_cli doctor || true)"
    assert_doctor_line WARN SMU-backend 'driver 0.1.6' "$out" \
        'an incompatible module version was reported as a usable backend'

    rm -f "$LOCKDOWN"

    if grep -qE '^(OK|WARN|FAIL) +ryzen_smu ' <<<"$out"; then
        printf 'FAIL: the standalone ryzen_smu row is back; its states belong to SMU-backend now:\n%s\n' "$out" >&2
        exit 1
    fi
}

load_installer_smu_routines() {
    local routine_file="$FAKE_ROOT/installer-functions.sh"
    sed -n '/^[a-z_][a-z0-9_]*() {/,/^}/p' "$ROOT_DIR/install.sh" > "$routine_file"
    [[ -s "$routine_file" ]] || { printf 'FAIL: could not isolate the installer SMU check\n' >&2; exit 1; }
    source "$routine_file"
}

case_existing_smu_interface_is_persisted_only_when_usable() {
    fake_add_smu_interface
    local called_file="$FAKE_ROOT/persisted"

    (
        load_installer_smu_routines
        INSTALL_RYZEN_SMU=1
        RYZEN_SMU_SYSFS_DIR="$SMU_SYSFS_DIR"
        RYZEN_SMU_PKG=ryzen_smu-dkms-git
        ARCH_FAMILY=0
        SUDO=()
        persist_ryzen_smu() { : > "$called_file"; }
        info() { :; }
        warn() { :; }
        ensure_ryzen_smu
    )
    [[ -e "$called_file" ]] || { printf 'FAIL: explicit --install-ryzen-smu skipped boot persistence for an already loaded module\n' >&2; exit 1; }

    rm -f "$called_file" "$SMU_SYSFS_DIR/pm_table"
    (
        load_installer_smu_routines
        INSTALL_RYZEN_SMU=1
        RYZEN_SMU_SYSFS_DIR="$SMU_SYSFS_DIR"
        RYZEN_SMU_PKG=ryzen_smu-dkms-git
        ARCH_FAMILY=0
        SUDO=()
        persist_ryzen_smu() { : > "$called_file"; }
        info() { :; }
        warn() { :; }
        ensure_ryzen_smu
    )
    [[ ! -e "$called_file" ]] || { printf 'FAIL: installer persisted a module lacking required RyzenAdj files\n' >&2; exit 1; }
}

case_smu_persistence_rejects_an_existing_incompatible_driver() {
    fake_add_smu_interface
    printf '0.1.6\n' > "$SMU_SYSFS_DIR/drv_version"
    local called_file="$FAKE_ROOT/persisted"
    (
        load_installer_smu_routines
        INSTALL_RYZEN_SMU=1
        RYZEN_SMU_SYSFS_DIR="$SMU_SYSFS_DIR"
        RYZEN_SMU_PKG=ryzen_smu-dkms-git
        ARCH_FAMILY=0
        SUDO=()
        persist_ryzen_smu() { : > "$called_file"; }
        info() { :; }
        warn() { :; }
        ensure_ryzen_smu
    )
    [[ ! -e "$called_file" ]] || {
        printf 'FAIL: explicit module install persisted an existing 0.1.6 driver\n' >&2
        exit 1
    }
}

case_smu_persistence_rejects_a_freshly_loaded_incompatible_driver() {
    local called_file="$FAKE_ROOT/persisted" loaded_file="$FAKE_ROOT/loaded"
    (
        load_installer_smu_routines
        INSTALL_RYZEN_SMU=1
        RYZEN_SMU_SYSFS_DIR="$SMU_SYSFS_DIR"
        RYZEN_SMU_PKG=ryzen_smu-dkms-git
        SUDO=()
        modprobe() {
            : > "$loaded_file"
            fake_add_smu_interface
            printf '0.1.6\n' > "$SMU_SYSFS_DIR/drv_version"
        }
        persist_ryzen_smu() { : > "$called_file"; }
        info() { :; }
        warn() { :; }
        load_ryzen_smu
    )
    [[ -e "$loaded_file" ]] || { printf 'FAIL: the fresh-load path did not load the module\n' >&2; exit 1; }
    [[ ! -e "$called_file" ]] || {
        printf 'FAIL: explicit module install persisted a freshly loaded 0.1.6 driver\n' >&2
        exit 1
    }
}

plant_ryzenadj() {
    local dir="$1" marker="$2"
    mkdir -p "$dir"
    printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> %q\nprintf "Version: v9.9.9\\n"\n' "$marker" > "$dir/ryzenadj"
    chmod 0755 "$dir/ryzenadj"
}

untested_env() {
    local entry
    for entry in "${FAKE_ENV[@]}"; do
        [[ "$entry" == LEGION_POWERCTL_TESTING=* || "$entry" == LEGION_POWERCTL_*_BIN=* ]] || \
            printf '%s\n' "$entry"
    done
}

case_doctor_and_status_never_run_a_ryzenadj_planted_on_path() {
    if (( EUID == 0 )); then
        printf '  (skipped: running as root)\n'
        return 0
    fi
    local marker="$FAKE_ROOT/planted.log" out
    local -a production_env=()
    mapfile -t production_env < <(untested_env)
    plant_ryzenadj "$FAKE_ROOT/planted" "$marker"
    out="$(env "${production_env[@]}" PATH="$FAKE_ROOT/planted:$PATH" \
        "$FAKE_CLI" doctor 2>&1 || true)"
    if [[ -e /usr/local/bin/ryzenadj || -e /usr/bin/ryzenadj ]]; then
        refute_contains "$FAKE_ROOT/planted" "$(grep -E '^OK +RyzenAdj ' <<<"$out" || true)" \
            'doctor chose a ryzenadj from PATH'
    else
        assert_doctor_line FAIL RyzenAdj "$FAKE_ROOT/planted/ryzenadj is on PATH, but only a root-owned ryzenadj in /usr/local/bin /usr/bin" \
            "$out" 'doctor said ryzenadj was not found instead of naming the one on PATH it will not run'
    fi
    out="$(env "${production_env[@]}" PATH="$FAKE_ROOT/planted:$PATH" \
        "$FAKE_CLI" status --json 2>&1 || true)"
    refute_contains "$FAKE_ROOT/planted" "$out" 'status --json chose a ryzenadj from PATH'
    env "${production_env[@]}" LEGION_POWERCTL_RYZENADJ_BIN="$FAKE_ROOT/planted/ryzenadj" \
        "$FAKE_CLI" doctor >/dev/null 2>&1 || true
    env "${production_env[@]}" LEGION_POWERCTL_RYZENADJ_BIN="$FAKE_ROOT/planted/ryzenadj" \
        "$FAKE_CLI" status >/dev/null 2>&1 || true
    [[ ! -e "$marker" ]] || {
        printf 'FAIL: doctor or status executed a planted ryzenadj without TESTING:\n%s\n' "$(<"$marker")" >&2
        exit 1
    }

    out="$(PATH="$FAKE_ROOT/planted:$PATH" LEGION_TEST_RYZENADJ_BIN='' run_cli doctor 2>&1 || true)"
    assert_contains "$FAKE_ROOT/planted/ryzenadj" "$out" 'TESTING no longer reaches the fake ryzenadj on PATH'
}

case_root_ignores_testing_and_every_test_override() {
    if ! unshare --map-root-user true >/dev/null 2>&1; then
        printf '  (skipped: no unprivileged user namespace to become root in)\n'
        return 0
    fi
    local marker="$FAKE_ROOT/planted.log" out
    plant_ryzenadj "$FAKE_ROOT/planted" "$marker"
    out="$(unshare --map-root-user env "${FAKE_ENV[@]}" \
        LEGION_POWERCTL_RYZENADJ_BIN="$FAKE_ROOT/planted/ryzenadj" \
        PATH="$FAKE_ROOT/planted:$PATH" "$FAKE_CLI" doctor 2>&1 || true)"
    refute_contains "$FAKE_ROOT" "$(grep -Ev '^(OK|WARN|FAIL) +RyzenAdj ' <<<"$out")" \
        'root honoured a test path or binary override'
    refute_contains "$FAKE_ROOT" "$(grep -E '^OK +RyzenAdj ' <<<"$out" || true)" \
        'root honoured the ryzenadj override'
    [[ ! -e "$marker" ]] || {
        printf 'FAIL: root executed the ryzenadj named by a test override\n' >&2
        exit 1
    }
}

case_root_never_takes_powerprofilesctl_or_systemctl_from_path() {
    if ! unshare --map-root-user true >/dev/null 2>&1; then
        printf '  (skipped: no unprivileged user namespace to become root in)\n'
        return 0
    fi
    local marker="$FAKE_ROOT/planted.log" name command
    local -a production_env=()
    mapfile -t production_env < <(untested_env)
    mkdir -p "$FAKE_ROOT/planted"
    for name in powerprofilesctl systemctl; do
        # shellcheck disable=SC2016
        printf '#!/bin/sh\nprintf "%%s %%s\\n" "$0" "$*" >> %q\n' "$marker" > "$FAKE_ROOT/planted/$name"
        chmod 0755 "$FAKE_ROOT/planted/$name"
    done
    for command in doctor "status --json"; do
        # shellcheck disable=SC2086
        unshare --map-root-user env PATH="$FAKE_ROOT/planted:$PATH" "$FAKE_CLI" $command >/dev/null 2>&1 || true
    done
    [[ ! -e "$marker" ]] || {
        printf 'FAIL: root ran a powerprofilesctl or systemctl found on PATH:\n%s\n' "$(<"$marker")" >&2
        exit 1
    }
    env "${production_env[@]}" PATH="$FAKE_ROOT/planted:$PATH" "$FAKE_CLI" status --json >/dev/null 2>&1 || true
    assert_file_contains "$FAKE_ROOT/planted/" "$marker" 'the planted PATH binaries are not reachable unprivileged'
}

fake_tree_digest() {
    (cd "$FAKE_ROOT" && find etc run var sys -type f -print0 | sort -z | xargs -0 md5sum)
}

case_dry_run_refuses_every_mutation_it_cannot_preview() {
    cp "$ROOT_DIR/profiles/balanced.conf" "$PROFILES/balanced.conf"
    local before command out rc
    local -a argv
    mkdir -p "$LIB"
    before="$(fake_tree_digest)"
    : > "$LOG"
    for command in "configure quiet --stapm 40 --slow 45 --fast 50 --select --apply" \
                   "configure fresh --select" "select quiet --apply" "select quiet" \
                   "delete quiet" "delete balanced-plus --force" "enable --force" "enable" \
                   "disable" "baseline --capture" "wizard quiet"; do
        read -r -a argv <<<"$command"
        rc=0
        out="$(LEGION_POWERCTL_DRY_RUN=1 run_cli "${argv[@]}" 2>&1)" || rc=$?
        assert_eq '1' "$rc" "'$command' did not refuse under LEGION_POWERCTL_DRY_RUN=1"
        assert_contains 'has no dry run' "$out" "'$command' refused without saying why"
    done
    assert_eq '' "$(<"$LOG")" 'a refused dry-run command still ran a helper'
    assert_eq "$before" "$(fake_tree_digest)" \
        'a refused dry-run command still changed a file'

    for command in "apply quiet" "restore-frequency" "repair balanced-plus"; do
        read -r -a argv <<<"$command"
        out="$(LEGION_POWERCTL_DRY_RUN=1 run_cli "${argv[@]}" 2>&1)"
        assert_contains 'DRY RUN' "$out" "'$command' did not preview under LEGION_POWERCTL_DRY_RUN=1"
    done
    assert_eq '' "$(<"$LOG")" 'a previewed command ran a helper'
    assert_eq "$before" "$(fake_tree_digest)" \
        'a previewed command changed a file'
}

case_no_writer_follows_a_planted_symlink() {
    local victim="$FAKE_ROOT/victim" out rc
    printf 'victim\n' > "$victim"
    chmod 0600 "$victim"

    rm -f "$STATE/last-apply.env"
    ln -s "$victim" "$STATE/last-apply.env"
    assert_fails 'apply wrote its record through a symlink' run_cli apply quiet
    assert_eq 'victim' "$(<"$victim")" 'the apply record was written through a symlink'
    rm -f "$STATE/last-apply.env"

    mkdir -p "$LIB"
    : > "$FAKE_ROOT/empty-victim"
    chmod 0600 "$FAKE_ROOT/empty-victim"
    ln -s "$FAKE_ROOT/empty-victim" "$LIB/stock-limits.env"
    run_cli apply quiet >/dev/null 2>&1
    assert_eq '' "$(<"$FAKE_ROOT/empty-victim")" 'the baseline was written through a symlink'
    assert_eq '600' "$(stat -c %a "$FAKE_ROOT/empty-victim")" 'the baseline chmod went through a symlink'
    rm -f "$LIB/stock-limits.env"

    mv "$ETC/config.conf" "$FAKE_ROOT/config.real"
    ln -s "$victim" "$ETC/config.conf"
    assert_fails 'select wrote config.conf through a symlink' run_cli select quiet
    assert_eq 'victim' "$(<"$victim")" 'config.conf was written through a symlink'
    rm -f "$ETC/config.conf"
    mv "$FAKE_ROOT/config.real" "$ETC/config.conf"

    ln -s "$FAKE_ROOT/no-such-target" "$PROFILES/fresh.conf"
    assert_fails 'configure wrote a profile through a symlink' \
        run_cli configure fresh --stapm 40 --slow 45 --fast 50
    [[ ! -e "$FAKE_ROOT/no-such-target" ]] || assert_eq 'absent' 'created' 'a profile was written through a symlink'
    rm -f "$PROFILES/fresh.conf"

    local control
    for control in scaling_min_freq scaling_max_freq energy_performance_preference; do
        cp -p "$SYSFS/cpufreq/policy0/$control" "$FAKE_ROOT/$control.saved"
        rm -f "$SYSFS/cpufreq/policy0/$control"
        ln -s "$victim" "$SYSFS/cpufreq/policy0/$control"
        rc=0
        out="$(run_cli restore-frequency 2>&1 && run_cli apply balanced-plus 2>&1)" || rc=$?
        assert_eq '1' "$rc" "a symlinked $control was accepted"
        assert_contains 'symlink' "$out" "the refusal to write $control did not say why"
        assert_eq 'victim' "$(<"$victim")" "$control was written through a symlink"
        rm -f "$SYSFS/cpufreq/policy0/$control"
        cp -p "$FAKE_ROOT/$control.saved" "$SYSFS/cpufreq/policy0/$control"
    done

    rm -f "$SYSFS/cpufreq/boost"
    ln -s "$victim" "$SYSFS/cpufreq/boost"
    out="$(run_cli restore-frequency --boost on 2>&1)"
    assert_contains 'rejected writing BOOST' "$out" 'a symlinked boost control was not refused'
    assert_eq 'victim' "$(<"$victim")" 'boost was written through a symlink'
}

case_persistent_writes_replace_files_rather_than_truncating_them() {
    local file
    local -a files=("$STATE/last-apply.env" "$ETC/config.conf" "$PROFILES/quiet.conf")
    for file in "${files[@]}"; do
        ln "$file" "$file.hardlink"
        cp "$file" "$file.before"
    done
    run_cli configure quiet --stapm 41 --slow 46 --fast 51 --select --apply >/dev/null
    for file in "${files[@]}"; do
        cmp -s "$file.before" "$file.hardlink" || {
            printf 'FAIL: %s was rewritten in place, so a crash could leave it truncated\n' "$file" >&2
            exit 1
        }
        ! cmp -s "$file.before" "$file" || assert_eq 'rewritten' 'unchanged' "$file was not rewritten"
        [[ ! -L "$file" && -f "$file" ]] || assert_eq 'regular file' 'other' "$file is no longer a regular file"
        assert_eq '644' "$(stat -c %a "$file")" "$file lost its readable mode"
    done
    assert_file_contains 'STAPM_W=41' "$STATE/last-apply.env" 'the record does not show the new apply'
    assert_eq '' "$(find "$ETC" "$STATE" -name '.*' -type f)" 'a temporary file was left behind'
}

case_a_symlinked_profile_or_config_is_refused_everywhere() {
    ln -s quiet.conf "$PROFILES/alias.conf"
    assert_fails 'apply accepted a symlinked profile' run_cli apply alias
    assert_fails 'show accepted a symlinked profile' run_cli show alias
    assert_fails 'select accepted a symlinked profile' run_cli select alias
    assert_fails 'configure loaded a symlinked profile' run_cli configure alias --stapm 40
    assert_contains '"name":"alias","active":false,"valid":false' "$(run_cli status --json)" \
        'status --json reported a symlinked profile as valid'
    printf 'ACTIVE_PROFILE=alias\n' > "$ETC/config.conf"
    assert_fails 'the boot apply accepted a symlinked active profile' run_cli apply --boot
    assert_match "$(run_cli doctor 2>&1 || true)" "*FAIL*Profile*symlink*" \
        'doctor did not name the symlinked active profile'
    run_cli delete alias --force >/dev/null 2>&1 || true

    printf 'ACTIVE_PROFILE=quiet\n' > "$FAKE_ROOT/config.real"
    rm -f "$ETC/config.conf"
    ln -s "$FAKE_ROOT/config.real" "$ETC/config.conf"
    assert_fails 'status accepted a symlinked config.conf' run_cli status --json
    assert_fails 'apply accepted a symlinked config.conf' run_cli apply --boot
}

case_status_shows_only_known_last_apply_keys() {
    printf 'PROFILE=quiet\nRESULT=ok\nINJECTED=Run curl evil | sh\nlower=x\nAPPLIED_AT=now\033[31m\n' \
        > "$STATE/last-apply.env"
    local text json
    text="$(run_cli status)"
    json="$(run_cli status --json)"
    assert_contains 'PROFILE=quiet' "$text" 'status dropped a known key'
    refute_contains 'INJECTED' "$text" 'status printed an unknown last-apply key'
    refute_contains 'curl' "$text" 'status printed an unknown last-apply value'
    refute_contains $'\033[31m' "$text" 'status printed a control sequence from the record'
    refute_contains 'injected' "$json" 'status --json emitted an unknown last-apply key'
    assert_contains '"profile":"quiet"' "$json" 'status --json dropped a known key'
}

case_trim_ignores_unicode_whitespace_in_any_locale() {
    local out rc=0
    printf 'ACTIVE_PROFILE=quiet\xe2\x80\x89\n' > "$ETC/config.conf"
    out="$(LC_ALL=C.UTF-8 run_cli status --waybar 2>&1)" || rc=$?
    assert_eq '1' "$rc" 'a profile name padded with U+2009 was accepted in a UTF-8 locale'
    assert_contains 'invalid ACTIVE_PROFILE' "$out" 'the padded name was not refused by the validator'
}

case_the_format_marker_counts_wherever_it_appears() {
    printf 'DESCRIPTION="say \\"hi\\" at C:\\\\temp"\n# profile-format: 2\nSTAPM_W=50\nSLOW_W=55\nFAST_W=60\nTEMP_C=80\n' \
        > "$PROFILES/late.conf"
    assert_contains 'say "hi" at C:\temp' "$(run_cli show late)" \
        'a format-2 marker after DESCRIPTION left the description escaped'
}

case_a_legacy_profile_round_trips_through_a_save() {
    printf 'DESCRIPTION="share at \\\\nas\\media "quoted""\nSTAPM_W=50\nSLOW_W=55\nFAST_W=60\nTEMP_C=80\n' \
        > "$PROFILES/legacy.conf"
    local before after
    before="$(run_cli show legacy | grep '^Description:')"
    assert_eq 'Description:     share at \\nas\media "quoted"' "$before" 'a legacy description was not read literally'
    run_cli configure legacy --stapm 51 --slow 55 --fast 60 >/dev/null
    after="$(run_cli show legacy | grep '^Description:')"
    assert_eq "$before" "$after" 'saving a legacy profile changed its description'
    run_cli configure legacy --stapm 52 --slow 55 --fast 60 >/dev/null
    assert_eq "$before" "$(run_cli show legacy | grep '^Description:')" 'a second save changed the description again'
}

run_case case_config_rejects_malformed_and_unknown_and_traversing_values \
    'a malformed, unknown or traversing config value is refused'
run_case case_the_boot_service_argv_applies_the_active_profile \
    'the boot service argv applies the active profile'
run_case case_an_interrupted_apply_records_a_partial_result \
    'an interrupted apply records a partial result and exits 130'
run_case case_the_dry_run_environment_default_touches_nothing \
    'LEGION_POWERCTL_DRY_RUN=1 makes apply touch nothing'
run_case case_apply_refuses_before_touching_hardware_without_ryzenadj \
    'apply refuses before touching hardware when ryzenadj is missing'
run_case case_every_cpu_policy_gets_the_frequency_range \
    'every CPU policy gets the frequency range'
run_case case_a_policy_that_does_not_advertise_the_epp_is_skipped_not_fatal \
    'a policy that does not advertise the EPP is skipped, not fatal'
run_case case_a_machine_with_no_epp_control_is_reported_not_written_to \
    'a machine with no EPP control is reported, not written to'
run_case case_the_global_boost_control_wins_and_per_policy_files_are_left_alone \
    'the global boost control wins and per-policy files are left alone'
run_case case_per_policy_boost_is_the_fallback_when_there_is_no_global_file \
    'per-policy boost is the fallback when there is no global file'
run_case case_a_rejected_boost_write_warns_and_the_apply_still_finishes \
    'a rejected boost write warns and the apply still finishes'
run_case case_restore_frequency_survives_a_rejected_boost_write \
    'restore-frequency survives a rejected boost write'
run_case case_a_kernel_with_no_boost_control_warns_instead_of_dying \
    'a kernel with no boost control warns instead of dying'
run_case case_no_cpufreq_policies_at_all_warns_and_continues \
    'no CPUFreq policies at all warns and continues'
run_case case_a_policy_missing_its_control_file_is_named_not_created \
    'a policy missing its control file is named, not created'
run_case case_a_frequency_below_the_hardware_minimum_is_refused \
    'a frequency below the hardware minimum is refused and nothing is written'
run_case case_a_frequency_above_the_hardware_maximum_is_refused \
    'a frequency above the hardware maximum is refused and nothing is written'
run_case case_a_stock_minimum_above_a_fixed_maximum_is_refused \
    'a stock minimum above a fixed maximum is refused'
run_case case_the_stock_maximum_prefers_the_amd_pstate_ceiling \
    'the stock maximum prefers the amd_pstate ceiling'
run_case case_a_lower_range_is_applied_when_it_does_not_overlap \
    'a lower range is applied when it does not overlap the old one'
run_case case_missing_powerprofilesctl_does_not_stop_the_cpu_limits \
    'a missing powerprofilesctl does not stop the CPU limits'
run_case case_a_failing_power_profile_switch_does_not_stop_the_cpu_limits \
    'a failing power-profile switch does not stop the CPU limits'
run_case case_doctor_fails_on_a_non_amd_cpu_and_on_no_smu_backend \
    'doctor fails on a non-AMD CPU and with no SMU backend'
run_case case_doctor_fails_without_ryzenadj_or_systemctl_and_exits_one \
    'doctor fails without ryzenadj or systemctl and still finishes its report'
run_case case_doctor_reports_the_remaining_warning_branches \
    'doctor reports lockdown, legion_laptop, CPUFreq, powerprofilesctl and a non-Lenovo'
run_case case_doctor_reports_a_ready_gui_and_a_missing_polkit_policy \
    'doctor reports a ready GUI and a missing polkit policy'
run_case case_a_fresh_machine_reports_itself_without_dying \
    'a machine with no profiles and no runtime record reports itself without dying'
run_case case_waybar_still_emits_an_object_for_an_invalid_active_profile \
    'waybar still emits an object for an invalid active profile'
run_case case_profile_names_that_are_paths_or_flags_are_refused \
    'profile names that are paths or flags are refused'
run_case case_the_guardrail_bounds_and_the_unit_name_come_from_the_environment \
    'the guardrail bounds and the unit name come from the environment'
run_case case_a_value_that_wraps_the_arithmetic_is_refused \
    'a value that wraps the 64-bit arithmetic is refused rather than tested as its remainder'
run_case case_the_privileged_subcommands_refuse_to_run_unprivileged \
    'the privileged subcommands refuse to run unprivileged'
run_case case_the_read_only_subcommands_take_their_defaults_from_the_config \
    'select, show and delete take their defaults from the config'
run_case case_forced_delete_of_the_boot_profile_moves_boot_to_balanced \
    'a forced delete of the boot profile moves boot to balanced'
run_case case_forced_delete_of_the_boot_profile_refuses_without_a_valid_balanced \
    'a forced delete of the boot profile refuses without a valid balanced'
run_case case_restore_frequency_honours_every_boost_value \
    'restore-frequency honours every boost value'
run_case case_restore_frequency_dry_run_preserves_controls \
    'restore-frequency dry run preserves controls and state'
run_case case_power_mutations_refuse_a_concurrent_operation \
    'power mutations refuse a concurrent operation before writing hardware'
run_case case_configure_names_the_flag_it_could_not_parse \
    'configure names the flag it could not parse'
run_case case_a_blocked_apply_does_not_move_the_boot_profile \
    'a blocked apply does not move the boot profile'
run_case case_a_failed_apply_does_not_move_the_boot_profile \
    'a failed apply does not move the boot profile'
run_case case_select_refuses_an_invalid_profile \
    'select refuses an invalid profile before writing config.conf'
run_case case_a_powerbench_scratch_profile_cannot_become_the_boot_profile \
    'a powerbench scratch profile cannot become the boot profile'
run_case case_a_scratch_boot_pointer_cannot_be_written_and_boots_balanced_loudly \
    'the wizard cannot point boot at a scratch profile, and a stale pointer boots balanced loudly'
run_case case_deleting_balanced_while_it_boots_says_why \
    'deleting balanced while it boots names the real reason'
run_case case_delete_waits_for_the_power_lock \
    'delete refuses while another power operation holds the lock'
run_case case_select_never_points_boot_at_a_profile_deleted_during_its_apply \
    'select and configure re-check the profile under the lock before moving boot'
run_case case_per_cpu_boost_through_the_real_symlink_layout_is_written_once \
    'per-policy boost works through the real cpuN/cpufreq symlink and is written once'
run_case case_the_power_lock_is_private_and_never_follows_a_symlink \
    'the power lock is private, never follows a symlink, and stays out of children'
run_case case_the_gui_launcher_refuses_before_it_execs_anything \
    'the GUI launcher refuses before it execs anything'
run_case case_the_launcher_tells_a_graphical_session_and_only_a_graphical_session \
    'the launcher tells a graphical session it failed, and only a graphical session'
run_case case_the_installers_parse_their_arguments_before_they_touch_the_system \
    'the installers parse their arguments before they touch the system'
run_case case_a_shipped_profile_leaves_the_ceiling_and_boost_alone \
    'a shipped profile leaves the frequency ceiling and boost alone'
run_case case_a_profile_that_raises_the_ceiling_says_so \
    'a profile that raises the ceiling says so'
run_case case_apply_fails_when_the_limits_do_not_read_back \
    'apply fails when the limits do not read back'
run_case case_doctor_reports_limits_that_drifted_from_the_profile \
    'doctor reports limits that drifted from the profile'
run_case case_a_partial_readback_is_not_reported_as_confirmed \
    'a partial readback is not reported as confirmed'
run_case case_a_child_exit_126_or_127_leaves_as_1 \
    'a child exit 126 or 127 leaves as 1'
run_case case_a_nan_readback_is_unread_not_drift \
    'a nan readback is unread not drift'
run_case case_unprivileged_doctor_prints_no_limits_row_when_it_cannot_read_them \
    'unprivileged doctor prints no Limits row when it cannot read them'
run_case case_a_partial_or_nan_capture_stores_nothing \
    'a partial or nan capture stores nothing'
run_case case_a_symlinked_stock_limits_file_is_never_read \
    'a symlinked stock limits file is never read'
run_case case_apply_reports_a_failed_capture_once \
    'apply reports a failed capture once'
run_case case_baseline_rejects_capture_together_with_show \
    'baseline rejects capture together with show'
run_case case_a_killed_apply_still_blocks_the_baseline \
    'a killed apply still blocks the baseline'
run_case case_the_boot_apply_captures_once_and_cheaply \
    'the boot apply captures once and cheaply'
run_case case_status_labels_the_last_apply_from_its_result \
    'status labels the last apply from its result'
run_case case_restore_frequency_updates_the_runtime_record \
    'restore frequency updates the runtime record'
run_case case_duplicate_keys_are_rejected_with_a_line_number \
    'duplicate keys are rejected with a line number'
run_case case_a_tab_in_a_description_is_named_correctly \
    'a tab in a description is named correctly'
run_case case_an_empty_config_boots_balanced_and_fails_loudly \
    'an empty config boots balanced and fails loudly'
run_case case_the_wizard_rejects_each_bad_answer_where_it_is_given \
    'the wizard rejects each bad answer where it is given'
run_case case_the_wizard_selects_only_after_a_successful_apply \
    'the wizard selects only after a successful apply'
run_case case_an_unreadable_ryzenadj_table_is_unverified_not_fatal \
    'an unreadable ryzenadj table is unverified, not fatal'
run_case case_doctor_reports_the_boost_control_it_found \
    'doctor reports the boost control it found'
run_case case_doctor_folds_the_ryzen_smu_module_state_into_the_smu_backend_check \
    'doctor folds the ryzen_smu module state into the SMU-backend check'
run_case case_existing_smu_interface_is_persisted_only_when_usable \
    'explicit module install persists an existing usable module but not an unusable one'
run_case case_smu_persistence_rejects_an_existing_incompatible_driver \
    'explicit module install cannot persist an existing incompatible driver'
run_case case_smu_persistence_rejects_a_freshly_loaded_incompatible_driver \
    'explicit module install cannot persist a freshly loaded incompatible driver'
run_case case_balanced_plus_rejects_saving_a_ceiling_above_82 \
    'balanced-plus cannot save a ceiling above 82 C'
run_case case_balanced_plus_rejects_applying_a_hand_edited_high_ceiling \
    'balanced-plus cannot apply a hand-edited ceiling above 82 C'
run_case case_balanced_plus_can_repair_an_existing_high_ceiling \
    'balanced-plus can correct and apply an existing high ceiling at 82 C'
run_case case_other_profiles_keep_their_temperature_range \
    'other profiles can save and apply 85 C and 90 C ceilings'

run_case case_doctor_and_status_never_run_a_ryzenadj_planted_on_path \
    'doctor and status never run a ryzenadj planted on PATH without TESTING'
run_case case_root_ignores_testing_and_every_test_override \
    'root ignores TESTING and every test override'
run_case case_root_never_takes_powerprofilesctl_or_systemctl_from_path \
    'root never takes powerprofilesctl or systemctl from PATH'
run_case case_dry_run_refuses_every_mutation_it_cannot_preview \
    'LEGION_POWERCTL_DRY_RUN=1 previews or refuses every mutating command'
run_case case_no_writer_follows_a_planted_symlink \
    'no writer follows a planted symlink'
run_case case_persistent_writes_replace_files_rather_than_truncating_them \
    'persistent writes replace files rather than truncating them'
run_case case_a_symlinked_profile_or_config_is_refused_everywhere \
    'a symlinked profile or config.conf is refused everywhere'
run_case case_status_shows_only_known_last_apply_keys \
    'status shows only known last-apply keys'
run_case case_trim_ignores_unicode_whitespace_in_any_locale \
    'trim ignores Unicode whitespace in any locale'
run_case case_the_format_marker_counts_wherever_it_appears \
    'the profile-format marker counts wherever it appears'
run_case case_a_legacy_profile_round_trips_through_a_save \
    'a legacy profile round-trips through a save'

registered="$CASE_NUMBER"
defined="$(declare -F | sed -n 's/^declare -f \(case_.*\)$/\1/p' | wc -l)"
assert_eq "$defined" "$registered" 'a case_* function was defined but never registered'

if (( ${#FAILED[@]} > 0 )); then
    printf '\n%d of %d branch cases failed:\n' "${#FAILED[@]}" "$CASE_NUMBER" >&2
    printf '  %s\n' "${FAILED[@]}" >&2
    exit 1
fi
printf 'All %d branch cases passed.\n' "$CASE_NUMBER"
