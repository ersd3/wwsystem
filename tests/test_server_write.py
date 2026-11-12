"""Tests für den Server (schreibend): Lager-Ordner ändern, Bauteile anlegen, Dateien hochladen."""
import pytest

from lager import categories, config, parts
from lager import root as rootmod

EMPTY_FILE_FIELD = ("dateien", ("", b"", "application/octet-stream"))


def pdf(name="datenblatt.pdf", content=b"%PDF-1.4 neu"):
    return ("dateien", (name, content, "application/pdf"))


# ------------------------------------------- Rückmeldung nach dem Einlesen


def test_neu_einlesen_gibt_rueckmeldung(client, lager_voll):
    (lager_voll / "mosfets" / "IRF540N" / "irf540n.pdf").write_bytes(b"%PDF")
    response = client.post("/index/rebuild", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?hinweis=eingelesen"
    page = client.get(response.headers["location"]).text
    assert "Ordner neu eingelesen: 4 Bauteile, 7 Dateien, 2 Kategorien" in page
    assert "beim Einlesen" not in page
    # Ohne den Hinweis in der Adresse erscheint die Meldung nicht (z. B. nach Neuladen der Startseite).
    assert "Ordner neu eingelesen" not in client.get("/").text


def test_neu_einlesen_zeigt_hinweise_aus_den_ordnern(client, lager_voll):
    lose = lager_voll / "LOSE"
    lose.mkdir()
    (lose / "part.yaml").write_text("part: LOSE\n", encoding="utf-8")
    page = client.post("/index/rebuild").text  # folgt der Weiterleitung
    assert "Ordner neu eingelesen: 4 Bauteile" in page
    assert "1 Hinweis beim Einlesen" in page
    assert "ohne Kategorie" in page


def test_lager_ordner_wechsel_gibt_rueckmeldung(client, tmp_path):
    new = tmp_path / "leer"
    page = client.post("/einstellungen/lager-ordner", data={"pfad": str(new), "anlegen": "1"}).text
    assert "Lager-Ordner umgestellt und eingelesen: 0 Bauteile, 0 Dateien, 0 Kategorien" in page


# ---------------------------------------------- Lager-Ordner sehen und ändern


def test_fusszeile_zeigt_lager_ordner(client, phone, lager_voll):
    page = client.get("/").text
    assert str(lager_voll) in page
    assert "Lager-Ordner ändern" in page
    remote = phone.get("/").text
    assert str(lager_voll) in remote
    assert "Lager-Ordner ändern" not in remote
    assert "nur an dem PC ändern" in remote


def test_lager_ordner_wechseln(client, app, tmp_path, config_path):
    other = tmp_path / "zweites lager"
    rootmod.create_structure(other)
    categories.add(other, "dioden", "Dioden")
    parts.create_part(other, "dioden", "1N4148", {"name": "Schaltdiode"})

    response = client.post(
        "/einstellungen/lager-ordner", data={"pfad": f'"{other}"'}, follow_redirects=False
    )
    assert response.status_code == 303
    assert app.state.root == other.resolve()
    found = client.get("/api/v1/parts").json()
    assert [p["part"] for p in found["treffer"]] == ["1N4148"]
    assert str(other) in client.get("/").text

    assert "# Test-Konfiguration" in config_path.read_text(encoding="utf-8")
    cfg = config.load_config(config_path)
    assert config.resolve_lager_root(cfg, config_path) == other.resolve()


def test_lager_ordner_ohne_lager_wird_abgelehnt(client, app, lager_voll, tmp_path, config_path):
    before = config_path.read_text(encoding="utf-8")
    response = client.post("/einstellungen/lager-ordner", data={"pfad": str(tmp_path / "gibtsnicht")})
    assert response.status_code == 400
    assert "kein Lager" in response.text
    assert "Häkchen" in response.text
    assert app.state.root == lager_voll
    assert config_path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "gibtsnicht").exists()


def test_lager_ordner_neu_anlegen(client, app, tmp_path):
    new = tmp_path / "neu" / "Lager"
    response = client.post(
        "/einstellungen/lager-ordner", data={"pfad": str(new), "anlegen": "1"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert (new / "categories.yaml").is_file()
    assert app.state.root == new.resolve()
    assert client.get("/api/v1/parts").json()["anzahl"] == 0


def test_lager_ordner_nicht_leer_wird_nicht_angefasst(client, app, lager_voll, tmp_path):
    full = tmp_path / "voll"
    full.mkdir()
    (full / "wichtig.txt").write_text("x", encoding="utf-8")
    response = client.post("/einstellungen/lager-ordner", data={"pfad": str(full), "anlegen": "1"})
    assert response.status_code == 400
    assert "nicht leer" in response.text
    assert sorted(p.name for p in full.iterdir()) == ["wichtig.txt"]
    assert app.state.root == lager_voll


def test_lager_ordner_braucht_vollstaendigen_pfad(client):
    assert client.post("/einstellungen/lager-ordner", data={"pfad": "lager"}).status_code == 400
    assert client.post("/einstellungen/lager-ordner", data={"pfad": "  "}).status_code == 400


def test_lager_ordner_nur_am_server_pc(phone, app, lager_voll, tmp_path):
    other = tmp_path / "anderes"
    rootmod.create_structure(other)
    response = phone.post("/einstellungen/lager-ordner", data={"pfad": str(other)})
    assert response.status_code == 403
    assert app.state.root == lager_voll


# ----------------------------------------------------- Neues Bauteil


def test_seite_neu_zeigt_formular(client):
    page = client.get("/neu", params={"kategorie": "widerstaende"})
    assert page.status_code == 200
    assert "Neues Bauteil" in page.text
    assert '<option value="mosfets">MOSFETs</option>' in page.text
    assert '<option value="widerstaende" selected>Widerstände</option>' in page.text
    assert 'href="/neu"' in client.get("/").text


def test_neues_bauteil_mit_datenblatt(client, lager_voll):
    response = client.post(
        "/neu",
        data={
            "bezeichnung": " bc547 ", "kategorie": "mosfets", "name": "NPN-Transistor",
            "hersteller": "onsemi", "lagerfach": "B-01", "menge": "12",
            "tags": "npn, to-92", "aliase": "BC547B", "notizen": "Standardtyp",
        },
        files=[pdf("BC547.pdf")],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/BC547"
    part = client.get("/api/v1/parts/BC547").json()
    assert part["name"] == "NPN-Transistor"
    assert part["manufacturer"] == "onsemi"
    assert part["location"] == "B-01"
    assert part["quantity"] == 12
    assert part["tags"] == ["npn", "to-92"]
    assert part["aliases"] == ["BC547B"]
    assert part["notes"] == "Standardtyp"
    assert [f["path"] for f in part["files"]] == ["BC547.pdf"]
    assert (lager_voll / "mosfets" / "BC547" / "part.yaml").is_file()
    assert client.get("/files/mosfets/BC547/BC547.pdf").content == b"%PDF-1.4 neu"


def test_neues_bauteil_ohne_datei_wie_vom_browser(client):
    # Ein leeres Dateifeld schickt der Browser als Datei ohne Namen mit.
    response = client.post(
        "/neu",
        data={"bezeichnung": "BC557", "kategorie": "mosfets"},
        files=[EMPTY_FILE_FIELD],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/api/v1/parts/BC557").json()["files"] == []


def test_neues_bauteil_mit_neuer_kategorie(client):
    response = client.post(
        "/neu",
        data={"bezeichnung": "100NF-50V", "neue_kategorie": "Kondensatoren & Co"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    part = client.get("/api/v1/parts/100NF-50V").json()
    assert part["category"] == "kondensatoren-co"
    assert part["category_label"] == "Kondensatoren & Co"
    # Dieselbe neue Kategorie ein zweites Mal eintragen nutzt die vorhandene.
    again = client.post(
        "/neu",
        data={"bezeichnung": "10UF-25V", "neue_kategorie": "kondensatoren co"},
        follow_redirects=False,
    )
    assert again.status_code == 303
    cats = {c["id"]: c["parts"] for c in client.get("/api/v1/categories").json()}
    assert cats["kondensatoren-co"] == 2


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"bezeichnung": "irlz44n", "kategorie": "widerstaende"}, "existiert bereits"),
        ({"bezeichnung": "NEU1"}, "Kategorie wählen"),
        ({"bezeichnung": "NEU1", "kategorie": "gibtsnicht"}, "Kategorie existiert nicht"),
        ({"bezeichnung": "NEU1", "kategorie": "../fremd"}, "Kategorie existiert nicht"),
        ({"bezeichnung": "   ", "kategorie": "mosfets"}, "Bezeichnung eintragen"),
        ({"bezeichnung": "???", "kategorie": "mosfets"}, "Ungültige Bauteil-Bezeichnung"),
        ({"bezeichnung": "NEU1", "kategorie": "mosfets", "menge": "viele"}, "ganze Zahl"),
    ],
)
def test_neues_bauteil_fehler_bleiben_im_formular(client, lager_voll, data, expected):
    (lager_voll.parent / "fremd").mkdir(exist_ok=True)
    response = client.post("/neu", data={"name": "Mein Text", **data})
    assert response.status_code == 400
    assert expected in response.text
    assert 'value="Mein Text"' in response.text
    assert client.get("/api/v1/parts/NEU1").status_code == 404
    assert not (lager_voll.parent / "fremd" / "NEU1").exists()


def test_neues_bauteil_datei_fehler_wird_gemeldet(client):
    response = client.post(
        "/neu",
        data={"bezeichnung": "BC337", "kategorie": "mosfets"},
        files=[("dateien", ("part.yaml", b"part: BOESE\n", "text/yaml"))],
    )
    assert response.status_code == 200
    assert "Das Bauteil ist angelegt" in response.text
    assert client.get("/api/v1/parts/BC337").json()["part"] == "BC337"


# ------------------------------------------------- Dateien hinzufügen


def test_upload_zu_bauteil(client):
    response = client.post(
        "/p/irf540n/dateien",
        files=[pdf("irf540n.pdf"), ("dateien", ("TO-220.step", b"step", "application/octet-stream"))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/p/IRF540N"
    paths = [f["path"] for f in client.get("/api/v1/parts/IRF540N").json()["files"]]
    assert paths == ["irf540n.pdf", "3d/TO-220.step"]
    page = client.get("/p/IRF540N").text
    assert "Dateien hinzufügen" in page
    assert 'href="/files/mosfets/IRF540N/irf540n.pdf"' in page


def test_upload_ueberschreibt_nicht(client, lager_voll):
    client.post("/p/IRLZ44N/dateien", files=[pdf("datasheet.pdf", b"%PDF neu")])
    folder = lager_voll / "mosfets" / "IRLZ44N"
    assert (folder / "datasheet.pdf").read_bytes() == b"%PDF-1.4 test"
    assert (folder / "datasheet-2.pdf").read_bytes() == b"%PDF neu"


def test_upload_ohne_datei(client):
    response = client.post("/p/IRLZ44N/dateien", files=[EMPTY_FILE_FIELD])
    assert response.status_code == 400
    assert "keine Datei ausgewählt" in response.text


def test_upload_part_yaml_wird_abgelehnt(client, lager_voll):
    target = lager_voll / "mosfets" / "IRLZ44N" / "part.yaml"
    original = target.read_bytes()
    response = client.post(
        "/p/IRLZ44N/dateien", files=[("dateien", ("../part.yaml", b"part: BOESE\n", "text/yaml"))]
    )
    assert response.status_code == 400
    assert "Nicht gespeichert" in response.text
    assert target.read_bytes() == original


def test_upload_unbekanntes_bauteil(client):
    assert client.post("/p/GIBTSNICHT/dateien", files=[pdf()]).status_code == 404


def test_svg_wird_nicht_im_browser_ausgefuehrt(client):
    client.post(
        "/p/IRLZ44N/dateien",
        files=[("dateien", ("bild.svg", b"<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "image/svg+xml"))],
    )
    response = client.get("/files/mosfets/IRLZ44N/images/bild.svg")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------ Schreiben per API


def test_api_bauteil_anlegen(client):
    response = client.post(
        "/api/v1/parts",
        json={"part": "ne555", "category": "mosfets", "name": "Timer", "tags": ["timer"], "quantity": 3},
    )
    assert response.status_code == 201
    assert response.json()["part"] == "NE555"
    assert response.json()["tags"] == ["timer"]
    assert response.json()["quantity"] == 3
    duplicate = client.post("/api/v1/parts", json={"part": "NE555", "category": "widerstaende"})
    assert duplicate.status_code == 400
    assert "existiert bereits" in duplicate.json()["detail"]
    assert client.post("/api/v1/parts", json={"part": "X1", "category": ".."}).status_code == 400


def test_api_dateien_hochladen(client):
    response = client.post(
        "/api/v1/parts/IRF540N/files",
        files=[("files", ("irf540n.pdf", b"%PDF", "application/pdf"))],
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hinzugefuegt"] == ["irf540n.pdf"]
    assert data["fehler"] == []
    assert data["teil"]["files"][0]["kind"] == "datasheet"
    bad = client.post(
        "/api/v1/parts/IRF540N/files", files=[("files", ("part.yaml", b"x", "text/yaml"))]
    )
    assert bad.status_code == 400
    missing = client.post(
        "/api/v1/parts/GIBTSNICHT/files", files=[("files", ("a.pdf", b"x", "application/pdf"))]
    )
    assert missing.status_code == 404


def test_api_kategorie_anlegen(client, lager_voll):
    response = client.post("/api/v1/categories", json={"id": "Dioden", "label": "Dioden"})
    assert response.status_code == 201
    assert response.json() == {"id": "dioden", "label": "Dioden", "listed": True, "parts": 0}
    assert (lager_voll / "dioden").is_dir()
    assert client.post("/api/v1/categories", json={"id": "dioden"}).status_code == 400


def test_schreibschutz_gilt_fuer_alle_schreibwege(geschuetzt, lager_voll):
    client = geschuetzt
    token = {"X-Lager-Token": "geheim"}
    api_file = [("files", ("a.pdf", b"x", "application/pdf"))]
    assert client.post("/neu", data={"bezeichnung": "X1", "kategorie": "mosfets"}).status_code == 403
    assert client.post("/p/IRLZ44N/dateien", files=[pdf()]).status_code == 403
    assert client.post("/einstellungen/lager-ordner", data={"pfad": str(lager_voll)}).status_code == 403
    assert client.post("/api/v1/parts", json={"part": "X1", "category": "mosfets"}).status_code == 403
    assert client.post("/api/v1/categories", json={"id": "x"}).status_code == 403
    assert client.post("/api/v1/parts/IRLZ44N/files", files=api_file).status_code == 403
    created = client.post(
        "/api/v1/parts", json={"part": "X1", "category": "mosfets"}, headers=token
    )
    assert created.status_code == 201

    page = client.get("/p/IRLZ44N").text
    assert "Dateien hinzufügen" not in page
    assert 'href="/neu"' not in page
    assert "Lager-Ordner ändern" not in page
    assert "Schreibschutz ist aktiv" in client.get("/neu").text
