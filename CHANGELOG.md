# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Security

- `ryzenadj` is no longer looked up on `PATH`. Only `/usr/local/bin/ryzenadj` and
  `/usr/bin/ryzenadj` are considered, and only when root owns them and neither group nor
  others can write them, so an unprivileged `doctor` or the GUI's status poll can no
  longer run a binary planted earlier on `PATH`. `LEGION_POWERCTL_RYZENADJ_BIN` and the
  other `*_BIN` overrides now work only in the test harness.
- A process running as root ignores `LEGION_POWERCTL_TESTING` and every other
  `LEGION_POWERCTL_*` override except `LEGION_POWERCTL_DRY_RUN`. The test fixture and
  the e2e container no longer run as root.
- `LEGION_POWERCTL_DRY_RUN=1` is honoured by every mutating command: `configure`,
  `select`, `delete`, `enable`, `disable`, `wizard` and `baseline --capture` refuse
  instead of changing anything.
- The GUI honours `LEGION_POWERCTL_GUI_ELEVATE` and `LEGION_POWERCTL_GUI_NO_DIALOGS` only
  when `LEGION_POWERCTL_GUI_DEV=1` is set; otherwise it always elevates with `pkexec` and
  always confirms. A dismissed prompt is recognised for an absolute `/usr/bin/pkexec`.
- `config.conf`, profiles, `last-apply.env`, `stock-limits.env` and the repair files are
  written to a temporary file and renamed into place, so a crash cannot leave one
  truncated, and a target that is a symlink is refused. CPUFreq, EPP and boost controls
  that are symlinks or not regular files are refused too.
- A symlinked profile or `config.conf` is refused by every command, not only `repair`.
- `status` and `status --json` show only the keys the CLI writes to `last-apply.env`,
  with control characters removed.
- As root, the CLI takes `powerprofilesctl` and `systemctl` only from the system
  binary directories, under the same ownership check as `ryzenadj`, never from `PATH`.
- `legion-powerbench` reads `ryzenadj -i` only from the two root-owned paths the CLI
  uses, and runs only a root-owned `/usr/local/bin/legion-powerctl` or
  `/usr/bin/legion-powerctl`, the same binary for its unprivileged reads and its `sudo`
  writes. It refuses to start while a `LEGION_POWERCTL_*` variable is exported, since
  `sudo` would drop it for the writes only. Its overrides need
  `LEGION_POWERBENCH_TESTING=1`, which root ignores.
- The ownership check for `ryzenadj`, `powerprofilesctl`, `systemctl` and, in
  `legion-powerbench`, `legion-powerctl` also requires every directory above the
  resolved binary, up to `/`, to be root-owned and not writable by group or others, in
  the CLI, `install.sh` and `legion-powerbench` alike.
- The GUI ignores `LEGION_POWERCTL_GUI_CLI` unless `LEGION_POWERCTL_GUI_DEV=1` is set,
  so no environment variable can choose what `pkexec` runs. It runs the CLI installed
  beside its own package, so a `/usr/local` install still finds its own CLI, or
  `/usr/bin/legion-powerctl`, and never searches `PATH`. The launcher no longer exports
  the variable; `make dev-gui` sets the gate.
- `legion-powerbench` honours its `sudo`, `turbostat`, `nvidia-smi` and workload
  overrides and `LEGION_POWERBENCH_PROFILE_NAME` only with `LEGION_POWERBENCH_TESTING=1`,
  and its scratch profile is always named `powerbench-*`, so no name can skip the
  scratch-profile guards in the CLI and the GUI.
- Power operations lock `/run/legion-powerctl/power-v2.lock`, created mode 0600 and never
  unlinked, and ignore the `power.lock` older versions left behind. An unprivileged
  process that kept the old world-readable lock open can no longer block every power
  operation, and two root processes can no longer each replace the other's lock and run
  together. The lock no longer depends on `/proc` or `/dev/fd`.
- `powerprofilesctl` and `systemctl` in the CLI as root, and `ryzenadj` and
  `legion-powerctl` in `legion-powerbench`, run from the resolved path the ownership
  check approved, so a symlink cannot be swapped between the check and the run.
- Every GitHub Action is pinned to a full commit SHA, and CI and the e2e container
  install exact PySide6 and ruff versions from `requirements-dev.txt`, which Dependabot
  updates after a seven-day cooldown.

### Fixed

- A pacman upgrade never moves the boot profile. `pre_upgrade` records it and, when
  pacman replaces an unedited `config.conf` with the shipped one, `post_upgrade` selects
  the recorded profile again, without applying it, if that profile still exists and is
  valid. An install that kept the `balanced` a fresh install selected no longer boots
  `balanced-plus` after an upgrade. It restores only when the boot profile is the shipped
  `balanced-plus`, so a profile selected during the transaction is kept, and it never
  selects a `powerbench-*` scratch profile for boot.
- The CLI no longer uses process substitution, so `apply`, `doctor` and the ownership
  check work where `/proc` is not mounted.
- When `./install.sh` cannot remove the script install while moving to the package
  flow, for example after a wrong `sudo` password, it stops before `pacman -U` and keeps
  the built package, whose path the recovery message names.
- The wizard asks whether to select and apply before it saves, and takes the power lock
  before it writes the profile when it will do either, so a concurrent power operation
  no longer sees a profile change under it.
- `select` without `--apply` warns and proceeds without the power lock when the state
  directory cannot be created, since no apply can be running then. The package's
  `post_install` relies on this in a `pacstrap` or chroot without a writable `/run`.
- Dismissing the prompt while applying the profile that the GUI's Go back names keeps
  the Go back offer, since nothing changed. Go back never points boot back at a
  `powerbench-*` scratch profile; it selects the profile it restores instead.
- `legion-powerbench` can restore a running profile whose name contains a dot.
- Moving from a script install to the package flow builds the package first with
  `makepkg -sf`, then removes the script install and installs the built package with
  `pacman -U --noconfirm`, so a missing `ryzenadj` package, a busy pacman, a failed
  build or a "n" at a prompt no longer leaves the machine with no CLI and no boot apply.
  Rerunning `./install.sh` without a version bump rebuilds instead of stopping on an
  already built package, the `ryzen_smu` boot entry the script install wrote is kept,
  and a failed `pacman -U` names the full recovery, including `legion-powerctl enable`.
- `wizard` refuses a `powerbench-*` scratch name, so it can no longer make one the boot
  profile. A `config.conf` that already names one boots `balanced`, and the boot unit
  and `doctor` name the scratch pointer, instead of the boot holding no limits at all.
- Cancelling or failing the first step of the GUI's Go back keeps the Go back button, so
  it can be retried, and a Go back left half done also reports the first step's warning.
- A fresh `sudo make install` boots `balanced` like every other fresh install; a staged
  install (`DESTDIR`) still ships `config.conf` byte for byte, and `make uninstall` runs
  `systemctl daemon-reload` after removing the unit.
- The package's fresh-install marker lives in `/var/lib/legion-powerctl` instead of
  `/run`, so a `pacstrap` or chroot install without a writable `/run` still boots
  `balanced`.
- `install.sh` accepts only the `ryzenadj` the CLI will run, a root-owned file in
  `/usr/local/bin` or `/usr/bin`, and `doctor` names a `ryzenadj` it will not run
  instead of saying none was found.
- `legion-powerbench` no longer refuses `LEGION_POWERCTL_GUI_*` variables such as the
  `LEGION_POWERCTL_GUI_SCHEME` the docs recommend; the CLI never reads them.
- A stock-limits capture that fails during an apply is reported on standard output, not
  as a warning, so a machine without `ryzen_smu` no longer shows a GUI warning on the
  first apply of every boot; `baseline --capture` still warns and fails.
- `delete` takes the power lock, and `select`, `configure --select` and the wizard check
  under the lock that the profile still exists before pointing boot at it, so a
  concurrent delete can no longer leave `config.conf` naming a missing profile.
  `delete balanced --force` while `balanced` boots says why it is refused.
- `apply` refuses a `powerbench-*` scratch profile; only `legion-powerbench` applies it,
  through `configure --apply`. The GUI never offers to go back to one.
- `ryzenadj --help`, run to pick between two installed copies, no longer inherits the
  power lock.
- A per-CPU boost file reached through the kernel's `cpuN/cpufreq` symlink is no longer
  written a second time after its `policyN` file.
- **Go back** in the GUI says so when it applied the old profile but could not set the
  old boot profile back, including when that prompt is dismissed, and keeps the offer
  to finish. A cancelled or failed action no longer changes what **Go back** does, and
  going back after applying the boot profile itself only re-applies.
- The `Status not updating` chip can be reached by keyboard, carries the error as its
  description, and its recovery is announced.
- `make dist` packs the working tree when the checkout sits inside another git
  repository, such as an extracted ZIP under a tracked directory, instead of an empty
  or unrelated tree.
- `make install` keeps an existing `config.conf` and profiles unless `FORCE_CONFIG=1`,
  and `make uninstall` disables the boot unit before removing it, or refuses, so no
  dangling `.wants` link is left behind.
- `uninstall.sh` refreshes the desktop database and icon cache, as `install.sh` does.
- `install.sh --force-config` selects `balanced` like a fresh install instead of
  restoring the shipped `balanced-plus` pointer. The package's `post_install` selects
  `balanced` only when `config.conf` did not exist before the install, so a stale
  `config.conf.pacnew` no longer stops a fresh install from booting `balanced`.
- The boot unit orders itself after `power-profiles-daemon.service`, so the daemon
  starting later cannot reset the platform profile the boot apply set.
- `legion-powerbench run` refuses a `--to` that is not on the step grid instead of
  silently skipping it, and an `--interval` above 30 s or a `--soak` below 120 s that the
  report would call inconclusive. A failing GPU load is named and its log is shown
  instead of discarded. Every load runs under `timeout`, so a SIGKILLed harness leaves
  none running for more than 70 s past its soak. Each step starts with `sudo -v`, and
  without turbostat the credential is renewed at every sample so the final restore does
  not stop for a password. `--no-gpu` skips `nvidia-smi`.
- A status poll that keeps failing leaves a `Status not updating` chip in the GUI's
  status bar until a poll succeeds, instead of disappearing with the 10 s message.
- The man page and `docs/ARCHITECTURE.md` list all seven subcommands the GUI elevates,
  including `repair`, which always prompts; `docs/TUNING.md` describes the telemetry
  `legion-powerbench` actually reads.

- The readback after an apply says the limits are confirmed, and records `VERIFIED=yes`,
  only when `ryzenadj -i` read back all four and they match. When some were not read it
  names them, warns, and records `VERIFIED=partial`, which `status`, `doctor` and the
  GUI's `partly confirmed` badge report. A missing row or `nan` counts as not read
  rather than as drift, so a `nan` no longer fails the boot unit on every boot.
- `doctor` run as root prints a `Limits` warning when `ryzenadj -i` fails instead of no
  row, and warns about partly read back limits instead of reporting them in force. An
  unprivileged `doctor`, which is what the GUI polls, still prints no `Limits` row when
  `-i` fails, because reading the SMU needs root.
- The stock-limits capture stores nothing unless all four limits read back as numbers,
  and a `stock-limits.env` without all four is treated as not captured, so a partial
  capture no longer locks capture out for good. The file is never read through a
  symlink. The capture an apply attempts warns once when it fails instead of failing
  silently, and `baseline --capture --show` is rejected instead of skipping the capture.
- Every apply and repair writes a boot-scoped marker in `/run/legion-powerctl` before
  its first power write, and a capture is refused while it names the current boot. A
  SIGKILLed apply can no longer leave the profile's limits to be stored as the firmware
  baseline, a marker from an earlier boot on a persistent `/run` no longer blocks the
  capture, and later applies in the same boot skip the capture without reading the SMU.
- `doctor`'s `RyzenAdj-shadow` row names every candidate with its version and warns when
  a stale one sits beside the chosen one, including when another has no readable
  version.
- `status` labels the last-apply record from its result instead of always calling it
  successful, and `restore-frequency` updates the frequency and boost fields of the
  record.
- A profile or `config.conf` key set twice is rejected with its line numbers instead of
  the last one winning, and a tab in `DESCRIPTION` is reported as a control character.
- A `config.conf` that exists but sets no `ACTIVE_PROFILE` still boots `balanced`, but
  the boot unit fails with the reason and `doctor` warns about it.
- The wizard rejects an answer at its own prompt (slow below STAPM, fast below slow, a
  `balanced-plus` ceiling above 82 C, a maximum frequency below the minimum) instead of
  discarding every answer at the end, and selects the boot profile only after the apply
  it was asked for succeeds.

- `delete --force` of the boot profile moves boot to `balanced` and says so, and
  refuses when `balanced` is missing or invalid, instead of leaving every boot to fail.
- A profile or config value padded with Unicode whitespace is refused in every locale,
  not trimmed to a valid name in UTF-8 locales.
- A `# profile-format: 2` marker below `DESCRIPTION` is honoured; the description was
  shown with its escapes before.
- The CLI never exits 126 or 127 itself; a child that does is reported as 1. The GUI
  reads those two codes as a dismissed pkexec prompt only when the CLI printed nothing,
  so a failure after a partial apply is no longer shown as cancelled.
- A warning from an apply no longer hides the GUI's **Go back** offer, and **Go back**
  is disabled while another action runs. **Ctrl+S** during an action says it is busy
  instead of doing nothing silently.
- A failing GUI status poll (an invalid `config.conf`, a missing CLI, unreadable
  `status --json`) is shown in the status bar once instead of opening a new error
  dialog every 15 seconds.
- The GUI refuses to delete the boot profile before asking for confirmation or a
  password, matching the CLI, which refuses it without `--force`.
- The GUI rejects a profile name or frequency with a trailing newline, a `profiles`
  value that is not a list, and limits written as `6_0` or with non-ASCII digits, and
  shows a null boot profile as none rather than `None`.
- The GUI's **Apply now** now also sets the boot profile, so the profile you apply is
  the one the boot service applies after a restart. Before, it changed only the running
  limits and the next boot went back to the old pointer. **Go back** restores both the
  profile that was running and the boot profile that was set before that apply.
- A fresh install boots `balanced` instead of `balanced-plus`: the pacman package's
  `post_install` and a script install that creates `config.conf` run
  `legion-powerctl select balanced` without applying it. The shipped `config.conf` is
  unchanged, so a pacman upgrade or a script reinstall never rewrites the boot profile
  of an existing install. Change it with `sudo legion-powerctl select balanced --apply`.
- `select --apply` and `configure --select --apply` take the power lock first and move
  the boot profile only after the apply succeeds, so a blocked or failed apply no longer
  changes what boots. `select` validates the profile before it writes `config.conf`.
- `select` and `configure --select` refuse `powerbench-*` scratch profiles.
- The GUI re-reads the status after a failed or cancelled action, so the header and
  the boot-service switch show what is on disk.
- The raise warning says the profile will also be applied at every boot when the boot
  service is on, and that it applies at boot only once the service is on otherwise.
- pacman now tracks `profiles.d/balanced.conf` as a backup file, so an upgrade no longer
  overwrites an edited `balanced` profile and removal keeps it as `.pacsave`.
- An interrupted `legion-powerbench run` whose output was piped through `tee` now
  still restores the previous profile; the scratch profile is removed even when the
  restore fails, and SIGHUP is handled like SIGINT and SIGTERM.
- The power-operation lock in `/run/legion-powerctl` is created mode 0600, is never
  opened through a symlink or truncated, and is no longer inherited by RyzenAdj,
  `powerprofilesctl`, `systemctl` or `modprobe`.
- Refuse a known broken SMU backend before changing power policy, and record
  ordinary apply failures as partial instead of leaving a stale success visible.
- Unload an unusable module newly loaded by the installer, and respect a recovery
  blacklist on later installs.
- Retune `balanced-plus` to 70/75/85 W at 72 C, down from 87/92/102 W at 80 C: the
  lower 85 W fast limit keeps boost spikes off the thermal ceiling, which an 80 C
  Tctl cap alone could not hold under load. Its adjustable ceiling now rises to 82 C,
  and `repair balanced-plus` restores the new baseline. Bring an older install up to
  date with `configure balanced-plus --stapm 70 --slow 75 --fast 85 --temp 72 --apply`.
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
  the installed settings and recover the shipped 70/75/85 W at 72 C with stock
  frequencies and boost on. With lockdown off, recovery can remove an incomplete optional
  SMU module and disable its automatic loading after a successful RyzenAdj apply.
- `make dev-gui` runs the GUI and CLI straight from a local checkout for fast
  previews without pushing to GitHub or rebuilding the installed package.
- A reproducible game-plus-VM comparison for balanced-plus, starting at 85 C with
  unchanged 70/75/85 W limits, including acceptance thresholds and explicit rollback.
  The candidate is unmeasured; the bundled 72 C ceiling stays pending hardware results.

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

- The GUI has a new look: flat hairline cards with one teal accent, a status strip
  across the top, a profile rail that marks the running profile, and **Apply now** pinned
  below the form so it never scrolls away. It is light or dark to follow the desktop's
  colour scheme and switches live; set `LEGION_POWERCTL_GUI_SCHEME=desktop` to keep the
  desktop's native style and palette instead.
- The `compute` and `crossload` example profiles are gone. If either is your boot
  profile, select another before upgrading; `crossload` matched the old `balanced-plus`.
  A package upgrade now names a boot profile that no longer exists.
- `performance-capped` no longer describes itself as the fastest profile.
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
