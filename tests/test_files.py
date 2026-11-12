"""Tests für das Aufnehmen von Dateien in Bauteil-Ordner und für den Pfad in config.yaml."""
import io
from pathlib import Path

import pytest

from lager import config, files, parts, root


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("datasheet.pdf", "datasheet.pdf"),
        ("C:\\Users\\x\\Downloads\\IRLZ44N.pdf", "IRLZ44N.pdf"),
        ("../../etc/passwd", "passwd"),
        ("  Datenblatt Größe.pdf  ", "Datenblatt Größe.pdf"),
        ('a<b>:"c|d?e*.pdf', "abcde.pdf"),
        (".versteckt.pdf", "versteckt.pdf"),
        ("name.pdf. ", "name.pdf"),
        ("NUL.txt", "datei-NUL.txt"),
    ],
)
def test_safe_filename(raw, expected):
    assert files.safe_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "...", "/", "part.yaml", "sub/PART.YAML"])
def test_safe_filename_lehnt_ab(raw):
    with pytest.raises(ValueError):
        files.safe_filename(raw)


def _part(lager_voll: Path) -> Path:
    return lager_voll / "mosfets" / "IRF540N"


def test_add_file_sortiert_nach_art(lager_voll):
    part_dir = _part(lager_voll)
    stored = {
        name: files.add_file(part_dir, name, io.BytesIO(b"x")).relative_to(part_dir).as_posix()
        for name in ("irf540n.pdf", "TO-220.step", "TO-220.kicad_mod", "foto.PNG", "notiz.txt")
    }
    assert stored == {
        "irf540n.pdf": "irf540n.pdf",
        "TO-220.step": "3d/TO-220.step",
        "TO-220.kicad_mod": "kicad/TO-220.kicad_mod",
        "foto.PNG": "images/foto.PNG",
        "notiz.txt": "notiz.txt",
    }


def test_add_file_ueberschreibt_nichts(lager_voll):
    part_dir = _part(lager_voll)
    first = files.add_file(part_dir, "ds.pdf", io.BytesIO(b"eins"))
    second = files.add_file(part_dir, "ds.pdf", io.BytesIO(b"zwei"))
    third = files.add_file(part_dir, "ds.pdf", io.BytesIO(b"drei"))
    assert [p.name for p in (first, second, third)] == ["ds.pdf", "ds-2.pdf", "ds-3.pdf"]
    assert first.read_bytes() == b"eins"
    assert third.read_bytes() == b"drei"


def test_add_file_groessengrenze_hinterlaesst_nichts(lager_voll):
    part_dir = _part(lager_voll)
    with pytest.raises(ValueError, match="größer"):
        files.add_file(part_dir, "gross.pdf", io.BytesIO(b"x" * 2048), max_bytes=1024)
    assert not (part_dir / "gross.pdf").exists()


def test_add_file_leere_datei(lager_voll):
    part_dir = _part(lager_voll)
    with pytest.raises(ValueError, match="leer"):
        files.add_file(part_dir, "leer.pdf", io.BytesIO(b""))
    assert not (part_dir / "leer.pdf").exists()


def test_add_file_eigene_dateiarten(lager_voll):
    part_dir = _part(lager_voll)
    cfg = {"file_kinds": {"cad3d": ["f3d"]}}
    target = files.add_file(part_dir, "gehaeuse.f3d", io.BytesIO(b"x"), cfg)
    assert target.relative_to(part_dir).as_posix() == "3d/gehaeuse.f3d"


def test_add_file_from_path_kopieren_und_verschieben(lager_voll, tmp_path):
    part_dir = _part(lager_voll)
    source = tmp_path / "quelle.pdf"
    source.write_bytes(b"%PDF")
    files.add_file_from_path(part_dir, source)
    assert source.exists()
    moved = files.add_file_from_path(part_dir, source, move=True)
    assert not source.exists()
    assert moved.name == "quelle-2.pdf"
    with pytest.raises(ValueError, match="nicht gefunden"):
        files.add_file_from_path(part_dir, source)


# ------------------------------------------------------ Bauteile anlegen


def test_bezeichnung_ist_im_ganzen_lager_eindeutig(lager_voll):
    with pytest.raises(ValueError, match="existiert bereits"):
        parts.create_part(lager_voll, "widerstaende", "irlz44n", {})


def test_kategorie_darf_nicht_aus_dem_lager_fuehren(lager_voll):
    (lager_voll.parent / "fremd").mkdir()
    for category in ("../fremd", "", "  ", str(lager_voll.parent / "fremd")):
        with pytest.raises(ValueError):
            parts.create_part(lager_voll, category, "X1", {})
    assert not (lager_voll.parent / "fremd" / "X1").exists()


def test_vorhandener_ordner_ohne_part_yaml_wird_uebernommen(lager_voll):
    folder = lager_voll / "mosfets" / "BS170"
    folder.mkdir()
    (folder / "bs170.pdf").write_bytes(b"%PDF")
    assert parts.create_part(lager_voll, "mosfets", "bs170", {}) == folder
    assert (folder / "part.yaml").is_file()
    assert (folder / "bs170.pdf").is_file()


def test_create_structure_ist_wiederholbar(tmp_path):
    target = tmp_path / "neu" / "lager"
    root.create_structure(target)
    (target / "categories.yaml").write_text("categories:\n- id: x\n  label: X\n", encoding="utf-8")
    root.create_structure(target)
    assert "id: x" in (target / "categories.yaml").read_text(encoding="utf-8")
    assert (target / "_vorlage" / "part.yaml").is_file()
    assert root.check_root(target).valid


# ------------------------------------------------- Pfad in config.yaml


def test_set_lager_root_erhaelt_kommentare(tmp_path):
    cp = tmp_path / "config.yaml"
    cp.write_text(
        '# Kopfkommentar\nlager_root: "lager"\n\nserver:\n  port: 9000  # eigener Port\n'
        '# file_kinds:\n#   datasheet: [pdf]\nwrite_token: ""\n',
        encoding="utf-8",
    )
    outside = tmp_path.parent / "ganz woanders" / "Lager"
    config.set_lager_root(str(outside), cp)
    text = cp.read_text(encoding="utf-8")
    assert "# Kopfkommentar" in text
    assert "port: 9000  # eigener Port" in text
    assert "# file_kinds:" in text
    cfg = config.load_config(cp)
    assert config.resolve_lager_root(cfg, cp) == outside.resolve()
    assert cfg["server"]["port"] == 9000

    config.set_lager_root(str(tmp_path / "lager"), cp)
    assert config.load_config(cp)["lager_root"] == "lager"
    assert "# Kopfkommentar" in cp.read_text(encoding="utf-8")


def test_set_lager_root_ohne_eintrag_in_der_datei(tmp_path):
    cp = tmp_path / "config.yaml"
    cp.write_text("server:\n  port: 9000\n", encoding="utf-8")
    config.set_lager_root(str(tmp_path / "lager"), cp)
    cfg = config.load_config(cp)
    assert cfg["lager_root"] == "lager"
    assert cfg["server"]["port"] == 9000
