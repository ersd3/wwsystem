"""Gemeinsame Test-Daten: ein kleines Lager mit Bauteilen und Dateien."""
from pathlib import Path

import pytest

from lager import categories, parts


def _write(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.fixture()
def lager_voll(tmp_path: Path) -> Path:
    """Lager mit zwei Kategorien, drei Bauteilen (eines in einer Unterkategorie) und Dateien."""
    root = tmp_path / "lager"
    root.mkdir()
    categories.save(root, [])
    categories.add(root, "mosfets", "MOSFETs")
    categories.add(root, "Widerstände", "Widerstände")

    irlz = parts.create_part(
        root,
        "mosfets",
        "IRLZ44N",
        {
            "name": "MOSFET N-Kanal 55 V / 47 A, TO-220",
            "manufacturer": "Infineon",
            "aliases": ["IRLZ44NTR"],
            "tags": ["n-kanal", "to-220"],
            "location": "A-03-2",
            "quantity": 5,
        },
    )
    _write(irlz / "datasheet.pdf", b"%PDF-1.4 test")
    _write(irlz / "3d" / "TO-220.step")
    _write(irlz / "kicad" / "TO-220.kicad_mod")
    _write(irlz / "images" / "foto.JPG")
    _write(irlz / "notiz.txt")
    _write(irlz / ".versteckt")
    _write(irlz / "Thumbs.db")

    parts.create_part(root, "mosfets", "IRF540N", {"name": "MOSFET N-Kanal 100 V", "tags": ["n-kanal"]})
    parts.create_part(root, "widerstaende", "223-0.1W", {"name": "Widerstand 22 kOhm"})

    # Bauteil in einer Unterkategorie, von Hand angelegt (wie im Explorer).
    sub = root / "mosfets" / "p-kanal" / "IRF9540N"
    _write(sub / "part.yaml", "part: IRF9540N\nname: MOSFET P-Kanal 100 V\n".encode("utf-8"))
    _write(sub / "IRF9540N.pdf", b"%PDF-1.4 test")

    # Wird vom Scanner ignoriert.
    _write(root / "_vorlage" / "part.yaml", b"part: BEZEICHNUNG\n")
    return root
