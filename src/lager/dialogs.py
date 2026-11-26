"""Fenster des Betriebssystems, für den PC, auf dem das Programm läuft.

Ein Browser darf einer Webseite keinen vollständigen Ordnerpfad verraten und keinen
Ordner im Explorer öffnen. Der Server läuft aber auf demselben PC und kann beides selbst:
das Ordner-Auswahlfenster (`pick_folder`) und einen Ordner im Explorer (`reveal`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

# So lange darf das Fenster offen bleiben, bevor es wieder geschlossen wird.
TIMEOUT_SECONDS = 600
_open = threading.Lock()


class DialogUnavailable(RuntimeError):
    """Das Auswahlfenster lässt sich nicht öffnen (Meldung auf Deutsch, für die Ausgabe)."""


def _run_dialog(title: str, initial: str) -> subprocess.CompletedProcess:
    """Startet das Auswahlfenster als eigenen Prozess und wartet auf sein Ende.

    Ein eigener Prozess, weil Tk nicht aus wechselnden Threads des Servers laufen mag.
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # unter Windows kein Konsolenfenster
    return subprocess.run(
        [sys.executable, "-m", "lager.folder_dialog", title, initial],
        capture_output=True,
        timeout=TIMEOUT_SECONDS,
        creationflags=flags,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def pick_folder(initial: Path | None = None, title: str = "Lager-Ordner auswählen") -> Path | None:
    """Lässt am PC einen Ordner auswählen. `None` heißt: abgebrochen.

    Kann kein Fenster geöffnet werden, gibt es eine DialogUnavailable mit dem Grund.
    """
    if not _open.acquire(blocking=False):
        raise DialogUnavailable(
            "Das Auswahlfenster ist schon offen. Es liegt vielleicht hinter dem Browser."
        )
    try:
        done = _run_dialog(title, str(initial or ""))
    except subprocess.TimeoutExpired:
        raise DialogUnavailable("Im Auswahlfenster wurde nichts gewählt; es wurde geschlossen.") from None
    except OSError as e:
        raise DialogUnavailable(f"Das Auswahlfenster lässt sich nicht starten ({e}).") from e
    finally:
        _open.release()
    if done.returncode != 0:
        raise DialogUnavailable(
            "Auf diesem Rechner lässt sich kein Auswahlfenster öffnen. Bitte den Pfad eintippen."
        )
    chosen = done.stdout.decode("utf-8", errors="replace").strip()
    return Path(chosen) if chosen else None


def reveal(folder: Path) -> None:
    """Öffnet einen Ordner im Dateimanager dieses PCs (unter Windows im Explorer).

    Geht das nicht (kein Ordner, kein Bildschirm, kein Dateimanager), gibt es eine
    DialogUnavailable mit dem Grund.
    """
    if not folder.is_dir():
        raise DialogUnavailable(f"Den Ordner gibt es nicht: {folder}")
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except OSError as e:
        raise DialogUnavailable(
            f"Der Ordner lässt sich auf diesem Rechner nicht öffnen ({e}). Er liegt hier: {folder}"
        ) from e
