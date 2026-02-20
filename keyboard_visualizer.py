#!/usr/bin/env python3
"""
Charybdis ZMK Keyboard Layout Visualizer
=========================================
Parses config/charybdis.keymap and displays all 9 layers interactively.

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

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QSizePolicy, QShortcut,
)
from PyQt5.QtCore import Qt, QRect, QFileSystemWatcher, QRectF
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
# (background_hex, foreground_hex)
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
    # Brackets / punctuation
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
    # Numbers (two naming conventions ZMK uses)
    "NUMBER_0": "0", "NUMBER_1": "1", "NUMBER_2": "2",
    "NUMBER_3": "3", "NUMBER_4": "4", "NUMBER_5": "5",
    "NUMBER_6": "6", "NUMBER_7": "7", "NUMBER_8": "8", "NUMBER_9": "9",
    "N0": "0", "N1": "1", "N2": "2", "N3": "3", "N4": "4",
    "N5": "5", "N6": "6", "N7": "7", "N8": "8", "N9": "9",
    # Media
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
    # Title-case long names, keep short ones as-is
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
            f"Homerow mod\n"
            f"  Tap  →  {fmt_key(key)}\n"
            f"  Hold →  {mod}"
        )

    if b.startswith("&lt "):
        parts = b[4:].split()
        ln, key = int(parts[0]), parts[1]
        lname = LAYER_DEFS[ln][1] if ln < len(LAYER_DEFS) else f"L{ln}"
        return fmt_key(key), f"[{layer_short(ln)}]", "layer", (
            f"Layer-tap\n"
            f"  Tap  →  {fmt_key(key)}\n"
            f"  Hold →  Layer {ln}: {lname}"
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

    # Fallback
    label = b.replace("&", "").replace("_", " ")[:9]
    return label, "", "normal", b


# ── Keymap parser ──────────────────────────────────────────────────────────

def extract_bindings(text: str):
    """Split a <...> block into individual ZMK binding strings."""
    text = re.sub(r'//.*', '', text)          # strip line comments
    result = []
    for part in text.split('&'):
        p = ' '.join(part.split())            # normalise whitespace
        if p:
            result.append('&' + p)
    return result


def parse_keymap(filepath: str):
    """
    Parse the ZMK keymap file.
    Returns [(layer_name, [binding_str, ...]), ...] in file order.
    """
    with open(filepath, 'r') as f:
        content = f.read()

    layers = []
    # Match: WordName { ... bindings = <...> ...
    # [^{]* ensures we don't accidentally cross into a nested block
    pattern = re.compile(
        r'(\w+)\s*\{[^{]*?bindings\s*=\s*<([^>]*)>',
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        name = m.group(1)
        bindings = extract_bindings(m.group(2))
        # Real keyboard layers have 35 keys; macro/behavior blocks have 1-2
        if len(bindings) >= 30:
            layers.append((name, bindings))
    return layers


# ── Key widget ─────────────────────────────────────────────────────────────

class Key(QWidget):
    """One physical key, drawn with QPainter for full control."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main  = ""
        self.sub   = ""
        self.ktype = "normal"
        self._hovered = False
        self.setMouseTracking(True)

    def set_binding(self, main, sub, ktype, tip):
        self.main, self.sub, self.ktype = main, sub, ktype
        self.setToolTip(tip)
        self.update()

    def enterEvent(self, _): self._hovered = True;  self.update()
    def leaveEvent(self, _): self._hovered = False; self.update()

    def paintEvent(self, _):
        bg_hex, fg_hex = KEY_COLORS.get(self.ktype, KEY_COLORS["normal"])
        bg = QColor(bg_hex)
        fg = QColor(fg_hex)
        if self._hovered:
            bg = bg.lighter(150)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)

        # Drop shadow
        shadow_path = QPainterPath()
        sr = r.adjusted(1, 2, 1, 2)
        shadow_path.addRoundedRect(QRectF(sr.x(), sr.y(), sr.width(), sr.height()), 7, 7)
        p.fillPath(shadow_path, QColor(0, 0, 0, 70))

        # Key face
        face = QPainterPath()
        face.addRoundedRect(QRectF(r.x(), r.y(), r.width(), r.height()), 7, 7)
        p.fillPath(face, bg)

        # Subtle top-gloss
        gloss = QLinearGradient(0, r.top(), 0, r.top() + r.height() * 0.45)
        gloss.setColorAt(0, QColor(255, 255, 255, 28))
        gloss.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(face, QBrush(gloss))

        # Border
        border = QColor(255, 255, 255, 55) if self._hovered else QColor(0, 0, 0, 90)
        p.setPen(QPen(border, 1.2))
        p.drawPath(face)

        # Text
        p.setPen(fg)
        if self.sub:
            font = QFont("Monospace", 10, QFont.Bold)
            p.setFont(font)
            top_rect = QRect(r.x(), r.y() + 4, r.width(), r.height() - 18)
            p.drawText(top_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.main)

            font2 = QFont("Monospace", 7)
            p.setFont(font2)
            p.setPen(fg.darker(150))
            bot_rect = QRect(r.x(), r.bottom() - 16, r.width(), 16)
            p.drawText(bot_rect, Qt.AlignHCenter | Qt.AlignBottom, self.sub)
        else:
            font = QFont("Monospace", 10, QFont.Bold)
            p.setFont(font)
            p.drawText(r, Qt.AlignCenter, self.main)

        p.end()


# ── Keyboard canvas ────────────────────────────────────────────────────────
# Physical Charybdis 3×5 layout constants
KW, KH, KG = 64, 60, 5   # key width / height / gap
HG = 30                    # gap between the two halves

# Columnar stagger in pixels (positive = key sits lower)
# Left hand: col 0 = pinky outer … col 4 = inner index
L_STAGGER = [14, 4, 0, 6, 12]
# Right hand: col 0 = inner index … col 4 = pinky outer  (mirrored)
R_STAGGER  = [12, 6, 0, 4, 14]


class KeyboardCanvas(QWidget):
    """Renders the full split keyboard with columnar stagger."""

    def __init__(self, parent=None):
        super().__init__(parent)

        max_stag = max(max(L_STAGGER), max(R_STAGGER))
        half_w   = 5 * (KW + KG) - KG
        total_w  = 2 * half_w + HG
        rows_h   = 3 * (KH + KG) - KG + max_stag
        total_h  = rows_h + KG * 3 + KH          # + thumb row

        self.setFixedSize(total_w + 20, total_h + 20)

        self._keys = [Key(parent=self) for _ in range(35)]
        for k in self._keys:
            k.setFixedSize(KW, KH)

        # ── Main grid (indices 0-29) ──────────────────────────────────────
        for row in range(3):
            for col in range(10):
                idx  = row * 10 + col
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

        # ── Thumb cluster ─────────────────────────────────────────────────
        thumb_y = 10 + max_stag + 3 * (KH + KG) + KG * 2

        # Left thumbs: keys 30 31 32 — ESC / TAB / SPACE
        lx = 10 + 2 * (KW + KG)
        for i, idx in enumerate([30, 31, 32]):
            self._keys[idx].move(lx + i * (KW + KG), thumb_y)

        # Right thumbs: keys 33 34 — BACKSPACE / ENTER
        # (right side only has 2; trackball occupies the 3rd slot)
        rx = 10 + half_w + HG
        for i, idx in enumerate([33, 34]):
            self._keys[idx].move(rx + i * (KW + KG), thumb_y)

        # Trackball placeholder position (for painting)
        self._trackball_x = rx + 2 * (KW + KG) + KG + KW // 2
        self._trackball_y = thumb_y + KH // 2

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d0d1a"))

        # Draw a subtle trackball circle
        p.setPen(QPen(QColor("#333350"), 2))
        p.setBrush(QColor("#1a1a30"))
        r = KH // 2 - 4
        p.drawEllipse(self._trackball_x - r, self._trackball_y - r, r * 2, r * 2)
        # Inner dot
        p.setBrush(QColor("#2a2a50"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(self._trackball_x - r // 3, self._trackball_y - r // 3,
                      r * 2 // 3, r * 2 // 3)

        p.end()

    def load_layer(self, bindings):
        for i, raw in enumerate(bindings[:35]):
            self._keys[i].set_binding(*parse_binding(raw))


# ── Main window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self, layers):
        super().__init__()
        self._layers  = layers
        self._current = 0

        self.setWindowTitle("Charybdis Layout Viewer")
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #0d0d1a; color: #b8c0d8; }
            QToolTip {
                background: #1a1a2e; color: #d0d8f0;
                border: 1px solid #4060a0; padding: 6px;
                font-size: 11px; line-height: 1.5;
            }
        """)

        root  = QWidget()
        vbox  = QVBoxLayout(root)
        vbox.setSpacing(10)
        vbox.setContentsMargins(16, 12, 16, 14)
        self.setCentralWidget(root)

        # ── Title ─────────────────────────────────────────────────────────
        title = QLabel("⌨  Charybdis 3×5  —  Layout Viewer")
        title.setFont(QFont("Sans", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #7090c0; letter-spacing: 1px; margin-bottom: 2px;")
        vbox.addWidget(title)

        hint = QLabel("Hover a key for details  ·  Keys 1-9 or ← → to switch layers  ·  R to reload")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #383850; font-size: 10px;")
        vbox.addWidget(hint)

        # ── Layer tab buttons ─────────────────────────────────────────────
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
            btn.clicked.connect(lambda _, ix=i: self.switch_layer(ix))
            tab_row.addWidget(btn)
            self._tab_btns.append(btn)
        vbox.addLayout(tab_row)

        # ── Layer description ─────────────────────────────────────────────
        self._desc = QLabel()
        self._desc.setAlignment(Qt.AlignCenter)
        self._desc.setFont(QFont("Sans", 10))
        self._desc.setStyleSheet("color: #50506a; margin: 1px 0;")
        vbox.addWidget(self._desc)

        # ── Keyboard ──────────────────────────────────────────────────────
        kb_row = QHBoxLayout()
        kb_row.setAlignment(Qt.AlignCenter)
        self._kb = KeyboardCanvas()
        kb_row.addWidget(self._kb)
        vbox.addLayout(kb_row)

        # ── Legend ────────────────────────────────────────────────────────
        legend_row = QHBoxLayout()
        legend_row.setSpacing(0)
        for ktype, label in [
            ("normal",  "Normal key"),
            ("mod",     "Homerow mod"),
            ("layer",   "Layer key"),
            ("macro",   "Macro"),
            ("special", "BT / System"),
            ("mouse",   "Mouse btn"),
            ("rgb",     "RGB"),
            ("trans",   "Transparent"),
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
        vbox.addLayout(legend_row)

        self.switch_layer(0)
        self.adjustSize()
        self.setFixedSize(self.size())   # prevent accidental resize

        # ── Global shortcuts (work regardless of which widget has focus) ──
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

    # ── Layer switching ───────────────────────────────────────────────────

    def switch_layer(self, idx: int):
        if not (0 <= idx < len(LAYER_DEFS)):
            return
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

    def reload_keymap(self):
        try:
            self._layers = parse_keymap(KEYMAP_FILE)
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

    # Auto-reload when you save the keymap file
    watcher = QFileSystemWatcher([KEYMAP_FILE])

    def _on_change(path):
        # Some editors replace-by-delete, so re-watch if needed
        if path not in watcher.files():
            watcher.addPath(KEYMAP_FILE)
        win.reload_keymap()

    watcher.fileChanged.connect(_on_change)

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
