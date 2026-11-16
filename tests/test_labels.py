"""Tests für die QR-Etiketten (Phase 3a): Adresse, QR-Code, Aufbau, Seite /etiketten, CLI.

Das Netz ist in allen Tests fest vorgegeben (Fixture `netz` in conftest.py): Der PC heißt
TestPC, hat die IP 192.168.0.10, und der Router löst testpc.fritz.box und lager.fritz.box auf.
"""
import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from conftest import LOCAL, TEST_IP
from lager import cli, config, labels
from lager.server.app import create_app

BASE = "http://lager.fritz.box:8080"


# ------------------------------------------------------------- Adresse


@pytest.mark.parametrize(
    "part, expected",
    [
        ("IRLZ44N", "http://lager.fritz.box:8080/p/IRLZ44N"),
        ("223-0.1W", "http://lager.fritz.box:8080/p/223-0.1W"),
        ("LM317+ADJ", "http://lager.fritz.box:8080/p/LM317+ADJ"),
        ("Mein Teil", "http://lager.fritz.box:8080/p/Mein%20Teil"),
        ("WIDERSTÄNDE", "http://lager.fritz.box:8080/p/WIDERST%C3%84NDE"),
    ],
)
def test_part_url(part, expected):
    assert labels.part_url(BASE, part) == expected
    assert labels.part_url(BASE + "/", part) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://lager.fritz.box:8080", "http://lager.fritz.box:8080"),
        ("  lager.fritz.box:8080/  ", "http://lager.fritz.box:8080"),
        ("HTTP://Lager.Fritz.Box:8080", "http://lager.fritz.box:8080"),
        ("192.168.0.10:8080", "http://192.168.0.10:8080"),
        ("https://lager.example.org/lager/", "https://lager.example.org/lager"),
        ("lager", "http://lager"),
    ],
)
def test_normalize_base_url(raw, expected):
    assert labels.normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "http://", "ftp://lager.fritz.box", "lager fritz box", "http://lager:port",
     "http://lager.fritz.box/?x=1", "http://lager.fritz.box/#teil", "http://nutzer@lager.fritz.box"],
)
def test_normalize_base_url_lehnt_ab(raw):
    with pytest.raises(ValueError):
        labels.normalize_base_url(raw)


def test_vorschlag_nimmt_den_namen_den_der_router_aufloest():
    assert labels.suggest_base_url(8080) == "http://testpc.fritz.box:8080"
    assert labels.suggest_base_url(80) == "http://testpc.fritz.box"


def test_vorschlag_faellt_auf_die_ip_zurueck():
    # Der Router kennt den Namen nicht.
    assert labels.suggest_base_url(8080, hostname="unbekannt") == f"http://{TEST_IP}:8080"
    # Der Name zeigt auf einen anderen Rechner.
    assert labels.suggest_base_url(8080, hostname="anderer") == f"http://{TEST_IP}:8080"
    # Ein Rechnername, der kein gültiger DNS-Name ist.
    assert labels.suggest_base_url(8080, hostname="mein pc") == f"http://{TEST_IP}:8080"


def test_vorschlag_ohne_netz_ist_leer():
    assert labels.suggest_base_url(8080, lan_ip="") == ""


def test_pruefung_unauffaellige_adresse():
    assert labels.check_base_url("http://lager.fritz.box:8080") == []
    assert labels.check_base_url("http://testpc.fritz.box") == []


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://localhost:8080", "erreicht nur dieser PC"),
        ("http://127.0.0.1:8080", "erreicht nur dieser PC"),
        (f"http://{TEST_IP}:8080", "feste IP"),
        ("http://192.168.0.99:8080", "gehört nicht zu diesem PC"),
        ("http://tippfehler.fritz.box:8080", "nicht auflösen"),
        ("http://anderer.fritz.box:8080", "nicht auf diesen PC"),
        ("http://testpc:8080", "Kurznamen"),
        ("http://testpc.local:8080", ".local"),
    ],
)
def test_pruefung_meldet_auffaelliges(url, expected):
    assert any(expected in note for note in labels.check_base_url(url))


def test_pruefung_eigene_ip_ist_nur_ein_hinweis_auf_die_feste_ip():
    notes = labels.check_base_url(f"http://{TEST_IP}:8080")
    assert len(notes) == 1
    assert "gehört nicht" not in notes[0]


# ------------------------------------------------------------- Größen


def test_feste_groessen_und_standard():
    assert labels.resolve_size().id == labels.DEFAULT_SIZE
    assert (labels.resolve_size("gross").width, labels.resolve_size("gross").height) == (70, 37)
    assert labels.resolve_size(" KLEIN ").id == "klein"
    assert labels.resolve_size("klein").title == "Klein · 38 × 21 mm"


def test_eigene_groesse():
    size = labels.resolve_size("eigen", "52,5", " 30 ")
    assert (size.id, size.width, size.height) == ("eigen", 52.5, 30.0)
    assert size.title == "Eigene Größe · 52,5 × 30 mm"


@pytest.mark.parametrize(
    "args",
    [("riesig",), ("eigen", "", ""), ("eigen", "abc", "20"), ("eigen", "5", "5"),
     ("eigen", "500", "20"), ("eigen", "50", "nan"), ("eigen", "inf", "20")],
)
def test_groesse_fehler(args):
    with pytest.raises(ValueError):
        labels.resolve_size(*args)


def test_format_mm():
    assert [labels.format_mm(v) for v in (38.0, 52.5, 0.55, 1.0)] == ["38", "52,5", "0,6", "1"]
    assert labels.format_mm(0.547, 2) == "0,55"


# ------------------------------------------------------------- QR-Code


def test_qr_code_fuer_eine_bauteilseite():
    qr = labels.make_qr(labels.part_url(BASE, "IRLZ44N"))
    assert qr.data == "http://lager.fritz.box:8080/p/IRLZ44N"
    # 37 Zeichen passen in einen Code mit 29 Punkten Kantenlänge, dazu 2 Punkte Ruhezone je Seite.
    assert qr.modules == 33
    assert qr.svg.startswith("<svg") and 'viewBox="0 0 33 33"' in qr.svg
    assert "width=" not in qr.svg.split(">")[0]  # ohne feste Größe: der Kasten bestimmt sie
    assert qr.module_mm(16.5) == pytest.approx(0.5)


def test_qr_code_waechst_mit_der_laenge_der_adresse():
    short = labels.make_qr(labels.part_url(BASE, "IRLZ44N"))
    long = labels.make_qr(labels.part_url(BASE, "ATMEGA328P-PU-MIT-LANGEM-ZUSATZ"))
    assert long.modules > short.modules


def test_qr_bild_als_datei():
    url = labels.part_url(BASE, "IRLZ44N")
    assert labels.qr_image(url, "png").startswith(b"\x89PNG\r\n")
    assert b"<svg" in labels.qr_image(url, "svg")
    assert len(labels.qr_image(url, "png", scale=20)) > len(labels.qr_image(url, "png", scale=2))
    for kind, scale in (("gif", 10), ("png", 0), ("png", 99)):
        with pytest.raises(ValueError):
            labels.qr_image(url, kind, scale)


# ------------------------------------------------------ Aufbau Etikett


ALL_SIZES = [size.id for size in labels.SIZES]


def _inside(box, width, height):
    return box.x >= 0 and box.y >= 0 and box.x + box.width <= width + 1e-6 and box.y + box.height <= height + 1e-6


@pytest.mark.parametrize("size_id", ALL_SIZES)
def test_aufbau_liegt_im_etikett_und_ueberlappt_nicht(size_id):
    size = labels.resolve_size(size_id)
    geo = labels.geometry(size)
    assert _inside(geo.qr, size.width, size.height)
    assert _inside(geo.text, size.width, size.height)
    assert geo.qr.width == pytest.approx(geo.qr.height)  # der Code bleibt quadratisch
    assert geo.qr.width > 0 and geo.text.width > 0 and geo.text.height > 0
    if geo.stacked:
        assert geo.qr.y + geo.qr.height <= geo.text.y + 1e-6
    else:
        assert geo.qr.x + geo.qr.width <= geo.text.x + 1e-6


def test_schmales_etikett_setzt_den_text_unter_den_code():
    assert labels.geometry(labels.resolve_size("eigen", "20", "25")).stacked is True
    assert labels.geometry(labels.resolve_size("klein")).stacked is False


def test_kurze_bezeichnung_steht_in_einer_zeile():
    geo = labels.geometry(labels.resolve_size("klein"))
    text = labels.fit_text(geo, "IRLZ44N", "MOSFET N-Kanal 55 V / 47 A, TO-220", "A-03-2")
    assert text.id_parts == ("IRLZ44N",)
    assert text.id_size >= labels.TWO_LINE_BELOW_MM
    assert text.name_lines >= 1
    assert text.show_location is True
    # Bezeichnung, Beschreibung und Fach passen zusammen in die Höhe des Textkastens.
    used = text.id_size * 1.2 + (text.name_lines + 1) * text.small_size * 1.2
    assert used <= geo.text.height + 1e-6


def test_lange_bezeichnung_kommt_auf_zwei_zeilen_und_wird_groesser():
    geo = labels.geometry(labels.resolve_size("klein"))
    text = labels.fit_text(geo, "ATMEGA328P-PU")
    one_line = geo.text.width / (labels.CHAR_WIDTH * len("ATMEGA328P-PU"))
    assert text.id_parts == ("ATMEGA3", "28P-PU")
    assert text.id_lines == 2
    assert text.id_size > one_line * 1.25
    # Jede der beiden Zeilen passt in die Breite.
    assert labels.CHAR_WIDTH * 7 * text.id_size <= geo.text.width + 1e-6
    # Beide Zeilen der Bezeichnung und der Rest passen in die Höhe.
    full = labels.fit_text(geo, "ATMEGA328P-PU", "Mikrocontroller 8 Bit, DIP-28", "B-01-1")
    used = 2 * full.id_size * 1.2 + (full.name_lines + 1) * full.small_size * 1.2
    assert used <= geo.text.height + 1e-6


@pytest.mark.parametrize(
    "part_id, expected",
    [
        ("R-10K-0.25W", ("R-10K-", "0.25W")),      # Trennzeichen nahe der Mitte
        ("R-1K-0.25W", ("R-1K-", "0.25W")),
        ("R-100K-0.25W", ("R-100K-", "0.25W")),
        ("ATMEGA328P-PU", ("ATMEGA3", "28P-PU")),  # Trennzeichen zu weit hinten: Mitte
        ("LM2596S-ADJ", ("LM2596", "S-ADJ")),
        ("SN74HC595N", ("SN74H", "C595N")),         # kein Trennzeichen: Mitte
        ("AB-CD", ("AB-", "CD")),
    ],
)
def test_bezeichnung_teilen(part_id, expected):
    assert labels.split_id(part_id) == expected
    assert "".join(labels.split_id(part_id)) == part_id


def test_text_auswahl():
    geo = labels.geometry(labels.resolve_size("mittel"))
    assert labels.fit_text(geo, "X1", "Name", "A-1", show_name=False).name_lines == 0
    assert labels.fit_text(geo, "X1", "Name", "A-1", show_location=False).show_location is False
    assert labels.fit_text(geo, "X1", "Name", "").show_location is False
    assert labels.fit_text(geo, "X1", "", "A-1").name_lines == 0
    stacked = labels.geometry(labels.resolve_size("eigen", "20", "25"))
    only_id = labels.fit_text(stacked, "IRLZ44N", "Name", "A-1")
    assert (only_id.name_lines, only_id.show_location) == (0, False)
    assert only_id.id_size >= labels.MIN_TEXT_MM


# ------------------------------------------------------------ Seiten


@pytest.mark.parametrize("size_id", ALL_SIZES)
def test_raster_bleibt_im_bedruckbaren_bereich(size_id):
    size = labels.resolve_size(size_id)
    layout = labels.sheet_layout(size)
    assert layout.columns >= 1 and layout.rows >= 1
    assert layout.offset_x >= labels.PAGE_MARGIN - 1e-6
    assert layout.offset_y >= labels.PAGE_MARGIN - 1e-6
    assert layout.offset_x + layout.columns * size.width <= labels.PAGE_WIDTH - labels.PAGE_MARGIN + 1e-6
    assert layout.offset_y + layout.rows * size.height <= labels.PAGE_HEIGHT - labels.PAGE_MARGIN + 1e-6


def test_raster_klein_und_groesstes_etikett():
    klein = labels.sheet_layout(labels.resolve_size("klein"))
    assert (klein.columns, klein.rows, klein.per_sheet) == (5, 13, 65)
    full = labels.sheet_layout(labels.resolve_size("eigen", "190", "277"))
    assert (full.columns, full.rows, full.offset_x, full.offset_y) == (1, 1, 10.0, 10.0)


def _parts(count):
    return [{"part": f"TEIL{i:03d}", "name": f"Bauteil {i}", "location": "A-1"} for i in range(count)]


def test_etiketten_werden_auf_seiten_verteilt():
    size = labels.resolve_size("klein")
    result = labels.prepare(_parts(70), BASE, size)
    assert result.count == 70
    assert [len(sheet) for sheet in result.sheets] == [65, 5]
    first = result.sheets[0]
    assert first[0].url == "http://lager.fritz.box:8080/p/TEIL000"
    assert first[0].qr.data == first[0].url
    assert (first[0].x, first[0].y) == (result.layout.offset_x, result.layout.offset_y)
    assert (first[1].x, first[1].y) == (result.layout.offset_x + 38, result.layout.offset_y)
    assert (first[5].x, first[5].y) == (result.layout.offset_x, result.layout.offset_y + 21)
    assert len({(label.x, label.y) for label in first}) == 65  # kein Platz doppelt belegt
    # Die zweite Seite beginnt wieder oben links.
    assert (result.sheets[1][0].x, result.sheets[1][0].y) == (first[0].x, first[0].y)
    assert result.min_module_mm == pytest.approx(result.geometry.qr.width / 33, abs=0.001)
    assert result.min_module_mm >= labels.MIN_MODULE_MM


def test_keine_bauteile_keine_seiten():
    result = labels.prepare([], BASE, labels.resolve_size("klein"))
    assert (result.count, result.sheets, result.min_module_mm) == (0, [], 0.0)


def test_mini_etikett_ist_fuer_handys_grenzwertig():
    result = labels.prepare(_parts(1), BASE, labels.resolve_size("mini"))
    assert 0 < result.min_module_mm < labels.MIN_MODULE_MM


# ------------------------------------------- Adresse in der config.yaml


def test_set_public_url_erhaelt_kommentare(config_path):
    config.set_public_url("http://lager.fritz.box:8080", config_path)
    text = config_path.read_text(encoding="utf-8")
    assert "# Test-Konfiguration" in text
    assert "# Adresse für die QR-Etiketten" in text
    assert '  public_url: "http://lager.fritz.box:8080"' in text
    cfg = config.load_config(config_path)
    assert cfg["server"] == {"host": "127.0.0.1", "port": 8080, "public_url": "http://lager.fritz.box:8080"}
    assert cfg["lager_root"] == "lager"
    config.set_public_url("", config_path)
    assert config.load_config(config_path)["server"]["public_url"] == ""


def test_set_public_url_ohne_passende_zeile(tmp_path):
    cp = tmp_path / "config.yaml"
    cp.write_text('lager_root: "lager"\nwrite_token: "geheim"\n', encoding="utf-8")
    config.set_public_url("http://lager.fritz.box:8080", cp)
    cfg = config.load_config(cp)
    assert cfg["server"]["public_url"] == "http://lager.fritz.box:8080"
    assert (cfg["lager_root"], cfg["write_token"]) == ("lager", "geheim")
    missing = tmp_path / "neu.yaml"
    config.set_public_url("http://lager.fritz.box:8080", missing)
    assert config.load_config(missing)["server"]["public_url"] == "http://lager.fritz.box:8080"


# ------------------------------------------------------ Seite /etiketten


def _count_labels(html):
    return html.count('<div class="label"') + html.count('<div class="label stacked"')


def test_seite_etiketten_alle_bauteile_mit_vorschlag(client):
    page = client.get("/etiketten")
    assert page.status_code == 200
    assert _count_labels(page.text) == 4
    assert page.text.count('class="sheet"') == 1
    assert 'value="http://testpc.fritz.box"' in page.text
    assert "Vorschlag, noch nicht gespeichert" in page.text
    assert "4 Etiketten auf" in page.text and "1 Seite" in page.text
    assert "65 passen auf eine Seite" in page.text
    assert "@page { size: A4; margin: 0; }" in page.text
    assert 'onclick="window.print()"' in page.text
    assert "Adresse merken" in page.text
    assert "width:38mm;height:21mm" in page.text
    assert '<div class="label-name"' in page.text
    assert "Fach A-03-2" in page.text
    assert page.text.count("<svg") == 4


def test_druckregeln_stehen_nur_auf_der_etiketten_seite(client):
    assert "@page" not in client.get("/").text
    assert "@page" not in client.get("/p/IRLZ44N").text
    assert "@page" not in client.get("/static/style.css").text


def test_seite_etiketten_auswahl(client):
    assert _count_labels(client.get("/etiketten", params={"q": "irf"}).text) == 2
    assert _count_labels(client.get("/etiketten", params={"kategorie": "widerstaende"}).text) == 1
    one = client.get("/etiketten", params={"teil": ["irlz44n", "IRLZ44N", "GIBTSNICHT"]})
    assert one.status_code == 200
    assert _count_labels(one.text) == 1
    assert "Nicht gefunden: GIBTSNICHT" in one.text
    assert '<input type="hidden" name="teil" value="IRLZ44N">' in one.text
    assert 'name="q"' not in one.text.split('<form action="/etiketten"')[1].split("</form>")[0]
    empty = client.get("/etiketten", params={"q": "gibtsnicht"})
    assert _count_labels(empty.text) == 0
    assert "keine Bauteile" in empty.text
    assert 'onclick="window.print()"' not in empty.text


def test_seite_etiketten_groessen(client):
    big = client.get("/etiketten", params={"groesse": "gross"}).text
    assert "width:70mm;height:37mm" in big
    assert '<option value="gross" selected>' in big
    own = client.get("/etiketten", params={"groesse": "eigen", "breite": "60", "hoehe": "30,5"}).text
    assert "width:60mm;height:30.5mm" in own
    assert '<option value="eigen" selected>' in own
    assert 'name="breite" inputmode="decimal" autocomplete="off"\n                 value="60"' in own
    tall = client.get("/etiketten", params={"groesse": "eigen", "breite": "20", "hoehe": "25"}).text
    assert '<div class="label stacked"' in tall
    bad = client.get("/etiketten", params={"groesse": "eigen", "breite": "5", "hoehe": "5"})
    assert bad.status_code == 200
    assert "Eigene Größe muss zwischen" in bad.text
    assert "width:38mm;height:21mm" in bad.text  # zurück auf die Standardgröße


def test_seite_etiketten_adresse_und_hinweise(client):
    typed = client.get("/etiketten", params={"adresse": "lager.fritz.box:8080"}).text
    assert 'value="http://lager.fritz.box:8080"' in typed
    assert "Eingegeben, noch nicht gespeichert" in typed
    assert 'role="note"' not in typed  # unauffällige Adresse: keine Hinweise

    local = client.get("/etiketten", params={"adresse": "http://127.0.0.1:8080"}).text
    assert "erreicht nur dieser PC" in local
    assert "feste IP" in client.get("/etiketten", params={"adresse": f"http://{TEST_IP}:8080"}).text
    assert "nicht auflösen" in client.get("/etiketten", params={"adresse": "tippfehler.fritz.box"}).text

    broken = client.get("/etiketten", params={"adresse": "ftp://lager"})
    assert broken.status_code == 200
    assert "muss mit http:// oder https:// beginnen" in broken.text
    assert 'value="http://testpc.fritz.box"' in broken.text  # zurück auf den Vorschlag

    tiny = client.get("/etiketten", params={"groesse": "mini", "adresse": BASE}).text
    assert "muss das Handy sehr nah" in tiny


def test_seite_etiketten_ohne_beschreibung_und_fach(client):
    page = client.get("/etiketten", params={"ohne_beschreibung": "1", "ohne_fach": "1"}).text
    assert '<div class="label-name"' not in page
    assert "Fach A-03-2" not in page
    assert 'name="ohne_beschreibung" value="1" checked' in page
    assert _count_labels(page) == 4


def test_lange_bezeichnung_auf_der_seite_zweizeilig(client, lager_voll):
    from lager import parts

    parts.create_part(lager_voll, "mosfets", "ATMEGA328P-PU", {"name": "Mikrocontroller"})
    client.post("/index/rebuild")
    page = client.get("/etiketten", params={"teil": "ATMEGA328P-PU"}).text
    assert "<span>ATMEGA3</span><span>28P-PU</span>" in page
    assert "<span>IRLZ44N</span></div>" in client.get("/etiketten", params={"teil": "IRLZ44N"}).text


def test_hinweis_wenn_der_server_nur_lokal_lauscht(lager_voll, config_path):
    local_only = TestClient(
        create_app(lager_voll, {"write_token": ""}, config_path, bind_host="127.0.0.1"), client=LOCAL
    )
    assert "lager serve --host 0.0.0.0" in local_only.get("/etiketten").text
    open_to_lan = TestClient(
        create_app(lager_voll, {"write_token": ""}, config_path, bind_host="0.0.0.0"), client=LOCAL
    )
    assert "lager serve --host 0.0.0.0" not in open_to_lan.get("/etiketten").text


def test_adresse_merken(client, app, config_path):
    response = client.post(
        "/etiketten/adresse",
        data={"adresse": " lager.fritz.box:8080/ ", "groesse": "gross", "q": "irf", "teil": []},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/etiketten?q=irf&groesse=gross&hinweis=adresse"
    text = config_path.read_text(encoding="utf-8")
    assert '  public_url: "http://lager.fritz.box:8080"' in text
    assert "# Test-Konfiguration" in text
    assert app.state.cfg["server"]["public_url"] == "http://lager.fritz.box:8080"

    page = client.get(response.headers["location"]).text
    assert "Die Adresse ist gespeichert" in page
    assert 'value="http://lager.fritz.box:8080"' in page
    assert "Gespeicherte Adresse aus der config.yaml" in page
    assert _count_labels(page) == 2
    # Die gespeicherte Adresse gilt auch für den QR-Code auf der Bauteilseite.
    assert "http://lager.fritz.box:8080/p/IRLZ44N" in client.get("/p/IRLZ44N").text


def test_adresse_merken_behaelt_die_auswahl_einzelner_teile(client):
    response = client.post(
        "/etiketten/adresse",
        data={"adresse": BASE, "teil": ["IRLZ44N", "IRF540N"], "ohne_fach": "1"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/etiketten?teil=IRLZ44N&teil=IRF540N&ohne_fach=1&hinweis=adresse"


def test_adresse_merken_fehler_und_schutz(client, phone, geschuetzt, app, config_path):
    before = config_path.read_text(encoding="utf-8")
    bad = client.post("/etiketten/adresse", data={"adresse": "ftp://lager"})
    assert bad.status_code == 400
    assert "muss mit http:// oder https:// beginnen" in bad.text
    assert phone.post("/etiketten/adresse", data={"adresse": BASE}).status_code == 403
    assert geschuetzt.post("/etiketten/adresse", data={"adresse": BASE}).status_code == 403
    assert config_path.read_text(encoding="utf-8") == before
    assert "server" not in app.state.cfg or not app.state.cfg["server"].get("public_url")
    # Am Handy und bei Schreibschutz fehlt der Knopf; drucken geht trotzdem.
    assert "Adresse merken" not in phone.get("/etiketten").text
    assert "Adresse merken" not in geschuetzt.get("/etiketten").text
    assert _count_labels(geschuetzt.get("/etiketten").text) == 4


def test_gespeicherte_adresse_aus_der_config(lager_voll, config_path):
    cfg = {"write_token": "", "server": {"public_url": "http://lager.fritz.box:8080/"}}
    client = TestClient(create_app(lager_voll, cfg, config_path), client=LOCAL)
    page = client.get("/etiketten").text
    assert 'value="http://lager.fritz.box:8080"' in page
    assert "Gespeicherte Adresse" in page
    # Eine unbrauchbare gespeicherte Adresse wird wie eine fehlende behandelt.
    cfg["server"]["public_url"] = "kaputt kaputt"
    assert 'value="http://testpc.fritz.box"' in client.get("/etiketten").text


def test_bauteilseite_zeigt_qr_code_und_link_zum_etikett(client):
    page = client.get("/p/irlz44n").text
    assert '<div class="qr-box"><svg' in page
    assert "http://testpc.fritz.box/p/IRLZ44N" in page
    assert 'href="/etiketten?teil=IRLZ44N"' in page
    assert "qr-box" not in client.get("/p/GIBTSNICHT").text


def test_trefferliste_verlinkt_auf_die_etiketten(client):
    assert 'href="/etiketten?q=irlz&amp;"' in client.get("/", params={"q": "irlz"}).text
    both = client.get("/suche", params={"q": "irf", "kategorie": "mosfets"}).text
    assert 'href="/etiketten?q=irf&amp;kategorie=mosfets"' in both
    assert "/etiketten" not in client.get("/", params={"q": "gibtsnicht"}).text


def test_ohne_netz_und_ohne_adresse(client, monkeypatch):
    monkeypatch.setattr(labels, "lan_ipv4", lambda: None)
    page = client.get("/etiketten")
    assert page.status_code == 200
    assert "Bitte eine Adresse eintragen" in page.text
    assert _count_labels(page.text) == 0
    assert "qr-box" not in client.get("/p/IRLZ44N").text
    # Mit eingegebener Adresse geht es auch ohne erkanntes Netz.
    assert _count_labels(client.get("/etiketten", params={"adresse": BASE}).text) == 4


# ------------------------------------------------------------- CLI


@pytest.fixture()
def run(lager_voll, config_path, monkeypatch):
    """CLI gegen das Test-Lager und eine eigene config.yaml."""
    monkeypatch.setattr(cli, "_require_root", lambda: lager_voll)
    monkeypatch.setattr(cli, "load_config", lambda: config.load_config(config_path))
    monkeypatch.setattr(cli, "set_public_url", lambda url: config.set_public_url(url, config_path))
    runner = CliRunner()
    return lambda *args: runner.invoke(cli.app, [str(arg) for arg in args])


def test_qr_url_zeigen_und_speichern(run, config_path):
    shown = json.loads(run("qr", "url", "--json").stdout)
    assert shown == {
        "adresse": "", "gespeichert": False, "vorschlag": "http://testpc.fritz.box:8080", "hinweise": [],
    }
    saved = run("qr", "url", "lager.fritz.box:8080", "--json")
    assert saved.exit_code == 0
    assert json.loads(saved.stdout) == {
        "adresse": "http://lager.fritz.box:8080", "gespeichert": True, "hinweise": [],
    }
    assert '  public_url: "http://lager.fritz.box:8080"' in config_path.read_text(encoding="utf-8")
    again = json.loads(run("qr", "url", "--json").stdout)
    assert (again["adresse"], again["gespeichert"]) == ("http://lager.fritz.box:8080", True)


def test_qr_url_hinweise_und_fehler(run, config_path):
    before = config_path.read_text(encoding="utf-8")
    bad = run("qr", "url", "ftp://lager")
    assert bad.exit_code == 1
    assert "http:// oder https://" in bad.stderr
    assert config_path.read_text(encoding="utf-8") == before
    warned = json.loads(run("qr", "url", "http://127.0.0.1:8080", "--json").stdout)
    assert "erreicht nur dieser PC" in warned["hinweise"][0]
    assert "Tipp: lager qr url" not in run("qr", "url").stdout  # jetzt ist eine Adresse gespeichert


def test_qr_make_schreibt_bilder(run, tmp_path):
    out = tmp_path / "codes"
    missing_address = run("qr", "make", "IRLZ44N", "--out", out)
    assert missing_address.exit_code == 1
    assert "lager qr url" in missing_address.stderr
    assert not out.exists()

    result = run("qr", "make", "irlz44n", "IRF540N", "--out", out, "--url", BASE, "--format", "png", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["adresse"] == BASE
    assert [(c["part"], c["url"]) for c in data["codes"]] == [
        ("IRLZ44N", "http://lager.fritz.box:8080/p/IRLZ44N"),
        ("IRF540N", "http://lager.fritz.box:8080/p/IRF540N"),
    ]
    assert (out / "IRLZ44N.png").read_bytes().startswith(b"\x89PNG")
    assert (out / "IRF540N.png").is_file()

    run("qr", "url", BASE)
    svg = run("qr", "make", "IRLZ44N", "--out", out)
    assert svg.exit_code == 0
    assert b"<svg" in (out / "IRLZ44N.svg").read_bytes()


def test_qr_make_fehler_schreiben_nichts(run, tmp_path):
    out = tmp_path / "codes"
    unknown = run("qr", "make", "IRLZ44N", "GIBTSNICHT", "--out", out, "--url", BASE)
    assert unknown.exit_code == 1
    assert "Teil nicht gefunden: GIBTSNICHT" in unknown.stderr
    assert not out.exists()
    wrong = run("qr", "make", "IRLZ44N", "--out", out, "--url", BASE, "--format", "gif")
    assert wrong.exit_code == 1
    assert "Unbekanntes Bildformat" in wrong.stderr
    assert not list(out.glob("*")) if out.exists() else True
