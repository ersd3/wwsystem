"""Web-Server: REST-API, Dateiauslieferung und Handy-Seiten.

Der Server ist nur ein weiterer Client des Kerns: Er nutzt dieselben
Funktionen wie die CLI (indexer, search, parts, files) und liefert dieselben Daten.
"""
import mimetypes
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from fastapi import (
    APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, db, indexer
from .. import categories as catmod
from .. import files as filesmod
from .. import parts as partmod
from .. import root as rootmod
from .. import search as searchmod
from ..config import CONFIG_PATH, load_config, set_lager_root
from .schemas import (
    Category, Health, IndexStatus, NewCategory, NewPart, Part, RebuildResult, SearchResult,
    UploadResult,
)

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
# Dateifeld eines HTML-Formulars. Bleibt es leer, schickt der Browser einen
# leeren Text statt einer Datei mit; deshalb ist hier auch str erlaubt.
FormFiles = List[Union[UploadFile, str]]


def _filesize(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("kB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.1f} GB".replace(".", ",")


templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.filters["filesize"] = _filesize
templates.env.globals["kind_label"] = lambda kind: KIND_LABELS.get(kind, kind)


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


def write_protected(request: Request) -> bool:
    return bool(str(request.app.state.cfg.get("write_token") or ""))


def require_write(
    request: Request, x_lager_token: Optional[str] = Header(default=None)
) -> None:
    """Schreibende Aufrufe brauchen den Token, falls in config.yaml einer gesetzt ist."""
    token = str(request.app.state.cfg.get("write_token") or "")
    if token and not secrets.compare_digest((x_lager_token or "").encode(), token.encode()):
        raise HTTPException(403, "Schreibzugriff nur mit gültigem Kopffeld X-Lager-Token.")


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


def _create_part(request: Request, part: str, category: str, data: dict, new_category: str = "") -> Path:
    """Legt ein Bauteil an (auf Wunsch samt neuer Kategorie). Fehler als ValueError."""
    root = request.app.state.root
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
    return partmod.create_part(root, category, part, data)


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
    data = body.model_dump(exclude={"part", "category"})
    try:
        part_dir = _create_part(request, body.part, body.category, data)
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


@api.get("/categories", response_model=List[Category], summary="Kategorien mit Teil-Anzahl")
def api_categories(request: Request) -> list:
    with open_index(request) as conn:
        return searchmod.list_categories(conn)


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
        "lokal": is_local(request),
        "lager_root": str(request.app.state.root),
        "version": __version__,
        "q": "",
        "kategorie": "",
        "meldung": "",
        "erfolg": "",
        "warnungen": [],
    }


def _search_page(
    request: Request,
    q: str = "",
    kategorie: str = "",
    meldung: str = "",
    status: int = 200,
    hinweis: str = "",
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        hits = searchmod.search(conn, q, kategorie or None, 100)
    erfolg, warnungen = _rebuild_notice(request, hinweis)
    context.update(
        {
            "q": q, "kategorie": kategorie, "treffer": hits, "meldung": meldung,
            "erfolg": erfolg, "warnungen": warnungen,
        }
    )
    return templates.TemplateResponse(request, "index.html", context, status_code=status)


def _part_page(request: Request, part: str, meldung: str = "", status: Optional[int] = None):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    context.update({"teil": found, "gesucht": part, "meldung": meldung})
    if status is None:
        status = 200 if found else 404
    return templates.TemplateResponse(request, "part.html", context, status_code=status)


def _new_page(request: Request, form: dict, meldung: str = "", status: int = 200):
    with open_index(request) as conn:
        context = _page_context(request, conn)
    context.update({"form": form, "meldung": meldung})
    return templates.TemplateResponse(request, "new.html", context, status_code=status)


@pages.get("/", response_class=HTMLResponse)
def page_search(request: Request, q: str = "", kategorie: str = "", hinweis: str = ""):
    return _search_page(request, q, kategorie, hinweis=hinweis)


@pages.get("/p/{part}", response_class=HTMLResponse)
def page_part(request: Request, part: str):
    return _part_page(request, part)


@pages.post("/p/{part}/dateien", dependencies=[Depends(require_write)])
def page_add_files(request: Request, part: str, dateien: FormFiles = File(default=[])):
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    added, errors = _save_uploads(request, part_dir, dateien)
    if added:
        _rebuild(request)
    if errors:
        return _part_page(request, part, "Nicht gespeichert: " + "; ".join(errors), 400)
    if not added:
        return _part_page(request, part, "Es wurde keine Datei ausgewählt.", 400)
    return RedirectResponse(f"/p/{quote(part_dir.name)}", status_code=303)


@pages.get("/neu", response_class=HTMLResponse)
def page_new(request: Request, kategorie: str = ""):
    return _new_page(request, {"kategorie": kategorie, "menge": "0"})


@pages.post("/neu", dependencies=[Depends(require_write)])
def page_new_submit(
    request: Request,
    bezeichnung: str = Form(""),
    kategorie: str = Form(""),
    neue_kategorie: str = Form(""),
    name: str = Form(""),
    hersteller: str = Form(""),
    lagerfach: str = Form(""),
    menge: str = Form("0"),
    tags: str = Form(""),
    aliase: str = Form(""),
    notizen: str = Form(""),
    dateien: FormFiles = File(default=[]),
):
    form = {
        "bezeichnung": bezeichnung, "kategorie": kategorie, "neue_kategorie": neue_kategorie,
        "name": name, "hersteller": hersteller, "lagerfach": lagerfach, "menge": menge,
        "tags": tags, "aliase": aliase, "notizen": notizen,
    }
    try:
        try:
            quantity = int(menge.strip() or "0")
        except ValueError:
            raise ValueError("Die Menge muss eine ganze Zahl sein.")
        if not bezeichnung.strip():
            raise ValueError("Bitte eine Bezeichnung eintragen.")
        part_dir = _create_part(
            request,
            bezeichnung,
            kategorie,
            {
                "name": name.strip(), "manufacturer": hersteller.strip(),
                "location": lagerfach.strip(), "quantity": quantity,
                "tags": _split_list(tags), "aliases": _split_list(aliase),
                "notes": notizen.strip(),
            },
            neue_kategorie,
        )
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
    return RedirectResponse(f"/p/{quote(part_dir.name)}", status_code=303)


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


# ---------------------------------------------------------------------- App


def create_app(
    root: Path, cfg: Optional[dict] = None, config_path: Path = CONFIG_PATH
) -> FastAPI:
    """Baut die Anwendung für einen Lager-Root. Der Index wird beim Start frisch eingelesen.

    `config_path` ist die config.yaml, in die ein geänderter Lager-Ordner geschrieben wird.
    """
    app = FastAPI(
        title="Lager",
        version=__version__,
        description="Bauteile-Lagersystem: Suche, Bauteile, Datenblätter und andere Dateien.",
    )
    app.state.root = Path(root)
    app.state.cfg = cfg if cfg is not None else load_config(config_path)
    app.state.config_path = Path(config_path)

    @app.exception_handler(db.IndexDbError)
    def index_error(request: Request, error: db.IndexDbError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=500)

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.include_router(api, prefix="/api/v1")
    app.include_router(files)
    app.include_router(pages)

    app.state.last_rebuild = indexer.rebuild(app.state.root, app.state.cfg)
    return app
