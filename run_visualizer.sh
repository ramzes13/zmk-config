#!/usr/bin/env bash
# ── Charybdis Layout Viewer — launcher ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure DISPLAY is set (needed for Qt on X11)
export DISPLAY="${DISPLAY:-:0}"

# Install PyQt5 if missing (apt only, pip conflicts with system Python)
if ! python3 -c "import PyQt5" 2>/dev/null; then
    echo "PyQt5 not found — installing via apt..."
    sudo apt install -y python3-pyqt5
    # Verify it worked
    if ! python3 -c "import PyQt5" 2>/dev/null; then
        echo "ERROR: PyQt5 still not importable after install."
        echo "Try: sudo apt install python3-pyqt5"
        exit 1
    fi
fi

exec python3 "$SCRIPT_DIR/keyboard_visualizer.py" "$@"
