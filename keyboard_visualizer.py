#!/usr/bin/env python3
"""
Charybdis ZMK Keyboard Layout Visualizer
=========================================
Parses config/charybdis.keymap and displays all 9 layers interactively.
Keys you press on the real keyboard are highlighted in real time.

Usage:
    python3 keyboard_visualizer.py

Shortcuts:
    1-9        Switch to layer 0-8
    ←/→        Previous / next layer
    R          Reload keymap file
"""

import sys
import re
import os
import select
import time

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QShortcut, QTextEdit,
)
from PyQt5.QtCore import Qt, QRect, QFileSystemWatcher, QRectF, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence as QKS
from PyQt5.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush,
    QLinearGradient, QPainterPath,
)

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYMAP_FILE = os.path.join(SCRIPT_DIR, "config", "charybdis.keymap")

# ── Layer metadata ─────────────────────────────────────────────────────────
LAYER_DEFS = [
    (0, "Base",   "#4a90d9", "Default typing — homerow mods on ASDF / JKL;"),
    (1, "Media",  "#3cb878", "Media controls — hold ESC to activate"),
    (2, "Nav",    "#5b8dd9", "Navigation — arrows, clipboard, page scroll"),
    (3, "Mouse",  "#9b59b6", "Trackball snipe mode — precise cursor movement"),
    (4, "Sym",    "#e67e22", "Symbols  { & * ( } : $ % ^ + etc."),
    (5, "Num",    "#e74c3c", "Numbers 0-9 and brackets [ ] = ; ` \\"),
    (6, "Fun",    "#1abc9c", "Function keys F1-F12, Print Screen, Pause"),
    (7, "Button", "#d4a017", "Bluetooth profiles, USB/BLE toggle, power"),
    (8, "RGB",    "#8e44ad", "RGB LED controls — hue, sat, brightness, effects"),
]

# ── Key colour scheme ──────────────────────────────────────────────────────
KEY_COLORS = {
    "normal":  ("#2d3347", "#c8cce0"),
    "trans":   ("#1a1c28", "#50506a"),
    "none":    ("#141520", "#383848"),
    "mod":     ("#1a3a52", "#80d0f8"),
    "layer":   ("#30204a", "#c090ff"),
    "macro":   ("#1a3828", "#70e090"),
    "special": ("#38280e", "#f0c050"),
    "rgb":     ("#381838", "#f080f0"),
    "mouse":   ("#2c2c0e", "#d8d050"),
}

# ── ZMK label helpers ──────────────────────────────────────────────────────
MOD_ABBREV = {
    "LGUI": "⌘L", "RGUI": "⌘R",
    "LALT": "⌥L", "RALT": "⌥R",
    "LCTRL": "⌃L", "RCTRL": "⌃R",
    "LSHIFT": "⇧L", "RSHIFT": "⇧R",
    "LSHFT": "⇧L",  "RSHFT": "⇧R",
}

KEY_DISPLAY = {
    "BACKSPACE": "⌫",  "ESCAPE": "ESC",  "TAB": "⇥",
    "ENTER": "↵",      "RETURN": "↵",    "SPACE": "SPC",
    "DELETE": "Del",   "INSERT": "Ins",
    "LEFT": "←",  "RIGHT": "→",  "UP": "↑",  "DOWN": "↓",
    "HOME": "Home", "END": "End",
    "PAGE_UP": "PgUp", "PAGE_DOWN": "PgDn",
    "PRINTSCREEN": "PrtSc",  "SCROLLLOCK": "ScrLk",
    "PAUSE_BREAK": "Pause",  "CAPS": "Caps",
    "LEFT_BRACE": "{",  "RIGHT_BRACE": "}",
    "LEFT_BRACKET": "[", "RIGHT_BRACKET": "]",
    "LEFT_PARENTHESIS": "(", "RIGHT_PARENTHESIS": ")",
    "AMPERSAND": "&",  "ASTERISK": "*",  "DOLLAR": "$",
    "PERCENT": "%",    "CARET": "^",     "PLUS": "+",
    "COLON": ":",      "EXCL": "!",      "AT": "@",   "HASH": "#",
    "PIPE": "|",       "TILDE": "~",     "GRAVE": "`",
    "SEMICOLON": ";",  "COMMA": ",",     "DOT": ".",
    "SLASH": "/",      "BACKSLASH": "\\","MINUS": "-",
    "EQUAL": "=",      "UNDERSCORE": "_","SQT": "'",  "DQT": '"',
    "NUMBER_0": "0", "NUMBER_1": "1", "NUMBER_2": "2",
    "NUMBER_3": "3", "NUMBER_4": "4", "NUMBER_5": "5",
    "NUMBER_6": "6", "NUMBER_7": "7", "NUMBER_8": "8", "NUMBER_9": "9",
    "N0": "0", "N1": "1", "N2": "2", "N3": "3", "N4": "4",
    "N5": "5", "N6": "6", "N7": "7", "N8": "8", "N9": "9",
    "C_PREVIOUS": "⏮",  "C_NEXT": "⏭",    "C_PREV": "⏮",
    "C_VOLUME_UP": "Vol+","C_VOLUME_DOWN": "Vol-",
    "C_VOL_UP": "Vol+",  "C_VOL_DN": "Vol-",
    "C_PLAY_PAUSE": "⏯", "C_STOP": "⏹",   "C_MENU": "☰",
}

MACRO_LABELS = {
    "&undo":       ("Undo",   "⌃Z", "macro",  "Macro: Ctrl+Z"),
    "&cut":        ("Cut",    "⌃X", "macro",  "Macro: Ctrl+X"),
    "&copy":       ("Copy",   "⌃C", "macro",  "Macro: Ctrl+C"),
    "&paste":      ("Paste",  "⌃V", "macro",  "Macro: Ctrl+V"),
    "&select_all": ("SelAll", "⌃A", "macro",  "Macro: Ctrl+A"),
}


def fmt_key(key: str) -> str:
    if key in KEY_DISPLAY:
        return KEY_DISPLAY[key]
    return key.title() if len(key) > 3 else key


def layer_short(n: int) -> str:
    return LAYER_DEFS[n][1][:4] if n < len(LAYER_DEFS) else f"L{n}"


def parse_binding(raw: str):
    """Return (main_label, sub_label, key_type, tooltip_text)."""
    b = raw.strip()
    if b == "&trans":
        return "▽", "", "trans", "Transparent — inherits key from the next active layer below"
    if b in ("&none", "&kp NONE"):
        return "✕", "", "none", "No operation"
    if b == "&bootloader":
        return "BOOT", "", "special", "Enter bootloader / DFU mode (flash new firmware)"
    if b in MACRO_LABELS:
        return MACRO_LABELS[b]
    if b.startswith("&kp "):
        key = b[4:].strip()
        return fmt_key(key), "", "normal", f"Key: {key}"
    if b.startswith("&hm "):
        parts = b[4:].split()
        mod, key = parts[0], parts[1]
        mod_s = MOD_ABBREV.get(mod, mod[:4])
        return fmt_key(key), mod_s, "mod", (
            f"Homerow mod\n  Tap  →  {fmt_key(key)}\n  Hold →  {mod}"
        )
    if b.startswith("&lt "):
        parts = b[4:].split()
        ln, key = int(parts[0]), parts[1]
        lname = LAYER_DEFS[ln][1] if ln < len(LAYER_DEFS) else f"L{ln}"
        return fmt_key(key), f"[{layer_short(ln)}]", "layer", (
            f"Layer-tap\n  Tap  →  {fmt_key(key)}\n  Hold →  Layer {ln}: {lname}"
        )
    _LTS_LAYER = {
        "lts_media": 1, "lts_nav": 2, "lts_mouse": 3,
        "lts_sym": 4,   "lts_num": 5,
        "lts_fun": 6,   "lts_rgb": 8,
    }
    if b.startswith("&lts_"):
        parts = b.split()
        bname = parts[0][1:]  # strip &
        ln = _LTS_LAYER.get(bname)
        if ln is not None and len(parts) >= 3:
            key = parts[2]   # parts[1] is the dummy 0
            lname = LAYER_DEFS[ln][1] if ln < len(LAYER_DEFS) else f"L{ln}"
            _LTS_SIGNAL_KEY = {1:"F20",2:"F21",3:"F22",4:"F23",5:"F24",6:"F13",8:"F14"}
            sig = _LTS_SIGNAL_KEY.get(ln, f"F??")
            return fmt_key(key), f"[{layer_short(ln)}]★", "layer", (
                f"Signaled layer-tap\n  Tap  →  {fmt_key(key)}\n"
                f"  Hold →  Layer {ln}: {lname}  (sends {sig} signal)"
            )
    if b.startswith("&mo "):
        ln = int(b[4:].strip())
        lname = LAYER_DEFS[ln][1] if ln < len(LAYER_DEFS) else f"L{ln}"
        return f"[{lname}]", "", "layer", f"Momentary layer {ln}: {lname}"
    if b.startswith("&bt "):
        cmd = b[4:].strip()
        labels = {
            "BT_CLR": "BT CLR", "BT_NXT": "BT ►",  "BT_PRV": "◄ BT",
            "BT_SEL 0": "BT 0", "BT_SEL 1": "BT 1",
            "BT_SEL 2": "BT 2", "BT_SEL 3": "BT 3",
        }
        return labels.get(cmd, f"BT {cmd[:5]}"), "", "special", f"Bluetooth: {cmd}"
    if b.startswith("&out "):
        cmd = b[5:].strip()
        labels = {"OUT_TOG": "OUT↕", "OUT_USB": "USB", "OUT_BLE": "BLE"}
        return labels.get(cmd, cmd[:8]), "", "special", f"Output toggle: {cmd}"
    if b.startswith("&rgb_ug "):
        cmd = b[8:].strip()
        rgb_map = {
            "RGB_TOG": "RGB↕",  "RGB_HUI": "Hue+",  "RGB_HUD": "Hue−",
            "RGB_SAI": "Sat+",  "RGB_SAD": "Sat−",
            "RGB_BRI": "Bri+",  "RGB_BRD": "Bri−",
            "RGB_SPI": "Spd+",  "RGB_SPD": "Spd−",
            "RGB_EFF": "Eff+",  "RGB_EFR": "Eff−",
        }
        return rgb_map.get(cmd, cmd[:7]), "", "rgb", f"RGB: {cmd}"
    if b.startswith("&ext_power "):
        cmd = b[11:].strip()
        labels = {"EP_TOG": "Pwr↕", "EP_ON": "Pwr✓", "EP_OFF": "Pwr✗"}
        return labels.get(cmd, cmd[:7]), "", "special", f"External power: {cmd}"
    if b.startswith("&mkp "):
        btn = b[5:].strip()
        btn_map = {"LCLK": "LMB", "RCLK": "RMB", "MCLK": "MMB",
                   "MB4": "MB4", "MB5": "MB5"}
        return btn_map.get(btn, btn), "", "mouse", f"Mouse button: {btn}"
    label = b.replace("&", "").replace("_", " ")[:9]
    return label, "", "normal", b


# ── Keymap parser ──────────────────────────────────────────────────────────

def extract_bindings(text: str):
    text = re.sub(r'//.*', '', text)
    result = []
    for part in text.split('&'):
        p = ' '.join(part.split())
        if p:
            result.append('&' + p)
    return result


def parse_keymap(filepath: str):
    with open(filepath, 'r') as f:
        content = f.read()
    layers = []
    pattern = re.compile(r'(\w+)\s*\{[^{]*?bindings\s*=\s*<([^>]*)>', re.DOTALL)
    for m in pattern.finditer(content):
        name = m.group(1)
        bindings = extract_bindings(m.group(2))
        if len(bindings) >= 30:
            layers.append((name, bindings))
    return layers


# ── evdev key highlighting ─────────────────────────────────────────────────
try:
    import evdev
    from evdev import ecodes as EC
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

if HAS_EVDEV:
    # ZMK key name → evdev keycode
    ZMK_TO_EVDEV = {
        # Letters
        "A": EC.KEY_A, "B": EC.KEY_B, "C": EC.KEY_C, "D": EC.KEY_D,
        "E": EC.KEY_E, "F": EC.KEY_F, "G": EC.KEY_G, "H": EC.KEY_H,
        "I": EC.KEY_I, "J": EC.KEY_J, "K": EC.KEY_K, "L": EC.KEY_L,
        "M": EC.KEY_M, "N": EC.KEY_N, "O": EC.KEY_O, "P": EC.KEY_P,
        "Q": EC.KEY_Q, "R": EC.KEY_R, "S": EC.KEY_S, "T": EC.KEY_T,
        "U": EC.KEY_U, "V": EC.KEY_V, "W": EC.KEY_W, "X": EC.KEY_X,
        "Y": EC.KEY_Y, "Z": EC.KEY_Z,
        # Numbers
        "NUMBER_0": EC.KEY_0, "NUMBER_1": EC.KEY_1, "NUMBER_2": EC.KEY_2,
        "NUMBER_3": EC.KEY_3, "NUMBER_4": EC.KEY_4, "NUMBER_5": EC.KEY_5,
        "NUMBER_6": EC.KEY_6, "NUMBER_7": EC.KEY_7, "NUMBER_8": EC.KEY_8,
        "NUMBER_9": EC.KEY_9,
        "N0": EC.KEY_0, "N1": EC.KEY_1, "N2": EC.KEY_2, "N3": EC.KEY_3,
        "N4": EC.KEY_4, "N5": EC.KEY_5, "N6": EC.KEY_6, "N7": EC.KEY_7,
        "N8": EC.KEY_8, "N9": EC.KEY_9,
        # Control / navigation
        "ESCAPE": EC.KEY_ESC,         "BACKSPACE": EC.KEY_BACKSPACE,
        "TAB": EC.KEY_TAB,            "ENTER": EC.KEY_ENTER,
        "RETURN": EC.KEY_ENTER,       "SPACE": EC.KEY_SPACE,
        "DELETE": EC.KEY_DELETE,      "INSERT": EC.KEY_INSERT,
        "LEFT": EC.KEY_LEFT,          "RIGHT": EC.KEY_RIGHT,
        "UP": EC.KEY_UP,              "DOWN": EC.KEY_DOWN,
        "HOME": EC.KEY_HOME,          "END": EC.KEY_END,
        "PAGE_UP": EC.KEY_PAGEUP,     "PAGE_DOWN": EC.KEY_PAGEDOWN,
        "CAPS": EC.KEY_CAPSLOCK,
        "PRINTSCREEN": EC.KEY_SYSRQ,  "SCROLLLOCK": EC.KEY_SCROLLLOCK,
        "PAUSE_BREAK": EC.KEY_PAUSE,
        # Punctuation (base keys; shifted variants map to the same physical key)
        "SEMICOLON": EC.KEY_SEMICOLON, "COMMA": EC.KEY_COMMA,
        "DOT": EC.KEY_DOT,             "SLASH": EC.KEY_SLASH,
        "BACKSLASH": EC.KEY_BACKSLASH, "MINUS": EC.KEY_MINUS,
        "EQUAL": EC.KEY_EQUAL,         "GRAVE": EC.KEY_GRAVE,
        "SQT": EC.KEY_APOSTROPHE,
        "LEFT_BRACKET":  EC.KEY_LEFTBRACE,
        "RIGHT_BRACKET": EC.KEY_RIGHTBRACE,
        # Shifted symbols → same physical key as their base form
        "EXCL": EC.KEY_1,            "AT": EC.KEY_2,
        "HASH": EC.KEY_3,            "DOLLAR": EC.KEY_4,
        "PERCENT": EC.KEY_5,         "CARET": EC.KEY_6,
        "AMPERSAND": EC.KEY_7,       "ASTERISK": EC.KEY_8,
        "LEFT_PARENTHESIS":  EC.KEY_9,
        "RIGHT_PARENTHESIS": EC.KEY_0,
        "UNDERSCORE": EC.KEY_MINUS,  "PLUS": EC.KEY_EQUAL,
        "LEFT_BRACE":  EC.KEY_LEFTBRACE,
        "RIGHT_BRACE": EC.KEY_RIGHTBRACE,
        "COLON": EC.KEY_SEMICOLON,   "DQT": EC.KEY_APOSTROPHE,
        "TILDE": EC.KEY_GRAVE,       "PIPE": EC.KEY_BACKSLASH,
        # Function keys
        "F1":  EC.KEY_F1,  "F2":  EC.KEY_F2,  "F3":  EC.KEY_F3,
        "F4":  EC.KEY_F4,  "F5":  EC.KEY_F5,  "F6":  EC.KEY_F6,
        "F7":  EC.KEY_F7,  "F8":  EC.KEY_F8,  "F9":  EC.KEY_F9,
        "F10": EC.KEY_F10, "F11": EC.KEY_F11, "F12": EC.KEY_F12,
        "F13": EC.KEY_F13, "F14": EC.KEY_F14, "F15": EC.KEY_F15,
        "F16": EC.KEY_F16, "F17": EC.KEY_F17, "F18": EC.KEY_F18,
        "F19": EC.KEY_F19, "F20": EC.KEY_F20, "F21": EC.KEY_F21,
        "F22": EC.KEY_F22, "F23": EC.KEY_F23, "F24": EC.KEY_F24,
        # Modifiers (for homerow-mod hold detection)
        "LGUI": EC.KEY_LEFTMETA,   "RGUI": EC.KEY_RIGHTMETA,
        "LALT": EC.KEY_LEFTALT,    "RALT": EC.KEY_RIGHTALT,
        "LCTRL": EC.KEY_LEFTCTRL,  "RCTRL": EC.KEY_RIGHTCTRL,
        "LSHIFT": EC.KEY_LEFTSHIFT,"RSHIFT": EC.KEY_RIGHTSHIFT,
        "LSHFT": EC.KEY_LEFTSHIFT, "RSHFT": EC.KEY_RIGHTSHIFT,
        # Media
        "C_PREVIOUS": EC.KEY_PREVIOUSSONG, "C_PREV": EC.KEY_PREVIOUSSONG,
        "C_NEXT":     EC.KEY_NEXTSONG,
        "C_VOLUME_UP": EC.KEY_VOLUMEUP,    "C_VOL_UP": EC.KEY_VOLUMEUP,
        "C_VOLUME_DOWN": EC.KEY_VOLUMEDOWN,"C_VOL_DN": EC.KEY_VOLUMEDOWN,
        "C_PLAY_PAUSE": EC.KEY_PLAYPAUSE,
        "C_STOP": EC.KEY_STOPCD,
        "C_MENU": EC.KEY_MENU,
    }

    # F20-F24 are sent by the layer-signal macros in ZMK when a thumb &lt
    # hold is activated / released.  They map directly to layer indices.
    LAYER_SIGNAL_CODES = {
        EC.KEY_F13: 6,   # Fun   (&lts_fun  0 SLASH)
        EC.KEY_F14: 8,   # RGB   (&lts_rgb  0 P)
        EC.KEY_F20: 1,   # Media (&lts_media 0 ESCAPE)
        EC.KEY_F21: 2,   # Nav   (&lts_nav  0 TAB)
        EC.KEY_F22: 3,   # Mouse (&lts_mouse 0 SPACE)
        EC.KEY_F23: 4,   # Sym   (&lts_sym  0 BACKSPACE)
        EC.KEY_F24: 5,   # Num   (&lts_num  0 ENTER)
    }

    def binding_to_evdev_codes(binding: str) -> list:
        """Return list of evdev keycodes a binding can produce (tap + hold)."""
        b = binding.strip()
        codes = []
        if b.startswith("&kp "):
            c = ZMK_TO_EVDEV.get(b[4:].strip())
            if c is not None:
                codes.append(c)
        elif b.startswith("&hm "):
            parts = b[4:].split()
            # Only the tap key — modifier hold is resolved by ZMK already,
            # and tracked separately via build_mod_hold_map.
            if len(parts) >= 2:
                c = ZMK_TO_EVDEV.get(parts[1])
                if c is not None:
                    codes.append(c)
        elif b.startswith("&lt "):
            parts = b[4:].split()
            c = ZMK_TO_EVDEV.get(parts[1])
            if c is not None:
                codes.append(c)
        elif b.startswith("&lts_"):
            # &lts_media 0 ESCAPE — tap key is parts[2] (skip dummy 0)
            parts = b.split()
            if len(parts) >= 3:
                c = ZMK_TO_EVDEV.get(parts[2])
                if c is not None:
                    codes.append(c)
        elif b in ("&undo", "&cut", "&copy", "&paste", "&select_all"):
            # macros use ctrl combos; ctrl and the letter both fire
            macro_keys = {
                "&undo": [EC.KEY_LEFTCTRL, EC.KEY_Z],
                "&cut":  [EC.KEY_LEFTCTRL, EC.KEY_X],
                "&copy": [EC.KEY_LEFTCTRL, EC.KEY_C],
                "&paste":[EC.KEY_LEFTCTRL, EC.KEY_V],
                "&select_all": [EC.KEY_LEFTCTRL, EC.KEY_A],
            }
            codes.extend(macro_keys[b])
        return codes

    def build_reverse_map(bindings: list) -> dict:
        """evdev_code → key_index for the given layer."""
        result = {}
        for idx, raw in enumerate(bindings):
            for code in binding_to_evdev_codes(raw):
                # First mapping wins (don't overwrite with &trans positions)
                if code not in result:
                    result[code] = idx
        return result

    def build_mod_hold_map(bindings: list) -> dict:
        """modifier_evdev_code → key_index for &hm holds.
        Only includes modifiers that are unique to a single physical key so we
        can unambiguously highlight the correct key (e.g. LGUI→A is unique,
        but LCTRL is shared by D and Z so it's excluded)."""
        mod_to_indices: dict = {}
        for idx, raw in enumerate(bindings):
            b = raw.strip()
            if b.startswith("&hm "):
                parts = b[4:].split()
                if len(parts) >= 1:
                    mod_code = ZMK_TO_EVDEV.get(parts[0])
                    if mod_code is not None:
                        mod_to_indices.setdefault(mod_code, []).append(idx)
        # Drop any modifier that maps to more than one physical key
        return {code: idxs[0] for code, idxs in mod_to_indices.items() if len(idxs) == 1}

    def _evdev_name(code: int) -> str:
        """Human-readable name for a raw evdev keycode."""
        raw = EC.KEY.get(code, f"#{code}")
        if isinstance(raw, list):
            raw = raw[0]
        return raw.replace("KEY_", "")

    class KeyListener(QThread):
        """Background thread: reads evdev events and emits key_event signals.

        Watches only the ZMK Charybdis keyboard (device name must contain
        'charybdis', case-insensitive).  Automatically reconnects when the
        dongle reboots — rescans /dev/input/event* every RESCAN_INTERVAL
        seconds and subscribes to any newly-appearing Charybdis device.
        """
        key_event     = pyqtSignal(int, bool)  # (evdev_keycode, is_pressed)
        status_signal = pyqtSignal(str, str)   # (message, color_hex)
        device_lost   = pyqtSignal()           # emitted when Charybdis disconnects

        RESCAN_INTERVAL = 2.0   # seconds between /dev/input rescans
        DEVICE_KEYWORD  = "charybdis"

        def __init__(self, parent=None):
            super().__init__(parent)
            self._running = True

        # ------------------------------------------------------------------
        # helpers
        # ------------------------------------------------------------------
        def _is_charybdis(self, dev: "evdev.InputDevice") -> bool:
            return self.DEVICE_KEYWORD in dev.name.lower()

        def _open_charybdis_devices(self) -> dict:
            """Return {path: InputDevice} for every Charybdis event node found."""
            import glob
            found = {}
            for path in sorted(glob.glob("/dev/input/event*")):
                try:
                    dev = evdev.InputDevice(path)
                    if self._is_charybdis(dev):
                        found[path] = dev
                        print(f"[KeyListener] found: {dev.name} ({path})")
                except PermissionError:
                    pass
                except Exception:
                    pass
            return found

        def _update_status(self, devices: dict) -> None:
            if devices:
                names = ", ".join(d.name for d in devices.values())
                self.status_signal.emit(f"● listening: {names}", "#40a060")
            else:
                self.status_signal.emit(
                    f"○ waiting for ZMK keyboard ({self.DEVICE_KEYWORD})…", "#806040"
                )

        # ------------------------------------------------------------------
        # main loop
        # ------------------------------------------------------------------
        def run(self):
            import glob, time

            # Check whether we can open any input device at all (permissions).
            try:
                all_paths = sorted(glob.glob("/dev/input/event*"))
                if all_paths:
                    evdev.InputDevice(all_paths[0])   # probe first device
            except PermissionError:
                self.status_signal.emit(
                    "○ no input access — run: sudo usermod -aG input $USER  then log out/in",
                    "#804040",
                )
                return
            except Exception:
                pass

            devices: dict = self._open_charybdis_devices()
            self._update_status(devices)

            last_rescan = time.monotonic()

            while self._running:
                try:
                    dev_list = list(devices.values())
                    readable, _, _ = select.select(dev_list, [], [], 0.1)

                    # ── read available events ──────────────────────────────
                    for dev in readable:
                        try:
                            for ev in dev.read():
                                if ev.type == EC.EV_KEY and ev.value in (0, 1):
                                    self.key_event.emit(ev.code, ev.value == 1)
                        except OSError:
                            # Device disconnected (dongle rebooted, USB pulled…)
                            path = dev.path
                            print(f"[KeyListener] lost: {dev.name} ({path})")
                            devices.pop(path, None)
                            self.device_lost.emit()
                            self._update_status(devices)

                    # ── periodic rescan for newly connected Charybdis ──────
                    now = time.monotonic()
                    if now - last_rescan >= self.RESCAN_INTERVAL:
                        last_rescan = now
                        new_paths = sorted(glob.glob("/dev/input/event*"))
                        for path in new_paths:
                            if path in devices:
                                continue   # already tracking
                            try:
                                dev = evdev.InputDevice(path)
                                if self._is_charybdis(dev):
                                    devices[path] = dev
                                    print(f"[KeyListener] reconnected: {dev.name} ({path})")
                                    self._update_status(devices)
                            except Exception:
                                pass

                except Exception:
                    pass

        def stop(self):
            self._running = False


# ── Key widget ─────────────────────────────────────────────────────────────

class Key(QWidget):
    """One physical key, drawn with QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main     = ""
        self.sub      = ""
        self.ktype    = "normal"
        self._hovered  = False
        self._pressed  = False
        self._mod_held = False
        self.setMouseTracking(True)

    def set_binding(self, main, sub, ktype, tip):
        self.main, self.sub, self.ktype = main, sub, ktype
        self.setToolTip(tip)
        self.update()

    def set_pressed(self, pressed: bool):
        if self._pressed != pressed:
            self._pressed = pressed
            self.update()

    def set_mod_held(self, held: bool):
        if self._mod_held != held:
            self._mod_held = held
            self.update()

    def enterEvent(self, _): self._hovered = True;  self.update()
    def leaveEvent(self, _): self._hovered = False; self.update()

    def paintEvent(self, _):
        bg_hex, fg_hex = KEY_COLORS.get(self.ktype, KEY_COLORS["normal"])
        bg = QColor(bg_hex)
        fg = QColor(fg_hex)

        if self._mod_held:
            bg = bg.lighter(220)
            bg = QColor(min(255, bg.red() + 90), max(0, bg.green() - 20), max(0, bg.blue() - 20))
        elif self._pressed:
            bg = bg.lighter(280)
        elif self._hovered:
            bg = bg.lighter(150)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)

        # Drop shadow
        shadow = QPainterPath()
        sr = r.adjusted(1, 2, 1, 2)
        shadow.addRoundedRect(QRectF(sr.x(), sr.y(), sr.width(), sr.height()), 7, 7)
        p.fillPath(shadow, QColor(0, 0, 0, 70))

        # Key face
        face = QPainterPath()
        face.addRoundedRect(QRectF(r.x(), r.y(), r.width(), r.height()), 7, 7)
        p.fillPath(face, bg)

        # Top gloss
        gloss = QLinearGradient(0, r.top(), 0, r.top() + r.height() * 0.45)
        gloss.setColorAt(0, QColor(255, 255, 255, 28))
        gloss.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(face, QBrush(gloss))

        # Border — bright glow when pressed or mod held
        if self._mod_held:
            p.setPen(QPen(QColor(255, 100, 80, 220), 2.5))
        elif self._pressed:
            p.setPen(QPen(QColor(255, 240, 160, 230), 2.5))
        elif self._hovered:
            p.setPen(QPen(QColor(255, 255, 255, 55), 1.2))
        else:
            p.setPen(QPen(QColor(0, 0, 0, 90), 1.2))
        p.drawPath(face)

        # Text
        p.setPen(fg if not (self._pressed or self._mod_held) else QColor(20, 20, 20))
        if self.sub:
            font = QFont("Monospace", 10, QFont.Bold)
            p.setFont(font)
            top_rect = QRect(r.x(), r.y() + 4, r.width(), r.height() - 18)
            p.drawText(top_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.main)
            font2 = QFont("Monospace", 7)
            p.setFont(font2)
            p.setPen(fg.darker(150) if not (self._pressed or self._mod_held) else QColor(40, 40, 40))
            bot_rect = QRect(r.x(), r.bottom() - 16, r.width(), 16)
            p.drawText(bot_rect, Qt.AlignHCenter | Qt.AlignBottom, self.sub)
        else:
            font = QFont("Monospace", 10, QFont.Bold)
            p.setFont(font)
            p.drawText(r, Qt.AlignCenter, self.main)

        p.end()


# ── Keyboard canvas ────────────────────────────────────────────────────────
KW, KH, KG = 64, 60, 5
HG = 30
L_STAGGER = [14, 4, 0, 6, 12]
R_STAGGER  = [12, 6, 0, 4, 14]


class KeyboardCanvas(QWidget):
    """Renders the full split keyboard with columnar stagger."""

    def __init__(self, parent=None):
        super().__init__(parent)

        max_stag = max(max(L_STAGGER), max(R_STAGGER))
        half_w   = 5 * (KW + KG) - KG
        total_w  = 2 * half_w + HG
        rows_h   = 3 * (KH + KG) - KG + max_stag
        total_h  = rows_h + KG * 3 + KH

        self.setFixedSize(total_w + 20, total_h + 20)
        self._keys = [Key(parent=self) for _ in range(35)]
        for k in self._keys:
            k.setFixedSize(KW, KH)

        for row in range(3):
            for col in range(10):
                idx = row * 10 + col
                if col < 5:
                    hcol = col
                    stag = L_STAGGER[hcol]
                    x    = 10 + hcol * (KW + KG)
                else:
                    hcol = col - 5
                    stag = R_STAGGER[hcol]
                    x    = 10 + half_w + HG + hcol * (KW + KG)
                y = 10 + stag + row * (KH + KG)
                self._keys[idx].move(x, y)

        thumb_y = 10 + max_stag + 3 * (KH + KG) + KG * 2
        lx = 10 + 2 * (KW + KG)
        for i, idx in enumerate([30, 31, 32]):
            self._keys[idx].move(lx + i * (KW + KG), thumb_y)
        rx = 10 + half_w + HG
        for i, idx in enumerate([33, 34]):
            self._keys[idx].move(rx + i * (KW + KG), thumb_y)

        self._trackball_x = rx + 2 * (KW + KG) + KG + KW // 2
        self._trackball_y = thumb_y + KH // 2

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d0d1a"))
        p.setPen(QPen(QColor("#333350"), 2))
        p.setBrush(QColor("#1a1a30"))
        r = KH // 2 - 4
        p.drawEllipse(self._trackball_x - r, self._trackball_y - r, r * 2, r * 2)
        p.setBrush(QColor("#2a2a50"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(self._trackball_x - r // 3, self._trackball_y - r // 3,
                      r * 2 // 3, r * 2 // 3)
        p.end()

    def load_layer(self, bindings):
        for i, raw in enumerate(bindings[:35]):
            self._keys[i].set_binding(*parse_binding(raw))

    def set_key_pressed(self, idx: int, pressed: bool):
        if 0 <= idx < len(self._keys):
            self._keys[idx].set_pressed(pressed)

    def set_key_mod_held(self, idx: int, held: bool):
        if 0 <= idx < len(self._keys):
            self._keys[idx].set_mod_held(held)

    def release_all(self):
        for k in self._keys:
            k.set_pressed(False)
            k.set_mod_held(False)


# ── Debug window ───────────────────────────────────────────────────────────

class DebugWindow(QWidget):
    """Floating log of raw evdev events and how they were resolved."""

    _BTN_STYLE = """
        QPushButton { background:#141428; color:#6070a0;
            border:1px solid #222240; border-radius:3px; padding:0 8px; }
        QPushButton:hover { background:#1e1e40; color:#c0c8e0; }
    """

    def __init__(self, map_getter, parent=None):
        """map_getter: callable() → (rev_map, mod_hold_map)"""
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self._map_getter = map_getter
        self.setWindowTitle("Debug — Key Events")
        self.resize(660, 400)
        self.setStyleSheet("QWidget { background:#060610; color:#90a0b8; }")

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(4)

        hdr = QHBoxLayout()
        lbl = QLabel("evdev event log  ·  D to toggle")
        lbl.setFont(QFont("Monospace", 9, QFont.Bold))
        lbl.setStyleSheet("color:#4080c0;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        for text, slot in [("Dump maps", self._dump_maps), ("Clear", self._clear)]:
            btn = QPushButton(text)
            btn.setFont(QFont("Monospace", 8))
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._BTN_STYLE)
            btn.clicked.connect(slot)
            hdr.addWidget(btn)
        vbox.addLayout(hdr)

        self._te = QTextEdit()
        self._te.setReadOnly(True)
        self._te.setLineWrapMode(QTextEdit.NoWrap)
        self._te.setFont(QFont("Monospace", 9))
        self._te.setStyleSheet(
            "QTextEdit { background:#030308; border:1px solid #181830; }"
        )
        vbox.addWidget(self._te)

    def log(self, html: str):
        self._te.append(html)
        sb = self._te.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear(self):
        self._te.clear()

    def _dump_maps(self):
        if not HAS_EVDEV:
            return
        rev, mod = self._map_getter()
        self.log('<span style="color:#ffa040;">──── tap reverse map ────</span>')
        for code in sorted(rev):
            self.log(
                f'<span style="color:#c0b060;">&nbsp;&nbsp;'
                f'{_evdev_name(code):20s} {code:3d} → key[{rev[code]}]</span>'
            )
        self.log('<span style="color:#ffa040;">──── mod-hold map ────</span>')
        for code in sorted(mod):
            self.log(
                f'<span style="color:#c0b060;">&nbsp;&nbsp;'
                f'{_evdev_name(code):20s} {code:3d} → key[{mod[code]}]</span>'
            )
        self.log('<span style="color:#ffa040;">──────────────────────</span>')


# ── Main window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self, layers):
        super().__init__()
        self._layers  = layers
        self._current = 0

        # evdev_code → key_index for currently-pressed tap keys (yellow glow)
        self._pressed_evdev: dict = {}
        # evdev_code → key_index for currently-held modifier keys (red glow)
        self._mod_held_evdev: dict = {}
        # Auto-layer tracking: set of evdev_codes that triggered an auto layer-switch
        self._auto_layer_evdev: set = set()
        self._auto_layer_return: int = 0   # layer to return to when auto keys released
        # Layer-signal tracking: evdev_code → layer_to_return_to
        # First F2X press  = layer on  (switch to target layer, record return)
        # Second F2X press = layer off (switch back to recorded layer)
        self._layer_signal_on: dict = {}
        # Debug window (created lazily on first D press)
        self._debug_win = None
        # Tap reverse maps: evdev_code → key_index, one per layer
        self._rev_maps = []
        # Modifier-hold maps: unique modifier evdev_code → key_index, one per layer
        self._mod_hold_maps = []
        self._rebuild_rev_maps()

        self.setWindowTitle("Charybdis Layout Viewer")
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #0d0d1a; color: #b8c0d8; }
            QToolTip {
                background: #1a1a2e; color: #d0d8f0;
                border: 1px solid #4060a0; padding: 6px;
                font-size: 11px; line-height: 1.5;
            }
        """)

        root = QWidget()
        vbox = QVBoxLayout(root)
        vbox.setSpacing(10)
        vbox.setContentsMargins(16, 12, 16, 14)
        self.setCentralWidget(root)

        title = QLabel("⌨  Charybdis 3×5  —  Layout Viewer")
        title.setFont(QFont("Sans", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #7090c0; letter-spacing: 1px; margin-bottom: 2px;")
        vbox.addWidget(title)

        hint = QLabel("Hover a key for details  ·  1-9 or ← → to switch layers  ·  R to reload  ·  D to debug")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #383850; font-size: 10px;")
        vbox.addWidget(hint)

        self._kb_status = QLabel("○ key highlighting inactive")
        self._kb_status.setAlignment(Qt.AlignCenter)
        self._kb_status.setStyleSheet("color: #804040; font-size: 10px;")
        vbox.addWidget(self._kb_status)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self._tab_btns = []
        for i, (num, name, acc, _) in enumerate(LAYER_DEFS):
            btn = QPushButton(f" {num}: {name} ")
            btn.setCheckable(True)
            btn.setFont(QFont("Monospace", 9, QFont.Bold))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setToolTip(f"Layer {num}: {name}\n{LAYER_DEFS[i][3]}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #14142a; color: #60607a;
                    border: 1px solid #28284a; border-radius: 4px;
                    padding: 0 6px;
                }}
                QPushButton:hover {{
                    background: #1e1e38; color: #c0c8e0;
                    border-color: {acc};
                }}
                QPushButton:checked {{
                    background: {acc}20; color: #ffffff;
                    border: 2px solid {acc};
                }}
            """)
            # Hold to peek, release to return to Base
            btn.pressed.connect(lambda ix=i: self.switch_layer(ix))
            btn.released.connect(lambda: self.switch_layer(0))
            tab_row.addWidget(btn)
            self._tab_btns.append(btn)
        vbox.addLayout(tab_row)

        self._desc = QLabel()
        self._desc.setAlignment(Qt.AlignCenter)
        self._desc.setFont(QFont("Sans", 10))
        self._desc.setStyleSheet("color: #50506a; margin: 1px 0;")
        vbox.addWidget(self._desc)

        kb_row = QHBoxLayout()
        kb_row.setAlignment(Qt.AlignCenter)
        self._kb = KeyboardCanvas()
        kb_row.addWidget(self._kb)
        vbox.addLayout(kb_row)

        legend_row = QHBoxLayout()
        legend_row.setSpacing(0)
        for ktype, label in [
            ("normal", "Normal key"), ("mod",   "Homerow mod"),
            ("layer",  "Layer key"),  ("macro", "Macro"),
            ("special","BT / System"),("mouse", "Mouse btn"),
            ("rgb",    "RGB"),        ("trans", "Transparent"),
        ]:
            bg_hex, _ = KEY_COLORS[ktype]
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {QColor(bg_hex).lighter(170).name()};"
                f"font-size: 14px; margin: 0 3px 0 12px;"
            )
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #454560; font-size: 9px;")
            legend_row.addWidget(dot)
            legend_row.addWidget(lbl)
        legend_row.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.setFont(QFont("Sans", 9))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedHeight(22)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #2a1a1a; color: #805050;
                border: 1px solid #3a2020; border-radius: 4px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: #a03030; color: #ffffff;
                border-color: #c04040;
            }
        """)
        close_btn.clicked.connect(self.close)
        legend_row.addWidget(close_btn)
        vbox.addLayout(legend_row)

        self.switch_layer(0)
        self.adjustSize()
        self.setFixedSize(self.size())

        for i in range(len(LAYER_DEFS)):
            QShortcut(QKS(str(i + 1)), self).activated.connect(
                lambda ix=i: self.switch_layer(ix)
            )
        QShortcut(QKS(Qt.Key_Left),  self).activated.connect(
            lambda: self.switch_layer(max(0, self._current - 1))
        )
        QShortcut(QKS(Qt.Key_Right), self).activated.connect(
            lambda: self.switch_layer(min(len(LAYER_DEFS) - 1, self._current + 1))
        )
        QShortcut(QKS("r"), self).activated.connect(self.reload_keymap)
        QShortcut(QKS("R"), self).activated.connect(self.reload_keymap)
        QShortcut(QKS("d"), self).activated.connect(self._toggle_debug)
        QShortcut(QKS("D"), self).activated.connect(self._toggle_debug)

    # ── Reverse map helpers ───────────────────────────────────────────────

    def _rebuild_rev_maps(self):
        if HAS_EVDEV:
            self._rev_maps      = [build_reverse_map(bindings)  for _, bindings in self._layers]
            self._mod_hold_maps = [build_mod_hold_map(bindings) for _, bindings in self._layers]
        else:
            self._rev_maps      = []
            self._mod_hold_maps = []

    def _current_rev_map(self) -> dict:
        if self._rev_maps and self._current < len(self._rev_maps):
            return self._rev_maps[self._current]
        return {}

    def _base_rev_map(self) -> dict:
        return self._rev_maps[0] if self._rev_maps else {}

    def _current_mod_hold_map(self) -> dict:
        if self._mod_hold_maps and self._current < len(self._mod_hold_maps):
            return self._mod_hold_maps[self._current]
        return {}

    def _base_mod_hold_map(self) -> dict:
        return self._mod_hold_maps[0] if self._mod_hold_maps else {}

    def _find_layer_for_code(self, evdev_code: int) -> int | None:
        """Return the first non-base layer that contains evdev_code, if absent from base."""
        base_rev = self._rev_maps[0] if self._rev_maps else {}
        if evdev_code in base_rev:
            return None  # in base already, no need to auto-switch
        for layer_idx in range(1, len(self._rev_maps)):
            if evdev_code in self._rev_maps[layer_idx]:
                return layer_idx
        return None

    # ── Layer switching ───────────────────────────────────────────────────

    def switch_layer(self, idx: int):
        if not (0 <= idx < len(LAYER_DEFS)):
            return

        # Release currently highlighted keys before switching
        for key_idx in self._pressed_evdev.values():
            self._kb.set_key_pressed(key_idx, False)
        for key_idx in self._mod_held_evdev.values():
            self._kb.set_key_mod_held(key_idx, False)
        self._mod_held_evdev.clear()
        # Cancel auto-layer and signal tracking (manual switch takes over)
        self._auto_layer_evdev.clear()
        self._layer_signal_on.clear()

        self._current = idx
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == idx)

        if idx < len(self._layers):
            _, bindings = self._layers[idx]
            self._kb.load_layer(bindings)

        _, name, acc, desc = LAYER_DEFS[idx]
        self._desc.setText(
            f'<span style="color:{acc}; font-weight:bold;">Layer {idx}: {name}</span>'
            f'  <span style="color:#484860;">&mdash; {desc}</span>'
        )

        # Re-highlight any keys still physically held, now in new layer context
        new_pressed = {}
        rev = self._current_rev_map()
        base = self._base_rev_map()
        for evdev_code in self._pressed_evdev:
            _r = rev.get(evdev_code); key_idx = _r if _r is not None else base.get(evdev_code)
            if key_idx is not None:
                self._kb.set_key_pressed(key_idx, True)
                new_pressed[evdev_code] = key_idx
        self._pressed_evdev = new_pressed

    # ── Key event from evdev thread ───────────────────────────────────────

    def on_key_event(self, evdev_code: int, pressed: bool):
        self._debug_event(evdev_code, pressed)   # log before state changes
        if pressed:
            # ── Layer-signal keys (F20-F24 from ZMK signaled layer macros) ──
            if HAS_EVDEV and evdev_code in LAYER_SIGNAL_CODES:
                target = LAYER_SIGNAL_CODES[evdev_code]
                if evdev_code not in self._layer_signal_on:
                    # First press → switch to the signaled layer
                    self._layer_signal_on[evdev_code] = self._current
                    if self._current != target:
                        _saved = dict(self._layer_signal_on)
                        self.switch_layer(target)
                        self._layer_signal_on = _saved
                else:
                    # Second press → return to previous layer
                    ret = self._layer_signal_on.pop(evdev_code)
                    self.switch_layer(ret)
                return   # consumed — don't fall through to tap/mod logic

            # Check tap key codes first (regular keys + &hm tap + &lt/lts tap)
            rev  = self._current_rev_map()
            base = self._base_rev_map()
            _r = rev.get(evdev_code); key_idx = _r if _r is not None else base.get(evdev_code)
            if key_idx is not None:
                self._pressed_evdev[evdev_code] = key_idx
                self._kb.set_key_pressed(key_idx, True)
            else:
                # Check if ZMK sent a modifier from a unique &hm hold
                mod_map  = self._current_mod_hold_map()
                base_mod = self._base_mod_hold_map()
                _m = mod_map.get(evdev_code); mod_idx = _m if _m is not None else base_mod.get(evdev_code)
                if mod_idx is not None:
                    self._mod_held_evdev[evdev_code] = mod_idx
                    self._kb.set_key_mod_held(mod_idx, True)
                else:
                    # Key from a non-base layer — user must be holding an &lt key.
                    # Auto-switch the visualizer to that layer.
                    layer_idx = self._find_layer_for_code(evdev_code)
                    if layer_idx is not None:
                        if not self._auto_layer_evdev:          # first auto key
                            self._auto_layer_return = self._current
                        self._auto_layer_evdev.add(evdev_code)
                        if self._current != layer_idx:
                            # Save auto state — switch_layer clears it
                            _saved_auto   = set(self._auto_layer_evdev)
                            _saved_return = self._auto_layer_return
                            self.switch_layer(layer_idx)
                            self._auto_layer_evdev  = _saved_auto
                            self._auto_layer_return = _saved_return
                        _r2 = self._current_rev_map().get(evdev_code)
                        if _r2 is not None:
                            self._pressed_evdev[evdev_code] = _r2
                            self._kb.set_key_pressed(_r2, True)
        else:
            key_idx = self._pressed_evdev.pop(evdev_code, None)
            if key_idx is not None:
                if key_idx not in self._pressed_evdev.values():
                    self._kb.set_key_pressed(key_idx, False)
            mod_idx = self._mod_held_evdev.pop(evdev_code, None)
            if mod_idx is not None:
                if mod_idx not in self._mod_held_evdev.values():
                    self._kb.set_key_mod_held(mod_idx, False)
            # If this was an auto-layer key, return to the previous layer when all released
            if evdev_code in self._auto_layer_evdev:
                self._auto_layer_evdev.discard(evdev_code)
                if not self._auto_layer_evdev:
                    self.switch_layer(self._auto_layer_return)

    # ── Debug ─────────────────────────────────────────────────────────────

    def _toggle_debug(self):
        if not HAS_EVDEV:
            return
        if self._debug_win is None:
            self._debug_win = DebugWindow(
                map_getter=lambda: (self._current_rev_map(), self._current_mod_hold_map())
            )
        if self._debug_win.isVisible():
            self._debug_win.hide()
        else:
            self._debug_win.show()
            self._debug_win.raise_()

    def _debug_event(self, evdev_code: int, pressed: bool):
        if self._debug_win is None or not self._debug_win.isVisible():
            return
        ts   = time.strftime("%H:%M:%S")
        arr  = '<span style="color:#60e060;">▼</span>' if pressed else '<span style="color:#406040;">▲</span>'
        name = _evdev_name(evdev_code)
        code_html = f'<span style="color:#a0a8c0;">{name} ({evdev_code})</span>'

        if pressed:
            if HAS_EVDEV and evdev_code in LAYER_SIGNAL_CODES:
                target = LAYER_SIGNAL_CODES[evdev_code]
                lname  = LAYER_DEFS[target][1] if target < len(LAYER_DEFS) else f"L{target}"
                if evdev_code not in self._layer_signal_on:
                    action = (f'<span style="color:#00e0c0;">⟵ layer signal ON  '
                              f'→ layer {target} ({lname})</span>')
                else:
                    ret = self._layer_signal_on.get(evdev_code, 0)
                    ret_name = LAYER_DEFS[ret][1] if ret < len(LAYER_DEFS) else f"L{ret}"
                    action = (f'<span style="color:#00a090;">⟶ layer signal OFF '
                              f'→ return to layer {ret} ({ret_name})</span>')
                self._debug_win.log(
                    f'<span style="color:#505060;">{ts}</span> {arr} {code_html} &nbsp; {action}'
                )
                return

            rev  = self._current_rev_map()
            base = self._base_rev_map()
            _r = rev.get(evdev_code); key_idx = _r if _r is not None else base.get(evdev_code)
            if key_idx is not None:
                bindings = self._layers[self._current][1] if self._current < len(self._layers) else []
                label = bindings[key_idx].strip() if key_idx < len(bindings) else "?"
                action = f'<span style="color:#f0e040;">→ key[{key_idx}] {label}  tap/yellow</span>'
            else:
                mod_map  = self._current_mod_hold_map()
                base_mod = self._base_mod_hold_map()
                _m = mod_map.get(evdev_code); mod_idx = _m if _m is not None else base_mod.get(evdev_code)
                if mod_idx is not None:
                    bindings = self._layers[self._current][1] if self._current < len(self._layers) else []
                    label = bindings[mod_idx].strip() if mod_idx < len(bindings) else "?"
                    action = f'<span style="color:#ff7050;">→ key[{mod_idx}] {label}  mod-hold/red</span>'
                else:
                    layer_idx = self._find_layer_for_code(evdev_code)
                    if layer_idx is not None:
                        lname = LAYER_DEFS[layer_idx][1] if layer_idx < len(LAYER_DEFS) else f"L{layer_idx}"
                        action = f'<span style="color:#40a0ff;">⟳ auto-switch → layer {layer_idx} ({lname})</span>'
                    else:
                        action = '<span style="color:#604040;">✗ not in any layer map</span>'
        else:
            if evdev_code in self._pressed_evdev:
                ki = self._pressed_evdev[evdev_code]
                action = f'<span style="color:#808050;">→ key[{ki}]  released tap</span>'
            elif evdev_code in self._mod_held_evdev:
                mi = self._mod_held_evdev[evdev_code]
                action = f'<span style="color:#806040;">→ key[{mi}]  released mod-hold</span>'
            else:
                return   # untracked release — BLE dropout ghost, silently ignore

        self._debug_win.log(
            f'<span style="color:#505060;">{ts}</span> {arr} {code_html} &nbsp; {action}'
        )

    # ── Device lost ───────────────────────────────────────────────────────

    def on_device_lost(self):
        """Called when the Charybdis dongle disconnects.  Release all visual
        key state so no keys stay lit while the keyboard is gone."""
        self._kb.release_all()
        self._pressed_evdev.clear()
        self._mod_held_evdev.clear()
        self._auto_layer_evdev.clear()
        self._layer_signal_on.clear()
        if self._debug_win is not None and self._debug_win.isVisible():
            ts = time.strftime("%H:%M:%S")
            self._debug_win.log(
                f'<span style="color:#505060;">{ts}</span>'
                f' <span style="color:#c04040;">⚡ dongle disconnected — all keys released</span>'
            )

    # ── Reload ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        QApplication.quit()
        event.accept()

    def reload_keymap(self):
        try:
            self._layers = parse_keymap(KEYMAP_FILE)
            self._rebuild_rev_maps()
            self._kb.release_all()
            self._pressed_evdev.clear()
            self._mod_held_evdev.clear()
            self._auto_layer_evdev.clear()
            self._layer_signal_on.clear()
            self.switch_layer(self._current)
            self.setWindowTitle("Charybdis Layout Viewer  ✓ reloaded")
        except Exception as e:
            self.setWindowTitle(f"Charybdis Layout Viewer  ✗ {e}")


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Charybdis Layout Viewer")

    try:
        layers = parse_keymap(KEYMAP_FILE)
        print(f"[OK] Loaded {len(layers)} layers from:")
        print(f"     {KEYMAP_FILE}")
        for name, bindings in layers:
            print(f"     · {name:8s} — {len(bindings)} bindings")
    except Exception as e:
        print(f"[ERR] Could not parse keymap: {e}")
        layers = [(name, ["&trans"] * 35) for _, name, _, _ in LAYER_DEFS]

    win = MainWindow(layers)

    # Auto-reload on keymap file save
    watcher = QFileSystemWatcher([KEYMAP_FILE])

    def _on_change(path):
        if path not in watcher.files():
            watcher.addPath(KEYMAP_FILE)
        win.reload_keymap()

    watcher.fileChanged.connect(_on_change)

    # Start evdev key listener
    if HAS_EVDEV:
        listener = KeyListener()
        listener.key_event.connect(win.on_key_event)
        listener.device_lost.connect(win.on_device_lost)
        listener.status_signal.connect(
            lambda msg, col: (
                win._kb_status.setText(msg),
                win._kb_status.setStyleSheet(f"color: {col}; font-size: 10px;"),
            )
        )
        listener.start()
        app.aboutToQuit.connect(listener.stop)
    else:
        print("[WARN] python3-evdev not found — key highlighting disabled")
        print("       Fix: sudo apt install python3-evdev")

    win.show()
    win._toggle_debug()   # open debug window at startup
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
