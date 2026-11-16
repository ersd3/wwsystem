"""Kategorien: categories.yaml lesen/schreiben, anlegen, entfernen.

Kategorien sind reine Daten — es gibt keine hardcodierte Liste.
Anlegen funktioniert per CLI (und damit auch per AI-Agent).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from . import names
from .root import is_part_dir, visible_dirs

HEADER = """# Kategorien des Lagers.
# id    = Ordnername (normalisiert: a-z, 0-9, '-')
# label = Anzeigename (darf Umlaute enthalten)
# Reihenfolge = Anzeige-Reihenfolge.
# Anlegen: lager category add <id> [--label "Anzeigename"]
# Unterkategorien sind einfach Ordner in der Kategorie; ihr Ordnername ist ihr Anzeigename.
"""

# So tief dürfen Unterkategorien verschachtelt sein (Kategorie/A/B/C/Bauteil).
MAX_SUB_DEPTH = 3

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_UMLAUTS = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
     "Ä": "ae", "Ö": "oe", "Ü": "ue", "ẞ": "ss"}
)


def normalize_id(raw: str) -> str:
    """'Widerstände & Co' -> 'widerstaende-co'"""
    s = raw.strip().translate(_UMLAUTS).lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def path(root: Path) -> Path:
    return root / "categories.yaml"


def load(root: Path) -> list[dict]:
    p = path(root)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cats = data.get("categories") or []
    return [c for c in cats if isinstance(c, dict) and c.get("id")]


def save(root: Path, cats: list[dict]) -> None:
    body = yaml.safe_dump({"categories": cats}, allow_unicode=True, sort_keys=False)
    path(root).write_text(HEADER + body, encoding="utf-8")


def add(root: Path, cat_id: str, label: str = "") -> dict:
    """Legt eine Kategorie an (Eintrag in categories.yaml + Ordner)."""
    cat_id = normalize_id(cat_id)
    if not _ID_RE.match(cat_id or ""):
        raise ValueError(f"Ungültige Kategorie-ID: {cat_id!r}")
    cats = load(root)
    if any(c["id"] == cat_id for c in cats):
        raise ValueError(f"Kategorie existiert bereits: {cat_id}")
    entry = {"id": cat_id, "label": label or cat_id.replace("-", " ").title()}
    cats.append(entry)
    save(root, cats)
    (root / cat_id).mkdir(parents=True, exist_ok=True)
    return entry


def remove(root: Path, cat_id: str, force: bool = False) -> None:
    """Entfernt eine Kategorie (nur wenn der Ordner leer ist, sonst --force)."""
    cats = load(root)
    if not any(c["id"] == cat_id for c in cats):
        raise KeyError(f"Kategorie nicht gefunden: {cat_id}")
    d = root / cat_id
    if d.exists():
        if any(d.iterdir()) and not force:
            raise ValueError(f"Ordner nicht leer: {d} (mit --force löschen)")
        if force:
            shutil.rmtree(d)
    save(root, [c for c in cats if c["id"] != cat_id])


# ------------------------------------------------------- Unterkategorien


def normalize_subcategory(raw: str) -> str:
    """' Shields / Motor ' -> 'Shields/Motor'. Leer bleibt leer; ungültige Namen: ValueError."""
    pieces = [names.clean(piece) for piece in str(raw or "").replace("\\", "/").split("/")]
    pieces = [piece for piece in pieces if piece]
    if len(pieces) > MAX_SUB_DEPTH:
        raise ValueError(f"Unterkategorien gehen höchstens {MAX_SUB_DEPTH} Ebenen tief.")
    for piece in pieces:
        names.check(piece, "Der Name der Unterkategorie")
    return "/".join(pieces)


def subcategory_dir(root: Path, cat_id: str, subcategory: str) -> Path:
    """Ordner einer Unterkategorie in einer Kategorie; angelegt wird hier nichts.

    Gibt es den Ordner schon in anderer Groß-/Kleinschreibung, wird der vorhandene
    genommen. So entstehen unter Linux nicht „Shields“ und „shields“ nebeneinander.
    """
    current = root / cat_id
    sub = normalize_subcategory(subcategory)
    for piece in sub.split("/") if sub else []:
        match = next((d for d in visible_dirs(current) if d.name.lower() == piece.lower()), None)
        if match is None:
            current = current / piece
        elif is_part_dir(match):
            raise ValueError(f"{match.name} ist ein Bauteil und kann keine Unterkategorie sein.")
        else:
            current = match
    return current


def subcategories(root: Path, cat_id: str) -> list[str]:
    """Unterkategorien einer Kategorie: alle Ordner darin, die kein Bauteil sind.

    Pfade relativ zur Kategorie mit '/' als Trenner, z. B. ['Shields', 'Shields/Motor'].
    """
    found: list[str] = []

    def walk(directory: Path, prefix: str, depth: int) -> None:
        # Ohne Rücksicht auf Groß/Klein sortiert, damit die Reihenfolge überall gleich ist.
        for child in sorted(visible_dirs(directory), key=lambda d: d.name.lower()):
            if is_part_dir(child):
                continue
            found.append(prefix + child.name)
            if depth < MAX_SUB_DEPTH:
                walk(child, f"{prefix}{child.name}/", depth + 1)

    walk(root / cat_id, "", 1)
    return found
