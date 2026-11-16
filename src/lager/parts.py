"""Bauteile: part.yaml anlegen, lesen, ändern; Bauteile umbenennen, verschieben, löschen."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from . import categories as catmod
from . import names, trash

HEADER = """# part.yaml — Metadaten eines Bauteils
# part       Bezeichnung (= Ordnername; Groß-/Kleinschreibung und Leerzeichen erlaubt)
# name       Beschreibung (menschlich)
# aliases    weitere Suchbegriffe (Bestell-, Hersteller-, Alt-Bezeichnungen)
# quantity   aktuelle Lagermenge
# unit       Mengeneinheit
# location   Lagerfach (frei wählbar, z. B. "A-03-2")
# tags       freie Schlagwörter
# Kategorie und Unterkategorie kommen aus dem Pfad — nicht hier speichern
"""


def normalize_part_id(raw: str) -> str:
    """' Arduino   Mega ' -> 'Arduino Mega'.

    Die Schreibweise bleibt, wie sie eingegeben wurde. Nur Leerzeichen am Rand
    und doppelte Leerzeichen verschwinden.
    """
    return names.clean(raw)


def validate_part_id(part_id: str) -> None:
    """Prüft eine Bezeichnung als Ordnername (ValueError mit Grund, wenn sie nicht geht)."""
    names.check(part_id, "Die Bezeichnung")


def part_dir(root: Path, category_id: str, part_id: str) -> Path:
    return root / category_id / part_id


def read_part(root: Path, category_id: str, part_id: str) -> dict:
    p = part_dir(root, category_id, part_id) / "part.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Teil nicht gefunden: {category_id}/{part_id}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def find_part_dir(root: Path, raw_id: str) -> Path | None:
    """Ordner eines Teils über seine Bezeichnung (Groß-/Kleinschreibung egal)."""
    target = normalize_part_id(raw_id).lower()
    if not target:
        return None
    for py in sorted(root.rglob("part.yaml")):
        rel = py.relative_to(root)
        if any(piece.startswith(names.IGNORED_PREFIXES) for piece in rel.parts):
            continue
        if py.parent.name.lower() == target:
            return py.parent
    return None


def find_part(root: Path, raw_id: str) -> tuple[Path, dict] | None:
    """Sucht ein Teil über seine Bezeichnung und liest seine part.yaml."""
    pdir = find_part_dir(root, raw_id)
    if pdir is None:
        return None
    data = yaml.safe_load((pdir / "part.yaml").read_text(encoding="utf-8-sig")) or {}
    return pdir, data


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


def _category_dir(root: Path, category_id: str) -> Path:
    """Ordner einer vorhandenen Kategorie (ValueError, wenn es sie nicht gibt)."""
    category_path = Path(category_id)
    if not category_id.strip() or category_path.is_absolute() or ".." in category_path.parts:
        raise ValueError(f"Ungültige Kategorie: {category_id!r}")
    cat_dir = root / category_path
    if not cat_dir.is_dir():
        raise ValueError(
            f"Kategorie existiert nicht: {category_id} "
            f"(erst: lager category add {category_id})"
        )
    return cat_dir


def _existing_category(root: Path, category: str) -> Path:
    """Ordner einer Kategorie mit seinem wirklichen Namen (Groß-/Kleinschreibung egal)."""
    wanted = category.strip()
    if not wanted or Path(wanted).name != wanted or wanted.startswith(names.IGNORED_PREFIXES):
        raise ValueError(f"Ungültige Kategorie: {category!r}")
    for candidate in sorted(root.iterdir()) if root.is_dir() else []:
        if candidate.name.lower() == wanted.lower() and candidate.is_dir():
            if (candidate / "part.yaml").is_file():
                break
            return candidate
    raise ValueError(f"Kategorie existiert nicht: {category} (erst: lager category add {category})")


def _write_doc(path: Path, doc: dict) -> None:
    path.write_text(
        HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_doc(pdir: Path) -> dict:
    """Liest die part.yaml eines Bauteils zum Ändern (ValueError, wenn sie nicht lesbar ist)."""
    try:
        doc = yaml.safe_load((pdir / "part.yaml").read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ValueError(f"part.yaml von {pdir.name} ist nicht lesbar: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"part.yaml von {pdir.name} enthält keine Felder.")
    return doc


def create_part(
    root: Path, category_id: str, raw_id: str, data: dict, subcategory: str = ""
) -> Path:
    """Legt <root>/<kategorie>/[<unterkategorie>/]<Bezeichnung>/part.yaml an.

    Gibt den Ordner des Bauteils zurück. Eine Unterkategorie, die es noch nicht gibt,
    wird als Ordner angelegt.
    """
    part_id = normalize_part_id(raw_id)
    validate_part_id(part_id)
    _category_dir(root, category_id)
    parent = catmod.subcategory_dir(root, category_id, subcategory)
    # Die Bezeichnung ist im ganzen Lager eindeutig (Adresse /p/<Bezeichnung>, QR-Etikett).
    existing = find_part_dir(root, part_id)
    if existing is not None:
        raise ValueError(f"Teil existiert bereits: {existing}")
    pdir = parent / part_id
    # Ein schon vorhandener Ordner ohne part.yaml (z. B. mit PDFs) wird übernommen.
    pdir.mkdir(parents=True, exist_ok=True)
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
    _write_doc(pdir / "part.yaml", doc)
    return pdir


# Felder, die update_part ändert. Die Bezeichnung (`part`) ist der Ordnername;
# sie ändert move_part, zusammen mit Kategorie und Unterkategorie.
TEXT_FIELDS = ("name", "manufacturer", "unit", "location", "notes")
LIST_FIELDS = ("aliases", "tags")
EDITABLE_FIELDS = TEXT_FIELDS + LIST_FIELDS + ("quantity",)


def update_part(root: Path, raw_id: str, changes: dict) -> Path:
    """Ändert Felder in der part.yaml eines Bauteils und gibt seinen Ordner zurück.

    Nur die in `changes` genannten Felder werden gesetzt; alle anderen Einträge der
    Datei bleiben erhalten, auch unbekannte. Die Kopfkommentare werden neu geschrieben.
    """
    unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
    if unknown:
        raise ValueError(f"Diese Felder lassen sich nicht ändern: {', '.join(unknown)}")
    pdir = find_part_dir(root, raw_id)
    if pdir is None:
        raise ValueError(f"Teil nicht gefunden: {raw_id}")
    doc = _read_doc(pdir)

    for key, value in changes.items():
        if key == "quantity":
            try:
                doc[key] = int(value)
            except (TypeError, ValueError):
                raise ValueError("Die Menge muss eine ganze Zahl sein.") from None
        elif key in LIST_FIELDS:
            items = [str(item).strip() for item in (value or [])]
            doc[key] = list(dict.fromkeys(item for item in items if item))
        else:
            doc[key] = "" if value is None else str(value).strip()
    doc["part"] = pdir.name

    _write_doc(pdir / "part.yaml", doc)
    return pdir


def location_of(root: Path, pdir: Path) -> tuple[str, str]:
    """(Kategorie, Unterkategorie) eines Bauteil-Ordners, aus seinem Pfad."""
    rel = pdir.relative_to(root)
    return rel.parts[0], "/".join(rel.parts[1:-1])


def move_part(
    root: Path,
    raw_id: str,
    new_id: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
) -> Path:
    """Benennt ein Bauteil um und/oder verschiebt es; gibt den neuen Ordner zurück.

    `None` heißt jeweils: bleibt, wie es ist. Wechselt nur die Kategorie, landet das
    Bauteil direkt in der neuen Kategorie (die alte Unterkategorie gehört nicht dazu).
    Nach einem Umbenennen steht die alte Bezeichnung in den Aliasen. So wird das
    Bauteil weiter unter ihr gefunden, auch über schon gedruckte QR-Etiketten.
    """
    pdir = find_part_dir(root, raw_id)
    if pdir is None:
        raise ValueError(f"Teil nicht gefunden: {raw_id}")
    old_id = pdir.name
    old_category, old_sub = location_of(root, pdir)

    part_id = old_id if new_id is None else normalize_part_id(new_id)
    validate_part_id(part_id)
    renamed = part_id.lower() != old_id.lower()
    if renamed:
        other = find_part_dir(root, part_id)
        if other is not None:
            raise ValueError(f"Teil existiert bereits: {other}")

    if category is None and subcategory is None:
        parent = pdir.parent  # der Ort bleibt, auch wenn er von Hand tiefer verschachtelt wurde
    else:
        cat_dir = _existing_category(root, old_category if category is None else category)
        if subcategory is None:
            subcategory = old_sub if cat_dir.name.lower() == old_category.lower() else ""
        parent = catmod.subcategory_dir(root, cat_dir.name, subcategory)
    target = parent / part_id
    # Als Text vergleichen: Unter Windows gelten Pfade, die sich nur in Groß-/Klein-
    # schreibung unterscheiden, als gleich; genau das soll hier aber eine Änderung sein.
    if str(target) == str(pdir):
        return pdir
    try:
        parent.relative_to(pdir)
    except ValueError:
        pass
    else:
        raise ValueError("Ein Bauteil lässt sich nicht in seinen eigenen Ordner verschieben.")
    # Derselbe Ordner in anderer Groß-/Kleinschreibung ist kein Hindernis (reines Umbenennen).
    if target.exists() and not os.path.samefile(target, pdir):
        raise ValueError(f"Am Ziel gibt es schon einen Ordner: {target}")

    doc = _read_doc(pdir)  # vor dem Verschieben: Ist die Datei kaputt, bleibt alles, wie es ist
    try:
        parent.mkdir(parents=True, exist_ok=True)
        pdir.rename(target)
    except OSError as e:
        raise ValueError(
            f"Der Ordner von {old_id} lässt sich nicht verschieben. Ist eine Datei daraus "
            f"geöffnet, zum Beispiel ein Datenblatt? ({e})"
        ) from e

    doc["part"] = part_id
    aliases = [str(item).strip() for item in (doc.get("aliases") or [])]
    aliases = [item for item in aliases if item and item.lower() != part_id.lower()]
    if renamed and old_id.lower() not in (item.lower() for item in aliases):
        aliases.append(old_id)
    doc["aliases"] = aliases
    _write_doc(target / "part.yaml", doc)
    return target


def delete_part(root: Path, raw_id: str) -> Path:
    """Verschiebt den Ordner eines Bauteils in den Papierkorb des Lagers.

    Gibt den Ort im Papierkorb zurück. Endgültig gelöscht wird nichts.
    """
    pdir = find_part_dir(root, raw_id)
    if pdir is None:
        raise ValueError(f"Teil nicht gefunden: {raw_id}")
    try:
        return trash.move_to_trash(root, pdir)
    except OSError as e:
        raise ValueError(
            f"Der Ordner von {pdir.name} lässt sich nicht verschieben. Ist eine Datei daraus "
            f"geöffnet, zum Beispiel ein Datenblatt? ({e})"
        ) from e
