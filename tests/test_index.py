"""Tests für den SQLite-Index (Phase 0.2) und die Suche darauf."""
import sqlite3
from pathlib import Path

import pytest

from lager import db, indexer, search


def _conn(root: Path) -> sqlite3.Connection:
    return db.connect(root, create=False)


# ------------------------------------------------------------- Aufbau


def test_rebuild_zaehlt_teile_und_dateien(lager_voll):
    result = indexer.rebuild(lager_voll)
    assert result["kategorien"] == 2
    assert result["teile"] == 4
    assert result["dateien_nach_art"] == {
        "cad3d": 1, "datasheet": 2, "image": 1, "kicad": 1, "other": 1,
    }
    assert result["dateien"] == 6
    assert result["warnungen"] == []
    assert db.db_path(lager_voll).is_file()


def test_rebuild_ist_wiederholbar(lager_voll):
    first = indexer.rebuild(lager_voll)
    second = indexer.rebuild(lager_voll)
    for key in ("kategorien", "teile", "dateien", "dateien_nach_art", "warnungen"):
        assert first[key] == second[key]
    conn = _conn(lager_voll)
    try:
        assert conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == 4
    finally:
        conn.close()


def test_rebuild_folgt_den_ordnern(lager_voll):
    indexer.rebuild(lager_voll)
    (lager_voll / "mosfets" / "IRLZ44N" / "datasheet.pdf").unlink()
    (lager_voll / "mosfets" / "IRF540N" / "IRF540N.pdf").write_bytes(b"%PDF")
    result = indexer.rebuild(lager_voll)
    conn = _conn(lager_voll)
    try:
        assert [f["path"] for f in search.get_part(conn, "IRF540N")["files"]] == ["IRF540N.pdf"]
        kinds = {f["kind"] for f in search.get_part(conn, "IRLZ44N")["files"]}
        assert "datasheet" not in kinds
    finally:
        conn.close()
    assert result["dateien_nach_art"]["datasheet"] == 2


def test_versteckte_dateien_und_vorlage_fehlen(lager_voll):
    indexer.rebuild(lager_voll)
    conn = _conn(lager_voll)
    try:
        names = {row[0] for row in conn.execute("SELECT rel_path FROM files")}
        parts = {row[0] for row in conn.execute("SELECT part FROM parts")}
    finally:
        conn.close()
    assert ".versteckt" not in names
    assert "Thumbs.db" not in names
    assert "part.yaml" not in names
    assert "BEZEICHNUNG" not in parts


def test_unterkategorie_und_pfad(lager_voll):
    indexer.rebuild(lager_voll)
    conn = _conn(lager_voll)
    try:
        part = search.get_part(conn, "irf9540n")
    finally:
        conn.close()
    assert part["category"] == "mosfets"
    assert part["subcategory"] == "p-kanal"
    assert part["path"] == "mosfets/p-kanal/IRF9540N"


def test_index_ist_sprachneutral_lesbar(lager_voll):
    """Die Datei muss ohne dieses Programm mit reinem SQL lesbar sein (D6)."""
    indexer.rebuild(lager_voll)
    conn = sqlite3.connect(db.db_path(lager_voll))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        row = conn.execute(
            "SELECT p.part, p.quantity, c.label FROM parts p "
            "JOIN categories c ON c.id = p.category_id WHERE p.part = 'IRLZ44N'"
        ).fetchone()
        assert row == ("IRLZ44N", 5, "MOSFETs")
        aliases = conn.execute(
            "SELECT alias FROM part_aliases a JOIN parts p ON p.id = a.part_id "
            "WHERE p.part = 'IRLZ44N'"
        ).fetchall()
        assert aliases == [("IRLZ44NTR",)]
        mtime, size = conn.execute(
            "SELECT mtime, size FROM files WHERE rel_path = 'datasheet.pdf'"
        ).fetchone()
        assert len(mtime) == 20 and mtime[10] == "T" and mtime.endswith("Z")
        assert size == len(b"%PDF-1.4 test")
        built_at = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()[0]
        assert built_at.endswith("Z")
    finally:
        conn.close()


def test_warnungen_statt_abbruch(lager_voll):
    kaputt = lager_voll / "mosfets" / "KAPUTT"
    kaputt.mkdir()
    (kaputt / "part.yaml").write_text("name: [unvollständig\n", encoding="utf-8")
    liste = lager_voll / "mosfets" / "LISTE"
    liste.mkdir()
    (liste / "part.yaml").write_text("- nur\n- eine liste\n", encoding="utf-8")
    ohne_kat = lager_voll / "LOSE"
    ohne_kat.mkdir()
    (ohne_kat / "part.yaml").write_text("part: LOSE\n", encoding="utf-8")
    neu = lager_voll / "dioden" / "1N4148"
    neu.mkdir(parents=True)
    (neu / "part.yaml").write_text("part: 1N4148\nquantity: viele\n", encoding="utf-8")

    result = indexer.rebuild(lager_voll)
    warned = {w["pfad"] for w in result["warnungen"]}
    assert warned == {
        "mosfets/KAPUTT/part.yaml",
        "mosfets/LISTE/part.yaml",
        "LOSE",
        "dioden",
        "dioden/1N4148/part.yaml",
    }
    assert result["teile"] == 5  # die vier guten plus 1N4148
    conn = _conn(lager_voll)
    try:
        cats = {c["id"]: c for c in search.list_categories(conn)}
        assert cats["dioden"]["listed"] is False
        assert cats["dioden"]["parts"] == 1
        assert search.get_part(conn, "1N4148")["quantity"] == 0
    finally:
        conn.close()


def test_doppelte_bezeichnung_wird_gemeldet(lager_voll):
    doppelt = lager_voll / "widerstaende" / "IRLZ44N"
    doppelt.mkdir()
    (doppelt / "part.yaml").write_text("part: IRLZ44N\n", encoding="utf-8")
    result = indexer.rebuild(lager_voll)
    assert any("mehrfach" in w["grund"] for w in result["warnungen"])
    assert result["teile"] == 5


def test_part_yaml_mit_bom(lager_voll):
    bom = lager_voll / "mosfets" / "BS170"
    bom.mkdir()
    (bom / "part.yaml").write_bytes("﻿part: BS170\nname: Kleinsignal-MOSFET\n".encode("utf-8"))
    result = indexer.rebuild(lager_voll)
    assert result["warnungen"] == []
    conn = _conn(lager_voll)
    try:
        assert search.get_part(conn, "BS170")["name"] == "Kleinsignal-MOSFET"
    finally:
        conn.close()


def test_eigene_dateiarten_aus_config(lager_voll):
    result = indexer.rebuild(lager_voll, {"file_kinds": {"text": ["txt"], "datasheet": [".PDF"]}})
    assert result["dateien_nach_art"]["text"] == 1
    assert result["dateien_nach_art"]["datasheet"] == 2
    assert "kicad" not in result["dateien_nach_art"]


def test_status_ohne_und_mit_index(lager_voll):
    assert indexer.status(lager_voll) == {"vorhanden": False, "db": str(db.db_path(lager_voll))}
    assert not db.db_path(lager_voll).exists()  # status legt nichts an
    indexer.rebuild(lager_voll)
    status = indexer.status(lager_voll)
    assert status["vorhanden"] is True
    assert status["schema_version"] == 1
    assert status["teile"] == 4
    assert status["aufgebaut_am"].endswith("Z")


def test_fremde_schema_version_wird_abgelehnt(lager_voll):
    indexer.rebuild(lager_voll)
    conn = sqlite3.connect(db.db_path(lager_voll))
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(db.IndexDbError):
        db.connect(lager_voll)


def test_kaputte_categories_yaml_gibt_klare_meldung(lager_voll):
    (lager_voll / "categories.yaml").write_text("categories: [kaputt\n", encoding="utf-8")
    with pytest.raises(db.IndexDbError, match="categories.yaml"):
        indexer.rebuild(lager_voll)


# -------------------------------------------------------------- Suche


@pytest.fixture()
def conn(lager_voll):
    indexer.rebuild(lager_voll)
    connection = _conn(lager_voll)
    yield connection
    connection.close()


def _found(conn, query, **kwargs):
    return [p["part"] for p in search.search(conn, query, **kwargs)]


def test_suche_findet_bezeichnung_ohne_grossschreibung(conn):
    assert _found(conn, "irlz44n") == ["IRLZ44N"]
    assert _found(conn, "  IRLZ44N ") == ["IRLZ44N"]


def test_suche_ueber_alias_tag_hersteller_fach(conn):
    assert _found(conn, "irlz44ntr") == ["IRLZ44N"]
    assert _found(conn, "to-220") == ["IRLZ44N"]
    assert _found(conn, "infineon") == ["IRLZ44N"]
    assert _found(conn, "a-03") == ["IRLZ44N"]


def test_suche_teilwort_und_mehrere_begriffe(conn):
    assert _found(conn, "44n") == ["IRLZ44N"]
    assert _found(conn, "mosfet 100") == ["IRF540N", "IRF9540N"]
    assert _found(conn, "mosfet gibtsnicht") == []


def test_suche_mit_umlauten(conn):
    assert _found(conn, "widerstände") == ["223-0.1W"]
    assert _found(conn, "WIDERSTÄNDE") == ["223-0.1W"]
    assert _found(conn, "widerstaende") == ["223-0.1W"]


def test_suche_leer_liefert_alle_und_limit(conn):
    assert _found(conn, "") == ["223-0.1W", "IRF540N", "IRF9540N", "IRLZ44N"]
    assert len(_found(conn, "", limit=2)) == 2


def test_suche_nach_kategorie(conn):
    assert _found(conn, "", category="widerstaende") == ["223-0.1W"]
    assert _found(conn, "n-kanal", category="mosfets") == ["IRF540N", "IRLZ44N"]


def test_suche_genaue_bezeichnung_zuerst(conn):
    # "irf" passt auf mehrere; der Bezeichnungs-Anfang zählt vor Treffern im Text.
    assert _found(conn, "irf")[:2] == ["IRF540N", "IRF9540N"]
    assert _found(conn, "irf9540n")[0] == "IRF9540N"


def test_suche_platzhalter_sind_normale_zeichen(conn):
    assert _found(conn, "%") == []
    # Als Platzhalter würde "_" alle vier Bauteile treffen. Als normales Zeichen
    # passt es nur auf den Dateinamen TO-220.kicad_mod.
    assert _found(conn, "_") == ["IRLZ44N"]
    assert _found(conn, "0.1w") == ["223-0.1W"]


def test_suche_in_dateinamen(conn):
    assert _found(conn, "irf9540n.pdf") == ["IRF9540N"]
    assert _found(conn, "foto") == ["IRLZ44N"]
    assert _found(conn, "kicad_mod") == ["IRLZ44N"]
    assert _found(conn, "pdf") == ["IRF9540N", "IRLZ44N"]
    assert _found(conn, "mosfet pdf") == ["IRF9540N", "IRLZ44N"]


def test_index_einer_anderen_version_wird_neu_aufgebaut(lager_voll):
    indexer.rebuild(lager_voll)
    raw = sqlite3.connect(db.db_path(lager_voll))
    raw.execute("UPDATE meta SET value = 'lager 0.0.1' WHERE key = 'generator'")
    raw.execute("UPDATE parts SET search_text = ''")
    raw.commit()
    raw.close()

    indexer.ensure_index(lager_voll)
    assert indexer.status(lager_voll)["erzeugt_von"] == indexer.GENERATOR
    connection = _conn(lager_voll)
    try:
        assert _found(connection, "irlz44n") == ["IRLZ44N"]
    finally:
        connection.close()

    built_at = indexer.status(lager_voll)["aufgebaut_am"]
    indexer.ensure_index(lager_voll)  # gleiche Version: kein weiterer Aufbau nötig
    assert indexer.status(lager_voll)["aufgebaut_am"] == built_at


def test_dateien_datenblatt_zuerst(conn):
    files = search.get_part(conn, "IRLZ44N")["files"]
    assert files[0] == {
        "path": "datasheet.pdf",
        "kind": "datasheet",
        "ext": "pdf",
        "size": len(b"%PDF-1.4 test"),
        "mtime": files[0]["mtime"],
    }
    assert [f["path"] for f in files[1:]] == [
        "3d/TO-220.step", "images/foto.JPG", "kicad/TO-220.kicad_mod", "notiz.txt",
    ]
    assert {f["path"]: f["kind"] for f in files}["images/foto.JPG"] == "image"


def test_get_part_unbekannt(conn):
    assert search.get_part(conn, "GIBTSNICHT") is None


def test_find_file_nur_indizierte_dateien(conn):
    assert search.find_file(conn, "mosfets/IRLZ44N/datasheet.pdf")["kind"] == "datasheet"
    assert search.find_file(conn, "mosfets/IRLZ44N/part.yaml") is None
    assert search.find_file(conn, "mosfets/IRLZ44N/../../categories.yaml") is None
    assert search.find_file(conn, "categories.yaml") is None
