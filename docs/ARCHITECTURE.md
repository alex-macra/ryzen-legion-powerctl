# Architecture

## Components

- `/usr/bin/legion-powerctl`: validation, profile management, hardware writes, and diagnostics
- `/etc/legion-powerctl/config.conf`: selected boot profile
- `/etc/legion-powerctl/profiles.d/*.conf`: user-editable profiles
- `/usr/lib/systemd/system/legion-powerctl.service`: one-shot boot application
- `/run/legion-powerctl/last-apply.env`: volatile record of the most recent successful application
- `/usr/bin/legion-powerctl-gui`: PySide6 launcher; sets `PYTHONSAFEPATH` and `cd /` before importing anything
- `/usr/share/legion-powerctl/gui/legion_powerctl_gui/`: the Qt Widgets application, a flat package
- `/usr/share/polkit-1/actions/io.github.alexmacra.legion-powerctl.policy`: the two-tier authorisation rules the GUI's `pkexec` calls are matched against

The GUI never runs as root. It shells out to the same `/usr/bin/legion-powerctl`
through `pkexec`, reads `status --json`, and parses `doctor` output; it holds no
second implementation of the limits or of the profile format.

## Inside bin/legion-powerctl

One file, by design: the polkit policy pins `exec.path` to the executable and not
to anything it might source, so runtime-sourced library files would hand root a
path-resolution surface the pin does not cover. Four packaging paths also rely on
the CLI being one copyable file. Instead of directories, the file is divided by
`# --- Name ---` banners, in this order:

| Section | What lives there |
| --- | --- |
| Constants | paths, guardrail bounds, and every `LEGION_POWERCTL_*` test override |
| The profile schema | `PROFILE_KEYS`, its reset defaults, `configure`'s flag map, the three enums |
| Output helpers | `info`/`success`/`warn`/`die` |
| Usage | the help text |
| Value predicates | `require_root`, `in_list`, `trim`, `is_uint`, name and description rules |
| External binaries | resolving `ryzenadj` (newest on PATH wins), `powerprofilesctl`, `systemctl` |
| Configuration and profile loading | `load_global_config`, `load_profile`, `try_load_profile` |
| Validation | `validate_profile` and the frequency rules |
| Writing configuration and profiles | `write_global_config`, `write_profile`, `print_profile` |
| Hardware application | `run_or_print`, `write_sysfs`, and the five `apply_*` steps |
| Commands: profiles | `apply`, `configure`, `wizard`, `select`, `list`, `show`, `delete` |
| Status | `collect_status` and the text, JSON and Waybar renderers |
| Doctor | the diagnostic checks and DMI, lockdown and Secure Boot probes |
| Commands: the boot service | `enable`, `disable`, `restore-frequency` |
| Dispatch | `main` |

Every change to the machine passes through `run_or_print` or `write_sysfs`, so a
dry run has exactly two places to intercept. The profile schema is a table rather
than four parallel lists, because the reset, the key dispatch, the file that gets
written and the runtime record all have to agree about what a profile contains.

## Inside the GUI package

`gui/legion_powerctl_gui/` is flat. There is no build backend - `pyproject.toml`
configures ruff and nothing else - and the Makefile installs the package by
globbing `*.py`, which is also how the PKGBUILD installs it, through `make
install`. Anything in a subdirectory would import from a checkout and then
silently not ship. `gui/tests/test_package_shape.py` holds that rule, and the
length ceiling below.

| Module | What lives there |
| --- | --- |
| `__main__.py` | the entry point: builds the application and shows the window |
| `app.py` | the window: assembles the panels, runs the poll, and arbitrates whether a click on the sidebar may change the editor |
| `actions.py` | every privileged argv the GUI builds - the six subcommands that reach `pkexec`: `configure`, `apply`, `select`, `delete`, `enable`, `disable` - and what each exit code means |
| `editor.py` | the form for one profile - reads and writes the widgets, validates, and shows an unreadable profile without arming anything |
| `advanced.py` | the collapsed disclosure holding boost, EPP and the frequency range |
| `envelope.py` | the power instrument: three linked stops on one track, and the temperature ceiling |
| `fields.py` | the widget vocabulary the editor is built from - cards, value entries, combo boxes |
| `flow.py` | a wrapping layout, because Qt ships none |
| `sidebar.py` | the profile list, including rows for profiles that have never been written |
| `profile_delegate.py` | how one profile row is painted: the running rail, the boot pin, and the pin's hit test |
| `header.py` | the two-line answer: what is running now, and what applies at boot |
| `runstate.py` | `last_apply` read as a state, the deltas that decide whether an apply raises limits, and the service badge. No Qt |
| `dialogs.py` | the modal surfaces: the checks report, the raise confirmation, and profile naming |
| `reports.py` | the status line and its transient messages |
| `runner.py` | every child process, and the promise that none outlives the window |
| `model.py` | the CLI's data contract: profile shape, enumerations, validators, and the `status --json` and `doctor` parsers. No Qt |
| `theme.py` | severity colours derived from the running palette |
| `a11y.py` | announcing a message, and labelling the control pairs `QFormLayout` cannot |

`actions.py` is the seam the split was chosen around: polkit pins `exec.path` to
the CLI and `exec.argv1` to the subcommand, so what that one file is able to
construct is the whole of the GUI's privileged surface. Two tests hold that: no
other module may build a privileged command, and every subcommand this one sends
must have a polkit action pinning it.

Every module is under 300 lines except `model.py`, which is deliberately not split
- the exemption, its own ceiling and the reason for both are written down in the
test that would otherwise fail, rather than repeated here where nothing checks them. Only `app.py` knows about more than one panel; the panels reach it
through signals. `actions.py` is the exception: it holds the window to parent its
modal dialogs to, the runner it sends every command through, and the editor and
sidebar because those are what it acts on.

## Apply sequence

1. Parse and validate the selected profile without evaluating shell code.
2. Ask `powerprofilesctl` to select the requested Linux profile, unless unchanged.
3. Invoke RyzenAdj with STAPM, slow PPT, fast PPT, and Tctl values.
4. Apply optional boost control.
5. Apply optional CPUFreq range changes after boost, so `stock` can use the
   hardware maximum exposed for the selected boost state.
6. Apply the optional EPP preference.
7. Record a small runtime status file after success.

The power-profile request is nonfatal because desktop implementations differ. Missing RyzenAdj is fatal because the central power limits cannot be applied without it.

## Persistence model

RyzenAdj writes volatile hardware state. Persistence is implemented by reapplying the selected profile once during startup through a systemd `Type=oneshot` unit. No timer is installed.

## Security model

- System-changing commands require root.
- Profile names are restricted to a safe filename character set.
- Profile files are parsed as data; they are not sourced as shell scripts.
- Unknown keys and malformed values are rejected. A key read from a profile is
  assigned indirectly, so the `PROFILE_KEYS` allowlist is load-bearing: it is the
  only thing stopping a hand-edited profile from naming any variable in the shell.
- The installer does not automatically remove an ambiguous Pacman lock.
- The tool does not execute arbitrary extra RyzenAdj arguments from configuration.

## Scope boundaries

The project intentionally avoids fan EC writes, GPU power modification, voltage offsets, VBIOS changes, and automatic periodic enforcement. Those features have different risk and support characteristics and should not be hidden behind a generic CPU-limit profile.
