# Orientr: notes for developers

## Files

| File | |
|---|---|
| `orientr.cmd` | the `orientr` command (runs the tool with the model's Python) |
| `orientr.py` | the app: the command line, `bambu.json` and the form's choices, the report, Analyze, the update check, the self-test, the own window and the terminal it was typed in |
| `orientr_core.py` | slicer-independent: the SOMA model and its meshes, the geometry, the orientation, the rules for support, brim, walls and infill, packing the plates |
| `bambu_project.py` | Bambu Studio: finding it, the templates and presets, writing the 3mf, the test slice and its warnings, its settings file, the background start, its version |
| `orientr_form.py` | the console form |
| `bambu_studio.py` | Bambu Studio in the background: hidden start, keeping it hidden, and the guard process that closes it (standard library only) |
| `orientr_i18n.py` | all texts in English, German and French, and the user settings (`%LOCALAPPDATA%\orientr\settings.json`) |
| `bambu_templates.py` | template helpers (describe, import, save) |
| `orientr_banner.py` | the "Orientr" header |
| `orientr-logo.ico`, `assets\` | the logo: the shortcut icon (16 to 256 px on a dark circle, each size with the design's own drawing for it: no nozzle up to 24 px, thicker edges up to 64 px) and the same icons as PNG in `assets\icons\`, both made by `python assets\make_icons.py`; `assets\orientr-logo.svg` / `assets\orientr-logo-dark.svg` (logo with wordmark, light and dark) for the README and `assets\orientr-avatar-512.png` for the GitHub organization; the terminal version is in `orientr_banner.py`: the design's 59 x 26 pixel lockup (logo and wordmark) taken over exactly, 62 columns with its indent, so it fits the SOMA terminal (63) too |
| `templates\` | one Bambu Studio project per printer; `templates\README.md` says where their settings come from (AGPL-3.0) |
| `install.cmd`, `install.ps1`, `uninstall.cmd`, `uninstall.ps1` | setup and removal for one Windows user |
| `VERSION` | the version the update check compares with `VERSION` in `RELEASE_REPO` (the release repository) |
| `CHANGELOG.md` | what changed in each version, and where it came from (a tester, or noticed ourselves) |

## Version numbers

The test phase of Orientr starts at **0.0.1** (2026-11-22: both repositories started again with one commit;
2026-11-23: the release repository's 0.0.1 replaced once more, user's choice, before any tester had it). From there every release raises `VERSION` by exactly one step, chosen by the
biggest change in it:

| Step | When | Example |
|---|---|---|
| `0.0.x` → `0.0.x+1` | a fix, a text, a layout or a speed-up; nothing to learn for the user | 0.0.0 → 0.0.1 |
| `0.x.0` → `0.x+1.0` | something new or different to use: a field, an option, a rule, a changed default | 0.0.3 → 0.1.0 |
| `1.0.0` | the end of the test phase: the first version for everyone | |

- Changes collect under **Unreleased** in `CHANGELOG.md` as they are made, each with its source: *(tester)*,
  *(own)* or *(review)*. A release turns that heading into the version and the date.
- One version per release, never reused or lowered: installed copies only report a version higher than their own.
- `VERSION`, the README example (`Orientr x.y.z: up to date`) and the release commit
  (`Orientr x.y.z`) always carry the same number.

## Releasing

Development happens in a private repository with the full history; a release is a single fresh commit in the release
repository `RELEASE_REPO` (`orientr.py`), made from a clean `git archive` of the development repository, added on
top of the previous release (never a force push after 0.0.1: testers' copies follow that history). Commits are made
with the GitHub no-reply address (set in this repository's git config).

1. Raise `VERSION` (see above) and the version in the README example; in `CHANGELOG.md`, Unreleased becomes the
   version with the date.
2. Commit and push the development repository.
3. In a clone of `RELEASE_REPO`: delete the tracked files, unpack `git archive HEAD` of the development repository,
   commit as `Orientr x.y.z`, push.

## The three parts of the code

- `orientr_core.py` imports neither of the others; `bambu_project.py` imports only the core; `orientr.py` imports both
  and makes all their names reachable as `orientr.<name>` again (`from ... import *`): the form and
  `bambu_templates.py` are handed this module and need nothing else.
- The core still writes its choices as Bambu Studio setting names (`enable_support`, `brim_width`, `wall_loops`, ...)
  and reads the printer from a `Template` (bed, no-go zones, nozzles, prime tower). A second slicer needs its own part
  (`<slicer>_project.py`) that offers the same: a printer description with those attributes, a project writer, and a
  translation of those setting names.
- Slicer-specific names stay per slicer: `bambu.json`, `output\bambu`, `bambu_studio.py`, `bambu_templates.py`,
  `bambu_project.py`.

## To do

Open (user's list, 2026-11-23), in this order:

1. Done: one filament per color made by the tool (`expand_filaments`, see "Filaments made by the tool").
2. Done: form, Colors: "Auto from SOMA model" or "Manual · <color>" (Bambu Lab's colors of the chosen filament);
   Filament never blocked; C in Parts picks a part's color from that list. With filaments made per color every part
   goes by its color, merged ones too (`by_colour`; a `"filament": N` from bambu.json is ignored there), and with
   Manual a merged part keeps its model color. The preview names colors as Bambu does (Turquoise).
3. Done: keys G, A, C (German G A B, French G A N); the header stays while generating (scroll region) and analyzing.
4. Done: title "Export From SOMA to Bambu, Print-Ready" on two lines. In a 30-row cmd window the header stays and the
   form scrolls under it (user's choice 2026-11-23, of: compact header with a dense form, or the logo beside it).
5. Done: prime tower kept on the bed (`_tower_spot`), packing by outline (`outline`, `_place`), colors grouped per
   plate (`colour_changes`, `_colour_orders`).
6. Done: color mixing ("PLA palette"), see "Color mixing". Checked in the window by the user (2026-11-23): a CMYKW
   project with 5 physical and 4 mixed filaments loads without messages and slices.

Found in the self-test of 2026-11-23:

- Done: Analyze results taller than the rows under the header scroll with ↑↓ (they were cut with "…").
- Done: Nozzle *auto*: a layout Bambu Studio refuses on one nozzle's area is made again at the same level without
  that area before a roomier level is tried (`retry_layout`; the Lid: 1 plate as with *right only*, before 2).
- Note: the update check falls back to `gh api` (the GitHub login of whoever runs it, on their own PC) when the release
  repository is private; off with `ORIENTR_NO_UPDATE_CHECK=1`.

After that list (2026-11-23, user's wishes):

- Done: *Background Bambu Studio* in the form: ←→ only choose, Enter carries it out, the state beside the field
  (a0cc1f4, bceb7b4; see "Bambu Studio in the background").
- Done: ⚠ and orange text on Colors and Parts when something is wrong, the Parts hint says why (ba3ebe9).
- Done: plates centered, support room at a nozzle area's edge, parts in openings (ccd7cf5, 628da89, bdd5a24; see
  "Plate layout").
- Checked by the user: `orientr` typed in a terminal opens its own window; colors and font size look right.
- Open: the background Studio tried by hand with a real Studio (Yes+Enter starts it hidden, No+Enter really closes
  it, a visible Studio stays, quick Yes→No→Yes, the state follows); a second review of those commits.

## Future features

The user's wishes for later versions (list started 2026-11-24). Work out the details with the user before building.

- **Advanced menu**: a separate menu for deeper settings, so the main form stays short.
- **Max time**: an option for the maximum print time (like *Max plates*). Still to settle: per plate or in total,
  and what happens when it is exceeded.

## Self-test of 2026-11-23 (what was checked)

Static: compile, pyflakes (names from `import *` checked against the modules), the form's `sb.` names, i18n keys and
placeholders in en/de/fr. Privacy: report, 3mf (all files), templates (account metadata), network calls. Units:
`expand_filaments` on all 15 templates × 1/2/5/32 slots × with a mix × another filament or nozzle size (315 cases),
compared with a 32-filament project of the window; `slot_colours`, `snap_colours`, `mix_plan`, `nearest_filament`
with random and edge cases. Slices on A1, X1C, P2S, H2S, H2C, H3C, X2D, H2D (0.2/0.4/0.6) in every color mode. The
form driven with scripted keys through a terminal emulator (pyte) at 120×30, 63×51 and 63×20 in en/de/fr, with a
real Analyze and a real Generate. Fixed: every other nozzle size failed to slice (`print_compatible_printers`,
`extruder_nozzle_diameter`), the grey rule sent a mixed dark grey to white, list letters only jumped to M.

Then (2026-11-23, later) in real console windows instead of an emulator: a script opened Windows' own console
(conhost) and a Windows Terminal window, typed into them with `WriteConsoleInputW` (what `msvcrt.getwch` reads), read
the screen back with `ReadConsoleOutputW` and took pictures of the window (`PrintWindow`). Checked at 120×30 in
en/de/fr, the form in place (`SOMA_PROJECT` set) on a copy of a model: keys G A C / G A B / G A N (letters underlined;
B does nothing in French), Colors with ←→, Enter, letter jumps and Esc, C in Parts, Analyze and Generate with the
header on top the whole time (scroll region and own screen in both hosts), Generate with nozzle 0.6. Fixed: ◀ ▶ were
boxes in conhost (Consolas lacks them, ◄ ► it has), the header's status lines kept the old language after a switch,
two texts were English only. Not covered: the own window `orientr` opens when typed in a terminal (the form ran in
place), and how a person sees it (colors, font size).

## Color mixing (2026-11-23)

Bambu Studio (02.09.01.70) mixes colors from physical filaments in alternating sub-layers. A mixed filament is a
slot like the others, after the physical ones, with `filament_is_mixed` "1", `filament_mixed_components` "1,3"
(1-based physical slots) and `filament_mixed_sublayer_ratios` "0.7000,0.3000" (summing to 1; texts from
BambuStudio.dll), and the process needs `enable_mixed_color_sublayer` "1" (on by default only for the H3C). The
recipes are Bambu's measured ones, `resources/filament_mixing/standard_color_recipes.json`: CMYKW with PLA Palette,
CMYW and RYBW with PLA Basic, 2 or 3 components each. `mix_plan` gives each model color the nearest base color or
recipe, loads only the bases used, at most `MAX_MIXES` mixes (Bambu's own limit is not documented). Offered only on
printers with 2+ hotends (`hotends`: H2D, H2C, H3C, X2D): on one hotend every sub-layer is a filament change (Bambu
Studio warns of waste and clogging). Sliced on the command line (H2D, CMYKW, 9 filaments); mixing is slow (a
Testmodel plate 55 h instead of 22 h).

Not done (decided 2026-11-22): Dutch (English, German and French only), an option in the form to keep the terminal
open (`ORIENTR_KEEP_TERMINAL=1` stays for whoever needs it).

Tried on screen on 2026-11-22: the window on a small screen (display scale 200 % and a laptop: it fits, the form
scrolls to the buttons), the shortcut's message boxes (no SOMA model at all; SOMA's Python but no model), and
the presets message when they have to be read again (the shortcut's minimized window now comes to the front for it).
To try them again: start `orientr.cmd --shortcut` with `LOCALAPPDATA` pointing to an empty folder, or rename
`%LOCALAPPDATA%\orientr\profile-cache`. Not from SOMA's terminal: its `SOMA_PROJECT` makes Orientr behave as in SOMA.

## Bambu Studio's profiles

The form's lists (printers, nozzle sizes, filaments, processes) come from Bambu Studio's own system presets, read from
`%APPDATA%\BambuStudio\system\BBL` (else from Studio's installation). Reading them without the cache took 103 s on
2026-11-22 (machine 172 presets 6.7 s, filament 2233 presets 84.9 s, process 294 presets 11.4 s; about 10 ms per file
on a cold first open, Defender's real-time scan is the likely cause); with the cache in
`%LOCALAPPDATA%\orientr\profile-cache` (3 files) 0.25 s. When the files are still in Windows' memory, the same read
takes under a second, so the slow case is only seen cold (after installing, after a restart, after a Studio update).

- `install.cmd` runs `orientr.py --warm-profiles` with a SOMA model's Python, so the form opens at once later.
- `profiles_cached()` checks the cache keys from directory listings only (0.2 s); when they are not up to date,
  `announce_profiles()` says so before the wait: in the form, before the own window opens, and on stderr for
  command-line runs.
- Analyze's total time varies with the PC's load: 28-63 s measured on 2026-11-22 for a test model of 10 parts, with and without
  empty settings alike (slicing is mostly processor work).

## What the tool takes from SOMA

Not a documented interface, so a SOMA update may change it; `soma_checks()` (the SOMA lines of `--selftest`) tests
each on a built model: `.soma/build.json` (`status`, `started`, `finished`), `.soma/project.json` (`name`),
`.soma/model.map.json` (`parts[]`: `name`, `step_name`, `group`, `role`), the material names `<x>:<step_name>` in
`.soma/model.glb` (colors only), `output/model.step` read with CadQuery, and `soma.meshexport.export_mesh` (the
fallback is `python -m soma export --all --format stl`). A parts list that is not as expected raises the
`e.soma_changed` message.

## After a Bambu Studio update

`orientr --selftest` checks Studio's data files, the templates, a test slice of a cube (the formats this tool reads
back) and compares the Studio warnings copied into `studio_gui_warnings()` with Studio's source on GitHub. Otherwise:

- `warn ... saved with an older Studio`: open that printer in Bambu Studio and save it again as a template.
- `warn ... Studio's source changed`: read the named function in the source, adjust `studio_gui_warnings()`, then put
  the new fingerprint in `RULES_SOURCES` and the new version in `RULES_VERSION`.
- `FAIL`: Studio changed a file format this tool reads; fix that reader.
- `RULES_VERSION` is also the Studio version that counts as tested for every user (no `not tested yet` line):
  raise it only after `orientr --selftest` passed with that version.

Not covered by the self-test: the tested limits (overhang, bottom fillet, error -18), which only change on big releases.

## Bambu Studio in the background

- Bambu Studio ignores the show command it is started with: its splash (an owned pop-up) and its main window (own
  title bar, no `WS_CAPTION`, but `WS_MINIMIZEBOX`) take the focus, the main window while still invisible, and it
  shows itself once more after loading. `keep_hidden` hides them with `ShowWindowAsync` (Studio answers no messages
  while it loads, ~8 s, so `ShowWindow` and `AttachThreadInput` block) for as long as the form runs.
- In the form (2026-11-23) ←→ only change the choice; Enter calls `prestart_studio()` (Yes) or `cancel_prestart()`
  (No). `cancel_prestart` stops a start that still waits (`_PRESTART_CANCEL`) and, under `_PRESTART_LOCK` so it never
  crosses the delayed start, hands the form's own hidden Studio (`_HIDDEN_PID`, set by `_guard_studio`) to
  `bambu_studio.close_hidden` in a thread: WM_CLOSE as the guard does, never killed, its windows kept hidden
  meanwhile. Left alone when a main window is still visible after 1 s (in use; while starting it shows itself for a
  moment before `keep_hidden` hides it again), when the project was handed to it (`_STOP_HIDING`), and after 180 s
  without closing (a question from Studio: minimized in the taskbar, never left invisible).
- The state beside the field is `background_state()`, read on each redraw: *Opening* (the wait thread `_WAIT_THREAD`
  runs, or the process lives without a main window yet, `has_main_window`), *Open*, *Closing* (`_CLOSING_PID` still
  `alive`), *Closed*; None (nothing shown) when closing was given up (`_LEFT_PID`), so it never says *Closing* for ever.
- Studio attaches to its parent's console and writes debug lines into it, so it is started by a short-lived helper
  with an invisible console of its own (`start_studio`).
- The guard (`bambu_studio.py <form pid> <studio pid> <marker>`) is started with `CREATE_NO_WINDOW`: the model's
  `python.exe` is a launcher, and a detached console program gets a new, visible console.
- *Single instance* is `"single_instance"` in `BambuStudio.conf`, which ends with `# MD5 checksum`: the MD5 of the
  text above it with `\n` line ends and without the last line end. The tool changes it only while Studio is closed and
  only when the checksum matches.

## The terminal `orientr` was typed in

`orientr` typed in a terminal outside SOMA opens the form in a window of its own and then ends the shell it was typed in
(`close_calling_terminal`), with exit code 0 so that Windows Terminal closes the tab too. The shell is found in the
process snapshot: up past the Pythons (the model's `python.exe` is a launcher) to the first `cmd.exe`, `powershell.exe`
or `pwsh.exe`; a `cmd.exe /c` whose parent is PowerShell only runs `orientr.cmd`, so that PowerShell is the one. Only a
shell of its own window or tab is ended: one started by `WindowsTerminal.exe` or `explorer.exe` (`TERMINAL_HOSTS`). A
shell in VS Code or another IDE, a shell started by another shell, or anything else in between (Git Bash): nothing is
closed. Skipped in SOMA, under Claude Code (`CLAUDECODE`) and with
`ORIENTR_KEEP_TERMINAL=1`. The form's own window closes by itself when the project is made or canceled, and waits for a
key only after an error.

## Fitting the header in cmd, PowerShell and SOMA's terminal (2026-11-23)

Everything depends on the console's size in columns and rows: the sizes are in `orientr_banner.py`, the choice of
header in `orientr_form.py`.

**Which window.** `orientr` typed in cmd or PowerShell opens the form in a window of its own (Windows Terminal, or
Windows' own console when Windows Terminal is missing or not the default terminal app): Orientr sets its size
(`window_size`). In SOMA's terminal panel the form runs in the panel itself: the user sets its size. So there are two
cases: the own window and SOMA's panel.

**The full header's sizes.**

| Size | Value | From |
|---|---|---|
| Logo with wordmark | 59 × 24 pixels: 59 columns × 12 rows | two pixels per character (▀) |
| Title | text rows 1 and 2, right of the nozzle, each line centred on the wordmark (lockup column 42.5) | `TITLE`, `TITLE_ROW`, `WORD_MID` |
| Width with indent | 2 + 59 = 61: title and version checks stay inside it | `WIDTH` |
| Height | 12 rows + 1 empty row = 13 rows | `HEIGHT` |
| Version checks | text rows 9 to 11 under the baseline, right of the plate, at most 3 lines | `STATUS_ROWS`, `status_place` |

Colours: the plate's edge and the baseline use the terminal's own text colour (`PALETTE["W"] = None`), so they show on
a dark and a light terminal alike; all other colours are fixed.

**Where the version checks go** (`status_place`, the user's markup of 2026-11-23): on the lowest rows of
`STATUS_ROWS`, the shortest line on top (the plate's edge slants away to the left, so the lowest row has the most
room), all lines centred on one common middle. That middle stays as near the wordmark's middle as the room allows:
each line starts at least one empty column right of the plate on its own row (lockup columns 24, 20 and 16 on rows 9,
10 and 11) and ends at the header's right edge (61). So a version number a few characters longer still fits; checked
2026-11-23 for en, de and fr: "up to date" with versions two characters longer fits, an update or untested warning
(47 to 61 columns) does not and goes under the header.

**Rule 1: the full header with the version checks under the baseline** (`_head`), only when all of these hold:

1. Width: at least 62 columns, 61 plus one: the last column is never written (there the cursor waits to wrap, and the
   animation's erase-to-end-of-line would wipe the last letter).
2. Version checks: `status_place` finds room for them (see above).
3. Height: header and form must fit; the form scrolls under the header, so 13 + 14 = 27 rows are enough
   (`SCROLL_ROOM = 14`).

**Rule 2: otherwise a smaller header.** `_banner` takes the first that fits:

| # | Header | Minimum width | Rows |
|---|---|---|---|
| 1 | Full header, with indent | 62 columns | 13 |
| 2 | Full header, without indent | 60 columns | 13 |
| 3 | Compact: `◆ Orientr  Export From SOMA to Bambu, Print-Ready` | 52 columns | 2 |
| 4 | Mini: `◆ Orientr` | 12 columns | 1 |
| 5 | No header | — | 0 |

Under it the header leaves room for the form: as many rows as the form has, but never more than 14. Here the version
checks are not in the header but stay in the form, under it.

**Rule 3: the own window (cmd and PowerShell).**

- Width: the widest of the header (62), the version checks, the project line, the menu and the key legend, each with
  some room to spare; never wider than 110 columns (`WINDOW_MAX_COLS`).
- Height: the full height of the work area, from the top of the screen down to the taskbar (`_center_own_window`). On a
  1080p screen that is room enough for the full header and the whole form.
- Another language: Windows' own console is resized with `mode con`. A program cannot resize Windows Terminal; there
  the value column gives way.

**Rule 4: SOMA's terminal panel.**

- Orientr cannot resize the panel: it takes the largest header that fits (rule 2).
- The full header with the version checks under the baseline needs a panel of at least 62 columns and 27 rows. SOMA's
  panel is 63 columns by default: the description takes two lines to fit it.
- 60 or 61 columns: the full header without indent, the version checks under it. 52 to 59 columns, or too low for
  the full header: the compact header, the form scrolling under it.

**Rule 5: always.**

- The header appears only in a real terminal with colour (`isatty`, on Windows virtual terminal processing); piped
  output and tests stay plain.
- `ORIENTR_NO_ANIMATION=1` shows it at once, without the animation.
- During Generate and Analyze the header stays on the top rows, only when that leaves at least 8 rows for the output.

## Size guard

Duplicates and copies go up to `MAX_COPIES` (200) each; `check_volume` refuses a project of more than `MAX_OBJECTS`
(500) objects or `MAX_TRIANGLES` (5 million) triangles before anything is packed, and a `MemoryError` while packing or
writing becomes a normal message. The form checks the number of objects itself before Generate and Analyze.

## Where Analyze's time goes (measured 2026-11-22, a test model of 10 parts, H2D, ASA, 0.16mm Standard)

| Step | Time |
|---|---|
| preparing the parts (`make_project`, fresh process) | 7-9 s: loading CadQuery 2 s, reading the STEP 1 s, meshing 1.6 s, orientation 2 s (its largest part 1 s) |
| Bambu Studio's start-up (slicing a 20 mm cube) | about 1 s (3 s the first time) |
| Bambu Studio slicing the project | 17-21 s |

After a long pause the first preparation once took 37-51 s instead of 8 s (not reproducible on demand; most likely
CadQuery's libraries, about 140 MB, read from disk again). `preload_libraries()` therefore imports CadQuery, SOMA's
mesh export and scipy in a background thread as soon as the form opens: 4.9-5.4 s instead of 7.2-9.1 s when you
take a few seconds in the form, no slower when Analyze is pressed at once (the import lock makes it wait). The
project is the same (all 3mf files identical apart from the random object UUIDs). A Bambu Studio started early
(*Background Bambu Studio*) does not help Analyze: Studio's window only takes files to open, slicing always starts its
own command line process.

## Plate layout (2026-11-23)

`pack` makes each part's ways (plain and turned), `_plates` fills plate after plate with `_fill` from the four
corners (the fullest wins), `_place` finds each part's spot. Added on 2026-11-23:

- **Centered**: `_centre` moves the filled plate as one block towards the middle of the bounds. The fill decided what
  is on the plate; moving all together keeps the spacing, so the same parts fit. Tried: shifts along the way to the
  middle (40 steps), X only and Y only; the one ending closest to the middle that stays inside the bounds and clear
  of the zones (prime tower, no-go strips, tested as `_place` does) wins; none: the plate stays as it was. Lid and
  test model: same plates, both slice.
- **Support at a nozzle area's edge**: at the tight level (2) a part with tree support keeps level 1's room plus the
  bed margin to a side of the packed area that is a nozzle's limit inside the plate (`inner` in `pack`), not to the
  plate's own edges. Passed as `way[5]` (left, right, front, back; swapped with the mirroring in `_fill`) to `_place`
  and `_centre`. Why: the Lid with *Nozzle left* put the CB cap at x 325, its support spread past the left area's
  edge, Bambu Studio refused ("Found G-code in unprintable area of multi-extruder printers") and the tool fell back to
  2 plates; at the plate's own edges Studio did not object.
- **Parts in openings**: `openings(p)` draws the part's top view (with its merged parts) on a 1 mm grid
  (`HOLE_CELL`), all heights together, so an opening counts only when nothing of the part lies above it. Upright
  faces are skipped (they add nothing to the top view; 1.6 s → 0.2-0.4 s for the CB cap's 20 000 faces), the other
  faces sampled at most a cell apart, then grown by one cell (`binary_dilation`) for thin walls and safety;
  `binary_fill_holes` minus the part gives the openings, and in each `_largest_rect` (histogram method) is used.
  Only parts at least 3 × `HOLE_MIN` (12 mm) wide each way are drawn; an opening less the host's room (half gap and
  half pad) must stay `HOLE_MIN` wide. Kept per rotation in `p.opening` (copies share it). In `_fill` a part tries the
  openings of parts already on the plate first, then the plate; nested parts move with their host in `_centre`.
  `_plates` returns `Plate` lists with `nested` {part: host}, the report lists them (`rp.nested`). numpy and scipy
  only: no extra package in every model's Python.
- **Refused with nesting**: `pack_auto` sets `t.nest` from `"no-nest"` in `skip` and `t.nested` from the result;
  `retry_layout` first tries the same level with `"no-nest"`, then the other nozzle (auto), then a roomier level,
  where a refused nesting stays off. The Lid with 12 copies of each small part: 1 plate instead of 2, slices cleanly.

## Known limitations

- Parts merged into another with `merge_into` follow their host's orientation, but their own overhangs do not count
  for the host's support decision; check such parts in Bambu Studio.
- *Nozzle: left only / right only* applies to projects with one filament; with several colors (made by the tool or
  a color template) the choice has no effect (the form shows N/A, the saved value comes back with 1 color): Bambu
  Studio assigns the filaments to the nozzles itself (`filament_map_mode`).

## Colors (2026-11-22)

- A **color template** is a template with more than one filament, saved by the user in the Bambu Studio window (the
  AMS filaments with their colors). Templates of the user go to `%LOCALAPPDATA%\orientr\templates` (`USER_TEMPLATES`,
  `template_path()`), never into the tool's `templates\`: they survive a new version and never go into a release.
- `printer_templates()` only returns one-filament templates (the printer's normal template); `colour_templates()` lists
  the others per printer, the form's **Colors** field. Choosing one sends `--set template=<spec>`; back to
  *1 filament* sends `--printer`.
- Per part (`assign_filament()` in the core): its own `filament` (bambu.json, `--filament PART=N`, F in the form's
  parts list), else `nearest_filament()`: the CIELAB distance between the part's color in SOMA and each filament's
  color; a grey, black or white part (chroma < 12) only takes a grey, black or white filament when there is one (a
  mid-grey part went to a pink filament before). The reason goes into the report. Above a CIELAB distance of 55
  (`FAR_COLOUR`, `colour_far()`) the part gets a warning in the report, ⚠ in the parts list and a line under Colors:
  blue, red and orange went to pink at ~80, while grey to white (42) and dark green to green (51) are fine.
- With a color template the *Filament* choice (`material`) is not applied: swapping slot 1 put ASA next to PLA.
- Two nozzles (H2D): Bambu Studio may give some filaments to the other nozzle, and each nozzle misses a strip at one
  side of the bed. A prime tower in such a strip stops the slice ("Found G-code in unprintable area", code -102), so
  `_load_template()` moves it into the common area (`Template.tower_xy`, written per plate by `write_3mf()`).
- Tested with a 5-filament H2D project (black, black, pink, white, green): every one-filament project still comes out
  identical; the color project slices clean on 2 plates (the prime tower needs room).

## Model colors on a color template (2026-11-23)

- Bambu Studio's command line cannot add filaments: `--load-filaments` with one file works, with two or more
  (system presets or flat ones, the same or different) it crashes (0xC0000005 / 0xC0000409) on an H2D template,
  Studio 02.09.01.70. So the number of filaments stays the template's; only their colors change.
- `"colours": "model"` in `print` (`--set colours=model`, the form's *model colors*): `make_project()` collects the
  colors of the parts that go by color (no own `filament`; merged parts only with `"filament": "auto"`), in part
  order, and `model_colours()` makes one filament color per group: the same color (CIELAB < 12, `SAME_COLOUR`) or the
  same color name (`same_colour()`). More groups than filaments: the two closest groups merge (the color of the group
  with more parts) until they fit. `recolour()` writes them over the first filaments; the rest keep theirs.
- `recolour()` changes `filament_colour`, `filament_multi_colour` (when it has one entry per filament) and
  `flush_volumes_matrix` (nozzles × n × n, from row i to column j; only pairs where a color changed; the diagonal is
  left as it is). Purge = Bambu Studio's color formula (`FlushVolCalculator::calc_flush_vol_rgb`, ported as
  `_flush_formula()`) × 1.4 (`FLUSH_MARGIN`) + the nozzle's minimum (`flush_base()`: the median of the template's own values minus the
  formula, 130 mm³ without a usable pair), at most 900. Studio adds measured data per filament pair that is not in its
  source as a formula; the window's own values for black, pink, white, green (H2D, left nozzle) against Orientr's:
  black→white 900 / 900, pink→white 334 / 415, white→black 90 / 241, black→green 591 / 775, white→pink 190 / 213
  (base 129 mm³ left, 144 right); none of the 32 pairs is lower than the window's (with 1.3 black→white was 5 % lower).
  More purge than needed costs filament, too little shows as streaks of the old color. A list that keeps its length is accepted by the window and the
  command line (sliced clean, 2 plates, 10 parts).
- With model colors the warning is strict (`colour_far(strict=True)`): any part not printed in its own color (by name)
  is warned, `w.fil_merged`; red merged into orange (CIELAB 40) went unnoticed with the 55 limit.
- A part's own color (`"colour"`: a `PALETTE` name or `#RRGGBB`, `--colour`, C in the form) replaces its SOMA color in
  `load_model()`, for both modes; `"filament"` still wins over it.
- Not included: a color template in `templates\`. It has to be saved in the current Bambu Studio window (the only
  multi-filament project on the test PC was from 02.08, with an older start G-code); without one, the form's hint
  under Colors says how to save it.
- Two forms saving presets or settings at the very same moment: the last one wins.
- In the tight layout (level 2, 2 mm bed margin) a wide brim of a part at the bed edge may reach past the edge. Such a
  layout is only kept when Bambu Studio slices it clean; otherwise the tool steps back to the roomier one.

## Filaments made by the tool (2026-11-23)

With `"colours": "model"` or `"manual"` and a one-filament template, `expand_filaments` gives the project one
filament per color, all slot 1's preset. Compared with a 32-filament H2D project saved in the window by the same
Studio version (02.09.01.70) as its one-filament template, the rule is exact: every list that is a key of the filament
preset, starts with `filament_`, or is in `PER_FILAMENT_EXTRA` holds one block per filament (1, 3, 4 or 8 values),
copied per filament; `filament_self_index` numbers them, `filament_colour`/`filament_multi_colour` get the colors,
`flush_volumes_matrix` is n x n per nozzle (colour formula, as `recolour`), `different_settings_to_system` n + 2. The
same rule finds no other keys in the A1, X1C, P2S and H2C templates. Sliced on the command line on H2D (ASA, PLA) and
A1. The colors go to the nearest color Bambu Lab sells the filament in (`filaments_color_codes.json` next to Studio's
filament presets, by `filament_ids`); farther than `UNAVAILABLE` gives the warning `w.colour_unavailable`.
The older attempt below failed because it compared projects of other Studio versions.

## Why a second filament is not added to a template by the tool

Looked into on 2026-11-22 (parts with `merge_into` + `"filament": 2` print with filament 1 on the one-filament
templates). Compared with projects Bambu Studio itself saved with more filaments: X1 1 vs 4 filaments, 172
lists change length; X1 Carbon 1 vs 5, 106 lists. No single rule: per filament 1 -> N (71 and 51 lists), per filament
and extruder variant 2 -> 2N, the flush matrix 1 -> N² (`flush_volumes_matrix`), and lists that shrink (2 -> 1,
4 -> 2) because those projects come from other Studio versions and processes. Guessing them is what the window
refused before ("Invalid configuration file", see below), so the tool does not; a template saved in the window with
the filaments needed is the way (the warning `w.filament` says how).

## Why templates are not generated from Bambu Studio's profile files

Tested by swapping the printer of the H2D template to the X1 Carbon and comparing with a template saved in the window:

- Names only: 211 of 636 settings wrong. Names plus the flattened system presets (machine, process, filament): 65.
- The G-code is not in the inheritance chain (that ends in `fdm_machine_common`, a generic start G-code): the window
  takes it from separate presets `<printer> template machine_start_gcode` (also `machine_end_gcode`,
  `change_filament_gcode`, `layer_change_gcode`, `time_lapse_gcode`).
- `print_compatible_printers` must list the printer, or the command line refuses the slice (error -17).
- With all that and the prime tower position, the command line's G-code matched the real template within the slicer's
  own noise (it is not deterministic: slicing the same project twice differed in ~1000 of 180000 lines).
- But the window refused the project ("Invalid configuration file"): it checks the length of 44 lists, per extruder and
  per filament × extruder variant. A rule that guessed those lengths got 5 wrong; the window repaired 4, one
  (`flush_volumes_vector`) stayed wrong.

So it can work, but only by copying undocumented internals that differ per printer family and may change with any
update; a template saved in the window takes a minute per printer and is always right.

The window rebuilds the process and filaments from the system presets by name and keeps only the keys listed in
`different_settings_to_system`; the command line uses the values in the file as they are. The tool therefore writes
both: the preset names (for the window) and their values (for the test slice and its own rules).

A template made with Bambu Studio's command line is refused on purpose: the command line leaves the presets
unresolved (a generic start G-code, a wrong build height).
