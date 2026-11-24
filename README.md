<p align="center"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/orientr-logo-dark.svg">
  <img src="assets/orientr-logo.svg" width="330" alt="Orientr logo">
</picture></p>

# Orientr

Turns the printable parts of a SOMA model into one Bambu Studio project, with the
print settings chosen per part (orientation, support, brim, walls, infill) and the reason for each one written down
in a report. The printer is never contacted: you open the project in Bambu Studio, check it, slice it and send it
yourself.

Windows only. English, German and French.

```
             ████
             ████               Export From SOMA to Bambu
              ▀▀                       Print-Ready
              ▄▄
          ▄▄██████▄▄        ▄▀▀▀▄      ▀              █
         █▀▀██████▀▀█       █   █ █▄▀▀ █ ▄▀▀▀▄ █▄▀▀▄ ▀█▀ █▄▀▀
         █████▀▀█████       █   █ █    █ █▀▀▀▀ █   █  █  █
      ▄▄▀████████████▀▄▄    ▀▄▄▄▀ █    █ ▀▄▄▄▄ █   █  ▀▄ █
  ▄▄▀▀██████████████████▀▀▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
    ▀▀▄▄███▀▀████▀▀███▄▄▀▀
        ▀▀▄▄██████▄▄▀▀     ✅  Orientr 0.1.0: up to date
            ▀▀▄▄▀▀   ✅  Bambu Studio 02.09.01.70: up to date

  Project: Lid
  ─────────────────────────────────────────────────────────────────────
  Favorites
   Favorite                  ◄  1  ·  (empty)                       ►
  ─────────────────────────────────────────────────────────────────────
  Printer Settings
   Printer                   ◄  H2D  (current)                      ►
   Nozzle                    ◄  auto                                ►
   Nozzle size               ◄  0.4 mm                              ►
   Filament                  ◄  PLA Basic                           ►
   Colors                    ◄  Auto from SOMA model                ►
  ─────────────────────────────────────────────────────────────────────
  Quality Settings
   Process                   ◄  0.20mm Standard                     ►
   Support                   ◄  auto (per part)                     ►
   Brim                      ◄  auto (per part)                     ►
   Walls                     ◄  as in the preset                   ►
   Infill                    ◄  as in the preset                   ►
  ─────────────────────────────────────────────────────────────────────
  Quantity Settings
   Parts (10)                   10 of 10                            …
   Duplicates                ◄  1 ×                                 ►
   Max plates                ◄  no limit                            ►
  ─────────────────────────────────────────────────────────────────────
  Others
   Language                  ◄  English                             ►
   Open in Bambu Studio      ◄  Yes                                 ►
   Background Bambu Studio   ◄  No                                  ►
  ─────────────────────────────────────────────────────────────────────
   [ Generate ]                  [ Analyze ]                 [ Cancel ]
```

## What you need

- **Windows 10 or 11**
- **SOMA**, with at least one model built (`soma build`). The tool runs with the model's own Python, so there is
  nothing else to install.
- **Bambu Studio 2.9 or newer** in `C:\Program Files\Bambu Studio` (installed elsewhere: set the environment variable
  `BAMBU_STUDIO` to its `bambu-studio.exe`)

## Install

1. On the **Releases** page (right side of the repository page), open the newest version and download
   **Source code (zip)**. Unpack it where you want to keep it, for example in your user folder.
2. Double-click **`install.cmd`** in that folder. Windows may ask first, because the file was downloaded
   (*Open File - Security Warning*, or *Windows protected your PC*): choose **Run** (or **More info > Run anyway**).
   It adds the folder to your user PATH (the `orientr` command), adds an **Orientr** shortcut to the Start menu
   and the desktop, and checks that SOMA (with a built model) and Bambu Studio are there. No administrator rights
   needed. When it ends with *Ready*, everything was found; otherwise the lines with `[!!]` say what is missing.
   It also reads Bambu Studio's printer, filament and process presets once (about 2 minutes), so that the form opens
   at once later; after a Bambu Studio update the form reads them once more and says so.
3. **Restart SOMA** and open a new terminal: programs that were already open do not know the `orientr` command yet.

A newer version: unpack it (into a new folder or over the old one) and run its `install.cmd`: the `orientr` command and
the shortcuts then point to the new version. Moved the folder? Run `install.cmd` again too. To remove it, run
**`uninstall.cmd`** (see [Uninstall](#uninstall)).

In your models, Orientr's files are `bambu.json` (your choices) and `output\bambu` (the project and the report): they
are named after Bambu Studio, because they belong to it (other slicers may get their own later).

## Start it

- **In SOMA's terminal** (it opens in the model folder): type `orientr`. The form opens in the terminal panel.
- **From the Orientr shortcut** (Start menu, desktop) or by double-clicking `orientr.cmd`: choose a model (newest
  first, ↑ ↓ and Enter), then its form opens. The window that started it closes by itself.
- **In another terminal** (Windows Terminal, cmd, PowerShell): `orientr`. In a model folder the form opens; anywhere else
  you choose a model first. Both open in a window of their own, as big as the form, and the terminal you typed it in
  closes when it is a window or tab of its own; a terminal in VS Code or another editor stays open
  (`ORIENTR_KEEP_TERMINAL=1` always keeps it open). The form's window closes by itself when the project is made or
  canceled; after an error it waits for a key, so you can read the message.

## The form

| Key | |
|---|---|
| ↑ ↓ | choose a field (and the buttons) |
| ← → | change the value; filament and process lists follow the printer at once |
| Enter | the full list (filaments, processes, colors, parts), or press a button; in a list a letter jumps to the next name with it (*T* for *Manual · Turquoise*) |
| G A C | Generate, Analyze, Cancel at once (German G A B, French G A N; the letter is underlined) |
| Esc | cancel: nothing is made or saved |

- **Favorites**: 10 slots for your own favorite settings, the same in every model. ← → picks a slot, **S** saves all
  settings below it (you type a short name), **Enter** loads it. Which parts are printed is not part of a favorite. A
  printer, nozzle size, filament or process that is not available is kept as it was, and the form says which.
- **Printer Settings**: the printer (one per template, see [Templates](#templates)), which nozzle (printers with two),
  the nozzle size, the filament and the **Colors**: *Auto from SOMA model*, *Manual* in one color, or *Mix*
  (see [More colors](#more-colors)). A model you have not made a project for yet starts with what is selected in
  Bambu Studio (printer, nozzle size, filament, process), as far as this tool has a template and Bambu Studio's own
  preset for it.
- **Quality Settings**: the process preset, support and brim (*auto* decides per part), walls and infill (← → or
  Enter: from the list; or just type a number: walls 1 to 20, infill 0 to 100 %).
- **Quantity Settings**: **Parts** (in brackets the number of objects to print, beside it how many parts are on;
  Enter: switch parts on or off with Space, set how many of a part with ← → or type the
  number; each part shows the color it prints in, **C** chooses another color from a list),
  **Duplicates** (the whole set this many times, ← → or type the number) and **Max plates** (more plates needed: a tighter layout is tried,
  and if that is still too many nothing is made).
- **Other**: the language, open the result in Bambu Studio, and start Bambu Studio early (see below).

Duplicates and copies go up to 200 each. To keep Bambu Studio from getting stuck or crashing, a project holds at most
500 objects and 5 million triangles in all; above that the tool says so before it makes anything.

**Generate** writes `output/bambu/<model>.3mf` and `<model>-print.md` (every setting with its reason), lets
Bambu Studio slice it once as a check (20-80 s; the report lists its warnings) and opens it in Bambu Studio. A
`.gitignore` in `output/bambu` keeps these files out of SOMA's version history (they are made again every time).

**Analyze** makes the project with the choices on screen in a temporary folder and lets Bambu Studio slice it
(15-80 s; Esc stops it). It shows the number of plates, the print time, the filament (grams, meters, and the cost from the price per kg in its Bambu Studio preset, with
the currency sign of the region chosen in Bambu Studio)
and Bambu Studio's warnings. Nothing is saved, so you can change a choice and look again before you generate.

The two lines at the top say whether everything is ready: Bambu Studio found and up to date, and whether a newer
Orientr is available (see [Network and privacy](#network-and-privacy)).

### Background Bambu Studio

With **Background Bambu Studio** on (it is off after install), Bambu Studio starts hidden as soon as SOMA has finished
starting and the PC is quiet, so that *Generate* opens the project in about 2 s instead of about 20 s. Only Bambu
Studio's banner (splash screen) shows for a few seconds while it starts: Windows lets no other program hide it while
Bambu Studio is loading, and Bambu Studio has no setting to turn it off. After that you see no window and no taskbar
button until Generate. When nothing is opened in it (canceled, only Analyze, or *Open in Bambu
Studio* off) it closes again by itself, also when the form's window is closed with ×. If you start Bambu Studio
yourself meanwhile, that window simply appears. It puts extra load on the PC: while the form is open, Bambu Studio
runs in the background and uses memory and processor time.

In the form, ← → only changes the choice; nothing happens yet. **Enter** carries it out: *Yes* starts Bambu Studio
hidden now, *No* closes the hidden Bambu Studio now (one you are using, with a visible window, stays open). Leave the
field without Enter and it goes back to what is in effect. At the right of the field the form shows what the
background Bambu Studio does, and keeps it up to date: ◦ *Opening…*, ● *Open*, ◦ *Closing…* or ○ *Closed*.

To make this work the tool switches on Bambu Studio's *single instance* setting once (only while Bambu Studio is
closed; a copy of its settings is kept as `%APPDATA%\BambuStudio\BambuStudio.conf.orientr.bak`). The option is
saved for every model.

Just installed Bambu Studio? Open it yourself once first: its first start asks a few questions (region, login,
printers), which a hidden Bambu Studio could not show, and only after that does it have the settings file the tool
needs. Until then the form says so, and *Generate* opens Bambu Studio the normal way.

### Other commands

```
orientr --saved                       # make it again with the saved choices, no form
orientr --check --open                # make it with the saved choices, test-slice it, open it
orientr --set walls=3 --set infill=25%   # save choices (checked like the form), then make it
orientr --skip "Lid" --include "Base" # parts off / on again (--include-all: all on)
orientr --set duplicates=3 --copies "Knob=4"   # the whole set 3 times, the knob 4 x 3 = 12 times
orientr --set max_plates=2            # refuse when it needs more than 2 plates (after trying a tighter layout)
orientr --printer "X1 Carbon"         # use that printer (its template)
orientr --preview --set walls=3       # plates, print time and filament with these choices; saves nothing
orientr --status                      # the status lines, as JSON (works anywhere)
orientr --models                      # the SOMA models on this PC (works anywhere)
orientr --selftest                    # after a Bambu Studio update: see below
orientr --recent                      # projects Bambu Studio wrote when sending a print (for --import-recent)
orientr --import-template <3mf> --name MyTemplate   # add a Bambu Studio project as a template
orientr --help                        # everything
```

## Choices and hints: `bambu.json`

The form saves its choices in `bambu.json` in the model folder; the next run starts from them. You can also add hints
per part by hand (all optional):

```json
{
  "template": "default",
  "print": {"material": "PETG Basic", "process": "0.16mm Standard", "infill": "20%", "walls": "3",
            "support": "auto", "brim": "auto", "check": true, "open": true,
            "duplicates": 2, "max_plates": 3},
  "parts": {
    "Handle":  {"up": "+x"},
    "Knob":    {"copies": 4},
    "Hook":    {"support": true, "function": "load"},
    "Pin":     {"brim": 0, "walls": 5, "infill": "50%"},
    "Label":   {"merge_into": "Plate"},
    "Lid":     {"colour": "red"},
    "Cover":   {"skip": true},
    "Clip":    {"function": "snap", "settings": {"top_shell_layers": "6"}}
  }
}
```

- `up`: the model axis that points up on the bed.
- `support`, `brim` (mm), `walls`, `infill`: this part only. `support`/`brim` in `print` are `auto`, `on` or `off`.
- `colour`: print this part in this color instead of its color in SOMA: a name (`red`, `dark grey`) or `#RRGGBB`;
  `orientr --colour "Lid=red"` sets it too (`--colour "Lid=auto"`: the model's color again).
- `merge_into`: print this part inside another part, in its own color (a lettering on a plate).
- `filament`: only with a color template of your own (see [More colors](#more-colors)): print this part with that
  filament of it; when Orientr makes the filaments, every part goes by its color and a number is ignored.
- `settings`: any Bambu Studio per-object setting, as text.
- `copies`: print this part that many times; `duplicates` in `print` repeats the whole set, so a part is printed
  `duplicates × copies` times. Copies are named `Knob (2)`, `Knob (3)`, ...; the report shows them as `Knob × 3`.
- `max_plates` in `print`: when the parts need more plates, a tighter layout is tried; if that is still too many,
  nothing is made and the message says how many plates are needed (0 or missing: no limit).
- `function` (`snap`, `spring`, `load`): stronger walls and infill, and the orientation lays the part's longest side in
  the layers (layers are the weak direction). When the load runs another way: `"load_axis": "x"` (x, y, z or
  `[dx, dy, dz]`). Mark the part that flexes or carries, not a large housing with small clips on it.

A part's own hint always wins over the form, and the form over the automatic rules; the report says which applied.

## What it decides, per part

| Setting | Rule |
|---|---|
| Orientation | Six axes and the three largest flat faces are tried. Only stable ones count when there is one: at least 30 mm² bed contact and the center of mass inside it (or at most ¼ of the contact width past it, on the side that gets support). Cost = (support area − 0.3 × bed contact) / surface + 0.1 × height / size; it must fit the bed. The modeled orientation wins a near tie. The support angle comes from the process preset, so another preset can turn a part. |
| Support | Tree (auto) when an overhang region flatter than the preset's threshold angle (e.g. 30° from horizontal) is ≥ 20 mm², all together ≥ 50 mm², or an island hangs in the air. Ignored: spots < 10 mm², ledges ≤ 1 mm deep, bridges ≤ 10 mm held on both sides, and rounded or chamfered bottom edges that reach ≤ 1 mm past the first layer (a bottom fillet up to about R3.7 at 30° and a 0.2 mm first layer). For a part with support and such an edge the tool lowers that part's support threshold until Bambu Studio no longer warns about the edge, as long as the real overhang loses at most 10 mm² or 10 %; otherwise the report explains the warning. |
| Brim | Contact = cross-section at half the first layer. Tipping ratio = height of the center of mass / its distance to the contact edge: > 2.5 → 5 mm, > 5 → 8 mm. Contact < 80 mm² → 5 mm, < 30 mm² → 8 mm. Filaments that warp (a heated bed or a heated chamber in their preset: ABS, ASA, PC, PA …) → 5 mm for parts longer than 100 mm and for small parts. |
| Strength | Only for parts with a `function` or `load_axis`: orientations where the load axis leaves the layer plane by more than 15° are dropped before support and contact count. |
| Walls, infill | Tiny parts (< 15 mm or < 1 cm³) 4 walls. `snap`/`spring` 4 walls 40 %, `load` 4 walls 30 %. The rules only raise the chosen value, never lower it. 100 % infill switches the pattern to rectilinear (Bambu Studio refuses 100 % with grid, gyroid or monotonic). |
| Plates | All parts (and their copies) packed together by their outline seen from above (round parts fit diagonally), clear of the printer's no-go zones and of the prime tower (where Bambu Studio prints it). With two or more plates a tighter layout is tried too and kept when it needs fewer plates and Bambu Studio slices it cleanly. With several colors, parts of one color go on one plate where that needs no more plates (or up to **Max plates**): fewer color changes. A part with a large opening that is open over its full height (a frame, a ring) takes smaller parts inside it; the report says which ("In the opening of …"), and when Bambu Studio refuses such a layout it is made again without. Once a plate is filled, its parts move together as one block towards the middle of the plate, as far as the edges, the no-go zones and the prime tower allow: the same parts fit, they just stand in the middle. A part that does not fit the printer gets a warning. |

The report also warns about overhangs steeper than 45° from vertical without support, parts that tip over, and parts
that do not fit.

## Templates

The printer comes from a **template**: a project saved in the Bambu Studio window, one per printer, in `templates\`.
This folder has templates for all 15 Bambu printers of Bambu Studio 2.9 (A1, A1 mini, A2L, H2C, H2D (`default`),
H2D Pro, H2S, H3C, P1P, P1S, P2S, X1, X1 Carbon, X1E, X2D), with the 0.4 nozzle. Filament and process need no
template: the tool takes them from Bambu Studio's own presets for that printer, by name.

**A printer that is not here yet**: open any template in the Bambu Studio window, choose the new printer with the 0.4
nozzle, choose *Don't save* for the old settings, put a small object on the plate and *File > Save Project As* into
`%LOCALAPPDATA%\orientr\templates` (any file name). The tool finds a template by the printer in it. Your own templates
stay there when you install a newer Orientr; one with the same name as a template of the tool is used instead of it.
Bambu Studio writes your Bambu account number into every project it saves; the tool removes it from a template the
first time it loads it.

## More colors

Orientr makes the filaments itself, one per color, from the printer's own template: nothing to save in Bambu Studio.
All of them are the filament chosen under **Filament** (PLA Basic, ASA, ...); **Colors** decides their colors:

- ***Auto from SOMA model***: each part in its color in SOMA. Parts with the same color name (two dark greys) share
  one filament.
- ***Manual · <color>***: the whole project in that color; in **Parts**, **C** gives a part another one. A part merged
  into another (`merge_into`, a lettering) keeps its color from SOMA.
- ***Mix · CMYKW (PLA Palette)***, ***CMYW*** or ***RYBW (PLA Basic)***: Bambu Studio's color mixing. You load the base
  colors (the hint says which), and the other colors are mixed from them in thin sub-layers, after Bambu Lab's
  measured recipes. Only on printers with two or more hotends (H2D, H2D Pro, H2C, X2D, H3C): mixing changes filament
  on every sub-layer, and with one hotend that is much waste and a risk of clogging. Mixing takes much longer.

The colors are the ones Bambu Lab sells the filament in, by Bambu's own names (from Bambu Studio's color list, so new
colors come with a Bambu Studio update). A color that is not sold (or cannot be mixed closely) prints in the nearest
one, and the report, **Parts** (⚠) and the hint under **Colors** say so. When you send the print, Bambu Studio asks
which AMS slot holds which filament. Orientr sets the purge volumes between the colors (Bambu Studio's own color
formula, a little on the generous side), and parts in several colors need a prime tower: on a printer with two nozzles
the tool places it where both nozzles reach.

In `bambu.json`: `"colours": "model"`, `"manual"` (with `"colour": "#00B1B7"` for the project) or `"mix"` (with
`"mix": "CMYKW"`) in `print`, and `"colour"` per part (see above).

**Your own color template** (older way, command line only): a project saved in the Bambu Studio window with your AMS
filaments, in `%LOCALAPPDATA%\orientr\templates`, set as `"template"` in `bambu.json`. Its filaments are used as they
are (`"colours": "template"`) or get the model's colors (`"colours": "model"`), and `"filament": N` per part chooses one
of them. The form goes back to the printer's own template, since Orientr makes the filaments.

## Keeping it up to date

Most of what Orientr knows comes from Bambu Studio itself and is read anew after every Bambu Studio update, so it
stays current without you doing anything. A few things need you, and the tool tells you when.

### Comes with Bambu Studio by itself

| What | Read from Bambu Studio's |
|---|---|
| Filaments and process presets (a new filament appears in the list) | presets (read again once after an update, about 2 minutes) |
| Nozzle sizes per printer | printer presets |
| The colors Bambu Lab sells per filament, with their names | `filaments_color_codes.json` |
| Color mixing recipes (PLA Palette, CMYW, RYBW) | `standard_color_recipes.json` |
| Which printers can mix colors (two or more hotends) | printer presets |
| Data for the warnings (high-temperature filaments, nozzle combinations) | `resources/info/*.json` |

### After a Bambu Studio update

1. The status line says "Bambu Studio x not tested yet". Run **`orientr --selftest`** (`--selftest-all` slices with
   every template). It checks Studio's data files, the templates, a test slice (also with colors made by the tool, a
   mixed filament on printers with two or more hotends, and another nozzle size) and the Bambu Studio warnings the
   tool copies. All passed: the version is remembered and the line disappears.
2. **"saved with an older Studio, save them again"** (in the self-test or the report): Bambu Studio is newer than the
   one that saved a template (for example 2.9 → 2.10). Open that template in the Bambu Studio window and *File > Save
   Project As* over itself: the templates in `templates\` and your own in `%LOCALAPPDATA%\orientr\templates`. Until
   then the tool still works; this is a reminder, not a stop.
3. A **`warn`** line otherwise says what to do. A **`FAIL`** means Bambu Studio changed a format this tool reads:
   nothing you can set fixes that, the tool needs a new version. Please [open an issue](../../issues) with the line.

### A new printer

Bambu Studio knows it, Orientr does not yet: add a template for it, see [Templates](#templates) (*A printer that is
not here yet*). Everything else for it (filaments, processes, nozzle sizes, colors, mixing) then comes from Bambu
Studio.

### After a SOMA update

Orientr reads some of SOMA's own files (the parts list, colors and build status of a model). If SOMA changes
them, the tool says so instead of failing with a Python error; `orientr --selftest` checks them in its SOMA lines.
Please report a `FAIL` there, with SOMA's version.

### A new Orientr version

The status line says when there is one. Install it as in [Install](#install): unpack it and run its `install.cmd`.

### Fixed in the tool

At most 32 filaments and 16 mixed filaments per project (Bambu Studio's limits as far as known). The filament list
starts with the common ones (PLA Basic, PETG Basic, ...); new filaments appear below them in alphabetical order.

## Network and privacy

- The printer and your Bambu account are never contacted.
- At most every 12 hours the tool reads the file `VERSION` of this repository on GitHub (2 s timeout) to tell you
  about a newer version. Nothing is sent. `ORIENTR_NO_UPDATE_CHECK=1` switches it off. Without a connection to GitHub
  the status line says *no internet, update not checked* (and asks again after an hour); it says *up to date* only
  after a real check.
- Only when GitHub does not hand out that file (but the internet works), the tool asks the
  [GitHub CLI](https://cli.github.com/) (`gh`), when it is installed and you are logged in to it: that request goes
  with your GitHub login, as every `gh` command does. Without `gh`, nothing more is tried.
- `orientr --selftest` (only when you run it) downloads a few source files of Bambu Studio from its public repository on
  GitHub (github.com/bambulab/BambuStudio), to check the tool's rules against them. Nothing is sent.
- Settings of the tool (language, favorites, *Background Bambu Studio*, recently used printers, a cache of Bambu Studio's
  presets) and your own templates are kept in `%LOCALAPPDATA%\orientr`.

## Uninstall

Double-click **`uninstall.cmd`**: it removes the folder from your PATH and the shortcuts, and switches Bambu Studio's *single instance* setting off again if Orientr switched it on
(close Bambu Studio first; one you switched on yourself stays on). Then delete the Orientr folder and, if
you like, `%LOCALAPPDATA%\orientr` (your settings and your own templates).

## License

Copyright © 2026 Wouter Carleer. Orientr is licensed under the GNU General Public License version 3
(GPL-3.0), see [LICENSE](LICENSE).

The printer templates in `templates\` hold settings from Bambu Studio's system presets (printer, filament and process
values, start and end G-code), © Bambu Lab, licensed under the GNU Affero General Public License version 3 (AGPL-3.0);
see [templates/README.md](templates/README.md).

Orientr is not affiliated with or endorsed by Bambu Lab or SOMA; "Bambu Lab" and "Bambu Studio" are names of
their respective owners. What changed in each version is in [CHANGELOG.md](CHANGELOG.md). Technical notes for
developers are in [DEVELOPMENT.md](DEVELOPMENT.md).
