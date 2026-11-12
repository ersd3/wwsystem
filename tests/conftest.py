"""Gemeinsame Test-Daten: ein kleines Lager mit Bauteilen und Dateien, dazu Test-Browser."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lager import categories, parts
from lager.server.app import create_app

# Absender der Anfragen: der PC, auf dem der Server läuft, und ein anderes Gerät im WLAN.
LOCAL = ("127.0.0.1", 50000)
PHONE = ("192.168.1.77", 50000)


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    """Eigene config.yaml je Test, damit nie die echte Projekt-Konfiguration geändert wird."""
    path = tmp_path / "config.yaml"
    path.write_text('# Test-Konfiguration\nlager_root: "lager"\nwrite_token: ""\n', encoding="utf-8")
    return path


@pytest.fixture()
def app(lager_voll: Path, config_path: Path):
    return create_app(lager_voll, {"write_token": ""}, config_path)


@pytest.fixture()
def client(app) -> TestClient:
    """Browser auf dem PC, auf dem der Server läuft."""
    return TestClient(app, client=LOCAL)


@pytest.fixture()
def phone(app) -> TestClient:
    """Browser auf einem anderen Gerät im WLAN."""
    return TestClient(app, client=PHONE)


@pytest.fixture()
def geschuetzt(lager_voll: Path, config_path: Path) -> TestClient:
    """Server mit gesetztem write_token "geheim"."""
    return TestClient(create_app(lager_voll, {"write_token": "geheim"}, config_path), client=LOCAL)


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
