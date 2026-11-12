"""SQLite-Zugriff: Index-Datei öffnen, Schema anlegen, Version prüfen.

Das Schema steht als reines SQL in schema.sql (KONZEPT.md §8, D6). Die
Datenbank liegt unter <lager_root>/.lager/parts.db und wandert mit dem Lager.
"""
from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1
INDEX_DIR = ".lager"
DB_NAME = "parts.db"


class IndexDbError(Exception):
    """Fehler rund um die Index-Datenbank (Meldung auf Deutsch, für die Ausgabe)."""


def db_path(root: Path) -> Path:
    return root / INDEX_DIR / DB_NAME


def schema_sql() -> str:
    return resources.files("lager").joinpath("schema.sql").read_text(encoding="utf-8")


def connect(root: Path, create: bool = True) -> sqlite3.Connection:
    """Öffnet den Index. Fehlt die Datei, wird sie mit leerem Schema angelegt."""
    path = db_path(root)
    if not path.exists():
        if not create:
            raise IndexDbError("Kein Index vorhanden. Erst ausführen: lager index rebuild")
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(schema_sql())
    elif version != SCHEMA_VERSION:
        raise IndexDbError(
            f"Der Index hat Schema-Version {version}, dieses Programm erwartet "
            f"{SCHEMA_VERSION}. Der Index ist abgeleitet: Ordner `{INDEX_DIR}` im "
            "Lager-Root löschen und `lager index rebuild` ausführen."
        )
