#!/usr/bin/env python3
"""
AutoClicker - a fast, configurable auto-clicker for Windows.

Features
--------
* Custom click interval (hours / minutes / seconds / milliseconds) with optional random jitter
* Left / right / middle mouse button, single or double clicks
* Click until stopped, or a fixed number of clicks
* Clicks at the current cursor position, or at a fixed on-screen location
* Global hotkey (default F6) to start/stop - works in any application
* Session click counter, always-on-top mode, settings are saved automatically
"""

import ctypes
import ctypes.wintypes
import json
import math
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes

APP_NAME = "AutoClicker"
APP_VERSION = "1.0.0"

user32 = ctypes.windll.user32
# Dedicated handle so GetLastError() works reliably after CreateMutexW.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- Win32 bits
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_CXSCREEN = 0
SM_CYSCREEN = 1

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

HOTKEY_ID = 0xB001
SINGLE_INST_MUTEX = "AutoClicker_SingleInstance_Mutex_{9F2C}"

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT_UNION)]


def _send_mouse_event(flags, dx=0, dy=0):
    event = INPUT(type=INPUT_MOUSE)
    event._input.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    return event


def _send_inputs(events):
    n = len(events)
    arr = (INPUT * n)(*events)
    user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def send_click(button, double, fixed_xy=None):
    """Inject a (optionally double) click using SendInput."""
    events = []
    if fixed_xy is not None:
        x, y = fixed_xy
        screen_w = max(user32.GetSystemMetrics(SM_CXSCREEN) - 1, 1)
        screen_h = max(user32.GetSystemMetrics(SM_CYSCREEN) - 1, 1)
        abs_x = round(x * 65535 / screen_w)
        abs_y = round(y * 65535 / screen_h)
        events.append(_send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y))

    down_flag, up_flag = BUTTON_FLAGS[button]
    clicks = 2 if double else 1
    for _ in range(clicks):
        events.append(_send_mouse_event(down_flag))
        events.append(_send_mouse_event(up_flag))
    _send_inputs(events)


def get_cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ------------------------------------------------------------ config / state
def _config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "settings.json")


DEFAULT_SETTINGS = {
    "hours": 0,
    "minutes": 0,
    "seconds": 0,
    "millis": 100,
    "jitter_ms": 0,
    "button": "left",
    "click_type": "single",
    "repeat_mode": "infinite",      # "infinite" | "count"
    "repeat_count": 10,
    "position_mode": "current",     # "current" | "fixed"
    "fixed_x": 960,
    "fixed_y": 540,
    "hotkey": {"vk": 0x75, "mods": 0, "label": "F6"},  # F6
    "always_on_top": False,
}


def load_settings():
    try:
        with open(_config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        settings = dict(DEFAULT_SETTINGS)
        settings.update(data)
        # sanitize the hotkey dict
        hk = settings.get("hotkey") or {}
        if not isinstance(hk, dict) or "vk" not in hk:
            settings["hotkey"] = dict(DEFAULT_SETTINGS["hotkey"])
        else:
            settings["hotkey"] = {
                "vk": int(hk.get("vk", 0x75)),
                "mods": int(hk.get("mods", 0)),
                "label": str(hk.get("label", "F6")),
            }
        return settings
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    try:
        with open(_config_path(), "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------- UI colours
BG = "#1a1b26"
PANEL = "#24283b"
PANEL_ALT = "#1f2335"
TEXT = "#c0caf5"
TEXT_DIM = "#565f89"
ACCENT = "#7aa2f7"
GREEN = "#9ece6a"
RED = "#f7768e"
YELLOW = "#e0af68"
BORDER = "#3b4261"

FONT = "Segoe UI"

# Bare keys that are safe to use without modifiers (they don't clash with typing).
_SAFE_BARE_VKS = set(range(0x70, 0x88)) | {0x13, 0x91, 0x2C}  # F1-F24, Pause, ScrollLock, PrintScreen

_KEYSYM_LABELS = {
    "Prior": "PgUp", "Next": "PgDn", "Escape": "Esc", "space": "Space",
    "Return": "Enter", "BackSpace": "Backspace", "Delete": "Delete",
    "Insert": "Insert", "Tab": "Tab", "Home": "Home", "End": "End",
    "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
    "pause": "Pause", "Scroll_Lock": "ScrollLock", "Print": "PrtSc",
}


def keysym_label(keysym: str) -> str:
    if keysym.lower().startswith("f") and keysym[1:].isdigit():
        return keysym.upper()
    return _KEYSYM_LABELS.get(keysym, keysym.upper() if len(keysym) == 1 else keysym)


# ================================================================ application
class AutoClickerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()

        # --- state
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._counter_base = 0
        self._q = queue.Queue()          # cross-thread UI messages
        self.clicks_done = 0
        self.running = False
        self._counting_down = False

        # --- hotkey listener thread
        self._hk_thread: threading.Thread | None = None
        self._hk_tid: int | None = None
        self._hk_lock = threading.Lock()

        self._setup_window()
        self._build_variables()
        self._build_ui()
        self._load_into_ui()
        self._start_hotkey_listener()
        self._closed = False
        self._poll_job = self.root.after(100, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------- window setup
    def _setup_window(self):
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        # icon: use bundled icon.ico when available
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "icon.ico"))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico"))
        for path in candidates:
            if os.path.isfile(path):
                try:
                    self.root.iconbitmap(path)
                    break
                except tk.TclError:
                    pass

    # ------------------------------------------------------------- variables
    def _build_variables(self):
        s = self.settings
        self.var_hours = tk.StringVar(value=str(s["hours"]))
        self.var_minutes = tk.StringVar(value=str(s["minutes"]))
        self.var_seconds = tk.StringVar(value=str(s["seconds"]))
        self.var_millis = tk.StringVar(value=str(s["millis"]))
        self.var_jitter = tk.StringVar(value=str(s["jitter_ms"]))
        self.var_button = tk.StringVar(value=s["button"])
        self.var_click_type = tk.StringVar(value=s["click_type"])
        self.var_repeat_mode = tk.StringVar(value=s["repeat_mode"])
        self.var_repeat_count = tk.StringVar(value=str(s["repeat_count"]))
        self.var_position_mode = tk.StringVar(value=s["position_mode"])
        self.var_fixed_x = tk.StringVar(value=str(s["fixed_x"]))
        self.var_fixed_y = tk.StringVar(value=str(s["fixed_y"]))
        self.var_always_on_top = tk.BooleanVar(value=s["always_on_top"])
        self.hotkey = dict(s["hotkey"])

        for var in (self.var_hours, self.var_minutes, self.var_seconds, self.var_millis):
            var.trace_add("write", lambda *_: self._refresh_cps_label())

    # ------------------------------------------------------------------- UI
    def _card(self, parent, title):
        outer = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        title_lbl = tk.Label(
            outer, text=title.upper(), bg=PANEL, fg=TEXT_DIM,
            font=(FONT, 8, "bold"), anchor="w",
        )
        title_lbl.pack(fill="x", padx=12, pady=(4, 0))
        return outer

    def _spinbox(self, parent, var, from_, to, width=4):
        return tk.Spinbox(
            parent, from_=from_, to=to, width=width, textvariable=var,
            bg=PANEL_ALT, fg=TEXT, insertbackground=TEXT,
            buttonbackground=BORDER, relief="flat", borderwidth=1,
            highlightthickness=1, highlightbackground=BORDER,
            font=(FONT, 10), justify="center",
        )

    def _radio(self, parent, text, variable, value, command=None):
        return tk.Radiobutton(
            parent, text=text, value=value, variable=variable, command=command,
            bg=PANEL, fg=TEXT, activebackground=PANEL, activeforeground=TEXT,
            selectcolor=PANEL_ALT, relief="flat", highlightthickness=0,
            font=(FONT, 8), anchor="w",
        )

    def _build_ui(self):
        pad = {"padx": 14}
        # ---- header
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=16, pady=(4, 2))

        tk.Label(
            header, text="⚡", bg=BG, fg=YELLOW, font=(FONT, 17),
        ).pack(side="left", padx=(0, 8))

        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_box, text="AutoClicker", bg=BG, fg=TEXT,
            font=(FONT, 15, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            title_box, text="Fast, lightweight, global hotkey", bg=BG, fg=TEXT_DIM,
            font=(FONT, 8), anchor="w",
        ).pack(fill="x")

        self.status_canvas = tk.Canvas(header, width=14, height=14, bg=BG, highlightthickness=0)
        self.status_canvas.pack(side="right", pady=(6, 0))
        self.status_dot = self.status_canvas.create_oval(1, 1, 13, 13, fill=TEXT_DIM, outline="")
        self.status_label = tk.Label(
            header, text="IDLE", bg=BG, fg=TEXT_DIM, font=(FONT, 9, "bold"),
        )
        self.status_label.pack(side="right", pady=(6, 0), padx=(0, 6))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, **pad)

        # ---- interval card
        card = self._card(body, "Click Interval")
        card.pack(fill="x", pady=(0, 6))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(2, 1))
        for var, unit, hi in (
            (self.var_hours, "HH", 23),
            (self.var_minutes, "MM", 59),
            (self.var_seconds, "SS", 59),
            (self.var_millis, "MS", 999),
        ):
            col = tk.Frame(row, bg=PANEL)
            col.pack(side="left", padx=(0, 6))
            self._spinbox(col, var, 0, hi, 4).pack()
            tk.Label(col, text=unit, bg=PANEL, fg=TEXT_DIM, font=(FONT, 7)).pack()
        arrow = tk.Label(row, text="≈", bg=PANEL, fg=TEXT_DIM, font=(FONT, 12))
        arrow.pack(side="left", padx=(2, 6), pady=(0, 8))
        self.cps_label = tk.Label(row, text="10 CPS", bg=PANEL, fg=ACCENT, font=(FONT, 10, "bold"))
        self.cps_label.pack(side="left", pady=(0, 8))

        jitter_row = tk.Frame(card, bg=PANEL)
        jitter_row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(
            jitter_row, text="Random jitter (± ms):", bg=PANEL, fg=TEXT, font=(FONT, 9),
        ).pack(side="left")
        self._spinbox(jitter_row, self.var_jitter, 0, 9999, 5).pack(side="left", padx=(8, 0))

        # ---- button & click type card
        card = self._card(body, "Mouse Button  ·  Click Type")
        card.pack(fill="x", pady=(0, 6))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(4, 0))
        tk.Label(row, text="Button", bg=PANEL, fg=TEXT_DIM, font=(FONT, 8, "bold")).pack(side="left")
        for text, value in (("Left", "left"), ("Right", "right"), ("Middle", "middle")):
            self._radio(row, text, self.var_button, value).pack(side="left", padx=(8, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(2, 8))
        tk.Label(row, text="Click ", bg=PANEL, fg=TEXT_DIM, font=(FONT, 8, "bold")).pack(side="left")
        for text, value in (("Single", "single"), ("Double", "double")):
            self._radio(row, text, self.var_click_type, value).pack(side="left", padx=(8, 0))

        # ---- repeat card
        card = self._card(body, "Click Repeat")
        card.pack(fill="x", pady=(0, 6))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(2, 6))
        self._radio(
            row, "Until I stop it (infinite)", self.var_repeat_mode, "infinite",
            command=self._refresh_repeat_state,
        ).pack(anchor="w")
        count_row = tk.Frame(row, bg=PANEL)
        count_row.pack(anchor="w", fill="x")
        self._radio(
            count_row, "Repeat", self.var_repeat_mode, "count",
            command=self._refresh_repeat_state,
        ).pack(side="left")
        self.repeat_spin = self._spinbox(count_row, self.var_repeat_count, 1, 99999, 6)
        self.repeat_spin.pack(side="left", padx=6)
        tk.Label(count_row, text="clicks, then stop", bg=PANEL, fg=TEXT_DIM, font=(FONT, 9)).pack(side="left")

        # ---- position card
        card = self._card(body, "Cursor Position")
        card.pack(fill="x", pady=(0, 6))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(2, 6))
        self._radio(
            row, "Current cursor position (wherever it is)",
            self.var_position_mode, "current", command=self._refresh_position_state,
        ).pack(anchor="w")
        fixed_row = tk.Frame(row, bg=PANEL)
        fixed_row.pack(anchor="w", fill="x", pady=(2, 0))
        self._radio(
            fixed_row, "Fixed position", self.var_position_mode, "fixed",
            command=self._refresh_position_state,
        ).pack(side="left")
        xy_row = tk.Frame(fixed_row, bg=PANEL)
        xy_row.pack(side="left", padx=(8, 0))
        tk.Label(xy_row, text="X", bg=PANEL, fg=TEXT_DIM, font=(FONT, 8)).pack(side="left")
        self.entry_x = self._spinbox(xy_row, self.var_fixed_x, -20000, 20000, 5)
        self.entry_x.pack(side="left", padx=(2, 6))
        tk.Label(xy_row, text="Y", bg=PANEL, fg=TEXT_DIM, font=(FONT, 8)).pack(side="left")
        self.entry_y = self._spinbox(xy_row, self.var_fixed_y, -20000, 20000, 5)
        self.entry_y.pack(side="left", padx=(2, 0))
        self.pick_button = tk.Button(
            row, text="◎  Capture cursor position in 3 s",
            bg=PANEL_ALT, fg=ACCENT, activebackground=BORDER, activeforeground=ACCENT,
            relief="flat", borderwidth=1, highlightthickness=0, cursor="hand2",
            font=(FONT, 8, "bold"), padx=10, pady=4, command=self._capture_position,
        )
        self.pick_button.pack(anchor="w", pady=(6, 0))

        # ---- hotkey card
        card = self._card(body, "Global Hotkey")
        card.pack(fill="x", pady=(0, 6))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(row, text="Start / stop:", bg=PANEL, fg=TEXT, font=(FONT, 9)).pack(side="left")
        self.hotkey_button = tk.Button(
            row, text=self.hotkey["label"], width=12,
            bg=PANEL_ALT, fg=ACCENT, activebackground=BORDER, activeforeground=ACCENT,
            relief="flat", borderwidth=1, cursor="hand2", font=(FONT, 10, "bold"),
            command=self._record_hotkey,
        )
        self.hotkey_button.pack(side="left", padx=10)
        tk.Label(
            row, text="works in any app", bg=PANEL, fg=TEXT_DIM, font=(FONT, 8),
        ).pack(side="left")

        # ---- options row: always-on-top + counter
        opt_row = tk.Frame(body, bg=BG)
        opt_row.pack(fill="x", pady=(0, 2))
        self.always_top_check = tk.Checkbutton(
            opt_row, text="Always on top", variable=self.var_always_on_top,
            command=self._toggle_always_on_top,
            bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
            selectcolor=PANEL_ALT, relief="flat", highlightthickness=0, font=(FONT, 9),
        )
        self.always_top_check.pack(side="left")
        self.counter_label = tk.Label(
            opt_row, text="Clicks: 0", bg=BG, fg=TEXT_DIM, font=(FONT, 9),
        )
        self.counter_label.pack(side="right")
        tk.Button(
            opt_row, text="Reset", bg=BG, fg=TEXT_DIM, activeforeground=TEXT,
            relief="flat", borderwidth=0, cursor="hand2", font=(FONT, 8, "underline"),
            command=self._reset_counter,
        ).pack(side="right", padx=(0, 8))

        # ---- start & stop buttons
        button_row = tk.Frame(self.root, bg=BG)
        button_row.pack(fill="x", padx=14, pady=(0, 2))
        self.start_button = tk.Button(
            button_row, text="▶  START", bg=GREEN, fg="#10131a",
            activebackground="#86b956", activeforeground="#10131a",
            disabledforeground="#5a6b3f",
            relief="flat", borderwidth=0, cursor="hand2",
            font=(FONT, 14, "bold"), pady=9, command=self.start,
        )
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.stop_button = tk.Button(
            button_row, text="■  STOP", bg=RED, fg="#10131a",
            activebackground="#e05f77", activeforeground="#10131a",
            disabledforeground="#6b3f47",
            relief="flat", borderwidth=0, cursor="hand2",
            font=(FONT, 14, "bold"), pady=9, command=self.stop,
        )
        self.stop_button.pack(side="left", fill="x", expand=True, padx=(4, 0))


        self._refresh_repeat_state()
        self._refresh_position_state()
        self._refresh_cps_label()

    # -------------------------------------------------------- state helpers
    def _refresh_repeat_state(self):
        enabled = self.var_repeat_mode.get() == "count"
        self.repeat_spin.configure(state="normal" if enabled else "disabled")

    def _refresh_position_state(self):
        enabled = self.var_position_mode.get() == "fixed"
        state = "normal" if enabled else "disabled"
        self.entry_x.configure(state=state)
        self.entry_y.configure(state=state)
        self.pick_button.configure(state="normal" if enabled else "disabled")

    def _refresh_cps_label(self):
        if not hasattr(self, "cps_label"):
            return  # traces can fire before the UI is built
        ms = self._interval_ms()
        if ms <= 0:
            self.cps_label.configure(text="∞ CPS")
        else:
            cps = 1000.0 / ms
            self.cps_label.configure(text=f"{cps:.0f} CPS" if cps >= 100 else f"{cps:.1f} CPS")

    def _interval_ms(self):
        def num(var, lo):
            try:
                return max(lo, float(var.get()))
            except ValueError:
                return lo
        return (
            num(self.var_hours, 0) * 3600_000
            + num(self.var_minutes, 0) * 60_000
            + num(self.var_seconds, 0) * 1000
            + num(self.var_millis, 0)
        )

    def _jitter_ms(self):
        try:
            return max(0.0, float(self.var_jitter.get()))
        except ValueError:
            return 0.0

    def _toggle_always_on_top(self):
        self.root.attributes("-topmost", bool(self.var_always_on_top.get()))

    def _reset_counter(self):
        self.clicks_done = 0
        self._counter_base = 0
        self.counter_label.configure(text="Clicks: 0")

    # --------------------------------------------------------- click engine
    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        interval_ms = self._interval_ms()
        if interval_ms <= 0:
            interval_ms = 1.0
        interval = interval_ms / 1000.0
        jitter = self._jitter_ms() / 1000.0

        repeat_mode = self.var_repeat_mode.get()
        try:
            repeat_count = max(1, int(float(self.var_repeat_count.get())))
        except ValueError:
            repeat_count = 1

        position_mode = self.var_position_mode.get()
        try:
            fixed_xy = (int(float(self.var_fixed_x.get())), int(float(self.var_fixed_y.get())))
        except ValueError:
            fixed_xy = (960, 540)

        button = self.var_button.get()
        double = self.var_click_type.get() == "double"
        fixed = fixed_xy if position_mode == "fixed" else None
        limit = repeat_count if repeat_mode == "count" else None

        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._click_loop,
            args=(interval, jitter, button, double, fixed, limit),
            daemon=True,
        )
        self.running = True
        self._worker.start()
        self._update_running_ui(True)

    def stop(self):
        self._stop_event.set()
        self.running = False
        self._update_running_ui(False)

    def _click_loop(self, interval, jitter, button, double, fixed, limit):
        sent = 0
        next_t = time.perf_counter()
        while not self._stop_event.is_set():
            try:
                send_click(button, double, fixed)
            except Exception:
                break
            sent += 1
            self.clicks_done = sent + getattr(self, "_counter_base", 0)
            if limit is not None and sent >= limit:
                break
            delay = interval + (random.uniform(-jitter, jitter) if jitter > 0 else 0.0)
            if delay < 0.001:
                delay = 0.001
            next_t += delay
            drift = next_t - time.perf_counter()
            if drift <= 0:
                next_t = time.perf_counter()
                drift = 0.001
            self._stop_event.wait(drift)
        self._counter_base = self.clicks_done
        self._q.put(("stopped",))

    def _update_running_ui(self, running):
        if running:
            self.start_button.configure(state="disabled", bg="#2a3244")
            self.stop_button.configure(state="normal", bg=RED)
            self.status_label.configure(text="CLICKING", fg=GREEN)
            self.status_canvas.itemconfig(self.status_dot, fill=GREEN)
        else:
            self.start_button.configure(state="normal", bg=GREEN)
            self.stop_button.configure(state="disabled", bg="#2a3244")
            self.status_label.configure(text="IDLE", fg=TEXT_DIM)
            self.status_canvas.itemconfig(self.status_dot, fill=TEXT_DIM)
        self._persist_settings()

    # ------------------------------------------------------------- hotkey IO
    def _start_hotkey_listener(self):
        with self._hk_lock:
            self._stop_hotkey_listener_locked()
            vk, mods = self.hotkey["vk"], self.hotkey["mods"] | MOD_NOREPEAT
            ready = threading.Event()
            placeholder = {"ok": False}

            def listener():
                tid = _kernel32.GetCurrentThreadId()
                self._hk_tid = tid
                if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
                    ready.set()
                    self._q.put(("hotkey_error", self.hotkey["label"]))
                    return
                placeholder["ok"] = True
                ready.set()
                msg = wintypes.MSG()
                while True:
                    result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if result in (0, -1):
                        break
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                        self._q.put(("hotkey",))
                user32.UnregisterHotKey(None, HOTKEY_ID)

            self._hk_thread = threading.Thread(target=listener, daemon=True, name="hotkey")
            self._hk_thread.start()
            ready.wait(timeout=2.0)

    def _stop_hotkey_listener_locked(self):
        thread, tid = self._hk_thread, self._hk_tid
        if thread and thread.is_alive() and tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            thread.join(timeout=1.5)
        self._hk_thread = None
        self._hk_tid = None

    def _record_hotkey(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Set hotkey")
        dlg.configure(bg=PANEL)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.attributes("-topmost", True)
        dlg.geometry("360x150")
        dlg.update_idletasks()
        # center over parent
        px, py = self.root.winfo_x(), self.root.winfo_y()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{px + (pw - 360) // 2}+{py + (ph - 150) // 2}")

        tk.Label(
            dlg, text="Press your hotkey…", bg=PANEL, fg=TEXT, font=(FONT, 12, "bold"),
        ).pack(pady=(18, 4))
        hint = tk.Label(
            dlg, text="Use a function key, or combine with Ctrl / Alt / Shift.\nEsc cancels.",
            bg=PANEL, fg=TEXT_DIM, font=(FONT, 8), justify="center",
        )
        hint.pack()

        def on_key(event):
            keysym = event.keysym
            if keysym == "Escape":
                dlg.destroy()
                return
            if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Win_L", "Win_R"):
                return
            vk = event.keycode
            state = event.state
            mods = 0
            label_parts = []
            if state & 0x0004:
                mods |= MOD_CONTROL
                label_parts.append("Ctrl")
            if state & 0x0008:
                mods |= MOD_ALT
                label_parts.append("Alt")
            if state & 0x0001:
                mods |= MOD_SHIFT
                label_parts.append("Shift")
            if mods == 0 and vk not in _SAFE_BARE_VKS:
                hint.configure(
                    text="That key would swallow typing!\nCombine it with Ctrl / Alt / Shift,\nor use F1–F24 / Pause / ScrollLock / PrtSc.",
                    fg=RED,
                )
                return
            label_parts.append(keysym_label(keysym))
            label = "+".join(label_parts)
            self.hotkey = {"vk": int(vk), "mods": mods, "label": label}
            self.hotkey_button.configure(text=label)
            dlg.destroy()
            self._start_hotkey_listener()
            self._persist_settings()

        dlg.bind("<KeyPress>", on_key)
        dlg.focus_force()

    # ------------------------------------------------------ position capture
    def _capture_position(self):
        if self._counting_down:
            return
        self._counting_down = True

        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.92)
        overlay.configure(bg=PANEL)
        overlay.geometry("180x90")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        overlay.geometry(f"180x90+{(screen_w - 180) // 2}+{(screen_h - 90) // 2}")
        number = tk.Label(overlay, text="3", bg=PANEL, fg=YELLOW, font=(FONT, 30, "bold"))
        number.pack(expand=True)
        tk.Label(overlay, text="Esc to cancel", bg=PANEL, fg=TEXT_DIM, font=(FONT, 7)).pack()

        remaining = {"n": 3}

        def tick():
            if not overlay.winfo_exists():
                self._counting_down = False
                return
            remaining["n"] -= 1
            if remaining["n"] <= 0:
                x, y = get_cursor_pos()
                self.var_fixed_x.set(str(x))
                self.var_fixed_y.set(str(y))
                overlay.destroy()
                self._counting_down = False
                self.var_position_mode.set("fixed")
                self._refresh_position_state()
                self._persist_settings()
                return
            number.configure(text=str(remaining["n"]))
            self.root.after(700, tick)

        overlay.bind("<Escape>", lambda _e: (overlay.destroy(), setattr(self, "_counting_down", False)))
        self.root.after(700, tick)

    # ------------------------------------------------------------ queue poll
    def _poll_queue(self):
        if self._closed:
            return
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]
                if kind == "hotkey":
                    self.toggle()
                elif kind == "stopped":
                    self.running = False
                    self._update_running_ui(False)
                elif kind == "hotkey_error":
                    label = msg[1]
                    import tkinter.messagebox as mb
                    mb.showwarning(
                        "Hotkey unavailable",
                        f"Could not register “{label}” (another app may already use it).\n"
                        "Pick a different hotkey in the app.",
                        parent=self.root,
                    )
        except queue.Empty:
            pass
        try:
            self.counter_label.configure(text=f"Clicks: {self.clicks_done}")
        except tk.TclError:
            return  # window already gone
        self._poll_job = self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------- settings
    def _persist_settings(self):
        self.settings = {
            "hours": self._safe_int(self.var_hours.get()),
            "minutes": self._safe_int(self.var_minutes.get()),
            "seconds": self._safe_int(self.var_seconds.get()),
            "millis": self._safe_int(self.var_millis.get()),
            "jitter_ms": self._safe_int(self.var_jitter.get()),
            "button": self.var_button.get(),
            "click_type": self.var_click_type.get(),
            "repeat_mode": self.var_repeat_mode.get(),
            "repeat_count": max(1, self._safe_int(self.var_repeat_count.get())),
            "position_mode": self.var_position_mode.get(),
            "fixed_x": self._safe_int(self.var_fixed_x.get(), 960),
            "fixed_y": self._safe_int(self.var_fixed_y.get(), 540),
            "hotkey": self.hotkey,
            "always_on_top": bool(self.var_always_on_top.get()),
        }
        save_settings(self.settings)

    @staticmethod
    def _safe_int(text, fallback=0):
        try:
            return int(float(text))
        except (ValueError, TypeError):
            return fallback

    def _load_into_ui(self):
        self.root.attributes("-topmost", bool(self.var_always_on_top.get()))
        self.hotkey_button.configure(text=self.hotkey["label"])
        # initial state: ready to start, stop disabled
        self.stop_button.configure(state="disabled", bg="#2a3244")

    # ---------------------------------------------------------------- close
    def _on_close(self):
        self._closed = True
        try:
            self.root.after_cancel(self._poll_job)
        except tk.TclError:
            pass
        self._persist_settings()
        self._stop_event.set()
        self.stop_worker_join()
        with self._hk_lock:
            self._stop_hotkey_listener_locked()
        self.root.destroy()

    def stop_worker_join(self):
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.0)


# ===================================================================== main
def _focus_existing_instance():
    """Bring the already-running AutoClicker window to the front. Returns True on success."""
    title = f"{APP_NAME}  v{APP_VERSION}"
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    return False


def _already_running():
    handle = _kernel32.CreateMutexW(None, False, SINGLE_INST_MUTEX)
    already = handle is not None and _kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    return already


def main():
    if _already_running():
        _focus_existing_instance()  # exit silently whether or not focusing worked
        return 2

    root = tk.Tk()
    app = AutoClickerApp(root)
    root.update_idletasks()
    # Auto-fit height to content; center horizontally, anchored near the top of the work area
    req_height = max(root.winfo_reqheight(), 400)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x = max(0, (sw - 470) // 2)
    y = max(8, min(80, (sh - req_height) // 2))
    root.geometry(f"470x{req_height}+{x}+{y}")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
