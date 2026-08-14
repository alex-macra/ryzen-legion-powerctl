#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$HERE/../.." && pwd)"
OUT_DIR="${1:-$HERE}"

PYTHONPATH="$ROOT_DIR/gui" \
QT_QPA_PLATFORM=offscreen \
LEGION_POWERCTL_GUI_NO_DIALOGS=1 \
LEGION_POWERCTL_GUI_CLI="$ROOT_DIR/gui/tests/fake-legion-powerctl" \
OUT_DIR="$OUT_DIR" ROOT_DIR="$ROOT_DIR" python3 - <<'EOF_PY'
import json
import os
import pathlib
import tempfile
import time

root = pathlib.Path(os.environ["ROOT_DIR"])
out = pathlib.Path(os.environ["OUT_DIR"]) / "gui-main-window.png"

# The fixture with the two facts pulled apart: applied `quiet`, boots `balanced-plus`.
status = json.loads((root / "gui/tests/fixtures/status.json").read_text(encoding="utf-8"))
status["active_profile"] = "balanced-plus"
status["last_apply"].update({
    "profile": "quiet", "verified": "yes",
    "stapm_w": "45", "slow_w": "50", "fast_w": "60", "temp_c": "78",
})
# The README shows the shipped profile set: the fixture's deliberately-invalid
# "broken" entry is a test asset, and `balanced` is absent from the fixture.
status["profiles"] = [p for p in status["profiles"] if p.get("valid")]
status["profiles"].insert(0, {
    "name": "balanced", "active": False, "valid": True,
    "description": "Silent daily driver: boost off, quiet fan curve, full base-clock throughput.",
    "stapm_w": 60, "slow_w": 65, "fast_w": 70, "temp_c": 72,
    "power_profile": "power-saver", "min_freq_mhz": "stock", "max_freq_mhz": "stock",
    "boost": "off", "epp": "balance_performance",
})
handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
json.dump(status, handle)
handle.close()
os.environ["FAKE_CLI_STATUS_FIXTURE"] = handle.name

from PySide6.QtWidgets import QApplication  # noqa: E402  (after the env is set)

from legion_powerctl_gui.app import MainWindow  # noqa: E402

app = QApplication([])
window = MainWindow()
window.resize(960, 620)
window.show()
# Both polls have to land, or the capture is of an empty window.
for _ in range(400):
    app.processEvents()
    if window.refresh_count >= 1 and window.checks.count >= 1:
        break
    time.sleep(0.01)
else:
    raise SystemExit(f"the window never loaded: {list(window.errors)}")
for _ in range(50):
    app.processEvents()
    time.sleep(0.01)
if window.errors:
    raise SystemExit(f"the window reported errors: {list(window.errors)}")
if not window.grab().save(str(out)):
    raise SystemExit(f"could not write {out}")
print(f"wrote {out}")
os.unlink(handle.name)
EOF_PY
