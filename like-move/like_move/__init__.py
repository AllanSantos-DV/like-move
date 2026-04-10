"""like-move — Intelligent Mouse Jiggler for Windows."""

import os
import sys

def _read_version() -> str:
    """Read version from VERSION file."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    version_file = os.path.join(base, "VERSION")
    try:
        with open(version_file, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"

__version__ = _read_version()
