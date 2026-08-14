#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$HERE/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=/dev/null
source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$TMP" >/dev/null

cp "$ROOT_DIR/profiles/performance-capped.conf" "$PROFILES/performance-capped.conf"
printf 'STAPM_W=999\nSLOW_W=1\nFAST_W=1\nTEMP_C=82\n' > "$PROFILES/broken.conf"

run_cli status --json | sed -e "s#$TMP/bin#/usr/bin#g" > "$HERE/status.json.part"

if grep -n -e "$TMP" -e "$HOME" "$HERE/status.json.part"; then
    rm -f "$HERE/status.json.part"
    printf 'error: the generated fixture names paths from the machine that made it.\n' >&2
    exit 1
fi

mv "$HERE/status.json.part" "$HERE/status.json"
printf 'Wrote %s:\n\n' "$HERE/status.json"
cat "$HERE/status.json"
