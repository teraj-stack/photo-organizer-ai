#!/usr/bin/env python3
"""Punkt startowy dla spakowanej aplikacji macOS (.app / .dmg) Photo Organizer AI."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def get_bundle_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def find_port(preferred: int = 8765) -> int:
    for port in (preferred, preferred + 1, preferred + 2, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return 8765


def main() -> None:
    bundle_dir = get_bundle_dir()
    if str(bundle_dir) not in sys.path:
        sys.path.insert(0, str(bundle_dir))

    # Zapis logu Undo w ~/Library/Application Support/PhotoOrganizerAI (zamiast wewnątrz .app)
    app_support = Path.home() / "Library" / "Application Support" / "PhotoOrganizerAI"
    app_support.mkdir(parents=True, exist_ok=True)

    import app as backend

    backend.STATIC_DIR = bundle_dir / "static"
    backend.UNDO_LOG_PATH = app_support / "undo_log.json"

    port = find_port(8765)
    url = f"http://127.0.0.1:{port}"

    def _open_browser() -> None:
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(backend.app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
