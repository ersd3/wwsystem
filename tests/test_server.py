"""Tests für den Server (lesend): REST-API, Dateien, Handy-Seiten.

Die Fixtures client, phone, geschuetzt, app und config_path stehen in conftest.py.
"""
from lager import __version__


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok", "version": __version__}


def test_api_suche(client):
    data = client.get("/api/v1/parts", params={"q": "irlz44n"}).json()
    assert data["anzahl"] == 1
    part = data["treffer"][0]
    assert part["part"] == "IRLZ44N"
    assert part["category_label"] == "MOSFETs"
    assert part["files"][0]["path"] == "datasheet.pdf"


def test_api_suche_umlaut_und_kategorie(client):
    data = client.get("/api/v1/parts", params={"q": "widerstände"}).json()
    assert [p["part"] for p in data["treffer"]] == ["223-0.1W"]
    data = client.get("/api/v1/parts", params={"category": "mosfets"}).json()
    assert data["anzahl"] == 3


def test_api_limit_wird_geprueft(client):
    assert client.get("/api/v1/parts", params={"limit": 0}).status_code == 422


def test_api_bauteil_und_404(client):
    assert client.get("/api/v1/parts/irlz44n").json()["part"] == "IRLZ44N"
    missing = client.get("/api/v1/parts/GIBTSNICHT")
    assert missing.status_code == 404
    assert "nicht gefunden" in missing.json()["detail"]


def test_api_kategorien(client):
    cats = client.get("/api/v1/categories").json()
    assert [(c["id"], c["parts"]) for c in cats] == [("mosfets", 3), ("widerstaende", 1)]


def test_api_index_status_und_rebuild(client, lager_voll):
    assert client.get("/api/v1/index").json()["teile"] == 4
    (lager_voll / "widerstaende" / "223-0.1W" / "datenblatt.pdf").write_bytes(b"%PDF")
    result = client.post("/api/v1/index/rebuild").json()
    assert result["dateien_nach_art"]["datasheet"] == 3


def test_schreibschutz_mit_token(geschuetzt):
    client = geschuetzt
    assert client.post("/api/v1/index/rebuild").status_code == 403
    assert client.post("/api/v1/index/rebuild", headers={"X-Lager-Token": "falsch"}).status_code == 403
    ok = client.post("/api/v1/index/rebuild", headers={"X-Lager-Token": "geheim"})
    assert ok.status_code == 200
    assert client.post("/index/rebuild").status_code == 403
    # Lesen bleibt ohne Token möglich, der Knopf zum Einlesen ist ausgeblendet.
    page = client.get("/")
    assert page.status_code == 200
    assert "Ordner neu einlesen" not in page.text


def test_datei_pdf_wird_im_browser_geoeffnet(client):
    response = client.get("/files/mosfets/IRLZ44N/datasheet.pdf")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 test"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")


def test_datei_andere_art_wird_heruntergeladen(client):
    response = client.get("/files/mosfets/IRLZ44N/kicad/TO-220.kicad_mod")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")


def test_datei_nur_aus_dem_index(client):
    assert client.get("/files/mosfets/IRLZ44N/part.yaml").status_code == 404
    assert client.get("/files/categories.yaml").status_code == 404
    assert client.get("/files/mosfets/IRLZ44N/%2E%2E/%2E%2E/categories.yaml").status_code == 404
    assert client.get("/files/mosfets/IRLZ44N/gibtsnicht.pdf").status_code == 404


def test_datei_im_index_aber_geloescht(client, lager_voll):
    (lager_voll / "mosfets" / "IRLZ44N" / "datasheet.pdf").unlink()
    assert client.get("/files/mosfets/IRLZ44N/datasheet.pdf").status_code == 404


def test_seite_suche(client):
    page = client.get("/", params={"q": "irlz"})
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "IRLZ44N" in page.text
    assert 'href="/p/IRLZ44N"' in page.text
    assert 'href="/files/mosfets/IRLZ44N/datasheet.pdf"' in page.text
    assert "IRF540N" not in page.text
    assert "Ordner neu einlesen" in page.text


def test_seite_mehrere_datenblaetter(client, lager_voll):
    (lager_voll / "mosfets" / "IRLZ44N" / "anwendung.pdf").write_bytes(b"%PDF")
    client.post("/index/rebuild")
    page = client.get("/", params={"q": "irlz44n"}).text
    # Das erste Datenblatt direkt, die weiteren über "+1" auf der Bauteilseite.
    assert 'href="/files/mosfets/IRLZ44N/anwendung.pdf"' in page
    assert 'href="/files/mosfets/IRLZ44N/datasheet.pdf"' not in page
    assert ">+1</a>" in page


def test_seite_ohne_treffer(client):
    page = client.get("/", params={"q": "gibtsnicht"})
    assert page.status_code == 200
    assert "Keine Treffer" in page.text


def test_seite_sonderzeichen_werden_maskiert(client):
    page = client.get("/", params={"q": '<script>alert(1)</script>"'})
    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text


def test_seite_bauteil(client):
    page = client.get("/p/irlz44n")
    assert page.status_code == 200
    for expected in ("IRLZ44N", "Infineon", "A-03-2", "Datenblätter", "PDF öffnen", "KiCad", "3D-Modell"):
        assert expected in page.text


def test_seite_bauteil_unbekannt(client):
    page = client.get("/p/GIBTSNICHT")
    assert page.status_code == 404
    assert "Kein Bauteil" in page.text


def test_seite_neu_einlesen(client, lager_voll):
    (lager_voll / "mosfets" / "IRF540N" / "irf540n.pdf").write_bytes(b"%PDF")
    response = client.post("/index/rebuild", follow_redirects=False)
    assert response.status_code == 303
    assert 'href="/files/mosfets/IRF540N/irf540n.pdf"' in client.get("/", params={"q": "irf540n"}).text


def test_openapi_beschreibt_die_api(client):
    spec = client.get("/openapi.json").json()
    assert "/api/v1/parts" in spec["paths"]
    assert "/api/v1/parts/{part}" in spec["paths"]
    assert "/files/{rel_path}" in spec["paths"]
    assert "/p/{part}" not in spec["paths"]
    assert "Part" in spec["components"]["schemas"]
