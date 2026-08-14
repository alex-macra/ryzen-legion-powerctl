# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

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
