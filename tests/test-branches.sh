#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

# shellcheck disable=SC2030,SC2031

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
    rm -f "$DEV_MEM" "$SMU_DEV"
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
    LEGION_POWERCTL_SERVICE_NAME=other-name.service run_cli disable >/dev/null
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
    run_cli delete balanced-plus --force >/dev/null
    [[ ! -e "$PROFILES/balanced-plus.conf" ]] || \
        assert_eq 'removed' 'still present' 'delete --force left the active profile in place'
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
    assert_contains 'Tctl wanted 78, reads 95' "$output" \
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
    assert_doctor_line FAIL Limits 'Tctl wanted 78, reads 95' "$report" \
        'doctor did not report the limits drifting from the active profile'
    assert_eq '1' "$rc" 'doctor exited 0 with the limits not in force'
}

case_doctor_says_nothing_about_limits_it_cannot_read() {
    local -a LEGION_TEST_ENV=(LEGION_FAKE_RYZENADJ_NO_INFO=1)
    local report
    report="$(run_cli doctor 2>&1)"
    if grep -qE '^(OK|WARN|FAIL) +Limits ' <<<"$report"; then
        printf 'FAIL: doctor reported on limits it could not read:\n%s\n' "$report" >&2
        exit 1
    fi
    assert_contains 'OK    Profile' "$report" 'the rest of the report did not survive'
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

case_doctor_distinguishes_a_loaded_ryzen_smu_module_from_its_device_node() {
    mkdir -p "$MODULES/ryzen_smu"
    local out
    out="$(run_cli doctor || true)"
    assert_doctor_line WARN ryzen_smu 'module is loaded but' "$out" \
        'doctor did not flag a loaded module whose device node is absent'

    : > "$SMU_DEV"
    out="$(run_cli doctor || true)"
    if grep -qE '^(OK|WARN|FAIL) +ryzen_smu ' <<<"$out"; then
        printf 'FAIL: doctor reported on ryzen_smu although the device node exists:\n%s\n' "$out" >&2
        exit 1
    fi
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
run_case case_restore_frequency_honours_every_boost_value \
    'restore-frequency honours every boost value'
run_case case_configure_names_the_flag_it_could_not_parse \
    'configure names the flag it could not parse'
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
run_case case_doctor_says_nothing_about_limits_it_cannot_read \
    'doctor says nothing about limits it cannot read'
run_case case_an_unreadable_ryzenadj_table_is_unverified_not_fatal \
    'an unreadable ryzenadj table is unverified, not fatal'
run_case case_doctor_reports_the_boost_control_it_found \
    'doctor reports the boost control it found'
run_case case_doctor_distinguishes_a_loaded_ryzen_smu_module_from_its_device_node \
    'doctor distinguishes a loaded ryzen_smu module from its device node'

registered="$CASE_NUMBER"
defined="$(declare -F | sed -n 's/^declare -f \(case_.*\)$/\1/p' | wc -l)"
assert_eq "$defined" "$registered" 'a case_* function was defined but never registered'

if (( ${#FAILED[@]} > 0 )); then
    printf '\n%d of %d branch cases failed:\n' "${#FAILED[@]}" "$CASE_NUMBER" >&2
    printf '  %s\n' "${FAILED[@]}" >&2
    exit 1
fi
printf 'All %d branch cases passed.\n' "$CASE_NUMBER"
