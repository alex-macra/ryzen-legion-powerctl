# Why this exists

## The problem the shipped profiles were built for

On the development laptop under Linux, Lenovo's Balanced mode was the best gaming
baseline: it avoided the throttling seen in Performance mode and behaved better
thermally. Its stock balance still felt uneven. CPU package power could spike higher
than useful while the GPU felt constrained by the laptop's shared power and cooling
envelope.

The `balanced-plus` example asks `powerprofilesctl` for the balanced policy, then
applies 65/70/80 W CPU package limits and a 78 °C ceiling, with boost enabled on
the stock frequency range. The intent is to keep short CPU boosts while containing
sustained CPU heat, leaving more shared headroom for the GPU and improving frame
pacing and 1% lows. On the development machine,
gaming felt smoother and CPU temperature spikes were less severe.

This tool does not raise GPU power limits, so any GPU benefit is indirect. The
observations above come from one Lenovo Legion Pro 7 with a Ryzen 9 9955HX3D and are
informal, not controlled benchmarks. Windows may have a similar trade-off, but
neither the project nor this profile has been tested there. Treat `balanced-plus` as
a starting point and measure it on your own hardware; [PROFILES.md](PROFILES.md)
gives a before/after method.

## Why RyzenAdj, when the kernel now exposes these knobs

Since kernel 6.17, Lenovo's mainline WMI drivers (`lenovo-wmi-gamezone`,
`lenovo-wmi-other`) expose SPL/SPPT/FPPT and thermal attributes through
`/sys/class/firmware-attributes/`: no out-of-tree module, no `/dev/mem`, and
unaffected by kernel lockdown. That is a better foundation than RyzenAdj.

It is not the backend today because the attributes appear to be gated behind the
firmware's "custom" platform profile, and BIOS coverage on 2026 AMD Legions is
unverified on real hardware. The intent is to prefer firmware-attributes where the
BIOS exposes them and keep RyzenAdj as the fallback. If you have kernel 6.17+ on a
Legion, the output of `ls /sys/class/firmware-attributes/` in an issue would directly
accelerate that work.

AMD's DPTCi driver, proposed on LKML in March 2026, targets the same knobs
generically and may become a second native backend.

## What this will not become

No fan EC writes, no GPU power modification, no voltage offsets, no VBIOS changes,
and no resident daemon or periodic enforcement. Those carry different risk and
support characteristics and should not hide behind a generic CPU-limit profile.

A suspend and resume reapply hook is a plausible future feature, but only as an
explicit opt-in. Boot-time one-shot persistence stays the default.
