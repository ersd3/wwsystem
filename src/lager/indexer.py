"""Index: Ordnerstruktur einlesen und als SQLite-Index ablegen (Phase 0.2).

Die Ordner und part.yaml-Dateien sind die Quelle der Wahrheit. Der Index ist
abgeleitet und wird mit `rebuild` jederzeit vollständig neu aufgebaut. Ein
Neuaufbau läuft in einer einzigen Transaktion: Schlägt er fehl, bleibt der
alte Index unverändert.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import __version__, categories as catmod, db
from .root import is_part_dir, visible_dirs

# Dateiart je Dateiendung. Überschreibbar in config.yaml unter `file_kinds`.
DEFAULT_FILE_KINDS: dict[str, list[str]] = {
    "datasheet": ["pdf"],
    "cad3d": ["step", "stp", "wrl", "iges", "igs", "stl"],
    "kicad": ["kicad_mod", "kicad_sym", "kicad_pcb", "kicad_sch"],
    "image": ["png", "jpg", "jpeg", "gif", "webp", "svg"],
}
OTHER_KIND = "other"
# Dateien, die Windows selbst in Ordnern ablegt.
IGNORED_FILES = {"thumbs.db", "desktop.ini"}

# Tabellen, die ein Neuaufbau leert (Reihenfolge wegen der Fremdschlüssel).
_INDEX_TABLES = ("files", "part_tags", "part_aliases", "parts", "categories")


@dataclass
class ScannedFile:
    rel_path: str
    kind: str
    ext: str
    size: int
    mtime: str


@dataclass
class ScannedPart:
    part: str
    category_id: str
    category_label: str
    subcategory: str
    rel_path: str
    name: str = ""
    manufacturer: str = ""
    quantity: int = 0
    unit: str = ""
    location: str = ""
    notes: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    files: list[ScannedFile] = field(default_factory=list)

    def search_text(self) -> str:
        words = [
            self.part, self.name, self.manufacturer, *self.aliases, *self.tags,
            self.category_id, self.category_label, self.subcategory, self.location,
        ]
        return " ".join(w for w in words if w).casefold()


@dataclass
class Scan:
    categories: list[dict[str, Any]] = field(default_factory=list)
    parts: list[ScannedPart] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def warn(self, path: str, reason: str) -> None:
        self.warnings.append({"pfad": path, "grund": reason})


def utc_iso(timestamp: float | None = None) -> str:
    """Zeitpunkt als ISO-8601-Text in UTC, z. B. 2026-11-12T14:03:00Z."""
    if timestamp is None:
        moment = datetime.now(timezone.utc)
    else:
        moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _kind_by_ext(cfg: dict | None) -> dict[str, str]:
    kinds = (cfg or {}).get("file_kinds") or DEFAULT_FILE_KINDS
    out: dict[str, str] = {}
    for kind, extensions in kinds.items():
        for ext in extensions or []:
            out[str(ext).lower().lstrip(".")] = str(kind)
    return out


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _str_list(value: Any) -> list[str]:
    """Liste von Texten ohne leere und doppelte Einträge (Reihenfolge bleibt)."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out: list[str] = []
    for item in items:
        text = _text(item)
        if text and text not in out:
            out.append(text)
    return out


def _first_line(error: Exception) -> str:
    lines = str(error).strip().splitlines()
    return lines[0] if lines else type(error).__name__


def _scan_files(part_dir: Path, kind_by_ext: dict[str, str]) -> list[ScannedFile]:
    files: list[ScannedFile] = []
    for f in sorted(part_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(part_dir)
        if rel.as_posix() == "part.yaml":
            continue
        if any(piece.startswith(".") for piece in rel.parts):
            continue
        if f.name.lower() in IGNORED_FILES:
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        ext = f.suffix.lower().lstrip(".")
        files.append(
            ScannedFile(
                rel_path=rel.as_posix(),
                kind=kind_by_ext.get(ext, OTHER_KIND),
                ext=ext,
                size=stat.st_size,
                mtime=utc_iso(stat.st_mtime),
            )
        )
    return files


def _read_part(
    root: Path, part_dir: Path, cat: dict[str, Any], out: Scan, kind_by_ext: dict[str, str]
) -> ScannedPart | None:
    rel = part_dir.relative_to(root)
    rel_path = rel.as_posix()
    yaml_path = f"{rel_path}/part.yaml"
    try:
        # utf-8-sig liest auch Dateien, die der Windows-Editor mit BOM gespeichert hat.
        raw = yaml.safe_load((part_dir / "part.yaml").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        out.warn(yaml_path, f"nicht lesbar, Bauteil übersprungen: {_first_line(e)}")
        return None
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        out.warn(yaml_path, "enthält keine Felder (kein YAML-Mapping), Bauteil übersprungen")
        return None

    declared = _text(raw.get("part"))
    if declared and declared.lower() != part_dir.name.lower():
        out.warn(
            yaml_path,
            f"Feld part ({declared}) weicht vom Ordnernamen ({part_dir.name}) ab; "
            "der Ordnername gilt",
        )

    quantity = 0
    raw_quantity = raw.get("quantity")
    if raw_quantity not in (None, ""):
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            out.warn(yaml_path, f"quantity ist keine ganze Zahl ({raw_quantity!r}); als 0 übernommen")

    return ScannedPart(
        part=part_dir.name,
        category_id=cat["id"],
        category_label=cat["label"],
        subcategory="/".join(rel.parts[1:-1]),
        rel_path=rel_path,
        name=_text(raw.get("name")),
        manufacturer=_text(raw.get("manufacturer")),
        quantity=quantity,
        unit=_text(raw.get("unit")),
        location=_text(raw.get("location")),
        notes=_text(raw.get("notes")),
        aliases=_str_list(raw.get("aliases")),
        tags=_str_list(raw.get("tags")),
        files=_scan_files(part_dir, kind_by_ext),
    )


def _walk(
    root: Path, directory: Path, cat: dict[str, Any], out: Scan, kind_by_ext: dict[str, str]
) -> None:
    for child in visible_dirs(directory):
        if is_part_dir(child):
            part = _read_part(root, child, cat, out, kind_by_ext)
            if part is not None:
                out.parts.append(part)
        else:
            _walk(root, child, cat, out, kind_by_ext)


def scan(root: Path, cfg: dict | None = None) -> Scan:
    """Liest die Ordnerstruktur ein, ohne etwas zu verändern."""
    kind_by_ext = _kind_by_ext(cfg)
    out = Scan()

    by_lower: dict[str, dict[str, Any]] = {}
    for entry in catmod.load(root):
        cat_id = str(entry["id"])
        if cat_id.lower() in by_lower:
            out.warn("categories.yaml", f"Kategorie doppelt eingetragen: {cat_id}")
            continue
        cat = {
            "id": cat_id,
            "label": _text(entry.get("label")) or cat_id,
            "position": len(out.categories),
            "listed": 1,
        }
        by_lower[cat_id.lower()] = cat
        out.categories.append(cat)

    for top in visible_dirs(root):
        if is_part_dir(top):
            out.warn(
                top.name,
                "Bauteil-Ordner liegt direkt im Lager-Root (ohne Kategorie) und wurde übersprungen",
            )
            continue
        cat = by_lower.get(top.name.lower())
        if cat is None:
            cat = {
                "id": top.name,
                "label": top.name,
                "position": len(out.categories),
                "listed": 0,
            }
            by_lower[top.name.lower()] = cat
            out.categories.append(cat)
            out.warn(top.name, "Ordner ohne Eintrag in categories.yaml (als Kategorie übernommen)")
        _walk(root, top, cat, out, kind_by_ext)

    seen: dict[str, str] = {}
    for part in out.parts:
        key = part.part.lower()
        if key in seen:
            out.warn(
                part.rel_path,
                f"Bezeichnung {part.part} gibt es mehrfach (auch unter {seen[key]})",
            )
        else:
            seen[key] = part.rel_path
    return out


def rebuild(root: Path, cfg: dict | None = None) -> dict[str, Any]:
    """Baut den Index aus der Ordnerstruktur neu auf. Mehrfach ausführbar."""
    started = time.perf_counter()
    try:
        result = scan(root, cfg)
    except yaml.YAMLError as e:
        raise db.IndexDbError(f"categories.yaml ist nicht lesbar: {_first_line(e)}") from e

    by_kind: dict[str, int] = {}
    conn = db.connect(root)
    try:
        with conn:  # eine Transaktion: ganz oder gar nicht
            for table in _INDEX_TABLES:
                conn.execute(f"DELETE FROM {table}")
            conn.executemany(
                "INSERT INTO categories (id, label, position, listed) "
                "VALUES (:id, :label, :position, :listed)",
                result.categories,
            )
            for part in result.parts:
                cursor = conn.execute(
                    "INSERT INTO parts (part, category_id, subcategory, rel_path, name, "
                    "manufacturer, quantity, unit, location, notes, search_text) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        part.part, part.category_id, part.subcategory, part.rel_path,
                        part.name, part.manufacturer, part.quantity, part.unit,
                        part.location, part.notes, part.search_text(),
                    ),
                )
                part_id = cursor.lastrowid
                conn.executemany(
                    "INSERT INTO part_aliases (part_id, alias) VALUES (?, ?)",
                    [(part_id, alias) for alias in part.aliases],
                )
                conn.executemany(
                    "INSERT INTO part_tags (part_id, tag) VALUES (?, ?)",
                    [(part_id, tag) for tag in part.tags],
                )
                conn.executemany(
                    "INSERT INTO files (part_id, rel_path, kind, ext, size, mtime) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(part_id, f.rel_path, f.kind, f.ext, f.size, f.mtime) for f in part.files],
                )
                for f in part.files:
                    by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
            conn.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                [("built_at", utc_iso()), ("generator", f"lager {__version__}")],
            )
    except sqlite3.Error as e:
        raise db.IndexDbError(f"Index konnte nicht geschrieben werden: {e}") from e
    finally:
        conn.close()

    return {
        "aktion": "index rebuild",
        "db": str(db.db_path(root)),
        "kategorien": len(result.categories),
        "teile": len(result.parts),
        "dateien": sum(by_kind.values()),
        "dateien_nach_art": dict(sorted(by_kind.items())),
        "warnungen": result.warnings,
        "dauer_ms": int((time.perf_counter() - started) * 1000),
    }


def status(root: Path) -> dict[str, Any]:
    """Zustand des Index, ohne ihn anzulegen oder zu verändern."""
    path = db.db_path(root)
    if not path.exists():
        return {"vorhanden": False, "db": str(path)}
    conn = db.connect(root, create=False)
    try:
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}

        def count(table: str) -> int:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        by_kind = {
            row["kind"]: row["n"]
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM files GROUP BY kind ORDER BY kind"
            )
        }
        return {
            "vorhanden": True,
            "db": str(path),
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "aufgebaut_am": meta.get("built_at", ""),
            "erzeugt_von": meta.get("generator", ""),
            "kategorien": count("categories"),
            "teile": count("parts"),
            "dateien": count("files"),
            "dateien_nach_art": by_kind,
        }
    finally:
        conn.close()


def ensure_index(root: Path, cfg: dict | None = None) -> None:
    """Baut den Index auf, falls es noch keinen (fertigen) gibt."""
    if not status(root).get("aufgebaut_am"):
        rebuild(root, cfg)
