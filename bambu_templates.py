# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""Template helpers of Orientr: describe, list, import and save. The tool module is passed in (sb) to share
its classes and rules; only the standard library here."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path


def hex_rgb(h: str) -> tuple:
    h = re.sub(r"[^0-9A-Fa-f]", "", str(h or ""))[:6].ljust(6, "9")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def short(name: str) -> str:
    return re.sub(r"\s*@BBL.*$", "", str(name))


def describe(sb, path: Path) -> tuple[bool, str, object]:
    """(valid, one-line summary, Template or None) of a template file."""
    try:
        t = sb.load_template(path)
    except sb.ToolError as e:
        return False, str(e).splitlines()[0], None
    s = t.settings
    cols = s.get("filament_colour") or []
    fils = [f"{short(f)} ({sb.color_name(hex_rgb(cols[i] if i < len(cols) else ''))})"
            for i, f in enumerate(s.get("filament_settings_id") or [])]
    ver = t.app.split("-", 1)[-1]
    return True, f"{short(s.get('printer_settings_id'))} | {' + '.join(fils)} | {short(s.get('print_settings_id'))}" \
                 f"  [Bambu Studio {ver}]", t


def template_files(sb, ws: Path, current: str | None = None) -> list[tuple[str, Path]]:
    """(spec as stored in bambu.json, path): the tool's templates and the user's own (USER_TEMPLATES, which win over a
    tool template of the same name), the model's own one, and the current template when it is a file at its own path
    (e.g. inputs/x1c.3mf)."""
    names = {p.stem for d in (sb.TOOL_DIR / "templates", sb.USER_TEMPLATES) for p in d.glob("*.3mf")}
    out = [(n, sb.template_path(n)) for n in sorted(names, key=str.lower)]
    own = ws / "inputs" / "bambu_template.3mf"
    if own.exists():
        out.append(("inputs/bambu_template.3mf", own))
    if current:
        cur = sb.resolve_template(ws, current)
        if cur.exists() and cur.resolve() not in {p.resolve() for _, p in out}:
            out.append((current, cur))
    return out


def recent_prints(sb, limit: int = 8) -> list[tuple[Path, str]]:
    """Projects Bambu Studio wrote when sending a print (newest first, one per printer/filament/process/colour)."""
    base = Path(os.environ.get("TEMP", "")) / "bamboo_model"
    if not base.is_dir():
        return []

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    out, seen = [], set()
    for f in sorted(base.rglob("*.3mf"), key=mtime, reverse=True)[:60]:
        ok, text, t = describe(sb, f)
        if not ok:
            continue
        key = (t.settings.get("printer_settings_id"), tuple(t.settings.get("filament_settings_id") or []),
               t.settings.get("print_settings_id"), tuple(t.settings.get("filament_colour") or []))
        if key in seen:
            continue
        seen.add(key)
        out.append((f, f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime(f)))}  {text}"))
        if len(out) >= limit:
            break
    return out


def default_name(t) -> str:
    """'Bambu-Lab-H2D-0.4-nozzle-Bambu-PLA-Basic-0.20mm-Standard' from a template's printer, filament and process."""
    s = t.settings
    return re.sub(r"[^A-Za-z0-9.+-]+", "-", f"{short(s.get('printer_settings_id'))} "
                  f"{short((s.get('filament_settings_id') or ['?'])[0])} {short(s.get('print_settings_id'))}"
                  ).strip("-")


def clean_name(name: str, default: str) -> str:
    """A plain template name: no path characters, no (repeated) .3mf, no trailing dots or spaces."""
    name = re.sub(r'[<>:"/\\|?*\']', "-", name or "")   # also no apostrophe: names go into quoted arguments
    while True:
        stripped = re.sub(r"\.3mf$", "", name.strip(" ."), flags=re.I)   # "PLA.3mf." and "a.3mf.3mf" too
        if stripped == name:
            break
        name = stripped
    return name or default


def install_template(sb, src: Path, name: str, overwrite: bool = False) -> Path:
    """Copy a valid Bambu Studio project into the user's templates folder as <name>.3mf, without the account number."""
    ok, text, _ = describe(sb, src)
    if not ok:
        raise sb.ToolError(f"not usable as a template: {text}")
    dest = sb.USER_TEMPLATES / f"{name}.3mf"
    if dest.exists() and not overwrite:
        raise sb.ToolError(f"template {dest.name} already exists (choose another name)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    sb.strip_personal(dest)
    return dest


def save(ws: Path, cfg: dict) -> None:
    """Write bambu.json with every key it had, the choices updated (message on stderr: stdout may be JSON)."""
    import os
    import tempfile
    from orientr_i18n import t
    # written whole, then swapped in: a crash or a full disk halfway never leaves an empty bambu.json (review 2026-11-22)
    fd, tmp = tempfile.mkstemp(prefix="bambu.json.", suffix=".tmp", dir=ws)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, ws / "bambu.json")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print(f"  {t('msg.saved', path=ws / 'bambu.json')}\n", file=sys.stderr)
