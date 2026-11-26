"""Tests für die Kern-Logik (Root-Erkennung, Kategorien, Bauteile, Config)."""
from pathlib import Path

import pytest

from lager import categories, parts, root
from lager import config


@pytest.fixture()
def lager(tmp_path: Path) -> Path:
    r = tmp_path / "lager"
    r.mkdir()
    categories.save(r, [])
    return r


# ------------------------------------------------------------- root


def test_check_root_marker(lager):
    c = root.check_root(lager)
    assert c.valid
    assert "categories.yaml" in c.reason


def test_check_root_missing(tmp_path):
    c = root.check_root(tmp_path / "nichts")
    assert not c.valid


def test_check_root_schwaches_signal(lager):
    (lager / "categories.yaml").unlink()
    assert not root.check_root(lager).valid
    (lager / "mosfets" / "IRLZ44N").mkdir(parents=True)
    (lager / "mosfets" / "IRLZ44N" / "part.yaml").write_text(
        "part: IRLZ44N\n", encoding="utf-8"
    )
    c = root.check_root(lager)
    assert c.valid
    assert c.parts == 1


def test_ignoriert_underscore_ordner(lager):
    (lager / "_vorlage" / "part.yaml").parent.mkdir(parents=True)
    (lager / "_vorlage" / "part.yaml").write_text("part: X\n", encoding="utf-8")
    c = root.check_root(lager)
    assert c.valid
    assert c.parts == 0


# ---------------------------------------------------------- categories


def test_category_normalisierung(lager):
    e = categories.add(lager, "Widerstände & Co", "Widerstände")
    assert e["id"] == "widerstaende-co"
    assert e["label"] == "Widerstände"
    assert (lager / "widerstaende-co").is_dir()


def test_category_doppelt_verboten(lager):
    categories.add(lager, "mosfets")
    with pytest.raises(ValueError):
        categories.add(lager, "mosfets")


def test_category_remove_nicht_leer(lager):
    categories.add(lager, "mosfets")
    (lager / "mosfets" / "etwas.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        categories.remove(lager, "mosfets")
    categories.remove(lager, "mosfets", force=True)
    assert not (lager / "mosfets").exists()
    assert categories.load(lager) == []


# --------------------------------------------------------------- parts


def test_part_id_normalisierung():
    # Die Schreibweise bleibt; nur überflüssige Leerzeichen verschwinden.
    assert parts.normalize_part_id(" iRLz44n ") == "iRLz44n"
    assert parts.normalize_part_id("  Arduino   Mega 2560 ") == "Arduino Mega 2560"
    assert parts.normalize_part_id("ATMEGA328P-PU") == "ATMEGA328P-PU"


def test_part_new_find(lager):
    categories.add(lager, "mosfets")
    pdir = parts.create_part(
        lager, "mosfets", " Irlz44n ", {"quantity": 5, "tags": ["a"]}
    )
    assert pdir.name == "Irlz44n"
    found = parts.find_part(lager, "irlz44n")
    assert found is not None
    _, data = found
    assert data["quantity"] == 5


def test_part_new_fehlende_kategorie(lager):
    with pytest.raises(ValueError):
        parts.create_part(lager, "keine", "X1", {})


def test_part_doppelt_verboten(lager):
    categories.add(lager, "mosfets")
    parts.create_part(lager, "mosfets", "IRLZ44N", {})
    with pytest.raises(ValueError):
        parts.create_part(lager, "mosfets", "irlz44n", {})


# --------------------------------------------------------------- config


def test_config_roundtrip(tmp_path):
    cp = tmp_path / "config.yaml"
    cfg = config.load_config(cp)
    assert cfg["lager_root"] == ""
    config.set_lager_root(str(tmp_path / "lager"), cp)
    assert config.load_config(cp)["lager_root"] == "lager"
    # relative Auflösung relativ zur config.yaml
    resolved = config.resolve_lager_root(config.load_config(cp), cp)
    assert resolved == tmp_path / "lager"


EXAMPLE = config.PROJECT_DIR / config.EXAMPLE_NAME


def test_vorlage_passt_zu_den_standardwerten():
    cfg = config.load_config(EXAMPLE)
    assert cfg["lager_root"] == "lager"  # das Beispiel-Lager im Projekt
    assert cfg["server"] == config.DEFAULTS["server"]
    assert cfg["write_token"] == ""


def test_config_yaml_steht_nicht_in_git():
    ignored = (config.PROJECT_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "config.yaml" in ignored


def test_fehlende_config_wird_aus_der_vorlage_angelegt(tmp_path):
    (tmp_path / config.EXAMPLE_NAME).write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    cp = tmp_path / "config.yaml"
    assert config.load_config(cp)["lager_root"] == ""  # ohne Datei: Standardwerte

    config.set_lager_root(str(tmp_path / "mein lager"), cp)
    text = cp.read_text(encoding="utf-8")
    assert text.startswith("# Konfiguration")  # die Kommentare der Vorlage sind da
    assert "file_kinds" in text
    assert config.load_config(cp)["lager_root"] == "mein lager"

    other = tmp_path / "zweiter" / "config.yaml"
    other.parent.mkdir()
    (other.parent / config.EXAMPLE_NAME).write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    config.set_public_url("http://lager.fritz.box:8080", other)
    assert "# Adresse in den QR-Etiketten" in other.read_text(encoding="utf-8")
    assert config.load_config(other)["server"]["public_url"] == "http://lager.fritz.box:8080"
    # Eine vorhandene config.yaml wird nie durch die Vorlage ersetzt.
    config.ensure_config_file(cp)
    assert config.load_config(cp)["lager_root"] == "mein lager"
