# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""The full-screen form of Orientr: every choice on one screen, in the Windows console.

up/down picks a field, left/right changes its value, Enter opens the full list (type to search) or presses a button.
Filament and process lists follow the printer at once. "Generate" hands the choices to orientr as options
(--printer, --set, --skip, --include), so the checks, saving and building are the tool's own.
Standard library only (msvcrt for the keys, ANSI for colours): nothing to install.
"""
import os
import re
import shutil
import sys
import textwrap
import time
from pathlib import Path

from orientr_i18n import LANGS, cap, language, save_setting, set_language, setting, t

ACCENT, GREY, ORANGE, RESET = "\x1b[38;2;40;120;220m", "\x1b[38;2;140;140;140m", "\x1b[38;2;230;140;30m", "\x1b[0m"
SEL = "\x1b[48;2;40;120;220m\x1b[38;2;255;255;255m"         # the field the cursor is on
GREEN = "\x1b[38;2;60;170;80m"
# Background Bambu Studio's state beside its field (2026-11-23): symbol and colour. ○ ● ◦ are in Consolas, the font of
# Windows' own console (◐ ◑ are not)
BADGES = {"opening": ("◦", ACCENT), "open": ("●", GREEN), "closing": ("◦", ORANGE), "closed": ("○", GREY)}
BOLD, FAINT = "\x1b[1m", "\x1b[2m"
WALLS = [None, "1", "2", "3", "4", "5", "6"]
INFILL = [None, "10", "15", "20", "25", "30", "40", "50", "75", "100"]
MODES = ["auto", "on", "off"]
PLATES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20]      # 0: no limit
PRESET_SLOTS = 10         # 2026-11-21: slots with all settings, the same for every model (3, 10 since 2026-11-23)
PRESET_NAME_MAX = 24


def _presets() -> list:
    """The preset slots from the user's settings: {"name", "values"} or None (empty), always PRESET_SLOTS long."""
    raw = setting("presets", [])
    raw = raw if isinstance(raw, list) else []
    slots = []
    for i, p in enumerate((raw + [None] * PRESET_SLOTS)[:PRESET_SLOTS]):
        if isinstance(p, dict) and isinstance(p.get("values"), dict):   # a hand-edited file: name always text
            slots.append({"name": str(p.get("name") or f"Preset {i + 1}")[:PRESET_NAME_MAX], "values": p["values"]})
        else:
            slots.append(None)
    return slots
BUTTONS = ("b.make", "b.preview", "b.cancel")             # Preview between the two (2026-11-19)
WINDOW_MAX_COLS = 110     # the form's own window never gets wider, whatever a long model name asks for
MENU_EXTRA = 10           # menu width = label column + value column + this: " ◄  " ... "  ► " and the cursor bar


def _jump_text(label) -> str:
    """What a letter in a list jumps by: the name after the last "·" ("Manual  ·  Turquoise" -> turquoise), without a
    leading share ("20% Cyan + 80% Magenta" -> cyan + ...). 2026-11-23: every colour started with "Manual", so only
    M jumped."""
    text = str(label).split("·")[-1].strip()
    return re.sub(r"^\d+\s*%\s*", "", text).lower()


def _button_keys() -> str:
    """The shortcut letters of Generate, Analyze, Cancel in the form's language (2026-11-23: G A C; in German and
    French two buttons start with A, so there the third takes another letter of its word)."""
    keys = t("keys.buttons")
    return keys if len(keys) == len(BUTTONS) else "GAC"


def _underline(label: str, key: str) -> str:
    """The label with its shortcut letter underlined (the first one, either case); as it is when it has none."""
    i = label.lower().find(key.lower())
    return label if i < 0 else f"{label[:i]}\x1b[4m{label[i]}\x1b[24m{label[i + 1:]}"


def _digit(k: str) -> bool:
    """One of 0-9 (str.isdigit also takes ² and other digits int() refuses)."""
    return len(k) == 1 and k in "0123456789"


class Cancel(Exception):
    pass


def _key(tick=None) -> str:
    """One key: 'up', 'down', 'left', 'right', 'home', 'end', 'enter', 'esc', 'back', 'tab', or the character.
    `tick` is called every 0.25 s while no key comes (2026-11-23: the form redraws a changed Bambu Studio state)."""
    import msvcrt
    while tick is not None and not msvcrt.kbhit():
        tick()
        time.sleep(0.25)
    c = msvcrt.getwch()
    if c in ("\x00", "\xe0"):
        return {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end", "I": "pgup",
                "Q": "pgdn"}.get(msvcrt.getwch(), "")
    return {"\r": "enter", "\x1b": "esc", "\x08": "back", "\t": "tab", "\x03": "esc"}.get(c, c)


def _draw(lines: list[str]) -> None:
    """The whole screen from the top row. No newline after the last line: on the last row of the console it would
    scroll the screen up one row, so every row of the console can be used."""
    sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(lines[:_rows()]))
    sys.stdout.flush()


def _status_lines(status: dict) -> list[str]:
    """The Bambu Studio status, faint, ✅ in green or ⚠ in orange."""
    ok = status["ok"]
    return [f"  {FAINT}{ACCENT if ok else ORANGE}{'✅' if ok else '⚠'}  {_clip(line, _cols() - 7)}{RESET}"
            for line in status["lines"]]


def _visible(text: str) -> int:
    """The width a line takes on screen (colour codes take none)."""
    return len(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text))


SCROLL_ROOM = 14      # rows a form that scrolls keeps under its fixed header at least (see _head)


def _head(lines: list[str], side: int = 0, below_extra: int = 0,
          scroll: bool = False) -> tuple[list[str], list[str]]:
    """The header above `lines` and what is left of `lines` under it: (header rows, remaining lines). The first `side`
    lines (the status lines: the version checks) go into the header beside the nozzle when the full header fits with
    them (2026-11-22: version checks and project name swapped; the project name now stands above the
    menu, see Form.form_lines). They then take no rows of their own, so the form with the full header fits a window
    of a 1080p screen. Otherwise all of `lines` stay under the header (see _banner). `below_extra`: rows the caller
    needs further down. `scroll` (the form, which scrolls under a fixed header, see Form.screen): the header only has
    to leave SCROLL_ROOM rows, not room for all of `lines` (2026-11-23: in a cmd or PowerShell window of 30 rows the
    form of 39 lines had no header at all)."""
    try:
        import orientr_banner as b
        status = _beside(lines[:side])
        fits = b.status_place(status) is not None         # under the baseline, right of the plate (2026-11-23)
        rows = b.final_frame(status=status)
        need = min(len(lines) - side + below_extra, SCROLL_ROOM) if scroll else len(lines) - side + below_extra
        if side and fits and _cols() >= b.WIDTH + 1 and len(rows) + need <= _rows():
            return rows, lines[side:]
    except Exception:
        pass
    return _banner(min(len(lines) + below_extra, SCROLL_ROOM) if scroll else len(lines) + below_extra), lines


def _legend(text: str, colour: str = GREY) -> list[str]:
    """A key legend, in grey: wrapped between its groups (three spaces apart; a new line in the text starts a new line
    too) when the console is too narrow for it, so no key is cut off (2026-11-22: in the SOMA terminal of 63 columns
    "Esc back" fell off)."""
    room = _cols() - 4
    lines = []
    for part in text.split("\n"):
        line = ""
        for group in part.split("   "):
            if line and len(line) + 3 + len(group) > room:
                lines.append(line)
                line = group
            else:
                line = f"{line}   {group}" if line else group
        lines.append(line)
    return [f"  {colour}{_clip(line, room)}{RESET}" for line in lines]


FOOT_LINES = 4        # the form's last lines besides the key legend: blank, (legend), blank, two hint lines


def _scroll(lines: list[str], sel: int, foot: int, rows: int = 0) -> list[str]:
    """The part of a screen too high for the console that keeps line `sel` (the selected row) in view, about in the
    middle (2026-11-22: in a low console, like SOMA's terminal panel, the buttons fell off the bottom). The last `foot`
    lines (key legend and hint of the selected row) stay at the bottom when there is room. ▲ / ▼ in place of the first /
    last line show there is more above / below. `rows`: the rows it may take (0: the whole console)."""
    rows = rows or _rows()
    if len(lines) <= rows:
        return lines
    body, tail = (lines[:-foot], lines[-foot:]) if foot and rows >= foot + 6 else (lines, [])
    h = rows - len(tail)
    top = min(max(0, sel - h // 2), len(body) - h)
    view = body[top:top + h]
    if top > 0:
        view[0] = f"  {GREY}▲{RESET}"
    if top + h < len(body):
        view[-1] = f"  {GREY}▼{RESET}"
    return view + tail


def _beside(lines: list[str]) -> list[str]:
    """The status lines as they go into the header (under the baseline, right of the plate), without their indent and
    empty lines."""
    return [s[2:] if s.startswith("  ") else s for s in lines if s]


def _banner(below: int) -> list[str]:
    """The Orientr header that fits above `below` rows: the full one (the logo with the wordmark and the description,
    13 rows, 61 columns: also in the SOMA terminal of 63 columns), without its indent when the console is just too
    narrow, else the compact one ("◆ Orientr" and the description's first sentence, 2 rows), else that without it, else none
    (2026-11-19: the header was gone in a console just too low or too narrow for the full one). A header
    line stays off the last column: there the cursor waits to wrap, and the erase-to-end-of-line of the animation
    would wipe the last letter."""
    try:
        import orientr_banner as b
        tiers = [(b.final_frame(), b.WIDTH),
                 (b.final_frame(0), b.WIDTH - 2),
                 (b.compact_frame(), b.COMPACT_WIDTH),
                 (b.compact_frame(False), b.MINI_WIDTH)]
    except Exception:
        return []
    for rows, width in tiers:
        if len(rows) + below <= _rows() and _cols() >= width + 1:
            return rows
    return []


_FIXED = {"on": False}


def _fixed_banner() -> None:
    """While the tool makes the project: the header on the top rows, the tool's output scrolling under it (a scroll
    region), when the console leaves at least 8 rows for the output; else nothing changes."""
    rows = _rows()
    banner = _banner(SCROLL_ROOM)
    if not banner or len(banner) > rows - 8:
        return
    sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(banner) + f"\x1b[{len(banner) + 1};{rows}r\x1b[{len(banner) + 1};1H")
    sys.stdout.flush()
    _FIXED["on"] = True


def _free_banner() -> None:
    """The whole console scrolls again; the cursor stays where the output ended (setting the region moves it home)."""
    if _FIXED["on"]:
        sys.stdout.write("\x1b7\x1b[r\x1b8")
        sys.stdout.flush()
        _FIXED["on"] = False


def _animate_banner(rows: list[str], beside: list[str] = ()) -> None:
    """The full header grows in once (about 1 s) from the top row; the compact one is drawn by the caller as is.
    `beside`: the lines _head put into the header (as given to it, with their indent)."""
    import orientr_banner as b
    status = _beside(list(beside))
    if beside and rows == b.final_frame(status=status):
        indent = 2
    elif rows == b.final_frame():
        indent, status = 2, []
    elif rows == b.final_frame(0):
        indent, status = 0, []
    else:
        return
    sys.stdout.write("\x1b[H\x1b[2J")
    b.show(lead=False, indent=indent, status=status)      # ORIENTR_NO_ANIMATION=1: no animation.
    sys.stdout.write("\x1b[?25l")                         # show() gives the cursor back: hide it again


def choose_model(sb) -> int:
    """`orientr` outside a model folder: the header and the Bambu Studio status, then the SOMA models (newest first),
    chosen with the arrow keys; the form of the chosen model then opens with that model's own Python, as `orientr` in
    its folder would (2026-11-19)."""
    import subprocess
    import orientr_banner
    if os.name != "nt" or not orientr_banner.enable_ansi():
        print(t("run.windows_only"))
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    models = sb.soma_models()
    if not models:
        print(t("run.no_models"))
        return 2
    try:
        tpl = sb.load_template(sb.DEFAULT_TEMPLATE)
    except Exception:                                     # no or broken template: still report Bambu Studio itself
        tpl = None
    status = sb.bambu_status(tpl)
    chosen, pos, animated = None, 0, False
    sys.stdout.write("\x1b[?1049h\x1b[?25l")              # own screen, no cursor
    _center_own_window()                                  # its own window: in the middle, clear of the taskbar
    try:
        while True:
            stat = _status_lines(status)
            full = stat + ["", f"  {BOLD}{_clip(t('pick.model'), _cols() - 4)}{RESET}", ""]
            foot = [""] + _legend(t("help.models"))
            # at least 5 models in view
            banner, head = _head(full, len(stat), len(foot) + min(len(models), 5))
            if not animated:
                _animate_banner(banner, full[:len(full) - len(head)])
                animated = True
            room = max(1, _rows() - len(banner) - len(head) - len(foot))
            top = min(max(0, pos - room // 2), max(0, len(models) - room))
            items = []
            for i in range(top, min(len(models), top + room)):
                name = _clip(models[i][0], _cols() - 6)
                items.append(f"  {SEL} {name} {RESET}" if i == pos else f"   {name}")
            _draw(banner + head + items + foot)
            k = _key()
            if k == "esc":
                break
            if k == "enter":
                chosen = models[pos][1]
                break
            if k in ("up", "down", "pgup", "pgdn", "home", "end"):
                pos = {"up": pos - 1, "down": pos + 1, "pgup": pos - room, "pgdn": pos + room, "home": 0,
                       "end": len(models) - 1}[k]
                pos = max(0, min(pos, len(models) - 1))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
    if chosen is None:
        print(t("run.cancelled"))
        return 0
    py = chosen / ".soma" / "env" / "Scripts" / "python.exe"
    env = {**os.environ, "ORIENTR_NO_ANIMATION": "1"}       # the header already grew in once here
    # in the window `orientr` opened (ORIENTR_OWN_CONSOLE, passed on in env): the form there, waiting for a key at the end
    own = ["--form", "--wait"] if os.environ.get("ORIENTR_OWN_CONSOLE") else []
    child = subprocess.Popen([str(py) if py.exists() else sys.executable, "-I", str(Path(sb.__file__).resolve()),
                              *own], cwd=chosen, env=env)
    while True:
        try:
            return child.wait()
        except KeyboardInterrupt:                         # Ctrl+C reaches both: the form handles it and restores
            continue                                      # the screen itself, so wait for it instead of killing it


def _cols() -> int:
    return max(40, shutil.get_terminal_size().columns)


def _rows() -> int:
    return max(10, shutil.get_terminal_size().lines)


def _real_console() -> bool:
    """Is this Windows' own console window (conhost)? Only there `mode con` makes the window bigger. Windows Terminal
    runs the program in a pseudo console (window class PseudoConsoleWindow): there `mode con` would only change the
    size the program sees, not the window, and the form would be drawn for rows that are not there."""
    try:
        import ctypes
        from ctypes import wintypes
        kernel32, user32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        hwnd = kernel32.GetConsoleWindow()
        name = ctypes.create_unicode_buffer(64)
        return bool(hwnd) and user32.GetClassNameW(hwnd, name, 64) > 0 and name.value == "ConsoleWindowClass"
    except Exception:
        return False


def window_size(form: "Form") -> tuple[int, int]:
    """(columns, rows) that fit the form with the full header above it exactly (2026-11-21: the form's
    own window was too big; 2026-11-22: still too much room on the right). As wide as the widest of header, status,
    project name, menu (2 columns indent) and key legend in the form's current language, plus one column to spare:
    the last column is never written. Another language chosen in the form: Windows' own console follows it
    (_fit_own_console), Windows Terminal cannot be resized by a program, there the value column gives way.
    As high as the header plus the form (its status and project lines sit in the header, see _head)."""
    import orientr_banner as b
    width, room = form._layout(form.fields())
    n = form.side()
    lines = form.form_lines()
    status = _beside(lines[:n])                           # in the header, which never gets wider for them
    cols = max(b.WIDTH + 1, room + width + MENU_EXTRA + 3, len(t("help.form")) + 3)
    if b.status_place(status) is None:                    # they do not fit there: under the header
        return min(cols, WINDOW_MAX_COLS), len(b.final_frame()) + len(lines)
    return min(cols, WINDOW_MAX_COLS), len(b.final_frame(status=status)) + len(lines) - n


def _fit_own_console(form: "Form") -> None:
    """The form's own window gets window_size(): Windows Terminal already opened it at that size (_own_window),
    Windows' own console is set to it here. Then it is moved to the middle of the screen (_center_own_window)."""
    if not os.environ.get("ORIENTR_OWN_CONSOLE"):
        return
    if _real_console():
        cols, rows = window_size(form)
        if (cols, rows) != (_cols(), _rows()):           # on the normal screen: the own screen is a second buffer
            sys.stdout.write("\x1b[?1049l")
            sys.stdout.flush()
            import subprocess                             # Windows' own mode.com, never one from the current folder
            mode = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mode.com")
            subprocess.run([mode, "con:", f"cols={cols}", f"lines={rows}"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            sys.stdout.write("\x1b[?1049h\x1b[?25l")
            sys.stdout.flush()
    _center_own_window()


def _own_window_handle() -> int:
    """The window the form is shown in: Windows' own console window, or for Windows Terminal the terminal window that
    owns the program's pseudo console window (it is created owned by it). 0 when not found (yet)."""
    import ctypes
    from ctypes import wintypes
    kernel32, user32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    user32.GetWindow.restype = user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    hwnd = kernel32.GetConsoleWindow()
    if not hwnd:
        return 0
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, 64)
    if name.value == "ConsoleWindowClass":
        return hwnd
    owner = user32.GetWindow(hwnd, 4) or user32.GetAncestor(hwnd, 3)   # GW_OWNER, GA_ROOTOWNER
    return owner if owner and owner != hwnd else 0


_ICONS: list = []                                         # the loaded icons: they live as long as this process


def _set_window_icon(hwnd: int) -> None:
    """The Orientr logo as the icon of the form's own window, in the taskbar and Alt+Tab (2026-11-22),
    for Windows Terminal and Windows' own console alike. An icon belongs to the process that loaded it, so it stays
    while this process runs (the chooser waits for the form it started: the icon stays there too)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT)
        user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        ico = str(Path(__file__).resolve().parent / "orientr-logo.ico")
        for which, size in ((1, 32), (0, 16)):            # ICON_BIG, ICON_SMALL
            icon = user32.LoadImageW(None, ico, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
            if icon:
                _ICONS.append(icon)
                user32.SendMessageW(hwnd, 0x80, which, icon)           # WM_SETICON
    except Exception:                                     # no icon must never stop the form
        pass


def _center_own_window() -> None:
    """Move the form's own window into the screen's work area (the screen without the taskbar), on the screen it
    opened on (2026-11-22: it opened partly under the taskbar): centred left to right, and as high as the work area,
    from the top of the screen to the taskbar (2026-11-23). A window wider than the work area is made as wide as it.
    Only the window this tool opened (ORIENTR_OWN_CONSOLE), never a terminal of the user's."""
    if os.name != "nt" or not os.environ.get("ORIENTR_OWN_CONSOLE"):
        return
    try:
        import ctypes
        import time
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]

        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wintypes.UINT)
        hwnd = 0
        for _ in range(20):                               # Windows Terminal may still be putting its window up
            hwnd = _own_window_handle()
            if hwnd:
                break
            time.sleep(0.05)
        if not hwnd:
            return
        _set_window_icon(hwnd)
        r, info = wintypes.RECT(), MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)) or not user32.GetMonitorInfoW(
                user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):   # MONITOR_DEFAULTTONEAREST
            return
        work = info.rcWork
        ww, wh = work.right - work.left, work.bottom - work.top
        # 2026-11-23: always the full height of the work area, from the top of the screen down to the taskbar, so the
        # whole form fits; the console follows with more rows (the form reads its size on every draw)
        w, h = min(r.right - r.left, ww), wh
        x, y = work.left + (ww - w) // 2, work.top
        flags = 0x0004 | 0x0010                           # SWP_NOZORDER | SWP_NOACTIVATE
        if (w, h) == (r.right - r.left, r.bottom - r.top):
            flags |= 0x0001                               # SWP_NOSIZE: only moved
        user32.SetWindowPos(hwnd, None, x, y, w, h, flags)
    except Exception:                                     # a window in the wrong place must never stop the form
        pass


def _clip(text: str, room: int) -> str:
    """Plain text cut to the room left on the line (colour codes are added around it afterwards)."""
    return text if len(text) <= room else text[:max(1, room - 1)] + "…"


class Form:
    def __init__(self, ws: Path, cfg: dict, sb):
        self.ws, self.sb = ws, sb
        pr = cfg.get("print") or {}
        self.title = sb.model_title(ws)
        tpl = sb.load_template(sb.resolve_template(ws, cfg.get("template")))
        self.templates = {self._short(m): v for m, v in sb.printer_templates(ws, cfg.get("template")).items()}
        self.presets: dict[tuple, tuple] = {}             # (printer, nozzle size) -> (template, filaments, processes)
        self.tpls: dict[str, object] = {}                 # printer -> its template
        self.size = ""
        self.rebase(cfg)
        self.printers = sorted(self.templates, key=lambda m: (m != self.printer0, m.lower()))
        self.printer = self.printer0
        self.size = self.own_size(self.printer)
        want = pr.get("nozzle_size")
        try:
            want = f"{float(want):g}" if want not in (None, "") else None
        except ValueError:
            want = None
        if want in self.sizes(self.printer):
            self.size = want
        _, fils, procs = self._lists(self.printer)
        d_fil, d_proc = self._defaults(self.printer, self.size)
        self.filament = pr.get("material") if pr.get("material") in fils else d_fil
        self.process = pr.get("process") if pr.get("process") in procs else d_proc
        self.walls = str(pr["walls"]) if pr.get("walls") not in (None, "") else None
        self.infill = f"{sb._number(pr['infill']):g}" if pr.get("infill") not in (None, "") else None   # '50%'->'50'
        self.support, self.brim = pr.get("support") or "auto", pr.get("brim") or "auto"
        self.nozzle = pr.get("nozzle") or "auto"
        self.open = bool(pr.get("open", True))
        self.prestart = setting("prestart", False) is True   # per user, not per model; off after install
        self.prestart_sel = self.prestart                 # what the field shows; Enter makes it so (2026-11-23)
        self.duplicates = int(float(pr.get("duplicates") or 1))   # checked whole numbers ("2.0" too): validate_config
        self.max_plates = int(float(pr.get("max_plates") or 0))
        self.skip = set(self.skip0)
        self.copies = dict(self.copies0)                  # part -> how many (times the duplicates)
        # 2026-11-23: no colour templates in the form any more; the tool makes one filament per colour from the
        # printer's own template. "" here: a colour template in bambu.json goes back to the printer's own one
        self.colors = ""
        self.colour_mode = self.colour_mode0              # model: the parts' colours in SOMA; manual: proj_col + own
        self.proj_col = self.proj_col0                    # manual: the project's colour ('#RRGGBB' or a name)
        self.mix = self.mix0                              # mix: the mixing mode (CMYKW, CMYW, RYBW)
        if self.colour_mode == "mix" and not self._mix_ok(self.printer, self.mix):
            self.colour_mode = "model"
        self._ids: dict[tuple, str] = {}                  # (printer, size, filament) -> Bambu's filament id
        self.fil = dict(self.fil0)                        # part -> its own filament number (absent: by colour)
        self.own_col = dict(self.own_col0)                # part -> its own colour (C; absent: the model's)
        self.status = self._status0 = sb.bambu_status(tpl)
        self._status_tpl = tpl                            # for the status lines again in another language
        self.row = 0
        self.preset = 0                                   # the preset slot the field shows (0-based)
        self.note = ""                                    # a message in place of the hint, until the next key

    def rebase(self, cfg: dict) -> None:
        """What bambu.json holds now (printer, skipped parts): options() only sends what differs from it. Called again
        after a refused build, because the tool saves the choices before it builds."""
        tpl = self.sb.load_template(self.sb.resolve_template(self.ws, cfg.get("template")))
        self.printer0 = self._short(self.sb.template_printer(tpl))
        # a colour template in bambu.json (before 2026-11-23): Generate goes back to the printer's own template
        self.colors0 = (cfg.get("template") or "") if tpl.filaments > 1 else ""
        if self.printer0 not in self.templates:           # e.g. a model's own inputs/bambu_template.3mf
            self.templates[self.printer0] = (cfg.get("template"), None)
            self.tpls.pop(self.printer0, None)
            self.presets = {k: v for k, v in self.presets.items() if k[0] != self.printer0}
        hints = cfg.get("parts") or {}
        found = self.sb.printable_parts(self.ws)
        names = [n for n, *_ in found]
        self.part_rgb = {n: rgb for n, _, _, rgb in found}   # the part's colour in the model: its filament by colour
        self.parts = [n for n in names if not (hints.get(n) or {}).get("merge_into")]   # merged ones follow the host
        self.skip0 = {n for n in self.parts if (hints.get(n) or {}).get("skip")}
        self.copies0 = {n: int(float((hints.get(n) or {}).get("copies") or 1)) for n in self.parts}
        self.fil0 = {n: int(float(hints[n]["filament"])) for n in self.parts
                     if (hints.get(n) or {}).get("filament") not in (None, "", "auto")}
        self.own_col0 = {n: str(hints[n]["colour"]).lower() for n in self.parts
                         if (hints.get(n) or {}).get("colour") not in (None, "", "auto")}
        self.hints = [(n, dict(hints.get(n) or {})) for n in names]   # all parts, merged ones too, in model order
        self.merged_col = {n: str(h["colour"]).lower() for n, h in self.hints
                           if h.get("merge_into") and h.get("colour") not in (None, "", "auto")}
        self.merged = {n for n, h in self.hints if h.get("merge_into")}
        pr = cfg.get("print") or {}
        self.colour_mode0 = pr.get("colours") if pr.get("colours") in ("model", "mix") else "manual"
        self.mix0 = str(pr.get("mix") or "CMYKW").upper()
        self.proj_col0 = str(pr.get("colour") or "") if self.colour_mode0 == "manual" else ""

    @staticmethod
    def _short(model) -> str:
        return str(model or "").replace("Bambu Lab ", "").strip()

    def _tpl(self, printer: str):
        if printer not in self.tpls:
            spec, recent = self.templates[printer]
            self.tpls[printer] = self.sb.load_template(self.sb.resolve_template(self.ws, spec) if spec or not recent
                                                       else recent)
        return self.tpls[printer]

    def sizes(self, printer: str) -> list[str]:
        """Nozzle sizes that fit this printer (Bambu Studio's own printer presets)."""
        return self.sb.nozzle_sizes(self.sb.template_printer(self._tpl(printer)))

    def own_size(self, printer: str) -> str:
        return self.sb.template_nozzle(self._tpl(printer))

    def _defaults(self, printer: str, size: str) -> tuple:
        """(filament, process) a printer starts with at this nozzle size: its template's own, else the size's default."""
        tpl = self._tpl(printer)
        if size == self.own_size(printer):
            return (self.sb.filament_short((tpl.settings.get("filament_settings_id") or [""])[0]),
                    self.sb.filament_short(tpl.settings.get("print_settings_id") or ""))
        return self.sb.nozzle_defaults(self.sb.template_printer(tpl), size)

    def _lists(self, printer: str) -> tuple:
        """(template, filaments, processes) of a printer at the chosen nozzle size; popular filaments first."""
        size = self.size if printer == getattr(self, "printer", None) else self.own_size(printer)
        if (printer, size) not in self.presets:
            tpl = self._tpl(printer)
            preset = str(tpl.settings.get("printer_settings_id") or "")
            if size != self.own_size(printer):
                preset = f"{self.sb.template_printer(tpl)} {size} nozzle"
            fils = list(self.sb.filaments_for(preset))
            pop = [f for f in self.sb.POPULAR_FILAMENTS if f in fils]
            fils = pop + sorted((f for f in fils if f not in pop), key=str.lower)
            self.presets[(printer, size)] = (tpl, fils, list(self.sb.processes_for(preset)))
        return self.presets[(printer, size)]

    def _keep_lists(self) -> None:
        """After a printer or nozzle size change: keep filament and process when they exist there, else the defaults."""
        _, fils, procs = self._lists(self.printer)
        d_fil, d_proc = self._defaults(self.printer, self.size)
        if self.filament not in fils:
            self.filament = d_fil
        if self.process not in procs:
            self.process = d_proc

    def _set_printer(self, printer: str) -> None:
        """Another printer: keep nozzle size, filament and process when it has them, else its template's own."""
        if printer != self.printer:                       # a colour template belongs to one printer
            self.colors = ""
        self.printer = printer
        if self.size not in self.sizes(printer):
            self.size = self.own_size(printer)
        self._keep_lists()
        if self.colour_mode == "mix" and not self._mix_ok(printer, self.mix):
            self.colour_mode = "model"                    # e.g. a printer with one hotend: no mixing
            self._leave_mix()

    # --- colours (2026-11-23): Auto from the SOMA model, or Manual: one colour for the project, a part's own in Parts.
    # The tool makes one filament per colour, each the nearest colour Bambu Lab sells the chosen filament in.
    def official(self) -> list:
        """[('#RRGGBB', {language: name})]: the colours Bambu Lab sells the chosen filament in; [] for others."""
        key = (self.printer, self.size, self.filament)
        if key not in self._ids:
            tpl = self._lists(self.printer)[0]
            preset = str(tpl.settings.get("printer_settings_id") or "")
            if self.size != self.own_size(self.printer):
                preset = f"{self.sb.template_printer(tpl)} {self.size} nozzle"
            name = self.sb.filaments_for(preset).get(self.filament, "")
            self._ids[key] = str(self.sb.flat_filament(name).get("filament_id") or "") if name else ""
        return self.sb.official_colours(self._ids[key])

    def _mix_ok(self, printer: str, mode: str) -> bool:
        """Colour mixing in this mode on this printer: 2+ hotends and the mode's filament made for it (2026-11-23)."""
        recipes = self.sb.mix_recipes()
        if mode not in recipes:
            return False
        tpl, fils, _ = self._lists(printer)
        return self.sb.hotends(tpl) >= 2 and recipes[mode][0] in fils

    def _recipes(self) -> list:
        return self.sb.mix_recipes().get(self.mix, ("", []))[1]

    def colour_list(self) -> list:
        """(hex, label) of every colour to choose from: Bambu Lab's for this filament, else the tool's named ones;
        when mixing the mode's base colours and Bambu's measured mixes of them."""
        if self.colour_mode == "mix":
            bases = []
            for comps, _, _ in self._recipes():
                bases += [c for c in comps if c not in bases]
            return [(h, k) for k, h in bases] + [
                (h, " + ".join(f"{round(r * 100)}% {k}" for (k, _), r in zip(comps, ratios)))
                for comps, ratios, h in self._recipes()]
        sold = self.official()
        if sold:
            return [(h, self.sb.official_name(n) or h) for h, n in sold]
        return [(self.sb.srgb_hex(self.sb.COLOR_NAMES[n]), cap(t("col." + n))) for n in self.sb.PALETTE]

    def colour_label(self, rgb) -> str:
        """A colour's name: Bambu Lab's when it sells it in this filament, else the nearest named colour."""
        if rgb is None:
            return "?"
        h = self.sb.srgb_hex(rgb)
        return next((lab for x, lab in self.colour_list() if x == h), None) or cap(t("col." + self.sb.color_name(rgb)))

    def proj_hex(self) -> str:
        """Manual: the project's colour as one of colour_list() (the nearest; white when none is chosen)."""
        try:
            rgb = self.sb.parse_colour(self.proj_col) if self.proj_col else None
        except self.sb.ToolError:
            rgb = None
        return self.sb.snap_colours([rgb or (1.0, 1.0, 1.0)], [(h, {}) for h, _ in self.colour_list()])[0][0]

    def _colour_opts(self, printer: str) -> list:
        """The "Colors" choices as ((mode, colour), label): Auto from the SOMA model, then Manual in each colour."""
        mode, self.colour_mode = self.colour_mode, "manual"  # the manual list, also while mixing is chosen
        try:
            manual = [(("manual", h), t("v.manual", name=lab)) for h, lab in self.colour_list()]
        finally:
            self.colour_mode = mode
        # colour mixing (Bambu Studio's PLA Palette and PLA Basic recipes) on printers with 2+ hotends (2026-11-23)
        mixes = [(("mix", m), t("v.mix", mode=m, filament=mat)) for m, (mat, _) in self.sb.mix_recipes().items()
                 if self._mix_ok(printer, m)]
        return [(("model", ""), t("v.auto_model"))] + mixes + manual

    def _set_colours(self, v: tuple) -> None:
        was_mix = self.colour_mode == "mix"
        self.colour_mode, col = v
        if self.colour_mode == "mix":                     # the mode's own filament
            if not was_mix:
                self._before_mix = self.filament
            self.mix = col
            self.filament = self.sb.mix_recipes()[col][0]
        else:
            if was_mix:
                self._leave_mix()
            if col:
                self.proj_col = col

    def _leave_mix(self) -> None:
        """Mixing no longer applies: the filament chosen before it comes back, when this printer has it (2026-11-23:
        it stayed PLA Palette, with only its 5 colours)."""
        before = getattr(self, "_before_mix", None)
        if before and before in self._lists(self.printer)[1]:
            self.filament = before

    def _set_filament(self, v: str) -> None:
        self.filament = v
        if self.colour_mode == "mix" and v != self.sb.mix_recipes().get(self.mix, ("",))[0]:
            self.colour_mode = "model"                    # another filament: mixing in this mode no longer applies

    def part_colour(self, name: str):
        """The colour a part asks for: its own (C), else Manual: the project's, Auto: the one in the SOMA model."""
        own = self.own_col.get(name) or self.merged_col.get(name)
        if own:
            try:
                return self.sb.parse_colour(own)
            except self.sb.ToolError:
                pass
        if self.colour_mode == "manual" and name not in self.merged:   # a merged part keeps its own (make_project)
            return self.sb.hex_srgb(self.proj_hex())
        return self.part_rgb.get(name)

    def slot_colours(self) -> tuple[list, list]:
        """(filament colours '#RRGGBB', Bambu's names per filament) as make_project makes them (colour_parts,
        slot_colours), with the form's current choices of skip and colour per part."""
        entries = []
        for n, h in self.hints:
            h = dict(h)
            if n in self.parts:
                h["skip"] = n in self.skip
            entries.append((n, h))
        # every part by its colour, merged ones too (by_colour: a filament number means nothing here)
        rgbs = [c for c in (self.part_colour(n) for n in self.sb.colour_parts(self.sb.by_colour(entries))) if c]
        if self.colour_mode == "mix":                     # base filaments, then the mixes (as make_project)
            phys, mixes, names = self.sb.mix_plan(rgbs or [(1.0, 1.0, 1.0)], self._recipes())
            return phys + [h for *_, h in mixes], names
        return self.sb.slot_colours(rgbs or [(1.0, 1.0, 1.0)], self.official())

    def part_filament(self, name: str) -> tuple[int, bool]:
        """(filament number, False) of a part: the one of its colour (a number from bambu.json no longer counts)."""
        rgb = self.part_colour(name)
        # filaments made from the parts' colours: plainly the nearest, as make_project (no grey rule)
        return (self.sb.nearest_filament(rgb, self.slot_colours()[0], False) if rgb else 1), False

    def far_parts(self) -> list[str]:
        """Printed parts whose colour Bambu Lab does not sell in this filament: they print in the nearest one."""
        hexes, out = self.slot_colours()[0], []
        for n in self.parts:
            f, own = self.part_filament(n)
            rgb = self.part_colour(n)
            c = self.sb.hex_srgb(hexes[f - 1]) if 0 < f <= len(hexes) else None
            if not own and n not in self.skip and rgb and c and self.sb.colour_distance(rgb, c) > self.sb.UNAVAILABLE:
                out.append(n)
        return out

    def _warnings(self) -> dict[str, list[str]]:
        """Per field ("colors", "parts") the warning sentences, ⚠ first (2026-11-23: the field gets a ⚠ and turns
        orange): colours not sold or not mixable in this filament, no part chosen, too many objects."""
        out: dict[str, list[str]] = {}
        far = self.far_parts()
        if far:
            key = "h.mix_far" if self.colour_mode == "mix" else "h.colours_far2"
            out["colors"] = [t(key, n=len(far))]
            out["parts"] = [t(key, n=len(far))]
        if self.parts and len(self.skip) >= len(self.parts):
            out.setdefault("parts", []).append("⚠ " + t("run.no_parts"))
        elif self.objects() > self.sb.MAX_OBJECTS:
            out.setdefault("parts", []).append("⚠ " + t("e.too_many", n=self.objects(), max=self.sb.MAX_OBJECTS))
        return out

    def _bg_state(self) -> str | None:
        """Background Bambu Studio's state for the badge: opening, open, closing, closed or None (none to show)."""
        try:
            return self.sb.background_state()
        except Exception:                                 # never let this disturb the form
            return None

    def _badge(self, selected: bool) -> tuple[int, str] | None:
        """(visible width, text) of the state beside "Background Bambu Studio": "● Open" and so on, in its colour;
        plain on the selected row, whose colours it would break."""
        state = getattr(self, "_bg", None)
        if state not in BADGES:
            return None
        sym, colour = BADGES[state]
        plain = f"{sym} {t('bg.' + state)}"
        return len(plain), plain if selected else f"{colour}{plain}{RESET}"

    def _tick(self) -> None:
        """While the form waits for a key: redraw when Background Bambu Studio's state changed."""
        state = self._bg_state()
        if state != getattr(self, "_bg", None):
            self._bg = state
            self.draw(self.screen())

    def _pick_prestart(self, on: bool) -> None:
        """←→ on "Background Bambu Studio" only changes what the field shows (2026-11-23): nothing starts, closes or
        is saved until Enter (_set_prestart); the note says what Enter will do."""
        self.prestart_sel = on
        if on != self.prestart:
            self.note = t("n.prestart_on" if on else "n.prestart_off")

    def _set_prestart(self, on: bool) -> None:
        """Bambu Studio in the background, on or off (2026-11-21: a choice in the form, off after install):
        saved for every model; on starts it now (after SOMA, when the PC is quiet), off cancels a start that waits
        and closes the hidden Studio of this form. Called with Enter on the field (2026-11-23)."""
        self.prestart = self.prestart_sel = on
        save_setting("prestart", on)
        if on:
            started = self.open and self.sb.prestart_studio()
            self.note = t("n.prestart_started" if started else "n.prestart_not_started")
        else:
            self.sb.cancel_prestart()
            self.note = t("n.prestart_closed")

    def _set_language(self, code: str) -> None:
        """Another language: its labels are longer or shorter, so the form's own window follows (Windows' own console
        only, see window_size). The status lines in the header are made again in it (2026-11-23: they stayed in the
        old one); a message that took their place stays as it is."""
        set_language(code)
        if self.status is self._status0:                  # update check: cached for 12 h, so no wait on the network
            self.status = self._status0 = self.sb.bambu_status(self._status_tpl)
        _fit_own_console(self)

    def _set_size(self, size: str) -> None:
        self.size = size
        self._keep_lists()

    # --- fields: (key, label, list of (value, label) or None, value, setter) -------------------------------------
    def fields(self) -> list:
        _, fils, procs = self._lists(self.printer)
        yes_no = [(True, t("v.yes")), (False, t("v.no"))]
        modes = [(m, t(f"v.{m}")) for m in MODES]
        walls = [(w, t("v.profile") if w is None else t("v.wall" if w == "1" else "v.walls", n=w)) for w in WALLS]
        infill = [(i, t("v.profile") if i is None else f"{i} %") for i in INFILL]
        mark = lambda v, v0: f"{v}  ({t('v.current')})" if v == v0 else v   # noqa: E731
        # a printer with two nozzles; with a colour template the choice does not apply (see DEVELOPMENT.md)
        # (2026-11-23: also with several colours made by the tool: Bambu Studio maps the filaments to the nozzles)
        two = len(self._lists(self.printer)[0].nozzle_boxes) >= 2 and len(self.slot_colours()[0]) == 1
        nozzles = [("auto", "Auto"),("left", t("v.left")), ("right", t("v.right"))] if two else [("auto", t("v.na"))]
        sizes = self.sizes(self.printer) or [self.size]
        slots = [(i, f"{i + 1}  ·  {p['name'] if p else t('v.empty')}") for i, p in enumerate(_presets())]
        return [
            ("preset", t("f.preset"), slots, self.preset, lambda v: setattr(self, "preset", v)),
            ("printer", t("f.printer"), [(p, mark(p, self.printer0)) for p in self.printers], self.printer,
             self._set_printer),
            ("nozzle", t("f.nozzle"), nozzles, self.nozzle if len(nozzles) > 1 else "auto",
             lambda v: setattr(self, "nozzle", v)),
            ("nozzle_size", t("f.nozzle_size"), [(s, f"{s} mm") for s in sizes], self.size, self._set_size),
            # the filament is never blocked (2026-11-23): every filament the tool makes is this one, in its colours
            ("filament", t("f.filament"), [(f, f) for f in fils], self.filament, self._set_filament),
            ("colors", t("f.colors"), self._colour_opts(self.printer),
             ("model", "") if self.colour_mode == "model" else ("mix", self.mix) if self.colour_mode == "mix"
             else ("manual", self.proj_hex()), self._set_colours),
            ("process", t("f.process"), [(p, p) for p in procs], self.process, lambda v: setattr(self, "process", v)),
            ("support", t("f.support"), modes, self.support, lambda v: setattr(self, "support", v)),
            ("brim", t("f.brim"), modes, self.brim, lambda v: setattr(self, "brim", v)),
            ("walls", t("f.walls"), walls, self.walls, lambda v: setattr(self, "walls", v)),
            ("infill", t("f.infill"), infill, self.infill, lambda v: setattr(self, "infill", v)),
            ("parts", t("f.parts"), None, None, None),
            ("duplicates", t("f.duplicates"), [(n, f"{n} ×") for n in range(1, self.sb.MAX_COPIES + 1)],
             self.duplicates, lambda v: setattr(self, "duplicates", v)),
            ("max_plates", t("f.max_plates"), [(n, t("v.no_limit") if n == 0 else t("v.plate") if n == 1 else
                                               t("v.plates", n=n)) for n in PLATES], self.max_plates,
             lambda v: setattr(self, "max_plates", v)),
            # 2026-11-22: language first, then Open in Bambu Studio, then Background Bambu Studio
            ("language", t("f.language"), list(LANGS.items()), language(), self._set_language),
            ("open", t("f.open"), yes_no, self.open, lambda v: setattr(self, "open", v)),
            ("prestart", t("f.prestart"), yes_no, self.prestart_sel, self._pick_prestart),
        ]

    # the form's sections: (title key, number of fields), in the order of fields()
    # 2026-11-21: "Print Settings" became "Quality Settings", and the parts (later also duplicates and the
    # maximum number of plates) went to their own "Volume Settings"
    SECTIONS = (("s.presets", 1), ("s.printer", 5), ("s.quality", 5), ("s.volume", 3), ("s.other", 3))

    def objects(self) -> int:
        """How many objects the chosen parts, copies and duplicates make."""
        return self.duplicates * sum(self.copies.get(n, 1) for n in self.parts if n not in self.skip)

    def _shown(self, f) -> str:
        key, _, opts, value, _ = f
        if key == "parts":
            on = [n for n in self.parts if n not in self.skip]
            total = self.objects()
            if total != len(on):                          # duplicates or copies: how many objects that makes
                return t("v.objects", on=len(on), all=len(self.parts), n=total)
            return t("v.parts", on=len(on), all=len(self.parts))
        return next((lab for v, lab in opts if v == value), str(value or "-"))

    def _hint(self, key: str) -> str:
        _, fils, _ = self._lists(self.printer)
        if key == "colors":
            far = self.far_parts()                        # never silently in another colour (2026-11-22)
            hexes, names = self.slot_colours()
            if self.colour_mode == "mix":
                k = sum(1 for n in names if "%" not in n.get("en", ""))
                text = t("h.mix", k=k, m=len(hexes) - k, bases=", ".join(n.get("en", "") for n in names[:k]))
            else:
                text = t("h.colours2", n=len(hexes))
            far_key = "h.mix_far" if self.colour_mode == "mix" else "h.colours_far2"
            return text + (" " + t(far_key, n=len(far)) if far else "")
        text = t(f"h.{key}", n=len(fils) if key == "filament" else PRESET_SLOTS if key == "preset"
                 else len(self.printers))
        if key == "parts":                                # why Parts has a ⚠ (2026-11-23)
            text = " ".join([text] + self._warnings().get("parts", []))
        return text

    # --- drawing ------------------------------------------------------------------------------------------------
    draw = staticmethod(_draw)

    def header(self) -> list[str]:
        """The Bambu Studio status (the version checks), faint (2026-11-18: smaller than the menu); in the
        banner beside the nozzle when it fits (see _head)."""
        return _status_lines(self.status)

    def side(self) -> int:
        """The first lines of form_lines() that go beside the nozzle when the full header fits: the status lines and
        the blank line under them (_beside drops that one). In a header that does not fit they stay above the project
        line, with the blank line between (2026-11-22: they stood against it)."""
        return len(self.header()) + 1

    def project_line(self) -> str:
        """The project name in bold as "Project: name", right above the menu (2026-11-22; before, it
        stood in the banner beside the nozzle). 2026-11-20: normal letters, easier to read than the double-height
        font."""
        return f"  {BOLD}{_clip(t('f.project', name=self.title), _cols() - 4)}{RESET}"

    def _status_width(self) -> int:
        return max((5 + len(line) for line in self.status["lines"]), default=0) + 2   # indent, icon (2), two spaces

    banner = staticmethod(_banner)

    def screen(self) -> list[str]:
        lines = self.form_lines()
        banner, rest = _head(lines, self.side(), scroll=True)
        sel = self._sel_line - (len(lines) - len(rest))    # the selected row in the part under the header
        # the header stays on top, only the form under it scrolls (2026-11-23)
        return banner + _scroll(rest, sel, self._foot, max(1, _rows() - len(banner)))

    def _layout(self, fs) -> tuple[int, int]:
        """(label column, value column) when the console is wide enough: the value column at least 34, and wide
        enough that the menu is a bit wider than the status line above it. The menu is then their sum + MENU_EXTRA."""
        width = max(len(f[1]) for f in fs) + 2
        return width, max(34, self._status_width() + 2 - (width + 7))

    def form_lines(self) -> list[str]:
        fs = self.fields()
        lines = self.header() + ["", self.project_line()]   # the blank line goes with the status (see side)
        width, room = self._layout(fs)
        # a narrower console: the values give way. 3 = the rules' indent of 2 + the last column, never written
        room = max(8, min(room, _cols() - width - MENU_EXTRA - 3))
        menu = min(room + width + MENU_EXTRA, _cols() - 3)   # the menu's width: its rules, and the buttons span it
        rule = f"  {GREY}{'─' * menu}{RESET}"
        starts = {}
        first = 0
        for title, count in self.SECTIONS:
            starts[first] = title
            first += count
        lines.append(rule)
        warned = self._warnings()
        for i, f in enumerate(fs):
            if i in starts:
                if i:
                    lines += [rule]
                lines.append(f"  {BOLD}{t(starts[i])}{RESET}")
            value = _clip(self._shown(f), room)
            cell = f"{value:<{room}}"
            badge = self._badge(i == self.row) if f[0] == "prestart" else (1, "⚠") if f[0] in warned else None
            if badge and len(value) + 2 + badge[0] <= room:   # the state at the right end of the value (2026-11-23)
                cell = value + " " * (room - len(value) - badge[0]) + badge[1]
            # two spaces between a symbol and the text (2026-11-21: they stood against it); ◄ ► and not ◀ ▶,
            # which Consolas, the font of Windows' own console, does not have (2026-11-23: boxes with a ?)
            text = f"{f[1]:<{width}} ◄  {cell}  ►" if f[2] is not None else \
                f"{f[1]:<{width}}    {cell}  …"
            if i == self.row:
                self._sel_line = len(lines)
            # a field with a warning in orange (2026-11-23); the selected row stays white on blue, easier to read
            lines.append(f"  {SEL} {text} {RESET}" if i == self.row else f"   {ORANGE}{text}{RESET}"
                         if f[0] in warned else f"   {text}")
        lines.append(rule)
        n = len(fs)
        if self.row >= n:                                 # a button: the row of buttons
            self._sel_line = len(lines)
        labels = [t(k) for k in BUTTONS]
        under = [_underline(b, k) for b, k in zip(labels, _button_keys())]   # the shortcut letter (2026-11-23)
        if 3 + sum(len(b) + 4 for b in labels) + 3 * (len(labels) - 1) < _cols():
            # spread over the menu, not the console (2026-11-21: in a wide terminal they went to its edge):
            # the last button ends where the rules end (they start in column 3, the buttons in column 4)
            # the rest of the division goes to the first gaps, so the right edge lines up exactly
            spare = max(3 * (len(labels) - 1), menu - 1 - sum(len(b) + 4 for b in labels))
            base, extra = divmod(spare, len(labels) - 1)
            row = ""
            for j, b in enumerate(under):
                row += (" " * (base + (j <= extra)) if j else "") + (
                    f"{SEL}[ {b}{SEL} ]{RESET}" if self.row == n + j else f"[ {b} ]")
            lines.append("   " + row)
        else:                                             # a narrow console: no brackets, so the row does not wrap
            lines.append(" " + " ".join(f"{SEL} {b}{SEL} {RESET}" if self.row == n + j else f" {b} "
                                        for j, b in enumerate(under)))
        lines.append(rule)
        # the key legend right under the buttons, a blank line, then up to two wrapped hint lines
        legend = _legend(t("help.form"), "")
        self._foot = FOOT_LINES + len(legend)             # what stays at the bottom when the form scrolls
        lines += [""] + legend + [""]
        hint = self.note or (self._hint(fs[self.row][0]) if self.row < n else t("h.make") if self.row == n
                             else t("h.preview") if self.row == n + 1 else "")
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", hint) if s]
        plain = [s for s in sentences if not s.startswith("⚠")]
        if len(plain) > 2:                                # merged without the warnings, so those stay recognised
            plain = [plain[0], " ".join(plain[1:])]       # (2026-11-22: a third sentence hid the colour warning)
        sentences = plain + [s for s in sentences if s.startswith("⚠")]
        # a warning sentence (Background Bambu Studio: extra load on the PC) is always shown, in orange, and the rest
        # gets the lines left over (2026-11-22: in the narrow SOMA terminal the warning was cut off)
        wrap = lambda s: textwrap.wrap(s, max(1, _cols() - 6))   # noqa: E731
        warn = [line for s in sentences if s.startswith("⚠") for line in wrap(s)][:2]
        rest = [line for s in sentences if not s.startswith("⚠") for line in wrap(s)]
        room = 2 - len(warn)
        if len(rest) > room:
            rest = rest[:room]
            if rest:
                rest[-1] = _clip(rest[-1] + " …", max(1, _cols() - 6))
        hint_lines = rest + warn
        lines += [f"  {ORANGE if line.startswith('⚠') else GREY}{line}{RESET}"
                  for line in hint_lines + [""] * (2 - len(hint_lines))]
        return lines

    # --- lists --------------------------------------------------------------------------------------------------
    def pick(self, title: str, opts: list, current):
        """The full list, chosen with the arrow keys (no typing: 2026-11-18); `current` on Esc."""
        pos = next((i for i, (v, _) in enumerate(opts) if v == current), 0)
        while True:
            legend = _legend(t("help.list"))
            room = max(1, _rows() - 4 - len(legend))
            top = min(max(0, pos - room // 2), max(0, len(opts) - room))
            lines = [f"  {BOLD}{_clip(title, _cols() - 4)}{RESET}", ""]
            for i in range(top, min(len(opts), top + room)):
                lab = _clip(str(opts[i][1]), _cols() - 6)
                lines.append(f"  {SEL} {lab} {RESET}" if i == pos else f"   {lab}")
            lines += [""] + legend
            self.draw(lines)
            k = _key()
            if k == "esc":
                return current
            if k == "enter" and opts:
                return opts[pos][0]
            if k in ("up", "down", "pgup", "pgdn", "home", "end") and opts:
                pos = {"up": pos - 1, "down": pos + 1, "pgup": pos - room, "pgdn": pos + room, "home": 0,
                       "end": len(opts) - 1}[k]
                pos = max(0, min(pos, len(opts) - 1))
            elif len(k) == 1 and k.isprintable() and not k.isspace() and opts:   # a letter: next item starting with it
                n = len(opts)
                pos = next((j for j in ((pos + 1 + i) % n for i in range(n))
                            if _jump_text(opts[j][1]).startswith(k.lower())), pos)

    def pick_parts(self) -> None:
        pos = 0
        while True:
            # two lines: it did not fit the SOMA terminal (2026-11-22). C: the part's colour from a list (2026-11-23)
            legend = _legend(t("help.parts_c"))
            room = max(1, _rows() - 4 - len(legend))
            top = min(max(0, pos - room // 2), max(0, len(self.parts) - room))
            lines = [f"  {BOLD}{t('f.parts')}{RESET}", ""]
            hexes, names = self.slot_colours()
            far = set(self.far_parts())
            for i in range(top, min(len(self.parts), top + room)):
                n = self.parts[i]
                c = self.copies.get(n, 1)
                f, _ = self.part_filament(n)              # the colour it prints in: its filament's, by Bambu's name
                sold = self.sb.official_name(names[f - 1]) if 0 < f <= len(names) else ""
                col = sold or self.colour_label(self.sb.hex_srgb(hexes[f - 1]) if 0 < f <= len(hexes) else None)
                mark = f" ({t('v.col_own')})" if n in self.own_col else ""
                fil = f"  ·  {col}{mark}" + ("  ⚠" if n in far else "")
                item = _clip(f"{'[ ]' if n in self.skip else '[x]'}  {f'{c} ×  ' if c > 1 else ''}{n}{fil}", _cols() - 6)
                lines.append(f"  {SEL} {item} {RESET}" if i == pos else f"   {item}")
            lines += [""] + legend
            self.draw(lines)
            k = _key()
            if k in ("enter", "esc"):
                return
            if k == "up":
                pos = max(0, pos - 1)
            elif k == "down":
                pos = min(max(0, len(self.parts) - 1), pos + 1)
            elif k == " " and self.parts:
                self.skip ^= {self.parts[pos]}
            elif k in ("left", "right") and self.parts:  # copies of this part (2026-11-21)
                n = self.parts[pos]
                self.copies[n] = max(1, min(self.sb.MAX_COPIES, self.copies.get(n, 1) + (1 if k == "right" else -1)))
            elif _digit(k) and self.parts:              # a number typed in (2026-11-22: any number)
                n = self.parts[pos]
                self.copies[n] = self.ask_number(t("f.copies", name=n), k, self.copies.get(n, 1))
            elif k.lower() == "a":
                self.skip = set()
            elif k.lower() == "n":
                self.skip = set(self.parts)
            elif k.lower() == "c" and self.parts:       # colour from a list: Bambu's colours of the filament (2026-11-23)
                n = self.parts[pos]
                first = t("v.col_model") if self.colour_mode == "model" else \
                    t("v.col_project", name=self.colour_label(self.sb.hex_srgb(self.proj_hex())))
                cur = self.own_col.get(n) or ""
                try:                                      # an older own colour (a name): shown on its nearest
                    rgb = self.sb.parse_colour(cur) if cur else None
                except self.sb.ToolError:
                    rgb = None
                if rgb:
                    cur = self.sb.snap_colours([rgb], [(h, {}) for h, _ in self.colour_list()])[0][0]
                v = self.pick(t("f.colour_of", name=n), [("", first)] + self.colour_list(), cur)
                if v:
                    self.own_col[n] = v.lower()
                else:
                    self.own_col.pop(n, None)             # back to the project's / the model's colour
                self.fil.pop(n, None)                     # a colour chosen: the part goes by colour again

    # --- the loop -----------------------------------------------------------------------------------------------
    def run(self) -> list[str]:
        """Until "Generate" (returns the tool options) or Cancel / Esc (raises Cancel)."""
        while True:
            fs = self.fields()
            n = len(fs)
            if self.prestart_sel != self.prestart and (self.row >= n or fs[self.row][0] != "prestart"):
                self.prestart_sel = self.prestart         # left the field without Enter: back to what is in effect
                fs = self.fields()
            self._bg = self._bg_state()
            self.draw(self.screen())
            k = _key(self._tick)
            self.note = ""                                # a message stays until the next key
            if k == "esc":
                raise Cancel
            nb = len(BUTTONS)
            keys = _button_keys().lower()
            if len(k) == 1 and k.lower() in keys:         # G, A, C: the button at once, from any row (2026-11-23)
                self.row, k = n + keys.index(k.lower()), "enter"
            if k in ("up", "down", "tab"):
                self.row = (self.row + (-1 if k == "up" else 1)) % (n + nb)
                continue
            if self.row >= n:                             # the buttons: Generate, Analyze, Cancel
                if k in ("left", "right"):
                    self.row = n + (self.row - n + (1 if k == "right" else -1)) % nb
                elif k == "enter":
                    if self.row == n + 2:
                        raise Cancel
                    if len(self.skip) >= len(self.parts):
                        self.status = {"ok": False, "lines": [t("run.no_parts")]}
                        continue
                    total = self.objects()
                    if total > self.sb.MAX_OBJECTS:       # the tool refuses it too; here before anything is made
                        self.note = t("e.too_many", n=total, max=self.sb.MAX_OBJECTS)
                        continue
                    if self.row == n + 1:
                        self.preview()
                        continue
                    return self.options()
                continue
            key, label, opts, value, setter = fs[self.row]
            if key == "prestart" and k == "enter":        # ←→ only picks, Enter starts or closes it (2026-11-23)
                if self.prestart_sel != self.prestart:
                    self._set_prestart(self.prestart_sel)
                continue
            if key == "preset" and k == "enter":          # ←→ picks the slot (below), Enter loads it, S saves in it
                self.load_preset()
                continue
            if key == "preset" and k in ("s", "S"):
                self.save_preset()
                continue
            if key == "parts":
                if k in ("enter", "right", "left"):
                    self.pick_parts()
                continue
            if key == "duplicates":                       # 1..MAX_COPIES: ←→ by one (no wrap round), Enter or a
                if k in ("left", "right"):                # digit types the number (2026-11-22)
                    self.duplicates = max(1, min(self.sb.MAX_COPIES, self.duplicates + (1 if k == "right" else -1)))
                elif k == "enter" or _digit(k):
                    self.duplicates = self.ask_number(label, "" if k == "enter" else k, self.duplicates)
                continue
            values = [v for v, _ in opts]
            if not values:                                # no Bambu Studio profiles for this printer: nothing to pick
                continue
            i = values.index(value) if value in values else 0
            if k in ("left", "right"):
                setter(values[(i + (1 if k == "right" else -1)) % len(values)])
            elif k == "enter":
                setter(self.pick(label, opts, value))

    # --- presets (2026-11-21) ----------------------------------------------------------------------
    def preset_values(self) -> dict:
        """Every setting of the form except the parts (they belong to one model) and the language."""
        return {"printer": self.printer, "nozzle": self.nozzle, "nozzle_size": self.size, "filament": self.filament,
                "colour_mode": self.colour_mode, "colour": self.proj_col, "mix": self.mix, "process": self.process,
                "support": self.support, "brim": self.brim,
                "walls": self.walls, "infill": self.infill, "open": self.open, "duplicates": self.duplicates,
                "max_plates": self.max_plates}

    def save_preset(self) -> None:
        slots = _presets()
        old = slots[self.preset]
        name = self.ask_text(t("ps.title", n=self.preset + 1),
                             (old or {}).get("name") or f"{self.filament} {self.process}")
        if name is None:
            return
        slots[self.preset] = {"name": name, "values": self.preset_values()}
        self.note = t("n.saved", n=self.preset + 1, name=name) if save_setting("presets", slots) else t("n.not_saved")

    def load_preset(self) -> None:
        """The slot's settings, as far as this PC has them: a printer without a template, or a nozzle size, filament
        or process the printer does not have, stays as it was, and the message says which."""
        p = _presets()[self.preset]
        if not p:
            self.note = t("n.empty", n=self.preset + 1)
            return
        v, kept = p["values"], []
        own = {"filament": self.filament, "process": self.process}   # a printer change may reset them on the way
        if v.get("printer") in self.printers:
            if v["printer"] != self.printer:
                self._set_printer(v["printer"])
        elif v.get("printer"):
            kept.append(f"{t('f.printer')} {v['printer']}")
        size = str(v.get("nozzle_size") or "")
        if size in self.sizes(self.printer):
            if size != self.size:
                self._set_size(size)
        elif size:
            kept.append(f"{t('f.nozzle_size')} {size} mm")
        if "colour_mode" in v:                            # Auto, Mix or Manual with the project's colour (2026-11-23)
            self.colour_mode = v["colour_mode"] if v["colour_mode"] in ("model", "mix") else "manual"
            if self.colour_mode == "mix":
                self.mix = str(v.get("mix") or "CMYKW").upper()
                if not self._mix_ok(self.printer, self.mix):
                    kept.append(f"{t('f.colors')} {self.mix}")
                    self.colour_mode = "model"
            col = str(v.get("colour") or "")
            try:
                self.sb.parse_colour(col)
                self.proj_col = col
            except self.sb.ToolError:
                kept.append(f"{t('f.colors')} {col}")
        _, fils, procs = self._lists(self.printer)
        for key, have in (("filament", fils), ("process", procs)):
            if v.get(key) in have:
                setattr(self, key, v[key])
            else:
                if own[key] in have:                      # still valid on the final printer and size: keep it
                    setattr(self, key, own[key])
                if v.get(key):
                    kept.append(f"{t('f.' + key)} {v[key]}")
        # only values the form's own lists hold (a hand-edited file); bools are not numbers here
        for key, allowed in (("nozzle", ("auto", "left", "right")), ("support", MODES), ("brim", MODES),
                             ("walls", WALLS), ("infill", INFILL), ("open", (True, False)),
                             ("duplicates", range(1, self.sb.MAX_COPIES + 1)), ("max_plates", PLATES)):
            if key not in v:
                continue
            val = v[key]
            ok = (isinstance(val, bool) if key == "open" else not isinstance(val, bool)) and val in allowed
            if ok:
                setattr(self, key, val)
            else:
                kept.append(f"{t('f.' + key)} {val}")
        self.note = t("n.loaded", n=self.preset + 1, name=p.get("name") or "") + (
            " " + t("n.kept", what=", ".join(kept)) if kept else "")

    def ask_text(self, title: str, text: str) -> str | None:
        """A short name, typed in (Backspace deletes); None on Esc or when left empty."""
        text = text[:PRESET_NAME_MAX]
        while True:
            self.draw([f"  {BOLD}{_clip(title, _cols() - 4)}{RESET}", "",
                       f"  {t('ps.name')}{text}\x1b[7m \x1b[27m", "",
                       f"  {GREY}{_clip(t('help.name'), _cols() - 4)}{RESET}"])
            k = _key()
            if k == "esc":
                return None
            if k == "enter":
                return text.strip() or None
            if k == "back":
                text = text[:-1]
            elif len(k) == 1 and k.isprintable() and len(text) < PRESET_NAME_MAX:
                text += k

    def ask_number(self, title: str, text: str, current: int) -> int:
        """A whole number 1..MAX_COPIES, typed in (digits, Backspace deletes); `current` on Esc or when left empty.
        A number above the maximum is not taken: the line says the range."""
        hi = self.sb.MAX_COPIES
        while True:
            n = int(text) if text else 0
            msg = t("n.range", hi=hi)
            self.draw([f"  {BOLD}{_clip(title, _cols() - 4)}{RESET}", "",
                       f"  {t('ps.number')}{text}\x1b[7m \x1b[27m", "",
                       f"  {(ORANGE if n > hi else GREY)}{_clip(msg, _cols() - 4)}{RESET}",
                       f"  {GREY}{_clip(t('help.name'), _cols() - 4)}{RESET}"])
            k = _key()
            if k == "esc":
                return current
            if k == "enter":
                if 1 <= n <= hi:
                    return n
                if not text:
                    return current
            elif k == "back":
                text = text[:-1]
            elif _digit(k) and len(text) < len(str(hi)) + 1:
                text = (text + k).lstrip("0")

    def preview(self) -> None:
        """Preview: the tool makes the project with the choices on screen in a temporary folder and Bambu Studio
        slices it; then plates, print time and filament, until a key brings the form back. Nothing is saved."""
        import msvcrt
        import threading
        import time
        full = self.header() + ["", f"  {BOLD}{t('pv.title')}{RESET}"]
        banner, head = _head(full, len(self.header()), 1)
        row = len(banner) + len(head) + 1                 # console row (1-based) of the progress line
        self.draw(banner + head + [f"  {GREY}{_clip(t('pv.preparing', s=0), _cols() - 4)}{RESET}"])
        state = {"slicing": False, "stop": False}

        def tick(seconds: float) -> bool:                 # from the tool, every 0.2 s while Bambu Studio slices
            state["slicing"] = True
            return state["stop"]                          # True: the tool stops Bambu Studio (PreviewStopped)

        def progress(console, t0: float) -> None:
            """The seconds since Preview was pressed, and what it is doing (2026-11-19: the time
            seemed to stand still while the parts were prepared, before Bambu Studio started)."""
            key = "pv.stopping" if state["stop"] else "pv.slicing" if state["slicing"] else "pv.preparing"
            console.write(f"\x1b[{row};1H\x1b[2K  {GREY}{_clip(t(key, s=int(time.time() - t0)), _cols() - 4)}{RESET}")
            console.flush()
            while msvcrt.kbhit():
                c = msvcrt.getwch()
                if c in ("\x00", "\xe0"):                 # arrow and other special keys come as two characters
                    msvcrt.getwch()
                elif c in ("\x1b", "\x03"):
                    state["stop"] = True

        body: list[str]
        try:
            args = self.sb._parser().parse_args(self.options())
            box: dict = {}

            def work() -> None:
                try:
                    box["res"] = self.sb.preview(self.ws, args, tick)
                except BaseException as e:                # handed to the form below
                    box["err"] = e

            # the tool works in a thread so that the time counts on while it prepares the parts. preview() turns
            # sys.stdout into a buffer meanwhile (for the whole process): the counter writes to the console itself
            console, t0 = sys.stdout, time.time()
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            while worker.is_alive():
                try:
                    progress(console, t0)
                    worker.join(0.2)
                except KeyboardInterrupt:                 # Ctrl+C reaches Bambu Studio too: wait for the tool to end
                    state["stop"] = True
            if "err" in box:
                raise box["err"]
            res = box["res"]
            body = []
            note = [f"  {GREY}{w}{RESET}" for w in textwrap.wrap(t("pv.note"), max(20, _cols() - 4))]
            noted = False
            for line in self.sb.preview_lines(res):
                if line.startswith(("⚠", "ℹ")) and not noted:   # the note sits above the warnings
                    body += note + [""]
                    noted = True
                if line.startswith(("⚠", "ℹ")):           # Bambu Studio's warnings can be long: wrapped, not cut;
                    wrapped = textwrap.wrap(line, max(20, _cols() - 6), subsequent_indent="  ") or [""]
                    colour = ORANGE if line.startswith("⚠") else GREY   # its standard notes in grey: nothing to do
                    body += [f"  {colour}{w}{RESET}" for w in wrapped[:4]]
                else:
                    body.append(f"  {_clip(line, _cols() - 4)}")
            if not any(l.startswith("⚠") for l in self.sb.preview_lines(res)):
                body += ["", f"  {FAINT}{ACCENT}✅  {t('pv.nowarn')}{RESET}"]
            if not noted:
                body += [""] + note
        except self.sb.PreviewStopped:
            body = [f"  {t('pv.stopped')}"]
        except KeyboardInterrupt:                        # Ctrl+C reaches the form too: the slicing was killed
            body = [f"  {t('pv.stopped')}"]
        except self.sb.ToolError as e:                    # e.g. Bambu Studio refused to slice: its own message
            body = [f"  {ORANGE}{w}{RESET}" for w in textwrap.wrap(f"⚠  {e}", max(20, _cols() - 6))]
        except SystemExit:                                # argparse refused an option (a bug, but keep the form)
            body = [f"  {ORANGE}⚠  options{RESET}"]
        except Exception as e:                            # a crash in the preview must not close the form
            body = [f"  {ORANGE}{w}{RESET}" for w in textwrap.wrap(f"⚠  {type(e).__name__}: {e}", max(20, _cols() - 6))]
        # the header stays (2026-11-23: in a cmd window of 30 rows it gave way to the results), and results taller than
        # the rows under it scroll with ↑↓ (they were cut with "…": the plates and warnings did not show)
        foot = ["", f"  {_clip(t('pv.back'), _cols() - 4)}"]
        banner, head = _head(full, len(self.header()), len(body) + len(foot), scroll=True)
        room = max(1, _rows() - len(banner) - len(head) - len(foot))
        if len(body) > room:
            foot[-1] = f"  {_clip(t('pv.back_scroll'), _cols() - 4)}"
        while msvcrt.kbhit():                             # keys pressed while it sliced do not count
            msvcrt.getwch()
        off = 0
        while True:
            view = body[off:off + room]
            if off > 0:
                view[0] = f"  {GREY}▲{RESET}"
            if off + room < len(body):
                view[-1] = f"  {GREY}▼{RESET}"
            self.draw(banner + head + view + foot)
            k = _key()
            if len(body) > room and k in ("up", "down", "pgup", "pgdn", "home", "end"):
                last = len(body) - room
                off = {"up": off - 1, "down": off + 1, "pgup": off - room, "pgdn": off + room, "home": 0,
                       "end": last}[k]
                off = max(0, min(off, last))
                continue
            break

    def options(self) -> list[str]:
        """The choices as orientr options (only the printer and the parts that differ from bambu.json)."""
        args = []
        if self.colors:                                   # a colour template: it sets the printer too
            if self.colors != self.colors0:
                args += ["--set", f"template={self.colors}"]
        elif self.printer != self.printer0 or self.colors0:   # back from colours: the printer's own template
            args += ["--printer", self.printer]
        args += ["--set", f"nozzle_size={self.size}", "--set", f"material={self.filament}",
                 "--set", f"process={self.process}", "--set", "layer_height=",
                 "--set", f"walls={self.walls or ''}", "--set", f"infill={self.infill + '%' if self.infill else ''}",
                 "--set", f"support={self.support}", "--set", f"brim={self.brim}",
                 "--set", f"nozzle={self.nozzle if len(self._lists(self.printer)[0].nozzle_boxes) >= 2 else 'auto'}",
                 "--set", "check=yes", "--set", f"open={'yes' if self.open else 'no'}",
                 "--set", f"duplicates={self.duplicates}", "--set", f"max_plates={self.max_plates}",
                 "--set", f"colours={self.colour_mode}",
                 "--set", f"colour={self.proj_hex() if self.colour_mode == 'manual' else ''}",
                 "--set", f"mix={self.mix if self.colour_mode == 'mix' else ''}"]
        for n in self.parts:
            if n in self.skip and n not in self.skip0:
                args += ["--skip", n]
            elif n not in self.skip and n in self.skip0:
                args += ["--include", n]
            if self.copies.get(n, 1) != self.copies0.get(n, 1):
                args += ["--copies", f"{n}={self.copies[n]}"]
            if self.fil.get(n) != self.fil0.get(n):
                args += ["--filament", f"{n}={self.fil.get(n) or 'auto'}"]
            if self.own_col.get(n) != self.own_col0.get(n):
                args += ["--colour", f"{n}={self.own_col.get(n) or 'auto'}"]
        return args + ["--check"] + (["--open"] if self.open else [])


def run(ws: Path, sb, wait_at_end: bool = False) -> int:
    """Show the form, then make the project with the tool; a refused choice brings the form back. `wait_at_end` (its
    own window): wait for a key only when it went wrong, so the message can be read; made or cancelled, the window
    closes at once (2026-11-22)."""
    import orientr_banner
    if os.name != "nt" or not orientr_banner.enable_ansi():
        print(t("run.windows_only"))
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.stdout.write("\x1b[?1049h\x1b[?25l")              # own screen, no cursor
    on_own_screen, result, building = True, {"status": "cancelled"}, False
    try:
        # the form's lists need Bambu Studio's profiles: without the cache (after a Studio update) that takes about
        # 2 minutes, so say so instead of a blank window (2026-11-22)
        sb.announce_profiles(lambda text: (sys.stdout.write(f"\x1b[H\x1b[2J\n  {text}"), sys.stdout.flush()))
        form = Form(ws, sb.read_config(ws), sb)
        if (ws / "output" / "bambu").is_dir():           # tidy a folder an earlier version wrote (.gitignore,
            sb.keep_out_of_history(ws / "output" / "bambu")   # no leftover last-run.json)
        sb.preload_libraries()                          # CadQuery and scipy load while you choose (2026-11-22)
        if form.open and form.prestart:                   # Bambu Studio starts meanwhile, hidden
            sb.prestart_studio()                          # (2026-11-21, and only when switched on in the form)
        _fit_own_console(form)
        lines = form.form_lines()                         # the header grows in once, then stays on top
        banner, rest = _head(lines, form.side(), scroll=True)   # as Form.screen chooses it
        _animate_banner(banner, lines[:len(lines) - len(rest)])
        while True:
            try:
                args = form.run()
            except Cancel:
                break
            sys.stdout.write("\x1b[?1049l\x1b[?25h")      # back to the normal screen for the tool's output
            on_own_screen = False
            _fixed_banner()                               # the header stays on top while it works (2026-11-23)
            print(t("run.making"))
            building = True
            try:
                rc = sb.main(args)
                _free_banner()
                result = {"status": "made" if rc == 0 else "error", "options": args}
                break
            except sb.ToolError as e:                     # refused: show it, then the form again
                building = False
                print(f"\n{ORANGE}{t('run.error', msg=cap(e))}{RESET}\n{t('run.back')}")
                _key()
                _free_banner()
                form.rebase(sb.read_config(ws))           # the tool may have saved part of the choices already
                form.status = {"ok": False, "lines": [str(e).splitlines()[0]]}
                sys.stdout.write("\x1b[?1049h\x1b[?25l")
                on_own_screen = True
    except KeyboardInterrupt:
        result = {"status": "error", "message": "interrupted while making the project"} if building else \
            {"status": "cancelled"}
    except Exception as e:                                # a crash is shown as an error, not as "cancelled"
        result = {"status": "error", "message": f"{type(e).__name__}: {e}"}
    finally:                                              # (a hidden prestarted Studio: bambu_studio.py's guard)
        _free_banner()
        sys.stdout.write("\x1b[?25h" + ("\x1b[?1049l" if on_own_screen else ""))
        sys.stdout.flush()
    if result["status"] == "cancelled":
        print(t("run.cancelled"))
    elif result["status"] == "error" and result.get("message"):
        print(f"{ORANGE}{t('run.error', msg=cap(result['message']))}{RESET}")
    if wait_at_end and result["status"] == "error":
        print(f"\n{t('run.done')}")
        try:
            _key()
        except KeyboardInterrupt:
            pass
    return 0 if result["status"] in ("made", "cancelled") else 1
