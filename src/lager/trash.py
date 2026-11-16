"""Papierkorb des Lagers: Gelöschtes wird verschoben, nicht vernichtet.

Bauteile und Dateien, die über das Programm gelöscht werden, landen unter
<lager_root>/_papierkorb/<Zeitpunkt>/<derselbe Pfad wie im Lager>. Ordner mit `_`
am Anfang überspringt das Lager, deshalb taucht dort nichts mehr in der Suche auf.
Wiederherstellen und endgültiges Löschen gehen im Explorer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

TRASH_DIR = "_papierkorb"
README_NAME = "LIESMICH.txt"
README_TEXT = """Papierkorb des Lagers

Hier liegt, was im Lager-Programm gelöscht wurde. Jeder Ordner trägt den Zeitpunkt
des Löschens (UTC) und enthält den Pfad, an dem das Bauteil oder die Datei lag.

Wiederherstellen: den Ordner oder die Datei zurück an ihren Platz im Lager schieben
und im Programm "Ordner neu einlesen" wählen.
Endgültig löschen: hier im Explorer löschen.
"""


def trash_dir(root: Path) -> Path:
    return root / TRASH_DIR


def move_to_trash(root: Path, source: Path) -> Path:
    """Verschiebt eine Datei oder einen Ordner aus dem Lager in den Papierkorb.

    Gibt den neuen Ort zurück. Liegt `source` nicht im Lager, gibt es einen ValueError.
    Der Papierkorb liegt im Lager selbst, deshalb reicht ein Umbenennen: Entweder der
    ganze Ordner zieht um oder (bei einer gesperrten Datei) gar nichts, dann mit OSError.
    """
    try:
        rel = source.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"{source} liegt nicht im Lager-Ordner.") from None
    if not rel.parts or rel.parts[0] == TRASH_DIR:
        raise ValueError(f"{source} lässt sich nicht in den Papierkorb verschieben.")

    base = trash_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    readme = base / README_NAME
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = base / stamp / rel
    number = 2
    while target.exists():  # zweimal dasselbe in einer Sekunde gelöscht
        target = base / f"{stamp}-{number}" / rel
        number += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return target
