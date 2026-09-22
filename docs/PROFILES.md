# Profile reference

Each profile is a strict `KEY=VALUE` file. Unknown keys are rejected so spelling mistakes do not silently leave a setting unapplied.

## Metadata

### `DESCRIPTION`

One line of free text shown by `show`, `status --json`, and the GUI. Set it with `configure NAME --description TEXT` or by editing the field in the GUI. Newlines and control characters are rejected; quotes and backslashes round-trip through the file format unchanged.

## RyzenAdj limits

### `STAPM_W`

Sustained package-power limit in watts. This is the long-duration budget.

### `SLOW_W`

Slow or average PPT limit in watts. It should normally be at least as high as `STAPM_W`.

### `FAST_W`

Fast or short-duration PPT limit in watts. It permits brief boost bursts and should normally be the highest of the three power limits.

### `TEMP_C`

Tctl thermal ceiling in Celsius. It is a ceiling, not a target. Raising it only improves performance when temperature is the active limiter; a workload can still be power-limited below this temperature.

## Linux platform policy

### `POWER_PROFILE`

Accepted values:

- `balanced`
- `performance`
- `power-saver`
- `unchanged`

When `powerprofilesctl` is unavailable or rejects a profile, the tool warns and continues with the RyzenAdj limits.

## CPUFreq controls

### `MIN_FREQ_MHZ` and `MAX_FREQ_MHZ`

Accepted values:

- `stock`: restore the hardware-reported boundary
- `unchanged`: do not touch that boundary
- an integer MHz value

Using `stock` does not lock the CPU at that speed. It restores the range available to the governor and hardware-managed P-states.

### `BOOST`

Accepted values:

- `on`
- `off`
- `unchanged`

The kernel exposes one global control, `/sys/devices/system/cpu/cpufreq/boost`, when
the CPU driver supports toggling boost (amd-pstate on kernel 6.11 and newer,
acpi-cpufreq). The tool writes that file and stops, because the kernel applies it to
every policy itself - and because the kernel rejects per-policy boost writes while
global boost is off, so writing the per-policy files after the global one can never
work. Only when the global file is absent does the tool fall back to the legacy
per-policy and per-CPU controls.

When no control exists (amd-pstate-epp before kernel 6.11), or the kernel rejects the
write (for example the SBIOS has Core Performance Boost disabled), BOOST is skipped
with a warning and the rest of the profile still applies. The last-apply record shows
the outcome as `BOOST_APPLIED=yes`, `no`, `skipped` or `unchanged`.

Other services can toggle boost too. On CachyOS, power-profiles-daemon disables boost
on the power-saver profile and re-toggles it when the profile changes, so a profile
combining `POWER_PROFILE=power-saver` with `BOOST=on` will fight it.

### `EPP`

Accepted values:

- `performance`
- `balance_performance`
- `balance_power`
- `power`
- `unchanged`

EPP is a preference hint used by `amd-pstate-epp`; it is not a hard wattage limit. Leave it as `unchanged` unless there is a specific reason to override the value selected by the desktop power-profile service.

## Creating a profile

Profiles are created with `configure` or the wizard - see the README quickstart.

## The shipped profiles

Four vary by how loud you are willing for the machine to be:

| Profile | STAPM / Slow / Fast | Ceiling |
|---|---:|---:|
| `quiet` | 45 / 50 / 60 W | 78 °C |
| `balanced` | 60 / 65 / 70 W | 72 °C |
| `balanced-plus` | 65 / 70 / 80 W | 78 °C |
| `performance-capped` | 65 / 70 / 75 W | 85 °C |

Two vary by what the workload is doing, because the CPU and the GPU share one power and
cooling envelope:

| Profile | STAPM / Slow / Fast | Ceiling | For |
|---|---:|---:|---|
| `crossload` | 65 / 70 / 80 W | 78 °C | Gaming and anything loading both. Restraint here leaves budget for the GPU |
| `compute` | 85 / 90 / 100 W | 85 °C | CPU-only work with the GPU idle |

`balanced-plus` is capped at 78 °C by both the CLI and GUI, even if an older installed
file contains a higher value. Repair an older copy with
`sudo legion-powerctl configure balanced-plus --temp 78 --apply`; other profile names
retain the general 50-100 °C validation range.

`repair balanced-plus` is an explicit recovery action that saves a backup and
replaces the installed profile with 60/65/75 W at 78 °C, balanced platform policy,
stock frequency bounds, boost on and `balance_performance` EPP. Those wattages
reproduce the earlier manual gaming baseline; the bundled 65/70/80 W profile is
unchanged pending hardware comparisons. Repair applies immediately and preserves
the selected boot-profile name.

`compute` ships with **unmeasured** values. They are a hypothesis about what a Legion Pro
7 chassis can absorb with nothing competing for the cooler, not a recommendation. Run the
ladder in [TUNING.md](TUNING.md) before trusting them, and lower them if it reports the
machine as thermally limited rather than power limited.

## Tuning method

Do not raise a limit until you have shown that limit is the one binding. Most of the time
it is not, and raising it buys heat and noise for nothing.

[TUNING.md](TUNING.md) is the method: how to tell a power-limited machine from a
thermally limited one, what to sample and from where, the step-ladder protocol, the stop
rules, and how to record a result so it can be compared with someone else's.

Two things worth knowing before you start:

- A higher temperature alone is not proof of better utilization. It is proof of more
  heat. The gain has to show up in throughput or frametime, separately.
- Record the firmware's own limits first with `sudo legion-powerctl baseline --capture`.
  Without them, "65 W" has no denominator, and there is no way back short of a reboot.
