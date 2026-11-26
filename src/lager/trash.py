"""Papierkorb des Lagers: Gelöschtes wird verschoben, nicht vernichtet.

Bauteile und Dateien, die über das Programm gelöscht werden, landen unter
<lager_root>/_papierkorb/<Zeitpunkt>/<derselbe Pfad wie im Lager>. Jedes Löschen bekommt
einen eigenen Zeit-Ordner mit genau einem Eintrag: einem Bauteil-Ordner oder einer Datei.
Ordner mit `_` am Anfang überspringt das Lager, deshalb taucht dort nichts mehr in der
Suche auf.

`entries` listet den Inhalt, `restore` holt einen Eintrag an seinen alten Platz zurück.
Endgültig gelöscht wird nur im Explorer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import categories as catmod

TRASH_DIR = "_papierkorb"
README_NAME = "LIESMICH.txt"
README_TEXT = """Papierkorb des Lagers

Hier liegt, was im Lager-Programm gelöscht wurde. Jeder Ordner trägt den Zeitpunkt
des Löschens (UTC) und enthält den Pfad, an dem das Bauteil oder die Datei lag.

Wiederherstellen: im Lager-Programm auf der Seite "Papierkorb" (Link unten auf jeder
Seite) oder mit `lager trash restore`. Von Hand geht es auch: den Ordner oder die Datei
zurück an ihren Platz im Lager schieben und im Programm "Ordner neu einlesen" wählen.
Endgültig löschen: hier im Explorer löschen.
"""
# Name eines Zeit-Ordners, z. B. 20261126T205502Z, bei zwei Löschungen in derselben
# Sekunde mit Nummer: 20261126T205502Z-2.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_STAMP_RE = re.compile(r"^(?P<stamp>\d{8}T\d{6}Z)(?:-(?P<number>\d+))?$")
# Dateien, die Windows selbst in Ordnern ablegt; sie zählen nicht als Inhalt.
_IGNORED_FILES = {"thumbs.db", "desktop.ini"}


@dataclass(frozen=True)
class TrashEntry:
    id: str  # Name des Zeit-Ordners, z. B. "20261126T205502Z"
    kind: str  # "part" (ganzer Bauteil-Ordner) oder "file" (eine Datei)
    name: str  # Bezeichnung des Bauteils bzw. Name der Datei
    part: str  # Bauteil, zu dem der Eintrag gehört(e)
    path: str  # alter Platz im Lager, z. B. "microcontroller/Shields/Motor Shield"
    deleted_at: str  # Zeitpunkt des Löschens, ISO 8601 in UTC
    location: Path  # wo der Eintrag jetzt liegt

    def as_dict(self, root: Path) -> dict:
        """Für CLI (`--json`) und API: Felder auf Englisch, Pfade relativ zum Lager."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "part": self.part,
            "path": self.path,
            "deleted_at": self.deleted_at,
            "location": self.location.relative_to(root).as_posix(),
            "problem": restore_problem(root, self),
        }


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

    # Jedes Löschen bekommt einen eigenen Zeit-Ordner, auch zwei in derselben Sekunde.
    # mkdir ohne exist_ok belegt den Ordner in einem Schritt; zwei gleichzeitige
    # Anfragen an den Server bekommen so nie denselben.
    stamp = datetime.now(timezone.utc).strftime(STAMP_FORMAT)
    number = 1
    while True:
        folder = base / (stamp if number == 1 else f"{stamp}-{number}")
        try:
            folder.mkdir()
            break
        except FileExistsError:
            number += 1
    target = folder / rel
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError:
        _prune(target.parent, folder)  # keine leeren Ordner zurücklassen
        raise
    return target


# ------------------------------------------------------------ Inhalt ansehen


def _item(stamp_dir: Path) -> Path | None:
    """Der eine Eintrag in einem Zeit-Ordner: ein Bauteil-Ordner oder eine Datei.

    Der Weg dorthin besteht aus Ordnern mit genau einem Inhalt (dem alten Pfad im Lager).
    Ist ein Ordner leer oder enthält er mehreres (von Hand verändert), ist das Ergebnis None.
    """
    current = stamp_dir
    while current.is_dir():
        if (current / "part.yaml").is_file():
            return current
        children = [c for c in current.iterdir() if c.name.lower() not in _IGNORED_FILES]
        if len(children) != 1:
            return None
        current = children[0]
    return current if current.is_file() else None


def _deleted_at(stamp: str) -> str:
    moment = datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _owner_dir(root: Path, rel_parts: tuple[str, ...]) -> Path | None:
    """Der Bauteil-Ordner, in dem eine Datei mit diesem alten Pfad lag, falls es ihn noch gibt."""
    for depth in range(len(rel_parts) - 1, 1, -1):  # mindestens Kategorie und Bauteil
        candidate = root.joinpath(*rel_parts[:depth])
        if (candidate / "part.yaml").is_file():
            return candidate
    return None


def _owner_name(root: Path, rel_parts: tuple[str, ...]) -> str:
    """Bezeichnung des Bauteils, zu dem eine gelöschte Datei gehörte (für die Anzeige)."""
    owner = _owner_dir(root, rel_parts)
    if owner is not None:
        return owner.name
    from .files import KIND_FOLDERS  # hier, weil files.py dieses Modul importiert

    # Gibt es das Bauteil nicht mehr: Dateien einer Art liegen eine Ebene tiefer (3d/, …).
    if len(rel_parts) >= 4 and rel_parts[-2] in KIND_FOLDERS.values():
        return rel_parts[-3]
    return rel_parts[-2] if len(rel_parts) >= 2 else ""


def entries(root: Path) -> list[TrashEntry]:
    """Alles im Papierkorb, das Neueste zuerst."""
    base = trash_dir(root)
    if not base.is_dir():
        return []
    found: list[tuple[tuple[str, int], TrashEntry]] = []
    for stamp_dir in base.iterdir():
        match = _STAMP_RE.match(stamp_dir.name)
        if match is None or not stamp_dir.is_dir():
            continue
        item = _item(stamp_dir)
        if item is None:
            continue
        rel_parts = item.relative_to(stamp_dir).parts
        kind = "part" if item.is_dir() else "file"
        entry = TrashEntry(
            id=stamp_dir.name,
            kind=kind,
            name=item.name,
            part=item.name if kind == "part" else _owner_name(root, rel_parts),
            path="/".join(rel_parts),
            deleted_at=_deleted_at(match["stamp"]),
            location=item,
        )
        found.append(((match["stamp"], int(match["number"] or 1)), entry))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _key, entry in found]


def find_entry(root: Path, entry_id: str) -> TrashEntry:
    """Ein Eintrag über seine ID (den Namen des Zeit-Ordners). Unbekannt: ValueError."""
    if not _STAMP_RE.match(entry_id or ""):
        raise ValueError(f"Ungültiger Eintrag im Papierkorb: {entry_id!r}")
    for entry in entries(root):
        if entry.id == entry_id:
            return entry
    raise ValueError(f"Im Papierkorb gibt es keinen Eintrag {entry_id}.")


# ------------------------------------------------------------ Zurückholen


def restore_problem(root: Path, entry: TrashEntry) -> str:
    """Warum sich ein Eintrag nicht zurückholen lässt, auf Deutsch; leer, wenn es geht."""
    from . import parts as partmod  # hier, weil parts.py dieses Modul importiert

    rel_parts = tuple(entry.path.split("/"))
    if entry.kind == "part":
        if len(rel_parts) < 2:
            return "Unklar, wohin der Eintrag gehört. Bitte im Explorer zurückschieben."
        if not (root / rel_parts[0]).is_dir():
            return (
                f"Die Kategorie {rel_parts[0]} gibt es nicht mehr. "
                "Erst die Kategorie anlegen, dann wiederherstellen."
            )
        other = partmod.find_part_dir(root, entry.name)
        if other is not None:
            return (
                f"Die Bezeichnung {entry.name} ist inzwischen wieder vergeben "
                f"({other.relative_to(root).as_posix()})."
            )
        if root.joinpath(*rel_parts).exists():
            return f"Am alten Platz gibt es schon einen Ordner: {entry.path}"
        return ""
    if len(rel_parts) < 3:
        return "Unklar, wohin der Eintrag gehört. Bitte im Explorer zurückschieben."
    if _owner_dir(root, rel_parts) is None:
        return (
            f"Das Bauteil {entry.part} gibt es an seinem alten Platz nicht mehr. "
            "Die Datei im Explorer in den neuen Ordner des Bauteils schieben."
        )
    return ""


def _free_path(directory: Path, name: str) -> Path:
    """Freier Dateiname: datasheet.pdf, sonst datasheet-2.pdf, datasheet-3.pdf, …"""
    candidate = directory / name
    stem, suffix = Path(name).stem, Path(name).suffix
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{number}{suffix}"
        number += 1
    return candidate


def _prune(start: Path, stop: Path) -> None:
    """Entfernt leere Ordner von `start` aufwärts bis einschließlich `stop`."""
    current = start
    while True:
        try:
            current.rmdir()  # gelingt nur bei einem leeren Ordner
        except OSError:
            return
        if current == stop:
            return
        current = current.parent


def restore(root: Path, entry_id: str) -> Path:
    """Holt einen Eintrag an seinen alten Platz im Lager zurück und gibt den neuen Ort zurück.

    Ein Bauteil kommt in seine Kategorie und Unterkategorie (eine fehlende Unterkategorie
    wird wieder angelegt). Eine Datei kommt in ihr Bauteil; gibt es dort schon eine Datei
    gleichen Namens, bekommt sie eine Nummer. Geht das nicht, gibt es einen ValueError
    mit dem Grund, und nichts wird verändert.
    """
    entry = find_entry(root, entry_id)
    problem = restore_problem(root, entry)
    if problem:
        raise ValueError(problem)
    rel_parts = tuple(entry.path.split("/"))
    if entry.kind == "part":
        parent = catmod.subcategory_dir(root, rel_parts[0], "/".join(rel_parts[1:-1]))
        target = parent / entry.name
    else:
        owner = _owner_dir(root, rel_parts)
        assert owner is not None  # von restore_problem geprüft
        depth = len(owner.relative_to(root).parts)
        parent = owner.joinpath(*rel_parts[depth:-1])
        target = _free_path(parent, rel_parts[-1])
    try:
        parent.mkdir(parents=True, exist_ok=True)
        entry.location.rename(target)
    except OSError as e:
        raise ValueError(
            f"{entry.name} lässt sich nicht zurückholen. Ist eine Datei daraus gerade "
            f"geöffnet? ({e})"
        ) from e
    _prune(entry.location.parent, trash_dir(root) / entry.id)
    return target


def local_time(iso_utc: str) -> str:
    """'2026-11-26T20:55:02Z' -> '26.11.2026, 21:55' in der Zeitzone dieses Rechners."""
    try:
        moment = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return str(iso_utc)
    return moment.astimezone().strftime("%d.%m.%Y, %H:%M")
