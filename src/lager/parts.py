"""Bauteile: Bezeichnungen normalisieren, part.yaml anlegen und lesen."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

PART_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.+]*$")
_DISALLOWED = re.compile(r"[^A-Z0-9\-_.+]")

HEADER = """# part.yaml — Metadaten eines Bauteils
# part       kanonische Bezeichnung (= Ordnername)
# name       Beschreibung (menschlich)
# aliases    weitere Suchbegriffe (Bestell-, Hersteller-, Alt-Bezeichnungen)
# quantity   aktuelle Lagermenge
# unit       Mengeneinheit
# location   Lagerfach (frei wählbar, z. B. "A-03-2")
# tags       freie Schlagwörter
# Kategorie  kommt aus dem Pfad (1. Ebene unter lager_root) — nicht hier speichern
"""


def normalize_part_id(raw: str) -> str:
    """' Irlz44n ' -> 'IRLZ44N' (Groß, ohne Leerzeichen, nur erlaubte Zeichen)."""
    s = raw.strip().upper().replace(" ", "")
    return _DISALLOWED.sub("", s)


def part_dir(root: Path, category_id: str, part_id: str) -> Path:
    return root / category_id / part_id


def read_part(root: Path, category_id: str, part_id: str) -> dict:
    p = part_dir(root, category_id, part_id) / "part.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Teil nicht gefunden: {category_id}/{part_id}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def find_part(root: Path, raw_id: str) -> tuple[Path, dict] | None:
    """Sucht ein Teil über seine Bezeichnung (Groß-/Kleinschreibung egal)."""
    target = normalize_part_id(raw_id).lower()
    if not target:
        return None
    for py in sorted(root.rglob("part.yaml")):
        if any(part.startswith(("_", ".")) for part in py.parts):
            continue
        if py.parent.name.lower() == target:
            data = yaml.safe_load(py.read_text(encoding="utf-8")) or {}
            return py.parent, data
    return None


def find_part_dir(root: Path, raw_id: str) -> Path | None:
    """Ordner eines Teils über seine Bezeichnung, ohne die part.yaml zu lesen."""
    target = normalize_part_id(raw_id).lower()
    if not target:
        return None
    for py in sorted(root.rglob("part.yaml")):
        rel = py.relative_to(root)
        if any(piece.startswith(("_", ".")) for piece in rel.parts):
            continue
        if py.parent.name.lower() == target:
            return py.parent
    return None


def empty_doc_yaml() -> str:
    """Inhalt einer unbelegten part.yaml (für die Vorlage)."""
    doc = {
        "part": "BEZEICHNUNG",
        "name": "",
        "manufacturer": "",
        "aliases": [],
        "quantity": 0,
        "unit": "Stk",
        "location": "",
        "tags": [],
        "notes": "",
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def create_part(root: Path, category_id: str, raw_id: str, data: dict) -> Path:
    """Legt <root>/<kategorie>/<BEZEICHNUNG>/part.yaml an und gibt den Ordner zurück."""
    part_id = normalize_part_id(raw_id)
    if not part_id or not PART_ID_RE.match(part_id):
        raise ValueError(f"Ungültige Bauteil-Bezeichnung: {raw_id!r}")
    category_path = Path(category_id)
    if not category_id.strip() or category_path.is_absolute() or ".." in category_path.parts:
        raise ValueError(f"Ungültige Kategorie: {category_id!r}")
    cat_dir = root / category_path
    if not cat_dir.is_dir():
        raise ValueError(
            f"Kategorie existiert nicht: {category_id} "
            f"(erst: lager category add {category_id})"
        )
    # Die Bezeichnung ist im ganzen Lager eindeutig (Adresse /p/<BEZEICHNUNG>, QR-Etikett).
    existing = find_part_dir(root, part_id)
    if existing is not None:
        raise ValueError(f"Teil existiert bereits: {existing}")
    pdir = cat_dir / part_id
    # Ein schon vorhandener Ordner ohne part.yaml (z. B. mit PDFs) wird übernommen.
    pdir.mkdir(parents=False, exist_ok=True)
    doc = {
        "part": part_id,
        "name": data.get("name", ""),
        "manufacturer": data.get("manufacturer", ""),
        "aliases": list(data.get("aliases") or []),
        "quantity": int(data.get("quantity", 0)),
        "unit": data.get("unit", "Stk"),
        "location": data.get("location", ""),
        "tags": list(data.get("tags") or []),
        "notes": data.get("notes", ""),
    }
    (pdir / "part.yaml").write_text(
        HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return pdir
