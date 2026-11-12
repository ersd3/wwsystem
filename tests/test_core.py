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
    assert parts.normalize_part_id(" iRLz44n ") == "IRLZ44N"
    assert parts.normalize_part_id("ATMEGA328P-PU") == "ATMEGA328P-PU"


def test_part_new_find(lager):
    categories.add(lager, "mosfets")
    pdir = parts.create_part(
        lager, "mosfets", " Irlz44n ", {"quantity": 5, "tags": ["a"]}
    )
    assert pdir.name == "IRLZ44N"
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
