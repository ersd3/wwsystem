"""Tests für den Papierkorb: Inhalt ansehen und zurückholen (Kern, Seiten, API, CLI)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lager import cli, dialogs, files, indexer, parts, trash
from lager.dialogs import reveal as real_reveal  # vor dem Ersetzen durch die Fixture geholt

ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


@pytest.fixture()
def run(lager_voll, monkeypatch):
    """Führt CLI-Befehle gegen das Test-Lager aus (statt gegen config.yaml)."""
    monkeypatch.setattr(cli, "_require_root", lambda: lager_voll)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    runner = CliRunner()

    def _run(*args):
        return runner.invoke(cli.app, list(args))

    return _run


@pytest.fixture()
def opened(monkeypatch):
    """Ersetzt das Öffnen im Explorer und merkt sich, welcher Ordner geöffnet würde."""
    calls = []
    monkeypatch.setattr(dialogs, "reveal", lambda folder: calls.append(folder))
    return calls


def entry_for(root: Path, name: str) -> trash.TrashEntry:
    return next(entry for entry in trash.entries(root) if entry.name == name)


# ----------------------------------------------------------------- Inhalt


def test_leerer_papierkorb(lager_voll):
    assert trash.entries(lager_voll) == []
    assert not trash.trash_dir(lager_voll).exists()


def test_inhalt_neuestes_zuerst(lager_voll):
    irlz = lager_voll / "mosfets" / "IRLZ44N"
    files.remove_file(lager_voll, irlz, "kicad/TO-220.kicad_mod")
    parts.delete_part(lager_voll, "IRF540N")

    found = trash.entries(lager_voll)
    assert [entry.name for entry in found] == ["IRF540N", "TO-220.kicad_mod"]
    part, file = found
    assert (part.kind, part.part, part.path) == ("part", "IRF540N", "mosfets/IRF540N")
    assert (file.kind, file.part, file.path) == (
        "file", "IRLZ44N", "mosfets/IRLZ44N/kicad/TO-220.kicad_mod"
    )
    assert ISO_UTC.match(part.deleted_at)
    assert (part.location / "part.yaml").is_file()
    assert file.location.is_file()

    data = file.as_dict(lager_voll)
    assert data["id"] == file.id
    assert data["location"] == f"_papierkorb/{file.id}/mosfets/IRLZ44N/kicad/TO-220.kicad_mod"
    assert data["problem"] == ""


def test_von_hand_veraendertes_wird_uebersprungen(lager_voll):
    base = trash.trash_dir(lager_voll)
    # So sieht ein Eintrag aus, den das Programm früher angelegt hat.
    old = base / "20261126T205502Z" / "microcontroller" / "2812ARDUINOSHIELD"
    old.mkdir(parents=True)
    (old / "part.yaml").write_text("part: 2812ARDUINOSHIELD\n", encoding="utf-8")
    (base / "20261126T205502Z" / "Thumbs.db").write_bytes(b"x")  # zählt nicht als Inhalt
    (base / "LIESMICH.txt").write_text("x", encoding="utf-8")
    (base / "irgendwas").mkdir()
    (base / "20261126T205503Z").mkdir()  # leer, z. B. nach Wiederherstellen von Hand
    mixed = base / "20261126T205504Z"
    (mixed / "a").mkdir(parents=True)
    (mixed / "b").mkdir()

    found = trash.entries(lager_voll)
    assert [(entry.id, entry.name, entry.kind) for entry in found] == [
        ("20261126T205502Z", "2812ARDUINOSHIELD", "part")
    ]
    assert found[0].deleted_at == "2026-11-26T20:55:02Z"
    assert found[0].path == "microcontroller/2812ARDUINOSHIELD"


class FixedTime(datetime):
    """Uhr, die immer dieselbe Sekunde zeigt."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 26, 20, 55, 2, tzinfo=timezone.utc)


def test_jedes_loeschen_bekommt_einen_eigenen_ordner(lager_voll, monkeypatch):
    monkeypatch.setattr(trash, "datetime", FixedTime)
    parts.delete_part(lager_voll, "IRF540N")
    files.remove_file(lager_voll, lager_voll / "mosfets" / "IRLZ44N", "notiz.txt")
    parts.delete_part(lager_voll, "223-0.1W")
    found = trash.entries(lager_voll)
    assert [(entry.id, entry.name) for entry in found] == [
        ("20261126T205502Z-3", "223-0.1W"),
        ("20261126T205502Z-2", "notiz.txt"),
        ("20261126T205502Z", "IRF540N"),
    ]


def test_gesperrte_datei_hinterlaesst_nichts(lager_voll, monkeypatch):
    def locked(self, target):
        raise PermissionError("Die Datei wird von einem anderen Prozess verwendet")

    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(ValueError, match="Ist eine Datei daraus geöffnet"):
        parts.delete_part(lager_voll, "IRF540N")
    assert (lager_voll / "mosfets" / "IRF540N" / "part.yaml").is_file()
    assert [p.name for p in trash.trash_dir(lager_voll).iterdir()] == ["LIESMICH.txt"]


def test_ortszeit():
    expected = datetime(2026, 11, 26, 20, 55, 2, tzinfo=timezone.utc).astimezone()
    assert trash.local_time("2026-11-26T20:55:02Z") == expected.strftime("%d.%m.%Y, %H:%M")
    assert trash.local_time("kaputt") == "kaputt"


# ----------------------------------------------------------- Zurückholen


def test_bauteil_zurueckholen(lager_voll):
    parts.delete_part(lager_voll, "IRLZ44N")
    entry = entry_for(lager_voll, "IRLZ44N")
    target = trash.restore(lager_voll, entry.id)

    assert target == lager_voll / "mosfets" / "IRLZ44N"
    assert (target / "datasheet.pdf").read_bytes() == b"%PDF-1.4 test"
    assert (target / "kicad" / "TO-220.kicad_mod").is_file()
    assert trash.entries(lager_voll) == []
    assert not (trash.trash_dir(lager_voll) / entry.id).exists()  # leerer Zeit-Ordner ist weg
    assert indexer.rebuild(lager_voll)["teile"] == 4


def test_bauteil_in_unterkategorie_zurueckholen(lager_voll):
    parts.delete_part(lager_voll, "IRF9540N")
    (lager_voll / "mosfets" / "p-kanal").rmdir()  # die Unterkategorie ist inzwischen weg
    target = trash.restore(lager_voll, entry_for(lager_voll, "IRF9540N").id)
    assert target == lager_voll / "mosfets" / "p-kanal" / "IRF9540N"
    assert (target / "IRF9540N.pdf").is_file()


def test_datei_zurueckholen(lager_voll):
    irlz = lager_voll / "mosfets" / "IRLZ44N"
    files.remove_file(lager_voll, irlz, "kicad/TO-220.kicad_mod")
    assert not (irlz / "kicad").exists()
    target = trash.restore(lager_voll, entry_for(lager_voll, "TO-220.kicad_mod").id)
    assert target == irlz / "kicad" / "TO-220.kicad_mod"  # der Unterordner ist wieder da

    # Liegt am alten Platz inzwischen eine Datei gleichen Namens, wird nichts überschrieben.
    files.remove_file(lager_voll, irlz, "datasheet.pdf")
    (irlz / "datasheet.pdf").write_bytes(b"%PDF neu")
    target = trash.restore(lager_voll, entry_for(lager_voll, "datasheet.pdf").id)
    assert target == irlz / "datasheet-2.pdf"
    assert target.read_bytes() == b"%PDF-1.4 test"
    assert (irlz / "datasheet.pdf").read_bytes() == b"%PDF neu"


def test_zurueckholen_geht_nicht(lager_voll):
    # Die Bezeichnung ist inzwischen wieder vergeben.
    parts.delete_part(lager_voll, "IRF540N")
    parts.create_part(lager_voll, "widerstaende", "irf540n", {})
    entry = entry_for(lager_voll, "IRF540N")
    assert "inzwischen wieder vergeben" in trash.restore_problem(lager_voll, entry)
    with pytest.raises(ValueError, match="inzwischen wieder vergeben"):
        trash.restore(lager_voll, entry.id)
    assert entry.location.is_dir()  # bleibt im Papierkorb

    # Am alten Platz liegt ein Ordner (ohne part.yaml).
    parts.delete_part(lager_voll, "223-0.1W")
    (lager_voll / "widerstaende" / "223-0.1W").mkdir()
    with pytest.raises(ValueError, match="Am alten Platz gibt es schon einen Ordner"):
        trash.restore(lager_voll, entry_for(lager_voll, "223-0.1W").id)

    # Die Datei gehörte zu einem Bauteil, das selbst gelöscht ist.
    files.remove_file(lager_voll, lager_voll / "mosfets" / "IRLZ44N", "notiz.txt")
    parts.delete_part(lager_voll, "IRLZ44N")
    note = entry_for(lager_voll, "notiz.txt")
    assert note.part == "IRLZ44N"
    with pytest.raises(ValueError, match="Das Bauteil IRLZ44N gibt es an seinem alten Platz nicht mehr"):
        trash.restore(lager_voll, note.id)

    for bad in ("", "../mosfets", "20261126T205502Z", "abc"):
        with pytest.raises(ValueError):
            trash.restore(lager_voll, bad)


def test_kategorie_fehlt(lager_voll):
    parts.delete_part(lager_voll, "223-0.1W")
    (lager_voll / "widerstaende").rmdir()
    with pytest.raises(ValueError, match="Die Kategorie widerstaende gibt es nicht mehr"):
        trash.restore(lager_voll, entry_for(lager_voll, "223-0.1W").id)


def test_explorer_nur_fuer_vorhandene_ordner(tmp_path):
    with pytest.raises(dialogs.DialogUnavailable, match="Den Ordner gibt es nicht"):
        real_reveal(tmp_path / "gibtsnicht")


# ----------------------------------------------------------------- Seiten


def test_seite_papierkorb_leer(client):
    page = client.get("/papierkorb")
    assert page.status_code == 200
    assert "Der Papierkorb ist leer." in page.text
    assert "_papierkorb" in page.text  # der Ordner steht da, auch wenn es ihn noch nicht gibt
    assert "/papierkorb/oeffnen" not in page.text
    footer = client.get("/").text
    assert '<a href="/papierkorb">Papierkorb</a>' in footer
    assert "Eintrag" not in footer


def test_seite_papierkorb_mit_eintraegen(client, phone, lager_voll):
    client.post("/p/IRLZ44N/dateien/loeschen", data={"datei": "kicad/TO-220.kicad_mod"})
    client.post("/p/IRF540N/loeschen", data={"sicher": "1"})

    page = client.get("/papierkorb").text
    assert str(trash.trash_dir(lager_voll)) in page
    assert '<span class="part">IRF540N</span>' in page
    assert '<span class="part">TO-220.kicad_mod</span>' in page
    assert "Datei von IRLZ44N" in page
    assert "mosfets/IRLZ44N/kicad/TO-220.kicad_mod" in page
    assert "gelöscht am" in page
    assert page.count('action="/papierkorb/wiederherstellen"') == 2
    assert 'action="/papierkorb/oeffnen"' in page  # am PC des Servers
    assert "2 Einträge" in client.get("/").text

    remote = phone.get("/papierkorb").text
    assert remote.count('action="/papierkorb/wiederherstellen"') == 2
    assert 'action="/papierkorb/oeffnen"' not in remote  # am Handy sinnlos


def test_wiederherstellen_im_browser(client, lager_voll):
    client.post("/p/IRF540N/loeschen", data={"sicher": "1"})
    response = client.post(
        "/papierkorb/wiederherstellen",
        data={"eintrag": entry_for(lager_voll, "IRF540N").id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/IRF540N?wiederhergestellt=IRF540N"
    assert "IRF540N ist aus dem Papierkorb zurück." in client.get(response.headers["location"]).text
    assert client.get("/api/v1/parts/IRF540N").status_code == 200

    client.post("/p/IRLZ44N/dateien/loeschen", data={"datei": "3d/TO-220.step"})
    response = client.post(
        "/papierkorb/wiederherstellen",
        data={"eintrag": entry_for(lager_voll, "TO-220.step").id},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/p/IRLZ44N?wiederhergestellt=3d%2FTO-220.step"
    page = client.get(response.headers["location"]).text
    assert "3d/TO-220.step ist aus dem Papierkorb zurück." in page
    # Nur was stimmt, wird gemeldet.
    assert "aus dem Papierkorb zurück" not in client.get("/p/IRLZ44N?wiederhergestellt=erfunden.pdf").text
    assert "Der Papierkorb ist leer." in client.get("/papierkorb").text


def test_wiederherstellen_fehler_im_browser(client, lager_voll):
    client.post("/p/IRF540N/loeschen", data={"sicher": "1"})
    parts.create_part(lager_voll, "mosfets", "IRF540N", {})
    client.post("/index/rebuild")
    page = client.get("/papierkorb").text
    assert "inzwischen wieder vergeben" in page
    assert 'action="/papierkorb/wiederherstellen"' not in page  # kein Knopf, der nicht geht

    response = client.post(
        "/papierkorb/wiederherstellen", data={"eintrag": entry_for(lager_voll, "IRF540N").id}
    )
    assert response.status_code == 400
    assert "inzwischen wieder vergeben" in response.text
    unknown = client.post("/papierkorb/wiederherstellen", data={"eintrag": "20201231T000000Z"})
    assert unknown.status_code == 400
    assert "keinen Eintrag" in unknown.text


def test_papierkorb_im_explorer_oeffnen(client, phone, lager_voll, opened, monkeypatch):
    client.post("/p/IRF540N/loeschen", data={"sicher": "1"})
    response = client.post("/papierkorb/oeffnen", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/papierkorb?hinweis=explorer"
    assert opened == [trash.trash_dir(lager_voll)]
    assert "Der Papierkorb ist im Explorer geöffnet." in client.get(response.headers["location"]).text

    assert phone.post("/papierkorb/oeffnen").status_code == 403
    assert len(opened) == 1

    def unavailable(folder):
        raise dialogs.DialogUnavailable("Kein Explorer hier.")

    monkeypatch.setattr(dialogs, "reveal", unavailable)
    failed = client.post("/papierkorb/oeffnen")
    assert failed.status_code == 503
    assert "Kein Explorer hier." in failed.text


def test_papierkorb_bei_schreibschutz(geschuetzt, lager_voll):
    parts.delete_part(lager_voll, "IRF540N")
    entry_id = entry_for(lager_voll, "IRF540N").id
    page = geschuetzt.get("/papierkorb").text
    assert '<span class="part">IRF540N</span>' in page  # ansehen geht
    assert 'action="/papierkorb/wiederherstellen"' not in page
    assert geschuetzt.post("/papierkorb/wiederherstellen", data={"eintrag": entry_id}).status_code == 403
    assert geschuetzt.post(f"/api/v1/trash/{entry_id}/restore").status_code == 403
    ok = geschuetzt.post(f"/api/v1/trash/{entry_id}/restore", headers={"X-Lager-Token": "geheim"})
    assert ok.status_code == 200


# -------------------------------------------------------------------- API


def test_api_papierkorb(client, lager_voll):
    assert client.get("/api/v1/trash").json()["anzahl"] == 0
    client.delete("/api/v1/parts/IRF540N")
    client.delete("/api/v1/parts/IRLZ44N/files/notiz.txt")

    data = client.get("/api/v1/trash").json()
    assert data["papierkorb"] == str(trash.trash_dir(lager_voll))
    assert data["anzahl"] == 2
    by_name = {entry["name"]: entry for entry in data["eintraege"]}
    assert by_name["IRF540N"]["kind"] == "part"
    assert by_name["notiz.txt"]["part"] == "IRLZ44N"
    assert by_name["notiz.txt"]["path"] == "mosfets/IRLZ44N/notiz.txt"

    restored = client.post(f"/api/v1/trash/{by_name['IRF540N']['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["wiederhergestellt"] == "mosfets/IRF540N"
    assert restored.json()["teil"]["part"] == "IRF540N"
    note = client.post(f"/api/v1/trash/{by_name['notiz.txt']['id']}/restore").json()
    assert note["wiederhergestellt"] == "mosfets/IRLZ44N/notiz.txt"
    assert "notiz.txt" in [f["path"] for f in note["teil"]["files"]]

    assert client.post("/api/v1/trash/20201231T000000Z/restore").status_code == 404
    client.delete("/api/v1/parts/IRF540N")
    parts.create_part(lager_voll, "mosfets", "IRF540N", {})
    conflict = client.post(f"/api/v1/trash/{entry_for(lager_voll, 'IRF540N').id}/restore")
    assert conflict.status_code == 409
    assert "inzwischen wieder vergeben" in conflict.json()["detail"]


# -------------------------------------------------------------------- CLI


def test_cli_papierkorb(run, lager_voll, opened):
    assert "Der Papierkorb ist leer." in run("trash", "list").output
    assert run("trash", "open").exit_code == 1  # noch kein Ordner
    run("part", "remove", "IRF540N")

    listing = run("trash", "list")
    assert listing.exit_code == 0
    assert "IRF540N" in listing.output
    assert "alter Platz: mosfets/IRF540N" in listing.output
    data = json.loads(run("trash", "list", "--json").output)
    assert data["anzahl"] == 1
    entry_id = data["eintraege"][0]["id"]

    result = run("trash", "restore", entry_id, "--json")
    assert result.exit_code == 0, result.output
    assert Path(json.loads(result.output)["wiederhergestellt"]) == lager_voll / "mosfets" / "IRF540N"
    assert (lager_voll / "mosfets" / "IRF540N" / "part.yaml").is_file()
    assert run("trash", "restore", entry_id).exit_code == 1  # schon zurück

    run("part", "remove", "IRF540N")
    assert run("trash", "open").exit_code == 0
    assert opened == [trash.trash_dir(lager_voll)]
