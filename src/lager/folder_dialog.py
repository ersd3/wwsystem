"""Ordner-Auswahlfenster als eigenes kleines Programm.

Aufruf:  python -m lager.folder_dialog <Titel> [Startordner]

Schreibt den gewählten Ordner auf die Standardausgabe (UTF-8), bei Abbruch nichts.
Statuscode 2, wenn sich kein Fenster öffnen lässt (tkinter fehlt, kein Bildschirm).
Gestartet wird es von dialogs.pick_folder; so läuft das Fenster in einem eigenen Prozess.
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str]) -> int:
    title = argv[1] if len(argv) > 1 else "Ordner auswählen"
    initial = argv[2] if len(argv) > 2 else ""
    try:
        import tkinter
        from tkinter import filedialog

        window = tkinter.Tk()
    except Exception as e:  # ImportError oder TclError: kein tkinter, kein Bildschirm
        sys.stderr.write(str(e))
        return 2
    try:
        window.withdraw()
        # Das Auswahlfenster gehört zu diesem unsichtbaren Fenster. Liegt es zuoberst,
        # erscheint auch die Auswahl vor dem Browser und nicht dahinter.
        window.attributes("-topmost", True)
        window.update()
        options = {"parent": window, "title": title, "mustexist": True}
        if initial and os.path.isdir(initial):
            options["initialdir"] = initial
        chosen = filedialog.askdirectory(**options)
    finally:
        window.destroy()
    if chosen:
        sys.stdout.buffer.write(os.path.normpath(chosen).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
