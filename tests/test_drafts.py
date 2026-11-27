"""Tests für Vorschläge („Automatisch ergänzen“): Kern, Arbeiter, Papierkorb, Seiten, API, CLI."""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lager import cli, db, drafts, files, indexer, root as rootmod, search, trash

ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class FixedTime(datetime):
    """Uhr, die immer dieselbe Sekunde zeigt (mehrere Entwürfe in derselben Sekunde)."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 27, 9, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def run(lager_voll, monkeypatch):
    """Führt CLI-Befehle gegen das Test-Lager aus (statt gegen config.yaml)."""
    monkeypatch.setattr(cli, "_require_root", lambda: lager_voll)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    runner = CliRunner()

    def _run(*args):
        return runner.invoke(cli.app, list(args))

    return _run


def ready_draft(root: Path, text: str) -> drafts.Draft:
    """Vorschlag anlegen und gleich vorbereiten (im Server macht das der Arbeiter)."""
    draft = drafts.create(root, text)
    assert drafts.process(root, draft.id)
    return drafts.load(root, draft.id)


def write_draft_file(draft: drafts.Draft, rel: str, content: bytes = b"%PDF-1.4 test") -> None:
    """Legt eine Datei in den Entwurf, wie es später die Suche tut."""
    path = draft.folder.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def edit_doc(draft: drafts.Draft, change) -> None:
    """Ändert draft.yaml von Hand (wie eine spätere Suche oder ein Editor)."""
    path = draft.folder / drafts.DRAFT_FILE
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def make_stale(lock: Path) -> None:
    old = time.time() - drafts.STALE_SECONDS - 60
    os.utime(lock, (old, old))


def part_count(root: Path) -> int:
    indexer.rebuild(root, {})
    conn = db.connect(root, create=False)
    try:
        return len(search.search(conn, "", None, 100))
    finally:
        conn.close()


# ------------------------------------------------------------------ Anlegen


def test_entwurf_anlegen_wartet(lager_voll):
    draft = drafts.create(lager_voll, "  irlz44   mosfet to220 ")

    assert draft.folder == lager_voll / "_entwuerfe" / draft.id
    assert trash.is_stamp(draft.id)
    assert ISO_UTC.match(draft.created) and draft.updated == draft.created
    assert draft.input == "irlz44 mosfet to220"
    assert (draft.status, draft.reviewable, draft.error) == ("queued", False, "")
    for name in ("part", "category", "subcategory", "name", "manufacturer", "notes"):
        assert draft.value(name) == "" and draft.source(name) == {}
    assert draft.value("aliases") == [] and draft.value("tags") == []
    assert draft.files == []

    text = (draft.folder / "draft.yaml").read_text(encoding="utf-8")
    assert text.startswith("# draft.yaml")
    doc = yaml.safe_load(text)
    assert (doc["schema"], doc["id"], doc["status"]) == (1, draft.id, "queued")
    assert doc["input"] == draft.input
    assert [p.name for p in draft.folder.iterdir()] == ["draft.yaml"]  # keine Reste


def test_vorbereiten(lager_voll):
    draft = drafts.create(lager_voll, "irlz44 mosfet to220")
    assert [d.id for d in drafts.pending(lager_voll)] == [draft.id]

    assert drafts.process(lager_voll, draft.id) is True
    ready = drafts.load(lager_voll, draft.id)
    assert (ready.status, ready.reviewable) == ("ready", True)
    assert ready.value("part") == "irlz44 mosfet to220"
    assert ready.source("part") == {"kind": "input"}
    assert ISO_UTC.match(ready.updated)
    assert not (draft.folder / drafts.LOCK_FILE).exists()
    assert drafts.pending(lager_voll) == []
    assert drafts.process(lager_voll, draft.id) is False  # schon fertig


def test_entwurf_als_dict(lager_voll):
    draft = ready_draft(lager_voll, "NE555")
    data = draft.as_dict(lager_voll)
    assert data["id"] == draft.id and data["status"] == "ready" and data["error"] == ""
    assert data["path"] == f"_entwuerfe/{draft.id}"
    assert list(data["fields"]) == list(drafts.FIELDS)
    assert data["fields"]["part"] == {"value": "NE555", "source": {"kind": "input"}}
    assert data["files"] == []
    json.dumps(data)  # sprachneutral: nur Text, Zahlen, Listen


@pytest.mark.parametrize("text", ["", "   ", "x" * 201])
def test_ungueltige_eingabe(lager_voll, text):
    with pytest.raises(ValueError):
        drafts.create(lager_voll, text)
    assert not (lager_voll / "_entwuerfe").exists()


def test_entwuerfe_in_derselben_sekunde(lager_voll, monkeypatch):
    monkeypatch.setattr(trash, "datetime", FixedTime)
    ids = [drafts.create(lager_voll, name).id for name in ("a", "b", "c")]
    assert ids == ["20261127T091500Z", "20261127T091500Z-2", "20261127T091500Z-3"]
    assert [d.id for d in drafts.entries(lager_voll)] == list(reversed(ids))
    assert [d.id for d in drafts.pending(lager_voll)] == ids  # der älteste zuerst
    assert drafts.load(lager_voll, ids[1]).created == "2026-11-27T09:15:00Z"


def test_entwuerfe_bleiben_aus_suche_und_kategorien(lager_voll):
    before = part_count(lager_voll)
    draft = ready_draft(lager_voll, "IRF540N")  # dieselbe Bezeichnung wie ein Bauteil
    write_draft_file(draft, "datasheet.pdf")
    (draft.folder / "part.yaml").write_text("part: IRF540N\n", encoding="utf-8")  # von Hand
    assert part_count(lager_voll) == before
    assert "_entwuerfe" not in [d.name for d in rootmod.visible_dirs(lager_voll)]


# ------------------------------------------------------------------ Vorbereiten


def test_alle_wartenden_der_reihe_nach(lager_voll, monkeypatch):
    monkeypatch.setattr(trash, "datetime", FixedTime)
    for name in ("a", "b", "c"):
        drafts.create(lager_voll, name)
    seen = []
    monkeypatch.setattr(drafts, "STAGES", (lambda root, doc, cfg: seen.append(doc["input"]),))

    assert drafts.process_pending(lager_voll, should_stop=lambda: True) == 0
    assert drafts.process_pending(lager_voll) == 3
    assert seen == ["a", "b", "c"]
    assert {d.status for d in drafts.entries(lager_voll)} == {"ready"}


def test_gesperrter_entwurf_wird_nicht_doppelt_bearbeitet(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    lock = draft.folder / drafts.LOCK_FILE
    lock.touch()  # ein anderer Prozess arbeitet daran
    assert drafts.process(lager_voll, draft.id) is False
    assert drafts.load(lager_voll, draft.id).status == "queued"

    make_stale(lock)  # dieser Prozess ist offenbar beendet worden
    assert drafts.process(lager_voll, draft.id) is True
    assert drafts.load(lager_voll, draft.id).status == "ready"


def test_liegengebliebener_entwurf_wird_neu_vorbereitet(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    edit_doc(draft, lambda doc: doc.update({"status": "running"}))
    lock = draft.folder / drafts.LOCK_FILE
    lock.touch()
    assert drafts.pending(lager_voll) == []  # jemand arbeitet noch daran
    make_stale(lock)
    assert [d.id for d in drafts.pending(lager_voll)] == [draft.id]
    assert drafts.process_pending(lager_voll) == 1
    assert drafts.load(lager_voll, draft.id).status == "ready"


def test_fehler_in_einer_stufe(lager_voll, monkeypatch):
    def broken(root, doc, cfg):
        raise RuntimeError("Mouser antwortet nicht")

    monkeypatch.setattr(drafts, "STAGES", (drafts._stage_input, broken))
    draft = drafts.create(lager_voll, "NE555")
    assert drafts.process(lager_voll, draft.id) is True
    failed = drafts.load(lager_voll, draft.id)
    assert (failed.status, failed.reviewable) == ("failed", True)
    assert failed.error == "RuntimeError: Mouser antwortet nicht"
    assert failed.value("part") == "NE555"  # was die Stufen davor fanden, bleibt
    part_dir, _errors = drafts.save(lager_voll, draft.id, "mosfets", "NE555", {})
    assert (part_dir / "part.yaml").is_file()


def test_verworfen_waehrend_er_wartet(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    drafts.discard(lager_voll, draft.id)
    assert drafts.process(lager_voll, draft.id) is False
    assert drafts.process_pending(lager_voll) == 0


def test_entwurf_ohne_stand_gilt_als_fertig(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    edit_doc(draft, lambda doc: doc.pop("status"))
    assert drafts.load(lager_voll, draft.id).status == "ready"


# ------------------------------------------------------------------ Lesen


def test_liste_leer(lager_voll):
    assert drafts.entries(lager_voll) == []
    assert drafts.pending(lager_voll) == []


def test_fremdes_und_kaputtes_wird_uebersprungen(lager_voll):
    good = drafts.create(lager_voll, "NE555")
    broken = drafts.create(lager_voll, "LM317")
    (broken.folder / "draft.yaml").write_text("fields: [kaputt", encoding="utf-8")
    (lager_voll / "_entwuerfe" / "notizen").mkdir()
    (lager_voll / "_entwuerfe" / "liesmich.txt").write_text("x", encoding="utf-8")

    assert [d.id for d in drafts.entries(lager_voll)] == [good.id]
    with pytest.raises(ValueError, match="nicht lesbar"):
        drafts.load(lager_voll, broken.id)
    assert drafts.process(lager_voll, broken.id) is False


@pytest.mark.parametrize("draft_id", ["..", "../mosfets", "20261127T091500Z/../..", "", "abc"])
def test_ungueltige_id(lager_voll, draft_id):
    with pytest.raises(drafts.DraftNotFound):
        drafts.load(lager_voll, draft_id)
    assert drafts.process(lager_voll, draft_id) is False


def test_fehlender_entwurf(lager_voll):
    with pytest.raises(drafts.DraftNotFound, match="gibt es nicht"):
        drafts.load(lager_voll, "20261127T091500Z")


def test_von_hand_geaenderte_datei_wird_bereinigt(lager_voll):
    draft = ready_draft(lager_voll, "TP4056")

    def change(doc):
        fields = doc["fields"]
        fields["name"] = {
            "value": " Lademodul ",
            "source": {"kind": "web", "url": "https://example.org/a", "quote": "Lademodul"},
        }
        fields["manufacturer"] = {"value": "Acme", "source": {"kind": "erfunden"}}
        fields["tags"] = {"value": "lipo", "source": {"kind": "input"}}
        fields["aliases"] = {"value": ["TP4056", " TP4056 ", "", None], "source": {"kind": "api", "name": "Mouser"}}
        fields["notes"] = {"value": "", "source": {"kind": "input"}}
        fields["category"] = "kein Feld"
        doc["files"] = [{"path": "datasheet.pdf", "source": {"kind": "api", "name": "Mouser", "url": "https://mouser.example/p"}}]
        doc["status"] = "unbekannt"
        doc["error"] = "gilt nur bei failed"

    edit_doc(draft, change)
    write_draft_file(draft, "datasheet.pdf")
    write_draft_file(draft, "Thumbs.db", b"x")
    write_draft_file(draft, ".versteckt", b"x")
    loaded = drafts.load(lager_voll, draft.id)

    assert loaded.value("name") == "Lademodul"
    assert loaded.source("name") == {"kind": "web", "url": "https://example.org/a", "quote": "Lademodul"}
    assert loaded.source("manufacturer") == {}  # unbekannte Herkunft zählt nicht
    assert loaded.value("tags") == ["lipo"]
    assert loaded.value("aliases") == ["TP4056"]
    assert loaded.source("notes") == {}  # leerer Wert, keine Herkunft
    assert loaded.value("category") == ""
    assert (loaded.status, loaded.error) == ("ready", "")
    assert [(f.path, f.source.get("name")) for f in loaded.files] == [("datasheet.pdf", "Mouser")]


def test_herkunft_beschreiben():
    assert drafts.describe_source({}) == {}
    assert drafts.describe_source({"kind": "input"})["text"] == "aus deiner Eingabe"
    assert drafts.describe_source({"kind": "api", "name": "Mouser"})["text"] == "von Mouser"
    assert drafts.describe_source({"kind": "library", "name": "KiCad"})["text"] == "aus KiCad"
    web = drafts.describe_source({"kind": "web", "url": "https://ti.com/x.pdf", "quote": "4,2 V"})
    assert web == {"text": "aus einer Quelle im Netz", "url": "https://ti.com/x.pdf", "quote": "4,2 V"}
    # Nur echte Web-Adressen werden zum Link.
    assert drafts.describe_source({"kind": "web", "url": "javascript:alert(1)"})["url"] == ""


# ------------------------------------------------------------------ Speichern


def test_speichern_legt_bauteil_an_und_raeumt_auf(lager_voll):
    draft = ready_draft(lager_voll, "irlz44 mosfet to220")
    write_draft_file(draft, "datasheet.pdf")
    write_draft_file(draft, "TO-220.step", b"step")
    write_draft_file(draft, "Thumbs.db", b"x")

    part_dir, errors = drafts.save(
        lager_voll, draft.id, "mosfets", "IRLZ44", {"name": "MOSFET N-Kanal", "quantity": 3},
        subcategory="n-kanal",
    )

    assert errors == []
    assert part_dir == lager_voll / "mosfets" / "n-kanal" / "IRLZ44"
    doc = yaml.safe_load((part_dir / "part.yaml").read_text(encoding="utf-8"))
    assert (doc["part"], doc["name"], doc["quantity"]) == ("IRLZ44", "MOSFET N-Kanal", 3)
    assert (part_dir / "datasheet.pdf").read_bytes() == b"%PDF-1.4 test"
    assert (part_dir / "3d" / "TO-220.step").is_file()
    assert not (lager_voll / "_entwuerfe").exists()
    assert drafts.entries(lager_voll) == []


def test_speichern_erst_wenn_fertig(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    with pytest.raises(ValueError, match="wird noch vorbereitet"):
        drafts.save(lager_voll, draft.id, "mosfets", "NE555", {})
    assert not (lager_voll / "mosfets" / "NE555").exists()


def test_speichern_laesst_andere_entwuerfe_stehen(lager_voll):
    first = ready_draft(lager_voll, "NE555")
    other = drafts.create(lager_voll, "LM317")
    drafts.save(lager_voll, first.id, "mosfets", "NE555", {})
    assert [d.id for d in drafts.entries(lager_voll)] == [other.id]


def test_speichern_ohne_entwurf_legt_nichts_an(lager_voll):
    with pytest.raises(drafts.DraftNotFound):
        drafts.save(lager_voll, "20261127T091500Z", "mosfets", "NE555", {})
    assert not (lager_voll / "mosfets" / "NE555").exists()


def test_speichern_mit_vergebener_bezeichnung(lager_voll):
    draft = ready_draft(lager_voll, "irf540n")
    with pytest.raises(ValueError, match="existiert bereits"):
        drafts.save(lager_voll, draft.id, "mosfets", "irf540n", {})
    assert drafts.load(lager_voll, draft.id).value("part") == "irf540n"  # bleibt zum Nachbessern


def test_gesperrte_datei_bleibt_im_entwurf(lager_voll, monkeypatch):
    draft = ready_draft(lager_voll, "NE555")
    write_draft_file(draft, "a.pdf")
    write_draft_file(draft, "b.pdf")
    real = files.add_file_from_path

    def locked(part_dir, source, cfg=None, move=False):
        if source.name == "b.pdf":
            raise PermissionError("Die Datei wird von einem anderen Prozess verwendet")
        return real(part_dir, source, cfg, move)

    monkeypatch.setattr(files, "add_file_from_path", locked)
    part_dir, errors = drafts.save(lager_voll, draft.id, "mosfets", "NE555", {})

    assert len(errors) == 1 and errors[0].startswith("b.pdf:")
    assert (part_dir / "a.pdf").is_file()
    left = drafts.load(lager_voll, draft.id)
    assert [f.path for f in left.files] == ["b.pdf"]


# ------------------------------------------------------------------ Verwerfen


def test_verwerfen_und_zurueckholen(lager_voll):
    draft = ready_draft(lager_voll, "HW-130 Motor Shield")
    write_draft_file(draft, "datasheet.pdf")
    trashed = drafts.discard(lager_voll, draft.id)

    assert not (lager_voll / "_entwuerfe").exists()
    assert trashed.is_dir() and (trashed / "draft.yaml").is_file()
    (entry,) = trash.entries(lager_voll)
    assert (entry.kind, entry.name, entry.part) == ("draft", "HW-130 Motor Shield", "")
    assert entry.path == f"_entwuerfe/{draft.id}"
    assert entry.as_dict(lager_voll)["problem"] == ""

    target = trash.restore(lager_voll, entry.id)
    assert target == draft.folder
    restored = drafts.load(lager_voll, draft.id)
    assert (restored.input, restored.status) == ("HW-130 Motor Shield", "ready")
    assert [f.path for f in restored.files] == ["datasheet.pdf"]
    assert trash.entries(lager_voll) == []


def test_verwerfen_waehrend_der_vorbereitung(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    lock = draft.folder / drafts.LOCK_FILE
    lock.touch()
    with pytest.raises(ValueError, match="wird gerade vorbereitet"):
        drafts.discard(lager_voll, draft.id)
    assert draft.folder.is_dir()
    make_stale(lock)
    drafts.discard(lager_voll, draft.id)
    assert not draft.folder.exists()


def test_zurueckholen_wenn_ordner_wieder_da(lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    drafts.discard(lager_voll, draft.id)
    draft.folder.mkdir(parents=True)
    (entry,) = trash.entries(lager_voll)
    assert "schon einen Ordner" in trash.restore_problem(lager_voll, entry)
    with pytest.raises(ValueError, match="schon einen Ordner"):
        trash.restore(lager_voll, entry.id)


def test_verwerfen_ohne_entwurf(lager_voll):
    with pytest.raises(drafts.DraftNotFound):
        drafts.discard(lager_voll, "20261127T091500Z")
    assert not trash.trash_dir(lager_voll).exists()


# ------------------------------------------------------------------ Arbeiter


def test_arbeiter_bereitet_im_hintergrund_vor(app, lager_voll):
    """Mit `with` startet der Test-Browser den Server wie `lager serve`, samt Arbeiter."""
    with TestClient(app) as browser:
        assert app.state.worker.running
        response = browser.post("/neu/vorschlag", data={"eingabe": "NE555"}, follow_redirects=False)
        assert response.status_code == 303
        (draft,) = drafts.entries(lager_voll)
        deadline = time.monotonic() + 10
        while drafts.load(lager_voll, draft.id).status != "ready":
            assert time.monotonic() < deadline, "Der Arbeiter hat den Vorschlag nicht vorbereitet."
            time.sleep(0.05)
    assert not app.state.worker.running  # beim Beenden des Servers angehalten


def test_arbeiter_einmal_von_hand(app, lager_voll):
    drafts.create(lager_voll, "NE555")
    drafts.create(lager_voll, "LM317")
    assert app.state.worker.run_once() == 2
    assert app.state.worker.run_once() == 0
    assert not app.state.worker.running  # ohne `with` startet er nicht


# ------------------------------------------------------------------ Seiten

EMPTY_FILE_FIELD = ("dateien", ("", b"", "application/octet-stream"))


def form_for(**changes) -> dict:
    """Formular „Vorschlag prüfen“, wie der Browser es schickt."""
    data = {
        "bezeichnung": "IRLZ44", "kategorie": "mosfets", "neue_kategorie": "",
        "unterkategorie": "", "neue_unterkategorie": "", "name": "", "hersteller": "",
        "lagerfach": "", "menge": "0", "tags": "", "aliase": "", "notizen": "",
    }
    data.update(changes)
    return data


def test_neu_zeigt_automatisch_ergaenzen(client, lager_voll):
    page = client.get("/neu").text
    assert "Automatisch ergänzen" in page and 'action="/neu/vorschlag"' in page
    assert "<h3>Vorschläge</h3>" not in page and "data-pending" not in page
    draft = drafts.create(lager_voll, "HW-130 Motor Shield")
    page = client.get("/neu").text
    assert "<h3>Vorschläge</h3>" in page and 'data-pending="1"' in page
    assert f'href="/vorschlag/{draft.id}"' in page and "HW-130 Motor Shield" in page
    assert 'class="status status-queued">wartet<' in page


def test_vorschlag_im_hintergrund(phone, app, lager_voll):
    response = phone.post("/neu/vorschlag", data={"eingabe": " irlz44  mosfet "}, follow_redirects=False)
    assert response.status_code == 303
    (draft,) = drafts.entries(lager_voll)
    assert response.headers["location"] == f"/neu?hinweis=vorschlag&entwurf={draft.id}"

    # Gleich zurück auf „Neues Bauteil“: Meldung, leeres Feld mit Fokus, Liste mit Stand.
    page = phone.get(response.headers["location"]).text
    assert "„irlz44 mosfet“ wird im Hintergrund vorbereitet" in page
    assert 'name="eingabe" value=""' in page and " autofocus" in page
    assert 'class="status status-queued">wartet<' in page
    # Die Seite des Vorschlags wartet und lädt sich neu; zum Speichern gibt es noch nichts.
    waiting = phone.get(f"/vorschlag/{draft.id}").text
    assert '<meta http-equiv="refresh" content="3">' in waiting
    assert "wird im Hintergrund vorbereitet" in waiting
    assert 'name="bezeichnung"' not in waiting
    assert f'action="/vorschlag/{draft.id}/verwerfen"' in waiting  # wartende lassen sich verwerfen

    assert app.state.worker.run_once() == 1

    fragment = phone.get("/neu/vorschlaege").text
    assert "data-pending" not in fragment and "bereit zum Prüfen" in fragment
    page = phone.get(response.headers["location"]).text
    assert "Der Vorschlag für „irlz44 mosfet“ ist fertig" in page
    assert '<span class="badge" aria-hidden="true">1</span>' in page
    assert "1 Vorschlag bereit zum Prüfen" in page
    ready = phone.get(f"/vorschlag/{draft.id}").text
    assert "http-equiv" not in ready
    assert 'name="bezeichnung" value="irlz44 mosfet"' in ready
    assert "aus deiner Eingabe" in ready and "Noch ist nichts gespeichert" in ready


def test_vorschlag_ohne_eingabe(client, lager_voll):
    response = client.post("/neu/vorschlag", data={"eingabe": "  "})
    assert response.status_code == 400
    assert "Bitte einen Namen" in response.text
    assert drafts.entries(lager_voll) == []


def test_unbekannter_vorschlag(client):
    response = client.get("/vorschlag/20261127T091500Z")
    assert response.status_code == 404
    assert "gibt es nicht (mehr)" in response.text
    assert client.get("/vorschlag/abc").status_code == 404


def test_vorschlag_speichern(client, lager_voll):
    draft = ready_draft(lager_voll, "irlz44 mosfet to220")
    write_draft_file(draft, "datasheet.pdf")
    response = client.post(
        f"/vorschlag/{draft.id}",
        data=form_for(
            unterkategorie="mosfets/p-kanal", name="MOSFET N-Kanal", menge="4",
            tags="n-kanal, to-220", aliase="irlz44 mosfet to220",
        ),
        files=[("dateien", ("foto.jpg", b"jpg", "image/jpeg"))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?hinweis=angelegt&teil=IRLZ44"
    part_dir = lager_voll / "mosfets" / "p-kanal" / "IRLZ44"
    doc = yaml.safe_load((part_dir / "part.yaml").read_text(encoding="utf-8"))
    assert (doc["name"], doc["quantity"], doc["tags"]) == ("MOSFET N-Kanal", 4, ["n-kanal", "to-220"])
    assert doc["aliases"] == ["irlz44 mosfet to220"]
    assert (part_dir / "datasheet.pdf").is_file() and (part_dir / "images" / "foto.jpg").is_file()
    assert not (lager_voll / "_entwuerfe").exists()

    # Zurück auf die Startseite, mit Link zum neuen Bauteil.
    page = client.get(response.headers["location"]).text
    assert "„IRLZ44“ ist angelegt." in page and 'href="/p/IRLZ44">Zum Bauteil' in page
    assert "datasheet.pdf" in client.get("/p/IRLZ44").text
    # Ein zweites Abschicken (z. B. doppelt getippt) legt nichts an und sagt, warum.
    again = client.post(f"/vorschlag/{draft.id}", data=form_for(bezeichnung="IRLZ44-2"))
    assert again.status_code == 404 and "gibt es nicht (mehr)" in again.text
    assert not (lager_voll / "mosfets" / "IRLZ44-2").exists()


def test_speichern_waehrend_der_vorbereitung(client, lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    response = client.post(f"/vorschlag/{draft.id}", data=form_for(bezeichnung="NE555"))
    assert response.status_code == 409 and "wird noch vorbereitet" in response.text
    assert not (lager_voll / "mosfets" / "NE555").exists()


def test_fehler_beim_vorbereiten_im_browser(client, lager_voll, monkeypatch):
    def broken(root, doc, cfg):
        raise RuntimeError("keine Verbindung")

    monkeypatch.setattr(drafts, "STAGES", (drafts._stage_input, broken))
    draft = ready_draft(lager_voll, "NE555")
    page = client.get(f"/vorschlag/{draft.id}").text
    assert "Beim Vorbereiten ist ein Fehler aufgetreten: RuntimeError: keine Verbindung" in page
    assert 'name="bezeichnung" value="NE555"' in page  # von Hand ergänzen geht trotzdem
    assert 'class="status status-failed">Fehler beim Vorbereiten<' in client.get("/neu").text


def test_vorschlag_speichern_ohne_datei(client, lager_voll):
    draft = ready_draft(lager_voll, "NE555")
    response = client.post(
        f"/vorschlag/{draft.id}", data=form_for(bezeichnung="NE555"), files=[EMPTY_FILE_FIELD],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (lager_voll / "mosfets" / "NE555" / "part.yaml").is_file()


def test_vorschlag_speichern_mit_fehler(client, lager_voll):
    draft = ready_draft(lager_voll, "NE555")
    response = client.post(
        f"/vorschlag/{draft.id}", data=form_for(bezeichnung="NE555 Timer", kategorie="", name="Timer")
    )
    assert response.status_code == 400
    assert "Bitte eine Kategorie wählen" in response.text
    # Was Lukas eingetragen hat, bleibt stehen; die Herkunft gilt nur für unveränderte Werte.
    assert 'value="NE555 Timer"' in response.text and 'value="Timer"' in response.text
    assert "aus deiner Eingabe" not in response.text
    assert drafts.load(lager_voll, draft.id).value("part") == "NE555"


def test_vorschlag_mit_vergebener_bezeichnung(client, lager_voll):
    draft = ready_draft(lager_voll, "irf540n")
    page = client.get(f"/vorschlag/{draft.id}").text
    assert "gibt es schon" in page and 'href="/p/IRF540N"' in page
    response = client.post(f"/vorschlag/{draft.id}", data=form_for(bezeichnung="irf540n"))
    assert response.status_code == 400 and "existiert bereits" in response.text


def test_vorgeschlagene_kategorien(client, lager_voll):
    known = ready_draft(lager_voll, "IRF9530")
    new_sub = ready_draft(lager_voll, "IRF9531")
    unknown = ready_draft(lager_voll, "BME280")

    def proposal(category, sub):
        def change(doc):
            source = {"kind": "api", "name": "Mouser"}
            doc["fields"]["category"] = {"value": category, "source": source}
            doc["fields"]["subcategory"] = {"value": sub, "source": source}
        return change

    edit_doc(known, proposal("mosfets", "p-kanal"))
    edit_doc(new_sub, proposal("mosfets", "Leistung"))
    edit_doc(unknown, proposal("sensoren", "Klima"))

    page = client.get(f"/vorschlag/{known.id}").text
    assert '<option value="mosfets" selected>' in page
    assert 'data-kurz="p-kanal" selected' in page
    assert page.count("von Mouser") == 2
    page = client.get(f"/vorschlag/{new_sub.id}").text
    assert 'name="neue_unterkategorie" value="Leistung"' in page
    page = client.get(f"/vorschlag/{unknown.id}").text
    assert 'name="neue_kategorie" value="sensoren"' in page
    assert 'name="neue_unterkategorie" value="Klima"' in page


def test_herkunft_wird_sicher_angezeigt(client, lager_voll):
    draft = ready_draft(lager_voll, "TP4056")

    def change(doc):
        doc["fields"]["name"] = {
            "value": "Lademodul",
            "source": {"kind": "web", "url": "javascript:alert(1)", "quote": "<script>alert(1)</script>"},
        }
        doc["fields"]["manufacturer"] = {
            "value": "Acme",
            "source": {"kind": "web", "url": "https://example.org/tp4056", "quote": "Acme"},
        }

    edit_doc(draft, change)
    write_draft_file(draft, "datasheet.pdf")
    page = client.get(f"/vorschlag/{draft.id}").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "javascript:" not in page
    assert 'href="https://example.org/tp4056"' in page
    assert "Dateien im Vorschlag" in page and "datasheet.pdf" in page


def test_verwerfen_und_zurueckholen_im_browser(client, lager_voll):
    draft = ready_draft(lager_voll, "HW-130 Motor Shield")
    response = client.post(f"/vorschlag/{draft.id}/verwerfen", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/neu?hinweis=verworfen&entwurf={draft.id}"
    page = client.get(response.headers["location"]).text
    assert "Der Vorschlag ist verworfen" in page and 'href="/papierkorb"' in page

    trash_page = client.get("/papierkorb").text
    assert "HW-130 Motor Shield" in trash_page and "Vorschlag" in trash_page
    (entry,) = trash.entries(lager_voll)
    back = client.post(
        "/papierkorb/wiederherstellen", data={"eintrag": entry.id}, follow_redirects=False
    )
    assert back.status_code == 303
    assert back.headers["location"] == f"/vorschlag/{draft.id}?hinweis=wiederhergestellt"
    page = client.get(back.headers["location"]).text
    assert "aus dem Papierkorb zurück" in page and "HW-130 Motor Shield" in page

    # Verworfen wird nur gemeldet, was wirklich weg ist.
    page = client.get(f"/neu?hinweis=verworfen&entwurf={draft.id}").text
    assert "Der Vorschlag ist verworfen" not in page
    assert client.post("/vorschlag/20261127T091500Z/verwerfen").status_code == 404


def test_verwerfen_waehrend_der_vorbereitung_im_browser(client, lager_voll):
    draft = drafts.create(lager_voll, "NE555")
    (draft.folder / drafts.LOCK_FILE).touch()
    response = client.post(f"/vorschlag/{draft.id}/verwerfen")
    assert response.status_code == 400 and "wird gerade vorbereitet" in response.text
    assert draft.folder.is_dir()


def test_vorschlag_bei_schreibschutz(geschuetzt, lager_voll):
    draft = ready_draft(lager_voll, "NE555")
    page = geschuetzt.get(f"/vorschlag/{draft.id}")
    assert page.status_code == 200 and "Der Schreibschutz ist aktiv" in page.text
    assert f'action="/vorschlag/{draft.id}"' not in page.text
    assert geschuetzt.post("/neu/vorschlag", data={"eingabe": "LM317"}).status_code == 403
    assert geschuetzt.post(f"/vorschlag/{draft.id}", data=form_for()).status_code == 403
    assert geschuetzt.post(f"/vorschlag/{draft.id}/verwerfen").status_code == 403
    assert [d.id for d in drafts.entries(lager_voll)] == [draft.id]


# ------------------------------------------------------------------ API


def test_api_vorschlaege(client, app, lager_voll):
    listing = client.get("/api/v1/drafts").json()
    assert (listing["anzahl"], listing["eintraege"]) == (0, [])

    created = client.post("/api/v1/drafts", json={"input": "irlz44 mosfet"})
    assert created.status_code == 201
    body = created.json()
    assert (body["input"], body["status"]) == ("irlz44 mosfet", "queued")
    assert body["fields"]["part"] == {"value": "", "source": {}}
    assert client.get(f"/api/v1/drafts/{body['id']}").json() == body

    app.state.worker.run_once()
    ready = client.get(f"/api/v1/drafts/{body['id']}").json()
    assert ready["status"] == "ready"
    assert ready["fields"]["part"] == {"value": "irlz44 mosfet", "source": {"kind": "input"}}
    assert ready["fields"]["tags"] == {"value": [], "source": {}}
    assert client.get("/api/v1/drafts").json()["eintraege"] == [ready]

    assert client.post("/api/v1/drafts", json={"input": ""}).status_code == 400
    assert client.get("/api/v1/drafts/20261127T091500Z").status_code == 404

    # Speichern gibt es bewusst nur für Lukas (Seite oder CLI), nicht über die API.
    assert client.post(f"/api/v1/drafts/{body['id']}/save", json={}).status_code in (404, 405)

    gone = client.delete(f"/api/v1/drafts/{body['id']}")
    assert gone.status_code == 200
    (entry,) = trash.entries(lager_voll)
    assert gone.json() == {
        "verworfen": body["id"],
        "papierkorb": f"_papierkorb/{entry.id}/_entwuerfe/{body['id']}",
    }
    assert client.delete(f"/api/v1/drafts/{body['id']}").status_code == 404
    listed = client.get("/api/v1/trash").json()["eintraege"][0]
    assert (listed["kind"], listed["name"], listed["part"]) == ("draft", "irlz44 mosfet", "")


def test_api_vorschlaege_mit_schreibschutz(geschuetzt, lager_voll):
    assert geschuetzt.post("/api/v1/drafts", json={"input": "NE555"}).status_code == 403
    token = {"X-Lager-Token": "geheim"}
    ok = geschuetzt.post("/api/v1/drafts", json={"input": "NE555"}, headers=token)
    assert ok.status_code == 201
    assert geschuetzt.get("/api/v1/drafts").json()["anzahl"] == 1
    assert geschuetzt.delete(f"/api/v1/drafts/{ok.json()['id']}").status_code == 403


# ------------------------------------------------------------------ CLI


def test_cli_vorschlaege(run, lager_voll):
    assert "Keine offenen Vorschläge." in run("draft", "list").output

    # Die CLI wartet, bis der Vorschlag vorbereitet ist.
    result = run("draft", "new", "irlz44 mosfet to220", "--json")
    assert result.exit_code == 0, result.output
    created = json.loads(result.output)
    draft_id = created["id"]
    assert created["status"] == "ready"
    assert created["fields"]["part"] == {"value": "irlz44 mosfet to220", "source": {"kind": "input"}}
    assert run("draft", "new", "  ").exit_code == 1

    shown = run("draft", "show", draft_id)
    assert "Stand: bereit zum Prüfen" in shown.output
    assert "Bezeichnung: irlz44 mosfet to220  [aus deiner Eingabe]" in shown.output
    assert json.loads(run("draft", "show", draft_id, "--json").output) == created
    listed = json.loads(run("draft", "list", "--json").output)
    assert listed["anzahl"] == 1 and listed["eintraege"] == [created]
    assert f"{draft_id}  irlz44 mosfet to220  (bereit zum Prüfen" in run("draft", "list").output

    # Ohne Kategorie wird nichts angelegt, der Vorschlag bleibt.
    assert run("draft", "save", draft_id).exit_code == 1
    result = run(
        "draft", "save", draft_id, "-c", "mosfets", "-p", "IRLZ44", "-n", "MOSFET N-Kanal",
        "-q", "2", "--tags", "n-kanal, to-220", "--json",
    )
    assert result.exit_code == 0, result.output
    saved = json.loads(result.output)
    assert Path(saved["teil"]) == lager_voll / "mosfets" / "IRLZ44" and saved["fehler"] == []
    doc = yaml.safe_load((lager_voll / "mosfets" / "IRLZ44" / "part.yaml").read_text(encoding="utf-8"))
    assert (doc["name"], doc["quantity"], doc["tags"]) == ("MOSFET N-Kanal", 2, ["n-kanal", "to-220"])
    assert run("draft", "show", draft_id).exit_code == 1  # gespeichert, also weg

    other = json.loads(run("draft", "new", "NE555", "--json").output)["id"]
    result = run("draft", "discard", other, "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["verworfen"] == other
    listing = run("trash", "list").output
    assert "NE555  (Vorschlag, gelöscht am" in listing
    assert run("draft", "discard", other).exit_code == 1


def test_cli_speichern_erst_wenn_fertig(run, lager_voll):
    draft = drafts.create(lager_voll, "NE555")  # z. B. über die Seite, der Server bereitet noch vor
    assert "wartet" in run("draft", "list").output
    assert run("draft", "save", draft.id, "-c", "mosfets").exit_code == 1
    assert not (lager_voll / "mosfets" / "NE555").exists()


def test_cli_speichern_nimmt_vorgeschlagene_werte(run, lager_voll):
    draft = ready_draft(lager_voll, "IRF9530")

    def change(doc):
        source = {"kind": "api", "name": "Mouser", "url": "https://mouser.example/IRF9530"}
        doc["fields"]["category"] = {"value": "mosfets", "source": source}
        doc["fields"]["subcategory"] = {"value": "p-kanal", "source": source}
        doc["fields"]["name"] = {"value": "MOSFET P-Kanal", "source": source}
        doc["fields"]["aliases"] = {"value": ["IRF9530PBF"], "source": source}

    edit_doc(draft, change)
    shown = run("draft", "show", draft.id).output
    assert "Beschreibung: MOSFET P-Kanal  [von Mouser, https://mouser.example/IRF9530]" in shown
    result = run("draft", "save", draft.id)
    assert result.exit_code == 0, result.output
    doc = yaml.safe_load(
        (lager_voll / "mosfets" / "p-kanal" / "IRF9530" / "part.yaml").read_text(encoding="utf-8")
    )
    assert (doc["name"], doc["aliases"]) == ("MOSFET P-Kanal", ["IRF9530PBF"])
