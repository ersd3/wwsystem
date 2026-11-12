"""Kategorien: categories.yaml lesen/schreiben, anlegen, entfernen.

Kategorien sind reine Daten — es gibt keine hardcodierte Liste.
Anlegen funktioniert per CLI (und damit auch per AI-Agent).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

HEADER = """# Kategorien des Lagers.
# id    = Ordnername (normalisiert: a-z, 0-9, '-')
# label = Anzeigename (darf Umlaute enthalten)
# Reihenfolge = Anzeige-Reihenfolge.
# Anlegen: lager category add <id> [--label "Anzeigename"]
"""

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
