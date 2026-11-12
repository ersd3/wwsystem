"""Tests für die CLI: UTF-8-Ausgabe, Index- und Suchbefehle."""
import io
import json
import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from lager import cli, db


def test_force_utf8_output(monkeypatch):
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    cli.force_utf8_output()
    sys.stdout.write("Widerstände")
    sys.stdout.flush()
    assert raw.getvalue() == "Widerstände".encode("utf-8")


def test_umgeleitete_ausgabe_ist_utf8():
    """Echter Aufruf mit umgeleiteter Ausgabe, ohne UTF-8-Hilfen aus der Umgebung."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONUTF8", "PYTHONIOENCODING")
    }
    env["COLUMNS"] = "200"
    result = subprocess.run(
        [sys.executable, "-m", "lager", "--help"],
        capture_output=True,
        env=env,
        check=True,
    )
    text = result.stdout.decode("utf-8")  # wirft bei falscher Kodierung
    assert "unterstützen" in text


# ------------------------------------------------- Index und Suche


@pytest.fixture()
def run(lager_voll, monkeypatch):
    """Führt CLI-Befehle gegen das Test-Lager aus (statt gegen config.yaml)."""
    monkeypatch.setattr(cli, "_require_root", lambda: lager_voll)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    runner = CliRunner()

    def _run(*args):
        return runner.invoke(cli.app, list(args))

    return _run


def test_index_status_und_rebuild(run, lager_voll):
    before = json.loads(run("index", "status", "--json").stdout)
    assert before["vorhanden"] is False

    result = run("index", "rebuild", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["teile"] == 4
    assert data["dateien_nach_art"]["datasheet"] == 2

    after = json.loads(run("index", "status", "--json").stdout)
    assert after["vorhanden"] is True
    assert after["teile"] == 4


def test_index_rebuild_zeigt_warnungen(run, lager_voll):
    lose = lager_voll / "LOSE"
    lose.mkdir()
    (lose / "part.yaml").write_text("part: LOSE\n", encoding="utf-8")
    result = run("index", "rebuild")
    assert result.exit_code == 0
    assert "4 Bauteile" in result.stdout
    assert "Warnung: LOSE" in result.stdout


def test_part_search_json_baut_index_bei_bedarf(run, lager_voll):
    assert not db.db_path(lager_voll).exists()
    result = run("part", "search", "irlz44n", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["anzahl"] == 1
    assert data["treffer"][0]["part"] == "IRLZ44N"
    assert db.db_path(lager_voll).exists()


def test_part_search_lesbar(run):
    result = run("part", "search", "irlz")
    assert result.exit_code == 0
    assert "IRLZ44N  ·  MOSFETs" in result.stdout
    assert "Datenblatt: datasheet.pdf" in result.stdout


def test_part_search_ohne_treffer_ist_kein_fehler(run):
    result = run("part", "search", "gibtsnicht")
    assert result.exit_code == 0
    assert "Keine Treffer" in result.stdout
    data = json.loads(run("part", "search", "gibtsnicht", "--json").stdout)
    assert data == {"suche": "gibtsnicht", "kategorie": "", "anzahl": 0, "treffer": []}


def test_part_search_kategorie(run):
    data = json.loads(run("part", "search", "--category", "widerstaende", "--json").stdout)
    assert [p["part"] for p in data["treffer"]] == ["223-0.1W"]


def test_neues_bauteil_landet_im_vorhandenen_index(run):
    run("index", "rebuild")
    assert run("part", "new", "BC547", "-c", "mosfets", "-n", "NPN-Transistor").exit_code == 0
    data = json.loads(run("part", "search", "bc547", "--json").stdout)
    assert data["anzahl"] == 1


def test_neues_bauteil_legt_keinen_index_an(run, lager_voll):
    assert run("part", "new", "BC547", "-c", "mosfets").exit_code == 0
    assert not db.db_path(lager_voll).exists()
