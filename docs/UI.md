# UI design decision

The main window is `legion-powerctl-gui`: PySide6, unprivileged, bridged to the
CLI through pkexec. The CLI remains first-class, and every UI surface maps onto
an existing command.

## How Linux desktop theming actually works

There is no distro-agnostic app template that each distribution recolors.
An application chooses a toolkit, and the running desktop environment paints
that toolkit:

- **Qt on KDE Plasma**: the `plasma-integration` platform theme supplies the
  user's color scheme, fonts, and icons, and the Breeze QStyle draws the
  widgets. Any plain Qt app therefore automatically matches the desktop -
  including CachyOS's look, which is simply KDE Plasma plus their Emerald
  color scheme and Qogir icons. Zero theming work in the app.
- **GTK3 on KDE**: followed reasonably well via Breeze-GTK synchronization.
- **GTK4/libadwaita**: deliberately does not follow system themes; on KDE it
  keeps the GNOME look. That rules it out for a KDE-first tool.
- **Qt on GNOME**: close-but-not-native via Qt's gtk3 platform theme -
  an acceptable compromise in the other direction.
- Self-rendering stacks (Tauri webview, Slint, egui, iced) paint their own
  style and never inherit Breeze; they lose the "looks native" goal.

Kirigami is KDE's QML framework for KDE-HIG apps; through qqc2-desktop-style
it is also painted by the system QStyle. It is the phase-2 option, not the
starting point.

## Chosen stack

**PySide6 (LGPL) + Qt Widgets.**

- Native Breeze/CachyOS appearance for free when it is asked for
  (`LEGION_POWERCTL_GUI_SCHEME=desktop`), acceptable on GNOME.
- Python is the closest maintenance fit to a Bash project; no C++/CMake/ECM
  toolchain to carry.
- Form-heavy UI (sliders, combo boxes, checkboxes) is exactly what Qt Widgets
  is best at.

Phase 2, only if System Settings integration proves worth it: Kirigami/QML
and a KCM using KAuth.

## Visual language

The window answers one question: **what limits is this machine running right now, and
will it still be running them tomorrow?** A strip across the top holds the answer in
two cells - `RUNNING NOW` is the apply on record, `AT BOOT` is the boot pointer - and
under it sit a rail of profiles, two cards of limits, a policy card, a disclosure, and
one verb pinned below them.

The two are distinct and nothing keeps them in step. The running cell comes from
`last_apply`, the record the CLI leaves in `/run`; the boot cell is the pointer in
`config.conf` that the boot service reads. The word "active" is not used in the
GUI, because it does not say which of the two it means.

The running cell is the window's readout, and the one loud thing in it. Its top line is
the apply record - the `confirmed`, `unverified` or `limits did not take` badge and when it
happened - and under it the running profile's name, at the size of the editor's title,
sits beside the four limits it is running: sustained, slow PPT, fast PPT and the ceiling,
each a large tabular figure over a small caps caption. When the readback disagreed the
figures turn the FAIL colour, because what they show is what was asked for and not what the
machine holds; before anything has been applied the cell says so in one quiet sentence
instead. The figures are painted (`strip_widgets.Readout`) on a `QLabel` that keeps the
summary - `45/50/60 W, 78 C cap` - as its text and its accessible name, so a screen reader
hears the limits in the same words as on the profile row and the tree gains no node for the
captions. `AT BOOT` stays a plain name on purpose: the boot profile is a pointer, and its
limits are one glance away on its row. As the window narrows, the readout first closes the
gaps between its figures and the `AT BOOT` cell gives up its spare width; when the two cells
and the actions still do not fit side by side, the boot switch and the checks badge move to a
row of their own under them. Only after that, at the narrowest sizes, does a long running
name give way, and when the badge and the time above it still do not fit, the boot name gives
up the rest. A name that gives way is cut short with an ellipsis on screen while its text and
accessible name stay whole, so a figure, the badge or the time is never the thing that is cut.

What holds the look together is that **colour is written down in exactly one
module**. By default the window runs Qt's Fusion style with the Legion scheme: a warm
paper plane by day, a deep navy plane by night, one teal or mint accent. `scheme.py`
holds those two palettes as `QPalette` role values, picks one from the desktop's colour
scheme (or, when the desktop does not say, from the lightness of the palette it handed
over), and swaps it live when the desktop flips. Every other colour is still derived from
whichever palette is installed - `theme.py` fits each one to its contrast floor and
`styles.py` writes it into the stylesheets - and `test_package_shape.py` fails the build
on a colour literal in any other module. A colour in the source is the one thing on
screen the user's scheme does not get to choose, so the scheme's colours sit where the
contrast tests measure them, and `LEGION_POWERCTL_GUI_SCHEME=desktop` hands the choice
back: the platform style and the desktop's own palette return, and the same derivations
run on them.

The accent is `QPalette.Highlight`, fitted to the 3:1 non-text floor, and it carries
what is running and what acts: **the rail marking what is running**, in the strip and on
its row; the primary button and the switch when it is on; the envelope's filled tiers;
focus rings and the status bar's links. The selected row is a twelve percent tint of
it. The boot profile deliberately gets no accent: it is a different fact, and it wears
an ink `BOOT` pin instead. Under the Legion scheme the accent is teal by day and mint
by night; under `desktop` it is whatever the desktop chose - the mint the Waybar mockup
was drawn in on CachyOS, blue on Breeze, and on a high-contrast scheme whatever that
scheme chose. Card surfaces come from `Base`, hairlines and secondary text from a
measured step between `Window` and `WindowText`.

Three panels are painted rather than laid out, and all three were forced:

- **Profile rows** (`profile_delegate.py`). A `QListWidgetItem` draws one string in
  one weight, so a plain row cannot set a name apart from its numbers. The delegate
  paints two lines: the name with the sustained wattage in a monospaced column at the
  right, and under it the envelope with its pin at the right. The running profile
  gets a 3 px accent rail on the row's left edge. A theme's `power-profile-*` icon,
  where the theme has one, sits on the name line just before the wattage, so it never
  takes width from the envelope: at the default rail width every envelope and its pin
  fit whole, and the suite checks that with an icon forced in. The delegate draws its
  own focus rectangle, because a custom paint replaces the style's (WCAG 2.4.7); it
  changes nothing the keyboard or a screen reader sees, both of which read the item's
  roles, and the row's accessible text names both marks in words.

  **The pin is a click target, not a control.** Painted things have no AT-SPI node
  and Tab cannot land on them, so the real control is a `QAction` on the list - the
  Menu key opens it, and a screen reader reads it - with the pin as a shortcut. It
  says `BOOT` when it is the state and `SET BOOT` when it is the offer: one word in
  two weights read as *this is the boot profile* on the row under the pointer, which
  is the opposite of what clicking it does.
- **Diagnostics are a dialog** (`dialogs.py`). Thirteen checks used to sit in a strip
  nailed to the bottom of the window. On a healthy Legion that strip permanently
  showed two or three orange chips - historically a second `ryzenadj` on `PATH` and a
  missing `ryzen_smu` module - none of which a user acts on, and a window that always
  shows warnings teaches its user to stop reading them on the first day. One badge at the
  top of the window carries the count and its severity; the list is one click behind it, worst
  first. Those two examples are no longer warnings at all: the doctor now reports a
  resolved `ryzenadj` shadow as `OK`, and reports the module state as one
  `SMU-backend` line rather than two rows for one cause.
- **The power envelope** (`envelope.py`). Three sliders drew three independent
  numbers, and these three are nested: the CLI refuses them out of order and the
  editor pushes the neighbours to keep them in it, so dragging one past another moved
  two sliders elsewhere in the form with nothing on screen saying why. One track with
  a stop per tier makes the constraint the picture. The thermal ceiling is the same
  widget with one stop, so both cards read alike.

  **The stops are still `QSlider`s.** Each is a subclass whose `paintEvent` does
  nothing and which carries `WA_TransparentForMouseEvents`, so the bar hit-tests
  across all of them at once while Qt keeps the arrow keys, Page Up/Down, Home/End,
  the focus chain, and `QAccessibleSlider` - role, name, value, minimum and maximum,
  reported to AT-SPI for free. That is not a convenience: PySide6 exposes no
  `QAccessibleWidget` to subclass, so a hand-written `QAccessibleValueInterface` was
  never available here at any price, and a genuinely custom widget would have
  announced as an unnamed graphic with no number in it.

  The values sit in spin boxes under the bar rather than painted at the stops. At
  60/65/75 on the CLI's 5-200 W range three labels sit two and a half percent apart,
  so they collide and have to be pushed off the stops they name; and a spin box is
  the only thing here anyone can type an exact wattage into. Each box is as wide as
  its widest value. On a narrow window the row wraps (`flow.py`), but it closes its gaps
  first, so a scroll bar appearing cannot by itself push a value onto a second line -
  which would make the card taller and keep the scroll bar there.

  Nothing is drawn straight onto the fills. Each stop marker, and the focus ring
  around it, sits on a plate of the card's own colour, and the ends of the scale are
  labels beside the bar rather than text inside it. A mark spanning two tiers has two
  backgrounds and no single colour is guaranteed to clear the floor against both - on
  a scheme whose `Highlight` is near-white over a near-black `Base` they want opposite
  lightnesses. One known colour behind a mark is what makes its contrast a number.

Besides the readout, two smaller pieces are painted and keep their native roles. The
`Re-apply at every boot` switch is a `QCheckBox` whose `paintEvent` draws a track and a
knob, so AT-SPI still reads a check box with its mnemonic. A card's title is an eyebrow
painted over a `QGroupBox` that keeps the mixed-case title as its accessible name, so a
screen reader hears each card named once and the tree gains no text node for it.

## Privilege architecture

The GUI never runs as root - Wayland sessions (CachyOS default) refuse root
GUIs, and polkit's own guidance is a minimal privileged helper.

- One polkit action namespace: `io.github.alexmacra.legion-powerctl.*`, with
  one action per subcommand pinned via `exec.argv1`. Two trust tiers -
  auth_admin_keep on configure/apply/select, always-prompt on
  delete/enable/disable; SECURITY.md has the action table and why the split
  holds.
- Implemented (GUI v1, widgets, waybar): `pkexec /usr/bin/legion-powerctl <cmd>`
  behind those actions. The GUI validates every argument through its model
  layer (profile names against the CLI's own `[A-Za-z0-9][A-Za-z0-9._-]*`
  rule) before building the command.
- Phase 2: a small root D-Bus system service (D-Bus activated, polkit
  `CheckAuthorization` on every call) whose implementation shells out to
  `legion-powerctl` with validated arguments only. This is CoreCtrl's proven
  pattern; it removes the per-invocation pkexec round-trip and the same
  helper would serve a tray widget or a KCM.

## Desktop integration

- freedesktop `.desktop` entry (`desktop/legion-powerctl.desktop`).
- Scalable SVG icon and a monochrome `-symbolic` variant under
  `/usr/share/icons/hicolor/` so Breeze can recolor it with the theme.
- polkit `.policy` in `/usr/share/polkit-1/actions/`. D-Bus service files
  arrive with the phase-2 helper.

## Accessibility

Target: WCAG 2.2 AA where it applies to a desktop application, plus the Qt/AT-SPI
conventions a Linux screen reader depends on.

**Labels.** A control is announced either by its own accessible name or by the
`Label` relation Qt builds from the `QLabel` that `QFormLayout` made its buddy.
Both count, and the offscreen suite asserts every form control has one of them.
The distinction matters: Qt on Linux deliberately reports a combo box's *value*
as its accessible name and hands the label over as a relation. The four stops and
four spin boxes have no `QLabel` of their own for that search to find, so those carry
explicit names. The legend's visible label is deliberately not their buddy: Qt would
then hand a screen reader the same one string for a stop and for the spin box beside
it, which is exactly what tells them apart.

**Colour.** `theme.py` derives the four severity colours from `QPalette`. A hue is
fixed per severity and the lightness is walked away from the window colour until
the contrast clears 4.5:1; the focus ring clears the 3:1 non-text floor. This is
always solvable: the hardest possible background sits at relative luminance 0.179,
where black and white both reach 4.58:1. Nothing is a colour alone - the doctor
chips print `OK`/`WARN`/`FAIL` in their text and the service badge does too. Fusion
draws the frames of spin boxes, combo boxes and line edits, and the edges of a scroll
bar's thumb, from the palette's `Window` rather than from any role meant for them, so
under the Legion scheme those classes get a palette of their own whose `Window` lands
those edges at 3:1. The suite measures that on rendered pixels, not on the palette.

**Announcements.** Qt Widgets has no live region. Saves, doctor results and
validation errors go through one helper that posts Qt 6.8's announcement event,
which carries the text itself. The older `Alert` event, used when PySide6 predates
that, announces a widget's *name* instead, so the fallback renames the widget and
that name then outlives the message - which is why it is the fallback. Only errors
are assertive; everything else waits its turn. A message is announced once per
change, which matters most for the message a broken profile shows, because the
fifteen-second poll re-selects the same row and would otherwise repeat it forever.

**Keyboard.** Every control carrying a mnemonic claims a different letter; the form
labels deliberately have none, because a label that names a stop has no focus to hand
it. Each stop answers the arrow keys, Page Up/Down and Home/End, and pushing one past
a neighbour moves the neighbour - so the constraint the bar draws is reachable without
a mouse. Its focus ring is painted, because a custom paint replaces the style's own;
so are the rings of the two frameless scroll areas, the editor and the checks list,
which would otherwise take focus and show nothing, and the boot switch's, which shows
for any focus the pointer did not cause and keeps its state when the window hands the
focus back, after a command or on reactivation.
Setting a boot profile is a `QAction` on the list, so the Menu key reaches it; the
painted pin is a mouse shortcut to the same signal. Saving without applying is
`Ctrl+S` and a `Save` button on the discard prompt, which is the moment work would
otherwise be lost. The rows of the checks dialog are focusable, since their detail was
otherwise mouse-only. That dialog also carries a `Copy report` button (`Alt+C`) that
puts the doctor's own output, prefixed with the tool versions, on the clipboard - the
one thing a user needs when reporting a problem. Its row text is selectable by mouse
but not by keyboard, so selecting does not add two tab stops per row, and `Ctrl+C` was
deliberately left to that selection rather than bound to the button.

**Reflow.** Minimum 720x480, so the window fits a 200%-scaled 1080p desktop. The editor
column scrolls between a title above and, below, the problems callout and `Apply now`,
which stay put, so the verb and the reason it is unavailable are on screen at every
size, and the field being typed in is scrolled back into view when the callout appears; at the default 960x620 the form fits without scrolling until Advanced is opened.
A rail dragged wide cannot squeeze the editor below its own minimum, and at a font too
large for the window the editor scrolls sideways rather than cutting anything off.

Known gaps, deliberately not addressed yet:

- `desktop/legion-powerctl-symbolic.svg` uses GTK's `#bebebe` recolour sentinel,
  which Breeze does not honour, leaving it at roughly 1.8:1 on a light panel.
- No AppStream metainfo.
- **Every contrast number here is computed, not observed.** No automated check
  replaces one pass with Orca, and that has not been done.

## Interface images

The main-window image is captured from the running PySide6 application with
representative profile and diagnostic data - offscreen (`QT_QPA_PLATFORM=offscreen`),
driven by the test fixtures, so it can be regenerated on any machine and cannot go
stale in the way the previous one did. Three things follow from that and are worth
knowing when reading it: it shows the default look, Fusion with the Legion scheme; in
its light palette, because offscreen the desktop's colour scheme reads as unknown and
the palette it falls back to is light; and without power-profile icons, because
offscreen there is no icon theme to find them in.
The Waybar image remains a design mockup drawn in Breeze Dark with the CachyOS
Emerald accent.

| Image | Type and implementation status |
|---|---|
| [gui-main-window.png](design/gui-main-window.png) | real application screenshot, rendered offscreen under Fusion with the Legion scheme; implemented as `legion-powerctl-gui` |
| [waybar.png](design/waybar.png) | design mockup; implemented as `status --waybar` |
