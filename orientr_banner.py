# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""Animated header of Orientr's terminal form: the Orientr logo (a print nozzle above an orange cube on a build
plate, the plate's edge running on as the baseline of the wordmark "orientr") builds up from the bottom, then the
baseline with the wordmark and the title wipe in from the left (about 1 s).

Only in a real terminal with colour (Windows 10+ console or Windows Terminal); otherwise nothing is shown, so piped
runs and tests stay plain. Set ORIENTR_NO_ANIMATION=1 to show the header without the animation.
Run this file on its own to see it: python orientr_banner.py

One logo for every terminal (the Orientr design of 2026-11-22): the
lockup is 59 columns wide, 61 with the indent; the title and the version checks stay inside it, so it fits the own
window and the SOMA terminal (63 columns) alike. For a console too narrow or too low for it the compact header of the
design: "◆ Orientr" and the title on one line. The title appears only here (and in the
GitHub description; 2026-11-22); everywhere else the tool is just "Orientr".
"""
from __future__ import annotations

import os
import sys
import time

ACCENT = (40, 120, 220)       # Orientr blue: the status line
GREY = (139, 149, 161)        # the subtitle (the user's refined design, 2026-11-23)
# The title (user's text, 2026-11-23): in the full header on two lines above the wordmark (TITLE below), in the
# compact header on one line.
SUBTITLE = "Export From SOMA to Bambu, Print-Ready"
SUBTITLE_SHORT = SUBTITLE

# The colours of the user's refined design (2026-11-23, orientr_logo.py): W plate outline and baseline in the
# terminal's own text colour (None: light on a dark terminal, dark on a light one), N/G the nozzle's light and shaded
# side (mid tones, readable on both), T/L/R the cube's top, left and right (L is also the dot on the i), P the plate,
# B the wordmark's blue.
PALETTE = {"W": None, "N": (200, 209, 219), "G": (128, 141, 156), "T": (255, 154, 115), "L": (255, 107, 61),
           "R": (201, 74, 34), "P": (42, 67, 102), "B": (76, 154, 255)}
# The lockup as the user refined it (2026-11-23): 59 x 24 pixels, drawn with half blocks (two pixels per character),
# 12 rows. The first MARK_W columns are the logo itself, the rest the baseline and the wordmark.
LOCKUP = [
    "...........NNGG............................................",
    "...........NNGG............................................",
    "...........NNGG............................................",
    "...........NNGG............................................",
    "............NG.............................................",
    "...........................................................",
    "...........................................................",
    "............TT.............................................",
    "..........TTTTTT...........BBB.......L..............B......",
    "........TTTTTTTTTT........B...B.....................B......",
    ".......LTTTTTTTTTTR.......B...B.B.BB.B..BBB..B.BB..BBB.B.BB",
    ".......LLLTTTTTTRRR.......B...B.BB...B.B...B.BB..B..B..BB..",
    ".......LLLLLTTRRRRR.......B...B.B....B.BBBBB.B...B..B..B...",
    ".......LLLLLLRRRRRR.......B...B.B....B.B.....B...B..B..B...",
    "......WLLLLLLRRRRRRW......B...B.B....B.B.....B...B..B..B...",
    "....WWPLLLLLLRRRRRRPWW.....BBB..B....B..BBBB.B...B...B.B...",
    "..WWPPPLLLLLLRRRRRRPPPWW...................................",
    "WWPPPPPLLLLLLRRRRRRPPPPPWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
    "..WWPPPPPLLLLRRRRPPPPPWW...................................",
    "....WWPPPPPLLRRPPPPPWW.....................................",
    "......WWPPPPPPPPPPWW.......................................",
    "........WWPPPPPPWW.........................................",
    "..........WWPPWW...........................................",
    "............WW.............................................",
]
MARK_W = 26                   # the logo's own columns
LOCKUP_W = len(LOCKUP[0])     # 59
# The layout of the user's markup of 2026-11-23, in the same 61 x 13 as before:
# - the title in the empty rows right of the nozzle, above the wordmark: TITLE on text rows TITLE_ROW and the next,
#   each line centred on the wordmark (an empty row above it and one between it and the wordmark);
# - the version checks under the baseline, right of the plate: on the text rows STATUS_ROWS (the lowest ones when
#   there are fewer lines), the lines centred on each other, the block as near the wordmark's middle as the plate's
#   edge and the header's width allow (status_place). That room follows the plate's slanting edge row by row, so a
#   version number a few characters longer still fits; one that does not fit puts the checks under the header.
# one colour (user, 2026-11-23), in bold and lighter than the grey so it stands out (a terminal has no bigger letters):
# the light side of the nozzle
TITLE_COLOUR = (200, 209, 219)
TITLE = [("Export From SOMA to Bambu", TITLE_COLOUR), ("Print-Ready", TITLE_COLOUR)]
TITLE_ROW = 1
STATUS_ROWS = (9, 10, 11)     # the rows under the baseline (row 8)
HEIGHT = len(LOCKUP) // 2 + 1  # 13: the lockup and an empty row


def _ink(y0: int, y1: int, x0: int, x1: int) -> list[int]:
    """The columns x0..x1-1 of the lockup that have a pixel on pixel rows y0..y1-1."""
    return [x for x in range(x0, x1) if any(LOCKUP[y][x] != "." for y in range(y0, y1))]


WORD_MID = (min(_ink(8, 16, MARK_W, LOCKUP_W)) + max(_ink(8, 16, MARK_W, LOCKUP_W)) + 1) / 2   # 42.5: the wordmark's middle


def _plate_end(row: int) -> int:
    """The first lockup column right of the logo on text row `row` (two pixel rows)."""
    return max(_ink(2 * row, 2 * row + 2, 0, MARK_W), default=-1) + 1


def _fg(c):
    """Text colour; None: the terminal's own text colour."""
    return "\x1b[39m" if c is None else f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m"


def _bg(c):
    return f"\x1b[48;2;{c[0]};{c[1]};{c[2]}m"


RESET = "\x1b[0m"
BOLD = "\x1b[1m"


def _pixel_rows(px: list[str]) -> list[str]:
    """Pixel art as text rows, two pixels per character (the terminal's own background where it has none), trailing
    blanks left off."""
    out = []
    for y in range(0, len(px), 2):
        line = ""
        for top, bottom in zip(px[y], px[y + 1]):
            if top == "." and bottom == ".":
                line += " "
            elif top == ".":
                line += _fg(PALETTE[bottom]) + "▄" + RESET
            elif bottom == "." or PALETTE[bottom] == PALETTE[top]:
                line += _fg(PALETTE[top]) + ("▀" if bottom == "." else "█") + RESET
            elif PALETTE[bottom] is None:                 # the terminal's own text colour can only be a text colour:
                line += _fg(None) + _bg(PALETTE[top]) + "▄" + RESET   # then that half is the character
            else:
                line += _fg(PALETTE[top]) + _bg(PALETTE[bottom]) + "▀" + RESET
        out.append(line.rstrip(" "))
    return out


def _lockup_rows(grown: int, cols: int) -> list[str]:
    """The lockup as text rows: of the logo only the lowest `grown` pixel rows (it builds up), of the baseline and
    the wordmark only the columns left of `cols` (they wipe in)."""
    h = len(LOCKUP)
    return _pixel_rows(["".join(c if (x < MARK_W and y >= h - grown) or (MARK_W <= x < cols) else "."
                                for x, c in enumerate(row)) for y, row in enumerate(LOCKUP)])


def _visible(text: str) -> int:
    import re
    return len(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text))


def _width(text: str) -> int:
    """Screen columns of a line: colour codes take none, an emoji (✅) two."""
    return _visible(text) + text.count("✅")


def _put(rows: list[str], i: int, col: int, text: str) -> None:
    """`text` into row i from (screen) column col on; rows below the end are added."""
    while len(rows) <= i:
        rows.append("")
    rows[i] += " " * max(0, col - _visible(rows[i])) + text


def status_place(lines: list[str], indent: int = 2) -> list[tuple[int, int]] | None:
    """(text row, screen column) of each version check under the baseline (see STATUS_ROWS), or None when they do not
    fit there: too many lines, or one too long for the room between the plate's edge (one empty column after it) and
    the header's right edge (the header never gets wider). Each line is centred on one common middle, as near the
    wordmark's middle as that room allows. The shortest line goes on top: the plate's edge slants away to the left, so
    the lowest row has the most room (as in the user's markup). The result is in the order of `lines`."""
    if len(lines) > len(STATUS_ROWS):
        return None
    widths = [_width(s) for s in lines]
    free = STATUS_ROWS[len(STATUS_ROWS) - len(lines):]
    rank = sorted(range(len(lines)), key=lambda k: widths[k])
    rows = [free[rank.index(k)] for k in range(len(lines))]
    lows = [indent + _plate_end(r) + 1 for r in rows]    # each line's first possible column
    high = indent + LOCKUP_W                              # the first column past the header
    lo = max((a + w / 2 for a, w in zip(lows, widths)), default=0)
    hi = min((high - w / 2 for w in widths), default=0)
    if lo > hi:
        return None
    mid = min(max(indent + WORD_MID, lo), hi)
    return [(r, min(max(int(mid - w / 2 + 0.5), a), high - w)) for r, a, w in zip(rows, lows, widths)]


def _frame(grown: int, cols: int, sub_cols: int, indent: int = 2, status: tuple | list = ()) -> list[str]:
    """The lockup (12 rows) with the title above the wordmark and the version checks `status` under the baseline
    (status_place; the caller makes sure they fit), and an empty row; the logo up to `grown` pixel rows, baseline and
    wordmark up to column `cols`, the title up to `sub_cols` characters; `indent` spaces before it."""
    lead = " " * indent
    rows = [(lead + r) if r else "" for r in _lockup_rows(grown, cols)]
    left = sub_cols
    for i, (s, colour) in enumerate(TITLE):              # the title wipes in line by line
        if left > 0:
            col = indent + int(WORD_MID - len(s) / 2 + 0.5)
            _put(rows, TITLE_ROW + i, col, BOLD + _fg(colour) + s[:left] + RESET)
        left -= len(s)
    for (r, col), s in zip(status_place(list(status), indent) or [], status):
        _put(rows, r, col, s)
    while len(rows) < HEIGHT - 1:
        rows.append("")
    return rows + [""]


def _enable_ansi() -> bool:
    """True when the terminal shows colour codes (on Windows: switch on virtual terminal processing)."""
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k32.SetConsoleMode(h, mode.value | 0x0004))   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (OSError, AttributeError):
        return False


def show(animate: bool = True, lead: bool = True, indent: int = 2, status: tuple | list = ()) -> None:
    """Print the header (animated when allowed); nothing when the terminal cannot show it. lead=False: no empty line
    above it (the form draws it from the top row, so the header does not jump when the animation ends). `indent`:
    spaces before it; `status`: the version checks under the baseline (see _frame)."""
    if not _enable_ansi():
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    animate = animate and not os.environ.get("ORIENTR_NO_ANIMATION")
    frames = []
    if animate:
        frames += [(g, MARK_W, 0) for g in range(0, len(LOCKUP) + 1, 2)]               # the logo builds up
        frames += [(len(LOCKUP), c, 0) for c in range(MARK_W, LOCKUP_W + 3, 3)]       # baseline and wordmark
        frames += [(len(LOCKUP), LOCKUP_W, c) for c in range(0, TITLE_LEN + 6, 6)]    # the title wipes in
    frames.append((len(LOCKUP), LOCKUP_W, TITLE_LEN))
    w = sys.stdout.write
    w(("\n" if lead else "") + "\x1b[?25l")               # hide the cursor while drawing
    try:
        for i, f in enumerate(frames):
            rows = _frame(*f, indent, status)
            if i:
                w(f"\x1b[{len(rows)}A")                   # back to the top of the header
            w("\n".join(r + "\x1b[K" for r in rows) + "\n")
            sys.stdout.flush()
            if i < len(frames) - 1:
                time.sleep(0.03)
    finally:
        w("\x1b[?25h" + RESET)                            # cursor back, also after Ctrl+C
        sys.stdout.flush()


ORANGE = (230, 140, 30)


def enable_ansi() -> bool:
    return _enable_ansi()


def final_frame(indent: int = 2, status: tuple | list = ()) -> list[str]:
    """The finished header (no animation), for the form; `status`: see _frame."""
    return _frame(len(LOCKUP), LOCKUP_W, TITLE_LEN, indent, status)


def compact_frame(subtitle: bool = True) -> list[str]:
    """The compact header of the design, for a console too low or narrow for the full one: "◆ Orientr" and the
    description's first sentence on one line (without it when that does not fit either), then an empty row."""
    line = "  " + _fg(PALETTE["L"]) + "◆" + RESET + " " + BOLD + _fg(PALETTE["B"]) + "Orientr" + RESET
    if subtitle:
        line += "  " + _fg(GREY) + SUBTITLE_SHORT + RESET
    return [line, ""]


TITLE_LEN = sum(len(s) for s, _ in TITLE)
WIDTH = 2 + LOCKUP_W                                      # 61: the full header (the SOMA terminal: 63 columns)
COMPACT_WIDTH = 2 + len("◆ Orientr  ") + len(SUBTITLE_SHORT)   # 51
MINI_WIDTH = 2 + len("◆ Orientr")                         # 11


def status(ok: bool, lines: list[str]) -> None:
    """The line under the header: ✅ in the accent colour when Bambu Studio is installed and up to date, else ⚠ in
    orange."""
    colour = _enable_ansi()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    for line in lines:
        text = ("✅  " if ok else "⚠  ") + line
        sys.stdout.write((_fg(ACCENT if ok else ORANGE) + text + RESET if colour else text) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    show()
