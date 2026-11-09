# Security policy

## Reporting

Report privately through GitHub's private vulnerability reporting on this
repository ("Report a vulnerability" under the Security tab). Please do not open
a public issue for a security problem. If the report form is unavailable, mail
mail@alexmacra.com.

Do not include secrets, private logs, or unrelated system data in reports.

Only the latest release is supported. There are no backports.

## What this project does with privilege

`legion-powerctl` writes AMD SMU power and thermal limits through RyzenAdj,
writes CPUFreq sysfs attributes, and manages one systemd unit. All of that
requires root. There are three ways it gets there:

1. **`sudo legion-powerctl ...`** - the plain CLI path.
2. **The one-shot boot service**, which runs `legion-powerctl apply --boot` as
   root at startup.
3. **`pkexec`**, used by `legion-powerctl-gui`, which is itself unprivileged and
   never runs as root.

## The polkit surface

`/usr/share/polkit-1/actions/io.github.alexmacra.legion-powerctl.policy` defines
one action per subcommand, each pinned with `org.freedesktop.policykit.exec.argv1`:

| Action | `allow_active` |
|---|---|
| `.configure`, `.apply`, `.select` | `auth_admin_keep` |
| `.delete`, `.enable`, `.disable`, `.repair` | `auth_admin` |

Three properties of this design are deliberate and are **not** vulnerabilities:

- **`auth_admin_keep` is a retained capability grant.** For a few minutes after
  one successful authentication, any code running as that user in that session
  can invoke the retained actions with no prompt. Within that window it can
  write any in-range profile (up to the 200 W / 100 °C guardrails), apply it,
  and change which profile is selected. This is a conscious trade for not
  prompting on every click while switching profiles; if you do not want it,
  edit the policy to `auth_admin` or remove the file.
- **`exec.argv1` pins only `argv[1]`.** Every flag after the subcommand is
  unconstrained. Treat `.configure`, `.apply`, and `.select` as one trust tier:
  `configure NAME --select --apply` reaches what the other two do.
- **A retained grant cannot install boot persistence** (`enable` always
  prompts), **but it can repoint an already-enabled boot service** at a
  different profile via `select`, which then applies at every boot.

Genuine vulnerabilities in this area would include: a way to make the CLI
execute attacker-controlled commands or write outside its own paths; a way to
reach a privileged action without matching one of the pinned subcommands; or a
packaging defect that installs the policy with wrong ownership or permissions
(it must be root-owned `0644` in `/usr/share/polkit-1/actions/`).

`exec.path` must match the CLI as installed. `make install` rewrites it from
`PREFIX` for that reason. A mismatch is a functional bug, not a hole - polkit
falls back to `org.freedesktop.policykit.exec`, which prompts every time.

`repair balanced-plus` resets and applies the recovery profile after saving a
backup. It may unload an incomplete optional `ryzen_smu` module and disable that
module's automatic loading after a successful apply. This system configuration
change requires fresh administrator authentication; a retained profile-editing
grant does not authorize it. The GUI confirms the reset and any discarded edits.

## Trust boundaries

- **Profile files under `/etc/legion-powerctl/` are trusted input.** They are
  root-writable only. They are parsed as data and never sourced or evaluated,
  and the parser rejects unknown keys, but a threat model where an unprivileged
  user can write to `/etc/legion-powerctl` is already lost.
- **The GUI trusts `legion-powerctl status --json`**, which is the CLI reading
  those same root-owned files. It is schema-versioned and refuses a version it
  does not understand.
- **`LEGION_POWERCTL_GUI_CLI`** names the CLI the GUI runs. The launcher sets
  it to the `legion-powerctl` installed next to itself, so a `/usr/local`
  install finds its own CLI. Under `pkexec` the policy pins `exec.path`, so
  pointing it anywhere else gets the generic every-time prompt, not the
  retained grant.
- **`LEGION_POWERCTL_GUI_ELEVATE`** (the elevation command, or `none`) and
  **`LEGION_POWERCTL_GUI_NO_DIALOGS=1`** (skip every confirmation) exist for
  development and tests only. The GUI ignores both unless
  `LEGION_POWERCTL_GUI_DEV=1` is also set. Without that gate the GUI always
  elevates with `pkexec`, runs the CLI directly only when it is already uid 0,
  and always asks before a destructive action.
- **`LEGION_POWERCTL_TESTING=1`** makes the CLI skip its root check and honour
  the `LEGION_POWERCTL_*_BIN` binary overrides, so the test suite can drive it
  against a fake laptop as an ordinary user. It grants nothing: an ordinary
  user still cannot write `/etc`, `/run`, or sysfs. A process running as root
  ignores `LEGION_POWERCTL_TESTING` and every other `LEGION_POWERCTL_*`
  variable except `LEGION_POWERCTL_DRY_RUN`, so `sudo`, `pkexec` and the boot
  service always use the built-in paths, guardrails and binaries. The test
  fixture refuses to run as root for the same reason.
- **`ryzenadj` is never looked up on `PATH`.** The CLI considers only
  `/usr/local/bin/ryzenadj` and `/usr/bin/ryzenadj`, and uses one only if it is
  a regular file owned by root and not writable by group or others. Unprivileged
  `doctor` and `status` run it too, so the same check protects them.
- **As root, `powerprofilesctl` and `systemctl` are not looked up on `PATH`
  either.** They come from `/usr/local/sbin`, `/usr/local/bin`, `/usr/sbin`,
  `/usr/bin`, `/sbin` or `/bin`, under the same ownership check. An
  unprivileged run still uses `PATH`, which is the user's own.
- **`legion-powerbench` follows the same rules.** It reads `ryzenadj -i` only
  from the two root-owned paths above, runs only a root-owned
  `/usr/local/bin/legion-powerctl` or `/usr/bin/legion-powerctl` for both its
  unprivileged reads and its `sudo` writes, and refuses to start while any
  `LEGION_POWERCTL_*` variable is exported. Its own binary overrides need
  `LEGION_POWERBENCH_TESTING=1`, which root ignores.
- **`LEGION_POWERCTL_DRY_RUN=1`** is honoured by every mutating subcommand:
  `apply`, `repair` and `restore-frequency` preview, and the rest (`configure`,
  `select`, `delete`, `enable`, `disable`, `wizard`, `baseline --capture`)
  refuse before changing anything.
- **State and profile files are replaced, never written in place.** Each write
  goes to a temporary file in the same directory and is renamed over the
  target, and a target that is a symlink or not a regular file is refused. The
  CLI also refuses to load a symlinked profile or `config.conf`, and refuses to
  write a CPUFreq or boost control that is a symlink or not a regular file.

## Hardware risk is not a security boundary

Validation guardrails reject malformed input. They do not establish that a given
wattage or temperature is safe for a given processor or cooling system, and the
5-200 W / 50-100 °C bounds are sanity limits, far wider than any laptop's usable
envelope. Applying values outside a machine's stock envelope stresses VRMs and
cooling. That is a documented capability of the tool, not a vulnerability.

If a profile destabilizes a machine, see the recovery section in
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
