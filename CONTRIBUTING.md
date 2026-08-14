# Contributing

Contributions are welcome, especially compatibility reports from additional Lenovo Legion AMD models.

Before opening a pull request:

```bash
make check-strict
```

`make check-strict` refuses to run until ShellCheck, fish, ruff and PySide6 are
installed, then runs everything CI runs - including the end-to-end tier, which
needs an X server, a session bus, an accessibility bus and a window manager.
`make test-e2e` names what is missing and stops; on a machine without the stack,
`make test-e2e-podman` builds it in a container instead.

`make check` is the same set with the missing tools skipped, which is fine while
you work but will not tell you whether CI passes: without PySide6 the offscreen
GUI tests skip themselves, report `OK` and exit 0.

On Arch/CachyOS: `sudo pacman -S shellcheck fish ruff pyside6`, and for the
end-to-end tier `sudo pacman -S xorg-server-xvfb xorg-xprop xorg-xdpyinfo xdotool
openbox at-spi2-core python-atspi`.

Please keep these design constraints:

- Profiles must remain plain data, not sourced shell code.
- No repeating timer or resident daemon by default.
- New low-level controls must be opt-in and documented.
- Avoid unofficial EC, VBIOS, or voltage manipulation in this repository.
- Error messages should state what changed, what did not, and how to recover.

A hardware report should include the laptop model, CPU family, kernel, RyzenAdj version, CPUFreq driver, relevant command output, and whether the settings survived boot, suspend, Fn+Q changes, and AC transitions.
