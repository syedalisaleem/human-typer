#!/usr/bin/env python3
"""Human Typer — a desktop app that types your code into VS Code (or any
focused window) at realistic human speed, with jitter, pauses and typos.

How to use:
    1. Paste your code (or use Open File / From Clipboard).
    2. Click "Start Typing", then immediately click into VS Code.
    3. A small floating bar stays on top of the screen — use it to
       Pause / Resume, Stop, and watch progress.  F8 also aborts.

Requires only the Python standard library.  Windows only.
"""

import ctypes
import json
import math
import os
import random
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

import winsound

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", "."), "HumanTyper")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")

BG = "#1e1e1e"
PANEL = "#252526"
PANEL2 = "#2d2d30"
BORDER = "#3c3c3c"
TEXT = "#d4d4d4"
MUTED = "#8a8a8a"
ACCENT = "#007acc"
GREEN = "#2ea043"
GREEN_ACTIVE = "#33b64c"
GREEN_DARK = "#238636"
RED = "#b62324"
RED_ACTIVE = "#c93132"
WARN = "#d29922"
CODE_BG = "#1e1e1e"
CODE_SEL = "#264f78"
UI_FONT = ("Segoe UI", 10)
CODE_FONT = ("Consolas", 11)

VK_SHIFT = 0x10
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_BACK = 0x08
VK_PACKET = 0xE7
VK_F8 = 0x77

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

user32 = ctypes.windll.user32
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class InputI(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", InputI)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def _key_input(vk=0, scan=0, flags=0):
    ki = KeyBdInput()
    ki.wVk = vk
    ki.wScan = scan
    ki.dwFlags = flags
    ki.time = 0
    ki.dwExtraInfo = None
    inp = Input()
    inp.type = INPUT_KEYBOARD
    inp.ii.ki = ki
    return inp


def _send(events):
    arr = (Input * len(events))(*events)
    user32.SendInput(len(events), arr, ctypes.sizeof(Input))


def press_key(vk, shift=False):
    events = []
    if shift:
        events.append(_key_input(vk=VK_SHIFT))
    events.append(_key_input(vk=vk))
    events.append(_key_input(vk=vk, flags=KEYEVENTF_KEYUP))
    if shift:
        events.append(_key_input(vk=VK_SHIFT, flags=KEYEVENTF_KEYUP))
    _send(events)


def send_unicode_char(ch):
    code = ord(ch)
    _send([
        _key_input(vk=VK_PACKET, scan=code, flags=KEYEVENTF_UNICODE),
        _key_input(vk=VK_PACKET, scan=code,
                   flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
    ])


def send_char(ch):
    """Type one character the way a human would, honoring the layout."""
    if ch == "\n":
        press_key(VK_RETURN)
        return
    if ch == "\t":
        press_key(VK_TAB)
        return
    res = user32.VkKeyScanW(ch)
    if res == -1:
        send_unicode_char(ch)
        return
    mod = (res >> 8) & 0xFF
    key = res & 0xFF
    if key == 0 or (mod & 0xFC):
        send_unicode_char(ch)
        return
    press_key(key, shift=(mod & 1) != 0)


class HumanTyper:
    def __init__(self, text, cps, jitter=True, thinking=True,
                 mistakes=False, compensate=True,
                 is_paused=None, update_ui=None):
        self.text = text
        self.cps = max(1.0, float(cps))
        self.jitter = jitter
        self.thinking = thinking
        self.mistakes = mistakes
        self.compensate = compensate
        self.is_paused = is_paused
        self.update_ui = update_ui
        self.stop_requested = False
        self._state = "normal"
        self._state_left = 0
        self._line_mult = 1.0

    @staticmethod
    def _detect_step(lines):
        counts = {}
        for ln in lines[:60]:
            if ln.startswith(" "):
                n = len(ln) - len(ln.lstrip(" "))
                if n > 0:
                    counts[n] = counts.get(n, 0) + 1
        if not counts:
            return 4
        return max(counts, key=lambda n: (counts[n], -n))

    @staticmethod
    def _auto_indent(prev_line, prev_col, step):
        s = prev_line.strip()
        if not s:
            return prev_col
        if s[-1] in ":{[(":
            return prev_col + step
        return prev_col

    def _next_delay(self):
        base = 1.0 / self.cps
        if not self.jitter:
            return base * self._line_mult
        if self._state_left <= 0:
            r = random.random()
            if r < 0.14:
                self._state, self._state_left = "fast", random.randint(3, 10)
            elif r < 0.24:
                self._state, self._state_left = "slow", random.randint(2, 6)
            else:
                self._state, self._state_left = "normal", random.randint(4, 18)
        self._state_left -= 1
        mult = {"fast": 0.5, "normal": 1.0, "slow": 1.9}[self._state]
        d = base * mult * math.exp(random.gauss(0, 0.28))
        if random.random() < 0.04:
            d *= random.uniform(2.0, 4.0)
        return d * self._line_mult

    def _sleep(self, seconds):
        """Sleep in small chunks so the UI stays responsive and pause/stop
        interrupts can fire while we wait."""
        end = time.time() + seconds
        while time.time() < end:
            if self.update_ui:
                self.update_ui()
            if self.is_cancelled():
                return False
            if self.is_paused and self.is_paused():
                if not self._wait_while_paused():
                    return False
            time.sleep(0.05)
        return True

    def _wait_while_paused(self):
        while self.is_paused and self.is_paused():
            if self.update_ui:
                self.update_ui()
            if self.is_cancelled():
                return False
            time.sleep(0.05)
        return True

    def is_cancelled(self):
        if self.stop_requested:
            return True
        return False

    def _type_one(self, ch):
        if self.mistakes and ch.isalpha() and random.random() < 0.018:
            wrong = ch
            while wrong == ch:
                wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
            if ch.isupper():
                wrong = wrong.upper()
            send_char(wrong)
            if not self._sleep(random.uniform(0.05, 0.25)):
                return False
            press_key(VK_BACK)
            if not self._sleep(random.uniform(0.05, 0.2)):
                return False
        send_char(ch)
        d = self._next_delay()
        if ch in ". ,;:(){}[]=+-*/<>!&|?\"'":
            d += random.uniform(0.03, 0.10)
        if ch in "(={[" and random.random() < 0.3:
            d += random.uniform(0.15, 0.45)
        if self.thinking and random.random() < 0.004:
            d += random.uniform(0.7, 2.2)
        return self._sleep(d)

    def run(self, on_progress=None, on_cancel=None):
        lines = self.text.split("\n")
        step = self._detect_step(lines)
        total = max(1, len(self.text))
        done = 0
        col = 0
        prev_line = None

        if not self._sleep(random.uniform(0.6, 1.5) if self.jitter else 0.4):
            return False

        for line in lines:
            if self.is_cancelled():
                return False
            stripped = line.lstrip()
            is_structural = stripped.startswith((
                "#", "//", "/*", "*", "def ", "class ", "function ",
                "import ", "from ", "public ", "private ", "const ",
                "let ", "var "))
            if prev_line is not None:
                if not self._sleep(random.uniform(0.1, 0.3)):
                    return False
                if not self._type_one("\n"):
                    return False
                done += 1
                if self.compensate:
                    col = self._auto_indent(prev_line, col, step)
                else:
                    col = 0
                if self.jitter:
                    if is_structural and random.random() < 0.65:
                        if not self._sleep(random.uniform(0.4, 1.4)):
                            return False
                    elif random.random() < 0.2:
                        if not self._sleep(random.uniform(0.2, 0.8)):
                            return False
            else:
                col = 0

            self._line_mult = 1.0 + min(1.2, len(line) / 90.0)

            leading = len(line) - len(line.lstrip(" \t"))
            if leading:
                if self.compensate and leading > col:
                    for _ in range(leading - col):
                        if not self._type_one(" "):
                            return False
                        done += 1
                elif self.compensate:
                    for _ in range(col - leading):
                        if self.is_cancelled():
                            return False
                        press_key(VK_BACK)
                        if not self._sleep(random.uniform(0.03, 0.10)):
                            return False
                else:
                    for _ in range(leading):
                        if not self._type_one(" "):
                            return False
                        done += 1
            col = leading

            for ch in line[leading:]:
                if not self._type_one(ch):
                    return False
                done += 1
                if on_progress and done % 16 == 0:
                    on_progress(done / total)
            prev_line = line

        if on_progress:
            on_progress(1.0)
        return True


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Human Typer")
        self.geometry("760x580")
        self.minsize(560, 420)
        self.stop_requested = False
        self.paused = False
        self.typer = None
        self._setup_style()
        self._build_ui()
        self._build_float_bar()
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except tk.TclError:
                pass

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=UI_FONT)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT,
                        font=("Segoe UI", 14, "bold"))
        style.configure("Version.TLabel", background=BG, foreground=MUTED,
                        font=("Segoe UI", 9))

        style.configure("TButton", background=PANEL2, foreground=TEXT,
                        bordercolor=PANEL2, focuscolor=PANEL,
                        padding=(10, 5), font=UI_FONT)
        style.map("TButton",
                  background=[("disabled", PANEL), ("pressed", "#191919"),
                              ("active", "#3e3e42")],
                  bordercolor=[("disabled", PANEL), ("pressed", "#191919"),
                               ("active", "#3e3e42")],
                  foreground=[("disabled", MUTED)])

        style.configure("Accent.TButton", background=GREEN, foreground="#ffffff",
                        bordercolor=GREEN, focuscolor=GREEN, padding=(12, 6),
                        font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("disabled", "#1f6f33"), ("pressed", GREEN_DARK),
                              ("active", GREEN_ACTIVE)],
                  bordercolor=[("disabled", "#1f6f33"), ("pressed", GREEN_DARK),
                               ("active", GREEN_ACTIVE)],
                  foreground=[("disabled", "#9b9b9b")])

        style.configure("Danger.TButton", background=RED, foreground="#ffffff",
                        bordercolor=RED, focuscolor=RED, padding=(12, 6))
        style.map("Danger.TButton",
                  background=[("disabled", PANEL), ("pressed", "#8f1b1c"),
                              ("active", RED_ACTIVE)],
                  bordercolor=[("disabled", PANEL), ("pressed", "#8f1b1c"),
                               ("active", RED_ACTIVE)],
                  foreground=[("disabled", MUTED)])

        style.configure("TCheckbutton", background=BG, foreground=TEXT,
                        lightcolor=ACCENT, darkcolor=ACCENT,
                        bordercolor=BORDER, focuscolor=BG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Panel.TCheckbutton", background=PANEL, foreground=TEXT,
                        lightcolor=ACCENT, darkcolor=ACCENT,
                        bordercolor="#3f3f46", focuscolor=PANEL)
        style.map("Panel.TCheckbutton", background=[("active", PANEL)])

        style.configure("TProgressbar", troughcolor="#0c0c0c", background=ACCENT,
                        bordercolor="#0c0c0c", lightcolor=ACCENT, darkcolor=ACCENT)

        style.configure("Vertical.TScrollbar", background="#424242",
                        troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                        relief="flat", arrowsize=11)
        style.map("Vertical.TScrollbar", background=[("active", "#4f4f4f")])
        style.configure("Horizontal.TScrollbar", background="#424242",
                        troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                        relief="flat", arrowsize=11)
        style.map("Horizontal.TScrollbar", background=[("active", "#4f4f4f")])

    def _build_ui(self):
        header = ttk.Frame(self, padding=(14, 12, 14, 10))
        header.pack(fill="x")
        title_row = ttk.Frame(header)
        title_row.pack(side="left")
        self.dot = tk.Canvas(title_row, width=14, height=14, bg=BG,
                             highlightthickness=0)
        self.dot.create_oval(3, 3, 11, 11, fill=MUTED, outline="", tags="dot")
        self.dot.pack(side="left", padx=(0, 8))
        ttk.Label(title_row, text="Human Typer", style="Title.TLabel"
                  ).pack(side="left")
        ttk.Label(header, text="v1.0", style="Version.TLabel"
                  ).pack(side="right")
        ttk.Label(header, text="Types code into VS Code at human speed",
                  style="Muted.TLabel").pack(side="right", padx=(0, 14))

        toolbar = ttk.Frame(self, padding=(14, 0, 14, 0))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Open File...", command=self.open_file
                   ).pack(side="left")
        ttk.Button(toolbar, text="From Clipboard", command=self.from_clipboard
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Clear", command=self.clear_code
                   ).pack(side="left", padx=(6, 0))

        codewrap = ttk.Frame(self, padding=(14, 8, 14, 0))
        codewrap.pack(fill="both", expand=True)
        self.code = tk.Text(codewrap, wrap="none", font=CODE_FONT,
                            bg=CODE_BG, fg=TEXT, insertbackground=TEXT,
                            selectbackground=CODE_SEL,
                            selectforeground="#ffffff", relief="flat", bd=0,
                            padx=10, pady=8, undo=True, highlightthickness=1,
                            highlightbackground=BORDER, highlightcolor=ACCENT)
        vsb = ttk.Scrollbar(codewrap, orient="vertical",
                            command=self.code.yview)
        hsb = ttk.Scrollbar(codewrap, orient="horizontal",
                            command=self.code.xview)
        self.code.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.code.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        codewrap.rowconfigure(0, weight=1)
        codewrap.columnconfigure(0, weight=1)
        self.code.bind("<Control-a>", self._select_all)

        settings = ttk.Frame(self, style="Panel.TFrame",
                             padding=(14, 12, 14, 12))
        settings.pack(fill="x", padx=14, pady=10)

        row1 = ttk.Frame(settings, style="Panel.TFrame")
        row1.pack(fill="x")
        ttk.Label(row1, text="Typing speed", style="Panel.TLabel"
                  ).pack(side="left")
        self.speed = tk.Scale(row1, from_=1, to=12, resolution=0.5,
                              orient="horizontal", length=280,
                              command=self._speed_changed, showvalue=False,
                              bg=PANEL, fg=TEXT, troughcolor="#0c0c0c",
                              activebackground=ACCENT,
                              highlightthickness=0, bd=0)
        self.speed.set(5.0)
        self.speed.pack(side="left", padx=(12, 10))
        self.speed_label = ttk.Label(row1, text="5.0 cps  (~60 wpm)",
                                     style="Panel.TLabel")
        self.speed_label.pack(side="left")

        row2 = ttk.Frame(settings, style="Panel.TFrame")
        row2.pack(fill="x", pady=(10, 0))
        self.jitter_var = tk.BooleanVar(value=True)
        self.thinking_var = tk.BooleanVar(value=True)
        self.mistakes_var = tk.BooleanVar(value=False)
        self.compensate_var = tk.BooleanVar(value=True)
        self.minimize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="Human jitter",
                        variable=self.jitter_var,
                        style="Panel.TCheckbutton").pack(side="left")
        ttk.Checkbutton(row2, text="Thinking pauses",
                        variable=self.thinking_var,
                        style="Panel.TCheckbutton").pack(side="left", padx=(10, 0))
        ttk.Checkbutton(row2, text="Typos",
                        variable=self.mistakes_var,
                        style="Panel.TCheckbutton").pack(side="left", padx=(10, 0))
        ttk.Checkbutton(row2, text="Fix editor auto-indent",
                        variable=self.compensate_var,
                        style="Panel.TCheckbutton").pack(side="left", padx=(10, 0))
        ttk.Checkbutton(row2, text="Minimize while typing",
                        variable=self.minimize_var,
                        style="Panel.TCheckbutton").pack(side="left", padx=(10, 0))

        row3 = ttk.Frame(settings, style="Panel.TFrame")
        row3.pack(fill="x", pady=(12, 0))
        self.start_btn = ttk.Button(row3, text="Start Typing",
                                    style="Accent.TButton", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(row3, text="Stop", style="Danger.TButton",
                                   state="disabled", command=self.stop)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(row3, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(14, 0))

        footer = ttk.Frame(self, padding=(14, 0, 14, 10))
        footer.pack(fill="x")
        self.status = tk.StringVar(
            value="Ready. Paste code, click Start Typing, then focus VS Code.")
        ttk.Label(footer, textvariable=self.status,
                  style="Muted.TLabel").pack(side="left")
        ttk.Label(footer, text="F8 = abort   \u00b7   floating bar = pause / stop",
                  style="Muted.TLabel").pack(side="right")

    def _build_float_bar(self):
        bar = tk.Toplevel(self)
        bar.withdraw()
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.configure(bg=PANEL, highlightthickness=1,
                      highlightbackground=BORDER)
        bar.bind("<Button-1>", self._drag_start)
        bar.bind("<B1-Motion>", self._drag_move)
        bar.protocol("WM_DELETE_WINDOW", self.stop)

        handle = tk.Label(bar, text="  \u2630  ", bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 12), cursor="fleur")
        handle.pack(side="left")

        bar_btn = dict(relief="flat", bd=0, padx=14, pady=5, cursor="hand2",
                       font=("Segoe UI", 10))
        self.pause_btn = tk.Button(bar, text="Pause",
                                   command=self.toggle_pause,
                                   bg=PANEL2, fg=TEXT,
                                   activebackground="#3e3e42",
                                   activeforeground=TEXT, **bar_btn)
        self.pause_btn.pack(side="left", padx=(0, 2), pady=3)
        self.stop_btn = tk.Button(bar, text="Stop", command=self.stop,
                                  bg=RED, fg="#ffffff",
                                  activebackground=RED_ACTIVE,
                                  activeforeground="#ffffff", **bar_btn)
        self.stop_btn.pack(side="left", padx=(0, 2), pady=3)
        self.bar_pct = tk.Label(bar, text="0%", bg=PANEL, fg="#9cdcfe",
                                font=("Segoe UI", 10, "bold"), padx=10)
        self.bar_pct.pack(side="left")
        self.bar = bar

    def _drag_start(self, event):
        self._drag_off = (event.x_root - self.bar.winfo_x(),
                          event.y_root - self.bar.winfo_y())

    def _drag_move(self, event):
        x = event.x_root - self._drag_off[0]
        y = event.y_root - self._drag_off[1]
        self.bar.geometry(f"+{x}+{y}")

    def show_bar(self):
        self.bar.update_idletasks()
        w, h = self.bar.winfo_reqwidth(), self.bar.winfo_reqheight()
        x = self.winfo_screenwidth() - w - 24
        self.bar.geometry(f"+{x}+24")
        self.bar.deiconify()

    def hide_bar(self):
        if self.bar.winfo_exists():
            self.bar.withdraw()

    def _select_all(self, _event):
        self.code.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _speed_changed(self, value):
        cps = float(value)
        self.speed_label.config(text=f"{cps:.1f} cps  (~{int(cps * 12)} wpm)")

    def _load_settings(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            return
        try:
            self.speed.set(float(cfg.get("speed", 5.0)))
            self.jitter_var.set(bool(cfg.get("jitter", True)))
            self.thinking_var.set(bool(cfg.get("thinking", True)))
            self.mistakes_var.set(bool(cfg.get("mistakes", False)))
            self.compensate_var.set(bool(cfg.get("compensate", True)))
            self.minimize_var.set(bool(cfg.get("minimize", True)))
            self._speed_changed(self.speed.get())
        except (KeyError, TypeError):
            pass

    def _save_settings(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            cfg = {
                "speed": float(self.speed.get()),
                "jitter": self.jitter_var.get(),
                "thinking": self.thinking_var.get(),
                "mistakes": self.mistakes_var.get(),
                "compensate": self.compensate_var.get(),
                "minimize": self.minimize_var.get(),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except OSError:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open code file",
            filetypes=[("Code files", "*.py *.js *.ts *.tsx *.jsx *.c *.cpp "
                        "*.h *.cs *.java *.go *.rs *.rb *.php *.sh *.sql "
                        "*.json *.html *.css *.md *.txt"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as exc:
            messagebox.showerror("Open File", f"Could not read file:\n{exc}")
            return
        self.code.delete("1.0", "end")
        self.code.insert("1.0", text)

    def from_clipboard(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Clipboard", "Clipboard is empty.")
            return
        self.code.delete("1.0", "end")
        self.code.insert("1.0", text)

    def clear_code(self):
        self.code.delete("1.0", "end")

    def start(self):
        text = self.code.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showwarning("Human Typer", "Nothing to type.")
            return
        self.stop_requested = False
        self.paused = False
        self.pause_btn.config(text="Pause", bg=PANEL2,
                              activebackground="#3e3e42")
        self._set_dot(GREEN)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress["value"] = 0
        self.bar_pct.config(text="0%")
        self.show_bar()
        self.attributes("-topmost", True)
        self.countdown(3)

    def countdown(self, n):
        if self.stop_requested:
            self._finish("Stopped.")
            return
        if self.paused:
            self.after(250, self.countdown, n)
            return
        if n > 0:
            self.status.set(f"Click into VS Code now — starting in {n}...")
            self.after(1000, self.countdown, n - 1)
            return
        self.attributes("-topmost", False)
        self.status.set("Typing...")
        if self.minimize_var.get():
            self.iconify()
        self.after(200, self.run_typer)

    def run_typer(self):
        text = self.code.get("1.0", "end-1c")
        self.typer = HumanTyper(
            text,
            cps=float(self.speed.get()),
            jitter=self.jitter_var.get(),
            thinking=self.thinking_var.get(),
            mistakes=self.mistakes_var.get(),
            compensate=self.compensate_var.get(),
            is_paused=self._is_paused,
            update_ui=self._tick_ui,
        )
        self.deiconify()
        started = time.time()
        ok = self.typer.run(on_progress=self._progress)
        if not ok:
            self._finish("Stopped.")
            return
        elapsed = time.time() - started
        self._finish(f"Done — typed {len(text)} chars in {elapsed:.1f} s.")
        winsound.Beep(880, 150)
        winsound.Beep(1175, 200)

    def _progress(self, frac):
        self.progress["value"] = frac * 100
        self.bar_pct.config(text=f"{int(frac * 100)}%")
        self.update_idletasks()

    def _tick_ui(self):
        self.update()

    def _is_paused(self):
        return self.paused

    def _is_cancelled(self):
        if self.stop_requested:
            return True
        if self.typer and self.typer.stop_requested:
            return True
        return bool(user32.GetAsyncKeyState(VK_F8) & 0x8000)

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pause_btn.config(text="Resume", bg=WARN,
                                  activebackground="#b7821c")
            self._set_dot(WARN)
            self.status.set("Paused — resume from the floating bar.")
        else:
            self.pause_btn.config(text="Pause", bg=PANEL2,
                                  activebackground="#3e3e42")
            self._set_dot(GREEN)
            self.status.set("Typing...")

    def _set_dot(self, color):
        try:
            self.dot.itemconfigure("dot", fill=color)
        except tk.TclError:
            pass

    def stop(self):
        self.stop_requested = True
        if self.typer:
            self.typer.stop_requested = True

    def _finish(self, message):
        self.stop_requested = True
        if self.typer:
            self.typer.stop_requested = True
        self.paused = False
        self.pause_btn.config(text="Pause", bg=PANEL2,
                              activebackground="#3e3e42")
        self._set_dot(MUTED)
        self.attributes("-topmost", False)
        if self.state() == "iconic":
            self.deiconify()
        self.status.set(message)
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress["value"] = 0
        self.hide_bar()


if __name__ == "__main__":
    App().mainloop()
