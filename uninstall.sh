#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PURGE=0

if [[ "${1:-}" == "--purge" ]]; then
    PURGE=1
elif [[ $# -gt 0 ]]; then
    echo "Usage: ./uninstall.sh [--purge]" >&2
    exit 2
fi

if [[ $EUID -eq 0 ]]; then
    SUDO=()
else
    command -v sudo >/dev/null 2>&1 || { echo "ERROR: sudo is required." >&2; exit 1; }
    SUDO=(sudo)
fi

if command -v pacman >/dev/null 2>&1 && pacman -Qo /usr/bin/legion-powerctl >/dev/null 2>&1; then
    echo "legion-powerctl is installed as a pacman package; this script would desync the package database." >&2
    echo "Remove it with: sudo pacman -R legion-powerctl" >&2
    exit 1
fi

command -v make >/dev/null 2>&1 || { echo "ERROR: make is required; the file list lives in the Makefile." >&2; exit 1; }
[[ -f "$ROOT_DIR/Makefile" ]] || { echo "ERROR: Makefile is missing from this checkout." >&2; exit 1; }

"${SUDO[@]}" systemctl disable --now legion-powerctl.service 2>/dev/null || true
"${SUDO[@]}" make -C "$ROOT_DIR" uninstall-files PREFIX=/usr
"${SUDO[@]}" rm -f /etc/modules-load.d/legion-powerctl.conf
if (( PURGE == 1 )); then
    "${SUDO[@]}" rm -rf /etc/legion-powerctl
else
    echo "Keeping /etc/legion-powerctl. Use --purge to remove profiles and configuration."
fi
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl reset-failed legion-powerctl.service 2>/dev/null || true

echo "legion-powerctl removed. RyzenAdj and the ryzen_smu module were not removed."
