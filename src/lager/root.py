"""Erkennung und Validierung des Lager-Roots.

Ein Ordner gilt als Lager-Root, wenn
  - er categories.yaml enthält (starker Marker), oder
  - darunter die Struktur kategorie/<...>/part.yaml existiert (Struktur passt).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_DIR, load_config, resolve_lager_root

CATEGORY_MARKER = "categories.yaml"
IGNORED_PREFIXES = ("_", ".")


@dataclass
class Check:
    path: Path
    valid: bool
    reason: str
    parts: int = 0
    categories: int = 0


def visible_dirs(d: Path) -> list[Path]:
    """Unterordner ohne die ignorierten (Präfix `_` oder `.`), sortiert."""
    try:
        return [
            x for x in sorted(d.iterdir())
            if x.is_dir() and not x.name.startswith(IGNORED_PREFIXES)
        ]
    except OSError:
        return []


def is_part_dir(d: Path) -> bool:
    """Ein Ordner ist ein Bauteil, wenn er eine part.yaml enthält."""
    return d.is_dir() and (d / "part.yaml").is_file()


def count_parts(root: Path) -> int:
    """Zählt Bauteil-Ordner (mit part.yaml) in beliebiger Kategoriaustiefung."""
    total = 0

    def walk(d: Path) -> None:
        nonlocal total
        for child in visible_dirs(d):
            if is_part_dir(child):
                total += 1
            else:
                walk(child)

    walk(root)
    return total


def count_categories(root: Path) -> int:
    return len([d for d in visible_dirs(root) if not is_part_dir(d)])


def check_root(path: Path) -> Check:
    """Prüft, ob `path` eine gültige Lager-Struktur ist."""
    if not path.is_dir():
        return Check(path, False, "existiert nicht oder ist kein Ordner")

    n_cats = count_categories(path)
    n_parts = sum(1 for d in visible_dirs(path) if is_part_dir(d))
    n_parts += sum(
        count_parts(d) for d in visible_dirs(path) if not is_part_dir(d)
    )

    if (path / CATEGORY_MARKER).is_file():
        return Check(path, True, "categories.yaml gefunden (Marker)", n_parts, n_cats)
    if n_parts > 0:
        return Check(
            path,
            True,
            f"Teil-Struktur erkannt ({n_parts} Bauteile mit part.yaml)",
            n_parts,
            n_cats,
        )
    return Check(
        path,
        False,
        "kein categories.yaml und keine Teil-Struktur (kategorie/<teil>/part.yaml)",
        0,
        n_cats,
    )


def create_structure(target: Path) -> None:
    """Legt in `target` ein leeres Lager an: categories.yaml und _vorlage/part.yaml.

    Vorhandene Dateien bleiben unverändert.
    """
    from . import categories as catmod
    from . import parts as partmod

    target.mkdir(parents=True, exist_ok=True)
    if not (target / CATEGORY_MARKER).exists():
        catmod.save(target, [])
    vorlage = target / "_vorlage"
    vorlage.mkdir(exist_ok=True)
    template = vorlage / "part.yaml"
    if not template.exists():
        template.write_text(partmod.HEADER + partmod.empty_doc_yaml(), encoding="utf-8")


def candidate_roots(cfg: dict | None = None) -> list[Path]:
    """Kandidaten für den Lager-Root, in Prioritätsreihenfolge."""
    if cfg is None:
        cfg = load_config()
    cands: list[Path] = []
    explicit = resolve_lager_root(cfg)
    if explicit is not None:
        cands.append(explicit)
    cands.append(PROJECT_DIR / "lager")
    cands.append(Path.home() / "lager")
    seen: set[str] = set()
    out: list[Path] = []
    for c in cands:
        key = str(c).lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def detect(cfg: dict | None = None) -> tuple[Check | None, list[Check]]:
    """Auto-Erkennung: erstes gültiges Kandidat plus Protokoll über alle."""
    checks = [check_root(c) for c in candidate_roots(cfg)]
    found = next((c for c in checks if c.valid), None)
    return found, checks
