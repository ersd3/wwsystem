"""Tests für Phase 2: Bauteile bearbeiten, Suche beim Tippen, Anmelden bei Schreibschutz."""
import json

import pytest
import yaml
from typer.testing import CliRunner

from lager import cli, parts


def _doc(lager_voll, part="IRLZ44N"):
    return yaml.safe_load((parts.find_part_dir(lager_voll, part) / "part.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------- Kern: update_part


def test_update_part_aendert_nur_genannte_felder(lager_voll):
    folder = parts.update_part(lager_voll, "irlz44n", {"location": " B-07 ", "quantity": "12"})
    assert folder.name == "IRLZ44N"
    doc = _doc(lager_voll)
    assert doc["location"] == "B-07"
    assert doc["quantity"] == 12
    assert doc["manufacturer"] == "Infineon"  # unverändert
    assert doc["aliases"] == ["IRLZ44NTR"]


def test_update_part_listen_und_leeren(lager_voll):
    parts.update_part(lager_voll, "IRLZ44N", {"tags": ["a", " b ", "a", ""], "aliases": [], "notes": None})
    doc = _doc(lager_voll)
    assert doc["tags"] == ["a", "b"]
    assert doc["aliases"] == []
    assert doc["notes"] == ""


def test_update_part_behaelt_unbekannte_eintraege(lager_voll):
    path = parts.find_part_dir(lager_voll, "IRF540N") / "part.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "footprint: TO-220\n", encoding="utf-8")
    parts.update_part(lager_voll, "IRF540N", {"name": "Neu"})
    doc = _doc(lager_voll, "IRF540N")
    assert doc["footprint"] == "TO-220"
    assert doc["name"] == "Neu"
    assert doc["part"] == "IRF540N"
    assert path.read_text(encoding="utf-8").startswith("# part.yaml")


@pytest.mark.parametrize(
    "part, changes, expected",
    [
        ("IRLZ44N", {"quantity": "viele"}, "ganze Zahl"),
        ("IRLZ44N", {"part": "ANDERS"}, "lassen sich nicht ändern"),
        ("IRLZ44N", {"category": "x"}, "lassen sich nicht ändern"),
        ("GIBTSNICHT", {"name": "x"}, "nicht gefunden"),
    ],
)
def test_update_part_fehler(lager_voll, part, changes, expected):
    before = _doc(lager_voll)
    with pytest.raises(ValueError, match=expected):
        parts.update_part(lager_voll, part, changes)
    assert _doc(lager_voll) == before


# ------------------------------------------------------------- CLI


@pytest.fixture()
def run(lager_voll, monkeypatch):
    monkeypatch.setattr(cli, "_require_root", lambda: lager_voll)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    runner = CliRunner()
    return lambda *args: runner.invoke(cli.app, list(args))


def test_part_edit(run, lager_voll):
    run("index", "rebuild")
    result = run("part", "edit", "irf540n", "--location", "C-02", "--tags", "n-kanal, 100v", "-q", "7", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["geaendert"] == ["location", "quantity", "tags"]
    doc = _doc(lager_voll, "IRF540N")
    assert (doc["location"], doc["quantity"], doc["tags"]) == ("C-02", 7, ["n-kanal", "100v"])
    assert doc["name"] == "MOSFET N-Kanal 100 V"
    found = json.loads(run("part", "search", "c-02", "--json").stdout)
    assert [p["part"] for p in found["treffer"]] == ["IRF540N"]


def test_part_edit_leert_feld_und_fehler(run, lager_voll):
    assert run("part", "edit", "IRLZ44N", "--location", "").exit_code == 0
    assert _doc(lager_voll)["location"] == ""
    nothing = run("part", "edit", "IRLZ44N")
    assert nothing.exit_code == 1
    assert "Nichts zu ändern" in nothing.stderr
    assert run("part", "edit", "GIBTSNICHT", "--name", "x").exit_code == 1


# ------------------------------------------------------ Web: bearbeiten


def test_seite_bearbeiten_ist_vorbelegt(client):
    page = client.get("/p/irlz44n/bearbeiten")
    assert page.status_code == 200
    assert "IRLZ44N bearbeiten" in page.text
    assert 'value="Infineon"' in page.text
    assert 'value="A-03-2"' in page.text
    assert 'value="n-kanal, to-220"' in page.text
    assert 'href="/p/IRLZ44N/bearbeiten"' in client.get("/p/IRLZ44N").text


def test_bearbeiten_speichert(client, lager_voll):
    response = client.post(
        "/p/irlz44n/bearbeiten",
        data={
            "name": "Logic-Level-MOSFET", "hersteller": "Infineon", "lagerfach": "B-07",
            "menge": "9", "einheit": "Stk", "tags": "n-kanal, logic-level", "aliase": "",
            "notizen": "Für 3,3 V geeignet",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/IRLZ44N"
    part = client.get("/api/v1/parts/IRLZ44N").json()
    assert part["name"] == "Logic-Level-MOSFET"
    assert part["location"] == "B-07"
    assert part["quantity"] == 9
    assert part["tags"] == ["logic-level", "n-kanal"]
    assert part["aliases"] == []
    assert part["notes"] == "Für 3,3 V geeignet"
    assert [p["part"] for p in client.get("/api/v1/parts", params={"q": "b-07"}).json()["treffer"]] == ["IRLZ44N"]
    # Die Dateien bleiben unberührt.
    assert (lager_voll / "mosfets" / "IRLZ44N" / "datasheet.pdf").is_file()


def test_bearbeiten_fehler_bleibt_im_formular(client, lager_voll):
    before = _doc(lager_voll)
    response = client.post("/p/IRLZ44N/bearbeiten", data={"name": "Mein Text", "menge": "viele"})
    assert response.status_code == 400
    assert "ganze Zahl" in response.text
    assert 'value="Mein Text"' in response.text
    assert _doc(lager_voll) == before


def test_bearbeiten_unbekanntes_bauteil(client):
    assert client.get("/p/GIBTSNICHT/bearbeiten").status_code == 404
    assert client.post("/p/GIBTSNICHT/bearbeiten", data={"name": "x"}).status_code == 404


def test_api_bauteil_aendern(client):
    response = client.patch("/api/v1/parts/irf540n", json={"location": "C-02", "tags": ["neu"]})
    assert response.status_code == 200
    data = response.json()
    assert (data["location"], data["tags"], data["name"]) == ("C-02", ["neu"], "MOSFET N-Kanal 100 V")
    assert client.patch("/api/v1/parts/GIBTSNICHT", json={"name": "x"}).status_code == 404
    assert client.patch("/api/v1/parts/IRF540N", json={"quantity": "viele"}).status_code == 422


# --------------------------------------------------- Suche beim Tippen


def test_startseite_bindet_die_suche_beim_tippen_ein(client):
    page = client.get("/").text
    assert '<div id="treffer">' in page
    assert "/static/app.js" in page
    assert "fetch('/suche?'" in client.get("/static/app.js").text


def test_suche_liefert_nur_die_trefferliste(client):
    fragment = client.get("/suche", params={"q": "irlz"})
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert 'href="/p/IRLZ44N"' in fragment.text
    assert "IRF540N" not in fragment.text
    assert 'href="/?kategorie=mosfets&amp;q=irlz"' in fragment.text
    assert "Keine Treffer" in client.get("/suche", params={"q": "gibtsnicht"}).text
    only = client.get("/suche", params={"kategorie": "widerstaende"}).text
    assert "223-0.1W" in only and "IRLZ44N" not in only


# ------------------------------------------- Anmelden bei Schreibschutz


def test_ohne_token_ist_keine_anmeldung_noetig(client):
    assert "nicht nötig" in client.get("/anmelden").text
    assert "Anmelden" not in client.get("/").text
    assert client.post("/anmelden", data={"token": "egal"}, follow_redirects=False).status_code == 303


def test_anmelden_schaltet_schreiben_im_browser_frei(geschuetzt):
    client = geschuetzt
    start = client.get("/").text
    assert "Schreibschutz aktiv" in start
    assert 'href="/neu"' not in start
    assert client.post("/neu", data={"bezeichnung": "X1", "kategorie": "mosfets"}).status_code == 403

    wrong = client.post("/anmelden", data={"token": "falsch"})
    assert wrong.status_code == 403
    assert "stimmt nicht" in wrong.text
    assert client.post("/neu", data={"bezeichnung": "X1", "kategorie": "mosfets"}).status_code == 403

    ok = client.post("/anmelden", data={"token": " geheim "}, follow_redirects=False)
    assert ok.status_code == 303
    assert "httponly" in ok.headers["set-cookie"].lower()

    angemeldet = client.get("/").text
    assert "Angemeldet" in angemeldet
    assert 'href="/neu"' in angemeldet
    created = client.post("/neu", data={"bezeichnung": "X1", "kategorie": "mosfets"}, follow_redirects=False)
    assert created.status_code == 303
    assert client.post("/p/X1/bearbeiten", data={"name": "Test"}, follow_redirects=False).status_code == 303
    assert client.get("/api/v1/parts/X1").json()["name"] == "Test"

    assert client.post("/abmelden", follow_redirects=False).status_code == 303
    assert "Schreibschutz aktiv" in client.get("/").text
    assert client.post("/p/X1/bearbeiten", data={"name": "Nochmal"}).status_code == 403


def test_bearbeiten_seite_bei_schreibschutz(geschuetzt):
    page = geschuetzt.get("/p/IRLZ44N/bearbeiten").text
    assert "Schreibschutz ist aktiv" in page
    assert 'action="/p/IRLZ44N/bearbeiten"' not in page
    assert 'href="/p/IRLZ44N/bearbeiten"' not in geschuetzt.get("/p/IRLZ44N").text
    assert geschuetzt.patch("/api/v1/parts/IRLZ44N", json={"name": "x"}).status_code == 403
    ok = geschuetzt.patch("/api/v1/parts/IRLZ44N", json={"name": "x"}, headers={"X-Lager-Token": "geheim"})
    assert ok.status_code == 200
