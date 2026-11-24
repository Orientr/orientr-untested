# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""Orientr (orientr.py): turn the printable parts of a SOMA model into a Bambu Studio project with automatic print settings.

Run it in a SOMA model folder after `soma build`:

    orientr                 the form: every choice on one screen
    orientr --saved         again, with the saved choices
    orientr --help          all options

What it does, per printable part (role "part", no references or hardware):
  1. orientation: a hint from `bambu.json`, otherwise the orientation with the least support, most bed contact
     and lowest height (the modelled orientation wins a near tie);
  2. support: on (tree, auto) only where real overhang regions need it, small spots and short bridges ignored;
  3. brim: for tall, narrow parts and small bed contact, width by how critical it is; with a warping filament
     (ASA, ABS, PC, ...) also for long parts and for small ones (< 150 mm2 contact or < 30 mm long);
  4. walls/infill: stronger for tiny parts and for parts marked snap/spring/load in `bambu.json`;
  5. plates: all parts packed together onto the bed of the template's printer (part colour ignored).
It writes `output/bambu/<model>.3mf` (open it in Bambu Studio, check, slice, send) and a report with the reason for
every setting. Printer, filament and process come from a project saved in Bambu Studio (the template).

Hints in `bambu.json` (optional, in the model folder), all keys optional:
    {
      "template": "inputs/bambu_template.3mf",
      "parts": {
        "Handle":    {"up": "+x"},                         # model axis that points up on the bed
        "Hook":      {"support": true, "function": "load"},
        "Pin":       {"brim": 0, "walls": 5, "infill": "50%"},
        "Label":     {"merge_into": "Plate", "filament": 2},
        "Knob":      {"copies": 4},                       # 4 times (times "duplicates" in "print")
        "Cover":     {"skip": true, "settings": {"top_shell_layers": "6"}}
      }
    }
Only numpy, scipy, the standard library and, to mesh the parts from output/model.step, cadquery and soma are used
(all present in a SOMA environment).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np

def _take_env_file(argv: list[str]) -> None:
    """--env-file (the form in the Windows Terminal window _own_window() opened): take over the variables it sent,
    and delete the file. Here, before BAMBU_EXE and the other values read from the environment once."""
    if "--env-file" not in argv[:-1]:
        return
    path = Path(argv[argv.index("--env-file") + 1])
    try:
        os.environ.update({k: str(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()})
    except (OSError, ValueError, AttributeError):
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:                                       # the starter deletes it too
        pass


if __name__ == "__main__":
    _take_env_file(sys.argv)
TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:                         # python -I leaves the script's folder out: the
    sys.path.insert(0, str(TOOL_DIR))                     # other modules of the tool live next to this file
# the slicer-independent part and the Bambu Studio part; everything stays reachable as orientr.<name> (the form
# and bambu_templates.py get this module)
from orientr_core import *  # noqa: E402,F401,F403
from bambu_project import *  # noqa: E402,F401,F403
from orientr_core import _copy_part, _number, _version  # noqa: E402,F401
from orientr_i18n import APP_DIR, cap, t as tr  # noqa: E402,F401


_ERROR_FILE = os.environ.pop("ORIENTR_ERROR_FILE", "")     # taken out: the form's own window must not inherit it


def start_error(message: str) -> None:
    """Started from the Start menu or desktop shortcut (orientr.cmd --shortcut sets ORIENTR_ERROR_FILE): the window is
    minimized and closes at once, so the reason it could not start goes to that file, which orientr.cmd shows in a
    message box. Elsewhere nothing happens (the message is on the screen)."""
    path = _ERROR_FILE
    if path:
        try:
            Path(path).write_text(message, encoding="utf-8")
        except OSError:
            pass


def orientr_version() -> str:
    """This tool's version, from the VERSION file next to it ('' when missing)."""
    try:
        return (TOOL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


RELEASE_REPO = "orientr/orientr-untested"   # where releases are published (organisation Orientr, 2026-11-22;
                                            # was orientr-test until 2026-11-24, GitHub redirects the old name)


RELEASE_VERSION_URL = f"https://raw.githubusercontent.com/{RELEASE_REPO}/master/VERSION"


UPDATE_CHECK_FILE = APP_DIR / "update-check.json"


def orientr_latest() -> str:
    """The newest version published on GitHub ('' when unknown or offline); see update_check."""
    return update_check()[0]


def _no_connection(e: BaseException) -> bool:
    """Did a request fail because there is no connection (name not resolved, refused, unreachable, timed out)? Not
    when the server answered (an HTTP error such as 404 for a private repository): then the internet works."""
    import socket
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return False
    reason = e.reason if isinstance(e, urllib.error.URLError) else e
    return isinstance(reason, (socket.gaierror, socket.timeout, TimeoutError, ConnectionError)) or (
        isinstance(reason, OSError) and getattr(reason, "winerror", None) in (10050, 10051, 10060, 10061, 10065))


def update_check() -> tuple[str, str]:
    """(newest version published on GitHub or '', state): state "checked" (read now or within 12 hours), "offline"
    (no connection to GitHub: the name was not resolved, or the connection was refused or timed out; 
    2026-11-22: say so instead of "up to date"), "unknown" (GitHub answered but gave no version, e.g. a private
    repository without the GitHub CLI) or "off" (ORIENTR_NO_UPDATE_CHECK=1). After a failure it asks again after 1 hour,
    and a version found by an earlier check is still returned with it (it is real, only older). 2 s timeout, so the
    form never waits long on the network."""
    if os.environ.get("ORIENTR_NO_UPDATE_CHECK"):
        return "", "off"
    known = ""                                            # an earlier answer survives a failed check
    own = orientr_version()
    try:
        data = json.loads(UPDATE_CHECK_FILE.read_text(encoding="utf-8"))
        # only an answer given to this very version: after installing another one (also a lower one, as when the
        # releases started again at 0.0.1 on 2026-11-22) it asks GitHub again
        if data.get("url") == RELEASE_VERSION_URL and data.get("own") == own:
            known = str(data.get("latest") or "")
            state = str(data.get("state") or ("checked" if known else "unknown"))
            age = time.time() - float(data.get("checked", 0))
            if age < (12 * 3600 if state == "checked" else 3600):
                return known, state
    except (OSError, ValueError, TypeError):
        pass
    latest, state = "", "unknown"
    try:
        import urllib.request
        with urllib.request.urlopen(RELEASE_VERSION_URL, timeout=2) as r:
            text = r.read(64).decode("utf-8", "replace").strip()
        if re.fullmatch(r"\d+(\.\d+){1,3}", text):
            latest, state = text, "checked"
    except Exception as e:                                # offline, no such repo, blocked, or a private repo
        if _no_connection(e):
            state = "offline"                             # the GitHub CLI would not get through either
        else:
            try:                                          # private repo: the GitHub CLI knows who you are
                import bambu_studio
                gh = bambu_studio.trusted_exe("gh")       # never a gh.exe from the current folder
                if not gh:
                    raise OSError("no gh")
                out = subprocess.run([gh, "api", f"repos/{RELEASE_REPO}/contents/VERSION",
                                      "-H", "Accept: application/vnd.github.raw"], capture_output=True, text=True,
                                     timeout=4).stdout.strip()
                if re.fullmatch(r"\d+(\.\d+){1,3}", out):
                    latest, state = out, "checked"
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        UPDATE_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        for old in UPDATE_CHECK_FILE.parent.glob("*-version.json"):   # the same file of 0.0.1, under another name
            old.unlink(missing_ok=True)
        UPDATE_CHECK_FILE.write_text(json.dumps({"checked": time.time(), "latest": latest or known,
                                                    "state": state, "url": RELEASE_VERSION_URL, "own": own}),
                                        encoding="utf-8")
    except OSError:
        pass
    return latest or known, state


def bambu_status(t: Template | None) -> dict:
    """Is Bambu Studio installed and up to date, does the template still match it, and is this tool up to date? For
    the lines under the header of the form and of the model list: {"ok": bool, "lines": [...]} (one line per thing when
    all is well, else only what needs attention)."""
    from orientr_i18n import t as tr                        # wording of the lines: 2026-11-18
    if not Path(BAMBU_EXE).exists():
        return {"ok": False, "lines": [tr("s.missing", path=BAMBU_EXE)]}
    installed, cloud = studio_versions()
    mine, (latest, checked) = orientr_version(), update_check()
    lines = []
    if _version(cloud) and _version(installed) and _version(cloud) > _version(installed):
        lines.append(tr("s.update", v=cloud))
    # RULES_VERSION: the version this release was tested with (its self-test passes), so a new user does not see the
    # warning for it (0.0.0 test: every first start showed it); other versions until this user's own self-test passes
    if installed and installed not in (RULES_VERSION, verified_version()):
        lines.append(tr("s.untested", v=installed))
    if _version(latest) and _version(mine) and _version(latest) > _version(mine):
        lines.append(tr("s.orientr_new", new=latest, v=mine))
    if t is not None and template_age(t):                 # the report keeps the long text with the steps
        lines.append(tr("s.old_template"))
    if lines:
        return {"ok": False, "lines": lines}
    lines = [tr("s.ok", v=installed) if installed else tr("s.ok_unknown")]
    if mine:                                              # "up to date" only when it was really checked
        lines.append(tr("s.orientr_ok" if checked == "checked" else "s.orientr_offline" if checked == "offline"
                        else "s.orientr_local", v=mine))
    return {"ok": True, "lines": lines}


def _selftest_cube(t: Template, name: str, rgb=(0.8, 0.8, 0.8), s: float = 15.0) -> Part:
    """A cube of s mm as a part, oriented and decided like any part, for the self-test's slices."""
    c = np.array([[x, y, z] for z in (0, s) for y in (0, s) for x in (0, s)], float)
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    tris = np.array([c[[q[j] for j in i]] for q in quads for i in ((0, 1, 2), (0, 2, 3))])
    p = Part(name, "", "", rgb, Mesh.from_triangles(tris, "cube"))
    bed = (t.bed_x[1] - t.bed_x[0] - 2 * MARGIN, t.bed_y[1] - t.bed_y[0] - 2 * MARGIN)
    p.an = choose_orientation(p.mesh, {}, bed, t.bed_h, t.slope, t.first_layer / 2 + 1e-6)
    decide(p, t)
    return p


def _selftest_nozzle(path: Path) -> tuple[str, str]:
    """(level, text): the printer preset of another nozzle size swapped in (set_nozzle_size), sliced (2026-11-23: every
    other size failed on the command line, the project kept the template's extruder_nozzle_diameter)."""
    try:
        t = load_template(path)
        other = next((s for s in nozzle_sizes(template_printer(t)) if s != template_nozzle(t)), None)
        if not other:
            return "ok", f"{path.stem}: no other nozzle size to test"
        with orientr_tempdir() as td:
            td = Path(td)
            apply_print_settings(t, {"nozzle_size": other})
            p = _selftest_cube(t, "Selftest nozzle")
            plates, t.level = pack_auto([p], t, 0)
            out = td / "nozzle.3mf"
            write_3mf(out, plates, t, "Selftest nozzle")
            stats = slice_stats(out, td / "sliced")
            ok = bool(stats["plates"]) and stats["s"] > 0
            return ("ok" if ok else "FAIL", f"{path.stem}: another nozzle size ({other} mm) sliced")
    except Exception as e:                                # a format change surfaces as any kind of error
        return "FAIL", f"{path.stem}: nozzle size test slice failed: {type(e).__name__}: {e}"


def _selftest_colours(path: Path) -> tuple[str, str]:
    """(level, text): filaments made per colour (expand_filaments) and, on printers with 2+ hotends, a mixed one
    (2026-11-23), sliced: the lists are written as the window writes them, so a new layout in a Studio update shows
    here. Three cubes in red, blue and white, a fourth in a mix of the first two."""
    try:
        with orientr_tempdir() as td:
            td = Path(td)
            t = load_template(path)
            mixes = [([1, 2], [0.5, 0.5], "#7F3F7F")] if hotends(t) >= 2 else []
            expand_filaments(t, ["#C12E1F", "#0A2989", "#FFFFFF"], mixes)
            parts = []
            for i in range(t.filaments):
                p = _selftest_cube(t, f"Selftest colour {i + 1}", hex_srgb(t.colours[i]))
                p.filament = i + 1
                parts.append(p)
            plates, t.level = pack_auto(parts, t, 0)
            out = td / "colours.3mf"
            write_3mf(out, plates, t, "Selftest colours")
            stats = slice_stats(out, td / "sliced")
            with zipfile.ZipFile(td / "sliced" / "sliced.3mf") as z:
                ps = json.loads(z.read("Metadata/project_settings.config"))
            n = len(ps.get("filament_settings_id") or [])
            mixed = list(ps.get("filament_is_mixed") or [])
            used = {f["id"] for f in stats["filaments"]}
            ok = (n == t.filaments and used == {1, 2, 3} and stats["s"] > 0
                  and (not mixes or mixed[-1:] == ["1"]))
            what = f"{n} filaments" + (", 1 mixed" if mixes else "")
            return ("ok" if ok else "FAIL",
                    f"{path.stem}: colours made by the tool ({what}) sliced" + ("" if ok else
                    f": Studio read back {n} filaments, used {sorted(used)}, mixed {mixed}"))
    except Exception as e:                                # a format change surfaces as any kind of error
        return "FAIL", f"{path.stem}: colour test slice failed: {type(e).__name__}: {e}"


def selftest(all_templates: bool = False, template: str | None = None) -> int:
    """Everything that can break when Bambu Studio is updated, checked in one go (exit code 1 on a failure):
    Studio and its data files, the templates, a test slice of a small cube through the whole pipeline (the formats
    this tool reads back: result.json, slice_info.config, project_settings.config, the per-part settings), the
    Studio warnings, and the rules copied from Studio's source against the source online. A pass is remembered per
    Studio version, so the status stops asking for it."""
    rows: list[tuple[str, str]] = []

    def add(level: str, text: str) -> None:
        rows.append((level, text))
        print(f"[{level:^4}] {text}", flush=True)
    installed = studio_versions()[0]
    if not Path(BAMBU_EXE).exists():
        add("FAIL", f"Bambu Studio not found: {BAMBU_EXE}")
        return 1
    add("ok", f"Bambu Studio {installed or '(version unknown)'} at {BAMBU_EXE}")
    res = Path(BAMBU_EXE).parent / "resources"
    # 1. Studio's data files the rules read live
    checks = [("info/filament_info.json", lambda d: d.get("high_temp_filament")),
              ("info/nozzle_incompatibles.json", lambda d: d.get("incompatible_nozzles"))]
    for rel, ok in checks:
        try:
            good = ok(json.loads((res / rel).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            good = False
        add("ok" if good else "FAIL", f"resources/{rel} " + ("has the expected content" if good else "is missing or has a new layout"))
    flags = 0
    for f in (res / "printers").glob("*.json"):
        try:
            flags += any(isinstance(v, dict) and "support_wrapping_detection" in v for v in json.loads(f.read_text(encoding="utf-8")).values())
        except (OSError, ValueError):
            pass
    add("ok" if flags else "FAIL", f"resources/printers: support_wrapping_detection found in {flags} printer file(s)")
    models = printer_models()
    add("ok" if models else "FAIL", f"printer profiles readable: {len(models)} printer model(s)")
    # 2. templates
    tdir = TOOL_DIR / "templates"
    names, broken, old = [], [], []
    for f in sorted(tdir.glob("*.3mf")):
        try:
            tpl = load_template(f)
        except Exception as e:                            # any failure to read it counts
            broken.append(f"{f.name}: {e}")
            continue
        names.append(f)
        if template_age(tpl):
            old.append(f.name)
    add("FAIL" if broken else "ok", f"templates readable: {len(names)} of {len(names) + len(broken)}" + "".join(f"\n         {b}" for b in broken))
    if old:
        add("warn", f"saved with an older Studio, save them again: {', '.join(old)}")
    # 3. a test slice through the whole pipeline
    todo = names if all_templates else [resolve_template(Path.cwd(), template) if template else DEFAULT_TEMPLATE]
    for path in todo:
        try:
            with orientr_tempdir() as td:
                td = Path(td)
                t = load_template(path)
                s = 20.0
                c = np.array([[x, y, z] for z in (0, s) for y in (0, s) for x in (0, s)], float)
                quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
                tris = np.array([c[[q[j] for j in i]] for q in quads for i in ((0, 1, 2), (0, 2, 3))])
                p = Part("Selftest cube", "", "", (0.8, 0.8, 0.8), Mesh.from_triangles(tris, "cube"))
                bed = (t.bed_x[1] - t.bed_x[0] - 2 * MARGIN, t.bed_y[1] - t.bed_y[0] - 2 * MARGIN)
                p.an = choose_orientation(p.mesh, {}, bed, t.bed_h, t.slope, t.first_layer / 2 + 1e-6)
                decide(p, t)
                plates, t.level = pack_auto([p], t, 0)
                out = td / "selftest.3mf"
                write_3mf(out, plates, t, "Selftest")
                stats = slice_stats(out, td / "sliced")
                good = bool(stats["plates"]) and stats["s"] > 0 and stats["g"] > 0
                msgs = check_with_bambu(out, plates, {p.name: dict(p.settings)})
                settings_ok = tr("c.settings_ok", n=1) in msgs
                with zipfile.ZipFile(td / "sliced" / "sliced.3mf") as z:
                    studio_gui_warnings(z)                # must not raise on this Studio's files
                    ps = json.loads(z.read("Metadata/project_settings.config"))
                    studio_rules_note(z.read("Metadata/slice_info.config"))   # must not raise either
                keys = ("filament_type", "filament_ids", "filament_settings_id", "nozzle_diameter", "nozzle_volume_type",
                        "printer_model", "enable_prime_tower", "print_sequence", "filament_map", "filament_volume_map")
                lost = [k for k in keys if k not in ps]
            add("ok" if good else "FAIL", f"{path.stem}: Studio sliced the test cube, estimate and filament read back")
            add(*_selftest_colours(path))
            add(*_selftest_nozzle(path))
            add("ok" if settings_ok else "FAIL", f"{path.stem}: per-part settings survived loading in Studio")
            add("ok" if not lost else "FAIL", f"{path.stem}: project settings keys the warnings read: " + ("all present" if not lost else "missing " + ", ".join(lost)))
        except Exception as e:                            # a format change surfaces as any kind of error
            add("FAIL", f"{path.stem}: test slice failed: {type(e).__name__}: {e}")
    # 4. SOMA: its own files and functions this tool reads (2026-11-22: a SOMA update may change them)
    for level, text in soma_checks(Path.cwd()):           # this model when run in one, else the newest built model
        add(level, text)
    # 5. the rules copied from Studio's source, against the source online
    changed = unreachable = 0
    try:
        import urllib.request
        fetch = lambda path: urllib.request.urlopen(RULES_REPO_RAW + path, timeout=20).read().decode("utf-8", "replace")  # noqa: E731
        online = re.search(r'SLIC3R_VERSION "([\d.]+)"', fetch("version.inc"))
        cache: dict[str, str] = {}
        for label, path, fn, want in RULES_SOURCES:
            cache.setdefault(path, fetch(path))
            got = source_fingerprint(source_function(cache[path], fn))
            if got != want:
                changed += 1
                add("warn", f"Studio's source changed: {label} ({path}, {fn}); review studio_gui_warnings() and update "
                            f"the fingerprint ({want or 'none'} -> {got or 'function not found'})")
        if not changed:
            add("ok", f"all {len(RULES_SOURCES)} rules match Studio's source (source version {online.group(1) if online else '?'})")
    except Exception as e:                                # offline or blocked: say so, do not fail
        unreachable = 1
        add("warn", f"could not read Studio's source online, rules not compared: {type(e).__name__}: {e}")
    fails = sum(level == "FAIL" for level, _ in rows)
    print(f"\nself-test: {fails} failure(s), {sum(level == 'warn' for level, _ in rows)} warning(s)")
    if not fails and not changed and not unreachable and installed:
        try:
            VERIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
            VERIFIED_FILE.write_text(json.dumps({"studio": installed, "date": time.strftime("%Y-%m-%d")}), encoding="utf-8")
            print(f"remembered: Bambu Studio {installed} is verified")
        except OSError:
            pass
    return 1 if fails else 0


def soma_checks(ws: Path | None = None) -> list[tuple[str, str]]:
    """The SOMA side of the self-test, on a built model (the current folder when it is one, else the newest built
    model): everything this tool takes from SOMA, which is not a documented interface. FAIL: the tool would stop or
    fall back to the slow `soma export`; warn: it works with less (grey parts) or could not be checked."""
    if ws is None or not (ws / ".soma" / "model.map.json").exists():
        built = [f for _, f in soma_models() if (f / ".soma" / "model.map.json").exists()
                 and (f / "output" / "model.step").exists()]
        if not built:
            return [("warn", "SOMA: no built model on this PC, SOMA's files not checked (build one, then run again)")]
        ws = built[0]
    name, out = model_title(ws), []
    try:
        build = json.loads((ws / ".soma" / "build.json").read_text(encoding="utf-8"))
        missing = [k for k in ("status", "started", "finished") if k not in build]
        out.append(("FAIL" if missing else "ok", f"SOMA ({name}): .soma/build.json " +
                    (f"misses {', '.join(missing)}" if missing else f"readable, last build {build['status']}")))
        if build.get("status") != "ok":
            return out + [("warn", f"SOMA ({name}): the last build did not succeed, the rest is not checked")]
    except (OSError, ValueError) as e:
        return [("FAIL", f"SOMA ({name}): .soma/build.json not readable: {type(e).__name__}: {e}")]
    try:
        pj = json.loads((ws / ".soma" / "project.json").read_text(encoding="utf-8"))
        out.append(("ok" if pj.get("name") else "warn", f"SOMA ({name}): .soma/project.json " +
                    ("has the model's name" if pj.get("name") else "has no name (the folder name is used)")))
    except (OSError, ValueError, AttributeError) as e:
        out.append(("warn", f"SOMA: .soma/project.json not readable ({type(e).__name__}): the folder name is used"))
    try:
        parts = printable_parts(ws)
    except Exception as e:
        return out + [("FAIL", f"SOMA ({name}): parts list (.soma/model.map.json) not readable: {e}")]
    if not parts:
        return out + [("warn", f"SOMA ({name}): no printable parts, meshing not checked")]
    grey = sum(rgb == (0.6, 0.6, 0.6) for *_, rgb in parts)
    out.append(("ok", f"SOMA ({name}): parts list readable, {len(parts)} printable part(s)"))
    out.append(("ok" if grey < len(parts) else "warn", f"SOMA ({name}): colours from .soma/model.glb: "
                f"{len(parts) - grey} of {len(parts)}" + ("" if grey < len(parts) else " (parts will be grey)")))
    n, step, group, rgb = parts[0]
    try:                                                  # stl_from_step only trusts a STEP written by the last build
        written = (ws / "output" / "model.step").stat().st_mtime
    except OSError:
        written = -1.0
    if not build.get("started", 0) - 1 <= written <= build.get("finished", 0) + 1:
        return out + [("warn", f"SOMA ({name}): output/model.step is not from the last build, meshing not checked "
                               "(build the model, then run again)")]
    try:
        with orientr_tempdir() as td:
            p = Part(n, step, group, rgb)
            import io
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                ok = stl_from_step(ws, [p], Path(td))
            tris = len(read_stl(Path(td) / f"{step}.stl")) if ok else 0
        out.append(("ok" if tris else "FAIL", f"SOMA ({name}): output/model.step meshed with soma.meshexport, " +
                    (f"{n!r}: {tris} triangles" if tris else "not usable (each run falls back to the slow soma export)")))
    except Exception as e:
        out.append(("FAIL", f"SOMA ({name}): meshing with soma.meshexport failed: {type(e).__name__}: {e}"))
    return out


CONHOST_GUID = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"   # "Windows Console Host" as the default terminal app


FORM_START_TIMEOUT = 60                                   # seconds for Windows Terminal and Python to start the form


def _windows_terminal() -> str | None:
    """wt.exe, unless Windows Terminal is not installed or the user chose Windows' own console as the default
    terminal app (Settings > System > For developers > Terminal): then the form opens there, as before."""
    import bambu_studio
    wt = bambu_studio.trusted_exe("wt")                   # never a wt.exe from the current folder
    if not wt:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Console\%%Startup") as key:
            if str(winreg.QueryValueEx(key, "DelegationTerminal")[0]).upper() == CONHOST_GUID:
                return None
    except OSError:                                       # no choice made: "Let Windows decide"
        pass
    return wt


def _wait_process(pid: int) -> int | None:
    """Wait until process `pid` ends and give its exit code (None when it already ended or cannot be opened)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k.OpenProcess(0x00100000 | 0x1000, False, pid)   # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        while k.WaitForSingleObject(handle, 500) == 0x102:    # WAIT_TIMEOUT: in steps, so Ctrl+C still gets through
            pass
        code = wintypes.DWORD()
        return code.value if k.GetExitCodeProcess(handle, ctypes.byref(code)) else None
    finally:
        k.CloseHandle(handle)


def _form_window_size(ws: Path | None) -> tuple[int, int]:
    """(columns, rows) of the form's window: exactly the form of model `ws` with the full header
    (orientr_form.window_size); ws None: the newest SOMA model, for the window that starts with the model chooser."""
    try:
        import orientr_form
        ws = ws or soma_models()[0][1]
        return orientr_form.window_size(orientr_form.Form(ws, read_config(ws), sys.modules[__name__]))
    except Exception:                                     # e.g. a broken template: the form itself will say so
        return 100, 42


NOT_STARTED = f"the window did not start within {FORM_START_TIMEOUT} s (see it for an error)"


WT_START_TIMEOUT = 30    # Windows Terminal: no form by then (an old version refusing --size): Windows' own console


def _started(pid_file: Path, timeout: float = FORM_START_TIMEOUT) -> int | None:
    """The process id the new window writes first thing (own_console_start); None when it did not come in time."""
    t0 = time.time()
    while time.time() - t0 <= timeout:
        try:
            return int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):                     # not there yet, or still being written
            time.sleep(0.2)
    return None


def _form_in_terminal(wt: str, cwd: Path, cmd: list[str], pid_file: Path, size: tuple[int, int],
                      wait: bool) -> tuple[bool, int | None, str | None]:
    """`cmd` in a new Windows Terminal window of `size`: a new console window is 30 rows, too low for the full header
    above the form, and Windows Terminal ignores `mode con`. wt.exe hands the window to Windows Terminal and returns at
    once, and the tab gets Windows Terminal's own environment: the variables the form needs (PATH, BAMBU_*, SOMA_*) go
    along in a temporary file, and the window writes its process id to pid_file, which this waits for (and with
    `wait` for that process to end). Returns (started, exit code or None, message when it never started); started is
    False when wt.exe could not be run, or when no form came within WT_START_TIMEOUT (2026-11-24: an old Windows
    Terminal without --size shows an error instead): then Windows' own console takes over, and a form that still comes
    later in Windows Terminal closes at once (the ".late" marker next to pid_file, see own_console_start)."""
    cols, rows = size
    fd, env_file = tempfile.mkstemp(prefix=TEMP_PREFIX + "env-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in os.environ.items()
                   if k.upper() == "PATH" or k.upper().startswith(("BAMBU_", "SOMA_"))}, f)
    esc = lambda s: s.replace(";", r"\;")                 # noqa: E731  (wt.exe reads ; as "next command")
    try:
        try:
            if subprocess.run([wt, "-w", "new", "--size", f"{cols},{rows}", "new-tab", "--title", "Orientr",
                               "-d", esc(str(cwd)), "--", *map(esc, cmd + ["--env-file", env_file])]).returncode:
                return False, None, None                  # wt.exe refused: Windows' own console instead
        except OSError:
            return False, None, None
        pid = _started(pid_file, WT_START_TIMEOUT)        # it read the env file before it wrote this
        if pid is None:
            try:                                          # a form that comes after all: it closes at once
                Path(str(pid_file) + ".late").write_text("", encoding="utf-8")
            except OSError:
                pass
            if _started(pid_file, 0.5) is None:           # not in the meantime either: the console takes over
                return False, None, None
            _remove(Path(str(pid_file) + ".late"))        # it did come just now: keep it
            pid = _started(pid_file, 0)
        return True, _wait_process(pid) if wait else None, None
    finally:
        _remove(Path(env_file))


def own_console_start(pid_file: str | None) -> None:
    """In the window _own_window() opened: tell it the process id (the variables it sent were taken over when this
    file was loaded, see _take_env_file)."""
    os.environ["ORIENTR_OWN_CONSOLE"] = "1"                 # also for the form the model chooser starts in this window
    late = Path(str(pid_file) + ".late") if pid_file else None
    if late and late.exists():                            # Windows Terminal came too late: Windows' own console
        _remove(late)                                     # already shows the form (2026-11-24), so this window
        raise SystemExit(0)                               # closes (exit code 0: Windows Terminal closes the tab)
    if pid_file:
        try:                                              # written whole, then renamed: _own_window never sees a
            part = Path(pid_file + ".part")               # half-written file, nor one still open (it deletes it)
            part.write_text(str(os.getpid()), encoding="utf-8")
            os.replace(part, pid_file)
        except OSError:
            pass


def _remove(path: Path) -> None:
    """Delete a temporary file; a failure must not change how a run ends (the starter window must still close)."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _own_window(cwd: Path, cmd: list[str], size: tuple[int, int], wait: bool = True) -> tuple[int | None, str | None]:
    """Run `cmd` (this file with --own-console) in a new console window of `size`: Windows Terminal when there is
    one (_windows_terminal), else Windows' own console. With `wait` until that window ends, else only until it has
    started. Returns (exit code or None, message when it never started)."""
    pid_file = Path(tempfile.gettempdir()) / f"bambu-{uuid.uuid4().hex}.pid"
    wt_pid = Path(str(pid_file) + ".wt")                  # its own: a late Windows Terminal never takes the console's
    try:
        wt = _windows_terminal()
        started, rc, failed = _form_in_terminal(wt, cwd, cmd + ["--pid-file", str(wt_pid)], wt_pid, size, wait) \
            if wt else (False, None, None)
        cmd = cmd + ["--pid-file", str(pid_file)]
        if not started:                                   # Windows' own console (it inherits the environment)
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            env = {**os.environ, "ORIENTR_OWN_CONSOLE": "1"}   # a real console, also from SOMA
            if wait:
                rc = subprocess.run(cmd, cwd=cwd, creationflags=flags, env=env).returncode
            else:
                subprocess.Popen(cmd, cwd=cwd, creationflags=flags, env=env)
                failed = None if _started(pid_file) else NOT_STARTED
        return rc, failed
    finally:
        for p in (pid_file, wt_pid):
            _remove(p)
            _remove(Path(str(p) + ".part"))               # a window that started too late


def _own_window_wanted() -> bool:
    """`orientr` typed in a terminal: the form gets its own window of its own size (2026-11-21: a program
    cannot resize a Windows Terminal tab, and the header needs the room). Not in SOMA's terminal panel, which shows
    the form itself, and not inside that window."""
    return os.name == "nt" and not os.environ.get("SOMA_PROJECT") and not os.environ.get("ORIENTR_OWN_CONSOLE")


def show_own_console() -> None:
    """Bring this process's console window to the front, restored when it is minimized (the shortcut starts it so).
    Nothing happens without a console of its own; never fails."""
    try:
        import ctypes
        k32, u32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
        k32.GetConsoleWindow.restype = ctypes.c_void_p
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            u32.ShowWindow(ctypes.c_void_p(hwnd), 9)          # SW_RESTORE
            u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    except (OSError, AttributeError):
        pass


def open_own_window(ws: Path | None) -> int:
    """`orientr` typed in a terminal, or started from its shortcut: the form of model `ws` (None: the model chooser,
    then the chosen model's form) in its own window of the form's size. Returns as soon as that window is up
    (2026-11-21), so a window opened only to start it (the shortcut, a double-clicked orientr.cmd) closes by itself
    and the screen goes straight to Orientr, and a terminal of yours gets its prompt back."""
    if ws is None and not soma_models():
        print(tr("run.no_models"))
        start_error(tr("run.no_models"))
        return 2
    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--own-console"] + (["--form", "--wait"] if ws else [])
    # the window's size needs the form, the form the presets: reading them takes about 2 minutes after a Bambu Studio
    # update. The shortcut starts this window minimized, so it comes to the front first: else the message stayed
    # unseen for the whole wait (tested 2026-11-22)
    if not profiles_cached():
        show_own_console()
    announce_profiles()
    _, failed = _own_window(ws or Path.cwd(), cmd, _form_window_size(ws), wait=False)
    if failed:
        print(tr("run.error", msg=cap(failed)))
        start_error(tr("run.error", msg=cap(failed)))
        return 1
    print(tr("run.opened"))
    sys.stdout.flush()
    close_calling_terminal()
    return 0


SHELLS = ("cmd.exe", "powershell.exe", "pwsh.exe")


PYTHONS = ("python.exe", "pythonw.exe", "py.exe")


# what a shell of its own terminal window or tab is started by: Windows Terminal, or Explorer (Start menu, Win+R, a
# shortcut; also when Windows Terminal is the default terminal). A shell in VS Code or another IDE, or one started by
# another shell, is left open (2026-11-22: it was ended too, with whatever ran in it)
TERMINAL_HOSTS = ("windowsterminal.exe", "explorer.exe")


def _process_table() -> dict[int, tuple[int, str]]:
    """Every running process: pid -> (parent pid, exe name in lower case), from Windows' process snapshot."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):                        # PROCESSENTRY32W
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)           # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    table = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return table


def _command_line(pid: int) -> str | None:
    """The command line of another process (NtQueryInformationProcess, class 60: Windows 8.1 and newer), or None."""
    import ctypes
    from ctypes import wintypes
    k32, ntdll = ctypes.WinDLL("kernel32"), ctypes.WinDLL("ntdll")
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    ntdll.NtQueryInformationProcess.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                                ctypes.POINTER(wintypes.ULONG))

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    h = k32.OpenProcess(0x1000, False, pid)               # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        size = wintypes.ULONG(0)
        ntdll.NtQueryInformationProcess(h, 60, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if ntdll.NtQueryInformationProcess(h, 60, buf, size, ctypes.byref(size)) != 0:
            return None
        us = UnicodeString.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ""
    finally:
        k32.CloseHandle(h)


def calling_shell(table: dict[int, tuple[int, str]], pid: int, command_line=_command_line) -> int | None:
    """The shell `orientr` was typed in: up from this process past the Pythons (the model's python.exe is a launcher)
    to the first shell. A `cmd.exe /c` started by PowerShell only runs orientr.cmd, so its PowerShell is the one; an
    interactive cmd.exe is the shell itself. None when there is no shell (a shortcut
    started it: then its cmd.exe closes anyway), something else is in between, the command line cannot be read, or the
    shell is not one of its own terminal window or tab (TERMINAL_HOSTS)."""
    seen = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        parent, exe = table[pid]
        if exe in PYTHONS:
            pid = parent
            continue
        if exe not in SHELLS:
            return None
        if exe == "cmd.exe" and table.get(parent, (0, ""))[1] in ("powershell.exe", "pwsh.exe"):
            line = command_line(pid)
            if line is None:
                return None
            if not re.search(r"(?i)(^|\s)/c(\s|$)", line):
                return None                               # an interactive cmd.exe in a PowerShell: started by a shell
            pid = parent
        return pid if table.get(table[pid][0], (0, ""))[1] in TERMINAL_HOSTS else None
    return None


def close_calling_terminal() -> None:
    """2026-11-22: `orientr` typed in a terminal outside SOMA opens the form in its own window, and the
    terminal it was typed in closes then. Its shell is ended with exit code 0, so Windows Terminal closes the tab (it
    keeps a tab open after any other code). Not in SOMA (it never gets here), not when Claude Code runs it, and
    ORIENTR_KEEP_TERMINAL=1 keeps it open."""
    if os.name != "nt" or os.environ.get("ORIENTR_KEEP_TERMINAL") or os.environ.get("CLAUDECODE"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        shell = calling_shell(_process_table(), os.getpid())
        if not shell:
            return
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x0001, False, shell)          # PROCESS_TERMINATE
        if h:
            try:
                k32.TerminateProcess(h, 0)
            finally:
                k32.CloseHandle(h)
    except Exception:                                     # the form is open already: never fail over this
        pass


# --- report ---------------------------------------------------------------------------------------------------------
def orientation_label(down: str) -> str:
    """The orientation as the report shows it: the internal names ('-z down', 'face (...) down', 'x up (bambu.json)',
    'as modelled') stay the keys the code compares, only the text is translated."""
    if down == "as modelled":
        return tr("o.modelled")
    m = re.fullmatch(r"face (\(.*\)) down", down)
    if m:
        return tr("o.face", vec=m.group(1))
    m = re.fullmatch(r"(\S+) up \(bambu\.json\)", down)
    if m:
        return tr("o.up", key=m.group(1))
    m = re.fullmatch(r"([+-][xyz]) down", down)
    return tr("o.axis", axis=m.group(1)) if m else down


def override_label(key: str, value) -> str:
    """A project-wide choice as the report names it: "walls 3", not Bambu Studio's key "wall_loops 3" (2026-11-22)."""
    text = tr(f"rp.k_{key}", v=value)
    return f"{key} {value}" if text == f"rp.k_{key}" else text


def report(plates, t: Template, out: Path, title: str, checks: list[str], notices: list[str] = ()) -> str:
    mode = lambda m: tr(f"v.{m}") if m in ("auto", "on", "off") else str(m)   # noqa: E731
    only = tr("rp.only", nozzle=tr(f"nz.{t.nozzle}") if t.nozzle in (1, 2) and len(t.nozzle_boxes) == 2
              else f"nozzle {t.nozzle}") if t.nozzle is not None else ""
    L = [tr("rp.title", title=title), "", tr("rp.made", time=time.strftime("%Y-%m-%d %H:%M"), file=out.name), "",
         tr("rp.printer", printer=t.settings.get("printer_settings_id"), x=f"{t.bed_x[1] - t.bed_x[0]:.0f}",
            y=f"{t.bed_y[1] - t.bed_y[0]:.0f}", z=f"{t.bed_h:.0f}", only=only),
         tr("rp.process", process=t.settings.get("print_settings_id"))
         + (tr("rp.chosen", what=t.process) if t.process else ""),
         # filaments made per colour (2026-11-23): each with its number and Bambu's name of its colour or mix
         tr("rp.filaments", filaments="; ".join(filament_label(t, i + 1) for i in range(t.filaments)) if t.generated
            else ", ".join(t.settings.get("filament_settings_id", [])))
         + (tr("rp.chosen", what=t.material) if t.material else ""),
         tr("rp.template", path=shown_path(t.path), app=t.app),
         tr("rp.wide", layer=t.base("layer_height"), walls=t.base("wall_loops"),
            infill=t.base("sparse_infill_density"), support=mode(t.support_mode), brim=mode(t.brim_mode))
         + (tr("rp.chosen", what=", ".join(override_label(k, v) for k, v in t.overrides.items()))
            if t.overrides else ""), ""]
    if t.colour_swap and not t.generated:                 # the model's colours on the template's filaments
        L[-1:-1] = [tr("rp.recoloured", colours=", ".join(filament_label(t, i + 1) for i in range(t.model_used)))]
    objects = sum(len(items) for _, items in plates)
    if t.duplicates > 1 or t.max_plates or any(p.copy_of for _, items in plates for p, *_ in items):
        L[-1:-1] = [tr("rp.volume", n=objects, dup=t.duplicates, plates=len(plates),
                       max=t.max_plates or tr("v.no_limit"))]
    L += [tr("rp.notice", text=n) for n in notices] + ([""] if notices else [])
    for i, (_, items) in enumerate(plates):
        L += [tr("rp.plate", n=i + 1), "", tr("rp.head"), "|---|---|---|---|---|---|"]
        rows: dict[str, list] = {}                        # copies of a part on this plate: one row, "Part × 3"
        for p, *_ in items:
            key = p.copy_of or p.name
            rows.setdefault(key, [p, 0])[1] += 1
        for key, (p, count) in rows.items():
            a = p.an
            sz = f"{a.size_xy[0]:.0f} x {a.size_xy[1]:.0f} x {a.height:.0f}"
            names = key + "".join(tr("rp.with", name=e.name, n=f) for e, f in p.extras) + \
                (f" × {count}" if count > 1 else "")
            support = tr("rp.tree") if p.settings.get("enable_support") == "1" else tr("rp.none")
            cell = lambda s: str(s).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")   # noqa: E731
            # a | in a part name would end the table cell (2026-11-22): escaped, as Markdown wants it
            L.append(f"| {cell(names)} | {orientation_label(a.down)} | {sz} | {p.brim:g} mm | {support} | "
                     f"{cell('; '.join(p.reasons))} |")
        # parts standing in another part's opening (2026-11-23)
        inside: dict[str, list] = {}
        for part, host in (getattr(items, "nested", None) or {}).items():
            inside.setdefault(host, []).append(part)
        if inside:
            L += [""] + [tr("rp.nested", host=h, parts=", ".join(ps)) for h, ps in inside.items()]
        # once per part and plate: copies carry the part's warnings too
        warn = list(dict.fromkeys(f"- **{p.copy_of or p.name}**: {w}" for p, *_ in items
                                  for w in p.warnings + sum((e.warnings for e, _ in p.extras), [])))
        L += ([""] + warn if warn else []) + [""]
    if checks:
        L += [tr("rp.check"), ""] + [f"- {c}" for c in checks] + [""]
    return "\n".join(L)


def printer_templates(ws: Path, current: str | None) -> dict[str, tuple[str | None, Path | None]]:
    """Per printer model, the template to use: (spec, None) for an existing template, (None, path) for a recently
    sent print that can become one. Prefers the current template's filament and process, then the 0.4 mm nozzle,
    then the newest print. One pass over all templates and prints, so it is cheap to ask for every printer."""
    menu = _menu()
    me = sys.modules[__name__]
    cur_ok, _, cur = menu.describe(me, resolve_template(ws, current))
    c = cur.settings if cur_ok else {}

    def rank(t: Template) -> tuple:
        s = t.settings
        same_fil = [menu.short(f) for f in s.get("filament_settings_id") or []] == \
                   [menu.short(f) for f in c.get("filament_settings_id") or []]
        same_proc = menu.short(s.get("print_settings_id")) == menu.short(c.get("print_settings_id"))
        return (not same_fil, not same_proc, str(s.get("printer_variant", "")) != "0.4")

    best: dict[str, tuple] = {}
    # one filament only: templates with more are chosen apart, as "Colors" (colour_templates, 2026-11-22)
    for spec, path in menu.template_files(me, ws, current):      # a template at its own path counts too
        ok, _, t = menu.describe(me, path)
        if ok and t.filaments == 1:
            key = (0, rank(t), spec)
            m = template_printer(t)
            if m not in best or key < best[m][0]:
                best[m] = (key, (spec, None))
    for i, (p, _) in enumerate(menu.recent_prints(me, limit=30)):  # newest first, more than the 8 --recent lists
        ok, _, t = menu.describe(me, p)
        if ok and t.filaments == 1:
            key = (1, rank(t), str(i).zfill(3))
            m = template_printer(t)
            if m not in best or key < best[m][0]:
                best[m] = (key, (None, p))
    return {m: v for m, (_, v) in best.items()}


def colour_templates(ws: Path, current: str | None = None) -> dict[str, list[tuple[str, object]]]:
    """Per printer model, the templates with more than one filament (saved in Bambu Studio with the AMS colours):
    [(spec, Template)], by name. The form offers them as "Colors" (2026-11-22)."""
    menu = _menu()
    me = sys.modules[__name__]
    out: dict[str, list] = {}
    for spec, path in menu.template_files(me, ws, current):
        ok, _, t = menu.describe(me, path)
        if ok and t.filaments > 1:
            out.setdefault(template_printer(t), []).append((spec, t))
    return out


MENU_PRINT_KEYS = ("material", "process", "layer_height", "infill", "walls", "support", "brim", "nozzle", "nozzle_size",
                   "check", "open", "duplicates", "max_plates", "colours", "colour", "mix")


MAX_OBJECTS = 500         # objects in one project (all duplicates and copies), checked before anything is packed


MAX_TRIANGLES = 5_000_000  # triangles in one project (all objects): beyond this Bambu Studio gets slow or runs out


NOZZLE_WORDS = {"auto": "auto", "left": "left", "links": "left", "gauche": "left",
                "right": "right", "rechts": "right", "droite": "right"}


def validate_config(cfg) -> dict:
    """Check the shape of bambu.json, so that odd content gives a clear message instead of a crash."""
    if not isinstance(cfg, dict):
        raise ToolError("bambu.json must contain an object { ... }")
    if "template" in cfg and cfg["template"] is not None and not isinstance(cfg["template"], str):
        raise ToolError('"template" in bambu.json must be a name or a path (text)')
    pr = cfg.get("print")
    if pr is not None:
        if not isinstance(pr, dict):
            raise ToolError('"print" in bambu.json must be an object { ... }')
        for key in ("support", "brim"):
            if pr.get(key) is not None and pr[key] not in ("auto", "on", "off"):
                raise ToolError(f'"{key}" in "print" must be auto, on or off, not {pr[key]!r}')
        if pr.get("nozzle") is not None and pr["nozzle"] not in ("auto", "left", "right"):
            raise ToolError(f'"nozzle" in "print" must be auto, left or right, not {pr["nozzle"]!r}')
        if pr.get("colours") is not None and pr["colours"] not in ("model", "manual", "mix", "template"):
            raise ToolError(f'"colours" in "print" must be model, manual, mix or template, not {pr["colours"]!r}')
        if pr.get("mix") is not None and not isinstance(pr["mix"], str):
            raise ToolError(f'"mix" in "print" must be a mixing mode (CMYKW, CMYW, RYBW), not {pr["mix"]!r}')
        try:
            parse_colour(pr.get("colour"))
        except ToolError as e:
            raise ToolError(f'"colour" in "print": {e}') from None
        for key in ("check", "open"):
            if pr.get(key) is not None and not isinstance(pr[key], bool):
                raise ToolError(f'"{key}" in "print" must be true or false, not {pr[key]!r}')
        for key in ("material", "process"):
            if pr.get(key) is not None and not isinstance(pr[key], str):
                raise ToolError(f'"{key}" in "print" must be a profile name (text), not {pr[key]!r}')
        for key, pct in (("layer_height", False), ("walls", False), ("infill", True), ("nozzle_size", False)):
            if pr.get(key) not in (None, ""):
                strict_number(pr[key], f'"{key}" in "print"', percent=pct)
        for key, lo, hi in (("duplicates", 1, MAX_COPIES), ("max_plates", 0, MAX_PLATES)):
            if pr.get(key) not in (None, ""):
                whole_number(pr[key], f'"{key}" in "print"', lo, hi)
    parts = cfg.get("parts")
    if parts is not None:
        if not isinstance(parts, dict):
            raise ToolError('"parts" in bambu.json must be an object { "Part name": { ... } }')
        for name, h in parts.items():
            if not isinstance(h, dict):
                raise ToolError(f'"parts" -> {name!r} in bambu.json must be an object {{ ... }}, not {h!r}')
            if "settings" in h and not isinstance(h["settings"], dict):
                raise ToolError(f'{name}: "settings" must be an object {{ "key": "value" }}')
            if h.get("copies") not in (None, ""):
                whole_number(h["copies"], f'{name}: "copies"', 1, MAX_COPIES)
            if h.get("filament") not in (None, "", "auto"):
                whole_number(h["filament"], f'{name}: "filament"', 1, MAX_FILAMENTS)
            try:
                parse_colour(h.get("colour"))
            except ToolError as e:
                raise ToolError(f'{name}: "colour": {e}') from None
    return cfg


def read_config(ws: Path) -> dict:
    path = ws / "bambu.json"
    if not path.exists():
        return with_studio_choice(ws, {})
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ToolError(tr("e.json", line=e.lineno, msg=e.msg)) from None
    return with_studio_choice(ws, validate_config(cfg))


_STUDIO_SPEC: dict = {}                                   # model folder -> template of Studio's printer (or None)


def with_studio_choice(ws: Path, cfg: dict) -> dict:
    """A model without a printer choice yet (no "template" in bambu.json, no inputs/bambu_template.3mf) starts with
    the printer, nozzle size, filament and process selected in Bambu Studio (2026-11-22: every new user
    started on the H2D of the default template). Only what this tool can use: a printer with a template, and the
    system profiles Bambu Studio offers for it (a user's own profile is left out); everything else keeps the
    template's own. A choice already in bambu.json always wins. Saved with the next Generate, like a choice in the
    form."""
    if cfg.get("template") or (ws / "inputs" / "bambu_template.3mf").exists():
        return cfg
    ch = studio_choice()
    if not ch:
        return cfg
    if ws not in _STUDIO_SPEC:                            # read_config runs several times per run: look up once
        try:
            _STUDIO_SPEC[ws] = printer_templates(ws, None).get(ch["printer"], (None, None))[0]
        except Exception:                                 # a broken template: the form and the build say so
            _STUDIO_SPEC[ws] = None
    spec = _STUDIO_SPEC[ws]
    if not spec:
        return cfg
    cfg = json.loads(json.dumps(cfg))
    cfg["template"] = spec
    if cfg.get("print") is None:                          # absent, or null in a hand-written file
        cfg["print"] = {}
    pr = cfg["print"]
    try:
        if not pr.get("nozzle_size") and ch["nozzle_size"] in nozzle_sizes(ch["printer"]):
            pr["nozzle_size"] = ch["nozzle_size"]
        size = str(pr.get("nozzle_size") or "")
        if size == ch["nozzle_size"]:                     # Studio's filament and process belong to its nozzle size
            if not pr.get("material") and ch["material"] in filaments_for(ch["preset"]):
                pr["material"] = ch["material"]
            if not pr.get("process") and ch["process"] in processes_for(ch["preset"]):
                pr["process"] = ch["process"]
    except Exception:                                     # Studio's profiles not readable: the template's own
        pass
    return cfg


def printed_names(ws: Path, cfg: dict) -> list[str]:
    """Names of the parts a build would print: not skipped, and not merged into a part that is skipped."""
    hints = cfg.get("parts") or {}
    names = [n for n, *_ in printable_parts(ws)]
    skipped = {n for n in names if (hints.get(n) or {}).get("skip")}
    return [n for n in names if n not in skipped and (hints.get(n) or {}).get("merge_into") not in skipped]


def _menu():
    import bambu_templates                                # next to this file (TOOL_DIR is on sys.path)
    return bambu_templates


YES = {"yes": True, "y": True, "true": True, "1": True, "on": True, "ja": True, "j": True, "oui": True,
       "no": False, "n": False, "false": False, "0": False, "off": False, "nein": False, "non": False}


MODE_WORDS = {"auto": "auto", "automatic": "auto", "automatisch": "auto", "automatique": "auto",
              "on": "on", "always": "on", "immer": "on", "toujours": "on",
              "off": "off", "never": "off", "nie": "off", "jamais": "off"}


def change_config(ws: Path, cfg: dict, args, save: bool = True) -> dict:
    """Apply --import-template / --set / --skip / --include to bambu.json: checked like the menu, then saved.
    save=False (the form's Preview): the same checks, but nothing is written and no template is added; a template
    that would be added is used from where it is."""
    menu = _menu()
    me = sys.modules[__name__]
    cfg = json.loads(json.dumps(cfg))
    had = set(cfg)                                        # sections that exist already are kept, even if empty
    old_empty = {n for n, h in (cfg.get("parts") or {}).items() if h == {}}
    new_tpl = None                                        # (source, name): installed only after everything checks out
    if args.import_template and args.import_recent:
        raise ToolError("use --import-template or --import-recent, not both")
    if args.import_recent is not None:
        rec = menu.recent_prints(me)
        if not 1 <= args.import_recent <= len(rec):
            raise ToolError(f"--import-recent {args.import_recent}: there are {len(rec)} recently sent print(s)")
        args.import_template = str(rec[args.import_recent - 1][0])
    if args.import_template:
        src = Path(args.import_template)
        ok, text, t = menu.describe(me, src)
        if not ok:
            raise ToolError(f"{src}: {text}")
        name = menu.clean_name(args.name or "", menu.default_name(t))
        if template_path(name).exists() and not args.overwrite:
            raise ToolError(f"template {name}.3mf already exists (choose another --name, or add --overwrite)")
        new_tpl = (src, name)
        cfg["template"] = name
    if args.new_filament and not args.printer:
        raise ToolError("--new-filament needs --printer (the printer to make a template for)")
    if args.printer:
        if args.import_template or args.template or \
                any(s.partition("=")[0].strip().lower() == "template" for s in args.set):
            raise ToolError("--printer chooses the template itself: do not combine it with a template choice")
        model = match_printer(args.printer, printer_models())
        if args.new_filament:                             # a filament this printer has no template for yet
            raise ToolError(no_template_help(model, other_filament=True))
        spec, recent = printer_templates(ws, cfg.get("template")).get(model, (None, None))
        if spec:
            cfg["template"] = spec
        elif recent:                                      # a print sent to this printer: becomes its template
            ok, _, t = menu.describe(me, recent)
            name = menu.clean_name("", menu.default_name(t))
            if template_path(name).exists():
                raise ToolError(f"template {name}.3mf exists but is not usable; remove or fix it, then try again")
            new_tpl = (recent, name)
            cfg["template"] = name
        else:
            raise ToolError(no_template_help(model))
    if not isinstance(cfg.get("print"), dict):            # absent or null
        cfg["print"] = {}
    if not isinstance(cfg.get("parts"), dict):
        cfg["parts"] = {}
    pr = cfg["print"]
    for item in args.set:
        key, sep, value = item.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not sep:
            raise ToolError(f"--set needs KEY=VALUE, not {item!r}")
        if key == "template":
            if value.lower() in ("", "default"):
                cfg.pop("template", None)
            else:
                cfg["template"] = value
            continue
        if key not in MENU_PRINT_KEYS:
            raise ToolError(f"--set: unknown key {key!r} (use template, {', '.join(MENU_PRINT_KEYS)})")
        if value.lower() in ("", "template"):
            pr.pop(key, None)
        elif key in ("check", "open"):
            if value.lower() not in YES:
                raise ToolError(f"--set {key}: use yes or no, not {value!r}")
            pr[key] = YES[value.lower()]
        elif key in ("support", "brim"):
            if value.lower() not in MODE_WORDS:
                raise ToolError(f"--set {key}: use auto, on or off, not {value!r}")
            pr[key] = MODE_WORDS[value.lower()]
        elif key == "colours":                            # template is the default: removed above, not saved
            if value.lower() not in ("model", "manual", "mix"):
                raise ToolError(f"--set colours: use model, manual, mix or template, not {value!r}")
            pr[key] = value.lower()
        elif key == "mix":                                # colour mixing mode: CMYKW (PLA Palette), CMYW, RYBW
            if value.upper() not in mix_recipes():
                raise ToolError(f"--set mix: use {', '.join(mix_recipes()) or '-'}, not {value!r}")
            pr[key] = value.upper()
        elif key == "colour":                             # manual: the project's colour (a name or #RRGGBB)
            parse_colour(value)
            pr[key] = value
        elif key == "nozzle":
            if value.lower() not in NOZZLE_WORDS:
                raise ToolError(f"--set nozzle: use auto, left or right, not {value!r}")
            pr[key] = NOZZLE_WORDS[value.lower()]
        elif key in ("duplicates", "max_plates"):         # 1 duplicate / 0 plates: the default, so not saved
            n = whole_number(value, f"--set {key}", *((1, MAX_COPIES) if key == "duplicates" else (0, MAX_PLATES)))
            if n == (1 if key == "duplicates" else 0):
                pr.pop(key, None)
            else:
                pr[key] = n
        else:
            pr[key] = value
    names = {n.lower(): n for n, *_ in printable_parts(ws)}
    hints = cfg["parts"]

    def part(n: str) -> str:
        if n.strip().lower() not in names:
            raise ToolError(f"unknown part {n!r}; printable parts: {', '.join(names.values())}")
        return names[n.strip().lower()]

    both = {part(n) for n in args.skip} & {part(n) for n in args.include}
    if both:
        raise ToolError(f"--skip and --include both name {', '.join(sorted(both))}: choose one")
    if args.include_all:
        for h in hints.values():
            if isinstance(h, dict):
                h.pop("skip", None)
    for n in args.include:
        (hints.get(part(n)) or {}).pop("skip", None)
    for n in args.skip:
        hints.setdefault(part(n), {})["skip"] = True
    for item in args.copies:                              # PART=N: this part N times (times the duplicates)
        name, sep, value = item.rpartition("=")           # the last '=': a part name may hold one
        if not sep:
            raise ToolError(f"--copies needs PART=N, not {item!r}")
        n = whole_number(value.strip(), f"--copies {name.strip()}", 1, MAX_COPIES)
        h = hints.setdefault(part(name), {})
        if n == 1:
            h.pop("copies", None)
        else:
            h["copies"] = n
    for item in args.filament:                            # PART=N or PART=auto: the filament this part prints with
        name, sep, value = item.rpartition("=")
        if not sep:
            raise ToolError(f"--filament needs PART=N or PART=auto, not {item!r}")
        h = hints.setdefault(part(name), {})
        if value.strip().lower() == "auto":
            h.pop("filament", None)                       # by colour (see assign_filament)
        else:
            h["filament"] = whole_number(value.strip(), f"--filament {name.strip()}", 1, MAX_FILAMENTS)
    for item in args.colour:                              # PART=red / #1F4FCC / auto: the colour this part prints in
        name, sep, value = item.rpartition("=")
        if not sep:
            raise ToolError(f"--colour needs PART=COLOUR or PART=auto, not {item!r}")
        h = hints.setdefault(part(name), {})
        value = value.strip()
        try:
            rgb = parse_colour(value)
        except ToolError as e:
            raise ToolError(f"--colour {name.strip()}: {e}") from None
        if rgb is None:
            h.pop("colour", None)                         # the model's own colour again
        else:
            h["colour"] = value.lower() if value.lower() in PALETTE else srgb_hex(rgb)
    for n in [n for n, h in hints.items() if h == {} and n not in old_empty]:
        hints.pop(n)                                      # only entries this run emptied
    for k in ("print", "parts"):
        if cfg.get(k) == {} and k not in had:
            cfg.pop(k)
    validate_config(cfg)
    using_new = new_tpl is not None and cfg.get("template") == new_tpl[1]
    tpl_path = new_tpl[0] if using_new else resolve_template(ws, cfg.get("template"))
    t = load_template(tpl_path)
    if args.printer and isinstance(cfg.get("print"), dict):   # another printer: drop a saved profile it does not have
        pp = str(t.settings.get("printer_settings_id") or "")
        given = {s.partition("=")[0].strip().lower() for s in args.set}   # chosen in this command: keep (or fail)
        saved = cfg["print"].get("nozzle_size")
        if saved and "nozzle_size" not in given and f"{_number(saved):g}" not in \
                [template_nozzle(t), *nozzle_sizes(template_printer(t))]:
            print(f"nozzle size {cfg['print'].pop('nozzle_size')!r} does not fit the {template_printer(t)}: "
                  f"the template's is used", file=sys.stderr)
        for key, match in (("process", match_process), ("material", match_filament)):
            if cfg["print"].get(key) and key not in given:
                try:
                    match(str(cfg["print"][key]), pp)
                except ToolError:
                    print(f"{key} {cfg['print'].pop(key)!r} does not exist for the {pp}: the template's is used",
                          file=sys.stderr)
    apply_print_settings(t, cfg.get("print") or {})       # checked with the template it will use
    if t.material:                                        # saved as its exact short name: 'petg basic' -> 'PETG Basic'
        cfg["print"]["material"] = t.material
    if t.process:
        cfg["print"]["process"] = t.process
    if not printed_names(ws, cfg):
        raise ToolError(tr("e.no_parts"))
    if not save:
        if using_new:
            cfg["template"] = str(Path(new_tpl[0]).resolve())   # an absolute path: resolve_template takes it as is
        return cfg
    if new_tpl:                                           # only now, with every choice valid, add the template
        dest = menu.install_template(me, new_tpl[0], new_tpl[1], overwrite=args.overwrite)
        print(f"template saved: {dest}", file=sys.stderr)
    menu.save(ws, cfg)
    return cfg


def main(argv=None) -> int:
    ap = _parser()
    bare = argv is None and len(sys.argv) == 1
    args = ap.parse_args(argv)
    if argv is None:                                      # once per start (the form calls main again to build)
        clean_old_temp()
    return _main(args, argv, bare)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="SOMA model -> Bambu Studio project with automatic print settings. "
                                 "Without options in a terminal: the form.")
    ap.add_argument("--template", help="template name or Bambu Studio project with printer, filament and process")
    ap.add_argument("--out", default="output/bambu", help="target folder (default output/bambu)")
    ap.add_argument("--selftest", action="store_true",
                    help="after a Bambu Studio update: check its files, the templates, a test slice and the copied rules")
    ap.add_argument("--selftest-all", action="store_true", help="like --selftest, with a test slice for every template")
    ap.add_argument("--check", action="store_true", help="slice with Bambu Studio's command line to verify")
    ap.add_argument("--open", action="store_true", help="open the result in Bambu Studio")
    ap.add_argument("--menu", action="store_true", help="show the form (default when started without options)")
    ap.add_argument("--form", action="store_true", help="show the form (same as --menu)")
    ap.add_argument("--wait", action="store_true",
                    help="with the form: wait for a key at the end when it was not made (own window)")
    ap.add_argument("--own-console", action="store_true", help=argparse.SUPPRESS)   # in the window _own_window opened
    ap.add_argument("--env-file", help=argparse.SUPPRESS)  # variables sent by _own_window, read by _take_env_file()
    ap.add_argument("--pid-file", help=argparse.SUPPRESS)  # with --own-console: where _own_window waits for the id
    ap.add_argument("--saved", action="store_true",
                    help="make the project with the saved choices (check and open as saved), no form")
    ap.add_argument("--recent", action="store_true",
                    help="list the projects Bambu Studio wrote when sending a print, numbered for --import-recent")
    ap.add_argument("--models", action="store_true",
                    help="print the SOMA models as 'name | folder', newest first; works anywhere")
    ap.add_argument("--restore-studio-setting", action="store_true",
                    help="switch Bambu Studio's 'single instance' off again if this tool switched it on "
                         "(uninstall.cmd does this)")
    ap.add_argument("--warm-profiles", action="store_true",
                    help="read Bambu Studio's profiles into the cache now (install.cmd does this; about 2 minutes)")
    ap.add_argument("--status", action="store_true",
                    help="print whether Bambu Studio is installed and up to date as JSON; also outside a model folder")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="save a choice in bambu.json: template, layer_height, infill, walls, support, brim, check, "
                         "open (empty value or 'template' = as in the template)")
    ap.add_argument("--skip", action="append", default=[], metavar="PART", help="do not print this part (saved)")
    ap.add_argument("--include", action="append", default=[], metavar="PART", help="print this part again (saved)")
    ap.add_argument("--include-all", action="store_true", help="print every part again (saved)")
    ap.add_argument("--copies", action="append", default=[], metavar="PART=N",
                    help="print this part N times, times --set duplicates (saved; N=1 removes it)")
    ap.add_argument("--filament", action="append", default=[], metavar="PART=N",
                    help="print this part with filament N of the template (saved; PART=auto: the filament closest "
                         "to the part's colour, the default)")
    ap.add_argument("--colour", "--color", action="append", default=[], metavar="PART=COLOUR",
                    help="print this part in this colour instead of its colour in the model: a name (red, dark grey) "
                         "or #RRGGBB (saved; PART=auto: the model's colour again). With --set colours=model the "
                         "template's filaments get the parts' colours")
    ap.add_argument("--import-template", metavar="3MF", help="add a Bambu Studio project as a template and use it")
    ap.add_argument("--import-recent", type=int, metavar="N",
                    help="like --import-template, with the N-th recently sent print (numbers as in --recent)")
    ap.add_argument("--printer", metavar="MODEL",
                    help="use this printer's template (e.g. 'H2D Pro'); a recently sent print to it becomes one")
    ap.add_argument("--new-filament", action="store_true",
                    help="with --printer: explain how to make a template for another filament on it (saves nothing)")
    ap.add_argument("--name", help="name for --import-template (default: printer-filament-process)")
    ap.add_argument("--overwrite", action="store_true", help="--import-template may replace a template")
    ap.add_argument("--no-build", action="store_true", help="only save the choices, do not make the project")
    ap.add_argument("--preview", action="store_true",
                    help="with the other options: make the project in a temporary folder and slice it, then print "
                         "plates, print time and filament; nothing is saved")
    return ap


def _is_model(folder: Path) -> bool:
    """A SOMA model folder: model.py and .soma."""
    return (folder / "model.py").exists() and (folder / ".soma").is_dir()


def _soma_project() -> Path | None:
    """The model SOMA has open, from SOMA_PROJECT (SOMA sets it in its terminal); None outside SOMA or when it is
    not a model folder."""
    value = os.environ.get("SOMA_PROJECT", "").strip().strip('"')
    if not value:
        return None
    try:
        folder = Path(value).resolve()
    except (OSError, ValueError):
        return None
    return folder if folder.is_absolute() and _is_model(folder) else None


def _main(args, argv, bare: bool) -> int:
    if argv is None:                                      # names, paths and reports with accents, also in a pipe
        for stream in (sys.stdout, sys.stderr):           # (python -I ignores PYTHONIOENCODING)
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        import orientr_banner                             # Windows' own console: ✅ ⚠ ◆ as symbols its fonts have
        orientr_banner.plain_symbols()
    ws = Path.cwd()
    in_model = _is_model(ws)
    soma = _soma_project()
    if not in_model and soma:                             # in SOMA's terminal, but not in the model's folder
        os.chdir(soma)                                    # (2026-11-24, tester: the model list instead of the form):
        ws, in_model = soma, True                         # the model SOMA has open; everything below uses its folder
    if args.selftest or args.selftest_all:                # after a Studio update: everything that may have broken
        return selftest(args.selftest_all, args.template)
    if args.status:                                       # the status lines as JSON, also outside a model folder
        try:
            t = load_template(resolve_template(ws, read_config(ws).get("template")) if in_model else DEFAULT_TEMPLATE)
        except Exception:                                 # no or broken template: still report Bambu Studio itself
            t = None
        print(json.dumps(bambu_status(t), ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.warm_profiles:
        return warm_profiles()
    if args.restore_studio_setting:
        result = restore_single_instance()
        print(result)
        return 0 if result in ("restored", "untouched", "already-off") else 1
    if args.recent:
        for i, (p, text) in enumerate(_menu().recent_prints(sys.modules[__name__]), 1):
            print(f"{i:>2}  {text}\n    {p}")
        return 0
    if args.models:
        for name, folder in soma_models():
            print(f"{name} | {folder}")
        return 0
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    if args.own_console:                                  # in the window _own_window opened
        own_console_start(args.pid_file)
    if not in_model:
        if (bare or args.own_console) and tty:            # `orientr` anywhere: choose a model, then its form
            if bare and _own_window_wanted():             # typed in a terminal: both in a window of the form's size
                return open_own_window(None)
            import orientr_form
            rc = orientr_form.choose_model(sys.modules[__name__])
            return 0 if args.own_console else rc          # 0: Windows Terminal closes the tab (see below)
        raise ToolError(tr("e.not_model"))
    if bare and tty and _own_window_wanted():             # `orientr` typed in a terminal: the form in its own window
        return open_own_window(ws)
    if args.form or args.menu or (bare and tty):
        import orientr_form                                 # next to this file; it calls main() again with the choices
        rc = orientr_form.run(ws, sys.modules[__name__], wait_at_end=args.wait)
        # in its own window: exit code 0 lets Windows Terminal close the tab (it keeps a tab open after any other code)
        return 0 if args.own_console else rc
    # every command-line run left here may read the profiles first; stderr: stdout may be a report or JSON
    announce_profiles(lambda text: print(text, file=sys.stderr))
    if args.preview:                                      # the form's Preview, also from the command line
        print("\n".join(preview_lines(preview(ws, args))))
        return 0
    cfg = read_config(ws)
    if args.saved:                                        # again with the saved choices, no form
        pr = cfg.get("print") or {}
        from orientr_i18n import setting
        if pr.get("open", True) and setting("prestart", False) is True:   # "Background Bambu Studio" switched on:
            prestart_studio()                                             # it starts while the project is made
        return build(ws, cfg, args.template, args.out, True, bool(pr.get("open", True)))   # always a test slice
    if (args.import_template or args.import_recent or args.printer or args.new_filament or args.set or args.skip
            or args.include or args.include_all or args.copies or args.filament or args.colour):
        cfg = change_config(ws, cfg, args)
    if args.no_build:
        return 0
    check, open_, template = args.check, args.open, args.template
    return build(ws, cfg, template, args.out, check, open_)


def preview(ws: Path, args, tick=None) -> dict:
    """The form's Preview: the project with these choices (the same options as "Generate"), made in a temporary
    folder and sliced by Bambu Studio's command line. bambu.json, the output folder and the recent printers stay as
    they are (2026-11-19: plates, print time and filament before making it). tick(seconds) is called
    while Bambu Studio slices; when it returns True the slicing stops (PreviewStopped)."""
    import contextlib
    import io
    cfg = read_config(ws)
    quiet = io.StringIO()                                 # the form owns the screen: the tool's own lines stay out
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        if (args.import_template or args.import_recent or args.printer or args.set or args.skip or args.include
                or args.include_all or args.copies or args.filament or args.colour):
            cfg = change_config(ws, cfg, args, save=False)
    with orientr_tempdir() as td:
        td = Path(td)
        level, skip, n = None, frozenset(), 0
        while True:
            with contextlib.redirect_stdout(quiet):
                out, plates, hosts, t, title = make_project(ws, cfg, args.template, td, level, skip)
            n += 1
            try:
                res = slice_stats(out, td / f"sliced{n}", tick)
                break
            except ToolError:                             # as build(): a tight layout Bambu Studio refuses (many
                nxt = retry_layout(t, skip)               # duplicates: "G-code conflicts"): the other nozzle's area,
                if nxt is None:                           # or a roomier layout
                    raise
                level, skip = nxt
    for i, (_, items) in enumerate(plates):
        if i < len(res["plates"]):
            res["plates"][i]["parts"] = [n for p, *_ in items for n in [p.name] + [e.name for e, _ in p.extras]]
    res["title"] = title
    # the filament profiles by number, for the result (2026-11-22: which filament): 'PLA Basic', 'ASA'
    res["names"] = [filament_short(n) for n in t.settings.get("filament_settings_id") or []]
    # and Bambu Lab's name of each filament's colour when the tool made them (2026-11-23: "Turquoise", not "blue")
    res["colour_names"] = [official_name(n) for n in t.colour_names]
    res["warnings"] = list(dict.fromkeys(f"{q.copy_of or q.name}: {w}" for p in hosts
                                         for q in [p] + [e for e, _ in p.extras] for w in q.warnings))
    return res


def duration(seconds: float) -> str:
    """8 h 15 min, 45 min, < 1 min."""
    m = int(round(seconds / 60))
    if m < 1:
        return "< 1 min"
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def preview_lines(res: dict) -> list[str]:
    """The Preview as plain lines (the form adds colours): totals, per plate when there are several, warnings."""
    L = [f"{tr('pv.plates'):<14}{len(res['plates'])}",
         f"{tr('pv.time'):<14}{duration(res['s'])}",
         f"{tr('pv.filament'):<14}{res['g']:.1f} g  ({res['m']:.2f} m)"]
    names = res.get("names") or []

    def name(f: dict) -> str:                             # its profile name, else the type Bambu Studio reports
        return names[f["id"] - 1] if 0 < f["id"] <= len(names) and names[f["id"] - 1] else f["type"]
    if len(res["filaments"]) == 1:                        # which filament (2026-11-22)
        L[-1] += f"  ·  {name(res['filaments'][0])}"
    if res.get("cost"):
        L.append(f"{tr('pv.cost'):<14}{money(res['cost'])}")
    if len(res["filaments"]) > 1:                         # per filament: number, name and colour (in words)
        sold = res.get("colour_names") or []

        def colour(f: dict) -> str:                       # Bambu's name of the colour, else the nearest named one
            if 0 < f["id"] <= len(sold) and sold[f["id"] - 1]:
                return sold[f["id"] - 1]
            rgb = hex_srgb(f["color"])
            return cap(tr("col." + color_name(rgb))) if rgb else str(f["color"])
        L += [f"{'':<14}{f['id']} {name(f)}, {colour(f)}: {f['g']:.1f} g  ({f['m']:.2f} m)" for f in res["filaments"]]
    if len(res["plates"]) > 1:
        L.append("")
        for p in res["plates"]:
            L.append(f"{tr('pv.plate', n=p['n']):<10}{duration(p['s']):>12}   {p['g']:>7.1f} g   {p['m']:>6.2f} m   "
                     + tr("pv.part" if len(p.get("parts") or []) == 1 else "pv.parts", n=len(p.get("parts") or [])))
    warns = [tr("pv.warn", n=p["n"], msg=cap(p["warning"])) for p in res["plates"] if p["warning"]]
    warns += [tr("pv.part_warn", msg=cap(w)) for w in res.get("warnings") or []]
    if res.get("rules_note"):
        warns.append(tr("pv.part_warn", msg=res["rules_note"]))
    # Studio's standard warnings for the filament: once, by their short title (the report has the full text)
    std = list(dict.fromkeys(short_warning(m) for p in res["plates"] for m in p.get("standard") or []))
    if std:
        warns.append(tr("pv.standard", msgs="; ".join(std)))
    return L + ([""] + warns if warns else [])


def short_warning(msg: str) -> str:
    """A Bambu Studio warning by its title: the words before its first colon ('Filament Shrinkage'), else its first
    sentence, at most 5 words."""
    head = msg.split(":", 1)[0] if ":" in msg[:60] else re.split(r"(?<=[.!?])\s", msg, maxsplit=1)[0]
    words = head.rstrip(".").split()
    return " ".join(words[:5]) + (" …" if len(words) > 5 else "")


def retry_layout(t: Template, skip: frozenset) -> tuple | None:
    """After Bambu Studio refused a layout: (level, skip) to make it again with, or None when nothing is left. With
    Nozzle auto first the same level without that nozzle's area (2026-11-23: left and right tied, left was refused,
    right sliced), then a roomier level with every area again. Parts nested in another part's opening (2026-11-23):
    first the same layout without nesting."""
    if getattr(t, "nested", False) and "no-nest" not in skip:
        return t.level, skip | {"no-nest"}
    if t.nozzle is not None and t.nozzle_mode == "auto" and len(t.nozzle_boxes) >= 2 and t.nozzle not in skip:
        return t.level, skip | {t.nozzle}
    if t.level > 0:
        return t.level - 1, frozenset(s for s in skip if s == "no-nest")   # a refused nesting stays off
    return None


def make_project(ws: Path, cfg: dict, template: str | None, out_dir: Path, level: int | None = None,
                 skip_nozzles: frozenset = frozenset()) -> tuple:
    """Every part oriented, set and placed on plates, written as <out_dir>/<model>.3mf; (out, plates, hosts,
    template, title). The report, the check and opening it are build()'s. level: see pack(); None picks the
    least roomy layout that needs the fewest plates (see pack_auto)."""
    validate_config(cfg)
    t = load_template(resolve_template(ws, template or cfg.get("template")))
    pr = dict(cfg.get("print") or {})
    recipes = None
    if pr.get("colours") == "mix":                        # colour mixing: the mode's own filament (2026-11-23)
        modes = mix_recipes()
        mode = str(pr.get("mix") or "CMYKW").upper()
        if mode not in modes:
            raise ToolError(tr("e.mix_mode", mode=mode, modes=", ".join(modes) or "-"))
        pr["material"], recipes = modes[mode]
    apply_print_settings(t, pr)
    if recipes is not None and t.filaments == 1 and hotends(t) < 2:
        raise ToolError(tr("e.mix_printer", printer=template_printer(t).replace("Bambu Lab ", "")))
    bed_xy = (t.bed_x[1] - t.bed_x[0] - 2 * MARGIN, t.bed_y[1] - t.bed_y[0] - 2 * MARGIN)
    hints = cfg.get("parts") or {}
    skipped = {n for n, h in hints.items() if h.get("skip")}
    with orientr_tempdir() as td:
        parts = load_model(ws, hints, Path(td))
    by_name = {p.name: p for p in parts}
    if t.colour_mode == "model" and t.filaments > 1:      # the template's filaments get the parts' colours
        names = set(colour_parts(((p.name, p.hint) for p in parts), skipped))
        recolour(t, model_colours([p.color for p in parts if p.name in names], t.filaments))
    elif t.colour_mode in ("model", "manual") and t.filaments == 1:
        # one filament per colour, made here from the printer's own template (2026-11-23: no colour template needed);
        # manual: every part the project's colour unless it has its own. A merged part keeps the one it has in the
        # model (it is merged to print in another colour: a lettering in the project's colour would vanish)
        if t.colour_mode == "manual":
            base = parse_colour((cfg.get("print") or {}).get("colour")) or hex_srgb((t.colours or ["#FFFFFF"])[0])
            for p in parts:
                if not p.own_colour and not p.hint.get("merge_into"):
                    p.color = base or (1.0, 1.0, 1.0)
        # every part by its colour, merged ones too: a filament number from bambu.json means nothing here (the
        # filaments are the colours), 2026-11-23: a merged lettering with "filament": 2 got whatever colour came 2nd
        names = set(colour_parts(by_colour((p.name, p.hint) for p in parts), skipped))
        hexes, sold = slot_colours([p.color for p in parts if p.name in names] or [parts[0].color],
                                   official_colours(str((t.settings.get("filament_ids") or [""])[0])))
        expand_filaments(t, hexes)
        t.colour_names = sold
    elif recipes is not None and t.filaments == 1:
        # colour mixing (2026-11-23): the base colours to load, and Bambu's measured mixes of them for the rest
        names = set(colour_parts(by_colour((p.name, p.hint) for p in parts), skipped))
        phys, mixes, mix_names = mix_plan([p.color for p in parts if p.name in names] or [parts[0].color], recipes)
        expand_filaments(t, phys, mixes)
        t.colour_names, t.mixing = mix_names, True
    hosts = []
    for p in parts:
        tgt = p.hint.get("merge_into")
        if tgt:
            if tgt == p.name:
                raise ToolError(f'{p.name}: "merge_into" names the part itself')
            if tgt in skipped:
                print(f"skipped: {p.name} (it is printed inside {tgt}, which is not printed)")
                continue
            if tgt not in by_name:
                raise ToolError(f'{p.name}: "merge_into" names an unknown or skipped part {tgt!r}')
            if by_name[tgt].hint.get("merge_into"):
                raise ToolError(f'{p.name}: "merge_into" {tgt!r}, which is itself merged into another part; '
                                "merge every part directly into the main part")
            want = "auto" if t.generated else p.hint.get("filament", 2)   # its own filament, 2 unless it says
            fil = nearest_filament(p.color, colour_choices(t), not t.generated) if want in ("", "auto") \
                else int(want)                            # "auto": by colour
            if fil < 1:
                raise ToolError(f'{p.name}: "filament" must be 1 or more')
            if fil > t.filaments:
                p.warnings.append(tr("w.filament", n=fil, have=t.filaments))
                fil = 1
            by_name[tgt].extras.append((p, fil))
        else:
            hosts.append(p)
    for p in hosts:
        assign_filament(p, t)                         # before decide(): the brim looks at the filament's warping
        p.an = choose_orientation(p.mesh, p.hint, bed_xy, t.bed_h, t.slope, t.first_layer / 2 + 1e-6)
        if p.extras:                              # size, fit and plate space of the whole merged object
            own = p.mesh.verts @ p.an.rot.T
            allv = np.vstack([own] + [e.mesh.verts @ p.an.rot.T for e, _ in p.extras])
            size = np.ptp(allv, axis=0)
            p.an.size_xy, p.an.height = (float(size[0]), float(size[1])), float(size[2])
            p.an.fits = bool(size[2] <= t.bed_h and (
                (size[0] <= bed_xy[0] and size[1] <= bed_xy[1]) or (size[1] <= bed_xy[0] and size[0] <= bed_xy[1])))
            if allv[:, 2].min() < own[:, 2].min() - 0.01:
                p.warnings.append(tr("w.lift"))
        decide(p, t)
        for e, _ in p.extras:                     # merged parts follow their host
            e.an = p.an
    if not hosts:
        raise ToolError(tr("e.no_parts"))
    # a part that does not fit the printer: stop here with a clear message (2026-11-22: Bambu Studio
    # refused such a project with "One of the plate is empty or has no object fully inside it", code -50)
    big = [p for p in hosts if p.too_big]
    if big:
        raise ToolError(tr("e.no_fit", printer=template_printer(t).replace("Bambu Lab ", ""),
                           parts="; ".join(f"{p.name} {p.too_big}" for p in big)))
    # duplicates (2026-11-21): the whole set t.duplicates times, and each part its own "copies" times
    # that; a copy is packed like any part
    counts = [(p, t.duplicates * whole_number(p.hint.get("copies") or 1, f'{p.name}: "copies"', 1, MAX_COPIES))
              for p in hosts]
    check_volume(counts)                                  # too big a project: a message before anything is packed
    placed = []
    taken = {q.name for q in parts}                       # a copy "Knob (2)" must not take a real part's name: the
    for p, n in counts:                                   # slice check and the report find objects by name
        placed.append(p)
        i = 1
        for _ in range(n - 1):
            i += 1
            while f"{p.name} ({i})" in taken:
                i += 1
            taken.add(f"{p.name} ({i})")
            placed.append(_copy_part(p, f"{p.name} ({i})"))
    try:
        plates, t.level = pack_auto(placed, t, level, skip_nozzles)   # with 2+ plates the tighter one is tried too
        if t.max_plates and len(plates) > t.max_plates:   # 2026-11-21: tighter first, then refuse
            raise ToolError(tr("e.max_plates", need=len(plates), max=t.max_plates, n=len(placed)))
        hosts = placed                                    # the check and the warnings cover the copies too
        title = json.loads((ws / ".soma" / "project.json").read_text(encoding="utf-8")).get("name", ws.name)
        safe = re.sub(r'[<>:"/\\|?*]', "_", title)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{safe}.3mf"
        write_3mf(out, plates, t, title)
    except MemoryError:                                   # the guard's limits were not enough on this PC
        raise ToolError(tr("e.memory", n=len(placed))) from None
    return out, plates, hosts, t, title


def check_volume(counts: list) -> None:
    """Refuse a project too big for one Bambu Studio project (2026-11-22: more duplicates, but no crashes):
    `counts` is [(part, how many objects of it)], a part counted with the parts merged into it."""
    objects = sum(n for _, n in counts)
    if objects > MAX_OBJECTS:
        raise ToolError(tr("e.too_many", n=objects, max=MAX_OBJECTS))
    tris = sum(n * (len(p.mesh.faces) + sum(len(e.mesh.faces) for e, _ in p.extras)) for p, n in counts)
    if tris > MAX_TRIANGLES:
        raise ToolError(tr("e.too_big", n=objects, tris=f"{tris / 1e6:.1f}", max=f"{MAX_TRIANGLES / 1e6:g}"))


GITIGNORE_TEXT = ("# Orientr: the project, its report and pictures are made again by every Generate, so SOMA's\n"
                  "# version history leaves them out (about 1 MB each time).\n*\n")


def keep_out_of_history(out_dir: Path) -> None:
    """A .gitignore in the output folder (2026-11-22: SOMA committed the .3mf, the pictures and the report
    of every Generate into its version history). Files the history already has stay in it until they are taken out
    with `git rm --cached`; that is the user's choice, the tool does not touch SOMA's git."""
    gi = out_dir / ".gitignore"
    try:                                                  # the tool's old name (Bambu Generator) in its own text:
        old = gi.read_text(encoding="utf-8") if gi.exists() else None   # renamed (2026-11-23); a changed file stays
    except (OSError, UnicodeDecodeError):
        old = ""
    if old is None or (old != GITIGNORE_TEXT and old.replace("# Bambu Generator:", "# Orientr:", 1) == GITIGNORE_TEXT):
        try:
            gi.write_text(GITIGNORE_TEXT, encoding="utf-8")
        except OSError:
            pass                                          # only the history grows: nothing to stop the build for
    try:                                                  # written by versions before 0.0.0 for the old /bambu skill
        (out_dir / "last-run.json").unlink(missing_ok=True)
    except OSError:
        pass


def build(ws: Path, cfg: dict, template: str | None, out_rel: str, check: bool, open_: bool) -> int:
    # made and checked in a folder of its own, then moved to out_rel: a tight layout that fails, or a step back that
    # then needs too many plates (max_plates), never replaces the project already there (review 2026-11-22)
    with orientr_tempdir("build") as stage:
        stage = Path(stage)
        # without the slice check only the safe layout (level 0) is used: a tighter one is kept only when it sliced
        # clean
        out, plates, hosts, t, title = make_project(ws, cfg, template, stage, None if check else 0)
        safe = out.stem
        remember_printer(str(t.settings.get("printer_model") or ""))
        checks = []
        if check:
            expected = {p.name: dict(p.settings) for p in hosts}
            checks = check_with_bambu(out, plates, expected)
            skip = frozenset()
            # Bambu Studio objects to the layout: the other nozzle's area (Nozzle auto), else a roomier level
            while not CHECK.clean and (nxt := retry_layout(t, skip)) is not None:
                level, skip = nxt
                nozzles = sorted(s for s in skip if isinstance(s, int))
                print(f"note: layout level {t.level}" + (f", nozzle {t.nozzle}" if t.nozzle else "")
                      + f" did not slice clean, trying level {level}"
                      + (f" without nozzle {', '.join(map(str, nozzles))}" if nozzles else "")
                      + (" without parts in openings" if "no-nest" in skip else ""))
                for old in stage.glob(f"{safe}-plate*.png"):
                    old.unlink()
                out, plates, hosts, t, title = make_project(ws, cfg, template, stage, level, skip)
                expected = {p.name: dict(p.settings) for p in hosts}
                checks = check_with_bambu(out, plates, expected)
        notices = template_age(t)
        for n in notices:
            print(f"warning: {n}")
        out_dir = ws / out_rel
        rep = report(plates, t, out_dir / out.name, title, checks, notices)
        (stage / f"{safe}-print.md").write_text(rep, encoding="utf-8")
        out_dir.mkdir(parents=True, exist_ok=True)
        keep_out_of_history(out_dir)
        for old in out_dir.glob(f"{safe}-plate*.png"):    # pictures of an earlier run with more plates
            old.unlink(missing_ok=True)
        for f in sorted(stage.iterdir(), key=lambda f: f.suffix != ".3mf"):   # the project first: when it is open
            try:                                                                # in Studio, nothing else changes
                shutil.copyfile(f, out_dir / f.name)
            except PermissionError:
                raise ToolError(tr("e.locked", path=out_dir / f.name)) from None
        out = out_dir / out.name
    print(rep)
    print("\n" + tr("run.written", out=out, report=out_dir / (safe + "-print.md")))
    if open_:
        if Path(BAMBU_EXE).exists():
            stop_hiding_studio()                          # first: the guard must not close it during the hand-over
            try:
                start_studio(str(out), hidden=False)      # the hidden prestarted Studio shows itself with it
            except OSError:
                undo_stop_hiding_studio()                 # not handed over: the guard closes it after the form
                raise
        else:
            os.startfile(out)  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ToolError as e:
        print(f"orientr: {e}", file=sys.stderr)
        start_error(str(e))
        sys.exit(2)
