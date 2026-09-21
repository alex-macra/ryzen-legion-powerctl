#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_RYZENADJ=0
INSTALL_RYZEN_SMU=0
ENABLE_SERVICE=1
FORCE_CONFIG=0
MIGRATE_LEGACY=0
SCRIPT_INSTALL=0
ARCH_FAMILY=0
INSTALL_GUI=1
REPLACE_SCRIPT_INSTALL=0

usage() {
    cat <<'EOF_USAGE'
Usage: ./install.sh [OPTIONS]

On Arch/CachyOS this builds a pacman package with makepkg and installs it,
so every file is tracked and 'pacman -R legion-powerctl' uninstalls cleanly.
On other distributions it falls back to a direct script install.

Options:
  --install-ryzenadj   Install ryzenadj (AUR) through paru/yay or makepkg
  --install-ryzen-smu  Install and load the ryzen_smu DKMS module (AUR) and keep
                       it loaded at boot when the driver and required files work
  --script-install     Skip makepkg and copy files directly (untracked by pacman)
  --no-gui             Do not install the GUI runtime (PySide6, polkit); the
                       GUI files are still installed but will not start
  --replace-script-install
                       Remove a previous untracked script install without
                       asking, then continue with the package install
  --no-enable          Install without enabling the boot service
  --force-config       Overwrite bundled profiles and config (script install only;
                       the package flow always preserves /etc through pacman)
  --migrate-legacy     Disable and archive legion-balanced-plus.service/timer
  -h, --help           Show this help

Run this script as your normal user. It invokes sudo only for system changes.
EOF_USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --install-ryzenadj) INSTALL_RYZENADJ=1 ;;
        --install-ryzen-smu) INSTALL_RYZEN_SMU=1 ;;
        --script-install) SCRIPT_INSTALL=1 ;;
        --no-gui) INSTALL_GUI=0 ;;
        --replace-script-install) REPLACE_SCRIPT_INSTALL=1 ;;
        --no-enable) ENABLE_SERVICE=0 ;;
        --force-config) FORCE_CONFIG=1 ;;
        --migrate-legacy) MIGRATE_LEGACY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'ERROR: Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ $EUID -eq 0 ]]; then
    SUDO=()
else
    command -v sudo >/dev/null 2>&1 || { echo "ERROR: sudo is required." >&2; exit 1; }
    SUDO=(sudo)
fi

info() { printf '\033[36m%s\033[0m\n' "$*"; }
warn() { printf '\033[33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

confirm() {
    local prompt="$1" reply
    [[ -t 0 ]] || return 1
    read -r -p "$prompt [y/N] " reply || return 1
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

check_pacman_lock() {
    [[ -e /var/lib/pacman/db.lck ]] || return 0
    if command -v fuser >/dev/null 2>&1 && "${SUDO[@]}" fuser /var/lib/pacman/db.lck >/dev/null 2>&1; then
        "${SUDO[@]}" fuser -v /var/lib/pacman/db.lck || true
        die "Pacman is currently in use. Finish or close the updater, then rerun the installer."
    fi
    die "A stale-looking pacman lock exists at /var/lib/pacman/db.lck. Verify no package manager is running, then remove the stale lock yourself."
}

readonly RYZENADJ_DEP='ryzenadj>=0.19.0'
readonly RYZEN_SMU_PKG='ryzen_smu-dkms-git'
readonly RYZEN_SMU_SYSFS_DIR='/sys/kernel/ryzen_smu_drv'
readonly MODULES_LOAD_CONF='/etc/modules-load.d/legion-powerctl.conf'

aur_install_ryzenadj() {
    (( INSTALL_RYZENADJ == 1 )) || die "Rerun with --install-ryzenadj, or install the AUR 'ryzenadj' package first (it replaces ryzenadj-git)."
    [[ $EUID -ne 0 ]] || die "Do not build AUR packages as root. Run ./install.sh as your normal user."
    command -v pacman >/dev/null 2>&1 || die "This installer currently supports Arch/CachyOS package management."
    check_pacman_lock

    if command -v paru >/dev/null 2>&1; then
        info "Installing ryzenadj with paru..."
        paru -S --needed ryzenadj
    elif command -v yay >/dev/null 2>&1; then
        info "Installing ryzenadj with yay..."
        yay -S --needed ryzenadj
    else
        die "No AUR helper found. Install paru or yay, or build ryzenadj yourself after reviewing its PKGBUILD:
    git clone https://aur.archlinux.org/ryzenadj.git
    cd ryzenadj && less PKGBUILD && makepkg -si"
    fi
    hash -r
}

ensure_ryzenadj_package() {
    if pacman -T "$RYZENADJ_DEP" >/dev/null 2>&1; then
        info "pacman-tracked ${RYZENADJ_DEP} is present."
        return 0
    fi
    if command -v ryzenadj >/dev/null 2>&1; then
        warn "A ryzenadj binary exists at $(command -v ryzenadj), but no pacman package satisfies '${RYZENADJ_DEP}'."
        warn "ryzenadj-git and source builds cannot satisfy the versioned dependency; the AUR 'ryzenadj' package replaces them."
    fi
    aur_install_ryzenadj
    pacman -T "$RYZENADJ_DEP" >/dev/null 2>&1 || die "The ryzenadj installation still does not satisfy '${RYZENADJ_DEP}'."
}

ensure_ryzenadj_binary() {
    if command -v ryzenadj >/dev/null 2>&1; then
        info "RyzenAdj found at $(command -v ryzenadj)."
        return 0
    fi

    if (( ARCH_FAMILY == 0 )); then
        die "RyzenAdj is missing and this is not an Arch-family system. Build it from source first: https://github.com/FlyGoat/RyzenAdj"
    fi
    aur_install_ryzenadj
    command -v ryzenadj >/dev/null 2>&1 || die "RyzenAdj installation completed without exposing a ryzenadj executable."
    info "Installed RyzenAdj at $(command -v ryzenadj)."
}

secure_boot_on() {
    if command -v mokutil >/dev/null 2>&1; then
        mokutil --sb-state 2>/dev/null | grep -qi 'SecureBoot enabled'
        return
    fi
    local var state
    for var in /sys/firmware/efi/efivars/SecureBoot-*; do
        [[ -r "$var" ]] || continue
        state="$(od -An -tu1 -j4 -N1 "$var" 2>/dev/null | tr -d '[:space:]')"
        if [[ "$state" == "1" ]]; then
            return 0
        fi
    done
    return 1
}

# DKMS needs headers for the kernel that is running now, which is not necessarily the
# one a bare 'linux-headers' would match on CachyOS. pkgbase names the right package.
ensure_kernel_headers() {
    local release build pkgbase
    release="$(uname -r)"
    build="/usr/lib/modules/${release}/build"
    if [[ -e "$build" ]]; then
        return 0
    fi
    if [[ ! -d "/usr/lib/modules/${release}" ]]; then
        warn "Skipping ryzen_smu: the running kernel ${release} has no module tree, so an update replaced it without a reboot. Reboot, then rerun with --install-ryzen-smu."
        return 1
    fi
    pkgbase="$(cat "/usr/lib/modules/${release}/pkgbase" 2>/dev/null || true)"
    if [[ -z "$pkgbase" ]]; then
        warn "Skipping ryzen_smu: cannot tell which headers package matches kernel ${release}. Install it by hand (CachyOS: linux-cachyos-headers), then rerun with --install-ryzen-smu."
        return 1
    fi
    info "Installing ${pkgbase}-headers for the DKMS build..."
    if ! "${SUDO[@]}" pacman -S --needed "${pkgbase}-headers"; then
        warn "Skipping ryzen_smu: could not install ${pkgbase}-headers."
        return 1
    fi
    if [[ ! -e "$build" ]]; then
        warn "Skipping ryzen_smu: ${pkgbase}-headers is installed but ${build} is still missing."
        return 1
    fi
}

aur_install_ryzen_smu() {
    if command -v paru >/dev/null 2>&1; then
        info "Installing ${RYZEN_SMU_PKG} with paru..."
        paru -S "$RYZEN_SMU_PKG" || { warn "Skipping ryzen_smu: the paru build failed."; return 1; }
    elif command -v yay >/dev/null 2>&1; then
        info "Installing ${RYZEN_SMU_PKG} with yay..."
        yay -S "$RYZEN_SMU_PKG" || { warn "Skipping ryzen_smu: the yay build failed."; return 1; }
    else
        warn "Skipping ryzen_smu: no AUR helper found. Build it yourself after reviewing its PKGBUILD:
    git clone https://aur.archlinux.org/${RYZEN_SMU_PKG}.git
    cd ${RYZEN_SMU_PKG} && less PKGBUILD && makepkg -si"
        return 1
    fi
}

# Only after a successful load: an entry for a module that is absent or unsupported
# makes systemd-modules-load.service fail on every boot.
persist_ryzen_smu() {
    if grep -rqs '^[[:space:]]*ryzen_smu[[:space:]]*$' \
        /etc/modules-load.d /usr/lib/modules-load.d /run/modules-load.d; then
        info "Something already loads ryzen_smu at boot; leaving it alone."
        return 0
    fi
    local staged=""
    if ! staged="$(mktemp)"; then
        warn "Could not stage $MODULES_LOAD_CONF; ryzen_smu will need a modprobe after each boot."
        return 0
    fi
    if ! printf '# Written by legion-powerctl install.sh --install-ryzen-smu.\n# Delete this file if you remove %s.\nryzen_smu\n' \
        "$RYZEN_SMU_PKG" > "$staged"; then
        warn "Could not write $MODULES_LOAD_CONF; ryzen_smu will need a modprobe after each boot."
        rm -f "$staged"
        return 0
    fi
    if "${SUDO[@]}" install -Dm0644 "$staged" "$MODULES_LOAD_CONF"; then
        info "Wrote $MODULES_LOAD_CONF so ryzen_smu loads at boot."
    else
        warn "Could not write $MODULES_LOAD_CONF; ryzen_smu will need a modprobe after each boot."
    fi
    rm -f "$staged"
}

ryzen_smu_usable() {
    local driver_version="" required_file
    driver_version="$("${SUDO[@]}" cat "$RYZEN_SMU_SYSFS_DIR/drv_version" 2>/dev/null || true)"
    if [[ "$driver_version" =~ ^0\.1\.([0-9]+)$ ]] && (( 10#${BASH_REMATCH[1]} >= 7 )); then
        :
    else
        warn "ryzen_smu driver ${driver_version:-unreadable} is not compatible with RyzenAdj 0.19 (needs 0.1.7 or newer); not adding a boot entry."
        return 1
    fi
    for required_file in mp1_smu_cmd smu_args smn pm_table_size pm_table; do
        if [[ ! -e "$RYZEN_SMU_SYSFS_DIR/$required_file" ]]; then
            warn "ryzen_smu lacks $required_file, which RyzenAdj 0.19 needs; applying limits through the module may fail. Not adding a boot entry."
            return 1
        fi
    done
    return 0
}

load_ryzen_smu() {
    if ! "${SUDO[@]}" modprobe ryzen_smu; then
        warn "${RYZEN_SMU_PKG} is installed but the module did not load. With Secure Boot on, enrol its MOK key; see docs/INSTALL.md."
        return 0
    fi
    if [[ ! -e "$RYZEN_SMU_SYSFS_DIR/mp1_smu_cmd" || ! -e "$RYZEN_SMU_SYSFS_DIR/smu_args" ]]; then
        warn "ryzen_smu loaded but $RYZEN_SMU_SYSFS_DIR has no command interface. Check 'sudo dmesg | grep -i ryzen_smu'; RyzenAdj may fall back to /dev/mem if permitted."
        return 0
    fi
    info "ryzen_smu is loaded and $RYZEN_SMU_SYSFS_DIR provides its command interface."
    if ! ryzen_smu_usable; then
        warn "If the package changed, reboot to load the updated module, then rerun --install-ryzen-smu; this CPU may still need driver support."
        return 0
    fi
    persist_ryzen_smu
}

# Optional, so nothing here may abort the install: every failure warns and returns 0.
ensure_ryzen_smu() {
    if [[ -e "$RYZEN_SMU_SYSFS_DIR/mp1_smu_cmd" && -e "$RYZEN_SMU_SYSFS_DIR/smu_args" ]]; then
        info "ryzen_smu already provides $RYZEN_SMU_SYSFS_DIR."
        if ryzen_smu_usable; then
            if (( INSTALL_RYZEN_SMU == 1 )); then
                persist_ryzen_smu
            fi
            return 0
        fi
        (( INSTALL_RYZEN_SMU == 1 )) || return 0
        warn "Trying to update ${RYZEN_SMU_PKG}; the running module may need a reboot before it can be verified."
    fi

    # Eligibility before the offer, so we never prompt for something we cannot do,
    # and never mention the module to someone who did not ask and cannot have it.
    local blocker=""
    if (( ARCH_FAMILY == 0 )); then
        blocker="this installer only builds AUR packages on Arch/CachyOS"
    elif [[ $EUID -eq 0 ]]; then
        blocker="AUR packages must not be built as root, so rerun as your normal user"
    elif ! command -v pacman >/dev/null 2>&1; then
        blocker="pacman is not available"
    elif [[ -e /var/lib/pacman/db.lck ]]; then
        blocker="pacman is busy"
    fi
    if [[ -n "$blocker" ]]; then
        if (( INSTALL_RYZEN_SMU == 1 )); then
            warn "Skipping ryzen_smu: ${blocker}. Install ${RYZEN_SMU_PKG} by hand; RyzenAdj also needs a compatible driver and PM-table files."
        fi
        return 0
    fi

    if (( INSTALL_RYZEN_SMU == 0 )); then
        printf '\n'
        info "Without the ryzen_smu module RyzenAdj may use /dev/mem if permitted, but limit readback may be unavailable."
        if ! confirm "Install the ${RYZEN_SMU_PKG} DKMS module now?"; then
            info "Skipping ryzen_smu. Later: ./install.sh --install-ryzen-smu"
            return 0
        fi
    fi

    if secure_boot_on; then
        warn "Secure Boot is enabled. ${RYZEN_SMU_PKG} is an out-of-tree module, so it will not load until you enrol its MOK key (mokutil --import, then reboot and confirm)."
    fi

    ensure_kernel_headers || return 0
    aur_install_ryzen_smu || return 0
    load_ryzen_smu
}

ensure_gui_runtime() {
    if (( INSTALL_GUI == 0 )); then
        info "Skipping the GUI runtime (--no-gui). Later: sudo pacman -S pyside6 polkit"
        return 0
    fi

    local have_qt=0 have_polkit=0
    python3 -I -c 'import PySide6' >/dev/null 2>&1 && have_qt=1
    command -v pkexec >/dev/null 2>&1 && have_polkit=1
    if (( have_qt == 1 && have_polkit == 1 )); then
        info "GUI runtime present (PySide6 and pkexec)."
        return 0
    fi

    if (( ARCH_FAMILY == 0 )); then
        warn "legion-powerctl-gui needs PySide6 and polkit; install them with your distribution's package manager."
        return 0
    fi

    check_pacman_lock
    info "Installing the GUI runtime (pyside6, polkit)..."
    if ! "${SUDO[@]}" pacman -S --needed pyside6 polkit; then
        warn "Could not install the GUI runtime. The CLI works; legion-powerctl-gui will not start until 'pacman -S pyside6' succeeds."
        return 0
    fi
}

refresh_desktop_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        "${SUDO[@]}" update-desktop-database -q /usr/share/applications 2>/dev/null || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        "${SUDO[@]}" gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
    fi
}

migrate_legacy() {
    local found=0 enabled_or_active=0 unit path stamp state
    for unit in legion-balanced-plus.timer legion-balanced-plus.service; do
        if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "^$unit"; then
            found=1
        fi
        [[ -e "/etc/systemd/system/$unit" ]] && found=1

        state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
        [[ "$state" == "enabled" ]] && enabled_or_active=1
        state="$(systemctl is-active "$unit" 2>/dev/null || true)"
        [[ "$state" == "active" || "$state" == "activating" ]] && enabled_or_active=1
    done
    (( found == 1 )) || return 0

    if (( MIGRATE_LEGACY == 0 )); then
        if (( enabled_or_active == 1 )); then
            die "An enabled or active legacy legion-balanced-plus unit was detected. Rerun with --migrate-legacy to prevent two services applying competing limits."
        fi
        warn "Disabled legacy legion-balanced-plus files were detected; they will be left untouched."
        return 0
    fi

    stamp="$(date +%Y%m%d-%H%M%S)"
    info "Disabling legacy Balanced+ units..."
    for unit in legion-balanced-plus.timer legion-balanced-plus.service; do
        "${SUDO[@]}" systemctl disable --now "$unit" 2>/dev/null || true
        path="/etc/systemd/system/$unit"
        if [[ -e "$path" ]]; then
            "${SUDO[@]}" mv "$path" "${path}.disabled-${stamp}"
        fi
    done
}

enable_service() {
    (( ENABLE_SERVICE == 1 )) || {
        info "Skipping service enablement (--no-enable). Later: sudo legion-powerctl enable"
        return 0
    }
    info "Enabling the boot service (doctor runs first; use 'legion-powerctl enable --force' to override)..."
    if ! "${SUDO[@]}" /usr/bin/legion-powerctl enable; then
        warn "The files are installed, but the service was not enabled."
        warn "Fix the doctor failures above, then run: sudo legion-powerctl enable"
        return 1
    fi
}

package_install() {
    [[ $EUID -ne 0 ]] || die "makepkg refuses to run as root. Run ./install.sh as your normal user."
    command -v tar >/dev/null 2>&1 || die "tar is required to build the package tarball."

    if [[ -e /usr/bin/legion-powerctl ]] && ! pacman -Qo /usr/bin/legion-powerctl >/dev/null 2>&1; then
        warn "A previous script install was detected at /usr/bin/legion-powerctl."
        warn "pacman will not overwrite files it does not own, so it has to be removed first."
        warn "Your profiles and configuration in /etc/legion-powerctl are kept either way."
        if (( REPLACE_SCRIPT_INSTALL == 1 )) || confirm "Remove the previous script install now?"; then
            info "Removing the previous script install..."
            [[ -x "$ROOT_DIR/uninstall.sh" ]] || die "uninstall.sh is missing from this checkout; remove /usr/bin/legion-powerctl by hand."
            "$ROOT_DIR/uninstall.sh"
        else
            die "Run ./uninstall.sh once, then rerun this installer - or rerun with --replace-script-install."
        fi
    fi

    if (( FORCE_CONFIG == 1 )); then
        warn "--force-config has no effect in the package flow; pacman preserves edited /etc files. Use --script-install, or reset profiles by hand."
    fi

    check_pacman_lock
    ensure_ryzenadj_package
    ensure_ryzen_smu
    migrate_legacy

    local version
    version="$(make -C "$ROOT_DIR" -s print-version)"
    [[ -n "$version" ]] || die "Could not read the version from bin/legion-powerctl."

    BUILD_DIR="$(mktemp -d)"
    trap 'rm -rf "${BUILD_DIR:-}"' EXIT
    info "Building legion-powerctl $version package in $BUILD_DIR..."
    make -C "$ROOT_DIR" dist DISTDIR="$BUILD_DIR"
    cp "$ROOT_DIR/packaging/arch/PKGBUILD" "$ROOT_DIR/packaging/arch/legion-powerctl.install" "$BUILD_DIR/"
    (cd "$BUILD_DIR" && makepkg -si)

    ensure_gui_runtime
    enable_service || true
    printf '\n'
    info "Installed as a pacman package. Uninstall with: sudo pacman -R legion-powerctl"
}

install_preserving() {
    local source="$1" destination="$2" mode="$3"
    if [[ -e "$destination" && $FORCE_CONFIG -eq 0 ]]; then
        info "Keeping existing $destination"
    else
        "${SUDO[@]}" install -Dm"$mode" "$source" "$destination"
        info "Installed $destination"
    fi
}

script_install() {
    warn "Script install: files will NOT be tracked by a package manager."
    warn "On Arch/CachyOS prefer the default makepkg flow; run ./uninstall.sh before switching to it."

    ensure_ryzenadj_binary
    ensure_ryzen_smu
    migrate_legacy

    info "Installing legion-powerctl..."
    "${SUDO[@]}" make -C "$ROOT_DIR" install-files PREFIX=/usr

    "${SUDO[@]}" install -d -m0755 /etc/legion-powerctl/profiles.d
    install_preserving "$ROOT_DIR/config/config.conf" /etc/legion-powerctl/config.conf 0644
    local profile
    for profile in "$ROOT_DIR"/profiles/*.conf; do
        install_preserving "$profile" "/etc/legion-powerctl/profiles.d/${profile##*/}" 0644
    done

    "${SUDO[@]}" systemd-analyze verify /usr/lib/systemd/system/legion-powerctl.service
    "${SUDO[@]}" systemctl daemon-reload
    "${SUDO[@]}" systemctl reset-failed legion-powerctl.service 2>/dev/null || true

    refresh_desktop_caches
    ensure_gui_runtime
    enable_service || true
}

main() {
    [[ -x "$ROOT_DIR/bin/legion-powerctl" ]] || die "Run install.sh from the repository checkout."
    command -v systemctl >/dev/null 2>&1 || die "systemd/systemctl is required."
    command -v make >/dev/null 2>&1 || die "make is required (Arch: pacman -S make; Debian/Fedora: the base-devel or make package)."
    [[ -f "$ROOT_DIR/Makefile" ]] || die "Makefile is missing from this checkout; the file list lives there."

    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [[ "${ID:-}" == "arch" || "${ID:-}" == "cachyos" || " ${ID_LIKE:-} " == *arch* ]]; then
            ARCH_FAMILY=1
        else
            warn "This project is developed for CachyOS/Arch; detected ${PRETTY_NAME:-unknown Linux}."
        fi
    fi

    if [[ $EUID -ne 0 ]]; then
        sudo -v
    fi

    if (( SCRIPT_INSTALL == 0 )) && (( ARCH_FAMILY == 1 )) && command -v makepkg >/dev/null 2>&1; then
        package_install
    else
        if (( SCRIPT_INSTALL == 0 )) && (( ARCH_FAMILY == 1 )); then
            warn "makepkg not found; falling back to the script install."
        fi
        script_install
    fi

    printf '\n'
    info "Installation complete."
    /usr/bin/legion-powerctl doctor || true
    printf '\nUseful commands:\n'
    printf '  legion-powerctl status\n'
    printf '  legion-powerctl-gui\n'
    printf '  sudo legion-powerctl wizard balanced-plus\n'
    printf '  sudo legion-powerctl configure balanced-plus --temp 78 --select --apply\n'
    printf '  legion-powerbench doctor\n'
    printf '  systemctl status legion-powerctl.service\n'
}

main "$@"
