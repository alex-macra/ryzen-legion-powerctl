# Troubleshooting

## Recovery: the machine is unstable after applying a profile

Read this first. The boot service reapplies the selected profile at **every**
boot, so a profile that destabilizes the machine does not go away by rebooting.

RyzenAdj settings themselves are volatile - they are gone after a power cycle -
so the fix is to stop the service from reapplying them.

**If the system still boots and is usable:**

```bash
sudo systemctl disable --now legion-powerctl.service
```

Limits stay as they are until you reboot; reboot to return to firmware defaults.

**If the system is too unstable to reach a terminal**, stop the service before
it runs. At the boot loader, use its edit-entry command to change the kernel
command line for one boot and append:

```text
systemd.mask=legion-powerctl.service
```

The key and menu differ between systemd-boot, GRUB, Limine, and rEFInd. Use the
on-screen help or your boot loader's documentation, then boot and disable the
service permanently with the command above.

**Then pick something safer.** Select a lower profile before re-enabling:

```bash
sudo legion-powerctl select quiet --apply
sudo legion-powerctl enable
```

If you are not sure which value caused it, `sudo legion-powerctl apply quiet
--dry-run` prints exactly what would be written without writing anything.

Instability under a *lower* power limit usually means the limit is too low for
the workload rather than too high - a starved package can stutter. Raise STAPM
first. Instability under a raised limit points the other way: back it off toward
the machine's stock envelope.

## `no compatible ryzen_smu kernel module found, fallback to /dev/mem`

This is informational when followed by `Successfully set ...`. RyzenAdj first tries a compatible `ryzen_smu` module and then falls back to `/dev/mem`. The apply operation is successful when RyzenAdj exits with status zero and prints successful setting lines.

Setting limits talks to the SMU mailbox and works without the module. Reading them back with `ryzenadj -i` needs the power-metric table, which the `/dev/mem` fallback often cannot provide: without `ryzen_smu`, an apply can succeed while still printing `Could not read the limits back ... this apply is unverified.`, and doctor's `Limits` line stays unavailable. Install `ryzen_smu-dkms-git` (AUR, listed as an optional dependency of the Arch package) to make verification work; see INSTALL.md for the lockdown and Secure Boot caveats. `./install.sh --install-ryzen-smu` does the whole job: headers, AUR build, `modprobe`, and a `modules-load.d` entry so it survives a reboot. Doctor's `SMU-backend` line reports which of these states the machine is in - it names the backend RyzenAdj will get and, when the device node is missing, whether the module is absent or merely unable to support this CPU.

## `WARNING: The kernel rejected writing BOOST=...`

The boost control file exists but the kernel or firmware refused the value. The rest of the profile - power limits, frequency range, EPP - was still applied; only BOOST was skipped, and `legion-powerctl status` shows `BOOST_APPLIED=no`.

`Invalid argument` (EINVAL) and `Operation not supported` (EOPNOTSUPP) both usually mean boost cannot be toggled on this machine. Run `sudo dmesg | grep -i boost` and look for `Cannot disable BOOST` or `Boost mode is not supported by this processor or SBIOS`, which points at Core Performance Boost being disabled in the firmware setup.

On CachyOS, the patched power-profiles-daemon toggles boost itself when the power profile changes (power-saver disables it), so a profile combining `POWER_PROFILE=power-saver` with `BOOST=on` will fight it. Set `BOOST=unchanged` or align the two settings.

`legion-powerctl doctor` prints the boost control in use and its current value on the `Boost-control` line.

## `request_table_ver_and_size is not supported on this family`

Recent CPU families such as Fire Range may accept adjustments while the monitoring table remains unsupported. Do not use `ryzenadj --info` as the only success test on those systems. Check the direct apply output and the systemd exit status.

## Service shows `active (exited)`

That is correct. `legion-powerctl.service` is `Type=oneshot` with `RemainAfterExit=yes`. It ran once and no process remains.

## Service failed with `203/EXEC`

The executable in `ExecStart` is missing or not executable. Check:

```bash
command -v legion-powerctl
command -v ryzenadj
systemctl cat legion-powerctl.service
```

Reinstall the project with `./install.sh` after ensuring `ryzenadj` (AUR, 0.19.0 or newer) is installed.

## Settings disappeared after suspend or Fn+Q

Some firmware actions reinitialize the SMU and overwrite userspace limits. This project intentionally installs no timer. Reapply explicitly:

```bash
sudo legion-powerctl apply
```

To find out whether that has happened, run `sudo legion-powerctl doctor` and read the
`Limits` line. It reads the limits back out of the SMU and compares them to the active
profile, so it distinguishes "applied and still in force" from "applied, then
overwritten". The check needs root; an unprivileged `doctor`, which is what the GUI
runs, prints no `Limits` line at all rather than a warning it cannot act on.

## The CPU still gets hotter than `TEMP_C`

Two different things are usually going on, and they have different answers.

**Check which sensor you are reading.** `TEMP_C` becomes RyzenAdj's `--tctl-temp`, which
governs **Tctl**. On Zen 4 and Zen 5 the kernel's `k10temp` also exposes per-CCD sensors
(`Tccd1`, `Tccd2`), and most monitors label one of those, or a package maximum, simply
"CPU". A CCD hotspot is expected to read above Tctl, so `Tccd1` at 95 C with an 82 C
Tctl cap is not a failed cap. Compare like for like:

```bash
sensors k10temp-pci-*
```

**Check that the profile is not widening the machine.** `MAX_FREQ_MHZ=stock` does not
mean "leave the frequency alone" - it resolves to the highest ceiling the hardware
advertises, which on `amd-pstate` is the boost frequency, and it is then written to
every CPU policy. `BOOST=on` likewise force-enables boost rather than leaving it as
found. Either can raise peak temperatures at an unchanged power limit, because the
package can reach a higher voltage and frequency in a burst while the sustained average
the power limits govern is unchanged. Since 0.3.0 an apply that raises a limit says so:

```
WARNING: MAX_FREQ_MHZ=stock raised the ceiling from 3200 MHz to 5460 MHz on 32 policy(s)
```

If you want a profile that only ever caps, set `MIN_FREQ_MHZ`, `MAX_FREQ_MHZ` and
`BOOST` to `unchanged`, which is what the shipped profiles do. `stock` remains the right
setting for `restore-frequency`, whose job is to undo a cap.

## The GUI does not start, or never appears in the menu

Run `legion-powerctl doctor` and read the `GUI` line. It reports the three
things that have to line up:

- the launcher at `/usr/bin/legion-powerctl-gui`,
- an importable `PySide6` (`sudo pacman -S pyside6`),
- the polkit policy in `/usr/share/polkit-1/actions/`.

`pyside6` is an optional dependency of the package, so `pacman -S legion-powerctl`
alone installs a launcher that only fails when clicked. `./install.sh` installs it
by default unless `--no-gui` was passed.

If the application menu has no entry after a `--script-install`, the desktop
database was not refreshed:

```bash
sudo update-desktop-database /usr/share/applications
sudo gtk-update-icon-cache -f /usr/share/icons/hicolor
```

## `RyzenAdj-version 1.55`, or the wrong ryzenadj is being used

RyzenAdj has no `--version` flag. Pre-0.3.0 parsers misread the usage text and
always reported `1.55`, so the minimum-version check never fired. Read it
directly with:

```bash
ryzenadj --help | grep -i '^Version'
```

`doctor`'s `RyzenAdj-shadow` line reports how many `ryzenadj` binaries are on
`PATH` - more than one is typically an old `make install` source build in
`/usr/local/bin` sitting in front of the packaged `/usr/bin/ryzenadj`.

This is normally an `OK` row, not a warning. legion-powerctl picks the
**newest** of the candidates rather than the first, so the shadow does not
affect the tool; the row names the one it chose and the ones it passed over,
because typing `ryzenadj` by hand still runs whichever comes first on `PATH`.

It turns into a `WARN` only when one of the candidates does not print a version
its `--help` banner can be parsed from. Then "newest" cannot be proven and the
choice falls back to `PATH` order, so the line names the binary it could not
read. Fix that one, or pin a binary with the environment variable below.

Candidates at the *same* version are reported as `Same version:` rather than
`Stale:`, and the line does not offer to delete them. That tie is broken by
`PATH` order rather than by recency, and on a default Arch `PATH` the binary
that loses it is the packaged `/usr/bin/ryzenadj` - which is a hard dependency,
so deleting it is exactly the wrong move.

The tool never removes a shadowing binary - no package owns `/usr/local` files
- so deleting it is your call:

```bash
command -v -a ryzenadj
pacman -Qo /usr/local/bin/ryzenadj     # "No package owns" confirms it is yours
sudo rm /usr/local/bin/ryzenadj        # only after that check
```

To pin a specific binary regardless of `PATH`, set
`LEGION_POWERCTL_RYZENADJ_BIN`. For the boot service:

```bash
sudo systemctl edit legion-powerctl.service
# [Service]
# Environment=LEGION_POWERCTL_RYZENADJ_BIN=/usr/bin/ryzenadj
```

## `Not identified as a Lenovo Legion` on a Legion

The warning is cosmetic and does not stop anything. On Lenovo firmware
`product_name` holds the machine-type code (`83RU`) rather than the model, so
the model name has to be read from the other DMI fields. Confirm what your
firmware reports with:

```bash
cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name \
    /sys/class/dmi/id/product_family /sys/class/dmi/id/product_version
```

## `Pacman is currently in use`

Do not delete `/var/lib/pacman/db.lck` while a package manager is running. Finish or close Discover, the CachyOS updater, `paru`, `yay`, or another Pacman transaction. Remove the lock manually only after verifying it is stale.

## `powerprofilesctl` is unavailable

RyzenAdj limits can still be applied. Install the power-profile implementation used by the desktop, or set `POWER_PROFILE=unchanged` in the profile.

## Profile validation failed

The tool requires integer watts, an integer temperature, and ordered power limits:

```text
STAPM_W <= SLOW_W <= FAST_W
```

Run:

```bash
legion-powerctl show PROFILE
legion-powerctl doctor
```

Then update the profile through `sudo legion-powerctl configure ...` rather than editing around validation.

## Confirm boot persistence

```bash
systemctl is-enabled legion-powerctl.service
systemctl show legion-powerctl.service \
  --property=LoadState \
  --property=ActiveState \
  --property=SubState \
  --property=Result \
  --property=ExecMainStatus
journalctl -u legion-powerctl.service -b --no-pager
```

Success is `enabled`, `active`, `exited`, `success`, and exit status `0`.
