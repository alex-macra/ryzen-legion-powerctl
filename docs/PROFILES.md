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

## Tuning method

Change one dimension at a time and compare the same workload:

1. Restore stock frequency range and keep boost enabled.
2. Choose a conservative sustained power value.
3. Keep the slow limit slightly above sustained and the fast limit above slow.
4. Set a temperature ceiling below the processor's published maximum.
5. Record task completion time, game frametime, 1% lows, fan speed, and temperature.
6. Increase sustained power in small steps only when performance improves enough to justify the added heat and noise.

A higher temperature alone is not proof of better utilization.
