# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed

- Refuse a known broken SMU backend before changing power policy, and record
  ordinary apply failures as partial instead of leaving a stale success visible.
- Unload an unusable module newly loaded by the installer, and respect a recovery
  blacklist on later installs.
- Keep `balanced-plus` at or below 78 C in the CLI and GUI, and correct the
  installer and CLI examples that previously set it to 82 C. Existing edited
  installs can be repaired with `configure balanced-plus --temp 78 --apply`.
- Detect the actual `ryzen_smu` sysfs interface instead of a nonexistent device
  node. Check RyzenAdj's driver version and required PM-table files before
  reporting the module backend ready; missing files can prevent applying limits.
  Persist an already loaded usable module when explicitly requested; try an AUR
  update without persisting an incompatible one.
- Keep a same-name GUI repair draft for an invalid profile through status refreshes
  until a valid saved profile replaces it.
- Temperature sweeps preserve all three running wattages. Trials require a known,
  unchanged restoration profile, restore it once on exit, stop their workload process
  groups and remove their scratch profiles after successful restoration.
- Read command-mode turbostat telemetry from stderr without confusing missing power
  columns with clocks. Battery draw never becomes CPU package power. Reports use the
  final two minutes and mark incomplete or invalid measurements inconclusive.
- Parse only structured stress-ng real-time throughput; other workloads no longer
  produce fabricated throughput from arbitrary log numbers. Failed workloads fail the run.
- Validate trial arguments before changing limits, preserve existing CSV files, and
  make dry runs leave no profiles or CSV files behind.
- Fix the three Python lint errors in the profile-derived desktop test.

### Added

- `repair balanced-plus` and the GUI's **Repair balanced-plus** action back up
  the installed settings and recover 60/65/75 W at 78 C with stock frequencies
  and boost on. With lockdown off, recovery can remove an incomplete optional
  SMU module and disable its automatic loading after a successful RyzenAdj apply.
- `make dev-gui` runs the GUI and CLI straight from a local checkout for fast
  previews without pushing to GitHub or rebuilding the installed package.
- A reproducible game-plus-VM comparison for balanced-plus, starting at 85 C with
  unchanged 65/70/80 W limits, including acceptance thresholds and explicit rollback.
  The candidate is unmeasured; bundled profile values remain unchanged pending hardware results.

- `docs/TUNING.md` and `legion-powerbench`: a way to find out which limit is actually
  binding before changing one. The document is the protocol - a signature table that maps
  observed telemetry to the constraint in the way, the telemetry sources and each one's
  caveat, the step-ladder experiment, the stop rules, and the shared CPU/GPU envelope
  arithmetic that explains why a CPU limit that helps a compile can cost frames in a game.
  The harness runs it: `doctor` reports which sources this machine offers, `sample` and
  `run` write CSV, and `report` prints the per-step table and the verdict. It samples
  unprivileged, applies steps only through `legion-powerctl`, restores the profile that
  was active when it started including on interrupt, and never writes GPU state.
- `legion-powerctl baseline --capture|--show` records the firmware's own SMU limits to
  `/var/lib/legion-powerctl/stock-limits.env`. The first apply captures them
  automatically, before it overwrites them. The capture happens once and is never
  overwritten, and it is refused once a profile has already been applied this boot,
  because the SMU no longer holds firmware values by then. Without this there was no
  reference point for how much headroom a machine has, and no way back short of a reboot.
- Two workload-class profiles, `crossload` and `compute`. The four existing profiles vary
  by how loud the machine is; these vary by what the workload is doing, because the CPU
  and GPU share one power and cooling envelope. `compute` ships with unmeasured values and
  says so in its header and its description: it is a hypothesis to run the ladder against,
  not a recommendation.
- `install.sh --install-ryzen-smu` installs the `ryzen_smu-dkms-git` DKMS module, loads
  it, and writes `/etc/modules-load.d/legion-powerctl.conf` when its RyzenAdj interface
  is usable so it survives a reboot. It
  resolves the headers package from the running kernel's `pkgbase` rather than assuming
  `linux-headers`. The module is optional, so every failure in that path warns and lets
  the install continue. Without the flag the installer offers it interactively when
  `/sys/kernel/ryzen_smu_drv` has no command interface, and stays silent with no terminal.
- A `Copy report` button in the GUI's System checks dialog. It puts the doctor's own
  output, prefixed with the tool versions and the verdict, on the clipboard, including
  on the path where doctor could not run at all. Check rows are now selectable by mouse.

### Changed

- The `ryzen_smu` doctor check is folded into `SMU-backend`. The two were one root cause
  reported as two warnings on every machine without the module, which is the default
  after a fresh install. `SMU-backend` now carries the module state in its detail and
  distinguishes a missing command interface from missing RyzenAdj initialization
  files. With no usable module backend or `/dev/mem`, the `FAIL` line points to the
  kernel log; the module may be loaded without having successfully probed this CPU.
- `RyzenAdj-shadow` reports `OK` when it has proof it picked correctly. The tool already
  selects the newest of several `ryzenadj` binaries rather than the first on `PATH`, so
  the old warning fired on a situation it had itself handled. It stays a warning in the
  one case where the claim is unprovable: a candidate whose `--help` names no version,
  which is also the case where selection degenerates to `PATH` order. Candidates at the
  same version are reported as a tie rather than as stale, because that tie is broken by
  `PATH` order and on a default Arch `PATH` the loser is the packaged binary.

## 0.3.0 - 2026-08-14

First public release. Versions 0.1.0 and 0.2.0 were development milestones and were
never published, so nothing here is an upgrade path from them.

### Added

- A Bash CLI, `legion-powerctl`, with `apply`, `configure`, `wizard`, `select`, `list`,
  `show`, `delete`, `status`, `doctor`, `enable`, `disable` and `restore-frequency`.
  `apply --dry-run` previews every write without performing one.
- Profiles as plain `KEY=VALUE` files under `/etc/legion-powerctl/profiles.d/`, parsed
  as data and never sourced, with input validation on every field.
- Control over the STAPM, slow PPT and fast PPT package-power limits and the Tctl
  ceiling through RyzenAdj, and optionally over the `powerprofilesctl` policy, the
  CPUFreq range, CPU boost and the AMD P-State EPP preference. Boost is toggled
  through the global `cpufreq/boost` control when the kernel exposes one (the kernel
  rejects per-policy writes while global boost is off), with the per-policy and
  per-CPU files as a fallback; a rejected write warns and is recorded as
  `BOOST_APPLIED=no` instead of aborting the apply.
- Boot persistence as a single systemd one-shot unit. No daemon and no timer.
- `status --json`, schema-versioned for machine consumption, and `status --waybar` for
  Waybar custom modules.
- `doctor`, reporting the SMU backend, the `ryzen_smu` module state, kernel lockdown,
  Secure Boot, the CPUFreq driver, the boost control in use, conflicting writers and
  whether the GUI's dependencies are installed.
- `legion-powerctl-gui`, an optional PySide6 control panel. It never runs as root: it
  reads `status --json` and routes privileged subcommands through `pkexec`.
- A polkit policy with one action per subcommand, in two authorisation tiers.
- Four example profiles, `balanced`, `balanced-plus`, `quiet` and `performance-capped`.
- Bash and fish completions, a man page, and an Arch package.

### Known limitations

- Not verified on real hardware beyond one Lenovo Legion Pro 7. The polkit prompts have
  never been displayed and the built package has not been installed on a real Arch
  system.
- The GUI is exercised only offscreen. Contrast is computed rather than observed and
  there has been no screen-reader pass.
- No AppStream metainfo, so the application does not appear in KDE Discover or GNOME
  Software.
