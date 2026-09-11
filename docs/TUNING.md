# Tuning by measurement

The shipped profiles were set by feel. [WHY.md](WHY.md) and the README say so plainly:
the numbers came from one machine, judged by how gaming felt, with no instrumentation.
That was honest but it is not a method, and it cannot answer the question most people
actually have - *how much is my chassis leaving on the table?*

This document is the method. It exists so that a profile change can be defended with a
number instead of an impression.

The short version: **do not raise a limit until you have shown that limit is the one
binding.** Most of the time it is not, and raising it buys heat and noise for nothing.

## 1. Before you touch anything

### Capture stock

Applying a profile overwrites the firmware's own SMU limits and there is no way back
short of a reboot. Record what the machine shipped with, once, before the first apply:

```
sudo legion-powerctl baseline --capture
legion-powerctl baseline --show
```

The capture is written to `/var/lib/legion-powerctl/stock-limits.env` and is never
overwritten once it exists. It is your denominator: "65 W" means nothing until you know
whether the firmware was asking for 55 W or 120 W.

If the boot service has already run, the capture is tainted. Disable it, reboot, and
capture before anything applies:

```
sudo legion-powerctl disable
# reboot
sudo legion-powerctl baseline --capture
```

### Know the recovery path

Every step below can be undone. If the machine becomes unstable, add
`systemd.mask=legion-powerctl.service` to the kernel command line at the boot loader.
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) has the full procedure. Read it before you
start, not after.

## 2. What is actually limiting you

This is the whole document in one table. Take a steady-state sample - eight to ten
minutes into a sustained load, not thirty seconds - and match the signature:

| Signature at steady state | Binding limiter | What to do |
|---|---|---|
| Package power sits at `STAPM_W`, Tctl more than 5 C below `TEMP_C`, fan below maximum | Your own power cap | Raise `STAPM_W` and `SLOW_W`. **This is the headroom case.** |
| Tctl sits at `TEMP_C`, package power below `STAPM_W` | Thermal ceiling | Raise `TEMP_C`, or improve cooling. Raising power does nothing at all. |
| Neither pinned, effective clock below the hardware maximum | Current (TDC/EDC) or a firmware limit below yours | Not reachable through this tool's four knobs. See section 8. |
| Effective clock pinned at `scaling_max_freq` | CPUFreq policy or boost | `MAX_FREQ_MHZ`, `BOOST` |
| Comfortable at 2 minutes, at the ceiling by 8 | Heat soak | Separate burst from sustained: keep `FAST_W` high, lower `STAPM_W`. |

Two corollaries that catch nearly everyone:

- **A higher temperature is not evidence of a gain.** It is evidence of more heat. The
  gain has to show up in throughput or frametime, separately.
- **If temperature stays flat while you raise the power limit, the limit was never
  binding.** Nothing changed because nothing was being held back. Put it back.

## 3. Reading the machine

None of these sources is universally available, so the harness probes in order and tells
you which one it got. `legion-powerbench doctor` prints the whole ladder.

| Signal | Source | Caveat |
|---|---|---|
| Tctl | `/sys/class/hwmon/hwmon*/` where `name` is `k10temp`, then `temp1_input` | This is the sensor the SMU caps against, and the one `TEMP_C` sets |
| Tccd1, Tccd2 | the same hwmon, `temp3_input` and up | Runs hotter than Tctl by design. A 95 C Tccd under an 82 C Tctl cap is not a failed cap - see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Package power | `turbostat --show PkgWatt,CorWatt,Bzy_MHz,Busy%` | The most trustworthy source on Zen. Needs root and the `msr` module |
| Package power, fallback | `ryzenadj -i`, the `STAPM VALUE` and `PPT VALUE FAST` rows | On Fire Range the metrics table is often unavailable without `ryzen_smu`, and these rows have an empty parameter column, so they must be matched by name |
| System draw, fallback | `/sys/class/power_supply/BAT*/power_now` | Whole-system, not package, and reads zero on AC. Useful only as a direction check |
| Effective clock | `turbostat` `Bzy_MHz` | `scaling_cur_freq` under `amd-pstate` is a *request*, not what the core ran at. Do not tune against it |
| Fan | `/sys/class/hwmon/*/fan*_input` | Absent unless a Legion platform driver is loaded. Treat as optional |
| GPU | `nvidia-smi --query-gpu=power.draw,power.limit,temperature.gpu,clocks.sm,utilization.gpu` | Read only. This tool never writes GPU state |

## 4. The harness

`tools/legion-powerbench` runs the protocol. It samples unprivileged, shells out to
`legion-powerctl apply` for profile changes, and writes CSV.

```
legion-powerbench doctor
legion-powerbench sample --duration 60 --out idle.csv
legion-powerbench run --ladder stapm --from 65 --to 105 --step 10 \
                      --workload cpu --soak 600 --cool 300 --out ladder.csv
legion-powerbench report ladder.csv
```

`report` prints the per-step table and the limiter verdict from section 2.

Load generation is pluggable. The built-in `cpu` preset probes for `stress-ng`, then
`openssl speed`, then falls back to a portable busy loop; `crossload` adds `vkmark` or
`glmark2` if either is present. None of them is a dependency - `doctor` names what is
missing and `--workload-cmd` takes any command you prefer, including a real build or a
game benchmark.

`--dry-run` prints the plan and every command without applying or loading anything.

## 5. The step ladder

Change one dimension at a time, against a fixed workload, with `TEMP_C` held constant.

1. Idle baseline, 60 s. Record it. A machine that starts at 60 C is not the same
   experiment as one that starts at 45 C.
2. Load, 10 minutes. The first two minutes are boost behaviour, not steady state; the
   number you want is the mean over the last two minutes.
3. Cooldown, 5 minutes, back to within a few degrees of the idle baseline.
4. Step, and repeat.

A reasonable CPU-only ladder: `STAPM_W` 65, 75, 85, 95, 105, with `SLOW_W` at
`STAPM_W + 5` and `FAST_W` at `SLOW_W + 10`, `TEMP_C` fixed at 85. That is
`--ladder stapm`.

Run the power ladder first. Only if it ends on the thermally limited verdict is
`--ladder temp` worth running, and then it answers a narrower question: how much more the
machine will draw for each degree you give it. Raising the ceiling on a machine that was
never thermally limited changes nothing except the worst case.

Record per step: throughput, steady-state Tctl, mean package power, fan RPM, and
**throughput per watt**. That last column is the one that decides where to stop; the
others only explain it.

## 6. Stop rules

Stop climbing when any of these is true:

- Tctl reaches `TEMP_C`. You are now thermally limited and further power does nothing.
- A 10 W step buys less than about 2% throughput. You are paying heat and noise for
  noise.
- `legion-powerctl apply` reports drift, or `doctor` reports the limits did not take.
- Anything at all is unstable. Instability under a *raised* limit means back it off
  toward stock. Instability under a *lowered* one usually means the opposite - a starved
  package stutters. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers both directions.

Nothing here overrides the README's warning: the tool's validation bounds are sanity
bounds, not a safe range. 200 W is far outside any Legion's power delivery.

## 7. Workload classes and the shared envelope

A CPU-only ladder will overstate what you can use while gaming, because the CPU and the
GPU share one cooling system and one power budget.

Concretely, on a Legion Pro 7 16ARX10: AMD rates the Ryzen 9 9955HX3D at 55 W default
TDP with a 55 to 75 W configurable range, Lenovo rates ColdFront Vapor on this chassis at
roughly 250 W sustained crossload, and the RTX 5080 laptop GPU is a 175 W part including
Dynamic Boost. Subtract, and the CPU's share of a fully loaded game is somewhere near 75
W - which is roughly where `balanced-plus` already sits.

Those are vendor figures for one configuration, not measurements of your machine. Use
them to predict, then measure.

The consequence is the useful part: **raising CPU power in a GPU-bound game can cost you
frames**, because the budget it takes comes out of the GPU's. But the same raise under a
compile or a render, with the GPU idle, has the whole cooler to itself and no competitor
for the budget. One profile cannot be right for both.

Hence two workload classes, and two profiles:

- `compute` - sustained CPU work, GPU idle. The class where headroom is most likely to
  be real.
- `crossload` - gaming and anything else that loads both. The class where restraint on
  the CPU side is the thing that helps.

Both ship with unmeasured starting values and say so in their header. Run the ladder
before you trust either.

## 8. GPU: what exists, and what this tool does

`legion-powerctl` reads GPU telemetry during measurement and writes no GPU state at all.
That boundary is deliberate and is not going to move; see [WHY.md](WHY.md).

For completeness, the controls that do exist on this class of machine:

- **`nvidia-smi -pl`** sets the GPU power limit within the range `nvidia-smi -q -d POWER`
  reports. On most laptop GPUs the settable range is narrow or the control is locked by
  the vendor BIOS.
- **`lenovo-wmi-gamezone`**, mainline since kernel 6.17, exposes SPL/SPPT/FPPT and GPU
  cTGP/PPAB through `/sys/class/firmware-attributes/`. This is the only path to the
  firmware's own limits, including the ones that sit *below* whatever you set with
  RyzenAdj and would show up as the third row of the section 2 table. It appears to be
  gated behind the firmware's "custom" platform profile, and BIOS coverage on 2026 AMD
  Legions is unverified.
- **NVIDIA Dynamic Boost** shifts budget between CPU and GPU automatically. It is the
  mechanism behind the crossload arithmetic above, and it means your CPU and GPU numbers
  are never independent.

If you have kernel 6.17 or newer on a Legion, the output of
`ls /sys/class/firmware-attributes/` in an issue is directly useful.

## 9. Recording a result

Report a ladder like this, so it can be compared against someone else's:

```
Machine:        Lenovo Legion Pro 7 16ARX10 (83RU), Ryzen 9 9955HX3D, RTX 5080
Kernel:         6.17.4-cachyos
ryzenadj:       0.19.0, ryzen_smu loaded
Stock limits:   <from `legion-powerctl baseline --show`>
Workload:       stress-ng --cpu 32 --cpu-method matrixprod
Ambient:        22 C, laptop on a hard surface, AC connected

| STAPM/SLOW/FAST | TEMP_C | Throughput | Tctl (8-10 min) | Pkg W | Fan RPM | Per watt |
|-----------------|--------|------------|-----------------|-------|---------|----------|
| 65/70/80        | 85     |            |                 |       |         |          |
| 75/80/90        | 85     |            |                 |       |         |          |
| 85/90/100       | 85     |            |                 |       |         |          |

Verdict: <which row of section 2 matched, and at which step it stopped improving>
```

The `Verdict` line is the point of the exercise. A ladder without it is a table of
numbers; with it, it is a reason to change a profile.
