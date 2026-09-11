#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$HERE/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# shellcheck source=/dev/null
source "$ROOT_DIR/tests/fixtures/make-fake-root.sh" "$TMP" >/dev/null

# A second, older ryzenadj so the fixture exercises RyzenAdj-shadow. The check reports
# OK once both candidates name a version, so this looks inert in the output; without it
# the label disappears and test_doctor_fixture_covers_every_check_the_cli_can_emit fails.
mkdir -p "$TMP/bin2"
sed 's/0\.19\.0/0.18.0/' "$TMP/bin/ryzenadj" > "$TMP/bin2/ryzenadj"
chmod +x "$TMP/bin2/ryzenadj"

cat > "$TMP/bin/systemctl" <<'EOF_SYSTEMCTL'
#!/usr/bin/env bash
case "$*" in
    "is-enabled "*) printf 'enabled\n' ;;
    "is-active tlp.service") printf 'active\n' ;;
    "is-active "*) printf 'inactive\n' ;;
esac
EOF_SYSTEMCTL

cat > "$TMP/bin/python3" <<'EOF_PYTHON'
#!/usr/bin/env bash
exit 0
EOF_PYTHON

printf '#!/bin/sh\n' > "$TMP/bin/legion-powerctl-gui"
chmod +x "$TMP/bin/systemctl" "$TMP/bin/python3" "$TMP/bin/legion-powerctl-gui"

mkdir -p "$TMP/sysbin"
for tool in bash awk cat date grep head install mkdir mktemp od readlink rm sed sort tr; do
    ln -sf "$(command -v "$tool")" "$TMP/sysbin/$tool"
done

env "${FAKE_ENV[@]}" \
    PATH="$TMP/bin:$TMP/bin2:$TMP/sysbin" \
    NO_COLOR=1 \
    LEGION_POWERCTL_RYZENADJ_BIN= \
    LEGION_POWERCTL_PYTHON_BIN="$TMP/bin/python3" \
    LEGION_POWERCTL_GUI_LAUNCHER="$TMP/bin/legion-powerctl-gui" \
    LEGION_POWERCTL_POLKIT_POLICY="$ROOT_DIR/packaging/polkit/io.github.alexmacra.legion-powerctl.policy" \
    bash "$ROOT_DIR/bin/legion-powerctl" doctor \
    | sed -e "s#$TMP/bin2#/usr/local/bin#g" \
          -e "s#$TMP/bin#/usr/bin#g" \
          -e "s#$TMP/dev#/dev#g" \
          -e "s#$TMP/sys#/sys#g" \
          -e "s#$TMP#/#g" \
    > "$HERE/doctor.txt"

if grep -n -e "$TMP" -e "$HOME" "$HERE/doctor.txt"; then
    printf 'error: the generated fixture names paths from the machine that made it.\n' >&2
    exit 1
fi

printf 'Wrote %s:\n\n' "$HERE/doctor.txt"
cat "$HERE/doctor.txt"
