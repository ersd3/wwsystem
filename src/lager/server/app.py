"""Web-Server: REST-API, Dateiauslieferung und Handy-Seiten.

Der Server ist nur ein weiterer Client des Kerns: Er nutzt dieselben
Funktionen wie die CLI (indexer, search, parts, files) und liefert dieselben Daten.
"""
import hashlib
import mimetypes
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote, urlencode

from fastapi import (
    APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, db, indexer
from .. import categories as catmod
from .. import dialogs as dialogmod
from .. import drafts as draftmod
from .. import files as filesmod
from .. import labels as labelmod
from .. import parts as partmod
from .. import root as rootmod
from .. import search as searchmod
from .. import trash as trashmod
from ..config import CONFIG_PATH, load_config, set_lager_root, set_public_url
from .schemas import (
    Category, Draft, DraftDiscardResult, DraftList, FileDeleteResult, Health, IndexStatus,
    NewCategory, NewDraft, NewPart, Part, PartChanges, PartDeleteResult, RebuildResult,
    SearchResult, TrashList, TrashRestoreResult, UploadResult,
)
from .worker import DraftWorker

HERE = Path(__file__).resolve().parent

# Anzeigenamen der Dateiarten. Unbekannte Arten werden mit ihrem Schlüssel gezeigt.
KIND_LABELS = {
    "datasheet": "Datenblatt",
    "cad3d": "3D-Modell",
    "kicad": "KiCad",
    "image": "Bild",
    "other": "Datei",
}
# Diese Dateien öffnet der Browser direkt, alles andere wird heruntergeladen.
# SVG fehlt bewusst: Eine SVG-Datei kann Skripte enthalten.
INLINE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
# Cookie, das der Browser nach dem Anmelden mit dem write_token bekommt (30 Tage).
TOKEN_COOKIE = "lager_token"
TOKEN_COOKIE_MAX_AGE = 30 * 24 * 3600
# Dateifeld eines HTML-Formulars. Bleibt es leer, schickt der Browser einen
# leeren Text statt einer Datei mit; deshalb ist hier auch str erlaubt.
FormFiles = List[Union[UploadFile, str]]
# Link unter der Meldung, nachdem etwas in den Papierkorb gewandert ist.
TRASH_LINK = {"href": "/papierkorb", "text": "Zum Papierkorb"}


def _filesize(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("kB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.1f} GB".replace(".", ",")


class RevalidatedStaticFiles(StaticFiles):
    """style.css und app.js: Der Browser fragt bei jedem Laden nach, ob sie sich geändert haben.

    Ohne Cache-Control darf ein Browser eine alte Fassung eine Weile weiterverwenden, ohne
    nachzufragen. Nach dem Update auf 0.7.0 hatte Lukas' Browser so noch die style.css von
    0.6.0: Die neuen Symbole wurden riesig und schwarz, die Knöpfe zerfielen. Die Nachfrage
    kostet wenig; ist die Datei gleich, antwortet der Server nur mit „unverändert“ (304).
    """

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


_static_versions: dict = {}


def static_version(name: str) -> str:
    """Kurze Kennung des Inhalts einer statischen Datei für ihre Adresse (style.css?v=…).

    Ändert sich die Datei, ändert sich die Adresse, und jeder Browser lädt sie neu.
    """
    path = HERE / "static" / name
    try:
        stat = path.stat()
    except OSError:
        return __version__
    key = (name, stat.st_mtime_ns, stat.st_size)
    if key not in _static_versions:
        _static_versions[key] = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    return _static_versions[key]


templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals["static_version"] = static_version


def _mm(value: float) -> str:
    """Maß für CSS: zwei Nachkommastellen, Punkt als Dezimalzeichen, ohne Endnullen."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


templates.env.filters["filesize"] = _filesize
templates.env.filters["mm"] = _mm
templates.env.filters["mm_de"] = labelmod.format_mm
templates.env.filters["ortszeit"] = trashmod.local_time
templates.env.globals["kind_label"] = lambda kind: KIND_LABELS.get(kind, kind)
templates.env.globals["describe_source"] = draftmod.describe_source
templates.env.globals["status_label"] = lambda status: draftmod.STATUS_LABELS.get(status, status)


# ------------------------------------------------------------------ Helfer


@contextmanager
def open_index(request: Request) -> Iterator[sqlite3.Connection]:
    """Öffnet den Index für eine Anfrage (und baut ihn auf, falls er fehlt)."""
    root = request.app.state.root
    indexer.ensure_index(root, request.app.state.cfg)
    conn = db.connect(root, create=False)
    try:
        yield conn
    finally:
        conn.close()


def _write_token(request: Request) -> str:
    return str(request.app.state.cfg.get("write_token") or "")


def _token_matches(request: Request, value: Optional[str]) -> bool:
    token = _write_token(request)
    return bool(token) and secrets.compare_digest((value or "").encode(), token.encode())


def may_write(request: Request, header_token: Optional[str] = None) -> bool:
    """Darf diese Anfrage schreiben?

    Ohne `write_token` in der config.yaml immer. Mit Token nur, wenn er im Kopffeld
    X-Lager-Token steht (API) oder der Browser sich angemeldet hat (Cookie).
    """
    if not _write_token(request):
        return True
    return _token_matches(request, header_token) or _token_matches(
        request, request.cookies.get(TOKEN_COOKIE)
    )


def write_protected(request: Request) -> bool:
    """Für die Seiten: Schreib-Funktionen ausblenden?"""
    return not may_write(request)


def require_write(
    request: Request, x_lager_token: Optional[str] = Header(default=None)
) -> None:
    """Schreibende Aufrufe brauchen den Token, falls in config.yaml einer gesetzt ist."""
    if not may_write(request, x_lager_token):
        raise HTTPException(
            403,
            "Schreibzugriff nur mit gültigem Kopffeld X-Lager-Token oder nach dem Anmelden im Browser.",
        )


def is_local(request: Request) -> bool:
    """Kommt die Anfrage vom Rechner, auf dem der Server läuft?"""
    return bool(request.client) and request.client.host in LOCAL_HOSTS


def _rebuild(request: Request) -> dict:
    """Liest die Ordner neu ein und merkt sich das Ergebnis für die Rückmeldung auf der Seite."""
    result = indexer.rebuild(request.app.state.root, request.app.state.cfg)
    request.app.state.last_rebuild = result
    return result


def _count(number: int, singular: str, plural: str) -> str:
    return f"{number} {singular if number == 1 else plural}"


def _rebuild_notice(request: Request, hinweis: str) -> Tuple[str, List[dict]]:
    """Text und Warnungen für die Erfolgsmeldung nach dem Einlesen (`?hinweis=...`)."""
    result = getattr(request.app.state, "last_rebuild", None)
    if hinweis not in ("eingelesen", "ordner") or not result:
        return "", []
    summary = (
        f"{_count(result['teile'], 'Bauteil', 'Bauteile')}, "
        f"{_count(result['dateien'], 'Datei', 'Dateien')}, "
        f"{_count(result['kategorien'], 'Kategorie', 'Kategorien')}"
    )
    if hinweis == "ordner":
        return f"Lager-Ordner umgestellt und eingelesen: {summary}.", result["warnungen"]
    return f"Ordner neu eingelesen: {summary} ({result['dauer_ms']} ms).", result["warnungen"]


def _split_list(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _chosen_subcategory(category: str, selected: str, typed: str, lenient: bool = False) -> str:
    """Unterkategorie aus den Formularfeldern; eine neu eingetippte geht vor der Auswahl.

    Die Auswahl hat die Form "<kategorie>/<unterkategorie>". Gehört sie zu einer anderen
    Kategorie (ohne JavaScript bleibt sie beim Wechsel der Kategorie stehen), ist das ein
    Fehler. Mit `lenient` wird sie stattdessen übergangen.
    """
    if typed.strip():
        return typed
    selected = selected.strip()
    if not selected:
        return ""
    prefix = f"{category}/"
    if selected.startswith(prefix):
        return selected[len(prefix):]
    if lenient:
        return ""
    raise ValueError(
        "Die gewählte Unterkategorie gehört zu einer anderen Kategorie. Bitte neu wählen."
    )


def _subcategory_options(request: Request, kategorien: List[dict]) -> List[dict]:
    """Alle Unterkategorien des Lagers für die Auswahlfelder (Ordner unter den Kategorien)."""
    root = request.app.state.root
    return [
        {"kategorie": k["id"], "label": k["label"], "pfad": sub}
        for k in kategorien
        for sub in catmod.subcategories(root, k["id"])
    ]


def _create_part(
    request: Request, part: str, category: str, data: dict, new_category: str = "",
    subcategory: str = "",
) -> Path:
    """Legt ein Bauteil an (auf Wunsch samt neuer Kategorie). Fehler als ValueError."""
    root = request.app.state.root
    # Erst prüfen, dann anlegen: Bei einer ungültigen Bezeichnung soll keine neue,
    # leere Kategorie zurückbleiben.
    partmod.validate_part_id(partmod.normalize_part_id(part))
    catmod.normalize_subcategory(subcategory)
    if new_category.strip():
        category = catmod.normalize_id(new_category)
        if not category:
            raise ValueError(f"Ungültiger Name für die neue Kategorie: {new_category!r}")
        if not (root / category).is_dir():
            catmod.add(root, category, new_category.strip())
    known = {d.name for d in rootmod.visible_dirs(root) if not rootmod.is_part_dir(d)}
    if not category:
        raise ValueError("Bitte eine Kategorie wählen oder eine neue eintragen.")
    if category not in known:
        raise ValueError(f"Kategorie existiert nicht: {category}")
    return partmod.create_part(root, category, part, data, subcategory)


def part_form(
    bezeichnung: str = Form(""),
    kategorie: str = Form(""),
    neue_kategorie: str = Form(""),
    unterkategorie: str = Form(""),
    neue_unterkategorie: str = Form(""),
    name: str = Form(""),
    hersteller: str = Form(""),
    lagerfach: str = Form(""),
    menge: str = Form("0"),
    tags: str = Form(""),
    aliase: str = Form(""),
    notizen: str = Form(""),
) -> dict:
    """Die Felder des Formulars „Neues Bauteil“ (auch auf der Seite „Vorschlag prüfen“)."""
    return {
        "bezeichnung": bezeichnung, "kategorie": kategorie, "neue_kategorie": neue_kategorie,
        "unterkategorie": unterkategorie, "neue_unterkategorie": neue_unterkategorie,
        "name": name, "hersteller": hersteller, "lagerfach": lagerfach, "menge": menge,
        "tags": tags, "aliase": aliase, "notizen": notizen,
    }


def _create_from_form(request: Request, form: dict) -> Path:
    """Legt ein Bauteil aus den Formularfeldern an (siehe part_form). Fehler als ValueError."""
    try:
        quantity = int(form["menge"].strip() or "0")
    except ValueError:
        raise ValueError("Die Menge muss eine ganze Zahl sein.") from None
    if not form["bezeichnung"].strip():
        raise ValueError("Bitte eine Bezeichnung eintragen.")
    # Bei einer neu eingetippten Kategorie kann die Auswahl darunter nicht passen.
    new_cat = bool(form["neue_kategorie"].strip())
    effective = catmod.normalize_id(form["neue_kategorie"]) if new_cat else form["kategorie"]
    subcategory = _chosen_subcategory(
        effective, form["unterkategorie"], form["neue_unterkategorie"], lenient=new_cat
    )
    return _create_part(
        request,
        form["bezeichnung"],
        form["kategorie"],
        {
            "name": form["name"].strip(), "manufacturer": form["hersteller"].strip(),
            "location": form["lagerfach"].strip(), "quantity": quantity,
            "tags": _split_list(form["tags"]), "aliases": _split_list(form["aliase"]),
            "notes": form["notizen"].strip(),
        },
        form["neue_kategorie"],
        subcategory,
    )


def _save_uploads(
    request: Request, part_dir: Path, uploads: Optional[Sequence[Union[UploadFile, str]]]
) -> Tuple[List[str], List[str]]:
    """Speichert hochgeladene Dateien. Liefert (hinzugefügt, Fehlermeldungen)."""
    added: List[str] = []
    errors: List[str] = []
    for upload in uploads or []:
        if isinstance(upload, str) or not upload.filename:
            continue  # leeres Dateifeld im Formular
        try:
            target = filesmod.add_file(
                part_dir, upload.filename, upload.file, request.app.state.cfg
            )
            added.append(target.relative_to(part_dir).as_posix())
        except (ValueError, OSError) as e:
            errors.append(str(e))
    return added, errors


def _part_dir(request: Request, part: str) -> Optional[Path]:
    with open_index(request) as conn:
        found = searchmod.get_part(conn, part)
    if found is None:
        return None
    return request.app.state.root.joinpath(*found["path"].split("/"))


def _owning_part_dir(root: Path, path: Path) -> Optional[Path]:
    """Der Bauteil-Ordner, in dem `path` liegt (oder `path` selbst, wenn es einer ist)."""
    for folder in (path, *path.parents):
        if folder == root:
            return None
        if (folder / "part.yaml").is_file():
            return folder
    return None


def switch_root(app: FastAPI, raw_path: str, create: bool = False) -> Path:
    """Stellt den Server auf einen anderen Lager-Ordner um und merkt ihn in config.yaml."""
    raw = raw_path.strip().strip('"')
    if not raw:
        raise ValueError("Bitte einen Pfad angeben.")
    target = Path(os.path.expanduser(raw))
    if not target.is_absolute():
        raise ValueError("Bitte den vollständigen Pfad angeben, zum Beispiel D:\\Lager.")
    target = target.resolve()
    check = rootmod.check_root(target)
    if not check.valid:
        if not create:
            raise ValueError(
                f"In {target} liegt kein Lager ({check.reason}). "
                "Zum Anlegen eines neuen Lagers das Häkchen setzen."
            )
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError(
                f"{target} ist nicht leer und enthält kein Lager. "
                "Ein neues Lager wird nur in einem leeren oder neuen Ordner angelegt."
            )
        rootmod.create_structure(target)
    # Erst einlesen: Scheitert das, bleibt der bisherige Ordner eingestellt.
    app.state.last_rebuild = indexer.rebuild(target, app.state.cfg)
    set_lager_root(str(target), app.state.config_path)
    app.state.root = target
    app.state.worker.wake()  # wartende Vorschläge im neuen Lager vorbereiten
    return target


# ----------------------------------------------------------------- REST-API

api = APIRouter(tags=["api"])


@api.get("/health", response_model=Health, summary="Lebenszeichen")
def api_health() -> dict:
    return {"status": "ok", "version": __version__}


@api.get("/parts", response_model=SearchResult, summary="Bauteile suchen")
def api_parts(
    request: Request,
    q: str = Query("", description="Suchbegriffe; alle müssen vorkommen. Leer = alle."),
    category: str = Query("", description="Nur in dieser Kategorie-ID"),
    limit: int = Query(50, ge=1, le=searchmod.MAX_LIMIT),
) -> dict:
    with open_index(request) as conn:
        hits = searchmod.search(conn, q, category or None, limit)
    return {"suche": q, "kategorie": category, "anzahl": len(hits), "treffer": hits}


@api.post(
    "/parts",
    response_model=Part,
    status_code=201,
    dependencies=[Depends(require_write)],
    summary="Neues Bauteil anlegen",
)
def api_create_part(request: Request, body: NewPart) -> dict:
    data = body.model_dump(exclude={"part", "category", "subcategory"})
    try:
        part_dir = _create_part(
            request, body.part, body.category, data, subcategory=body.subcategory
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    _rebuild(request)
    with open_index(request) as conn:
        return searchmod.get_part(conn, part_dir.name)


@api.get("/parts/{part}", response_model=Part, summary="Ein Bauteil mit seinen Dateien")
def api_part(request: Request, part: str) -> dict:
    with open_index(request) as conn:
        found = searchmod.get_part(conn, part)
    if found is None:
        raise HTTPException(404, f"Teil nicht gefunden: {part}")
    return found


@api.patch(
    "/parts/{part}",
    response_model=Part,
    dependencies=[Depends(require_write)],
    summary="Bauteil ändern, umbenennen oder verschieben (nur die mitgeschickten Felder)",
)
def api_update_part(request: Request, part: str, body: PartChanges) -> dict:
    """`part` benennt um, `category` und `subcategory` verschieben, der Rest ändert Angaben.

    Nach einem Umbenennen steht die alte Bezeichnung in den Aliasen.
    """
    part_dir = _part_dir(request, part)
    if part_dir is None:
        raise HTTPException(404, f"Teil nicht gefunden: {part}")
    root = request.app.state.root
    changes = body.model_dump(exclude_unset=True)
    move = {key: changes.pop(key) for key in ("part", "category", "subcategory") if key in changes}
    try:
        if changes:
            part_dir = partmod.update_part(root, part_dir.name, changes)
        if move:
            part_dir = partmod.move_part(
                root, part_dir.name, move.get("part"), move.get("category"), move.get("subcategory")
            )
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        _rebuild(request)
    with open_index(request) as conn:
        return searchmod.get_part(conn, part_dir.name)


@api.delete(
    "/parts/{part}",
    response_model=PartDeleteResult,
    dependencies=[Depends(require_write)],
    summary="Bauteil löschen (sein Ordner wandert in den Papierkorb des Lagers)",
)
def api_delete_part(request: Request, part: str) -> dict:
    part_dir = _part_dir(request, part)
    if part_dir is None:
        raise HTTPException(404, f"Teil nicht gefunden: {part}")
    root = request.app.state.root
    try:
        trashed = partmod.delete_part(root, part_dir.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _rebuild(request)
    return {"geloescht": part_dir.name, "papierkorb": trashed.relative_to(root).as_posix()}


@api.post(
    "/parts/{part}/files",
    response_model=UploadResult,
    dependencies=[Depends(require_write)],
    summary="Dateien (z. B. Datenblätter) zu einem Bauteil hochladen",
)
def api_add_files(request: Request, part: str, files: List[UploadFile] = File(...)) -> dict:
    part_dir = _part_dir(request, part)
    if part_dir is None:
        raise HTTPException(404, f"Teil nicht gefunden: {part}")
    added, errors = _save_uploads(request, part_dir, files)
    if added:
        _rebuild(request)
    elif errors:
        raise HTTPException(400, "; ".join(errors))
    with open_index(request) as conn:
        return {"hinzugefuegt": added, "fehler": errors, "teil": searchmod.get_part(conn, part)}


@api.delete(
    "/parts/{part}/files/{rel_path:path}",
    response_model=FileDeleteResult,
    dependencies=[Depends(require_write)],
    summary="Datei eines Bauteils löschen (sie wandert in den Papierkorb des Lagers)",
)
def api_delete_file(request: Request, part: str, rel_path: str) -> dict:
    """`rel_path` ist der Pfad im Bauteil-Ordner, z. B. `kicad/TO-220.kicad_mod`."""
    part_dir = _part_dir(request, part)
    if part_dir is None:
        raise HTTPException(404, f"Teil nicht gefunden: {part}")
    root = request.app.state.root
    try:
        trashed = filesmod.remove_file(root, part_dir, rel_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _rebuild(request)
    with open_index(request) as conn:
        return {
            "geloescht": rel_path,
            "papierkorb": trashed.relative_to(root).as_posix(),
            "teil": searchmod.get_part(conn, part_dir.name),
        }


@api.get("/trash", response_model=TrashList, summary="Inhalt des Papierkorbs, das Neueste zuerst")
def api_trash(request: Request) -> dict:
    root = request.app.state.root
    found = [entry.as_dict(root) for entry in trashmod.entries(root)]
    return {"papierkorb": str(trashmod.trash_dir(root)), "anzahl": len(found), "eintraege": found}


@api.post(
    "/trash/{entry_id}/restore",
    response_model=TrashRestoreResult,
    dependencies=[Depends(require_write)],
    summary="Eintrag aus dem Papierkorb an seinen alten Platz zurückholen",
)
def api_trash_restore(request: Request, entry_id: str) -> dict:
    """`entry_id` ist die `id` aus `GET /api/v1/trash`, z. B. `20261126T205502Z`."""
    root = request.app.state.root
    try:
        described = trashmod.find_entry(root, entry_id).as_dict(root)
    except ValueError as e:
        raise HTTPException(404, str(e))
    try:
        target = trashmod.restore(root, entry_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    _rebuild(request)
    owner = _owning_part_dir(root, target)
    with open_index(request) as conn:
        part = searchmod.get_part(conn, owner.name) if owner is not None else None
    return {
        "wiederhergestellt": target.relative_to(root).as_posix(),
        "eintrag": described,
        "teil": part,
    }


@api.get(
    "/drafts",
    response_model=DraftList,
    summary="Offene Vorschläge („Automatisch ergänzen“), der neueste zuerst",
)
def api_drafts(request: Request) -> dict:
    root = request.app.state.root
    found = [draft.as_dict(root) for draft in draftmod.entries(root)]
    return {"ordner": str(draftmod.drafts_dir(root)), "anzahl": len(found), "eintraege": found}


@api.post(
    "/drafts",
    response_model=Draft,
    status_code=201,
    dependencies=[Depends(require_write)],
    summary="Vorschlag aus einer Eingabe anlegen (Name, Bestellnummer oder Suchbegriff)",
)
def api_create_draft(request: Request, body: NewDraft) -> dict:
    """Antwortet sofort mit `status: queued`; vorbereitet wird im Hintergrund. Den Stand
    zeigt `GET /api/v1/drafts/{id}` (`ready` = bereit zum Prüfen).

    Gespeichert wird ein Vorschlag nur von Lukas, auf der Seite `/vorschlag/<id>`
    oder mit `lager draft save`. Deshalb gibt es dafür keinen API-Aufruf (KONZEPT.md D25)."""
    root = request.app.state.root
    try:
        draft = draftmod.create(root, body.input)
    except ValueError as e:
        raise HTTPException(400, str(e))
    request.app.state.worker.wake()
    return draft.as_dict(root)


@api.get("/drafts/{draft_id}", response_model=Draft, summary="Ein Vorschlag mit Herkunft je Wert")
def api_draft(request: Request, draft_id: str) -> dict:
    root = request.app.state.root
    try:
        return draftmod.load(root, draft_id).as_dict(root)
    except draftmod.DraftNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(500, str(e))


@api.delete(
    "/drafts/{draft_id}",
    response_model=DraftDiscardResult,
    dependencies=[Depends(require_write)],
    summary="Vorschlag verwerfen (er wandert in den Papierkorb des Lagers)",
)
def api_discard_draft(request: Request, draft_id: str) -> dict:
    root = request.app.state.root
    try:
        trashed = draftmod.discard(root, draft_id)
    except draftmod.DraftNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"verworfen": draft_id, "papierkorb": trashed.relative_to(root).as_posix()}


@api.get("/categories", response_model=List[Category], summary="Kategorien mit Teil-Anzahl")
def api_categories(request: Request) -> list:
    with open_index(request) as conn:
        found = searchmod.list_categories(conn)
    root = request.app.state.root
    return [{**c, "subcategories": catmod.subcategories(root, c["id"])} for c in found]


@api.post(
    "/categories",
    response_model=Category,
    status_code=201,
    dependencies=[Depends(require_write)],
    summary="Neue Kategorie anlegen",
)
def api_create_category(request: Request, body: NewCategory) -> dict:
    try:
        entry = catmod.add(request.app.state.root, body.id, body.label)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _rebuild(request)
    return {"id": entry["id"], "label": entry["label"], "listed": True, "parts": 0}


@api.get(
    "/index",
    response_model=IndexStatus,
    response_model_exclude_none=True,
    summary="Zustand des Such-Index",
)
def api_index_status(request: Request) -> dict:
    return indexer.status(request.app.state.root)


@api.post(
    "/index/rebuild",
    response_model=RebuildResult,
    dependencies=[Depends(require_write)],
    summary="Index aus den Ordnern neu aufbauen",
)
def api_index_rebuild(request: Request) -> dict:
    return _rebuild(request)


# ------------------------------------------------------------------ Dateien

files = APIRouter(tags=["dateien"])


@files.get("/files/{rel_path:path}", summary="Datei eines Bauteils (Pfad wie im Lager-Ordner)")
def get_file(request: Request, rel_path: str) -> FileResponse:
    with open_index(request) as conn:
        entry = searchmod.find_file(conn, rel_path)
    if entry is None:
        raise HTTPException(404, "Datei nicht gefunden.")
    # rel_path steht genau so im Index, zeigt also sicher in einen Bauteil-Ordner.
    full = request.app.state.root.joinpath(*rel_path.split("/"))
    if not full.is_file():
        raise HTTPException(404, "Datei steht im Index, fehlt aber im Ordner. Index neu aufbauen.")
    inline = entry["ext"] in INLINE_EXTENSIONS
    return FileResponse(
        full,
        media_type=mimetypes.guess_type(full.name)[0] or "application/octet-stream",
        filename=full.name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


# ------------------------------------------------------------- Handy-Seiten

pages = APIRouter(include_in_schema=False)


def _page_context(request: Request, conn: sqlite3.Connection) -> dict:
    return {
        "kategorien": searchmod.list_categories(conn),
        "index": indexer.status(request.app.state.root),
        "schreibschutz": write_protected(request),
        "token_aktiv": bool(_write_token(request)),
        "lokal": is_local(request),
        "lager_root": str(request.app.state.root),
        "papierkorb": trashmod.TRASH_DIR,
        "papierkorb_anzahl": len(trashmod.entries(request.app.state.root)),
        "vorschlaege_bereit": sum(
            1 for d in draftmod.entries(request.app.state.root) if d.status == "ready"
        ),
        "version": __version__,
        "q": "",
        "kategorie": "",
        "meldung": "",
        "erfolg": "",
        "erfolg_link": None,
        "warnungen": [],
    }


def _to_start(part: str, hinweis: str) -> RedirectResponse:
    """Weiter zur Startseite mit Meldung, z. B. nach dem Anlegen (Wunsch von Lukas, 2026-11-27)."""
    return RedirectResponse("/?" + urlencode({"hinweis": hinweis, "teil": part}), status_code=303)


def _search_page(
    request: Request,
    q: str = "",
    kategorie: str = "",
    meldung: str = "",
    status: int = 200,
    hinweis: str = "",
    teil: str = "",
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        hits = searchmod.search(conn, q, kategorie or None, 100)
        found = searchmod.get_part(conn, teil) if teil else None
    erfolg, warnungen = _rebuild_notice(request, hinweis)
    # Gemeldet wird nur, was am Lager auch stimmt (das Bauteil ist weg bzw. da).
    if hinweis == "geloescht" and teil and found is None:
        erfolg = (
            f"{teil} ist gelöscht und liegt jetzt im Papierkorb des Lagers. "
            "Von dort lässt es sich wiederherstellen."
        )
        context["erfolg_link"] = TRASH_LINK
    elif hinweis in ("angelegt", "wiederhergestellt") and found is not None:
        what = "ist angelegt" if hinweis == "angelegt" else "ist aus dem Papierkorb zurück"
        erfolg = f"„{found['part']}“ {what}."
        context["erfolg_link"] = {"href": f"/p/{quote(found['part'])}", "text": "Zum Bauteil"}
    context.update(
        {
            "q": q, "kategorie": kategorie, "treffer": hits, "meldung": meldung,
            "erfolg": erfolg, "warnungen": warnungen,
        }
    )
    return templates.TemplateResponse(request, "index.html", context, status_code=status)


def _part_notice(
    found: dict, hochgeladen: Sequence[str], geloescht: str, frueher: str, wiederhergestellt: str
) -> Tuple[str, bool]:
    """Erfolgsmeldung der Bauteilseite und ob darunter der Link zum Papierkorb gehört.

    Gemeldet wird nur, was am Bauteil auch stimmt.
    """
    notes: List[str] = []
    trash_link = False
    paths = {f["path"] for f in found["files"]}
    uploaded = [name for name in hochgeladen if name in paths]
    if uploaded:
        notes.append(f"{_count(len(uploaded), 'Datei', 'Dateien')} hochgeladen: {', '.join(uploaded)}.")
    if geloescht and geloescht not in paths:
        notes.append(f"{geloescht} ist gelöscht und liegt jetzt im Papierkorb des Lagers.")
        trash_link = True
    if wiederhergestellt:
        if wiederhergestellt.lower() == found["part"].lower():
            notes.append(f"{found['part']} ist aus dem Papierkorb zurück.")
        elif wiederhergestellt in paths:
            notes.append(f"{wiederhergestellt} ist aus dem Papierkorb zurück.")
    if frueher and frueher.lower() in (alias.lower() for alias in found["aliases"]):
        notes.append(f"„{frueher}“ heißt jetzt „{found['part']}“.")
    return " ".join(notes), trash_link


def _part_page(
    request: Request,
    part: str,
    meldung: str = "",
    status: Optional[int] = None,
    hochgeladen: Sequence[str] = (),
    geloescht: str = "",
    frueher: str = "",
    wiederhergestellt: str = "",
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    qr = None
    if found:
        base, _source = label_base_url(request)
        if base:
            qr = labelmod.make_qr(labelmod.part_url(base, found["part"]))
        notice, trash_link = _part_notice(found, hochgeladen, geloescht, frueher, wiederhergestellt)
        context["erfolg"] = notice
        context["erfolg_link"] = TRASH_LINK if trash_link else None
    context.update({"teil": found, "gesucht": part, "meldung": meldung, "qr": qr})
    if status is None:
        status = 200 if found else 404
    return templates.TemplateResponse(request, "part.html", context, status_code=status)


def _new_page(
    request: Request,
    form: dict,
    meldung: str = "",
    status: int = 200,
    eingabe: str = "",
    erfolg: str = "",
    erfolg_link: Optional[dict] = None,
    fokus: bool = False,
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
    context.update(
        {
            "form": form,
            "meldung": meldung,
            "erfolg": erfolg,
            "erfolg_link": erfolg_link,
            "unterkategorien": _subcategory_options(request, context["kategorien"]),
            "eingabe": eingabe,
            "fokus": fokus or bool(meldung and eingabe),
            "entwuerfe": draftmod.entries(request.app.state.root),
        }
    )
    return templates.TemplateResponse(request, "new.html", context, status_code=status)


@pages.get("/", response_class=HTMLResponse)
def page_search(
    request: Request, q: str = "", kategorie: str = "", hinweis: str = "", teil: str = ""
):
    return _search_page(request, q, kategorie, hinweis=hinweis, teil=teil)


@pages.get("/suche", response_class=HTMLResponse)
def page_search_fragment(request: Request, q: str = "", kategorie: str = ""):
    """Nur die Trefferliste, für die Suche beim Tippen (static/app.js)."""
    with open_index(request) as conn:
        context = {
            "q": q,
            "kategorie": kategorie,
            "kategorien": searchmod.list_categories(conn),
            "treffer": searchmod.search(conn, q, kategorie or None, 100),
        }
    return templates.TemplateResponse(request, "_results.html", context)


@pages.get("/p/{part}", response_class=HTMLResponse)
def page_part(
    request: Request,
    part: str,
    hochgeladen: List[str] = Query(default=[]),
    geloescht: str = "",
    frueher: str = "",
    wiederhergestellt: str = "",
):
    with open_index(request) as conn:
        renamed = None
        if searchmod.get_part(conn, part) is None:
            renamed = searchmod.find_by_alias(conn, part)
    if renamed is not None:
        # Alte Bezeichnung eines umbenannten Bauteils, z. B. von einem gedruckten QR-Etikett.
        return RedirectResponse(
            f"/p/{quote(renamed['part'])}?" + urlencode({"frueher": part}), status_code=307
        )
    return _part_page(
        request, part, hochgeladen=hochgeladen, geloescht=geloescht, frueher=frueher,
        wiederhergestellt=wiederhergestellt,
    )


def _edit_page(request: Request, part: str, form: Optional[dict] = None, meldung: str = "", status: int = 200):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    if found is None:
        return _part_page(request, part)
    if form is None:
        sub = found["subcategory"]
        form = {
            "kategorie": found["category"],
            "unterkategorie": f"{found['category']}/{sub}" if sub else "",
            "neue_unterkategorie": "",
            "name": found["name"], "hersteller": found["manufacturer"],
            "lagerfach": found["location"], "menge": str(found["quantity"]),
            "einheit": found["unit"], "tags": ", ".join(found["tags"]),
            "aliase": ", ".join(found["aliases"]), "notizen": found["notes"],
        }
    options = _subcategory_options(request, context["kategorien"])
    # Die eigene Unterkategorie muss zur Auswahl stehen, auch wenn sie von Hand tiefer
    # verschachtelt wurde als die Liste reicht. Sonst würde Speichern das Bauteil verschieben.
    here = {"kategorie": found["category"], "label": found["category_label"], "pfad": found["subcategory"]}
    if here["pfad"] and not any(
        (o["kategorie"], o["pfad"]) == (here["kategorie"], here["pfad"]) for o in options
    ):
        options.append(here)
    context.update({"teil": found, "form": form, "meldung": meldung, "unterkategorien": options})
    return templates.TemplateResponse(request, "edit.html", context, status_code=status)


@pages.get("/p/{part}/bearbeiten", response_class=HTMLResponse)
def page_edit(request: Request, part: str):
    return _edit_page(request, part)


@pages.post("/p/{part}/bearbeiten", dependencies=[Depends(require_write)])
def page_edit_submit(
    request: Request,
    part: str,
    kategorie: str = Form(""),
    unterkategorie: str = Form(""),
    neue_unterkategorie: str = Form(""),
    name: str = Form(""),
    hersteller: str = Form(""),
    lagerfach: str = Form(""),
    menge: str = Form("0"),
    einheit: str = Form(""),
    tags: str = Form(""),
    aliase: str = Form(""),
    notizen: str = Form(""),
):
    """Speichert die Angaben; eine andere Kategorie oder Unterkategorie verschiebt den Ordner.

    Umbenennen und Löschen haben eigene Seiten (`/umbenennen`, `/loeschen`).
    """
    form = {
        "kategorie": kategorie, "unterkategorie": unterkategorie,
        "neue_unterkategorie": neue_unterkategorie,
        "name": name, "hersteller": hersteller, "lagerfach": lagerfach, "menge": menge,
        "einheit": einheit, "tags": tags, "aliase": aliase, "notizen": notizen,
    }
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    root = request.app.state.root
    old_category, old_sub = partmod.location_of(root, part_dir)
    # Ein leeres Feld „Kategorie“ heißt: bleibt, wie es ist (z. B. bei anderen Clients).
    category = kategorie.strip() or None
    try:
        subcategory = None
        if category is not None or neue_unterkategorie.strip():
            subcategory = _chosen_subcategory(
                category or old_category, unterkategorie, neue_unterkategorie
            )
        if (category or old_category, subcategory) == (old_category, old_sub):
            category = subcategory = None  # derselbe Ort wie bisher: nichts zu verschieben
        part_dir = partmod.update_part(
            root,
            part_dir.name,
            {
                "name": name, "manufacturer": hersteller, "location": lagerfach,
                "quantity": menge.strip() or "0", "unit": einheit,
                "tags": _split_list(tags), "aliases": _split_list(aliase), "notes": notizen,
            },
        )
    except ValueError as e:
        return _edit_page(request, part, form, str(e), 400)
    if category is not None or subcategory is not None:
        try:
            part_dir = partmod.move_part(root, part_dir.name, None, category, subcategory)
        except ValueError as e:
            _rebuild(request)
            return _edit_page(
                request, part, form, f"Die übrigen Angaben sind gespeichert. Aber: {e}", 400
            )
    _rebuild(request)
    return RedirectResponse(f"/p/{quote(part_dir.name)}", status_code=303)


def _rename_page(
    request: Request, part: str, neu: Optional[str] = None, meldung: str = "", status: int = 200
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    if found is None:
        return _part_page(request, part)
    context.update({"teil": found, "neu": found["part"] if neu is None else neu, "meldung": meldung})
    return templates.TemplateResponse(request, "rename.html", context, status_code=status)


@pages.get("/p/{part}/umbenennen", response_class=HTMLResponse)
def page_rename(request: Request, part: str):
    return _rename_page(request, part)


@pages.post("/p/{part}/umbenennen", dependencies=[Depends(require_write)])
def page_rename_submit(request: Request, part: str, bezeichnung: str = Form("")):
    """Benennt ein Bauteil um (Ordner und part.yaml); die alte Bezeichnung wird Alias."""
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    new_id = partmod.normalize_part_id(bezeichnung)
    if new_id == part_dir.name:
        return RedirectResponse(f"/p/{quote(part_dir.name)}", status_code=303)  # nichts geändert
    try:
        moved = partmod.move_part(request.app.state.root, part_dir.name, new_id=new_id)
    except ValueError as e:
        return _rename_page(request, part, bezeichnung, str(e), 400)
    _rebuild(request)
    target = f"/p/{quote(moved.name)}"
    if moved.name.lower() != part_dir.name.lower():
        target += "?" + urlencode({"frueher": part_dir.name})
    return RedirectResponse(target, status_code=303)


def _delete_page(request: Request, part: str, meldung: str = "", status: int = 200):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    if found is None:
        return _part_page(request, part)
    context.update(
        {
            "teil": found,
            "meldung": meldung,
            "papierkorb_ordner": str(trashmod.trash_dir(request.app.state.root)),
        }
    )
    return templates.TemplateResponse(request, "delete.html", context, status_code=status)


@pages.get("/p/{part}/loeschen", response_class=HTMLResponse)
def page_delete(request: Request, part: str):
    """Rückfrage vor dem Löschen eines Bauteils."""
    return _delete_page(request, part)


@pages.post("/p/{part}/loeschen", dependencies=[Depends(require_write)])
def page_delete_part(request: Request, part: str, sicher: str = Form("")):
    """Löscht ein Bauteil: Sein Ordner wandert in den Papierkorb des Lagers.

    Das Feld `sicher` schickt nur der Knopf „Ja, löschen“ der Rückfrage-Seite mit.
    """
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    if not sicher:
        return _delete_page(request, part, "Zum Löschen bitte auf „Ja, löschen“ tippen.", 400)
    try:
        partmod.delete_part(request.app.state.root, part_dir.name)
    except ValueError as e:
        return _delete_page(request, part, str(e), 400)
    _rebuild(request)
    return RedirectResponse(
        "/?" + urlencode({"hinweis": "geloescht", "teil": part_dir.name}), status_code=303
    )


@pages.get("/anmelden", response_class=HTMLResponse)
def page_login(request: Request):
    return _login_page(request)


def _login_page(request: Request, meldung: str = "", status: int = 200):
    with open_index(request) as conn:
        context = _page_context(request, conn)
    context["meldung"] = meldung
    return templates.TemplateResponse(request, "login.html", context, status_code=status)


@pages.post("/anmelden")
def page_login_submit(request: Request, token: str = Form("")):
    """Prüft den write_token und merkt ihn im Browser als Cookie."""
    if not _write_token(request):
        return RedirectResponse("/", status_code=303)
    if not _token_matches(request, token.strip()):
        return _login_page(request, "Der Token stimmt nicht.", 403)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        TOKEN_COOKIE, token.strip(), max_age=TOKEN_COOKIE_MAX_AGE, httponly=True, samesite="lax"
    )
    return response


@pages.post("/abmelden")
def page_logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(TOKEN_COOKIE)
    return response


@pages.post("/p/{part}/dateien", dependencies=[Depends(require_write)])
def page_add_files(request: Request, part: str, dateien: FormFiles = File(default=[])):
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    added, errors = _save_uploads(request, part_dir, dateien)
    if added:
        _rebuild(request)
    if errors:
        return _part_page(
            request, part, "Nicht gespeichert: " + "; ".join(errors), 400, hochgeladen=added
        )
    if not added:
        return _part_page(request, part, "Es wurde keine Datei ausgewählt.", 400)
    return RedirectResponse(
        f"/p/{quote(part_dir.name)}?" + urlencode([("hochgeladen", name) for name in added]),
        status_code=303,
    )


@pages.post("/p/{part}/dateien/loeschen", dependencies=[Depends(require_write)])
def page_delete_file(request: Request, part: str, datei: str = Form("")):
    """Löscht eine Datei eines Bauteils: Sie wandert in den Papierkorb des Lagers."""
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    try:
        filesmod.remove_file(request.app.state.root, part_dir, datei)
    except ValueError as e:
        return _part_page(request, part, str(e), 400)
    _rebuild(request)
    return RedirectResponse(
        f"/p/{quote(part_dir.name)}?" + urlencode({"geloescht": datei}), status_code=303
    )


@pages.get("/neu", response_class=HTMLResponse)
def page_new(request: Request, kategorie: str = "", hinweis: str = "", entwurf: str = ""):
    """Neues Bauteil. Die Meldungen nach Vorschlägen prüfen, was wirklich der Fall ist."""
    root = request.app.state.root
    erfolg, link, fokus = "", None, False
    if hinweis == "vorschlag" and trashmod.is_stamp(entwurf):
        try:
            draft = draftmod.load(root, entwurf)
        except ValueError:
            draft = None
        if draft is not None:
            fokus = True  # gleich das nächste Bauteil eintippen
            if draft.status == "ready":
                erfolg = f"Der Vorschlag für „{draft.input}“ ist fertig und steht unten zum Prüfen."
            else:
                erfolg = (
                    f"„{draft.input}“ wird im Hintergrund vorbereitet. Du kannst gleich das "
                    "nächste Bauteil eingeben; fertige Vorschläge stehen unten zum Prüfen."
                )
    elif hinweis == "verworfen" and trashmod.is_stamp(entwurf):
        if not (draftmod.drafts_dir(root) / entwurf).exists():
            erfolg = "Der Vorschlag ist verworfen und liegt im Papierkorb des Lagers."
            link = TRASH_LINK
    return _new_page(
        request, {"kategorie": kategorie, "menge": "0"}, erfolg=erfolg, erfolg_link=link,
        fokus=fokus,
    )


@pages.get("/neu/vorschlaege", response_class=HTMLResponse)
def page_draft_list(request: Request):
    """Nur die Liste der Vorschläge; static/app.js lädt sie nach, solange einer in Arbeit ist."""
    return templates.TemplateResponse(
        request, "_drafts.html", {"entwuerfe": draftmod.entries(request.app.state.root)}
    )


@pages.post("/neu", dependencies=[Depends(require_write)])
def page_new_submit(
    request: Request,
    form: dict = Depends(part_form),
    dateien: FormFiles = File(default=[]),
):
    try:
        part_dir = _create_from_form(request, form)
    except ValueError as e:
        return _new_page(request, form, str(e), 400)

    _added, errors = _save_uploads(request, part_dir, dateien)
    _rebuild(request)
    if errors:
        return _part_page(
            request,
            part_dir.name,
            "Das Bauteil ist angelegt, aber nicht jede Datei wurde gespeichert: " + "; ".join(errors),
            200,
        )
    return _to_start(part_dir.name, "angelegt")


# ------------------------------------------- Vorschläge („Automatisch ergänzen“)

# Formularfeld der Seite -> Feld im Entwurf. Darunter steht jeweils die Herkunft.
DRAFT_FORM_FIELDS = {
    "bezeichnung": "part",
    "kategorie": "category",
    "unterkategorie": "subcategory",
    "name": "name",
    "hersteller": "manufacturer",
    "aliase": "aliases",
    "tags": "tags",
    "notizen": "notes",
}


def _draft_form(request: Request, draft: draftmod.Draft, kategorien: List[dict]) -> dict:
    """Das Formular „Vorschlag prüfen“, vorbelegt mit den Werten des Entwurfs.

    Eine vorgeschlagene Kategorie oder Unterkategorie, die es noch nicht gibt, steht im
    Feld zum Anlegen. Menge und Lagerfach schlägt nie jemand vor; die trägt Lukas ein.
    """
    category, sub = draft.value("category"), draft.value("subcategory")
    form = {
        "bezeichnung": draft.value("part"),
        "kategorie": "",
        "neue_kategorie": "",
        "unterkategorie": "",
        "neue_unterkategorie": "",
        "name": draft.value("name"),
        "hersteller": draft.value("manufacturer"),
        "lagerfach": "",
        "menge": "0",
        "tags": ", ".join(draft.value("tags")),
        "aliase": ", ".join(draft.value("aliases")),
        "notizen": draft.value("notes"),
    }
    if category in {k["id"] for k in kategorien}:
        form["kategorie"] = category
        if sub and sub in catmod.subcategories(request.app.state.root, category):
            form["unterkategorie"] = f"{category}/{sub}"
        else:
            form["neue_unterkategorie"] = sub
    elif category:
        form["neue_kategorie"] = category
        form["neue_unterkategorie"] = sub
    return form


def _draft_sources(draft: draftmod.Draft, form: dict, proposed: dict) -> dict:
    """Herkunft je Formularfeld, aber nur solange dort noch der vorgeschlagene Wert steht."""
    shown = {}
    for name, field in DRAFT_FORM_FIELDS.items():
        source = draftmod.describe_source(draft.source(field))
        unchanged = all(
            form.get(key, "") == proposed.get(key, "")
            for key in (name, f"neue_{name}")
            if key in proposed
        )
        if source and unchanged:
            shown[name] = source
    return shown


def _draft_page(
    request: Request,
    draft_id: str,
    form: Optional[dict] = None,
    meldung: str = "",
    status: int = 200,
    erfolg: str = "",
):
    root = request.app.state.root
    with open_index(request) as conn:
        context = _page_context(request, conn)
        try:
            draft = draftmod.load(root, draft_id)
        except draftmod.DraftNotFound as e:
            draft, meldung, status = None, meldung or str(e), 404
        except ValueError as e:
            draft, meldung, status = None, meldung or str(e), 500
        herkunft, vergeben = {}, None
        if draft is not None:
            proposed = _draft_form(request, draft, context["kategorien"])
            form = form or proposed
            herkunft = _draft_sources(draft, form, proposed)
            if form["bezeichnung"].strip():
                vergeben = searchmod.get_part(conn, partmod.normalize_part_id(form["bezeichnung"]))
    context.update(
        {
            "entwurf": draft,
            "form": form or {},
            "herkunft": herkunft,
            "vergeben": vergeben,
            "meldung": meldung,
            "erfolg": erfolg if draft is not None else "",
            "unterkategorien": _subcategory_options(request, context["kategorien"]),
        }
    )
    return templates.TemplateResponse(request, "draft.html", context, status_code=status)


@pages.post("/neu/vorschlag", dependencies=[Depends(require_write)])
def page_draft_create(request: Request, eingabe: str = Form("")):
    """„Automatisch ergänzen“: legt einen Vorschlag an und kehrt gleich zurück.

    Vorbereitet wird er im Hintergrund (server/worker.py). Lukas kann sofort das nächste
    Bauteil eingeben und prüft die Vorschläge, sobald sie fertig sind.
    """
    try:
        draft = draftmod.create(request.app.state.root, eingabe)
    except ValueError as e:
        return _new_page(request, {"kategorie": "", "menge": "0"}, str(e), 400, eingabe=eingabe)
    request.app.state.worker.wake()
    return RedirectResponse(
        "/neu?" + urlencode({"hinweis": "vorschlag", "entwurf": draft.id}), status_code=303
    )


@pages.get("/vorschlag/{draft_id}", response_class=HTMLResponse)
def page_draft(request: Request, draft_id: str, hinweis: str = ""):
    erfolg = "Der Vorschlag ist aus dem Papierkorb zurück." if hinweis == "wiederhergestellt" else ""
    return _draft_page(request, draft_id, erfolg=erfolg)


@pages.post("/vorschlag/{draft_id}", dependencies=[Depends(require_write)])
def page_draft_save(
    request: Request,
    draft_id: str,
    form: dict = Depends(part_form),
    dateien: FormFiles = File(default=[]),
):
    """Speichern: legt das Bauteil mit den geprüften Werten an und räumt den Vorschlag weg."""
    root = request.app.state.root
    try:
        draft = draftmod.load(root, draft_id)
    except ValueError:
        return _draft_page(request, draft_id)  # zeigt, warum es ihn nicht (mehr) gibt
    try:
        draftmod.ensure_reviewable(draft)
    except ValueError as e:
        return _draft_page(request, draft_id, meldung=str(e), status=409)
    try:
        part_dir = _create_from_form(request, form)
    except ValueError as e:
        return _draft_page(request, draft_id, form, str(e), 400)
    errors = draftmod.finish(root, draft_id, part_dir, request.app.state.cfg)
    _added, upload_errors = _save_uploads(request, part_dir, dateien)
    _rebuild(request)
    errors += upload_errors
    if errors:
        return _part_page(
            request,
            part_dir.name,
            "Das Bauteil ist angelegt, aber nicht jede Datei wurde übernommen: " + "; ".join(errors),
            200,
        )
    return _to_start(part_dir.name, "angelegt")


@pages.post("/vorschlag/{draft_id}/verwerfen", dependencies=[Depends(require_write)])
def page_draft_discard(request: Request, draft_id: str):
    try:
        draftmod.discard(request.app.state.root, draft_id)
    except draftmod.DraftNotFound:
        return _draft_page(request, draft_id)
    except ValueError as e:
        return _draft_page(request, draft_id, meldung=str(e), status=400)
    return RedirectResponse(
        "/neu?" + urlencode({"hinweis": "verworfen", "entwurf": draft_id}), status_code=303
    )


@pages.post("/index/rebuild", dependencies=[Depends(require_write)])
def page_index_rebuild(request: Request):
    _rebuild(request)
    return RedirectResponse("/?hinweis=eingelesen", status_code=303)


@pages.post("/einstellungen/lager-ordner", dependencies=[Depends(require_write)])
def page_set_root(request: Request, pfad: str = Form(""), anlegen: str = Form("")):
    if not is_local(request):
        raise HTTPException(
            403, "Der Lager-Ordner lässt sich nur an dem PC ändern, auf dem der Server läuft."
        )
    try:
        switch_root(request.app, pfad, create=bool(anlegen))
    except (ValueError, OSError, db.IndexDbError) as e:
        return _search_page(request, meldung=str(e), status=400)
    return RedirectResponse("/?hinweis=ordner", status_code=303)


@pages.post("/einstellungen/ordner-waehlen", dependencies=[Depends(require_write)])
def page_pick_folder(request: Request) -> dict:
    """Öffnet am Server-PC das Ordner-Auswahlfenster und liefert den gewählten Pfad.

    Aufgerufen von static/app.js; die Antwort füllt nur das Eingabefeld. Umgestellt
    wird der Lager-Ordner erst mit „Übernehmen“. Ein leerer Pfad heißt: abgebrochen.
    """
    if not is_local(request):
        raise HTTPException(
            403, "Das Auswahlfenster gibt es nur an dem PC, auf dem der Server läuft."
        )
    try:
        chosen = dialogmod.pick_folder(request.app.state.root)
    except dialogmod.DialogUnavailable as e:
        raise HTTPException(503, str(e))
    return {"pfad": str(chosen) if chosen else ""}


# ---------------------------------------------------------------- Papierkorb


def _trash_page(request: Request, meldung: str = "", erfolg: str = "", status: int = 200):
    root = request.app.state.root
    with open_index(request) as conn:
        context = _page_context(request, conn)
    folder = trashmod.trash_dir(root)
    context.update(
        {
            "eintraege": [entry.as_dict(root) for entry in trashmod.entries(root)],
            "ordner": str(folder),
            "ordner_da": folder.is_dir(),
            "meldung": meldung,
            "erfolg": erfolg,
        }
    )
    return templates.TemplateResponse(request, "trash.html", context, status_code=status)


@pages.get("/papierkorb", response_class=HTMLResponse)
def page_trash(request: Request, hinweis: str = ""):
    erfolg = ""
    if hinweis == "explorer":
        # Windows lässt ein Programm im Hintergrund (den Server) kein Fenster vor den
        # Browser holen. Das neue Explorer-Fenster liegt deshalb oft dahinter.
        erfolg = (
            "Der Papierkorb ist im Explorer geöffnet. Liegt das Fenster nicht vorn, "
            "ist es über die Taskleiste zu erreichen."
        )
    return _trash_page(request, erfolg=erfolg)


@pages.post("/papierkorb/wiederherstellen", dependencies=[Depends(require_write)])
def page_trash_restore(request: Request, eintrag: str = Form("")):
    """Holt einen Eintrag zurück. Danach: Bauteil → Startseite mit Meldung, Datei → Seite
    ihres Bauteils, Vorschlag → Seite „Vorschlag prüfen“."""
    root = request.app.state.root
    try:
        target = trashmod.restore(root, eintrag)
    except ValueError as e:
        return _trash_page(request, meldung=str(e), status=400)
    _rebuild(request)
    if target.parent == draftmod.drafts_dir(root):
        return RedirectResponse(
            f"/vorschlag/{quote(target.name)}?hinweis=wiederhergestellt", status_code=303
        )
    owner = _owning_part_dir(root, target)
    if owner is None:
        return RedirectResponse("/papierkorb", status_code=303)
    if owner == target:  # ein ganzes Bauteil: zurück auf die Startseite
        return _to_start(owner.name, "wiederhergestellt")
    # Eine Datei: die Seite ihres Bauteils, dort ist sie wieder zu sehen.
    return RedirectResponse(
        f"/p/{quote(owner.name)}?"
        + urlencode({"wiederhergestellt": target.relative_to(owner).as_posix()}),
        status_code=303,
    )


@pages.post("/papierkorb/oeffnen")
def page_trash_open(request: Request):
    """Öffnet den Ordner des Papierkorbs im Explorer, nur an dem PC, auf dem der Server läuft."""
    if not is_local(request):
        raise HTTPException(
            403, "Der Explorer lässt sich nur an dem PC öffnen, auf dem der Server läuft."
        )
    try:
        dialogmod.reveal(trashmod.trash_dir(request.app.state.root))
    except dialogmod.DialogUnavailable as e:
        return _trash_page(request, meldung=str(e), status=503)
    return RedirectResponse("/papierkorb?hinweis=explorer", status_code=303)


# --------------------------------------------------------------- QR-Etiketten


def _request_port(request: Request) -> int:
    return request.url.port or (443 if request.url.scheme == "https" else 80)


def _suggested_base_url(request: Request) -> str:
    """Vorschlag für die Adresse in den QR-Codes; ermittelt wird er einmal je Serverstart."""
    cached = getattr(request.app.state, "label_suggestion", None)
    if cached is None:
        cached = labelmod.suggest_base_url(_request_port(request))
        request.app.state.label_suggestion = cached
    return cached


def label_base_url(request: Request, typed: str = "") -> Tuple[str, str]:
    """Adresse für die QR-Codes und ihre Herkunft: "eingabe", "config" oder "vorschlag".

    Eine ungültige Eingabe löst einen ValueError aus. Ohne Netz kann die Adresse leer sein.
    """
    if typed.strip():
        return labelmod.normalize_base_url(typed), "eingabe"
    server = request.app.state.cfg.get("server") or {}
    saved = str(server.get("public_url") or "").strip()
    if saved:
        try:
            return labelmod.normalize_base_url(saved), "config"
        except ValueError:
            pass  # unbrauchbarer Eintrag in der config.yaml: wie nicht gesetzt behandeln
    return _suggested_base_url(request), "vorschlag"


def _labels_page(
    request: Request,
    teil: Sequence[str] = (),
    q: str = "",
    kategorie: str = "",
    groesse: str = "",
    breite: str = "",
    hoehe: str = "",
    adresse: str = "",
    ohne_beschreibung: str = "",
    ohne_fach: str = "",
    meldung: str = "",
    erfolg: str = "",
    status: int = 200,
):
    problems = [meldung] if meldung else []
    try:
        size = labelmod.resolve_size(groesse, breite, hoehe)
    except ValueError as e:
        problems.append(str(e))
        size = labelmod.resolve_size()
    try:
        base, source = label_base_url(request, adresse)
    except ValueError as e:
        problems.append(str(e))
        base, source = label_base_url(request)

    wanted = list(dict.fromkeys(name.strip() for name in teil if name.strip()))
    with open_index(request) as conn:
        context = _page_context(request, conn)
        if wanted:
            found = {name: searchmod.get_part(conn, name) for name in wanted}
            missing = [name for name, part in found.items() if part is None]
            if missing:
                problems.append("Nicht gefunden: " + ", ".join(missing))
            by_id = {part["part"]: part for part in found.values() if part is not None}
            parts = list(by_id.values())
        else:
            parts = searchmod.search(conn, q, kategorie or None, searchmod.MAX_LIMIT)

    sheets = None
    hints: List[str] = []
    if base:
        sheets = labelmod.prepare(parts, base, size, not ohne_beschreibung, not ohne_fach)
        hints = labelmod.check_base_url(base)
        if 0 < sheets.min_module_mm < labelmod.MIN_MODULE_MM:
            hints.append(
                f"Die Punkte des QR-Codes werden nur {labelmod.format_mm(sheets.min_module_mm, 2)} mm "
                f"groß. Unter {labelmod.format_mm(labelmod.MIN_MODULE_MM)} mm muss das Handy sehr nah "
                "heran; besser eine größere Etikettengröße wählen."
            )
        if sheets.clipped:
            shown = ", ".join(sheets.clipped[:5]) + (" …" if len(sheets.clipped) > 5 else "")
            hints.append(
                f"Zu lang für diese Etikettengröße, die Bezeichnung wird abgeschnitten: {shown}. "
                "Eine größere Größe wählen."
            )
    else:
        problems.append("Bitte eine Adresse eintragen, unter der das Handy den Server erreicht.")
    if getattr(request.app.state, "bind_host", None) in LOCAL_HOSTS:
        hints.append(
            "Der Server ist gerade nur an diesem PC erreichbar. Damit das Handy die Codes "
            "öffnen kann, mit „lager serve --host 0.0.0.0“ starten."
        )

    context.update(
        {
            "meldung": " ".join(problems),
            "erfolg": erfolg,
            "bogen": sheets,
            "hinweise": hints,
            "groessen": labelmod.SIZES,
            "eigen": labelmod.CUSTOM_SIZE,
            "groesse": size,
            "adresse": base,
            "adresse_quelle": source,
            "auswahl": {
                "teile": [part["part"] for part in parts] if wanted else [],
                "q": q,
                "kategorie": kategorie,
                "breite": breite,
                "hoehe": hoehe,
                "ohne_beschreibung": bool(ohne_beschreibung),
                "ohne_fach": bool(ohne_fach),
            },
        }
    )
    return templates.TemplateResponse(request, "labels.html", context, status_code=status)


@pages.get("/etiketten", response_class=HTMLResponse)
def page_labels(
    request: Request,
    teil: List[str] = Query(default=[]),
    q: str = "",
    kategorie: str = "",
    groesse: str = "",
    breite: str = "",
    hoehe: str = "",
    adresse: str = "",
    ohne_beschreibung: str = "",
    ohne_fach: str = "",
    hinweis: str = "",
):
    erfolg = ""
    if hinweis == "adresse":
        erfolg = "Die Adresse ist gespeichert und gilt ab jetzt für alle QR-Codes."
    return _labels_page(
        request, teil, q, kategorie, groesse, breite, hoehe, adresse,
        ohne_beschreibung, ohne_fach, erfolg=erfolg,
    )


@pages.post("/etiketten/adresse", dependencies=[Depends(require_write)])
def page_labels_save_address(
    request: Request,
    teil: List[str] = Form(default=[]),
    q: str = Form(""),
    kategorie: str = Form(""),
    groesse: str = Form(""),
    breite: str = Form(""),
    hoehe: str = Form(""),
    adresse: str = Form(""),
    ohne_beschreibung: str = Form(""),
    ohne_fach: str = Form(""),
):
    """Merkt die Adresse für die QR-Codes in der config.yaml (server.public_url)."""
    if not is_local(request):
        raise HTTPException(
            403, "Die Adresse lässt sich nur an dem PC speichern, auf dem der Server läuft."
        )
    try:
        url = labelmod.normalize_base_url(adresse)
    except ValueError as e:
        return _labels_page(
            request, teil, q, kategorie, groesse, breite, hoehe, "",
            ohne_beschreibung, ohne_fach, meldung=str(e), status=400,
        )
    set_public_url(url, request.app.state.config_path)
    request.app.state.cfg.setdefault("server", {})["public_url"] = url
    fields = [("teil", name) for name in teil] + [
        (key, value)
        for key, value in (
            ("q", q), ("kategorie", kategorie), ("groesse", groesse), ("breite", breite),
            ("hoehe", hoehe), ("ohne_beschreibung", ohne_beschreibung), ("ohne_fach", ohne_fach),
        )
        if value
    ]
    return RedirectResponse(
        "/etiketten?" + urlencode(fields + [("hinweis", "adresse")]), status_code=303
    )


# ---------------------------------------------------------------------- App


def create_app(
    root: Path,
    cfg: Optional[dict] = None,
    config_path: Path = CONFIG_PATH,
    bind_host: Optional[str] = None,
) -> FastAPI:
    """Baut die Anwendung für einen Lager-Root. Der Index wird beim Start frisch eingelesen.

    `config_path` ist die config.yaml, in die ein geänderter Lager-Ordner geschrieben wird.
    `bind_host` ist die Adresse, an der der Server lauscht (nur für Hinweise auf der Seite).
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Der Arbeiter für Vorschläge läuft, solange der Server läuft. Die Test-Browser
        # (TestClient ohne `with`) lösen das nicht aus; dort ruft der Test run_once auf.
        app.state.worker.start()
        try:
            yield
        finally:
            app.state.worker.stop()

    app = FastAPI(
        title="Lager",
        version=__version__,
        description="Bauteile-Lagersystem: Suche, Bauteile, Datenblätter und andere Dateien.",
        lifespan=lifespan,
    )
    app.state.worker = DraftWorker(app)
    app.state.root = Path(root)
    app.state.cfg = cfg if cfg is not None else load_config(config_path)
    app.state.config_path = Path(config_path)
    app.state.bind_host = bind_host
    app.state.label_suggestion = None  # wird beim ersten Bedarf ermittelt

    @app.exception_handler(db.IndexDbError)
    def index_error(request: Request, error: db.IndexDbError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=500)

    app.mount("/static", RevalidatedStaticFiles(directory=str(HERE / "static")), name="static")
    app.include_router(api, prefix="/api/v1")
    app.include_router(files)
    app.include_router(pages)

    app.state.last_rebuild = indexer.rebuild(app.state.root, app.state.cfg)
    return app
