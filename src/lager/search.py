"""Suche und Abfragen auf dem Index.

Diese Funktionen liefern einfache dicts. CLI (`--json`) und REST-API geben
sie unverändert aus, damit beide Schnittstellen dieselben Daten zeigen.
"""
from __future__ import annotations

import sqlite3
from typing import Any

MAX_LIMIT = 500

_PART_SELECT = """
    SELECT p.id, p.part, p.category_id, c.label AS category_label, p.subcategory,
           p.rel_path, p.name, p.manufacturer, p.quantity, p.unit, p.location, p.notes
    FROM parts p
    JOIN categories c ON c.id = p.category_id
"""


def _escape_like(term: str) -> str:
    """Macht %, _ und \\ in einem Suchbegriff zu normalen Zeichen."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _part_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    part_id = row["id"]
    aliases = conn.execute(
        "SELECT alias FROM part_aliases WHERE part_id = ? ORDER BY alias", (part_id,)
    )
    tags = conn.execute("SELECT tag FROM part_tags WHERE part_id = ? ORDER BY tag", (part_id,))
    files = conn.execute(
        "SELECT rel_path, kind, ext, size, mtime FROM files WHERE part_id = ? "
        "ORDER BY CASE kind WHEN 'datasheet' THEN 0 ELSE 1 END, rel_path",
        (part_id,),
    )
    return {
        "part": row["part"],
        "name": row["name"],
        "manufacturer": row["manufacturer"],
        "category": row["category_id"],
        "category_label": row["category_label"],
        "subcategory": row["subcategory"],
        "path": row["rel_path"],
        "quantity": row["quantity"],
        "unit": row["unit"],
        "location": row["location"],
        "notes": row["notes"],
        "aliases": [r["alias"] for r in aliases],
        "tags": [r["tag"] for r in tags],
        "files": [
            {
                "path": f["rel_path"],
                "kind": f["kind"],
                "ext": f["ext"],
                "size": f["size"],
                "mtime": f["mtime"],
            }
            for f in files
        ],
    }


def search(
    conn: sqlite3.Connection, query: str = "", category: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Sucht Bauteile. Jeder Begriff muss vorkommen; Groß-/Kleinschreibung ist egal.

    Durchsucht werden Bezeichnung, Name, Hersteller, Aliase, Tags, Kategorie,
    Unterkategorie, Lagerfach und die Dateinamen im Bauteil-Ordner. Ohne Begriff
    kommen alle Bauteile zurück.
    Treffer mit genau passender Bezeichnung stehen vorn.
    """
    terms = query.casefold().split()
    where: list[str] = []
    params: dict[str, Any] = {}
    for i, term in enumerate(terms):
        where.append(f"p.search_text LIKE :t{i} ESCAPE '\\'")
        params[f"t{i}"] = f"%{_escape_like(term)}%"
    if category:
        where.append("p.category_id = :category")
        params["category"] = category
    params["first"] = terms[0] if terms else ""
    params["first_prefix"] = f"{_escape_like(terms[0])}%" if terms else ""
    params["limit"] = max(1, min(int(limit), MAX_LIMIT))

    sql = (
        _PART_SELECT
        + (" WHERE " + " AND ".join(where) if where else "")
        + """
        ORDER BY CASE
                   WHEN :first <> '' AND lower(p.part) = :first THEN 0
                   WHEN :first <> '' AND lower(p.part) LIKE :first_prefix ESCAPE '\\' THEN 1
                   ELSE 2
                 END,
                 p.part COLLATE NOCASE, p.rel_path
        LIMIT :limit
        """
    )
    return [_part_dict(conn, row) for row in conn.execute(sql, params).fetchall()]


def get_part(conn: sqlite3.Connection, part: str) -> dict[str, Any] | None:
    """Ein Bauteil über seine Bezeichnung (Groß-/Kleinschreibung egal)."""
    row = conn.execute(
        _PART_SELECT + " WHERE p.part = ? COLLATE NOCASE ORDER BY p.rel_path LIMIT 1",
        (part.strip(),),
    ).fetchone()
    return _part_dict(conn, row) if row is not None else None


def list_categories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id, c.label, c.listed, COUNT(p.id) AS parts
        FROM categories c
        LEFT JOIN parts p ON p.category_id = c.id
        GROUP BY c.id
        ORDER BY c.position
        """
    )
    return [
        {"id": r["id"], "label": r["label"], "listed": bool(r["listed"]), "parts": r["parts"]}
        for r in rows
    ]


def find_file(conn: sqlite3.Connection, rel_path: str) -> dict[str, Any] | None:
    """Eine indizierte Datei über ihren Pfad relativ zum Lager-Root.

    Nur Dateien, die im Index stehen, werden gefunden. Damit lässt sich über
    diesen Weg nichts außerhalb der Bauteil-Ordner abrufen.
    """
    row = conn.execute(
        """
        SELECT p.rel_path || '/' || f.rel_path AS path, f.kind, f.ext, f.size, f.mtime
        FROM files f
        JOIN parts p ON p.id = f.part_id
        WHERE p.rel_path || '/' || f.rel_path = ?
        """,
        (rel_path,),
    ).fetchone()
    return dict(row) if row is not None else None
