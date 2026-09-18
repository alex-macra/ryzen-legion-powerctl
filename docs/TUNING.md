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
| Neither pinned, effective clock below the hardware maximum | Inconclusive | Check CPU scheduling, VM allocation, memory pressure, workload demand, boost and firmware before raising limits |
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
| System draw, diagnostic only | `/sys/class/power_supply/BAT*/power_now` | Whole-system, not package. Never stored in `pkg_w` or used for CPU limiter or efficiency conclusions |
| Effective clock | `turbostat` `Bzy_MHz` | `scaling_cur_freq` under `amd-pstate` is a *request*, not what the core ran at. Do not tune against it |
| Fan | `/sys/class/hwmon/*/fan*_input` | Absent unless a Legion platform driver is loaded. Treat as optional |
| GPU | `nvidia-smi --query-gpu=power.draw,power.limit,temperature.gpu,clocks.sm,utilization.gpu` | Read only. This tool never writes GPU state |

## 4. The harness

`tools/legion-powerbench` runs the protocol. It samples unprivileged, shells out to
`legion-powerctl apply` for profile changes, and writes CSV. Python 3 validates the
CLI status JSON, and `setsid` from util-linux isolates workloads for cleanup. Both
are available with the Arch package and its base-system dependencies.

```
sudo -v
legion-powerbench doctor
legion-powerbench sample --duration 60 --out idle.csv
legion-powerbench run --ladder stapm --from 65 --to 105 --step 10 \
                      --workload cpu --soak 600 --cool 300 --out ladder.csv
legion-powerbench report ladder.csv
```

`report` averages only the final 120 seconds of each completed load. Interrupted
steps, runs shorter than two minutes, and missing or malformed package-power or
temperature readings produce an inconclusive verdict. The final window must have
increasing timestamps and no sampling gaps longer than 30 seconds; a few readings
near the end cannot establish sustained behaviour. Elapsed seconds include actual
sampling time, and a failed telemetry read still waits out its sampling interval.
The report keeps the CSV header unchanged. `turbostat` is read from stderr in command mode, including its
elapsed-time preamble; a missing `PkgWatt` column cannot turn a clock into watts.

Authenticate with `sudo -v` before probing telemetry. Do not grant blanket
passwordless access to turbostat: it can execute commands as root. If credentials
expire during a long run, authenticate when the restore command prompts. A failed
restore exits nonzero and prints the profile to reapply.

Before applying any step, the harness checks the last successfully applied profile,
including its three power limits and optional policy settings, against the profile
on disk. A missing, partially applied, or edited restoration profile blocks the run;
apply the intended profile once first. The selected boot profile is not a substitute
for the running profile. A temperature ladder preserves all three running wattages;
`--temp` is valid only for a power ladder. Scratch profiles leave platform policy,
boost, frequency range and EPP unchanged.

Each run uses a separate scratch profile and removes it after successful restoration.
Normal completion, interruption and failures stop the workload process groups and
restore the previously applied profile once. If the restore fails or that profile
was edited during the run, the scratch profile remains available for diagnosis and
the command fails. Existing output files are rejected, so use a fresh filename for
each comparison.

Load generation is pluggable. The built-in `cpu` preset probes for `stress-ng`, then
`openssl speed`, then falls back to a portable busy loop; `crossload` adds `vkmark` or
`glmark2`. A crossload preset without either GPU workload is rejected. None is a
mandatory dependency; `doctor` names what is missing. `--workload-cmd` takes a command
you choose, run as your user. It must remain active for the measurement window; an
early exit, including success, makes that step incomplete. Remaining workload
processes are stopped at the end of the window. Use `--workload none` when a game
and VM are already running outside the harness; those processes are never stopped.

Only the built-in stress-ng CPU metrics have a throughput parser: it reads real-time
bogo operations per second from the structured metrics table, over the full load.
OpenSSL, busy loops and custom command logs leave throughput blank. Record game FPS,
frame pacing and VM throughput separately; arbitrary numbers in a log are not a
benchmark result. The harness reports stop-rule evidence; it does not automatically
approve the next rung or enforce your machine's stock envelope.

`--dry-run` validates the restoration state and prints the plan without applying,
loading, probing privileged telemetry, creating a scratch profile, or writing CSV.

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

Choose the first dimension from the current measurements. At the 78 C balanced-plus
ceiling, test temperature first if Tctl is pinned. A temperature ladder answers how
much more the machine will draw for each degree you give it, at the same power limits.
Raising the ceiling on a machine that was never thermally limited changes only the
worst case.

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

## 10. Balanced-plus with a game and a VM

The first candidate is **65/70/80 W at 85 C**, with boost on, stock frequency range,
balanced platform policy and `balance_performance` EPP. It is unmeasured. The bundled
balanced-plus remains at 78 C until the hardware comparison below demonstrates a
gain. The 90 C ceiling here is a bound for this experiment on the Ryzen 9 9955HX3D,
not a new global validation limit or a claim that every Legion should use it.
AMD lists a 100 C processor maximum in the
[Ryzen 9 9955HX3D specifications](https://www.amd.com/en/products/processors/laptop/ryzen/9000-series/amd-ryzen-9-9955hx3d.html);
keep this tuning session at or below 90 C.

Use AC power, the same firmware mode, game settings and repeatable scene, and the
same VM task and CPU/RAM allocation throughout. Record the installed version, actual
profile, boost control, frequency range, CPU/GPU watts and temperatures. Check host
memory and CPU contention with the game and VM running:

```bash
legion-powerctl status
legion-powerctl doctor
free -h
vmstat 1 10
cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io
sudo -v
legion-powerbench doctor
```

`doctor` runs once and exits; it is not a background service. If boost is off, the
frequency range is restricted, or the host is swapping heavily, resolve that before
attributing lag to the thermal ceiling. Verify stock limits from a clean capture in
the same firmware mode before increasing watts. TDP specifications and a capture
taken after another tuning tool ran are not stock-limit measurements.

With balanced-plus actually applied and matching its saved profile, run one trial at
a time. Keep the real game and VM active during the load window. These commands
change only temperature temporarily and restore the previous profile on exit:

```bash
legion-powerbench run --ladder temp --from 78 --to 78 --workload none \
  --soak 600 --cool 0 --interval 5 --out balanced-plus-78-run1.csv
legion-powerbench report balanced-plus-78-run1.csv

# Pause the game/VM load and cool for at least five minutes before the next run.
legion-powerbench run --ladder temp --from 85 --to 85 --workload none \
  --soak 600 --cool 0 --interval 5 --out balanced-plus-85-run1.csv
legion-powerbench report balanced-plus-85-run1.csv
```

Repeat each condition three times with fresh `run2` and `run3` filenames, alternating
conditions. Compare the final two minutes at steady state and cool back near the
original idle temperature between runs. Record average FPS, 1% lows, and VM task
throughput alongside each CSV. For a timed fixed VM task, use the reciprocal of its
completion time as throughput. A stress-ng or synthetic crossload result does not
substitute for this game-plus-VM comparison.

Only if the 85 C trial is thermally limited, repeat it at 90 C (`--from 90 --to 90`).
If it is power limited instead, test 75/80/90 W at the chosen fixed temperature:

```bash
legion-powerbench run --ladder stapm --from 75 --to 75 --temp 85 \
  --workload none --soak 600 --cool 0 --interval 5 --out balanced-plus-75w-run1.csv
```

Use `--temp 90` only if that thermal trial was accepted. Test 85/90/100 W next only
if 75 W still binds and each limit is within the verified stock envelope. Use
`--from 85 --to 85` for that trial. Do not run a blind multi-step power ladder while
gaming. Stop on instability, rejected settings, excessive heat, or worse frame pacing.

Use the median of three runs. Accept a candidate only if game 1% lows or VM throughput
improves by at least 5%, while the other metric and average FPS each regress by no
more than 3%. Prefer the lower-power/cooler candidate when gains are within normal
run-to-run variation. If neither improves, leave balanced-plus unchanged and
investigate contention. Attach the CSVs and these results to the tuning PR:

| Condition | Run | Average FPS | 1% low FPS | VM throughput | Tctl / CPU W / GPU W |
|---|---|---|---|---|---|
| 65/70/80 W, 78 C | 1-3 | | | | |
| 65/70/80 W, 85 C | 1-3 | | | | |

### Promote and roll back a measured winner

Before replacing the installed profile, save it outside the profiles directory.
The backup is never overwritten by the following command:

```bash
sudo mkdir -p /var/lib/legion-powerctl/rollback
sudo cp -n /etc/legion-powerctl/profiles.d/balanced-plus.conf \
  /var/lib/legion-powerctl/rollback/balanced-plus.conf
```

After the 85 C candidate passes, explicitly write and apply its measured settings;
installing an update alone may preserve the old configuration or create a `.pacnew`:

```bash
sudo legion-powerctl configure balanced-plus --stapm 65 --slow 70 --fast 80 \
  --temp 85 --power-profile balanced --min-mhz stock --max-mhz stock \
  --boost on --epp balance_performance --apply
legion-powerctl status
```

Substitute different watts or 90 C only after that exact candidate passes. Preserve
the boot selection during trials; an already selected balanced-plus will use the
updated values at the next enabled service run. Update the bundled profile,
description and fixtures with the measured winner and its evidence at that point.
To restore the previous installed settings:

```bash
sudo cp /var/lib/legion-powerctl/rollback/balanced-plus.conf \
  /etc/legion-powerctl/profiles.d/balanced-plus.conf
sudo legion-powerctl apply balanced-plus
```
