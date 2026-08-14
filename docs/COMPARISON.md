# How this compares to other tools

`legion-powerctl` aims to be a strictly input-validated, no-daemon, profile-based
power CLI for Ryzen HX Legions. Different tools solve different problems.

| Tool | What it is | Why this exists anyway |
|---|---|---|
| [LenovoLegionLinux](https://github.com/johnfanv2/LenovoLegionLinux) | EC/WMI kernel module and GUI: fan curves, power modes, battery, and on supported models the same SPL/SPPT/FPPT triplet | Same knobs, different mechanism (EC/WMI rather than SMU) and a much larger scope. This is a small no-daemon CLI with profile files as data, and it works where the EC module has no support for your model |
| ZenTune (formerly UXTU4Linux) | Python TUI with a resident daemon, generic Ryzen presets | Daemon-based and not Legion-focused |
| [CoreCtrl](https://gitlab.com/corectrl/corectrl), TuxClocker | GPU-first tuning GUIs; CoreCtrl also handles governors and EPP | No Ryzen laptop package-power limits |
| power-options, TLP, auto-cpufreq | Generic power management: governors, radios, devices | No SMU package-power limits |
| Ryzen Controller | Electron GUI over RyzenAdj | Development stopped years ago |

What none of them combine: validated data-only profile files; RyzenAdj, the Linux
power profile, CPUFreq and EPP in one apply step; one-shot systemd persistence with
no daemon and no timer; and diagnostics built for Legion hardware.

If one of these already solves your problem, use it. This is a narrow tool.
