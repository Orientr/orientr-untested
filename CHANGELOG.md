# Changes

Version numbers: see [DEVELOPMENT.md](DEVELOPMENT.md#version-numbers). Source of each change: *(tester)*,
*(own)* or *(review)*.

## Unreleased

## 0.1.0 (2026-11-24)

The release repository is now public and called **orientr-untested**: the update check works without a GitHub
login, so this and later versions show up in the header by themselves.

- The release repository is public and renamed from orientr-test to orientr-untested (the old links still lead
  there). The update check no longer needs the GitHub CLI. *(own)*
- The form draws itself again when its terminal changes size, without waiting for a key. Started automatically
  by SOMA, the form was drawn before SOMA's panel had its final width and stayed cut off. *(own)*
- The Parts field shows **Parts (56)**: the number of objects to print (copies and duplicates included) in
  the label, and just "10 of 10" beside it. It was cut off as "10 of 10 printed, 56 obj…". *(own)*
- Windows' own console (no Windows Terminal, e.g. Windows 10): ✅ ⚠ ◆ are shown as √ ! ●. Its fonts lack them
  (measured: Consolas and Cascadia Mono), and it showed boxes or question marks. *(own)*
- A console window in legacy mode now says how to switch that off, instead of "the form needs the Windows
  console". *(own)*
- Part and model names with wide characters (Chinese, emoji) are measured as the two columns they take, so their
  lines no longer run past the edge. *(own)*
- When Windows Terminal shows no form within 30 s (an old version), the form opens in Windows' own console instead
  of failing after 60 s; a Windows Terminal window that still comes later closes by itself. *(own)*
- Background Bambu Studio on a PC where Bambu Studio was never started: the form now says to open it yourself once
  first (its first start asks a few questions), instead of "already open, or Open in Bambu Studio is off". *(own)*
- In a console of 60-61 columns (SOMA's panel on a laptop with display scaling) the version checks stay beside the
  logo, as in a wider one; before, they went under the header. *(tester)*
- Number fields (walls, infill, duplicates, copies) also take the digits of an AZERTY keyboard without Shift
  (`& é " ' ( § è ! ç à`). *(own)*
- In a console narrower than about 50 columns the field names give way too (cut with …): before, the menu ran past
  the edge (from 45 columns in English, 49 in German, 50 in French). *(own)*
- In SOMA's terminal `orientr` opens the form of the model SOMA has open (SOMA_PROJECT), also when the terminal is
  in another folder; before, it showed the model list. *(tester)*
- Walls and infill: type any number in the form (a digit opens the field): walls 1-20, infill 0-100 %, not only the
  values on the list. A typed value joins the list, ← → reach it, and favorites keep it. *(own)*
- Version check: the installed Bambu Studio version is read from `bambu-studio.exe` itself. After a Studio update,
  before Studio had run again, the form said *Update Bambu Studio* and *untested* (the old version was still in
  Studio's settings file) until Studio had started once. *(tester)*
- Background Bambu Studio: the hint and the README say that Bambu Studio's banner shows for a few seconds when it
  starts. It cannot be hidden: Windows only hides it once Bambu Studio has loaded (measured: 8.4 s), and Bambu
  Studio has no setting to turn it off. *(tester)*

## 0.0.1 (2026-11-23)

First test version of Orientr, for a few testers. Had an earlier test version? Install this one as the README says:
`install.cmd` replaces it, and your settings and presets move along. What it does is at the end of this section; first
what changed since the first build of 2026-11-22.

### Since the build of 2026-11-22

- Parts in openings: a part with a large opening open over its full height (the Lid plate: a frame round a window of
  about 118 × 155 mm) takes smaller parts inside it. The top view is drawn on a 1 mm grid (numpy and scipy only, no
  extra package), about 0.2-0.4 s once per part. The report lists them ("In the opening of Lid plate: …"); when Bambu
  Studio refuses a layout with nested parts, the tool first tries the same layout without nesting. The Lid with 12
  copies of each small part: 1 plate instead of 2, sliced cleanly. *(tester)*
- Fixed: the Lid with Nozzle *left only* needed 2 plates although 1 fits. The tight layout put the CB cap (tree
  support) against the edge of the left nozzle's area; its support reached past it and Bambu Studio refused the slice
  ("Found G-code in unprintable area of multi-extruder printers"), so the tool fell back to the roomy layout. In the
  tight layout a part with support now keeps the roomy layout's distance to a nozzle area's edge inside the plate (not
  to the plate's own edges, where Bambu Studio did not object). The Lid: 1 plate with left, auto and right, slices
  cleanly. *(tester)*
- Parts stand in the middle of the plate: once a plate is filled, all its parts move together as one block towards
  the middle, as far as the edges, no-go zones and prime tower allow. The same parts fit on each plate as before.
  Checked on the Lid and the test model: same plates, both slice cleanly; the Lid's single part on plate 2 now stands
  exactly in the middle (it was in a corner). *(tester)*
- Colors and Parts get a ⚠ and turn orange when something is wrong: a color not sold (or not mixable) in this
  filament, no part chosen, or too many objects. The line under Parts says why. *(tester)*
- Background Bambu Studio shows its state at the right of the field, updated while you look: ◦ *Opening…* (blue),
  ● *Open* (green), ◦ *Closing…* (orange), ○ *Closed* (grey). *(tester)*
- Background Bambu Studio: ← → only changes the choice, **Enter** carries it out. *Yes* + Enter starts Bambu Studio
  hidden, *No* + Enter now really closes the hidden one (before, it only stopped a start that was still waiting and
  the hidden Studio stayed until the form closed). A Studio you use stays open. Leaving the field without Enter goes
  back to what is in effect. The line under the form says so. *(tester)*
- Favorites: 10 slots instead of 3. Favorites saved before stay in slots 1-3. *(tester)*
- Every text in the form starts with a capital, also after a key or a colon (`S: Save settings / Change name`,
  `Esc Cancel`, `Auto: Per part`), in English, German and French: values, hints, key help, the status lines and the
  Analyze screen. Colour names and error messages get theirs where the form shows them, so the report's
  sentences stay as they were. *(tester)*
- Header, same size (61 × 13): the title stands above the wordmark, right of the nozzle, centred, both lines
  in bold and a lighter grey, so it stands out. The version checks moved under the baseline, right of the build plate, centred on each other
  with the shortest on top. A longer version number still fits; a warning too long for that room goes under the
  header. *(tester)*
- Logo: the user's refined banner. The nozzle has a light and a shaded side, the cube stands a pixel higher on the
  plate, and the plate's edge and the baseline use the terminal's own text colour, so they also show on a light
  terminal. *(tester)*
- `orientr` typed in cmd or PowerShell: its own window now opens as high as the screen allows, from the top of the
  screen down to the taskbar, so the whole form fits (it was centred at a fixed height). *(tester)*
- Header one row lower: the logo's nozzle stands a row lower, beside the version checks, so the form shows one row
  more. *(tester)*
- The form's arrows are ◄ ► instead of ◀ ▶: in Windows' own console (font Consolas) ◀ ▶ showed as boxes with a
  question mark. *(own: test in a real console window)*
- After switching **Language** in the form, the status lines in the header (Bambu Studio, Orientr) are in the new
  language too; Orientr's note after a standard Bambu Studio warning and the closing *written / report* lines are
  translated (they were English in every language). *(own: test in a real console window)*
- **Analyze** in a low window (cmd, 30 rows): results that do not fit under the header scroll with ↑↓ instead of being
  cut off. *(own: self-test)*
- **Nozzle auto** on a printer with two nozzles: when Bambu Studio refuses the layout on one nozzle's area, the other
  nozzle's area is tried before a roomier layout (a test model: 1 plate instead of 2). *(own: self-test)*
- Another **Nozzle size** works again: every size other than the template's (0.2, 0.6, ...) failed to slice on every
  printer ("not compatible with the process preset", or on the H2D "Failed slicing the model"). *(own: self-test)*
- `--selftest` also slices colors made by Orientr (with a mixed filament on printers with two or more hotends) and
  another nozzle size, so a change in a Bambu Studio update shows there. *(own: self-test)*
- With colors made by Orientr a grey part goes to the color chosen for it (with mixing, a dark grey part was printed
  white). *(own: self-test)*
- In a list, a letter jumps by the color's name (*T*: *Manual · Turquoise*); before, only M jumped. *(own: self-test)*
- *Nozzle left only / right only* shows N/A with several colors (it has no effect there); leaving color mixing gives
  back the filament chosen before it; the report lists each filament with its color. *(own: self-test)*
- Colors without a color template: Orientr makes one filament per color from the printer's own template. **Colors**
  in the form is *Auto from SOMA model* or *Manual* in one of the colors Bambu Lab sells the chosen filament in (by
  Bambu's own names); a part's own color with **C** in Parts. A color Bambu Lab does not sell gives a warning and
  prints in the nearest one. The filament can always be chosen. *(tester)*
- Parts are packed by their outline seen from above, not their bounding box: round parts fit side by side
  diagonally (a test model: 2 plates instead of 3). *(tester)*
- With several colors, parts of one color go on one plate where they can, for the fewest color changes, without more
  plates (or up to **Max plates**): a test model printed in 40 h instead of 52 h with 208 g less filament. *(tester)*
- The prime tower stays where Bambu Studio prints it: no more "WipeTower" conflicts with a part, nor "Prime Tower is
  too close to others". *(tester)*
- Color mixing: **Colors** offers *Mix · CMYKW (PLA Palette)*, *CMYW* and *RYBW (PLA Basic)* on printers with two or
  more hotends. The model's colors are made from the base colors and Bambu's measured mixes of them; the hint says
  which filaments to load, and a color that cannot be mixed closely gives a warning. *(tester)*
- Parts merged into another part go by their own color when Orientr makes the filaments; the preview names colors
  as Bambu does (Turquoise). *(tester)*
- Keys **G**, **A**, **C** for Generate, Analyze, Cancel (German G A B, French G A N); the header stays on top while
  generating and analyzing; its description is now "Export From SOMA to Bambu, Print-Ready". *(tester)*
- Header: the version checks now stand beside the nozzle (where the project name was), and the project name stands
  right above the settings menu. The version checks stand centered in the free space right of the nozzle, and there is a
  little more room between the logo and the description. *(own)*
- The report no longer shows your Windows user name: the template as `templates/default.3mf`, other paths in your
  user folder as `%USERPROFILE%\...` (the report is meant to be attached to issues). *(review)*
- `install.cmd` and `uninstall.cmd` keep your user PATH as it was: entries like `%USERPROFILE%\bin` stay variables
  (before, they were filled in and the PATH was saved as plain text). *(review)*
- The form scrolls in a low window (SOMA's terminal panel): the selected row stays in view, ▲ / ▼ show there is more,
  and the key legend and hint stay at the bottom. Before, the buttons fell off the screen. *(review)*
- `orientr` typed in a terminal closes that terminal only when it is a window or tab of its own (Windows Terminal, or
  started from the Start menu); a terminal in VS Code or another IDE, or a shell started from another shell, stays
  open. *(review)*
- The button **Generate Bambu** is now just **Generate** (*Generieren*, *Générer*). *(own)*
- The same words as Bambu Studio itself: German *Umrandung* (was Brim), *Druckplatte* and *Druckbett*, *Sonstige*;
  French *plaque* for a plate of the project (*plateau* stays the printer's bed), *arborescent* for tree support;
  English *Others*. *(own)*
- Orientr's own 3 slots are now **Favorites** (*Favoriten*, *Favoris*); what Bambu Studio calls presets is called
  presets in Orientr too (was "profiles"; German keeps *Profil*, French says *préréglage*). Your saved slots stay.
  *(own)*
- `install.cmd` says "about 2 minutes" for reading Bambu Studio's presets only when they really have to be read;
  installed again with the presets already in the cache, it no longer announces a wait. *(own)*
- Started from the shortcut after a Bambu Studio update, the window with "Reading Bambu Studio's presets (about 2
  minutes)" comes to the front; before, it stayed minimized and nothing seemed to happen for 2 minutes. *(own)*
- **More colors**: save a color template in Bambu Studio (your AMS filaments with their colors) and choose it in the
  form under **Colors**. Each part gets the filament closest to its color in SOMA, **F** in *Parts* chooses another,
  `bambu.json` and `--filament PART=N` too; the report says per part which filament and why, Analyze shows the
  filaments by color. On a printer with two nozzles the prime tower is placed where both reach. *(own)*
- A part whose color has no close filament in the color template (a blue part with only black, pink, white and
  green) is never silently printed in another color: the report warns, the parts list marks it with ⚠, and the form
  says how many parts it concerns under **Colors**. *(own)*
- Your own templates are kept in `%LOCALAPPDATA%\orientr\templates`: a newer Orientr unpacked over the old one leaves
  them alone. *(own)*
- **Model colors**: one color template per printer is enough. Under **Colors**, *model colors* gives the template's
  filaments the colors of your parts (a 5-filament template prints up to 5 colors, whatever colors it was saved
  with), with purge volumes to match; *as saved* keeps your AMS colors as before. More colors than filaments: the
  closest share one, with a ⚠ for each part not printed in its own color. Bambu Studio's command line cannot add
  filaments to a project (it crashes), so the number of filaments stays the template's. *(own)*
- **C** in *Parts* gives a part another color than in SOMA (12 colors, then the model's again); in `bambu.json`
  `"colour"` per part, on the command line `--colour PART=red` or `#RRGGBB`. *(own)*
- The code is split in three: `orientr_core.py` (the rules, slicer-independent), `bambu_project.py` (everything for
  Bambu Studio) and `orientr.py` (the app), so another slicer can get a part of its own later. Nothing changes in
  use: the project and the report come out the same. *(own)*
- "Project:" and the messages you can meet in the form (a file still open in Bambu Studio, no printable parts, a
  template that cannot be used, …) are now in German and French too. *(review)*
- Key legends wrap instead of being cut off in a narrow window, and the status lines are shorter, so "orientr
  --selftest" stays readable in SOMA's terminal. *(review)*
- Texts: singular and plural right ("1 plate", "1 ledge", one plate picture), American spelling throughout,
  "Quantity Settings" instead of "Volume Settings", Bambu Studio's own words in German and French (Reinigungsturm, tour
  de nettoyage), clearer hints for *Max plates*, *Walls* and *Infill*, and the report names project-wide choices
  ("walls 3", not "wall_loops 3"). An orientation no longer shows "-0.00". *(review)*
- The empty line between the version checks and the project name is back when the full header does not fit. *(review)*
- The README shows the current form with its header, and says what `orientr --selftest` and the update check
  (through the GitHub CLI, while the repository is private) fetch from GitHub. *(review)*
- Temporary folders are named `orientr-…` in `%TEMP%`, and ones older than a day are removed at the next start (an
  interrupted run left them behind for good). *(review)*
- A model's own `inputs\bambu_template.3mf` is no longer rewritten (SOMA's rule: never change `inputs/`); the project
  made from it never had the account number in it. *(review)*
- Taken out: the transition from the early test version (its settings folder, shortcuts, PATH entries and Bambu Studio
  backup), which nobody else installed; the update check's cache is now `update-check.json` (the old file is removed
  by itself); the command line takes `yes`/`no`, `auto`/`on`/`off` and `template=default` (no more Dutch words).
  *(review)*

### What it does

- The form (in SOMA's terminal, or in a window of its own from any terminal or the Start menu shortcut): printer,
  nozzle, filament, process, support, brim, walls, infill, parts and copies, duplicates, max plates, 10 favorites,
  English, German and French. A new model starts with the printer, nozzle size, filament and process selected in
  Bambu Studio.
- Per part: orientation, support, brim, walls and infill chosen by rules, each with its reason in the report.
- **Generate Bambu** writes the Bambu Studio project (`.3mf`) and the report, test-slices it and opens it in
  Bambu Studio; **Analyze** shows plates, print time, filament and cost (in the currency of the region chosen in
  Bambu Studio) without saving anything.
- Duplicates and copies up to 200 each, with a guard against projects too big for Bambu Studio (500 objects,
  5 million triangles); a part that does not fit the printer stops with a clear message.
- *Background Bambu Studio*: starts Bambu Studio hidden so that Generate opens the project in about 2 s (extra load on
  the PC, off after install). `uninstall.cmd` switches Bambu Studio's *single instance* setting off again when Orientr
  switched it on.
- Templates for the 15 Bambu printers of Bambu Studio 2.9 (from Bambu Studio's system profiles, © Bambu Lab,
  AGPL-3.0); a self-test after Bambu Studio or SOMA updates (`orientr --selftest`).
- `install.cmd` puts the `orientr` command in PATH (other copies out), makes the Start menu and desktop shortcut,
  checks for a built SOMA model and Bambu Studio 2.9 or newer, and reads Bambu Studio's profiles once (about
  2 minutes), so the form opens at once.
- The Orientr logo: in the header of every terminal (SOMA's too) with the description "Export from SOMA → Bambu
  Studio print-ready. Quick settings menu to generate or analyze your print." and the version checks beside the build
  plate, as the shortcut icon, in the taskbar for Orientr's own window, and in the README.
- The status line says whether Orientr and Bambu Studio are up to date (only after a real check: without internet
  "no internet, update not checked").
