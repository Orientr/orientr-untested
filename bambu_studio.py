# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""Bambu Studio in the background (2026-11-21): started early, hidden (not in front, not in the
taskbar), shown only when Generate opens the project in it, and closed again when nothing was opened.

orientr.prestart_studio() starts it, keep_hidden() hides it while it starts, and a small guard process
(this file: python bambu_studio.py <form pid> <studio pid> <marker>) closes it after the form ended (in any way, also
with the window's X) unless the project was handed to it (the marker file exists) or it is visible (in use).
Standard library only, so the guard starts fast.
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

# process ids of the tool's own command-line slices (the check, Analyze): not the user starting Bambu Studio, so
# keep_hidden goes on hiding (review 2026-11-22)
OWN_CLI: set[int] = set()

WS_MINIMIZEBOX = 0x00020000
SW_HIDE = 0
SW_SHOWMINNOACTIVE = 7
WM_CLOSE = 0x0010
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0


def trusted_exe(name: str) -> str | None:
    """The full path of a program on the PATH, never from the current folder: Windows (and shutil.which) look there
    first, so a wt.exe or gh.exe in a downloaded folder or a model folder would run instead (review 2026-11-22)."""
    here = os.path.normcase(os.path.abspath(os.getcwd()))
    exts = [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e] or [".exe"]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        folder = folder.strip().strip('"')
        if not folder or not os.path.isabs(folder) or os.path.normcase(os.path.abspath(folder)) == here:
            continue
        for ext in [""] + exts if os.path.splitext(name)[1] else exts:
            path = os.path.join(folder, name + ext)
            if os.path.isfile(path):
                return path
    return None


def user32():
    """user32 with the signatures used here (64-bit handles)."""
    u = ctypes.WinDLL("user32")
    u.EnumWindows.argtypes = (ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM)
    u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    for f in (u.IsWindowVisible, u.IsIconic, u.SetForegroundWindow, u.IsWindow):
        f.argtypes = (wintypes.HWND,)
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    u.GetWindow.restype = wintypes.HWND
    u.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    # ShowWindowAsync, not ShowWindow: that waits until Studio handled it, and while Studio loads (~8 s) it handles
    # nothing, so the caller would wait just as long
    u.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
    u.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    return u


def _kernel32():
    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def studio_pids() -> list[int]:
    """Process ids of every running bambu-studio.exe (Toolhelp: fast enough to ask several times a second)."""
    return pids_of("bambu-studio.exe")


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def value(self) -> int:                               # 100 ns units
        return (self.high << 32) | self.low


def _cpu_times() -> tuple[int, int]:
    """(idle, total) processor time of the whole PC so far."""
    idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
    ctypes.WinDLL("kernel32").GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    return idle.value(), kernel.value() + user.value()   # kernel time includes the idle time


def _process_age(pid: int) -> float:
    """Seconds since process `pid` started (0 when it cannot be read)."""
    k = _kernel32()
    ft = ctypes.POINTER(_FileTime)
    k.GetProcessTimes.argtypes = (wintypes.HANDLE, ft, ft, ft, ft)
    k.GetSystemTimeAsFileTime.argtypes = (ft,)
    h = k.OpenProcess(0x1000, False, pid)                 # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return 0.0
    try:
        created, ended, kernel, user, now = (_FileTime() for _ in range(5))
        if not k.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel),
                                 ctypes.byref(user)):
            return 0.0
        k.GetSystemTimeAsFileTime(ctypes.byref(now))
        return (now.value() - created.value()) / 1e7
    finally:
        k.CloseHandle(h)


def soma_ready(min_age: float = 20.0) -> bool:
    """Has SOMA finished starting (2026-11-21: Bambu Studio starts after SOMA, not at the same time)?
    True when SOMA is not running at all; else when a visible SOMA window answers within a second and its process
    has run for `min_age` seconds."""
    pids = pids_of("soma.exe")
    if not pids:
        return True
    u = user32()
    u.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT,
                                      wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    for pid in pids:
        for h, _, visible in windows(pid, u):
            if visible and _process_age(pid) >= min_age:
                result = ctypes.c_size_t()
                if u.SendMessageTimeoutW(h, 0, 0, 0, 0x0002, 1000, ctypes.byref(result)):   # WM_NULL, ABORTIFHUNG
                    return True
    return False


def wait_until_ready(cancel, limit: float = 120.0, quiet: float = 40.0, quiet_for: int = 3) -> bool:
    """Wait until SOMA has started (soma_ready) and the PC is quiet: the processor below `quiet` % for `quiet_for`
    seconds in a row (SOMA starting up, a build it runs, Analyze slicing). False when `cancel` (a threading.Event) is
    set or `limit` seconds passed: then Bambu Studio is not started early, it opens normally at Generate."""
    t0, calm = time.monotonic(), 0
    last = _cpu_times()
    while time.monotonic() - t0 < limit:
        if cancel.wait(1.0):
            return False
        now = _cpu_times()
        busy = 100.0 * (1 - (now[0] - last[0]) / max(1, now[1] - last[1]))
        last = now
        calm = calm + 1 if busy < quiet else 0
        # soma_ready can take a few seconds (a window that answers slowly): deadline and cancel once more after it
        if calm >= quiet_for and soma_ready():
            return time.monotonic() - t0 < limit and not cancel.is_set()
    return False


def pids_of(exe: str) -> list[int]:
    """Process ids of every running process with this file name (Toolhelp)."""
    k = ctypes.WinDLL("kernel32")
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    snap = k.CreateToolhelp32Snapshot(0x00000002, 0)     # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    pids = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe.lower():
                pids.append(entry.th32ProcessID)
            ok = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    return pids


def _owner_file(studio_pid: int) -> Path:
    import tempfile
    return Path(tempfile.gettempdir()) / f"bambu-studio-{studio_pid}.owner"


def set_owner(studio_pid: int, form_pid: int) -> None:
    """Note which form a hidden Studio belongs to: another Orientr then leaves it alone (2026-11-21: a second
    run adopted, and so closed, the Studio of a form that was still open)."""
    try:
        _owner_file(studio_pid).write_text(str(form_pid), encoding="utf-8")
    except OSError:
        pass


def _owner_alive(studio_pid: int) -> bool:
    """Is the form that owns this hidden Studio still running?"""
    try:
        form_pid = int(_owner_file(studio_pid).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    k = _kernel32()
    h = k.OpenProcess(SYNCHRONIZE, False, form_pid)
    if not h:
        return False
    try:
        return k.WaitForSingleObject(h, 0) != WAIT_OBJECT_0
    finally:
        k.CloseHandle(h)


def hidden_studio() -> int | None:
    """A Bambu Studio that runs with its main window hidden and whose form no longer runs: left behind by an earlier
    run whose guard did not finish (2026-11-21: it had to be ended in Task Manager). prestart_studio()
    adopts it. One that belongs to a form that is still open is not touched."""
    u = user32()
    for pid in studio_pids():
        mains = [visible for _, main, visible in windows(pid, u) if main]
        if mains and not any(mains) and not _owner_alive(pid):
            return pid
    return None


def show_minimized(pid: int) -> None:
    """Make Studio's hidden main window visible, minimized in the taskbar, so the user can close it with its X. A
    visible window (in use) is not touched."""
    try:
        u = user32()
        for h, main, visible in windows(pid, u):
            if main and not visible:
                u.ShowWindowAsync(h, SW_SHOWMINNOACTIVE)
    except Exception:
        pass


def owner_pid(u, hwnd) -> int:
    p = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def windows(pid: int, u=None) -> list[tuple]:
    """(hwnd, is main window, visible) of every top-level window of process `pid`, owned ones (the splash) too. The
    main window draws its own title bar (no WS_CAPTION) but has a minimize box; the splash has none."""
    u = u or user32()
    found = []

    def each(hwnd, _):
        if owner_pid(u, hwnd) == pid:
            found.append((hwnd, bool(u.GetWindowLongW(hwnd, -16) & WS_MINIMIZEBOX) and not u.GetWindow(hwnd, 4),
                          bool(u.IsWindowVisible(hwnd))))
        return True
    u.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(each), 0)
    return found


def keep_hidden(pid: int, focus, stop, focus_for: float = 60.0) -> None:
    """Bambu Studio puts its windows in front whatever it was started with (2026-11-21). Seen while it
    starts (2.9): first a splash, an owned pop-up without a title bar, which takes the focus; then the main window,
    which takes the focus while still invisible; and after it loaded it shows itself once more on its own. So, as
    long as the form runs (this is a thread of the form), its windows are hidden (no taskbar button either;
    2026-11-21: it came back in the taskbar after a while). During the first `focus_for` seconds the focus goes
    back to `focus`, the window that had it before (the form), whenever a Studio window or nobody has it.
    It stops when `stop` (a threading.Event) is set because the project opens, when Studio ends, and when the user
    starts Bambu Studio: that start runs a second bambu-studio.exe for a moment, which hands it to this one, and
    then the window must stay."""
    u, k = user32(), _kernel32()
    handle = k.OpenProcess(SYNCHRONIZE, False, pid)

    def give_focus_back() -> None:
        fg = u.GetForegroundWindow()
        if focus and u.IsWindow(focus) and (not fg or owner_pid(u, fg) == pid):
            u.SetForegroundWindow(focus)                  # no synthesized keys, no AttachThreadInput (blocks ~8 s)

    t0 = time.monotonic()
    try:
        while not stop.is_set():
            if handle and k.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0:
                return                                    # Studio ended
            if any(p != pid and p not in OWN_CLI for p in studio_pids()):
                return                                    # the user starts Bambu Studio: it shows this one
            for h, _, visible in windows(pid, u):
                if visible:
                    u.ShowWindowAsync(h, SW_HIDE)         # splash and main window: no taskbar button
            starting = time.monotonic() - t0 < focus_for
            if starting:
                give_focus_back()
            time.sleep(0.1 if starting else 0.2)
    except Exception:                                     # never let this disturb the form
        pass
    finally:
        if handle:
            k.CloseHandle(handle)


def alive(pid: int) -> bool:
    """Does process `pid` still run? (2026-11-23: for the form's Opening / Open / Closing / Closed)"""
    try:
        k = _kernel32()
        h = k.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) != WAIT_OBJECT_0
        finally:
            k.CloseHandle(h)
    except Exception:
        return False


def has_main_window(pid: int) -> bool:
    """Has Studio made its main window yet? Before that only the splash shows: it is still starting."""
    try:
        return any(main for _, main, _ in windows(pid))
    except Exception:
        return False


def close_hidden(pid: int, stop, limit: float = 180.0) -> None:
    """Close the form's own hidden Studio now (2026-11-23: "Background Bambu Studio" set to No and Enter), as the
    guard does after the form: with WM_CLOSE, never killed, its windows kept hidden meanwhile. Not when a main window
    is visible (in use), and it stops when `stop` is set (the project is handed to it). Not closed within `limit`
    (a question from Studio): minimized in the taskbar, never left invisible. A thread of the form."""
    try:
        k, u = _kernel32(), user32()
        handle = k.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return
        try:
            in_use = lambda: any(visible for _, main, visible in windows(pid, u) if main)   # noqa: E731
            if in_use():                                  # starting, it shows itself for a moment before
                time.sleep(1.0)                           # keep_hidden hides it again: still visible after 1 s
                if in_use():                              # means in use
                    return
            t0, closing = time.monotonic(), False
            while time.monotonic() - t0 < limit:
                if stop.is_set() or k.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0:
                    return
                wins = windows(pid, u)
                for h, _, visible in wins:
                    if visible:
                        u.ShowWindowAsync(h, SW_HIDE)
                mains = [h for h, main, _ in wins if main]
                if mains and not closing:
                    for h in mains:
                        u.PostMessageW(h, WM_CLOSE, 0, 0)
                    closing = True
                time.sleep(0.2)
            show_minimized(pid)
        finally:
            k.CloseHandle(handle)
    except Exception:                                     # never let this disturb the form
        pass


def guard(form_pid: int, studio_pid: int, marker: Path, limit: float = 180.0) -> None:
    """Wait until the form's process ends, then close the hidden Studio unless the project was handed to it (the
    marker exists) or it is visible (the user uses it). Closed as with the window's X (WM_CLOSE): never killed,
    which could cut off Studio writing its settings file; when it has no main window yet (still starting), wait for
    it. Process handles, not ids: an id that Windows gave to another process meanwhile is never touched."""
    k, u = _kernel32(), user32()
    studio = k.OpenProcess(SYNCHRONIZE, False, studio_pid)
    if not studio:
        return
    form = k.OpenProcess(SYNCHRONIZE, False, form_pid)
    try:
        while form and k.WaitForSingleObject(form, 1000) != WAIT_OBJECT_0:
            pass
        if marker.exists() or any(visible for _, main, visible in windows(studio_pid, u) if main):
            return                                        # handed the project, or visible when the form ended: in use
        # hidden or still starting: the form's keep_hidden ended with the form, so hide it here until it is closed
        t0, closing = time.monotonic(), False
        while time.monotonic() - t0 < limit:
            if marker.exists() or k.WaitForSingleObject(studio, 0) == WAIT_OBJECT_0:
                return                                    # handed the project, or ended (closed)
            wins = windows(studio_pid, u)
            for h, _, visible in wins:
                if visible:                               # also after WM_CLOSE: Studio handles it only once loaded,
                    u.ShowWindowAsync(h, SW_HIDE)         # and shows itself before that
            mains = [h for h, main, _ in wins if main]
            if mains and not closing:
                for h in mains:
                    u.PostMessageW(h, WM_CLOSE, 0, 0)
                closing = True
            time.sleep(0.2)
        # not closed in time (a question from Studio, or it never finished starting): never leave it invisible.
        # Minimized in the taskbar the user can close it with its X
        show_minimized(studio_pid)
    finally:
        k.CloseHandle(studio)
        if form:
            k.CloseHandle(form)
        for done in (marker, _owner_file(studio_pid)):
            try:
                done.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        guard(int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]))
    except Exception:                                     # a guard never shows an error, but never leaves Studio
        try:                                              # invisible either: then it goes to the taskbar
            if not Path(sys.argv[3]).exists():
                show_minimized(int(sys.argv[2]))
        except Exception:
            pass
    os._exit(0)
