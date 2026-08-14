#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

DRIVER_PYTHON="${E2E_DRIVER_PYTHON:-/usr/bin/python3}"
E2E_TIMEOUT="${E2E_TIMEOUT:-300}"
E2E_WAIT="${E2E_WAIT:-20}"
export E2E_WAIT

wait_for() {
    local what="$1"
    shift
    local deadline=$(( SECONDS + E2E_WAIT ))
    until "$@" >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then
            printf 'e2e: timed out after %ss waiting for %s\n' "$E2E_WAIT" "$what" >&2
            return 1
        fi
        sleep 0.05
    done
}

if [[ "${1:-}" == "--session" ]]; then
    shift
    openbox --sm-disable &
    OPENBOX=$!
    "$E2E_AT_SPI_BUS_LAUNCHER" --launch-immediately &
    A11Y_BUS=$!
    trap 'kill "$OPENBOX" "$A11Y_BUS" 2>/dev/null || true' EXIT
    wait_for 'the window manager' xprop -root _NET_SUPPORTING_WM_CHECK

    cd "$ROOT_DIR"
    rc=0
    timeout --signal=TERM --kill-after=30 "$E2E_TIMEOUT" \
        "$DRIVER_PYTHON" -m unittest discover \
            --start-directory "$ROOT_DIR/tests/e2e" \
            --top-level-directory "$ROOT_DIR/tests/e2e" \
            --verbose "$@" || rc=$?
    exit "$rc"
fi

E2E_AT_SPI_BUS_LAUNCHER=''
for candidate in /usr/libexec/at-spi-bus-launcher \
                 /usr/lib/at-spi2-core/at-spi-bus-launcher \
                 /usr/lib/at-spi-bus-launcher \
                 /usr/libexec/at-spi2-core/at-spi-bus-launcher; do
    if [[ -x "$candidate" ]]; then E2E_AT_SPI_BUS_LAUNCHER="$candidate"; break; fi
done
export E2E_AT_SPI_BUS_LAUNCHER

missing=''
for tool in make xvfb-run xauth xdpyinfo xprop xdotool openbox dbus-run-session timeout; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
[[ -n "$E2E_AT_SPI_BUS_LAUNCHER" ]] || missing="$missing at-spi2-core"
[[ -x "$DRIVER_PYTHON" ]] || missing="$missing $DRIVER_PYTHON"
"$DRIVER_PYTHON" -c 'import pyatspi' >/dev/null 2>&1 || missing="$missing python3-pyatspi"
python3 -I -c 'import PySide6' >/dev/null 2>&1 || missing="$missing PySide6"
if [[ -n "$missing" ]]; then
    printf 'The end-to-end tier cannot run; not installed:%s\n' "$missing" >&2
    printf 'Debian/Ubuntu: apt install xvfb xauth x11-utils xdotool openbox dbus-x11 \\\n' >&2
    printf '                           at-spi2-core python3-pyatspi gir1.2-atspi-2.0\n' >&2
    printf 'Arch/CachyOS:  pacman -S xorg-server-xvfb xorg-xprop xorg-xdpyinfo xdotool \\\n' >&2
    printf '                         openbox at-spi2-core python-atspi\n' >&2
    printf 'Anywhere else: make test-e2e-podman, which builds the stack in a container.\n' >&2
    exit 1
fi

E2E_WORK="$(mktemp -d)"
trap 'rm -rf "$E2E_WORK"' EXIT

make -C "$ROOT_DIR" -s install DESTDIR="$E2E_WORK/tree" PREFIX=/usr SYSCONFDIR=/etc

# shellcheck source=tests/fixtures/make-fake-root.sh
source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$E2E_WORK/fake"

export E2E_WORK E2E_REPO="$ROOT_DIR" E2E_TREE="$E2E_WORK/tree"
export HOME="$E2E_WORK/home" XDG_RUNTIME_DIR="$E2E_WORK/run"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
export XDG_DATA_DIRS="$E2E_TREE/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export QT_QPA_PLATFORM=xcb QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
export LEGION_POWERCTL_GUI_ELEVATE=none

rc=0
env "${FAKE_ENV[@]}" \
    xvfb-run --auto-servernum --error-file /dev/stderr \
        --server-args '-screen 0 1280x800x24 -nolisten tcp' \
        dbus-run-session -- "$0" --session "$@" || rc=$?
exit "$rc"
