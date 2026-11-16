"""Tests für das Verwalten von Bauteilen: freie Bezeichnungen, Unterkategorien, Umbenennen,
Verschieben, Löschen (Papierkorb), Dateien löschen, Hochladen mit Meldung, Ordner-Auswahl."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from lager import categories, cli, db, dialogs, files, indexer, labels, names, parts, search, trash
from lager.server import app as server


@pytest.fixture()
def run(lager_voll, monkeypatch):
    """Führt CLI-Befehle gegen das Test-Lager aus (statt gegen config.yaml)."""
    monkeypatch.setattr(cli, "_require_root", lambda: lager_voll)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    runner = CliRunner()

    def _run(*args):
        return runner.invoke(cli.app, list(args))

    return _run


def doc_of(folder: Path) -> dict:
    return yaml.safe_load((folder / "part.yaml").read_text(encoding="utf-8"))


def trashed(root: Path, rel: str) -> list[Path]:
    """Alle Fundstellen eines Pfads im Papierkorb (je Löschzeitpunkt ein Ordner)."""
    return [stamp / rel for stamp in trash.trash_dir(root).iterdir() if (stamp / rel).exists()]


# Formularfelder der Seite "Bearbeiten" für IRF540N, so wie der Browser sie schickt.
IRF540N_FORM = {
    "bezeichnung": "IRF540N", "kategorie": "mosfets", "unterkategorie": "",
    "neue_unterkategorie": "", "name": "MOSFET N-Kanal 100 V", "hersteller": "",
    "lagerfach": "", "menge": "0", "einheit": "Stk", "tags": "n-kanal", "aliase": "",
    "notizen": "",
}


# ------------------------------------------- Bezeichnung: Leerzeichen, Kleinbuchstaben


@pytest.mark.parametrize(
    "name",
    ["IRLZ44N", "Arduino Mega 2560", "raspberry pi pico h", "10 kΩ 0,25 W", "LM317 (TO-220)", "R&S #1"],
)
def test_erlaubte_bezeichnungen(name):
    names.check(name)
    assert parts.normalize_part_id(f"  {name}  ") == name


@pytest.mark.parametrize(
    "name, expected",
    [
        ("", "fehlt"),
        ("BC547/B", "darf diese Zeichen nicht enthalten: /"),
        ("C:Teil", "darf diese Zeichen nicht enthalten: :"),
        ("was?", "darf diese Zeichen nicht enthalten: ?"),
        ("_intern", "nicht mit _ oder . beginnen"),
        (".versteckt", "nicht mit _ oder . beginnen"),
        ("Ende.", "nicht mit einem Punkt enden"),
        ("con", "kein erlaubter Ordnername"),
        ("x" * 81, "zu lang"),
    ],
)
def test_abgelehnte_bezeichnungen(name, expected):
    with pytest.raises(ValueError, match=expected.replace("?", r"\?")):
        names.check(name)


def test_bezeichnung_bleibt_wie_eingegeben(lager_voll):
    folder = parts.create_part(lager_voll, "mosfets", "  Arduino   Mega 2560 ", {"name": "Board"})
    assert folder == lager_voll / "mosfets" / "Arduino Mega 2560"
    assert doc_of(folder)["part"] == "Arduino Mega 2560"
    # Eindeutig ohne Rücksicht auf Groß-/Kleinschreibung, im ganzen Lager.
    with pytest.raises(ValueError, match="existiert bereits"):
        parts.create_part(lager_voll, "widerstaende", "ARDUINO MEGA 2560", {})
    assert parts.find_part_dir(lager_voll, "arduino mega 2560") == folder
    assert parts.find_part_dir(lager_voll, "arduinomega2560") is None


def test_suche_und_seiten_mit_leerzeichen(client, lager_voll):
    folder = parts.create_part(lager_voll, "mosfets", "Arduino Mega 2560", {"name": "Board"})
    parts.create_part(lager_voll, "mosfets", "Mega", {})
    (folder / "pinout.pdf").write_bytes(b"%PDF-1.4 pins")
    client.post("/index/rebuild")

    hits = client.get("/api/v1/parts", params={"q": "arduino mega 2560"}).json()["treffer"]
    assert [p["part"] for p in hits] == ["Arduino Mega 2560"]
    # Die ganze Eingabe zählt für die Reihenfolge, nicht nur ihr erstes Wort.
    hits = client.get("/api/v1/parts", params={"q": "mega"}).json()["treffer"]
    assert [p["part"] for p in hits] == ["Mega", "Arduino Mega 2560"]

    page = client.get("/?q=arduino").text
    assert 'href="/p/Arduino%20Mega%202560"' in page
    assert 'href="/files/mosfets/Arduino%20Mega%202560/pinout.pdf"' in page
    detail = client.get("/p/Arduino%20Mega%202560")
    assert detail.status_code == 200
    assert "<h1>Arduino Mega 2560</h1>" in detail.text
    assert client.get("/p/arduino%20mega%202560").status_code == 200
    assert client.get("/files/mosfets/Arduino%20Mega%202560/pinout.pdf").content == b"%PDF-1.4 pins"


def test_neues_bauteil_im_browser_mit_leerzeichen_und_kleinbuchstaben(client, lager_voll):
    response = client.post(
        "/neu",
        data={"bezeichnung": "raspberry pi pico h", "kategorie": "mosfets"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/raspberry%20pi%20pico%20h"
    assert (lager_voll / "mosfets" / "raspberry pi pico h" / "part.yaml").is_file()
    form = client.get("/neu").text
    assert 'autocapitalize="characters"' not in form
    assert "auch mit Leerzeichen" in form


def test_ungueltige_bezeichnung_legt_keine_kategorie_an(client, lager_voll):
    response = client.post("/neu", data={"bezeichnung": "a/b", "neue_kategorie": "Sensoren"})
    assert response.status_code == 400
    assert "darf diese Zeichen nicht enthalten" in response.text
    assert not (lager_voll / "sensoren").exists()


def test_etikett_mit_leerzeichen():
    assert labels.part_url("http://lager.fritz.box:8080", "Arduino Mega 2560") == (
        "http://lager.fritz.box:8080/p/Arduino%20Mega%202560"
    )
    assert labels.split_id("Arduino Mega 2560") == ("Arduino", "Mega 2560")
    assert labels.split_id("raspberry pi pico h") == ("raspberry", "pi pico h")


def test_woerter_auf_zeilen_verteilen():
    assert labels.wrap_words("WS2812 Arduino Shield", 2) == ("WS2812", "Arduino Shield")
    assert labels.wrap_words("WS2812 Arduino Shield", 3) == ("WS2812", "Arduino", "Shield")
    assert labels.wrap_words("Raspberry Pi Pico H", 2) == ("Raspberry", "Pi Pico H")
    assert labels.wrap_words("Arduino Mega", 3) is None
    assert labels.wrap_words("IRLZ44N", 2) is None
    assert labels.even_split("ABCDEFGHIJ", 3) == ("ABCD", "EFGH", "IJ")


def test_lange_bezeichnung_mit_leerzeichen_bricht_an_leerzeichen_um():
    geo = labels.geometry(labels.resolve_size("klein"))
    text = labels.fit_text(geo, "WS2812 Arduino Shield", "LED-Shield", "A-1")
    assert text.id_parts == ("WS2812", "Arduino", "Shield")
    assert text.id_fits
    assert text.id_lines * text.id_size * labels.LINE_HEIGHT <= geo.text.height
    # Auf dem großen Etikett reicht eine Zeile mehr Breite: weniger Zeilen.
    big = labels.fit_text(labels.geometry(labels.resolve_size("gross")), "WS2812 Arduino Shield")
    assert big.id_parts == ("WS2812", "Arduino Shield")
    # Typnummern ohne Leerzeichen werden wie bisher behandelt.
    assert labels.fit_text(geo, "R-100K-0.25W").id_parts == ("R-100K-", "0.25W")
    assert labels.fit_text(geo, "IRLZ44N").id_parts == ("IRLZ44N",)


def test_zu_lange_bezeichnung_wird_gemeldet(client, lager_voll):
    long_name = "Sehr langer Name mit vielen Worten fuer ein Bauteil"
    geo = labels.geometry(labels.resolve_size("klein"))
    assert labels.fit_text(geo, long_name).id_fits is False
    assert labels.fit_text(labels.geometry(labels.resolve_size("gross")), long_name).id_fits is True

    parts.create_part(lager_voll, "mosfets", long_name, {})
    client.post("/index/rebuild")
    page = client.get("/etiketten", params={"groesse": "klein"}).text
    assert f"Zu lang für diese Etikettengröße, die Bezeichnung wird abgeschnitten: {long_name}." in page
    assert "Zu lang für diese Etikettengröße" not in client.get("/etiketten", params={"groesse": "gross"}).text


def test_etiketten_seite_mit_leerzeichen(client, lager_voll):
    parts.create_part(lager_voll, "mosfets", "Arduino Mega 2560", {})
    client.post("/index/rebuild")
    page = client.get("/etiketten", params={"teil": "Arduino Mega 2560"}).text
    assert "1 Etikett auf" in page and "1 Seite" in page
    # Die Bezeichnung steht auf dem Etikett; im QR-Code steckt die Adresse mit %20.
    assert "<span>Arduino</span><span>Mega</span><span>2560</span>" in page
    assert "Zu lang für diese Etikettengröße" not in page


# --------------------------------------------------------------- Unterkategorien


def test_unterkategorie_normalisieren():
    assert categories.normalize_subcategory("  Shields ") == "Shields"
    assert categories.normalize_subcategory("Shields \\ Motor / ") == "Shields/Motor"
    assert categories.normalize_subcategory("") == ""
    for bad in ("../fremd", "a:b", "_x", "a/b/c/d"):
        with pytest.raises(ValueError):
            categories.normalize_subcategory(bad)


def test_unterkategorien_auflisten(lager_voll):
    assert categories.subcategories(lager_voll, "mosfets") == ["p-kanal"]
    assert categories.subcategories(lager_voll, "widerstaende") == []
    (lager_voll / "mosfets" / "Shields" / "Motor").mkdir(parents=True)
    assert categories.subcategories(lager_voll, "mosfets") == ["p-kanal", "Shields", "Shields/Motor"]


def test_bauteil_in_unterkategorie_anlegen(lager_voll):
    folder = parts.create_part(lager_voll, "mosfets", "Motor Shield", {}, " Shields ")
    assert folder == lager_voll / "mosfets" / "Shields" / "Motor Shield"
    # Andere Schreibweise: der vorhandene Ordner wird genommen, kein zweiter angelegt.
    second = parts.create_part(lager_voll, "mosfets", "Relais Shield", {}, "shields")
    assert second.parent == lager_voll / "mosfets" / "Shields"
    assert parts.create_part(lager_voll, "mosfets", "IRF5305", {}, "P-KANAL").parent.name == "p-kanal"

    indexer.rebuild(lager_voll)
    conn = db.connect(lager_voll, create=False)
    try:
        found = search.get_part(conn, "motor shield")
    finally:
        conn.close()
    assert found["category"] == "mosfets"
    assert found["subcategory"] == "Shields"
    assert found["path"] == "mosfets/Shields/Motor Shield"


def test_bauteil_ist_keine_unterkategorie(lager_voll):
    with pytest.raises(ValueError, match="ist ein Bauteil"):
        parts.create_part(lager_voll, "mosfets", "Kind", {}, "IRLZ44N")
    assert not (lager_voll / "mosfets" / "IRLZ44N" / "Kind").exists()


def test_seite_neu_bietet_unterkategorien_an(client, lager_voll):
    (lager_voll / "widerstaende" / "SMD").mkdir()
    page = client.get("/neu").text
    assert 'name="unterkategorie"' in page
    assert '<option value="mosfets/p-kanal" data-kategorie="mosfets" data-kurz="p-kanal">MOSFETs / p-kanal</option>' in page
    assert 'value="widerstaende/SMD"' in page
    assert 'name="neue_unterkategorie"' in page


def test_neues_bauteil_mit_unterkategorie_aus_der_auswahl(client, lager_voll):
    response = client.post(
        "/neu",
        data={"bezeichnung": "IRF4905", "kategorie": "mosfets", "unterkategorie": "mosfets/p-kanal"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (lager_voll / "mosfets" / "p-kanal" / "IRF4905" / "part.yaml").is_file()
    page = client.get("/p/IRF4905").text
    assert "MOSFETs</a> / p-kanal" in page


def test_neues_bauteil_mit_neuer_unterkategorie(client, lager_voll):
    client.post(
        "/neu",
        data={
            "bezeichnung": "Arduino Mega", "neue_kategorie": "Microcontroller",
            "neue_unterkategorie": "Microcontroller",
        },
    )
    client.post(
        "/neu",
        data={
            "bezeichnung": "WS2812 Shield", "kategorie": "microcontroller",
            "neue_unterkategorie": "Shields",
        },
    )
    assert (lager_voll / "microcontroller" / "Microcontroller" / "Arduino Mega" / "part.yaml").is_file()
    assert (lager_voll / "microcontroller" / "Shields" / "WS2812 Shield" / "part.yaml").is_file()
    cats = {c["id"]: c for c in client.get("/api/v1/categories").json()}
    assert cats["microcontroller"]["subcategories"] == ["Microcontroller", "Shields"]
    assert cats["microcontroller"]["parts"] == 2
    assert cats["mosfets"]["subcategories"] == ["p-kanal"]


def test_unterkategorie_einer_anderen_kategorie(client, lager_voll):
    # Ohne JavaScript bleibt die alte Auswahl stehen, wenn die Kategorie gewechselt wird.
    response = client.post(
        "/neu",
        data={"bezeichnung": "R1", "kategorie": "widerstaende", "unterkategorie": "mosfets/p-kanal"},
    )
    assert response.status_code == 400
    assert "gehört zu einer anderen Kategorie" in response.text
    assert parts.find_part_dir(lager_voll, "R1") is None
    # Mit einer neu eingetippten Kategorie wird die Auswahl übergangen.
    response = client.post(
        "/neu",
        data={"bezeichnung": "R1", "neue_kategorie": "Sensoren", "unterkategorie": "mosfets/p-kanal"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (lager_voll / "sensoren" / "R1" / "part.yaml").is_file()


def test_api_und_cli_mit_unterkategorie(client, run, lager_voll):
    response = client.post(
        "/api/v1/parts", json={"part": "Uno R3", "category": "mosfets", "subcategory": "Boards"}
    )
    assert response.status_code == 201
    assert response.json()["subcategory"] == "Boards"
    assert response.json()["path"] == "mosfets/Boards/Uno R3"

    result = run("part", "new", "Nano Every", "-c", "mosfets", "-s", "Boards", "--json")
    assert result.exit_code == 0, result.output
    assert (lager_voll / "mosfets" / "Boards" / "Nano Every" / "part.yaml").is_file()
    listed = json.loads(run("category", "list", "--json").output)["kategorien"]
    assert listed[0]["unterkategorien"] == ["Boards", "p-kanal"]


# ------------------------------------------------------- Umbenennen und Verschieben


def test_umbenennen_behaelt_dateien_und_alte_bezeichnung(lager_voll):
    folder = parts.move_part(lager_voll, "irlz44n", new_id="IRLZ44N Logic Level")
    assert folder == lager_voll / "mosfets" / "IRLZ44N Logic Level"
    assert not (lager_voll / "mosfets" / "IRLZ44N").exists()
    assert (folder / "datasheet.pdf").is_file()
    assert (folder / "kicad" / "TO-220.kicad_mod").is_file()
    doc = doc_of(folder)
    assert doc["part"] == "IRLZ44N Logic Level"
    assert doc["aliases"] == ["IRLZ44NTR", "IRLZ44N"]
    assert doc["location"] == "A-03-2"
    assert parts.find_part_dir(lager_voll, "IRLZ44N") is None


def test_umbenennen_nur_gross_klein(lager_voll):
    folder = parts.move_part(lager_voll, "IRF540N", new_id="Irf540n")
    assert [d.name for d in (lager_voll / "mosfets").iterdir() if d.name.lower() == "irf540n"] == ["Irf540n"]
    assert doc_of(folder)["part"] == "Irf540n"
    assert doc_of(folder)["aliases"] == []  # dieselbe Bezeichnung braucht keinen Alias


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"new_id": "IRLZ44N"}, "existiert bereits"),
        ({"new_id": "a/b"}, "darf diese Zeichen nicht enthalten"),
        ({"new_id": "  "}, "fehlt"),
        ({"category": "gibtsnicht"}, "Kategorie existiert nicht"),
        ({"category": "../fremd"}, "Ungültige Kategorie"),
        ({"category": "_vorlage"}, "Ungültige Kategorie"),
        ({"subcategory": "IRLZ44N"}, "ist ein Bauteil"),
        ({"subcategory": "a:b"}, "darf diese Zeichen nicht enthalten"),
    ],
)
def test_verschieben_fehler_aendern_nichts(lager_voll, kwargs, expected):
    with pytest.raises(ValueError, match=expected):
        parts.move_part(lager_voll, "IRF540N", **kwargs)
    assert (lager_voll / "mosfets" / "IRF540N" / "part.yaml").is_file()
    assert doc_of(lager_voll / "mosfets" / "IRF540N")["aliases"] == []


def test_verschieben_unbekanntes_bauteil(lager_voll):
    with pytest.raises(ValueError, match="Teil nicht gefunden"):
        parts.move_part(lager_voll, "GIBTSNICHT", new_id="X")


def test_verschieben_in_kategorie_und_unterkategorie(lager_voll):
    folder = parts.move_part(lager_voll, "IRF540N", subcategory="N-Kanal")
    assert folder == lager_voll / "mosfets" / "N-Kanal" / "IRF540N"
    # Nur die Kategorie wechselt: Die alte Unterkategorie gehört nicht zur neuen.
    folder = parts.move_part(lager_voll, "IRF540N", category="widerstaende")
    assert folder == lager_voll / "widerstaende" / "IRF540N"
    assert parts.location_of(lager_voll, folder) == ("widerstaende", "")
    # Zurück, in eine vorhandene Unterkategorie, und dabei umbenennen.
    folder = parts.move_part(lager_voll, "IRF540N", "IRF 540 N", "mosfets", "p-kanal")
    assert folder == lager_voll / "mosfets" / "p-kanal" / "IRF 540 N"
    assert doc_of(folder)["aliases"] == ["IRF540N"]
    # Aus der Unterkategorie heraus direkt in die Kategorie.
    assert parts.move_part(lager_voll, "IRF 540 N", subcategory="") == lager_voll / "mosfets" / "IRF 540 N"


def test_seite_bearbeiten_zeigt_bezeichnung_und_ort(client):
    page = client.get("/p/IRF9540N/bearbeiten").text
    assert 'name="bezeichnung" value="IRF9540N"' in page
    assert '<option value="mosfets" selected>MOSFETs</option>' in page
    assert 'data-kurz="p-kanal" selected>' in page
    assert "Bauteil löschen" in page
    assert 'action="/p/IRF9540N/loeschen"' in page


def test_bearbeiten_benennt_um_und_alte_adresse_fuehrt_weiter(client, lager_voll):
    response = client.post(
        "/p/IRF540N/bearbeiten",
        data={**IRF540N_FORM, "bezeichnung": "Irf 540 n", "aliase": "IRF540"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/Irf%20540%20n?frueher=IRF540N"
    page = client.get(response.headers["location"]).text
    assert "<h1>Irf 540 n</h1>" in page
    assert "„IRF540N“ heißt jetzt „Irf 540 n“." in page
    part = client.get("/api/v1/parts/Irf%20540%20n").json()
    assert part["aliases"] == ["IRF540", "IRF540N"]
    assert part["name"] == "MOSFET N-Kanal 100 V"
    assert part["tags"] == ["n-kanal"]
    assert (lager_voll / "mosfets" / "Irf 540 n" / "part.yaml").is_file()

    # Die alte Adresse (z. B. auf einem gedruckten QR-Etikett) führt zum Bauteil.
    old = client.get("/p/IRF540N", follow_redirects=False)
    assert old.status_code == 307
    assert old.headers["location"] == "/p/Irf%20540%20n?frueher=IRF540N"
    assert client.get("/p/GIBTSNICHT").status_code == 404
    # Ohne Umbenennen gibt es keine Meldung.
    assert "heißt jetzt" not in client.get("/p/Irf%20540%20n").text


def test_alias_mehrerer_bauteile_leitet_nicht_weiter(client, lager_voll):
    parts.update_part(lager_voll, "IRF540N", {"aliases": ["TO-220-FET"]})
    parts.update_part(lager_voll, "IRLZ44N", {"aliases": ["TO-220-FET"]})
    client.post("/index/rebuild")
    assert client.get("/p/TO-220-FET", follow_redirects=False).status_code == 404


def test_bearbeiten_verschiebt_in_unterkategorie(client, lager_voll):
    response = client.post(
        "/p/IRF540N/bearbeiten",
        data={**IRF540N_FORM, "unterkategorie": "mosfets/p-kanal"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/p/IRF540N"
    assert (lager_voll / "mosfets" / "p-kanal" / "IRF540N" / "part.yaml").is_file()

    client.post(
        "/p/IRF540N/bearbeiten",
        data={**IRF540N_FORM, "kategorie": "widerstaende", "neue_unterkategorie": "Sonstige"},
    )
    assert (lager_voll / "widerstaende" / "Sonstige" / "IRF540N" / "part.yaml").is_file()
    assert not (lager_voll / "mosfets" / "p-kanal" / "IRF540N").exists()
    # "– keine –" holt das Bauteil aus der Unterkategorie heraus.
    client.post("/p/IRF540N/bearbeiten", data={**IRF540N_FORM, "kategorie": "widerstaende"})
    assert (lager_voll / "widerstaende" / "IRF540N" / "part.yaml").is_file()


def test_bearbeiten_fehler_beim_umbenennen(client, lager_voll):
    response = client.post(
        "/p/IRF540N/bearbeiten",
        data={**IRF540N_FORM, "bezeichnung": "IRLZ44N", "lagerfach": "C-9"},
    )
    assert response.status_code == 400
    assert "Die übrigen Angaben sind gespeichert. Aber: Teil existiert bereits" in response.text
    assert 'name="bezeichnung" value="IRLZ44N"' in response.text  # Eingabe bleibt stehen
    assert doc_of(lager_voll / "mosfets" / "IRF540N")["location"] == "C-9"

    response = client.post(
        "/p/IRF540N/bearbeiten",
        data={**IRF540N_FORM, "kategorie": "widerstaende", "unterkategorie": "mosfets/p-kanal"},
    )
    assert response.status_code == 400
    assert "gehört zu einer anderen Kategorie" in response.text
    assert (lager_voll / "mosfets" / "IRF540N").is_dir()


def test_bearbeiten_ohne_die_neuen_felder_laesst_den_ordner(client, lager_voll):
    # Andere Clients schicken nur die Angaben; Bezeichnung und Ort bleiben dann.
    response = client.post(
        "/p/IRF9540N/bearbeiten", data={"name": "P-Kanal", "menge": "2"}, follow_redirects=False
    )
    assert response.headers["location"] == "/p/IRF9540N"
    assert doc_of(lager_voll / "mosfets" / "p-kanal" / "IRF9540N")["quantity"] == 2


def test_tief_verschachteltes_bauteil_bleibt_beim_bearbeiten_an_seinem_ort(client, lager_voll):
    # Von Hand im Explorer tiefer einsortiert, als das Programm selbst Unterkategorien anlegt.
    deep = lager_voll / "mosfets" / "a" / "b" / "c" / "d" / "TIEF1"
    deep.mkdir(parents=True)
    (deep / "part.yaml").write_text("part: TIEF1\n", encoding="utf-8")
    client.post("/index/rebuild")

    page = client.get("/p/TIEF1/bearbeiten").text
    assert '<option value="mosfets/a/b/c/d" data-kategorie="mosfets" data-kurz="a/b/c/d" selected>' in page
    response = client.post(
        "/p/TIEF1/bearbeiten",
        data={
            "bezeichnung": "TIEF1", "kategorie": "mosfets", "unterkategorie": "mosfets/a/b/c/d",
            "name": "bleibt hier", "menge": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert doc_of(deep)["name"] == "bleibt hier"
    # Umbenennen ändert nur den Ordnernamen, nicht den Ort.
    renamed = parts.move_part(lager_voll, "TIEF1", new_id="Tief 1")
    assert renamed == deep.parent / "Tief 1"


def test_api_umbenennen_und_verschieben(client, lager_voll):
    response = client.patch("/api/v1/parts/IRF540N", json={"part": "IRF 540N", "location": "B-2"})
    assert response.status_code == 200
    data = response.json()
    assert (data["part"], data["location"], data["aliases"]) == ("IRF 540N", "B-2", ["IRF540N"])
    moved = client.patch(
        "/api/v1/parts/IRF%20540N", json={"category": "widerstaende", "subcategory": "Sonstige"}
    ).json()
    assert moved["path"] == "widerstaende/Sonstige/IRF 540N"
    bad = client.patch("/api/v1/parts/IRF%20540N", json={"part": "IRLZ44N"})
    assert bad.status_code == 400
    assert "existiert bereits" in bad.json()["detail"]


def test_cli_umbenennen_und_verschieben(run, lager_voll):
    result = run("part", "rename", "IRF540N", "IRF 540 N", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["teil"] == "IRF 540 N"
    result = run("part", "move", "IRF 540 N", "-c", "widerstaende", "-s", "Sonstige", "--json")
    assert json.loads(result.output)["unterkategorie"] == "Sonstige"
    assert (lager_voll / "widerstaende" / "Sonstige" / "IRF 540 N" / "part.yaml").is_file()
    assert run("part", "move", "IRF 540 N").exit_code == 1
    assert run("part", "rename", "IRF 540 N", "IRLZ44N").exit_code == 1


# ----------------------------------------------------------- Löschen und Papierkorb


def test_bauteil_loeschen_wandert_in_den_papierkorb(lager_voll):
    target = parts.delete_part(lager_voll, "irlz44n")
    assert not (lager_voll / "mosfets" / "IRLZ44N").exists()
    assert target.parent.parent.parent == trash.trash_dir(lager_voll)
    assert target.relative_to(target.parents[1]).as_posix() == "mosfets/IRLZ44N"
    assert (target / "part.yaml").is_file()
    assert (target / "datasheet.pdf").read_bytes() == b"%PDF-1.4 test"
    assert "Wiederherstellen" in (trash.trash_dir(lager_voll) / "LIESMICH.txt").read_text(encoding="utf-8")

    # Der Papierkorb zählt nicht zum Lager: keine Kategorie, kein Bauteil, kein Hinweis.
    result = indexer.rebuild(lager_voll)
    assert result["teile"] == 3
    assert result["warnungen"] == []
    assert parts.find_part_dir(lager_voll, "IRLZ44N") is None
    # Dieselbe Bezeichnung lässt sich danach neu vergeben.
    parts.create_part(lager_voll, "mosfets", "IRLZ44N", {})
    with pytest.raises(ValueError, match="Teil nicht gefunden"):
        parts.delete_part(lager_voll, "GIBTSNICHT")


def test_zweimal_dasselbe_loeschen(lager_voll):
    first = parts.delete_part(lager_voll, "IRF540N")
    parts.create_part(lager_voll, "mosfets", "IRF540N", {})
    second = parts.delete_part(lager_voll, "IRF540N")
    assert first != second
    assert first.is_dir() and second.is_dir()


def test_papierkorb_nimmt_nur_dinge_aus_dem_lager(lager_voll, tmp_path):
    outside = tmp_path / "fremd.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="liegt nicht im Lager"):
        trash.move_to_trash(lager_voll, outside)
    assert outside.exists()


def test_seite_bauteil_loeschen(client, lager_voll):
    without = client.post("/p/IRF540N/loeschen")
    assert without.status_code == 400
    assert "Häkchen setzen" in without.text
    assert (lager_voll / "mosfets" / "IRF540N").is_dir()

    response = client.post("/p/IRF540N/loeschen", data={"sicher": "1"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?hinweis=geloescht&teil=IRF540N"
    page = client.get(response.headers["location"]).text
    assert "IRF540N ist gelöscht. Der Ordner liegt im Papierkorb des Lagers (Ordner _papierkorb)." in page
    assert 'href="/p/IRF540N"' not in page
    assert client.get("/p/IRF540N").status_code == 404
    assert len(trashed(lager_voll, "mosfets/IRF540N")) == 1
    # Für ein Bauteil, das es noch gibt, erscheint die Meldung nicht.
    assert "ist gelöscht" not in client.get("/?hinweis=geloescht&teil=IRLZ44N").text
    assert client.post("/p/GIBTSNICHT/loeschen", data={"sicher": "1"}).status_code == 404


def test_datei_loeschen_im_kern(lager_voll):
    folder = lager_voll / "mosfets" / "IRLZ44N"
    target = files.remove_file(lager_voll, folder, "kicad/TO-220.kicad_mod")
    assert target.name == "TO-220.kicad_mod"
    assert not (folder / "kicad").exists()  # der leere Unterordner ist mit weg
    assert trashed(lager_voll, "mosfets/IRLZ44N/kicad/TO-220.kicad_mod") == [target]
    files.remove_file(lager_voll, folder, "datasheet.pdf")
    assert (folder / "part.yaml").is_file()
    assert (folder / "notiz.txt").is_file()


@pytest.mark.parametrize(
    "rel_path, expected",
    [
        ("part.yaml", "gehört zum Bauteil"),
        ("PART.YAML", "gehört zum Bauteil"),
        ("gibtsnicht.pdf", "Datei nicht gefunden"),
        ("3d", "Datei nicht gefunden"),
        ("../IRF540N/part.yaml", "Ungültiger Dateipfad"),
        ("", "Ungültiger Dateipfad"),
    ],
)
def test_datei_loeschen_fehler(lager_voll, rel_path, expected):
    folder = lager_voll / "mosfets" / "IRLZ44N"
    with pytest.raises(ValueError, match=expected):
        files.remove_file(lager_voll, folder, rel_path)
    assert not trash.trash_dir(lager_voll).exists()


def test_seite_datei_loeschen(client, lager_voll):
    page = client.get("/p/IRLZ44N").text
    assert page.count('action="/p/IRLZ44N/dateien/loeschen"') == 5
    assert 'name="datei" value="3d/TO-220.step"' in page
    assert 'data-confirm="datasheet.pdf löschen?' in page

    response = client.post(
        "/p/IRLZ44N/dateien/loeschen", data={"datei": "datasheet.pdf"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/IRLZ44N?geloescht=datasheet.pdf"
    page = client.get(response.headers["location"]).text
    assert "datasheet.pdf ist gelöscht. Die Datei liegt im Papierkorb des Lagers" in page
    assert "Noch kein Datenblatt im Ordner." in page
    assert client.get("/files/mosfets/IRLZ44N/datasheet.pdf").status_code == 404
    assert len(trashed(lager_voll, "mosfets/IRLZ44N/datasheet.pdf")) == 1
    # Für eine Datei, die es noch gibt, erscheint die Meldung nicht.
    assert "ist gelöscht" not in client.get("/p/IRLZ44N?geloescht=notiz.txt").text

    bad = client.post("/p/IRLZ44N/dateien/loeschen", data={"datei": "part.yaml"})
    assert bad.status_code == 400
    assert "gehört zum Bauteil" in bad.text
    assert client.post("/p/GIBTSNICHT/dateien/loeschen", data={"datei": "a.pdf"}).status_code == 404


def test_api_loeschen(client, lager_voll):
    response = client.delete("/api/v1/parts/IRLZ44N/files/3d/TO-220.step")
    assert response.status_code == 200
    data = response.json()
    assert data["geloescht"] == "3d/TO-220.step"
    assert data["papierkorb"].startswith("_papierkorb/")
    assert data["papierkorb"].endswith("/mosfets/IRLZ44N/3d/TO-220.step")
    assert "3d/TO-220.step" not in [f["path"] for f in data["teil"]["files"]]
    assert client.delete("/api/v1/parts/IRLZ44N/files/part.yaml").status_code == 400
    assert client.delete("/api/v1/parts/GIBTSNICHT/files/a.pdf").status_code == 404

    response = client.delete("/api/v1/parts/irlz44n")
    assert response.status_code == 200
    assert response.json()["geloescht"] == "IRLZ44N"
    assert response.json()["papierkorb"].endswith("/mosfets/IRLZ44N")
    assert client.get("/api/v1/parts/IRLZ44N").status_code == 404
    assert client.delete("/api/v1/parts/IRLZ44N").status_code == 404


def test_cli_loeschen(run, lager_voll):
    result = run("part", "detach", "IRLZ44N", "datasheet.pdf", "images/foto.JPG", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["geloescht"] == ["datasheet.pdf", "images/foto.JPG"]
    assert not (lager_voll / "mosfets" / "IRLZ44N" / "datasheet.pdf").exists()
    failed = run("part", "detach", "IRLZ44N", "notiz.txt", "gibtsnicht.pdf")
    assert failed.exit_code == 1
    assert "bereits gelöscht: notiz.txt" in failed.output

    result = run("part", "remove", "irf540n", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["geloescht"] == "IRF540N"
    assert Path(data["papierkorb"]).is_dir()
    assert run("part", "remove", "IRF540N").exit_code == 1


def test_loeschen_braucht_schreibrecht(geschuetzt, lager_voll):
    page = geschuetzt.get("/p/IRLZ44N").text
    assert "dateien/loeschen" not in page
    assert geschuetzt.post("/p/IRLZ44N/loeschen", data={"sicher": "1"}).status_code == 403
    assert geschuetzt.post("/p/IRLZ44N/dateien/loeschen", data={"datei": "datasheet.pdf"}).status_code == 403
    assert geschuetzt.delete("/api/v1/parts/IRLZ44N").status_code == 403
    assert geschuetzt.delete("/api/v1/parts/IRLZ44N/files/datasheet.pdf").status_code == 403
    assert (lager_voll / "mosfets" / "IRLZ44N" / "datasheet.pdf").is_file()
    allowed = geschuetzt.delete(
        "/api/v1/parts/IRLZ44N/files/datasheet.pdf", headers={"X-Lager-Token": "geheim"}
    )
    assert allowed.status_code == 200


# ------------------------------------------------------- Hochladen mit Rückmeldung


def test_upload_meldet_was_hochgeladen_wurde(client):
    response = client.post(
        "/p/IRF540N/dateien",
        files=[
            ("dateien", ("irf540n.pdf", b"%PDF", "application/pdf")),
            ("dateien", ("TO-220.step", b"step", "application/octet-stream")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/p/IRF540N?hochgeladen=irf540n.pdf&hochgeladen=3d%2FTO-220.step"
    )
    page = client.get(response.headers["location"]).text
    assert "2 Dateien hochgeladen: irf540n.pdf, 3d/TO-220.step." in page
    # Nur was wirklich im Ordner liegt, wird gemeldet.
    assert "hochgeladen:" not in client.get("/p/IRF540N?hochgeladen=erfunden.pdf").text


def test_upload_teils_gespeichert_teils_nicht(client):
    response = client.post(
        "/p/IRF540N/dateien",
        files=[
            ("dateien", ("gut.pdf", b"%PDF", "application/pdf")),
            ("dateien", ("leer.pdf", b"", "application/pdf")),
        ],
    )
    assert response.status_code == 400
    assert "Nicht gespeichert: leer.pdf ist leer." in response.text
    assert "1 Datei hochgeladen: gut.pdf." in response.text


def test_bauteilseite_ist_fuer_das_hochladen_mit_fortschritt_vorbereitet(client):
    page = client.get("/p/IRF540N").text
    assert "data-auto-upload" in page
    assert 'type="file" name="dateien" multiple' in page
    assert "<progress" in page
    script = client.get("/static/app.js").text
    assert "data-auto-upload" in script
    assert "upload.addEventListener('progress'" in script


# ---------------------------------------------------- Ordner-Auswahl für den Lager-Pfad


def fake_dialog(stdout: bytes = b"", returncode: int = 0):
    def run_dialog(title, initial):
        run_dialog.calls.append((title, initial))
        return subprocess.CompletedProcess([], returncode, stdout, b"")

    run_dialog.calls = []
    return run_dialog


def test_ordner_auswahl_im_kern(monkeypatch, tmp_path):
    dialog = fake_dialog("D:\\Lager Größe".encode("utf-8"))
    monkeypatch.setattr(dialogs, "_run_dialog", dialog)
    assert dialogs.pick_folder(tmp_path) == Path("D:\\Lager Größe")
    assert dialog.calls == [("Lager-Ordner auswählen", str(tmp_path))]

    monkeypatch.setattr(dialogs, "_run_dialog", fake_dialog(b""))
    assert dialogs.pick_folder() is None  # abgebrochen

    monkeypatch.setattr(dialogs, "_run_dialog", fake_dialog(b"", returncode=2))
    with pytest.raises(dialogs.DialogUnavailable, match="kein Auswahlfenster"):
        dialogs.pick_folder()

    def timeout(title, initial):
        raise subprocess.TimeoutExpired("dialog", 1)

    monkeypatch.setattr(dialogs, "_run_dialog", timeout)
    with pytest.raises(dialogs.DialogUnavailable):
        dialogs.pick_folder()
    # Nach einem Fehler ist das Fenster wieder frei.
    monkeypatch.setattr(dialogs, "_run_dialog", fake_dialog(b"C:\\x"))
    assert dialogs.pick_folder() == Path("C:\\x")


def test_seite_ordner_waehlen(client, phone, geschuetzt, app, lager_voll, monkeypatch, config_path):
    asked = []

    def pick(initial=None, title=""):
        asked.append(initial)
        return Path("D:\\Neues Lager")

    monkeypatch.setattr(server.dialogmod, "pick_folder", pick)
    before = config_path.read_text(encoding="utf-8")
    response = client.post("/einstellungen/ordner-waehlen")
    assert response.status_code == 200
    assert response.json() == {"pfad": "D:\\Neues Lager"}
    assert asked == [lager_voll]
    # Gewählt ist noch nicht umgestellt: Das passiert erst mit „Übernehmen“.
    assert app.state.root == lager_voll
    assert config_path.read_text(encoding="utf-8") == before

    monkeypatch.setattr(server.dialogmod, "pick_folder", lambda initial=None, title="": None)
    assert client.post("/einstellungen/ordner-waehlen").json() == {"pfad": ""}

    def unavailable(initial=None, title=""):
        raise dialogs.DialogUnavailable("Kein Fenster möglich.")

    monkeypatch.setattr(server.dialogmod, "pick_folder", unavailable)
    failed = client.post("/einstellungen/ordner-waehlen")
    assert failed.status_code == 503
    assert failed.json()["detail"] == "Kein Fenster möglich."

    # Nur am PC des Servers, und nur mit Schreibrecht.
    assert phone.post("/einstellungen/ordner-waehlen").status_code == 403
    assert geschuetzt.post("/einstellungen/ordner-waehlen").status_code == 403
    assert len(asked) == 1


def test_knopf_ordner_auswaehlen_nur_am_server_pc(client, phone):
    assert 'data-pick-folder="/einstellungen/ordner-waehlen"' in client.get("/").text
    assert "data-pick-folder" not in phone.get("/").text
