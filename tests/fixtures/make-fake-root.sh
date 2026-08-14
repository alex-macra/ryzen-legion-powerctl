#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -Eeuo pipefail
fi

FAKE_ROOT="${1:?usage: make-fake-root.sh ROOTDIR}"
FIXTURE_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

ETC="$FAKE_ROOT/etc/legion-powerctl"
PROFILES="$ETC/profiles.d"
STATE="$FAKE_ROOT/run/legion-powerctl"
SYSFS="$FAKE_ROOT/sys/devices/system/cpu"
DMI="$FAKE_ROOT/sys/class/dmi/id"
EFIVARS="$FAKE_ROOT/sys/firmware/efi/efivars"
MODULES="$FAKE_ROOT/sys/module"
FAKEBIN="$FAKE_ROOT/bin"
DEV="$FAKE_ROOT/dev"
CPUINFO="$FAKE_ROOT/cpuinfo"
LOCKDOWN="$FAKE_ROOT/lockdown"
SMU_DEV="$DEV/ryzen_smu_drv"
DEV_MEM="$DEV/mem"
LOG="$FAKE_ROOT/commands.log"
RYZENADJ_STATE="$FAKE_ROOT/ryzenadj-limits"
FAKE_EXTRA_POLICIES="${LEGION_FAKE_EXTRA_POLICIES:-0}"
FAKE_BOOST_SHAPE="${LEGION_FAKE_BOOST_SHAPE:-amd-pstate-611}"

mkdir -p "$PROFILES" "$STATE" "$SYSFS/cpufreq/policy0" "$DMI" "$EFIVARS" "$MODULES" \
    "$FAKEBIN" "$DEV"
: > "$LOG"

cp "$FIXTURE_REPO/profiles/balanced-plus.conf" "$PROFILES/balanced-plus.conf"
cp "$FIXTURE_REPO/profiles/quiet.conf" "$PROFILES/quiet.conf"
cp "$FIXTURE_REPO/config/config.conf" "$ETC/config.conf"
printf 'vendor_id\t: AuthenticAMD\n' > "$CPUINFO"

cat > "$STATE/last-apply.env" <<'EOF_STATE'
PROFILE=balanced-plus
RESULT=ok
VERIFIED=yes
STAPM_W=65
SLOW_W=70
FAST_W=80
TEMP_C=78
POWER_PROFILE=balanced
MIN_FREQ_MHZ=stock
MAX_FREQ_MHZ=stock
BOOST=on
EPP=balance_performance
APPLIED_AT=2026-08-07T09:00:00+03:00
EOF_STATE

printf 'LENOVO\n' > "$DMI/sys_vendor"
printf '83RU\n' > "$DMI/product_name"
printf 'Legion Pro 7 16ARX10\n' > "$DMI/product_family"
printf 'Legion Pro 7 16ARX10\n' > "$DMI/product_version"

printf '1200000\n' > "$SYSFS/cpufreq/policy0/cpuinfo_min_freq"
printf '5460000\n' > "$SYSFS/cpufreq/policy0/cpuinfo_max_freq"
printf '5460000\n' > "$SYSFS/cpufreq/policy0/amd_pstate_max_freq"
printf '2200000\n' > "$SYSFS/cpufreq/policy0/scaling_min_freq"
printf '3200000\n' > "$SYSFS/cpufreq/policy0/scaling_max_freq"
printf 'amd-pstate-epp\n' > "$SYSFS/cpufreq/policy0/scaling_driver"
printf 'balance_performance\n' > "$SYSFS/cpufreq/policy0/energy_performance_preference"
printf 'performance balance_performance balance_power power\n' \
    > "$SYSFS/cpufreq/policy0/energy_performance_available_preferences"
# Boost controls mirror real kernels: the global file and the per-policy
# files appear together (both are gated on the driver's set_boost), so a
# fixture with only one of them models a machine that does not exist.
rm -f "$SYSFS/cpufreq/boost" "$SYSFS/cpufreq/policy0/boost" "$SYSFS/cpufreq/policy0/cpb"
case "$FAKE_BOOST_SHAPE" in
    amd-pstate-611)
        printf '0\n' > "$SYSFS/cpufreq/boost"
        printf '0\n' > "$SYSFS/cpufreq/policy0/boost"
        ;;
    epp-pre611)
        ;;
    acpi-cpufreq)
        printf 'acpi-cpufreq\n' > "$SYSFS/cpufreq/policy0/scaling_driver"
        rm -f "$SYSFS/cpufreq/policy0/energy_performance_preference" \
              "$SYSFS/cpufreq/policy0/energy_performance_available_preferences" \
              "$SYSFS/cpufreq/policy0/amd_pstate_max_freq"
        printf '0\n' > "$SYSFS/cpufreq/boost"
        printf '0\n' > "$SYSFS/cpufreq/policy0/cpb"
        ;;
    *)
        printf 'make-fake-root.sh: unknown LEGION_FAKE_BOOST_SHAPE %s\n' "$FAKE_BOOST_SHAPE" >&2
        exit 1
        ;;
esac

: > "$DEV_MEM"

fake_add_policy() {
    local index="$1"
    local policy="$SYSFS/cpufreq/policy$index" spec control value
    shift
    mkdir -p "$policy"
    cp -a "$SYSFS/cpufreq/policy0/." "$policy/"
    for spec in "$@"; do
        control="${spec%%=*}"
        value="${spec#*=}"
        if [[ -z "$value" ]]; then
            rm -f "$policy/$control"
        else
            printf '%s\n' "$value" > "$policy/$control"
        fi
    done
    printf '%s' "$policy"
}

FAKE_CLI="$FIXTURE_REPO/bin/legion-powerctl"

run_cli() {
    env "${FAKE_ENV[@]}" \
        LEGION_POWERCTL_RYZENADJ_BIN="${LEGION_TEST_RYZENADJ_BIN-$FAKEBIN/ryzenadj}" \
        ${LEGION_TEST_ENV[@]+"${LEGION_TEST_ENV[@]}"} \
        "$FAKE_CLI" "$@"
}

cat > "$FAKEBIN/ryzenadj" <<'EOF_FAKE'
#!/usr/bin/env bash
if [[ -n "${LEGION_FAKE_RYZENADJ_NO_SMU:-}" ]]; then
    printf 'no compatible ryzen_smu kernel module found, fallback to /dev/mem\n' >&2
fi
if [[ "${1:-}" == "--help" || "${1:-}" == "--version" ]]; then
    cat <<EOF_USAGE
Usage: ryzenadj [options]
    --oc-volt=<u32>   Forced Core VID: Must follow this calculation (1.55 - [VID you want to set e.g. 1.25 for 1.25v]) / 0.00625 (Renoir and up Only)

WARNING: Use at your own risk!
By Jiaxun Yang <jiaxun.yang@flygoat.com>, Under LGPL.
Version: v${RYZENADJ_FAKE_VERSION:-0.19.0}
EOF_USAGE
    [[ "${1:-}" == "--version" ]] && { printf 'error: unknown option `--version`\n' >&2; exit 1; }
    exit 0
fi
if [[ "${1:-}" == "-i" || "${1:-}" == "--info" ]]; then
    [[ -n "${LEGION_FAKE_RYZENADJ_NO_INFO:-}" ]] && exit 1
    if [[ -n "${LEGION_FAKE_RYZENADJ_EMPTY_TABLE:-}" ]]; then
        printf 'CPU Family: Fire Range\n'
        printf 'request_table_ver_and_size is not supported on this family\n'
        exit 0
    fi
    state="${LEGION_FAKE_RYZENADJ_STATE:-}"
    stapm=65000 slow=70000 fast=80000 tctl=78
    [[ -n "$state" && -r "$state" ]] && . "$state"
    printf 'CPU Family: Fire Range\n'
    printf '| Name | Value | Parameter |\n'
    printf '| STAPM LIMIT | %d.000 | stapm-limit |\n' "$((stapm / 1000))"
    printf '| PPT LIMIT SLOW | %d.000 | slow-limit |\n' "$((slow / 1000))"
    printf '| PPT LIMIT FAST | %d.000 | fast-limit |\n' "$((fast / 1000))"
    printf '| THM LIMIT CORE | %d.000 | tctl-temp |\n' "${LEGION_FAKE_RYZENADJ_TCTL:-$tctl}"
    exit 0
fi
printf 'ryzenadj %s\n' "$*" >> "${LEGION_TEST_LOG:?}"
if [[ -n "${LEGION_FAKE_RYZENADJ_STATE:-}" ]]; then
    : > "$LEGION_FAKE_RYZENADJ_STATE"
    for arg in "$@"; do
        case "$arg" in
            --stapm-limit=*) printf 'stapm=%s\n' "${arg#*=}" ;;
            --slow-limit=*) printf 'slow=%s\n' "${arg#*=}" ;;
            --fast-limit=*) printf 'fast=%s\n' "${arg#*=}" ;;
            --tctl-temp=*) printf 'tctl=%s\n' "${arg#*=}" ;;
        esac >> "$LEGION_FAKE_RYZENADJ_STATE"
    done
fi
printf 'Successfully set test limits\n'
EOF_FAKE

cat > "$FAKEBIN/powerprofilesctl" <<'EOF_FAKE'
#!/usr/bin/env bash
case "${1:-}" in
    get) printf 'balanced\n' ;;
    set) printf 'powerprofilesctl set %s\n' "${2:-}" >> "${LEGION_TEST_LOG:?}" ;;
    list) printf 'balanced\nperformance\npower-saver\n' ;;
    *) exit 2 ;;
esac
EOF_FAKE

cat > "$FAKEBIN/systemctl" <<'EOF_FAKE'
#!/usr/bin/env bash
case "${1:-}" in
    is-enabled) printf 'enabled\n' ;;
    is-active) printf 'active\n' ;;
    *) printf 'systemctl %s\n' "$*" >> "${LEGION_TEST_LOG:?}" ;;
esac
EOF_FAKE
chmod +x "$FAKEBIN"/*

FAKE_ENV=(
    LEGION_POWERCTL_TESTING=1
    LEGION_POWERCTL_ETC_DIR="$ETC"
    LEGION_POWERCTL_STATE_DIR="$STATE"
    LEGION_POWERCTL_SYSFS_CPU_ROOT="$SYSFS"
    LEGION_POWERCTL_CPUINFO_PATH="$CPUINFO"
    LEGION_POWERCTL_DMI_ROOT="$DMI"
    LEGION_POWERCTL_EFIVARS_DIR="$EFIVARS"
    LEGION_POWERCTL_SMU_DEV="$SMU_DEV"
    LEGION_POWERCTL_DEV_MEM_PATH="$DEV_MEM"
    LEGION_POWERCTL_LOCKDOWN_PATH="$LOCKDOWN"
    LEGION_POWERCTL_MODULES_ROOT="$MODULES"
    LEGION_POWERCTL_RYZENADJ_BIN="$FAKEBIN/ryzenadj"
    LEGION_POWERCTL_POWERPROFILESCTL_BIN="$FAKEBIN/powerprofilesctl"
    LEGION_POWERCTL_SYSTEMCTL_BIN="$FAKEBIN/systemctl"
    LEGION_TEST_LOG="$LOG"
    LEGION_FAKE_RYZENADJ_STATE="$RYZENADJ_STATE"
)

for (( fake_policy_index = 1; fake_policy_index <= FAKE_EXTRA_POLICIES; fake_policy_index++ )); do
    fake_add_policy "$fake_policy_index" >/dev/null
done

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    printf '%s\n' "${FAKE_ENV[@]}"
fi
