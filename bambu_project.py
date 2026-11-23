# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""The Bambu Studio part of Orientr: finding Bambu Studio, its templates (a saved project per printer) and presets
(printer, filament, process), writing the project (.3mf), the test slice with its command line and its warnings, its
settings file (single instance), starting it in the background, and its version.

orientr_core.py holds the slicer-independent rules, orientr.py the app. Another slicer gets a part of its own.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from orientr_core import *  # noqa: F401,F403  (the rules, the mesh, ToolError, TOOL_DIR, tr)
from orientr_core import _number, _version  # noqa: F401
from orientr_i18n import APP_DIR, t as tr  # noqa: F401


STUDIO_DEFAULT = r"C:\Program Files\Bambu Studio\bambu-studio.exe"


def _find_bambu_exe() -> str:
    """Bambu Studio's bambu-studio.exe: the BAMBU_STUDIO variable, else the default folder, else where its installer
    recorded it in Windows' registry (2026-11-22: installed in another folder or drive, it was not found
    without the variable): App Paths, then the uninstall entries (DisplayIcon / InstallLocation). The default path
    when none is found, so the messages name where it was looked for."""
    if os.environ.get("BAMBU_STUDIO"):
        return os.environ["BAMBU_STUDIO"]
    if os.path.isfile(STUDIO_DEFAULT) or os.name != "nt":
        return STUDIO_DEFAULT
    try:
        import winreg
    except ImportError:
        return STUDIO_DEFAULT
    found = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:                                              # App Paths: the exe itself
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\bambu-studio.exe") as k:
                found.append(str(winreg.QueryValueEx(k, "")[0]))
        except OSError:
            pass
        for root in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(hive, root) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            with winreg.OpenKey(k, winreg.EnumKey(k, i)) as e:
                                if not str(winreg.QueryValueEx(e, "DisplayName")[0]).startswith("Bambu Studio"):
                                    continue
                                for value in ("DisplayIcon", "InstallLocation"):
                                    try:
                                        v = str(winreg.QueryValueEx(e, value)[0]).strip().strip('"')
                                    except OSError:
                                        continue
                                    v = v.split(",")[0].strip('"')                  # "...exe,0"
                                    found.append(v if v.lower().endswith(".exe") else os.path.join(v, "bambu-studio.exe"))
                        except OSError:
                            continue
            except OSError:
                pass
    return next((f for f in found if os.path.basename(f).lower() == "bambu-studio.exe" and os.path.isfile(f)),
                STUDIO_DEFAULT)


BAMBU_EXE = _find_bambu_exe()


DEFAULT_TEMPLATE = TOOL_DIR / "templates" / "default.3mf"


# Bambu Studio's printer list: the online-updated copy first, then the one that came with the installation
BAMBU_VENDOR = [Path(os.environ.get("APPDATA", "")) / "BambuStudio" / "system" / "BBL.json",
                Path(BAMBU_EXE).parent / "resources" / "profiles" / "BBL.json"]


# --- template -------------------------------------------------------------------------------------------------------
@dataclass
class Template:
    path: Path
    app: str
    settings: dict
    files: dict              # name -> bytes, copied as they are
    plate_meta: list         # (key, value) of the template's first plate, without per-plate files
    bed_x: tuple             # usable x range (all extruders)
    bed_y: tuple
    bed_h: float
    plate_w: float
    plate_d: float
    filaments: int
    materials: list
    slope: float
    first_layer: float
    keep_out: list           # (x0, x1, y0, y1) zones where no part may stand (bed exclusion, wrap detection)
    tower: tuple | None      # (x0, x1, y0, y1) of the prime tower when it is on, used by plates with 2+ filaments
    warps: list              # per filament: why it tends to warp ("" = it does not)
    overrides: dict = field(default_factory=dict)   # process settings chosen in the menu / bambu.json "print"
    support_mode: str = "auto"                       # auto | on | off (a part's own hint still wins)
    brim_mode: str = "auto"                          # auto | on | off
    material: str = ""                               # filament chosen in bambu.json ("PETG Basic"), "" = template's
    filament_swap: dict = field(default_factory=dict)   # project settings that set_filament() changed
    process: str = ""                                # process chosen in bambu.json ("0.16mm Standard"), "" = template's
    process_swap: dict = field(default_factory=dict)    # project settings that set_process() changed
    printer_swap: dict = field(default_factory=dict)    # project settings that set_nozzle_size() changed
    nozzle_mode: str = "auto"                           # auto | left | right (menu: which nozzle's area is used)
    level: int = 0                                      # how tightly parts were packed, see pack()
    nozzle_boxes: list = field(default_factory=list)    # (x0, x1, y0, y1) per nozzle when the printer has 2+ nozzles
    nozzle: int | None = None                           # 1-based nozzle the filament is fixed to (own area used)
    duplicates: int = 1                                 # bambu.json "print": every printed part this many times
    max_plates: int = 0                                 # bambu.json "print": at most this many plates (0: no limit)
    colours: list = field(default_factory=list)         # per filament its colour as Bambu Studio keeps it ("#FFFFFF")
    tower_xy: tuple | None = None                       # prime tower moved where every nozzle reaches (x, y), see below
    colour_mode: str = "template"                       # bambu.json "print" "colours": template | model (recolour())
    colour_swap: dict = field(default_factory=dict)     # project settings that recolour() changed
    model_used: int = 0                                 # recolour(): the first this many filaments have model colours
    slots_swap: dict = field(default_factory=dict)      # project settings that expand_filaments() changed
    generated: bool = False                             # expand_filaments(): the slots were made here, one per colour
    colour_names: list = field(default_factory=list)    # per filament Bambu Lab's names of its colour ({lang: name})
    mixing: bool = False                                # colour mixing: base filaments and mixes of them (mix_plan)

    @property
    def filament_names(self) -> list:
        """Per filament the short preset name ("Bambu PLA Basic"), for the form and the report."""
        return [re.sub(r"\s*@.*$", "", str(n)) for n in self.settings.get("filament_settings_id") or []]

    def base(self, key: str) -> str:
        """The project-wide value of a process setting: the menu's choice, else the template's."""
        return str(self.overrides.get(key, self.settings.get(key, "")))


def _per_filament(ps: dict, key: str, n: int) -> list[float]:
    vals = ps.get(key)
    vals = vals if isinstance(vals, list) else [vals] * n
    out = []
    for i in range(n):
        try:
            out.append(float(str(vals[i] if i < len(vals) else vals[-1]).rstrip("%")))
        except (ValueError, TypeError, IndexError):
            out.append(0.0)
    return out


def _warping(ps: dict, n: int) -> list[str]:
    """Per filament, why it tends to warp, from its own profile, so that new materials are covered too:
    a hot bed (>= WARP_BED_TEMP) or a heated chamber; the known names are a fallback."""
    types = ps.get("filament_type") or [""] * n
    bed = [max(a, b) for a, b in zip(_per_filament(ps, "hot_plate_temp", n), _per_filament(ps, "textured_plate_temp", n))]
    chamber = _per_filament(ps, "chamber_temperatures", n)
    out = []
    for i in range(n):
        typ = str(types[i] if i < len(types) else "").upper()
        if chamber[i] > 0:
            out.append(tr("wp.chamber", typ=typ or tr("wp.filament"), i=i + 1, c=f"{chamber[i]:.0f}"))
        elif bed[i] >= WARP_BED_TEMP:
            out.append(tr("wp.bed", typ=typ or tr("wp.filament"), i=i + 1, c=f"{bed[i]:.0f}"))
        elif typ.startswith(WARP_MATERIALS):
            out.append(tr("wp.warps", typ=typ, i=i + 1))
        else:
            out.append("")
    return out


def _poly_bbox(s: str):
    pts = [tuple(float(c) for c in p.split("x")) for p in s.split(",") if "x" in p]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _zones(ps: dict) -> list:
    """Bed exclusion and filament-wrap detection zones as rectangles (empty or degenerate ones skipped)."""
    out = []
    for key in ("bed_exclude_area", "wrapping_exclude_area"):
        pts = [p for p in (ps.get(key) or []) if "x" in str(p)]
        if len(pts) >= 3:
            b = _poly_bbox(",".join(pts))
            if b[1] - b[0] > 0.1 and b[3] - b[2] > 0.1:
                out.append(b)
    return out


def _tower_spot(ps: dict) -> tuple | None:
    """(x, y, width, room around it) of the prime tower, moved onto the bed. Bambu Studio keeps the tower on the bed:
    the H2D template has it at y = 276 with 60 mm width, past the bed's 320 mm, and the window put it at the bed's
    edge, over a part placed there (2026-11-23: "Conflicts of gcode paths ... WipeTower <-> Hinge pin left"). Its
    depth is only known after slicing: a square. Room: the brim (auto = -1: 3 mm) and half a rib (rib walls)."""
    if str(ps.get("enable_prime_tower", "0")) != "1":
        return None
    first = lambda v: float((v if isinstance(v, list) else [v])[0])  # noqa: E731
    x, y = first(ps.get("wipe_tower_x", 15)), first(ps.get("wipe_tower_y", 220))
    w = float(ps.get("prime_tower_width", 35) or 35)
    room = max(float(ps.get("prime_tower_brim_width", 3) or 3), 3.0)
    if str(ps.get("prime_tower_rib_wall", "0")) == "1":
        room += float(ps.get("prime_tower_rib_width", 8) or 8) / 2 + float(ps.get("prime_tower_extra_rib_length", 0) or 0)
    try:
        bx0, bx1, by0, by1 = _poly_bbox(",".join(ps["printable_area"]))
    except (KeyError, TypeError, ValueError):
        return x, y, w, room
    x = min(max(x, bx0 + room), bx1 - room - w)
    y = min(max(y, by0 + room), by1 - room - w)
    return x, y, w, room


def _tower(ps: dict) -> tuple | None:
    """Prime tower footprint (x0, x1, y0, y1) where it prints, see _tower_spot."""
    spot = _tower_spot(ps)
    if not spot:
        return None
    x, y, w, room = spot
    return (x - room, x + w + room, y - room, y + w + room)


PERSONAL_META = ("DesignerUserId", "Designer", "DesignerCover")   # Bambu Studio fills these from the logged-in account


def strip_personal(path: Path) -> bool:
    """Empty the account metadata Bambu Studio writes into a saved project (DesignerUserId is the user's Bambu account
    number), so a template can be shared. Rewrites the file only when something was filled in; True if it did."""
    pat = re.compile(r'(<metadata name="(?:%s)">)[^<]+(</metadata>)' % "|".join(PERSONAL_META))
    with zipfile.ZipFile(path) as z:
        model = z.read("3D/3dmodel.model").decode("utf-8")
        if not pat.search(model):
            return False
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for info, data in items:
                if info.filename == "3D/3dmodel.model":
                    data = pat.sub(r"\1\2", model).encode("utf-8")
                out.writestr(info, data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)                       # gone after os.replace; left over only on an error
    return True


def load_template(path: Path) -> Template:
    # only the tool's templates and the user's templates folder: a model's inputs\bambu_template.3mf is the user's
    # file and stays as it is (SOMA: never change inputs/); the project made from it never carries the account number,
    # write_3mf writes its own metadata (2026-11-22)
    if path.exists() and path.parent in (TOOL_DIR / "templates", USER_TEMPLATES):
        try:                                              # a template saved in the window carries the account number
            if strip_personal(path):                      # stderr: stdout may be JSON (--status)
                print(f"  removed the Bambu account number from {path.name} (for sharing)", file=sys.stderr)
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
            pass                                          # unreadable: _load_template reports it below
        except OSError as e:                              # locked or read-only: say so, the file still has it
            print(f"  could not remove the Bambu account number from {path.name}: {e}", file=sys.stderr)
    if not path.exists():
        raise ToolError(
            f"no Bambu Studio template at {path}.\n"
            "  Make one: open Bambu Studio, choose printer, filament(s) and process as you print, put any small\n"
            "  object on the plate and save the project (File > Save Project As) to that path.")
    try:
        return _load_template(path)
    except ToolError:
        raise
    except (zipfile.BadZipFile, OSError, KeyError, ValueError, IndexError, TypeError, AttributeError,
            ET.ParseError) as e:
        raise ToolError(tr("e.tpl_read", file=path.name, err=f"{type(e).__name__}: {e}")) from None


def _place_tower(ps: dict, filaments: int, boxes: list, bed_x: tuple) -> tuple:
    """(footprint, moved position or None) of the prime tower. Several filaments on a printer with two nozzles (H2D):
    Bambu Studio may give some to the other nozzle, and each nozzle misses a strip at one side of the bed. A prime
    tower in such a strip stops the slice ("Found G-code in unprintable area", 2026-11-22, a 5-filament H2D project
    with the tower at x = 15): moved into the common area."""
    tower, spot = _tower(ps), _tower_spot(ps)
    if not tower:
        return None, None
    shift = 0.0
    if filaments > 1 and len(boxes) > 1:
        x0, x1 = bed_x
        shift = (x0 + 1 - tower[0]) if tower[0] < x0 + 1 else (x1 - 1 - tower[1]) if tower[1] > x1 - 1 else 0.0
    # written into the project always: the window then shows it where the parts left room for it
    return (tower[0] + shift, tower[1] + shift, tower[2], tower[3]), (spot[0] + shift, spot[1])


def _load_template(path: Path) -> Template:
    with zipfile.ZipFile(path) as z:
        contents = {n: z.read(n) for n in z.namelist()
                    if n in ("3D/3dmodel.model", "[Content_Types].xml") or n.startswith("Metadata/") and
                    n.endswith((".config", ".json", ".xml"))}
    names = list(contents)
    if "Metadata/project_settings.config" not in names or "3D/3dmodel.model" not in names:
        raise ToolError(tr("e.tpl_no_settings", file=path.name))
    model = contents["3D/3dmodel.model"].decode("utf-8", "replace")
    m = re.search(r'name="Application">([^<]*)<', model)
    app = m.group(1) if m else ""
    if not app.startswith("BambuStudio"):
        raise ToolError(tr("e.tpl_app", file=path.name, app=app or tr("v.unknown_app")))
    ps = json.loads(contents["Metadata/project_settings.config"])
    if not isinstance(ps, dict) or not isinstance(ps.get("printable_area"), list):
        raise ToolError(tr("e.tpl_unusable", file=path.name))
    if len(str(ps.get("machine_start_gcode", ""))) < 300:
        raise ToolError(tr("e.tpl_gcode", file=path.name))
    areas = ps.get("extruder_printable_area") or []
    boxes = [_poly_bbox(a) for a in areas if a] or [_poly_bbox(",".join(ps["printable_area"]))]
    x0, x1 = max(b[0] for b in boxes), min(b[1] for b in boxes)
    y0, y1 = max(b[2] for b in boxes), min(b[3] for b in boxes)
    full = _poly_bbox(",".join(ps["printable_area"]))
    heights = [float(h) for h in ps.get("extruder_printable_height", []) if float(h) > 0]
    bed_h = min(heights) if heights else float(ps.get("printable_height", 0))
    files = {n: contents[n] for n in ("Metadata/project_settings.config", "Metadata/slice_info.config",
                                      "[Content_Types].xml") if n in names}
    plate_meta = []
    if "Metadata/model_settings.config" in names:
        plate = ET.fromstring(contents["Metadata/model_settings.config"]).find("plate")
        if plate is not None:
            skip = {"plater_id", "plater_name", "locked", "gcode_file", "thumbnail_file", "thumbnail_no_light_file",
                    "top_file", "pick_file", "pattern_file", "pattern_bbox_file"}
            for m in plate.findall("metadata"):                  # direct children only, not the model instances
                k, v = m.get("key"), m.get("value")
                if k and v is not None and k not in skip:
                    plate_meta.append((k, v))
    fil = ps.get("filament_settings_id") or ["?"]
    tower, tower_xy = _place_tower(ps, len(fil), boxes, (x0, x1))
    tpl = Template(path, app, ps, files, plate_meta, (x0, x1), (y0, y1), bed_h, full[1] - full[0], full[3] - full[2],
                   len(fil), [str(t).upper() for t in ps.get("filament_type", [])],
                   float(ps.get("support_threshold_angle", 30) or 30),
                   float(ps.get("initial_layer_print_height", 0.2) or 0.2), _zones(ps), tower,
                   _warping(ps, len(fil)))
    tpl.tower_xy = tower_xy
    if len(boxes) > 1:
        tpl.nozzle_boxes = boxes
    tpl.colours = [str(c) for c in (ps.get("filament_colour") or [])][:len(fil)]
    return tpl


def recolour(t: Template, rgbs: list) -> list[int]:
    """Give the template's filaments the colours `rgbs` (sRGB 0..1, at most one per filament; the others keep theirs)
    and purge volumes to match; returns the filament numbers that changed colour. Only values in lists that keep their
    length: Bambu Studio refuses a project whose per-filament lists do not fit ("Invalid configuration file"), and its
    command line crashes when asked to add filaments (2026-11-23), so the number of filaments stays the template's."""
    n = t.filaments
    old = (list(t.colours) + ["#FFFFFF"] * n)[:n]
    new = list(old)
    for i, rgb in enumerate(rgbs[:n]):
        if hex_srgb(old[i]) is None or srgb_hex(hex_srgb(old[i])) != srgb_hex(rgb):
            new[i] = srgb_hex(rgb)
    t.model_used = min(n, len(rgbs))                      # parts go by colour to these only (colour_choices)
    changed = [i + 1 for i in range(n) if new[i] != old[i]]
    if not changed:
        return []
    ps = t.settings
    swap = {"filament_colour": new}
    multi = ps.get("filament_multi_colour")               # one colour per filament here (no multi-colour filaments)
    if isinstance(multi, list) and len(multi) == n:
        swap["filament_multi_colour"] = list(new)
    matrix = ps.get("flush_volumes_matrix")
    if isinstance(matrix, list) and n > 1 and len(matrix) % (n * n) == 0:
        nozzles = len(matrix) // (n * n)
        base = flush_base(old, matrix, nozzles)
        rgb = [hex_srgb(c) or (1.0, 1.0, 1.0) for c in new]   # transparent counts as white, as in Bambu Studio
        m = [str(v) for v in matrix]
        for z in range(nozzles):
            for i in range(n):
                for j in range(n):
                    if i != j and (i + 1 in changed or j + 1 in changed):
                        m[z * n * n + i * n + j] = str(flush_volume(rgb[i], rgb[j], base[z]))
        swap["flush_volumes_matrix"] = m
    t.colour_swap = swap
    t.colours = new
    return changed


# Lists with one block of values per filament: the filament preset's own keys, every "filament_..." key and these.
# Checked 2026-11-23 against a 32-filament H2D project saved in the window (exactly these lists grow with the number of
# filaments) and the one-filament templates of A1, X1C, P2S, H2C (no other keys). The purge matrix is built apart.
PER_FILAMENT_EXTRA = frozenset({
    "close_optional_fan_first_x_layers", "default_filament_colour", "enable_overhang_bridge_fan",
    "enable_pressure_advance", "first_x_layer_fan_speed", "first_x_layer_optional_fan_speed",
    "first_x_layer_part_fan_speed", "flush_volumes_vector", "ironing_fan_speed", "min_temperature_when_ec",
    "optional_cooling_fan_speed", "optional_fan_full_speed_layer", "overhang_threshold_participating_cooling",
    "pressure_advance"})


def per_filament_keys(ps: dict) -> list[str]:
    """The project settings that hold one block of values per filament (see PER_FILAMENT_EXTRA)."""
    own = set(flat_filament(str((ps.get("filament_settings_id") or [""])[0])))
    return [k for k, v in ps.items() if isinstance(v, list) and v and k != "flush_volumes_matrix"
            and (k in own or k.startswith("filament_") or k in PER_FILAMENT_EXTRA)]


MAX_SLOTS = 32            # filaments Bambu Studio takes in one project (as MAX_FILAMENTS)


MIX_KEYS = ("filament_is_mixed", "filament_mixed_components", "filament_mixed_sublayer_ratios")


def expand_filaments(t: Template, colours: list[str], mixes: list | None = None) -> None:
    """Give a one-filament template one filament per colour ('#RRGGBB'): slot 1 (its preset and values, the chosen
    filament included) as often as needed, each with its colour, purge volumes by colour. So no colour template is
    needed (2026-11-23). Bambu Studio's command line crashes when asked to add filaments, so the lists are written as
    the window writes them for that many filaments: per filament the same block, a running number in
    filament_self_index, an n x n purge matrix per nozzle.
    mixes: mixed filaments after the physical ones (Bambu Studio's colour mixing, 2026-11-23), each
    (components, ratios, '#RRGGBB'): 1-based numbers of physical filaments and their shares (summing to 1), printed in
    alternating sub-layers; a mixed filament is a slot like the others with filament_is_mixed "1"."""
    mixes = list(mixes or [])
    n = len(colours) + len(mixes)
    if t.filaments != 1 or not 1 <= n <= MAX_SLOTS:
        raise ValueError(f"expand_filaments: {t.filaments} filaments, {n} colours")
    for comps, ratios, _ in mixes:
        if len(comps) < 2 or len(comps) != len(ratios) or any(not 1 <= c <= len(colours) for c in comps):
            raise ValueError(f"expand_filaments: mixed filament {comps} {ratios}")
    t.generated = True
    if n == 1:                                            # one colour: the template's one filament gets it
        recolour(t, [hex_srgb(colours[0]) or (1.0, 1.0, 1.0)])
        t.model_used = 1
        return
    colours = list(colours) + [h for *_, h in mixes]
    ps, swap = t.settings, {}
    phys = n - len(mixes)
    mix_vals = {"filament_is_mixed": ["0"] * phys + ["1"] * len(mixes),
                "filament_mixed_components": [""] * phys + [",".join(str(c) for c in m[0]) for m in mixes],
                "filament_mixed_sublayer_ratios": [""] * phys + [",".join(f"{r:.4f}" for r in m[1]) for m in mixes]}
    for k in per_filament_keys(ps):
        v = [str(x) for x in ps[k]]
        if k == "filament_self_index":
            swap[k] = [str(i + 1) for i in range(n) for _ in v]
        elif k in ("filament_colour", "filament_multi_colour") and len(v) == 1:
            swap[k] = list(colours)
        elif k in MIX_KEYS and len(v) == 1:
            swap[k] = mix_vals[k]
        else:
            swap[k] = v * n
    if mixes:                                             # the process splits layers with mixed filaments
        t.overrides["enable_mixed_color_sublayer"] = "1"
    matrix = ps.get("flush_volumes_matrix")
    if isinstance(matrix, list) and matrix:               # one value per nozzle with one filament
        nozzles = len(matrix)
        base = flush_base((list(t.colours) or ["#FFFFFF"])[:1], matrix, nozzles)   # one filament: the default minimum
        rgb = [hex_srgb(c) or (1.0, 1.0, 1.0) for c in colours]
        swap["flush_volumes_matrix"] = ["0" if i == j else str(flush_volume(rgb[i], rgb[j], base[z]))
                                        for z in range(nozzles) for i in range(n) for j in range(n)]
    dts = ps.get("different_settings_to_system")
    if isinstance(dts, list) and len(dts) == 3:           # process, filament, printer
        swap["different_settings_to_system"] = [str(dts[0])] + [str(dts[1])] * n + [str(dts[2])]
    ps.update(swap)
    t.slots_swap = swap
    t.filaments = n
    t.colours = list(colours)
    t.model_used = n
    t.materials = [str(x).upper() for x in ps.get("filament_type", [])]
    t.warps = _warping(ps, n)
    t.tower, t.tower_xy = _place_tower(ps, n, t.nozzle_boxes, t.bed_x)


_MIX: dict[str, tuple] = {}


def mix_recipes() -> dict[str, tuple[str, list]]:
    """Bambu Studio's colour mixing recipes (resources/filament_mixing/standard_color_recipes.json, measured by Bambu
    Lab): mode ('CMYKW', 'CMYW', 'RYBW') -> (filament 'PLA Palette' / 'PLA Basic', [(components [(name, '#RRGGBB')],
    shares summing to 1, the colour it prints '#RRGGBB')]); {} when Bambu Studio has none (older versions)."""
    if not _MIX:
        try:
            f = Path(BAMBU_EXE).parent / "resources" / "filament_mixing" / "standard_color_recipes.json"
            entries = json.loads(f.read_text(encoding="utf-8")).get("entries") or []
        except (OSError, ValueError, AttributeError):
            entries = []
        for e in entries:
            try:
                comps = [(str(c["key"]), str(c["rgb"]).upper()) for c in e["components"]]
                total = float(sum(e["ratios"]))
                ratios = [float(r) / total for r in e["ratios"]]
                out = str(e["measured_rgb"]).upper()
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if len(comps) >= 2 and len(comps) == len(ratios) and hex_srgb(out) and all(hex_srgb(h) for _, h in comps):
                mat = str(e.get("material") or "")
                _MIX.setdefault(str(e.get("mode") or ""), (mat, []))[1].append((comps, ratios, out))
        _MIX.setdefault("", ("", []))                     # looked once, also when nothing was found
    return {m: v for m, v in _MIX.items() if m}


def hotends(t: Template) -> int:
    """How many hotends the printer holds (H3C: 9, H2D: 2, X1C: 1): colour mixing is offered from 2 on, since it
    changes filament on every sub-layer (Bambu Studio: on a single-extruder printer much waste and a risk of clogging)."""
    ps = t.settings
    counts = ps.get("extruder_max_nozzle_count")
    if not isinstance(counts, list):
        counts = flat_profile("machine", str(ps.get("printer_settings_id") or "")).get("extruder_max_nozzle_count")
    try:
        n = sum(int(float(c)) for c in counts or [])
    except (TypeError, ValueError):
        n = 0
    return max(n, len(ps.get("nozzle_diameter") or [1]))


_OFFICIAL: dict[str, list] = {}


def official_colours(filament_id: str) -> list[tuple[str, dict]]:
    """The colours Bambu Lab sells this filament in ('GFA00' = PLA Basic), as Bambu Studio lists them
    (filaments_color_codes.json next to its filament presets): [('#RRGGBB', {language: name})], single colours only;
    [] for a filament it does not list (generic and other brands)."""
    if not _OFFICIAL:
        for vendor in BAMBU_VENDOR:                       # the online-updated copy first
            f = vendor.parent / "BBL" / "filament" / "filaments_color_codes.json"
            try:
                data = json.loads(f.read_text(encoding="utf-8")).get("data") or []
            except (OSError, ValueError, AttributeError):
                continue
            for x in data:
                cols = x.get("fila_color") or []
                if len(cols) == 1 and x.get("fila_id") and hex_srgb(str(cols[0])[:7]):
                    _OFFICIAL.setdefault(str(x["fila_id"]), []).append(
                        (str(cols[0])[:7].upper(), dict(x.get("fila_color_name") or {})))
            if _OFFICIAL:
                break
        _OFFICIAL.setdefault("", [])                      # looked once, also when nothing was found
    return _OFFICIAL.get(filament_id, [])


# --- 3MF ------------------------------------------------------------------------------------------------------------
NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')


def _mesh_xml(oid: int, verts: np.ndarray, faces: np.ndarray) -> str:
    vs = "\n".join(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
    ts = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    return (f'  <object id="{oid}" p:UUID="{uuid.uuid4()}" type="model">\n   <mesh>\n    <vertices>\n{vs}\n'
            f'    </vertices>\n    <triangles>\n{ts}\n    </triangles>\n   </mesh>\n  </object>\n')


def write_3mf(out: Path, plates, t: Template, title: str) -> None:
    cols = math.ceil(math.sqrt(len(plates)))
    res, build, rels, objects_cfg, plates_cfg, assemble = [], [], [], [], [], []
    files: dict[str, bytes] = {}
    oid = 0
    for pi, (pname, items) in enumerate(plates):
        ox = (pi % cols) * t.plate_w * (1 + PLATE_GAP)
        oy = -(pi // cols) * t.plate_d * (1 + PLATE_GAP)
        instances = []
        for k, (p, cx, cy, turn) in enumerate(items):
            rot = p.an.rot
            if turn:
                rot = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]]) @ rot
            vols = [(p, p.filament)] + p.extras
            placed = []
            for vp, fil in vols:
                v = vp.mesh.verts @ rot.T
                placed.append((vp, fil, v))
            allv = np.vstack([v for _, _, v in placed])
            lo, hi = allv.min(axis=0), allv.max(axis=0)
            ctr = (lo + hi) / 2
            oid += 1
            obj_id = 1000 + oid
            sub = f"3D/Objects/object_{oid}.model"
            body, comps, parts_cfg = [], [], []
            for vi, (vp, fil, v) in enumerate(placed):
                vid = oid * 100 + vi + 1
                body.append(_mesh_xml(vid, v - ctr, vp.mesh.faces))
                comps.append(f'    <component p:path="/{sub}" objectid="{vid}" p:UUID="{uuid.uuid4()}" '
                             f'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
                parts_cfg.append(
                    f'    <part id="{vid}" subtype="normal_part">\n'
                    f'      <metadata key="name" value={quoteattr(vp.name)}/>\n'
                    f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                    + (f'      <metadata key="extruder" value="{fil}"/>\n' if vi else "")
                    + f'      <mesh_stat face_count="{len(vp.mesh.faces)}" edges_fixed="0" degenerate_facets="0" '
                    'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>')
            files[sub] = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS}>\n'
                          f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n{"".join(body)}'
                          ' </resources>\n <build/>\n</model>\n').encode("utf-8")
            rels.append(f' <Relationship Target="/{sub}" Id="rel-{oid}" '
                        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
            res.append(f'  <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n'
                       + "\n".join(comps) + "\n   </components>\n  </object>")
            tx, ty, tz = ox + cx, oy + cy, ctr[2] - lo[2]
            build.append(f'  <item objectid="{obj_id}" p:UUID="{uuid.uuid4()}" '
                         f'transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} {tz:.4f}" printable="1"/>')
            meta = [f'    <metadata key="name" value={quoteattr(p.name)}/>',
                    f'    <metadata key="extruder" value="{p.filament}"/>']
            meta += [f'    <metadata key={quoteattr(k)} value={quoteattr(v)}/>' for k, v in p.settings.items()]
            objects_cfg.append(f'  <object id="{obj_id}">\n' + "\n".join(meta) + "\n" + "\n".join(parts_cfg)
                               + "\n  </object>")
            instances.append(f'    <model_instance>\n      <metadata key="object_id" value="{obj_id}"/>\n'
                             f'      <metadata key="instance_id" value="0"/>\n'
                             f'      <metadata key="identify_id" value="{500 + oid}"/>\n    </model_instance>')
            assemble.append(f'   <assemble_item object_id="{obj_id}" instance_id="0" '
                            f'transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} {tz:.4f}" offset="0 0 0" />')
        pmeta = [f'    <metadata key="plater_id" value="{pi + 1}"/>',
                 f'    <metadata key="plater_name" value={quoteattr(pname)}/>',
                 '    <metadata key="locked" value="false"/>']
        pmeta += [f'    <metadata key={quoteattr(k)} value={quoteattr(v)}/>' for k, v in t.plate_meta]
        plates_cfg.append("  <plate>\n" + "\n".join(pmeta + instances) + "\n  </plate>")

    today = time.strftime("%Y-%m-%d")
    main = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS}>\n'
            f' <metadata name="Application">{escape(t.app)}</metadata>\n'
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
            f' <metadata name="CreationDate">{today}</metadata>\n'
            f' <metadata name="ModificationDate">{today}</metadata>\n'
            f' <metadata name="Title">{escape(title)}</metadata>\n'
            ' <resources>\n' + "\n".join(res) + '\n </resources>\n'
            f' <build p:UUID="{uuid.uuid4()}">\n' + "\n".join(build) + '\n </build>\n</model>\n')
    model_cfg = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(objects_cfg + plates_cfg)
                 + '\n  <assemble>\n' + "\n".join(assemble) + '\n  </assemble>\n</config>\n')
    seq = {f"plate_{i + 1}": {"nozzle_sequence": [], "optimal_assignment": [], "sequence": []}
           for i in range(len(plates))}
    content_types = t.files.get("[Content_Types].xml") or (
        b'<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        b'content-types">\n <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        b'relationships+xml"/>\n <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-'
        b'3dmodel+xml"/>\n <Default Extension="png" ContentType="image/png"/>\n</Types>\n')
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships">\n <Relationship Target="/3D/3dmodel.model" '
                   'Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
                   '</Relationships>\n')
        z.writestr("3D/3dmodel.model", main)
        z.writestr("3D/_rels/3dmodel.model.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns='
                   '"http://schemas.openxmlformats.org/package/2006/relationships">\n' + "\n".join(rels)
                   + "\n</Relationships>\n")
        for name, data in files.items():
            z.writestr(name, data)
        ps_bytes = t.files["Metadata/project_settings.config"]
        ps = json.loads(ps_bytes)
        changed = False
        if isinstance(ps.get("wipe_tower_x"), list) and isinstance(ps.get("wipe_tower_y"), list) and ps["wipe_tower_x"]:
            # one prime tower position per plate, all where the packer kept room for it
            x, y = (f"{v:g}" for v in t.tower_xy) if t.tower_xy else (ps["wipe_tower_x"][0], ps["wipe_tower_y"][0])
            ps["wipe_tower_x"] = [x] * len(plates)
            ps["wipe_tower_y"] = [y] * len(plates)
            changed = True
        over = dict(t.overrides)
        if "sparse_infill_density" in over:      # the window sets these with the infill too
            for k in INFILL_LINKED:
                over[k] = over["sparse_infill_density"]
        ps.update(t.printer_swap)                 # a chosen nozzle size: the printer preset of that size
        ps.update(t.process_swap)                 # a chosen process preset first; walls/infill below go on top
        if ("sparse_infill_density" in over and _number(over["sparse_infill_density"]) >= 100
                and ps.get("sparse_infill_pattern") != FULL_INFILL_PATTERN):
            over["sparse_infill_pattern"] = FULL_INFILL_PATTERN       # as the window's "Yes" does
            t.overrides["sparse_infill_pattern"] = f"{FULL_INFILL_PATTERN} ({tr('r.rectilinear')})"
        done = []
        for k, v in over.items():                 # project-wide choices from the menu (plain text values only)
            if isinstance(ps.get(k), str):        # listed even when equal: the preset's own value may differ
                ps[k] = str(v)
                done.append(k)
        ps.update(t.filament_swap)                # a chosen filament: its preset name and values in slot 1
        if t.slots_swap:                          # one filament per colour, made from slot 1 (expand_filaments)
            ps.update(t.slots_swap)
            changed = True
        if t.colour_swap:                         # the model's colours on the template's filaments (recolour)
            ps.update(t.colour_swap)
            changed = True
        if t.nozzle is not None:                  # plates use one nozzle's own area: the filament must print there
            ps["filament_map_mode"] = "Manual"
            ps["filament_map"] = [str(t.nozzle)] * max(1, len(ps.get("filament_map") or [""]))
            changed = True
        if done or t.filament_swap or t.process_swap or t.printer_swap:
            # The window loads the system process preset and keeps only the keys listed here as changed (one entry
            # per preset: process, each filament, printer); without this it shows the preset's own values again
            n = 2 + len(ps.get("filament_settings_id") or [""])
            old = ps.get("different_settings_to_system")
            old = [str(d) for d in old] if isinstance(old, list) else []
            if len(old) == n:
                diff = old
            else:                                 # odd length: keep process and printer, filaments as far as known
                diff = [old[0] if old else ""] + (old[1:-1] + [""] * n)[:n - 2] + [old[-1] if len(old) > 1 else ""]
            if t.process_swap:                    # the template's changes belonged to its old process preset
                diff[0] = ""
            diff[0] = ";".join(sorted(set(filter(None, diff[0].split(";"))) | set(done)))
            if t.filament_swap:                   # the new filament is the plain system preset: nothing changed
                diff[1:-1] = [""] * (n - 2)       # every slot made from it too (expand_filaments)
            if t.printer_swap:                    # likewise the printer preset of the new nozzle size
                diff[-1] = ""
            ps["different_settings_to_system"] = diff
            changed = True
        if changed:
            ps_bytes = json.dumps(ps, indent=4, ensure_ascii=False).encode("utf-8")
        z.writestr("Metadata/project_settings.config", ps_bytes)
        if "Metadata/slice_info.config" in t.files:
            z.writestr("Metadata/slice_info.config", t.files["Metadata/slice_info.config"])
        z.writestr("Metadata/model_settings.config", model_cfg)
        z.writestr("Metadata/filament_sequence.json", json.dumps(seq))
    try:
        os.replace(tmp, out)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise ToolError(tr("e.locked", path=out))


# --- check with Bambu Studio's command line ------------------------------------------------------------------------
class CHECK:
    clean = False            # set by check_with_bambu: sliced without errors or warnings


CLUMP_MSG = ("Risk of nozzle clumping detected with the current high-temperature filament ({names}). We recommend "
             "enabling clumping detection (via probing). This feature uses a quick probing sequence to check for "
             "nozzle buildup during the print and utilizes the prime tower to absorb oozing before resuming.")


# Where the rules below come from. Everything not read live from Studio's resources folder is copied from Studio's
# open source (https://github.com/bambulab/BambuStudio, master), checked against this Studio version:
RULES_VERSION = "02.09.01.70"          # SLIC3R_VERSION in version.inc, also the latest release (v02.09.01.70) on 2026-11-21


RULES_REPO_RAW = "https://raw.githubusercontent.com/bambulab/BambuStudio/master/"


RULES_SOURCES = [                      # (what is copied, file in the source, function / enum, fingerprint of its text)
    ("clumping rule", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_high_temp_need_wrapping_detection", "346311e52a2c"),
    ("shrinkage ids (HIGH_SHRINKAGE_IDS)", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_high_shrinkage_filament", "3a7c35159b42"),
    ("brittle types (PPS-CF, PPA-CF)", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_brittle_filament", "326d0ce3c8b2"),
    ("PLA + PETG, X2D exception", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_mixture_of_pla_and_petg", "f4a0a6b4e093"),
    ("PVA + PETG", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_mixture_filament_compatible", "5712ad2ac6c8"),
    ("no prime tower", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_multi_filament_without_prime_tower", "493467fa016d"),
    ("nozzle and filament", "src/slic3r/GUI/PartPlate.cpp", "PartPlate::check_compatible_of_nozzle_and_filament", "a10a1cb7790b"),
    ("nozzle volume names", "src/libslic3r/PrintConfig.hpp", "enum NozzleVolumeType", "a40895170bf0"),
    ("message texts", "src/slic3r/GUI/GLCanvas3D.cpp", "GLCanvas3D::_set_warning_notification", "41f850ee907e"),
]


def source_function(src: str, name: str) -> str:
    """The text of one function (or enum) from a C++ source, from its name to the closing brace, without comments and
    whitespace, so that only a real change of the code changes it. '' when it is not found."""
    m = re.search(r"^[^\n;]*\b" + re.escape(name) + r"\s*(\(|\{|$)", src, re.M)
    if not m:
        return ""
    start = src.index("{", m.start())
    depth = 0
    for i in range(start, len(src)):
        depth += (src[i] == "{") - (src[i] == "}")
        if depth == 0:
            body = re.sub(r"//[^\n]*", "", src[m.start():i + 1])
            return re.sub(r"\s+", "", body)
    return ""


def source_fingerprint(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def studio_rules_note(slice_info: bytes) -> str:
    """A note when the Bambu Studio that sliced the project is not the version the rules were copied from, and the
    self-test (--selftest) has not confirmed that version yet."""
    try:
        hdr = {h.get("key"): h.get("value") for h in ET.fromstring(slice_info).iter("header_item")}
    except ET.ParseError:
        return ""
    ver = hdr.get("X-BBL-Client-Version") or ""
    if not ver or ver == RULES_VERSION or ver == verified_version():
        return ""
    return (f"Bambu Studio is version {ver}, the Studio warnings in this tool follow {RULES_VERSION}. Studio may have "
            "changed its rules: run  orientr --selftest  to compare them with Studio's source.")


SHRINK_MSG = ("Filament Shrinkage: filaments such as {names} have higher shrinkage rates, which may cause slight "
              "dimensional deviations after cooling and affect assembly fit. It is recommended to refer to the Wiki for "
              "shrinkage calibration to achieve more accurate print results.")


BRITTLE_MSG = ("Detected brittle filament (e.g., PPS-CF). Please place the models at the center of the heated bed. "
               "Printing near the edge may cause the filament to bend excessively and break inside the tube.")


PLA_PETG_MSG = ("PLA and PETG filaments detected in the mixture. Adjust parameters according to the Wiki to ensure "
                "print quality.")


NO_TOWER_MSG = "The prime tower improves multi-color print quality and is recommended."


MIX_MSG = "Mixing {a} with {b} in printing is not recommended."


NOZZLE_MSG = "It is not recommended to print the following filament(s) with {nozzle}: {names}"


# Filament IDs Bambu Studio treats as high-shrinkage (list copied from PartPlate::check_high_shrinkage_filament in
# Studio's source; it is compiled into the program, so re-check it after a Studio update)
HIGH_SHRINKAGE_IDS = {"GFN08", "GFB00", "GFB99", "GFB50", "GFB01", "GFB98", "GFT01", "GFB51", "GFN05", "GFC00", "GFC99",
                      "GFC01", "GFN04", "GFN06", "GFN97", "GFT02", "GFT98", "GFG50", "GFG98", "GFG00", "GFA06", "GFG01",
                      "GFG02", "GFG96"}


NOZZLE_VOLUME_NAMES = ["Standard", "High Flow", "Hybrid", "TPU High Flow", "TPU285", "E3D High Flow"]


def _aslist(v) -> list:
    """Project settings hold a single value as a plain string, several as a list."""
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def studio_gui_warnings(z: zipfile.ZipFile) -> list[tuple[int, str, bool]]:
    """Warnings per plate that Bambu Studio only shows in its window (PartPlate / GLCanvas3D::_update_...), never in the
    command line's result.json: (plate, text, standard). The rules are Studio's own (open source), applied to the sliced
    project and to Studio's data files (resources/info, resources/printers). `standard` marks information that Studio
    always gives for the filament in use, however the project is set up; the others point at a setting you can change.
    Not covered: checks that need a dual-nozzle layout (nozzle cannot print filament, flow, TPU nozzles, TPU 2.85),
    mixed-colour filaments, and object-based checks (outside plate, clashes), which Studio's slice reports itself."""
    res = Path(BAMBU_EXE).parent / "resources"
    try:
        ps = json.loads(z.read("Metadata/project_settings.config"))
        root = ET.fromstring(z.read("Metadata/slice_info.config"))
    except (KeyError, ValueError, ET.ParseError):
        return []

    def data(*parts):
        try:
            return json.loads(Path(res, *parts).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    info = data("info", "filament_info.json")
    incompatible = data("info", "nozzle_incompatibles.json").get("incompatible_nozzles", {})
    model = str(ps.get("printer_model") or "")
    wrap_supported = any(isinstance(v, dict) and v.get("display_name") == model and v.get("support_wrapping_detection") is True
                         for f in (res / "printers").glob("*.json") for v in data("printers", f.name).values())
    wrap_on = str((_aslist(ps.get("enable_wrapping_detection")) or ["0"])[0]).lower() in ("1", "true")
    types, ids, settings = (_aslist(ps.get(k)) for k in ("filament_type", "filament_ids", "filament_settings_id"))
    support = _aslist(ps.get("filament_is_support"))
    diam = _aslist(ps.get("filament_diameter_map")) or _aslist(ps.get("nozzle_diameter"))
    fmap, vmap = _aslist(ps.get("filament_map")), _aslist(ps.get("filament_volume_map"))
    vtypes = _aslist(ps.get("nozzle_volume_type"))
    by_object = str(ps.get("print_sequence") or "") == "by object"
    tower = str((_aslist(ps.get("enable_prime_tower")) or ["1"])[0]) in ("1", "true")
    high = set(info.get("high_temp_filament") or [])
    out = []
    for i, pl in enumerate(root.findall("plate")):
        kv = {m.get("key"): m.get("value") for m in pl.findall("metadata")}
        n = int(kv.get("index") or i + 1)
        used = sorted({int(f.get("id") or 0) - 1 for f in pl.findall("filament") if int(f.get("id") or 0) > 0})
        used = [k for k in used if k < len(types)]
        if not used:
            continue
        ftypes = [types[k] for k in used]
        hot = sorted({t for t in ftypes if t in high})
        if hot and wrap_supported and not wrap_on:
            out.append((n, CLUMP_MSG.format(names=", ".join(hot)), True))
        shrink = sorted({settings[k].split("@")[0].strip() if k < len(settings) else ids[k] for k in used
                         if k < len(ids) and ids[k] in HIGH_SHRINKAGE_IDS})
        if shrink:
            out.append((n, SHRINK_MSG.format(names=", ".join(shrink)), True))
        if any(t in ("PPS-CF", "PPA-CF") for t in ftypes):
            out.append((n, BRITTLE_MSG, True))
        model_fils = [k for k in used if not (k < len(support) and str(support[k]) in ("1", "true"))]
        if model != "Bambu Lab X2D" and any(types[k] == "PLA" for k in model_fils) and any(types[k] == "PETG" for k in model_fils):
            out.append((n, PLA_PETG_MSG, False))
        if "PVA" in ftypes and "PETG" in ftypes:
            out.append((n, MIX_MSG.format(a="PVA", b="PETG"), False))
        if len(used) > 1 and not tower and not by_object:
            out.append((n, NO_TOWER_MSG, False))
        bad: dict[tuple[str, str], set] = {}
        for k in used:
            if k >= len(settings) or k >= len(diam):
                continue
            ext = int(fmap[k]) - 1 if k < len(fmap) and str(fmap[k]).isdigit() else 0
            vol = int(vmap[k]) if k < len(vmap) and str(vmap[k]).isdigit() else -1
            if not 0 <= vol < len(NOZZLE_VOLUME_NAMES) or vol == 2:
                vol = NOZZLE_VOLUME_NAMES.index(vtypes[ext]) if 0 <= ext < len(vtypes) and vtypes[ext] in NOZZLE_VOLUME_NAMES else -1
            if vol < 0 or vol == 2:
                continue
            vname, d, alias = NOZZLE_VOLUME_NAMES[vol], f"{float(diam[k]):.1f}", settings[k].split("@")[0].strip()
            if alias in (incompatible.get(vname, {}).get(d) or []):
                bad.setdefault((d, vname), set()).add(alias)
        for (d, vname), names in sorted(bad.items()):
            out.append((n, NOZZLE_MSG.format(nozzle=f"{d}mm {vname} nozzle", names=",".join(sorted(names))), False))
    return out


def check_with_bambu(out: Path, plates, expected: dict) -> list[str]:
    """Slice every plate with Bambu Studio's command line and read the per-object settings back."""
    CHECK.clean = False
    if not Path(BAMBU_EXE).exists():
        return [tr("c.skipped", path=shown_path(BAMBU_EXE))]   # goes into the report: no user name in it
    msgs = []
    with orientr_tempdir() as td:
        td = Path(td)
        cmd = [BAMBU_EXE, "--slice", "0", "--outputdir", str(td), "--export-3mf", "check.3mf", str(out)]
        t0 = time.time()
        import bambu_studio
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace") as r:
            bambu_studio.OWN_CLI.add(r.pid)               # not the user starting Studio: keep_hidden goes on
            try:
                r.communicate(timeout=1800)
            except subprocess.TimeoutExpired:
                r.kill()
                r.communicate()
        res = td / "result.json"
        # UTF-8: Bambu Studio writes it so, and a part name with accents must not crash the check (review 2026-11-22)
        info = json.loads(res.read_text(encoding="utf-8", errors="replace")) if res.exists() else {}
        code = info.get("return_code", r.returncode)
        if code != 0:
            return [tr("c.failed", err=info.get("error_string", ""), code=code)]
        # Bambu Studio's own warnings (the ones its window shows after slicing), per plate
        rims = {p.name: p.an.bed_rim for _, items in plates for p, *_ in items if p.an.ignored.get("bed rims")}
        warned = []
        for i, sp in enumerate(info.get("sliced_plates") or []):
            raw = str(sp.get("warning_message") or "")
            wm = " ".join(raw.split())
            if not wm:
                continue
            warned.append(tr("c.warns", n=sp.get("id", i + 1), msg=wm))
            # names from the original text (a name may hold double spaces); Bambu quotes them with "", accept '' too
            for _, name in re.findall(r'Model (["\'])(.+?)\1 has \d+ overhang region', raw):
                if name in rims:
                    warned.append(tr("c.rim", name=name, mm=f"{rims[name]:.1f}"))
        back = td / "check.3mf"
        standard = []                                     # information Studio always gives with this filament: do not count
        if back.exists():
            with zipfile.ZipFile(back) as z:
                for n, m, std in studio_gui_warnings(z):
                    (standard if std else warned).append(tr("c.warns", n=n, msg=f"{m} {tr('c.standard_note')}" if std else m))
        # only standard notes: not "without warnings" with warnings right under it (2026-11-22)
        msgs.append(tr("c.sliced_warn" if warned else "c.sliced_std" if standard else "c.sliced_ok", n=len(plates),
                       s=f"{time.time() - t0:.0f}", k=len(standard)))
        CHECK.clean = not warned
        msgs += warned + standard
        note = ""
        if back.exists():
            with zipfile.ZipFile(back) as zv:
                note = studio_rules_note(zv.read("Metadata/slice_info.config"))
        if note:
            msgs.append(note)
        if back.exists():
            with zipfile.ZipFile(back) as z:
                ms = z.read("Metadata/model_settings.config").decode("utf-8", "replace")
                gfiles = [n for n in z.namelist() if n.endswith(".gcode")]
                shots = 0
                for i in range(1, len(plates) + 1):           # Bambu Studio's own plate pictures
                    src = f"Metadata/plate_{i}.png"
                    if src in z.namelist():
                        (out.parent / f"{out.stem}-plate{i}.png").write_bytes(z.read(src))
                        shots += 1
                if shots:
                    msgs.append(tr("c.pictures", first=f"{out.stem}-plate1.png", n=len(plates)))
            root = ET.fromstring(ms)                          # a parser: names with & or quotes come back decoded
            got = {}
            for obj in root.findall("object"):
                kv = {m.get("key"): m.get("value") for m in obj.findall("metadata") if m.get("key")}
                got[kv.get("name")] = kv
            bad = []
            for name, exp in expected.items():
                kv = got.get(name)
                if kv is None:
                    bad.append(tr("c.missing", name=name))
                    continue
                diff = [k for k, v in exp.items() if kv.get(k) != v]
                if diff:
                    bad.append(tr("c.diff", name=name, list=', '.join(f'{k}={kv.get(k)!r} (≠ {exp[k]!r})' for k in diff)))
            gplates = len(root.findall("plate"))
            if gplates != len(plates):
                bad.append(tr("c.plates", g=gplates, n=len(plates)))
            msgs += bad or [tr("c.settings_ok", n=len(expected))]
            if len(gfiles) < len(plates):
                msgs.append(tr("c.gcode", g=len(gfiles), n=len(plates)))
    return msgs


STUDIO_CONF = Path(os.environ.get("APPDATA", "")) / "BambuStudio" / "BambuStudio.conf"


def _studio_app() -> dict:
    """The "app" part of BambuStudio.conf ({} when it is missing or unreadable)."""
    try:
        txt = STUDIO_CONF.read_text(encoding="utf-8")
        app = json.loads(txt[txt.index("{"):txt.rindex("}") + 1]).get("app", {})
    except (OSError, ValueError):
        return {}
    return app if isinstance(app, dict) else {}


def studio_versions() -> tuple[str, str]:
    """(installed, newest seen online) Bambu Studio versions, from BambuStudio.conf: Bambu Studio writes both itself
    ("version", and "cloud_version" when it checks for updates), so no network is needed. '' when unknown."""
    app = _studio_app()
    return str(app.get("version") or ""), str(app.get("cloud_version") or "")


def studio_running() -> bool:
    """Is a Bambu Studio open (any bambu-studio.exe)? Toolhelp, a few ms: also asked inside _PRESTART_LOCK."""
    try:
        import bambu_studio
        return bool(bambu_studio.studio_pids())
    except (OSError, AttributeError):
        return False


def studio_single_instance() -> str:
    """Switch on Bambu Studio's "single instance" (Preferences: one Bambu Studio window), so the project the tool
    opens goes to the window that is already open, not to a second one (2026-11-21). Only while Studio is
    closed (it writes this file itself when it closes) and only when the file's own checksum is right: Bambu Studio
    keeps a "# MD5 checksum" of the text above it (with \\n line ends, without the last one) and takes a file that does
    not match for damaged. One value changes, the checksum is made new, and a copy of the old file stays next to it.
    Returns "on" (it was), "switched", or why it was left alone."""
    try:
        data = STUDIO_CONF.read_bytes()
    except OSError:
        return "no Bambu Studio settings file"
    m = re.search(rb"\r?\n# MD5 checksum ([0-9A-Fa-f]{32})(\s*)$", data)
    if not m:
        return "no checksum in the settings file"
    body = data[:m.start()]
    if hashlib.md5(body.replace(b"\r\n", b"\n")).hexdigest().upper() != m.group(1).decode().upper():
        return "the settings file's checksum does not match"
    if re.search(rb'"single_instance":\s*true', body):
        return "on"
    new, n = re.subn(rb'("single_instance":\s*)false', rb"\1true", body)
    if n != 1:
        return "single_instance not found in the settings file"
    md5 = hashlib.md5(new.replace(b"\r\n", b"\n")).hexdigest().upper().encode()
    backup = _studio_backup()
    tmp = STUDIO_CONF.with_name(STUDIO_CONF.name + ".orientr.tmp")
    try:
        if not backup.exists():
            backup.write_bytes(data)
        tmp.write_bytes(new + data[m.start():m.start(1)] + md5 + m.group(2))
        os.replace(tmp, STUDIO_CONF)
    except OSError as e:
        return f"could not write the settings file: {e}"
    return "switched"


def _studio_backup() -> Path:
    """The copy of Bambu Studio's settings this tool keeps while it has "single instance" switched on:
    BambuStudio.conf.orientr.bak, so that switch can still be undone."""
    return STUDIO_CONF.with_name(STUDIO_CONF.name + ".orientr.bak")


def restore_single_instance() -> str:
    """uninstall.cmd (--restore-studio-setting): switch Bambu Studio's "single instance" off again, but only when this
    tool switched it on (studio_single_instance keeps its backup file only then; switched on by the user: no backup,
    left alone). Only that one value changes, the rest of the file is Bambu Studio's current one, with the checksum
    made new as above; the backup is removed afterwards. Returns a code for uninstall.ps1: "restored", "untouched"
    (not switched by this tool), "already-off", "studio-open" (try again with Bambu Studio closed), or "failed: ..."."""
    backup = _studio_backup()
    if not backup.exists():
        return "untouched"
    if studio_running():                                  # it writes the file itself when it closes
        return "studio-open"
    try:
        data = STUDIO_CONF.read_bytes()
    except OSError:
        return "failed: no Bambu Studio settings file"
    m = re.search(rb"\r?\n# MD5 checksum ([0-9A-Fa-f]{32})(\s*)$", data)
    if not m:
        return "failed: no checksum in the settings file"
    body = data[:m.start()]
    if hashlib.md5(body.replace(b"\r\n", b"\n")).hexdigest().upper() != m.group(1).decode().upper():
        return "failed: the settings file's checksum does not match"
    if re.search(rb'"single_instance":\s*false', body):   # switched off meanwhile (in Bambu Studio's preferences)
        backup.unlink(missing_ok=True)
        return "already-off"
    new, n = re.subn(rb'("single_instance":\s*)true', rb"\1false", body)
    if n != 1:
        return "failed: single_instance not found in the settings file"
    md5 = hashlib.md5(new.replace(b"\r\n", b"\n")).hexdigest().upper().encode()
    tmp = STUDIO_CONF.with_name(STUDIO_CONF.name + ".orientr.tmp")
    try:
        tmp.write_bytes(new + data[m.start():m.start(1)] + md5 + m.group(2))
        os.replace(tmp, STUDIO_CONF)
        backup.unlink(missing_ok=True)
    except OSError as e:
        return f"failed: could not write the settings file: {e}"
    return "restored"


import threading as _threading                           # noqa: E402


# once per process: an old keep_hidden must see the same event, also after the option was switched off and on again
_STOP_HIDING = _threading.Event()                         # the project opens: stop hiding Studio, start nothing more


_PRESTART_CANCEL = _threading.Event()                     # this waiting start is cancelled (new one per start)


_STUDIO_MARKER: Path | None = None                        # exists: the project was handed to the prestarted Studio


_HIDDEN_PID: int | None = None                            # the hidden Studio this form started or adopted


_WAIT_THREAD = None                                       # _prestart_when_ready: waits for a quiet PC, then starts it
_CLOSING_PID: int | None = None                           # the hidden Studio cancel_prestart() is closing
_LEFT_PID: int | None = None                              # closing was given up: in use, or a question from Studio


def background_state() -> str | None:
    """What the form shows beside "Background Bambu Studio" (2026-11-23): "opening" (waiting for a quiet PC, or
    started without its main window yet), "open", "closing", "closed" (no hidden Studio of this form runs), or None
    (closing was given up because the Studio is in use: no state to show)."""
    global _CLOSING_PID, _LEFT_PID
    if os.name != "nt":
        return None
    import bambu_studio
    closing = _CLOSING_PID
    if closing is not None:
        if bambu_studio.alive(closing):
            return "closing"
        _CLOSING_PID = None
    pid = _HIDDEN_PID
    if pid is not None:
        if bambu_studio.alive(pid):
            return "open" if bambu_studio.has_main_window(pid) else "opening"
    elif _WAIT_THREAD is not None and _WAIT_THREAD.is_alive() and not _PRESTART_CANCEL.is_set():
        return "opening"
    left = _LEFT_PID
    if left is not None:
        if bambu_studio.alive(left):
            return None
        _LEFT_PID = None
    return "closed"


_PRESTART_LOCK = _threading.Lock()                        # the delayed start and Generate's opening never cross


def prestart_studio() -> bool:
    """Start Bambu Studio hidden in the background when the form opens (2026-11-21: it takes a while to
    start; not in front, not even in the taskbar, only Generate shows it), so the finished project opens at once in
    that window: Studio shows itself when it gets the project. Only when it is installed and not open yet, and when
    "single instance" is or could be switched on: otherwise the project would open in a second window. A guard
    process (bambu_studio.py) closes it again after the form when nothing was opened in it. A hidden Studio left
    behind by an earlier run is adopted: this run's guard closes it, or Generate shows it.
    Only when switched on ("Background Bambu Studio" in the form, saved per user, off after install)."""
    global _PRESTART_CANCEL, _WAIT_THREAD
    if os.name != "nt" or not Path(BAMBU_EXE).exists() or _STOP_HIDING.is_set():
        return False
    import threading
    import bambu_studio                                   # next to this file
    _PRESTART_CANCEL.set()                                # a start that still waits from before: this one replaces it
    _PRESTART_CANCEL = threading.Event()
    left = bambu_studio.hidden_studio()
    if left:                                              # 2026-11-21: one had to be ended in Task
        if not _guard_studio(left):                       # Manager; never again left behind invisible
            bambu_studio.show_minimized(left)             # no guard: visible in the taskbar instead
            return True
        try:                                              # and it stays hidden while this form runs
            threading.Thread(target=bambu_studio.keep_hidden, args=(left, None, _STOP_HIDING), daemon=True).start()
        except RuntimeError:
            pass
        return True
    if studio_running():
        return False
    if studio_single_instance() not in ("on", "switched"):
        return False
    try:                                                  # the form opens at once; Studio follows when SOMA is ready
        _WAIT_THREAD = threading.Thread(target=_prestart_when_ready, args=(_PRESTART_CANCEL,), daemon=True)
        _WAIT_THREAD.start()
    except RuntimeError:
        _WAIT_THREAD = None
        return False
    return True


def cancel_prestart() -> None:
    """"Background Bambu Studio" switched off in the form: a start that still waits does not happen, and the hidden
    Studio of this form closes now (2026-11-23; it stayed until the form ended). One in use (visible) or with the
    project handed to it stays."""
    global _HIDDEN_PID, _CLOSING_PID
    _PRESTART_CANCEL.set()
    with _PRESTART_LOCK:                                  # not while the delayed start launches one
        pid, _HIDDEN_PID = _HIDDEN_PID, None
        if pid is None or _STOP_HIDING.is_set() or os.name != "nt":
            return
        import threading
        import bambu_studio
        _CLOSING_PID = pid                                # background_state(): "closing" until it has ended

        def close() -> None:
            global _CLOSING_PID, _LEFT_PID
            bambu_studio.close_hidden(pid, _STOP_HIDING)
            if _CLOSING_PID == pid and bambu_studio.alive(pid):   # left alone (in use, the project, a question
                _CLOSING_PID, _LEFT_PID = None, pid               # from Studio): not "closing" for ever
        try:
            threading.Thread(target=close, daemon=True).start()
        except RuntimeError:                              # no thread: the guard closes it after the form
            _CLOSING_PID = None


def _prestart_when_ready(cancel) -> None:
    """Start Studio hidden once SOMA has started and the PC is quiet (2026-11-21: not at the same time as
    SOMA, which may also run commands when it starts). Not when Generate came first (_STOP_HIDING) or the option was
    switched off (cancel): then Studio opens the normal way. The lock keeps this start and Generate's opening from
    crossing."""
    import threading
    import bambu_studio
    both = threading.Event()                              # wait_until_ready watches one event: either of the two

    def relay() -> None:
        while not both.is_set():
            if cancel.wait(0.5) or _STOP_HIDING.is_set():
                both.set()
    threading.Thread(target=relay, daemon=True).start()
    ready = bambu_studio.wait_until_ready(both)
    both.set()
    if not ready:
        return
    with _PRESTART_LOCK:
        if _STOP_HIDING.is_set() or cancel.is_set() or studio_running():
            return
        _launch_hidden_studio(bambu_studio, threading)


def start_studio(*args: str, hidden: bool = True) -> int:
    """Start Bambu Studio (with `args`) and give its process id. Not as a child of this process: Bambu Studio attaches
    to its parent's console and, once it has loaded, writes debug lines into it, so "use_count = 4" appeared in the
    form (2026-11-21, caught 15 s after Studio started). A short-lived helper with an invisible console
    of its own starts it and ends at once. `hidden` asks for a hidden window (Studio ignores it: keep_hidden)."""
    code = ("import subprocess,sys;si=subprocess.STARTUPINFO();si.dwFlags|=1;"
            f"si.wShowWindow={0 if hidden else 1};"
            "p=subprocess.Popen(sys.argv[1:],startupinfo=si,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
            "stderr=subprocess.DEVNULL,close_fds=True,creationflags=0x8|0x200);print(p.pid)")   # DETACHED, NEW_GROUP
    try:
        r = subprocess.run([sys.executable, "-I", "-c", code, BAMBU_EXE, *args], capture_output=True, text=True,
                           timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        return int(r.stdout.strip())
    except (subprocess.SubprocessError, ValueError) as e:
        raise OSError(f"could not start Bambu Studio: {e}") from None


def _launch_hidden_studio(bambu_studio, threading) -> None:
    focus = bambu_studio.user32().GetForegroundWindow()   # the window the user is in now: it keeps the focus
    try:
        pid = start_studio()
    except OSError:
        return
    if not _guard_studio(pid):                            # no guard: not hidden either, so it is never left invisible
        return
    try:
        threading.Thread(target=bambu_studio.keep_hidden, args=(pid, focus, _STOP_HIDING), daemon=True).start()
    except RuntimeError:                                  # no thread: Studio just shows itself, the form goes on
        pass


def _guard_studio(studio_pid: int) -> bool:
    """The guard that closes the hidden Studio after this process (the form) ends, however it ends."""
    global _STUDIO_MARKER, _HIDDEN_PID
    import bambu_studio
    _HIDDEN_PID = studio_pid                              # cancel_prestart() closes it when the option goes off
    bambu_studio.set_owner(studio_pid, os.getpid())       # another Orientr leaves it alone while this form runs
    _STUDIO_MARKER = Path(tempfile.gettempdir()) / f"bambu-studio-{studio_pid}-{uuid.uuid4().hex[:8]}.open"
    try:
        # CREATE_NO_WINDOW, not DETACHED_PROCESS: the model's python.exe is a launcher that starts the real Python as
        # a console program; detached it has no console, so Windows opened a terminal window for it, and closing that
        # window ended the guard (2026-11-21). Now it gets an invisible console of its own, which also
        # outlives the form's window.
        subprocess.Popen([sys.executable, "-I", str(TOOL_DIR / "bambu_studio.py"), str(os.getpid()), str(studio_pid),
                          str(_STUDIO_MARKER)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        return True
    except OSError:
        _STUDIO_MARKER = None
        return False


def stop_hiding_studio() -> None:
    """The project is handed to Studio: it may show itself now, the guard leaves it open, and a start that still
    waited for SOMA (_prestart_when_ready) does not happen."""
    with _PRESTART_LOCK:
        if _STOP_HIDING is not None:
            _STOP_HIDING.set()
        if _STUDIO_MARKER is not None:
            try:
                _STUDIO_MARKER.touch()
            except OSError:
                pass


def undo_stop_hiding_studio() -> None:
    """Opening the project failed: the guard closes the hidden Studio again after the form."""
    if _STUDIO_MARKER is not None:
        try:
            _STUDIO_MARKER.unlink(missing_ok=True)
        except OSError:
            pass


REGION_CURRENCY = {"Europe": "€", "North America": "$", "China": "¥"}


def money(amount: float, region: str | None = None) -> str:
    """The filament cost. Bambu Studio keeps the price per kg without a currency: the user typed it in their own. So
    the number as it is, with the sign of the region chosen in Bambu Studio (Europe €, North America $, China ¥; other
    regions just the number). 2026-11-22: no second currency at a fixed rate that gets out of date."""
    region = str(_studio_app().get("region") or "") if region is None else region
    sign = REGION_CURRENCY.get(region)
    return f"{sign} {amount:.2f}" if sign else f"{amount:.2f}"


VERIFIED_FILE = APP_DIR / "verified.json"


def verified_version() -> str:
    """The Bambu Studio version the last passed self-test ran against ('' when never)."""
    try:
        return str(json.loads(VERIFIED_FILE.read_text(encoding="utf-8")).get("studio") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def template_age(t: Template) -> list[str]:
    """Remind to save the template again when Bambu Studio was updated after it was saved."""
    installed = studio_versions()[0]
    if not installed:
        return []
    saved = t.app.split("-", 1)[-1]
    if _version(installed) and _version(saved) and _version(installed)[:3] > _version(saved)[:3]:
        return [tr("ta.old", saved=saved, inst=installed, file=t.path.name)]
    return []


# --- main -----------------------------------------------------------------------------------------------------------
USER_TEMPLATES = APP_DIR / "templates"
"""Templates the user saved or imported (2026-11-22): apart from the tool's own, so they survive a new version unpacked
over the old one and never go into a release. A name found here wins over the tool's template of the same name."""


def template_path(name: str) -> Path:
    """Where the template of this name is: the user's own first, else the tool's."""
    own = USER_TEMPLATES / f"{name}.3mf"
    return own if own.exists() else TOOL_DIR / "templates" / f"{name}.3mf"


def resolve_template(ws: Path, spec: str | None) -> Path:
    """A template by name (the user's templates folder, else the tool's), by path (relative to the model or absolute),
    or the default: inputs/bambu_template.3mf of the model if present, else templates/default.3mf."""
    if not spec:
        own = ws / "inputs" / "bambu_template.3mf"
        return own if own.exists() else DEFAULT_TEMPLATE
    if not re.search(r"[\\/]", spec) and not spec.lower().endswith(".3mf"):
        return template_path(spec)
    p = Path(spec)
    return p if p.is_absolute() else ws / p


def printer_models() -> list[str]:
    """Every Bambu Lab printer Bambu Studio knows ('Bambu Lab H2D', ...), from its vendor file; [] if not found."""
    for f in BAMBU_VENDOR:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names = [str(m.get("name", "")) for m in data.get("machine_model_list") or [] if isinstance(m, dict)]
        names = [n for n in names if n.startswith("Bambu Lab ")]
        if names:
            return list(dict.fromkeys(names))             # vendor order, no duplicates
    return []


# --- filaments ------------------------------------------------------------------------------------------------------
# The Bambu Studio window loads a filament by its preset name (tested 2026-11-17: only the name changed to PETG, the
# window showed PETG with 250/70 C). So a filament needs no template of its own: the tool sets the name, plus the
# preset's values for the command-line check and its own rules (warping, brim), which read the file directly.
POPULAR_FILAMENTS = ("PLA Basic", "PETG Basic", "PLA Matte", "PETG HF", "ABS", "ASA", "PLA Tough+", "TPU 95A HF")


FILAMENT_META = {"name", "inherits", "from", "setting_id", "instantiation", "type", "filament_id", "version",
                 "compatible_printers", "compatible_printers_condition", "compatible_prints",
                 "compatible_prints_condition", "filament_settings_id", "filament_colour", "default_filament_colour",
                 "is_custom_defined", "description"}


_PROFILES: dict[str, dict[str, dict]] = {}


# Reading ~2500 preset files took ~115 s on this PC (each open ~44 ms, likely the virus scanner), so the presets are
# kept in one cache file per folder, valid as long as no file in the folder was added, removed or changed.
PROFILE_CACHE = APP_DIR / "profile-cache"


def _json_files(folder: Path) -> list[tuple[str, int, int]]:
    """(relative path, mtime_ns, size) of every .json below folder, from directory listings only (no file opened)."""
    out, todo = [], [folder]
    while todo:
        d = todo.pop()
        with os.scandir(d) as it:
            for e in it:
                if e.is_dir():
                    todo.append(Path(e.path))
                elif e.name.lower().endswith(".json"):
                    st = e.stat()
                    out.append((Path(e.path).relative_to(folder).as_posix(), st.st_mtime_ns, st.st_size))
    return sorted(out)


def _read_presets(folder: Path) -> tuple[dict[str, dict], bool]:
    """(presets by name, complete): complete is False when a file could not be opened (locked during an update),
    so that result must not be cached; a file that is not valid JSON stays skipped until it changes."""
    found: dict[str, dict] = {}
    complete = True
    for f in folder.rglob("*.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except OSError:
            complete = False
            continue
        except ValueError:
            continue
        if isinstance(p, dict) and isinstance(p.get("name"), str):
            found[p["name"]] = p
    return found, complete


def _cached_presets(folder: Path) -> dict[str, dict]:
    """_read_presets(folder) through the cache file; reads the folder again when any file in it changed."""
    import hashlib
    try:
        listing = _json_files(folder)
    except OSError:
        return _read_presets(folder)[0]
    key =hashlib.sha256(json.dumps([str(folder.resolve()), listing]).encode()).hexdigest()
    cache = PROFILE_CACHE / f"{hashlib.sha256(str(folder.resolve()).lower().encode()).hexdigest()[:16]}.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key and isinstance(data.get("presets"), dict):
            return data["presets"]
    except (OSError, ValueError):
        pass
    found, complete = _read_presets(folder)
    if not complete:
        return found                                      # try again next run instead of caching a gap
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        part = cache.with_suffix(f".{os.getpid()}.tmp")
        part.write_text(json.dumps({"folder": str(folder), "key": key, "presets": found}), encoding="utf-8")
        os.replace(part, cache)
    except OSError:
        pass                                              # no cache: slower next time, still correct
    return found


def profile_index(kind: str) -> dict[str, dict]:
    """Bambu Studio's system presets of one kind ('filament', 'process') by name, as stored; {} when not found."""
    if kind not in _PROFILES:
        found: dict[str, dict] = {}
        for vendor in BAMBU_VENDOR:                       # the online-updated copy first: it is complete
            folder = vendor.parent / "BBL" / kind
            if not folder.is_dir():
                continue
            found = _cached_presets(folder)
            if found:
                break
        _PROFILES[kind] = found
    return _PROFILES[kind]


PROFILE_KINDS = ("machine", "filament", "process")       # what the form needs before it can show its lists


def _folder_cached(folder: Path) -> str:
    """'full' / 'empty' when the cache of this folder is up to date (with presets / without), else 'stale'. Reads only
    the directory listing and the start and end of the cache file."""
    import hashlib
    try:
        key = hashlib.sha256(json.dumps([str(folder.resolve()), _json_files(folder)]).encode()).hexdigest()
        cache = PROFILE_CACHE / f"{hashlib.sha256(str(folder.resolve()).lower().encode()).hexdigest()[:16]}.json"
        with open(cache, "rb") as f:
            head = f.read(1000).decode("utf-8", "replace")   # the key is written right after the folder name
            f.seek(max(0, cache.stat().st_size - 20))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return "stale"
    if f'"key": "{key}"' not in head:
        return "stale"
    return "empty" if tail.replace(" ", "").endswith('"presets":{}}') else "full"


def profiles_cached() -> bool:
    """Are Bambu Studio's profiles in the cache and up to date (directory listings and the ends of the cache files
    only, well under a second)? False after installing and after a Bambu Studio update: reading them then takes about
    2 minutes (measured 2026-11-22: 103 s for 2700 presets), which the callers announce. Follows profile_index()'s
    choice exactly: per kind the first folder with presets, an empty one is passed over."""
    for kind in PROFILE_KINDS:
        for vendor in BAMBU_VENDOR:
            folder = vendor.parent / "BBL" / kind
            if not folder.is_dir():
                continue
            state = _folder_cached(folder)
            if state == "stale":
                return False                              # this folder would be read now: slow
            if state == "full":
                break                                     # profile_index() stops here too
    return True


def announce_profiles(write=print) -> bool:
    """When the profiles still have to be read (see profiles_cached), say so before the long wait. True if it did."""
    if profiles_cached():
        return False
    write(tr("p.reading"))
    return True


def warm_profiles() -> int:
    """--warm-profiles (install.cmd runs it): read Bambu Studio's profiles into the cache now, so the form opens at
    once the first time. Says it takes about 2 minutes only when they really have to be read (2026-11-22: install.cmd
    said so also when they were in the cache already and it took 0 s); already in the cache: nothing to say."""
    if not Path(BAMBU_EXE).exists():
        print(tr("s.missing", path=BAMBU_EXE))
        return 1
    if not announce_profiles(lambda text: print(f"\n[..] {text}", flush=True)):
        return 0
    t0 = time.time()
    counts = [len(profile_index(kind)) for kind in PROFILE_KINDS]
    print(tr("p.done", n=sum(counts), s=int(time.time() - t0)))
    return 0 if all(counts) else 1


def flat_profile(kind: str, name: str) -> dict:
    """A preset with everything it inherits filled in."""
    idx, chain, seen = profile_index(kind), [], set()
    while name and name in idx and name not in seen:
        seen.add(name)
        chain.append(idx[name])
        name = idx[name].get("inherits", "")
    out: dict = {}
    for p in reversed(chain):
        out.update(p)
    return out


def profiles_for(kind: str, printer_preset: str) -> dict[str, str]:
    """Short name -> preset name of every system preset of this kind made for the printer preset."""
    out = {}
    for n, p in sorted(profile_index(kind).items()):
        if str(p.get("instantiation")) == "true" and printer_preset in (p.get("compatible_printers") or []) \
                and "'" not in n:                         # names go into single-quoted arguments
            out.setdefault(filament_short(n), n)
    return out


def flat_filament(name: str) -> dict:
    return flat_profile("filament", name)


def filament_short(name: str) -> str:
    """'Bambu PETG Basic @BBL H2D 0.4 nozzle' -> 'PETG Basic'; 'Generic PETG @BBL H2D' -> 'Generic PETG'."""
    return re.sub(r"^Bambu\s+", "", re.sub(r"\s*@.*$", "", str(name))).strip()


def filaments_for(printer_preset: str) -> dict[str, str]:
    """Short name -> preset name of every system filament made for this printer preset ('Bambu Lab H2D 0.4 nozzle')."""
    return profiles_for("filament", printer_preset)


def processes_for(printer_preset: str) -> dict[str, str]:
    """'0.16mm Standard' -> '0.16mm Standard @BBL H2D', every system process preset for this printer preset."""
    return profiles_for("process", printer_preset)


def match_process(name: str, printer_preset: str) -> str:
    """'0.16mm standard', the full preset name, or a part that fits one profile -> the process preset name."""
    avail = processes_for(printer_preset)
    if not avail:
        raise ToolError(tr("e.no_processes", printer=printer_preset))
    want = filament_short(re.sub(r"\s+", " ", name.strip())).lower()
    exact = [s for s in avail if s.lower() == want]
    if exact:
        return avail[exact[0]]
    part = sorted(s for s in avail if want and want in s.lower())
    if len(part) == 1:
        return avail[part[0]]
    raise ToolError(tr("e.process_near" if part else "e.process_list", name=name, printer=printer_preset,
                       names=", ".join(part or sorted(avail))))


def set_process(t: Template, preset: str) -> None:
    """Make a system process preset the project's process: its name (what the window loads) and its values (what the
    command-line check and the rules read). Walls/infill chosen in bambu.json are applied on top when writing."""
    p, ps, new = flat_profile("process", preset), t.settings, {}
    for k, v in p.items():
        cur = ps.get(k)
        if k in FILAMENT_META or k in ("print_settings_id",) or cur is None:
            continue
        if isinstance(cur, str) and isinstance(v, str):
            new[k] = v
        elif isinstance(cur, list) and isinstance(v, list) and len(cur) == len(v):
            new[k] = [str(x) for x in v]
    new["print_settings_id"] = preset
    # the project keeps the process's printers apart (print_compatible_printers; the preset calls it
    # compatible_printers): left as the template's, the command line refused every other nozzle size ("The selected
    # printer is not compatible with the process preset in the 3mf", code -17, found 2026-11-23)
    if isinstance(ps.get("print_compatible_printers"), list) and p.get("compatible_printers"):
        new["print_compatible_printers"] = [str(x) for x in p["compatible_printers"]]
    ps.update(new)
    t.process_swap = new
    t.slope = float(ps.get("support_threshold_angle", 30) or 30)
    t.first_layer = float(ps.get("initial_layer_print_height", 0.2) or 0.2)
    # the process may move, resize or switch the prime tower
    t.tower, t.tower_xy = _place_tower(ps, t.filaments, t.nozzle_boxes, t.bed_x)


def match_filament(name: str, printer_preset: str) -> str:
    """'petg basic', 'Bambu PETG Basic' or the full preset name -> the preset name for this printer (no guessing:
    an exact short name, or a part of a name that fits only one)."""
    avail = filaments_for(printer_preset)
    if not avail:
        raise ToolError(tr("e.no_filaments", printer=printer_preset))
    want = filament_short(re.sub(r"\s+", " ", name.strip())).lower()
    exact = [s for s in avail if s.lower() == want]
    if exact:
        return avail[exact[0]]
    part = sorted(s for s in avail if want and want in s.lower())
    if len(part) == 1:
        return avail[part[0]]
    examples = ", ".join(part[:10]) if part else ", ".join(p for p in POPULAR_FILAMENTS if p in avail)
    raise ToolError(tr("e.filament", name=name, printer=printer_preset, examples=examples))


def set_filament(t: Template, preset: str) -> None:
    """Put a system filament preset in filament slot 1 of the template: its name (what the window loads) and its
    values (what the command-line check and the rules read). Per-filament lists hold one value per extruder
    variant; a value that does not fit the template's layout is left out (the window fills it in by name)."""
    p, ps, n = flat_filament(preset), t.settings, max(t.filaments, 1)
    new = {}
    for k, v in p.items():
        cur = ps.get(k)
        if k in FILAMENT_META or not isinstance(cur, list) or not cur or len(cur) % n:
            continue
        m = len(cur) // n                                 # values per filament in this project
        vals = [str(x) for x in (v if isinstance(v, list) else [v])]
        if len(vals) == 1 and m > 1:
            vals = vals * m
        if len(vals) == m:
            new[k] = vals + [str(x) for x in cur[m:]]
    new["filament_settings_id"] = [preset] + list(ps.get("filament_settings_id") or [""])[1:]
    if isinstance(ps.get("filament_ids"), list) and ps["filament_ids"] and p.get("filament_id"):
        new["filament_ids"] = [str(p["filament_id"])] + ps["filament_ids"][1:]
    ps.update(new)
    t.filament_swap = new
    t.materials = [str(x).upper() for x in ps.get("filament_type", [])]
    t.warps = _warping(ps, t.filaments)


def template_printer(t: Template) -> str:
    """The printer model of a template ('Bambu Lab H2D'), also for projects without the printer_model key."""
    model = str(t.settings.get("printer_model") or "")
    return model or re.sub(r"\s+[\d.]+ nozzle$", "", str(t.settings.get("printer_settings_id") or ""))


def nozzle_sizes(model: str) -> list[str]:
    """Nozzle diameters ('0.2', '0.4', ...) Bambu Studio has a system printer preset for on this printer model, so
    only sizes that fit the printer are offered; [] when the presets are not found."""
    pat = re.compile(rf"^{re.escape(model)} (\d+(?:\.\d+)?) nozzle$")
    found = {f"{float(m.group(1)):g}" for n, p in profile_index("machine").items()
             if str(p.get("instantiation")) == "true" and (m := pat.match(n))}
    return sorted(found, key=float)


def template_nozzle(t: Template) -> str:
    """The nozzle diameter of a template ('0.4')."""
    ps = t.settings
    raw = ps.get("printer_variant") or (ps.get("nozzle_diameter") or [""])[0]
    try:
        return f"{float(raw):g}"
    except (TypeError, ValueError):
        return str(raw)


def nozzle_defaults(model: str, size: str) -> tuple[str, str]:
    """(filament, process) short names the printer preset of this nozzle size starts with."""
    mach = flat_profile("machine", f"{model} {size} nozzle")
    fil = (mach.get("default_filament_profile") or [""])[0]
    return filament_short(fil), filament_short(str(mach.get("default_print_profile") or ""))


PRINTER_META = FILAMENT_META | {"printer_settings_id", "printer_model", "default_filament_profile",
                                "default_print_profile", "upward_compatible_machine"}


def set_nozzle_size(t: Template, size: str) -> None:
    """Make the printer preset of another nozzle size the project's printer: its name (what the window loads) and its
    values (nozzle diameter, retraction, layer height range). Only sizes Bambu Studio has for this printer fit."""
    model, own = template_printer(t), template_nozzle(t)
    fits = nozzle_sizes(model)
    if size not in fits and size != own:
        raise ToolError(tr("e.nozzle_size", size=size, printer=model, sizes=", ".join(fits) or own))
    if size == own:
        return
    preset = f"{model} {size} nozzle"
    ps, new = t.settings, {}
    for k, v in flat_profile("machine", preset).items():
        cur = ps.get(k)
        # G-code is not in the inheritance chain (it ends in fdm_machine_common's generic one; the window takes it
        # from separate "template" presets): the template's own G-code of this printer stays (review 2026-11-22)
        if k in PRINTER_META or cur is None or k.endswith("gcode"):
            continue
        if isinstance(cur, str) and isinstance(v, str):
            # a point: the preset writes "0.3x0.5", a project saved by the window "0.3,0.5" (best_object_pos,
            # default_wipe_tower_pos)
            if re.fullmatch(r"-?[\d.]+,-?[\d.]+", cur) and re.fullmatch(r"-?[\d.]+x-?[\d.]+", v):
                v = v.replace("x", ",")
            new[k] = v
        elif isinstance(cur, list) and isinstance(v, list) and len(cur) == len(v):
            new[k] = [str(x) for x in v]
    new["printer_settings_id"] = preset
    new["printer_variant"] = size
    # per extruder, not in the printer preset (the window works it out): left at the template's size, the command
    # line failed every slice with another nozzle size on the H2D ("Failed slicing the model", code -100, 2026-11-23)
    if isinstance(ps.get("extruder_nozzle_diameter"), list):
        new["extruder_nozzle_diameter"] = [size] * len(ps["extruder_nozzle_diameter"])
    ps.update(new)
    t.printer_swap = new


def _name_key(s: str) -> str:
    """'Bambu Lab X1 Carbon', 'x1carbon', 'X1-Carbon' -> 'x1carbon': the same printer however it is typed."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^\s*bambu\s*lab\s*", "", str(s), flags=re.I).lower())


def match_printer(name: str, models: list[str]) -> str:
    """'h2d pro', 'H2DPro' or 'Bambu Lab H2D Pro' -> 'Bambu Lab H2D Pro' (the whole name, spaces and case free;
    no guessing from a part of it)."""
    want = _name_key(name)
    for m in models:
        if _name_key(m) == want:
            return m
    raise ToolError(tr("e.printer", name=name, names=', '.join(m[len('Bambu Lab '):] for m in models) or '-'))


RECENT_PRINTERS = PROFILE_CACHE.parent / "recent-printers.json"   # for every model: printers sent to lately


def recent_printers() -> list[str]:
    """Short names of the printers projects were made for, most recent first ('H2D', 'X1 Carbon', ...)."""
    try:
        data = json.loads(RECENT_PRINTERS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(x) for x in data if isinstance(x, str)] if isinstance(data, list) else []


def remember_printer(model: str) -> None:
    """Put this printer ('Bambu Lab H2D' or 'H2D') first in the recent list; a write error only loses the hint."""
    short = re.sub(r"^\s*Bambu Lab\s+", "", model).strip()
    if not short:
        return
    try:
        RECENT_PRINTERS.parent.mkdir(parents=True, exist_ok=True)
        RECENT_PRINTERS.write_text(json.dumps([short] + [p for p in recent_printers() if p != short][:7]),
                                   encoding="utf-8")
    except OSError:
        pass


def no_template_help(model: str, other_filament: bool = False) -> str:
    """How to save a template for a printer (filament and process need none: they are swapped by name)."""
    USER_TEMPLATES.mkdir(parents=True, exist_ok=True)     # Bambu Studio's Save As cannot make the folder itself
    return tr("e.no_template", printer=model, folder=USER_TEMPLATES)


def apply_print_settings(t: Template, pr: dict) -> None:
    """Project-wide choices from bambu.json "print" (written by the menu), checked against the printer."""
    size = pr.get("nozzle_size")
    if size not in (None, ""):                           # first: filament and process lists belong to the size
        diameter = strict_number(size, '"nozzle_size"')
        set_nozzle_size(t, f"{diameter:g}")
    pp = str(t.settings.get("printer_settings_id") or "")
    if t.printer_swap:                                   # the template's own filament/process were made for its nozzle
        model = template_printer(t)
        d_fil, d_proc = nozzle_defaults(model, template_nozzle(t))
        proc_name, fil_name = pr.get("process") or t.settings.get("print_settings_id"), \
            pr.get("material") or (t.settings.get("filament_settings_id") or [""])[0]
        pr = dict(pr)
        for key, name, match, fallback in (("process", proc_name, match_process, d_proc),
                                           ("material", fil_name, match_filament, d_fil)):
            try:
                match(str(name), pp)
                pr[key] = str(name)
            except ToolError:
                pr[key] = fallback
    if pr.get("process") not in (None, ""):              # a system process preset, by name (loaded so by the window)
        preset = match_process(str(pr["process"]), pp)
        set_process(t, preset)                            # also for the template's own: back to the system values
        t.process = filament_short(preset)
    # the filament, by name: no template of its own needed. Not with a colour template (2026-11-22): its filaments were
    # chosen in Bambu Studio on purpose, and swapping slot 1 put ASA next to PLA on one plate
    if pr.get("material") not in (None, "") and t.filaments == 1:
        preset = match_filament(str(pr["material"]), pp)
        set_filament(t, preset)                           # also for the template's own: back to the system values
        t.material = filament_short(preset)
    if pr.get("layer_height") not in (None, ""):
        lh = strict_number(pr["layer_height"], '"layer_height"')
        lo = min(_per_filament(t.settings, "min_layer_height", 2) or [0.04])
        hi = max(_per_filament(t.settings, "max_layer_height", 2) or [1.0])
        if not (lo - 1e-9 <= lh <= hi + 1e-9):
            raise ToolError(tr("e.layer", lh=f"{lh:g}", lo=f"{lo:g}", hi=f"{hi:g}"))
        t.overrides["layer_height"] = f"{lh:g}"
    if pr.get("walls") not in (None, ""):
        w = strict_number(pr["walls"], '"walls"')
        if w != int(w) or not 1 <= w <= 20:
            raise ToolError(f'"walls" must be a whole number 1..20, not {pr["walls"]!r}')
        t.overrides["wall_loops"] = str(int(w))
    if pr.get("infill") not in (None, ""):
        f = strict_number(pr["infill"], '"infill"', percent=True)
        if not 0 <= f <= 100:
            raise ToolError(f'"infill" must be 0..100 %, not {pr["infill"]!r}')
        t.overrides["sparse_infill_density"] = f"{f:g}%"
    for key in ("support", "brim"):
        setattr(t, f"{key}_mode", str(pr.get(key) or "auto"))
    t.nozzle_mode = str(pr.get("nozzle") or "auto")       # only used by printers with 2+ nozzles
    t.colour_mode = str(pr.get("colours") or "template")  # model: the parts' colours on the filaments (make_project)
    if pr.get("duplicates") not in (None, ""):
        t.duplicates = whole_number(pr["duplicates"], '"duplicates"', 1, MAX_COPIES)
    if pr.get("max_plates") not in (None, ""):
        t.max_plates = whole_number(pr["max_plates"], '"max_plates"', 0, MAX_PLATES)


_STUDIO_CHOICE: dict | None = None


def studio_choice() -> dict:
    """What is selected in Bambu Studio right now (its settings file, BambuStudio.conf "presets"): {"printer":
    'Bambu Lab P1S', "preset": 'Bambu Lab P1S 0.4 nozzle', "nozzle_size": '0.4', "material": 'PLA Basic',
    "process": '0.20mm Standard'} as far as found; {} when the file cannot be read. Read once per run."""
    global _STUDIO_CHOICE
    if _STUDIO_CHOICE is None:
        _STUDIO_CHOICE = {}
        try:
            text = STUDIO_CONF.read_text(encoding="utf-8")
            data = json.loads(re.sub(r"\r?\n# MD5 checksum[^\n]*\s*$", "", text))
            pre = data.get("presets") or {}
            m = re.fullmatch(r"(Bambu Lab .+?) (\d+(?:\.\d+)?) nozzle", str(pre.get("machine") or ""))
            if m:
                fil = pre.get("filaments", pre.get("filament"))
                fil = (fil[0] if fil else "") if isinstance(fil, list) else str(fil or "")
                _STUDIO_CHOICE = {"printer": m.group(1), "preset": m.group(0), "nozzle_size": f"{float(m.group(2)):g}",
                                  "material": filament_short(fil), "process": filament_short(str(pre.get("print") or ""))}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    return _STUDIO_CHOICE


def slice_stats(out: Path, td: Path, tick=None) -> dict:
    """Slice every plate with Bambu Studio's command line and read its estimate per plate from the sliced project
    (Metadata/slice_info.config: prediction in s, used_g and used_m per filament) and its warnings (result.json)."""
    if not Path(BAMBU_EXE).exists():
        raise ToolError(tr("c.skipped", path=BAMBU_EXE))
    td.mkdir(parents=True, exist_ok=True)
    cmd = [BAMBU_EXE, "--slice", "0", "--outputdir", str(td), "--export-3mf", "sliced.3mf", str(out)]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import bambu_studio
    bambu_studio.OWN_CLI.add(proc.pid)                    # not the user starting Studio: keep_hidden goes on
    try:
        while proc.poll() is None:
            if tick and tick(time.time() - t0):
                raise PreviewStopped
            time.sleep(0.2)
    finally:
        if proc.poll() is None:                           # stopped, Ctrl+C or an error: do not leave it running
            proc.kill()
            proc.wait()
    res = td / "result.json"
    info = json.loads(res.read_text(encoding="utf-8", errors="replace")) if res.exists() else {}
    code = info.get("return_code", proc.returncode)
    if code != 0:
        raise ToolError(tr("c.failed", err=info.get("error_string", ""), code=code))
    warn = {int(sp.get("id", i + 1)): " ".join(str(sp.get("warning_message") or "").split())
            for i, sp in enumerate(info.get("sliced_plates") or [])}
    back = td / "sliced.3mf"
    if not back.exists():
        raise ToolError(tr("c.failed", err="no sliced project", code=code))
    with zipfile.ZipFile(back) as z:
        z_ver = z.read("Metadata/slice_info.config")
        root = ET.fromstring(z_ver)
        try:                                              # price per kg of each filament, as set in its profile
            prices = [float(x or 0) for x in json.loads(z.read("Metadata/project_settings.config")).get("filament_cost", [])]
        except (KeyError, ValueError):
            prices = []
        standard: dict[int, list[str]] = {}               # warnings Studio always gives for this filament: shown
        for n, m, std in studio_gui_warnings(z):          # once and short by Analyze (2026-11-22)
            if std:
                standard.setdefault(n, []).append(m)
            else:
                warn[n] = " | ".join(x for x in (warn.get(n), m) if x)
    plates = []
    for pl in root.findall("plate"):
        kv = {m.get("key"): m.get("value") for m in pl.findall("metadata")}
        n = int(kv.get("index") or len(plates) + 1)
        fils = [{"id": int(f.get("id") or 0), "type": f.get("type") or "", "color": f.get("color") or "",
                 "g": float(f.get("used_g") or 0), "m": float(f.get("used_m") or 0)} for f in pl.findall("filament")]
        for f in fils:
            f["cost"] = f["g"] / 1000 * (prices[f["id"] - 1] if 0 < f["id"] <= len(prices) else 0)
        plates.append({"n": n, "s": float(kv.get("prediction") or 0), "g": sum(f["g"] for f in fils),
                       "m": sum(f["m"] for f in fils), "cost": sum(f["cost"] for f in fils),
                       "filaments": fils, "warning": warn.get(n, ""), "standard": standard.get(n, [])})
    fil_total: dict[int, dict] = {}
    for p in plates:
        for f in p["filaments"]:
            tot = fil_total.setdefault(f["id"], {**f, "g": 0.0, "m": 0.0, "cost": 0.0})
            tot["g"] += f["g"]
            tot["m"] += f["m"]
            tot["cost"] += f["cost"]
    return {"plates": plates, "s": sum(p["s"] for p in plates), "g": sum(p["g"] for p in plates),
            "m": sum(p["m"] for p in plates), "cost": sum(p["cost"] for p in plates),
            "filaments": [fil_total[k] for k in sorted(fil_total)],
            "slice_s": time.time() - t0, "rules_note": studio_rules_note(z_ver)}
