"""Entwürfe für „Automatisch ergänzen“ (KONZEPT.md §6d, D25).

Ein Entwurf ist ein Vorschlag für ein neues Bauteil. Er liegt unter
<lager_root>/_entwuerfe/<Zeitpunkt>/draft.yaml; Dateien, die eine Suche findet
(Datenblatt, KiCad, 3D-Modell), liegen daneben. Ordner mit `_` am Anfang überspringt das
Lager, ein Entwurf taucht deshalb nicht in der Suche auf.

Ablauf: `create` legt einen Entwurf mit dem Stand `queued` (wartet) an und kehrt sofort
zurück. Vorbereitet wird er im Hintergrund (`process`, im Server vom Arbeiter in
server/worker.py): Stand `running`, danach `ready` (bereit zum Prüfen) oder `failed` (Fehler,
lässt sich trotzdem von Hand ergänzen). So kann Lukas viele Bauteile hintereinander eingeben.
Eine Sperrdatei im Ordner sorgt dafür, dass nie zwei Prozesse denselben Entwurf bearbeiten.

Zum Bauteil wird ein Entwurf erst, wenn Lukas ihn prüft und speichert: Das Bauteil wird
mit den geprüften Werten angelegt, `finish` räumt die Dateien des Entwurfs hinein und
entfernt den Entwurf. `discard` schiebt einen Entwurf in den Papierkorb des Lagers.

Jeder Wert trägt seine Herkunft (`source`), ein leerer Wert keine:

    kind: input    aus der Eingabe
          api      von einer Schnittstelle   (name, z. B. "Mouser"; url: Seite des Bauteils)
          library  aus einer Bibliothek      (name, z. B. "KiCad")
          web      aus einer Quelle im Netz  (url; quote: wörtliche Textstelle als Beleg)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from . import files as filesmod
from . import names, trash
from . import parts as partmod

DRAFT_DIR = "_entwuerfe"
DRAFT_FILE = "draft.yaml"
SCHEMA_VERSION = 1
MAX_INPUT_LENGTH = 200
# Felder eines Vorschlags, wie in part.yaml (dazu Kategorie und Unterkategorie, die beim
# Bauteil aus dem Pfad kommen). Menge und Lagerfach trägt nur Lukas ein, nie eine Suche.
FIELDS = ("part", "category", "subcategory", "name", "manufacturer", "aliases", "tags", "notes")
LIST_FIELDS = ("aliases", "tags")
SOURCE_KINDS = ("input", "api", "library", "web")
SOURCE_KEYS = ("kind", "name", "url", "quote")
# Stand eines Entwurfs. Prüfen und speichern lässt er sich, sobald er fertig ist (auch nach
# einem Fehler: dann ergänzt Lukas von Hand).
STATUSES = ("queued", "running", "ready", "failed")
STATUS_LABELS = {
    "queued": "wartet",
    "running": "in Arbeit",
    "ready": "bereit zum Prüfen",
    "failed": "Fehler beim Vorbereiten",
}
REVIEWABLE = ("ready", "failed")
# Sperrdatei während der Bearbeitung (Punkt am Anfang: gehört nicht zu den Dateien des
# Vorschlags). Ist sie älter als STALE_SECONDS, gilt die Bearbeitung als abgebrochen
# (z. B. Server beendet) und der Entwurf wird neu vorbereitet.
LOCK_FILE = ".in-arbeit"
STALE_SECONDS = 30 * 60
_TEMP_FILE = ".draft.yaml.neu"
HEADER = """# draft.yaml — Vorschlag für ein neues Bauteil („Automatisch ergänzen“, KONZEPT.md §6d)
# Wird erst durch „Speichern“ zum Bauteil. Jeder Wert nennt seine Herkunft (source):
# input = aus der Eingabe, api = Schnittstelle, library = Bibliothek, web = Quelle im Netz
# (url, quote = wörtliche Textstelle als Beleg). Ein leerer Wert hat keine Herkunft.
"""
# Dateien, die Windows selbst in Ordnern ablegt; sie gehören nicht zum Vorschlag.
_IGNORED_FILES = {"thumbs.db", "desktop.ini"}


class DraftNotFound(ValueError):
    """Den Entwurf gibt es nicht (mehr), z. B. weil er schon gespeichert wurde."""


@dataclass(frozen=True)
class DraftFile:
    path: str  # relativ zum Ordner des Entwurfs, z. B. "datasheet.pdf"
    size: int
    source: dict  # Herkunft wie bei den Werten; leer = unbekannt (z. B. von Hand dazugelegt)


@dataclass(frozen=True)
class Draft:
    id: str  # Name des Ordners, z. B. "20261127T091500Z"
    created: str  # ISO 8601 in UTC
    input: str  # was eingegeben wurde
    fields: dict  # Feld -> {"value": Text oder Liste, "source": Herkunft}
    files: list  # DraftFile
    folder: Path
    status: str = "ready"  # queued | running | ready | failed
    error: str = ""  # Grund bei failed
    updated: str = ""  # letzte Änderung des Stands, ISO 8601 in UTC

    @property
    def reviewable(self) -> bool:
        """Fertig vorbereitet (oder gescheitert): Lukas kann prüfen und speichern."""
        return self.status in REVIEWABLE

    def value(self, name: str):
        return self.fields[name]["value"]

    def source(self, name: str) -> dict:
        return self.fields[name]["source"]

    def as_dict(self, root: Path) -> dict:
        """Für CLI (`--json`) und API: Felder auf Englisch, Pfade relativ zum Lager."""
        return {
            "id": self.id,
            "created": self.created,
            "updated": self.updated,
            "status": self.status,
            "error": self.error,
            "input": self.input,
            "path": self.folder.relative_to(root).as_posix(),
            "fields": {
                name: {"value": self.value(name), "source": dict(self.source(name))}
                for name in FIELDS
            },
            "files": [
                {"path": item.path, "size": item.size, "source": dict(item.source)}
                for item in self.files
            ],
        }


def drafts_dir(root: Path) -> Path:
    return root / DRAFT_DIR


# ------------------------------------------------------------ Lesen


def _clean_source(raw) -> dict:
    """Herkunft aus der Datei: nur bekannte Schlüssel als Text; unbekannte Art = keine."""
    if not isinstance(raw, dict):
        return {}
    source = {key: str(raw.get(key) or "").strip() for key in SOURCE_KEYS}
    if source["kind"] not in SOURCE_KINDS:
        return {}
    return {key: value for key, value in source.items() if value}


def _clean_value(name: str, raw):
    if name in LIST_FIELDS:
        items = raw if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
        cleaned = (names.clean(str(item)) for item in items if item is not None)
        return list(dict.fromkeys(item for item in cleaned if item))
    return "" if raw is None else str(raw).strip()


def _field(name: str, raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    value = _clean_value(name, raw.get("value"))
    return {"value": value, "source": _clean_source(raw.get("source")) if value else {}}


def _files(folder: Path, raw) -> list[DraftFile]:
    """Die Dateien im Ordner des Entwurfs, mit ihrer Herkunft aus draft.yaml."""
    sources = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("path"):
            sources[str(item["path"])] = _clean_source(item.get("source"))
    found = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if (
            not path.is_file()
            or rel.as_posix() == DRAFT_FILE
            or path.name.lower() in _IGNORED_FILES
            or any(piece.startswith(".") for piece in rel.parts)
        ):
            continue
        found.append(DraftFile(rel.as_posix(), path.stat().st_size, sources.get(rel.as_posix(), {})))
    return found


def _folder(root: Path, draft_id: str) -> Path:
    """Ordner eines vorhandenen Entwurfs; sonst DraftNotFound."""
    if not trash.is_stamp(draft_id):
        raise DraftNotFound(f"Ungültiger Vorschlag: {draft_id!r}")
    folder = drafts_dir(root) / draft_id
    if not (folder / DRAFT_FILE).is_file():
        raise DraftNotFound(
            f"Den Vorschlag {draft_id} gibt es nicht (mehr). "
            "Vielleicht ist er schon gespeichert oder verworfen."
        )
    return folder


def _read_doc(folder: Path) -> dict:
    """Inhalt von draft.yaml als dict (ValueError, wenn die Datei nicht lesbar ist)."""
    try:
        doc = yaml.safe_load((folder / DRAFT_FILE).read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ValueError(f"Der Vorschlag {folder.name} ist nicht lesbar: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"Der Vorschlag {folder.name} enthält keine Felder.")
    return doc


def load(root: Path, draft_id: str) -> Draft:
    """Liest einen Entwurf. Fehlt er: DraftNotFound; ist er kaputt: ValueError."""
    folder = _folder(root, draft_id)
    doc = _read_doc(folder)
    raw_fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
    created = str(doc.get("created") or trash.stamp_iso(draft_id))
    # Ohne Stand (von Hand angelegt): als fertig behandeln, damit er sich prüfen lässt.
    status = doc.get("status") if doc.get("status") in STATUSES else "ready"
    return Draft(
        id=draft_id,
        created=created,
        input=names.clean(str(doc.get("input") or "")),
        fields={name: _field(name, raw_fields.get(name)) for name in FIELDS},
        files=_files(folder, doc.get("files")),
        folder=folder,
        status=status,
        error=str(doc.get("error") or "") if status == "failed" else "",
        updated=str(doc.get("updated") or created),
    )


def entries(root: Path) -> list[Draft]:
    """Alle offenen Entwürfe, der neueste zuerst. Unlesbare werden übersprungen."""
    base = drafts_dir(root)
    if not base.is_dir():
        return []
    found = []
    for folder in base.iterdir():
        if not folder.is_dir() or not trash.is_stamp(folder.name):
            continue
        try:
            found.append(load(root, folder.name))
        except ValueError:
            continue
    found.sort(key=lambda draft: trash.stamp_key(draft.id), reverse=True)
    return found


def title_of(folder: Path) -> str:
    """Eingabe eines Entwurfs für Anzeigen (Papierkorb); ohne lesbare Datei der Ordnername."""
    try:
        doc = yaml.safe_load((folder / DRAFT_FILE).read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        doc = {}
    text = names.clean(str(doc.get("input") or "")) if isinstance(doc, dict) else ""
    return text or folder.name


def describe_source(source: dict) -> dict:
    """Herkunft eines Werts für Seite und CLI: Text, Link (nur http/https) und Zitat."""
    kind, name = source.get("kind", ""), source.get("name", "")
    if kind == "input":
        text = "aus deiner Eingabe"
    elif kind == "api":
        text = f"von {name}" if name else "von einer Schnittstelle"
    elif kind == "library":
        text = f"aus {name}" if name else "aus einer Bibliothek"
    elif kind == "web":
        text = "aus einer Quelle im Netz"
    else:
        return {}
    url = source.get("url", "")
    if not url.lower().startswith(("http://", "https://")):
        url = ""
    return {"text": text, "url": url, "quote": source.get("quote", "")}


# ------------------------------------------------------------ Anlegen


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(folder: Path, doc: dict) -> None:
    """Schreibt draft.yaml in einem Schritt (erst eine neue Datei, dann austauschen).

    Die Seite liest einen Entwurf, während der Arbeiter ihn schreibt; sie soll nie eine halb
    geschriebene Datei sehen. Windows lässt das Austauschen kurz nicht zu, solange gerade
    jemand liest; dann wird es nach einer Pause wiederholt.
    """
    temp = folder / _TEMP_FILE
    temp.write_text(
        HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for _attempt in range(40):
        try:
            os.replace(temp, folder / DRAFT_FILE)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(temp, folder / DRAFT_FILE)


def create(root: Path, text: str) -> Draft:
    """Legt einen Entwurf aus einer Eingabe an (Name, Bestellnummer oder Suchbegriff).

    Kehrt sofort zurück: Der Entwurf wartet (`queued`), bis `process` ihn vorbereitet.
    """
    raw = names.clean(text)
    if not raw:
        raise ValueError("Bitte einen Namen, eine Bestellnummer oder einen Suchbegriff eingeben.")
    if len(raw) > MAX_INPUT_LENGTH:
        raise ValueError(f"Die Eingabe ist zu lang (höchstens {MAX_INPUT_LENGTH} Zeichen).")
    base = drafts_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    folder = trash.claim_stamp_folder(base)
    created = trash.stamp_iso(folder.name)
    doc = {
        "schema": SCHEMA_VERSION,
        "id": folder.name,
        "created": created,
        "updated": created,
        "status": "queued",
        "error": "",
        "input": raw,
        "fields": {
            name: {"value": [] if name in LIST_FIELDS else "", "source": {}} for name in FIELDS
        },
        "files": [],
    }
    try:
        _write(folder, doc)
    except OSError:
        _remove_folder(folder, base)
        raise
    return load(root, folder.name)


# ------------------------------------------------------------ Vorbereiten


def _stage_input(root: Path, doc: dict, cfg: dict) -> None:
    """Stufe 1: die Eingabe als Bezeichnung vorschlagen (nur Leerzeichen aufgeräumt)."""
    part = doc["fields"].setdefault("part", {})
    if not _clean_value("part", part.get("value")):
        doc["fields"]["part"] = {"value": names.clean(doc.get("input")), "source": {"kind": "input"}}


# Die Stufen eines Vorschlags, in dieser Reihenfolge (KONZEPT.md §6d). Jede bekommt das Lager,
# den Inhalt von draft.yaml (zum Ergänzen) und die Einstellungen. Mouser, KiCad und die
# KI-Recherche kommen in den nächsten Schritten dazu.
STAGES: tuple[Callable[[Path, dict, dict], None], ...] = (_stage_input,)


def _lock_is_stale(lock: Path) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > STALE_SECONDS
    except OSError:
        return True  # gerade freigegeben


def _abandoned(draft: Draft) -> bool:
    """In Arbeit, aber niemand arbeitet mehr daran (Sperre fehlt oder ist zu alt)."""
    return draft.status == "running" and _lock_is_stale(draft.folder / LOCK_FILE)


def pending(root: Path) -> list[Draft]:
    """Vorschläge, die auf das Vorbereiten warten (auch liegengebliebene), der älteste zuerst."""
    waiting = [d for d in entries(root) if d.status == "queued" or _abandoned(d)]
    return list(reversed(waiting))


def process(root: Path, draft_id: str, cfg: dict | None = None) -> bool:
    """Bereitet einen wartenden Entwurf vor: alle Stufen, danach `ready` oder `failed`.

    Gibt False zurück, wenn er nicht (mehr) wartet, weg ist oder gerade ein anderer Prozess
    daran arbeitet. Ein Fehler in einer Stufe hält nichts an: Der Entwurf bekommt den Stand
    `failed` mit dem Grund und lässt sich trotzdem von Hand ergänzen.
    """
    try:
        folder = _folder(root, draft_id)
    except DraftNotFound:
        return False
    lock = folder / LOCK_FILE
    try:
        lock.touch(exist_ok=False)  # belegt den Entwurf in einem Schritt
    except FileExistsError:
        if not _lock_is_stale(lock):
            return False
        lock.unlink(missing_ok=True)
        try:
            lock.touch(exist_ok=False)
        except OSError:
            return False
    except OSError:
        return False
    try:
        doc = _read_doc(folder)
        if doc.get("status") not in ("queued", "running"):
            return False
        doc["fields"] = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
        doc.update({"status": "running", "error": "", "updated": _now()})
        _write(folder, doc)
        try:
            for stage in STAGES:
                stage(root, doc, cfg or {})
        except Exception as e:  # noqa: BLE001 - eine Stufe darf den Arbeiter nicht anhalten
            doc.update({"status": "failed", "error": f"{type(e).__name__}: {e}"})
        else:
            doc["status"] = "ready"
        doc["updated"] = _now()
        _write(folder, doc)
        return True
    except (FileNotFoundError, ValueError):
        return False  # inzwischen verworfen oder unlesbar
    finally:
        lock.unlink(missing_ok=True)


def process_pending(
    root: Path, cfg: dict | None = None, should_stop: Callable[[], bool] | None = None
) -> int:
    """Bereitet alle wartenden Entwürfe vor, den ältesten zuerst; gibt ihre Anzahl zurück."""
    done = 0
    for draft in pending(root):
        if should_stop is not None and should_stop():
            break
        if process(root, draft.id, cfg):
            done += 1
    return done


# ------------------------------------------------------------ Abschließen


def _remove_folder(folder: Path, base: Path) -> None:
    """Entfernt den Ordner eines Entwurfs, sobald darin nichts Wichtiges mehr liegt.

    Weg kommen nur leere Ordner und die Dateien, die Windows selbst anlegt. Bleibt etwas
    anderes übrig, bleibt der Ordner (ohne draft.yaml taucht er nirgends mehr auf).
    Danach verschwindet auch `_entwuerfe`, wenn es leer ist.
    """
    for path in folder.rglob("*"):
        if path.is_file() and path.name.lower() in _IGNORED_FILES:
            try:
                path.unlink()
            except OSError:
                pass
    subfolders = sorted(
        (path for path in folder.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in [*subfolders, folder, base]:
        try:
            path.rmdir()  # gelingt nur bei einem leeren Ordner
        except OSError:
            if path in (folder, base):
                return


def finish(root: Path, draft_id: str, part_dir: Path, cfg: dict | None = None) -> list[str]:
    """Räumt die Dateien eines gespeicherten Entwurfs in das neue Bauteil und entfernt ihn.

    Gibt Fehlermeldungen zurück (leer = alles übernommen). Bleibt eine Datei zurück, zum
    Beispiel weil sie gerade geöffnet ist, bleibt auch der Entwurf mit ihr liegen.
    """
    draft = load(root, draft_id)
    errors = []
    for item in draft.files:
        source = draft.folder.joinpath(*item.path.split("/"))
        try:
            filesmod.add_file_from_path(part_dir, source, cfg, move=True)
        except (ValueError, OSError) as e:
            errors.append(f"{item.path}: {e}")
    if errors:
        return errors
    (draft.folder / DRAFT_FILE).unlink()
    _remove_folder(draft.folder, drafts_dir(root))
    return []


def ensure_reviewable(draft: Draft) -> None:
    """ValueError, solange ein Entwurf noch wartet oder vorbereitet wird."""
    if not draft.reviewable:
        raise ValueError(
            f"Der Vorschlag „{draft.input}“ wird noch vorbereitet ({STATUS_LABELS[draft.status]}). "
            "Gespeichert werden kann er, sobald er fertig ist."
        )


def save(
    root: Path,
    draft_id: str,
    category: str,
    part_id: str,
    data: dict,
    subcategory: str = "",
    cfg: dict | None = None,
) -> tuple[Path, list[str]]:
    """Legt aus einem geprüften Entwurf das Bauteil an und gibt (Ordner, Fehler) zurück.

    `data` sind die Felder wie bei parts.create_part, so wie Lukas sie bestätigt hat.
    Gibt es den Entwurf nicht mehr oder ist er noch nicht fertig, wird nichts angelegt.
    """
    ensure_reviewable(load(root, draft_id))
    part_dir = partmod.create_part(root, category, part_id, data, subcategory)
    return part_dir, finish(root, draft_id, part_dir, cfg)


def discard(root: Path, draft_id: str) -> Path:
    """Schiebt einen Entwurf in den Papierkorb des Lagers und gibt den Ort dort zurück.

    Während er gerade vorbereitet wird, geht das nicht (ValueError); wartende lassen sich
    verwerfen.
    """
    folder = _folder(root, draft_id)
    if (folder / LOCK_FILE).exists() and not _lock_is_stale(folder / LOCK_FILE):
        raise ValueError(
            "Der Vorschlag wird gerade vorbereitet und lässt sich erst danach verwerfen. "
            "Bitte gleich noch einmal versuchen."
        )
    try:
        target = trash.move_to_trash(root, folder)
    except OSError as e:
        raise ValueError(
            f"Der Vorschlag lässt sich nicht verwerfen. Ist eine Datei daraus geöffnet? ({e})"
        ) from e
    try:
        drafts_dir(root).rmdir()  # nur, wenn kein Entwurf mehr übrig ist
    except OSError:
        pass
    return target
