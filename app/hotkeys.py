"""Global hotkeys via the Win32 RegisterHotKey API (ctypes only, no low-level
keyboard hooks). Must be used from a QWidget that already has a native
window handle (call after the widget has been shown at least once).

WM_HOTKEY is picked up via a QAbstractNativeEventFilter installed on the
QApplication, rather than overriding nativeEvent() on the band window
itself. Overriding nativeEvent() on the same widget that hosts a
QWebEngineView turned out to crash the process (access violation) during
window realization on some Qt6 builds -- QWebEngineView's own internal
child windows drive extra native messages through that widget, and a
Python-level nativeEvent override there is not safe. A process-wide
native event filter avoids the problem entirely and is the more standard
way to do this in Qt anyway.
"""
import ctypes
import time
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication

user32 = ctypes.windll.user32

# Minimum time between two triggers of the *same* hotkey before we treat a
# second WM_HOTKEY as real rather than chatter (fast/rapid-trigger keyboards
# and, occasionally, Windows itself can deliver a hotkey twice for one
# physical press).
_DEBOUNCE_SECONDS = 0.35

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

_MOD_MAP = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}


def parse_hotkey(spec):
    """spec: {"modifiers": ["ctrl","alt"], "key": "P"} -> (mods, vk)"""
    mods = 0
    for m in spec.get("modifiers", []):
        mods |= _MOD_MAP.get(m.lower(), 0)
    key = spec["key"]
    vk = ord(key.upper()[0])
    return mods, vk


def _extract_wm_hotkey_id(message_address):
    """Given the raw MSG* address from a native event filter, return the
    hotkey id if this message is WM_HOTKEY, else None."""
    msg = wintypes.MSG.from_address(int(message_address))
    if msg.message == WM_HOTKEY:
        return msg.wParam
    return None


kernel32 = ctypes.windll.kernel32


def force_foreground(widget):
    """Windows refuses SetForegroundWindow() (which Qt's activateWindow()
    calls internally) from a background process unless it thinks the
    request is tied to real user input -- a global hotkey delivered via
    WM_HOTKEY doesn't count, since our band window (which owns no OS
    focus by design) is the one "receiving" it, not whatever app is
    actually focused. Without this, a window opened from a hotkey (login,
    settings, the interact window, ...) shows up but never actually gets
    keyboard focus, so typing into it does nothing.

    Fixed via AttachThreadInput: temporarily share input state with
    whatever window currently owns the foreground so Windows treats our
    SetForegroundWindow() call as coming from an already-foreground
    thread, which it allows. This only touches window/thread bookkeeping
    through documented Win32 calls -- no synthetic keystrokes are ever
    injected. (An earlier version of this used keybd_event() to fake an
    Alt keypress as a workaround; synthetic key injection is also a
    classic keylogger technique, and it's what tripped a Windows Security
    warning for at least one user, so it's gone now.)
    """
    hwnd = int(widget.winId())
    fg_hwnd = user32.GetForegroundWindow()
    if not fg_hwnd or fg_hwnd == hwnd:
        user32.SetForegroundWindow(hwnd)
        return

    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
    cur_thread = kernel32.GetCurrentThreadId()
    if fg_thread == cur_thread:
        user32.SetForegroundWindow(hwnd)
        return

    user32.AttachThreadInput(fg_thread, cur_thread, True)
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        user32.AttachThreadInput(fg_thread, cur_thread, False)


class HotkeyManager(QAbstractNativeEventFilter):
    """Registers a set of named hotkeys against a window handle and
    dispatches WM_HOTKEY messages to callbacks by name, via a native event
    filter installed on the running QApplication."""

    def __init__(self, hwnd):
        super().__init__()
        self.hwnd = hwnd
        self._id_to_name = {}
        self._name_to_id = {}
        self._callbacks = {}
        self._next_id = 1
        self._last_triggered = {}
        QCoreApplication.instance().installNativeEventFilter(self)

    def register(self, name, spec, callback):
        mods, vk = parse_hotkey(spec)
        hotkey_id = self._next_id
        self._next_id += 1
        ok = user32.RegisterHotKey(self.hwnd, hotkey_id, mods | MOD_NOREPEAT, vk)
        if not ok:
            raise OSError(
                f"RegisterHotKey failed for '{name}' "
                f"(mods={mods:#x}, vk={vk:#x}) - it may already be in use."
            )
        self._id_to_name[hotkey_id] = name
        self._name_to_id[name] = hotkey_id
        self._callbacks[name] = callback
        return hotkey_id

    def nativeEventFilter(self, eventType, message):
        if eventType == "windows_generic_MSG":
            hotkey_id = _extract_wm_hotkey_id(int(message))
            if hotkey_id is not None:
                self._handle_wm_hotkey(hotkey_id)
        return False, 0

    def _handle_wm_hotkey(self, hotkey_id):
        name = self._id_to_name.get(hotkey_id)
        if name is None:
            return

        now = time.monotonic()
        last = self._last_triggered.get(hotkey_id, 0.0)
        if now - last < _DEBOUNCE_SECONDS:
            return
        self._last_triggered[hotkey_id] = now

        cb = self._callbacks.get(name)
        if cb:
            cb()

    def unregister_all(self):
        for hotkey_id in list(self._id_to_name.keys()):
            user32.UnregisterHotKey(self.hwnd, hotkey_id)
        self._id_to_name.clear()
        self._name_to_id.clear()
        self._callbacks.clear()
        QCoreApplication.instance().removeNativeEventFilter(self)
