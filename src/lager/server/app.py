"""Web-Server (Grundgerüst): REST-API, Dateiauslieferung und Handy-Seiten.

Der Server ist nur ein weiterer Client des Kerns: Er nutzt dieselben
Funktionen wie die CLI (indexer, search) und liefert dieselben Daten.
"""
import mimetypes
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, db, indexer
from .. import search as searchmod
from ..config import load_config
from .schemas import Category, Health, IndexStatus, Part, RebuildResult, SearchResult

HERE = Path(__file__).resolve().parent

# Anzeigenamen der Dateiarten. Unbekannte Arten werden mit ihrem Schlüssel gezeigt.
KIND_LABELS = {
    "datasheet": "Datenblatt",
    "cad3d": "3D-Modell",
    "kicad": "KiCad",
    "image": "Bild",
    "other": "Datei",
}
# Diese Arten öffnet der Browser direkt, alles andere wird heruntergeladen.
INLINE_KINDS = {"datasheet", "image"}


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


@api.get("/parts/{part}", response_model=Part, summary="Ein Bauteil mit seinen Dateien")
def api_part(request: Request, part: str) -> dict:
    with open_index(request) as conn:
        found = searchmod.get_part(conn, part)
    if found is None:
        raise HTTPException(404, f"Teil nicht gefunden: {part}")
    return found


@api.get("/categories", response_model=List[Category], summary="Kategorien mit Teil-Anzahl")
def api_categories(request: Request) -> list:
    with open_index(request) as conn:
        return searchmod.list_categories(conn)


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
    return indexer.rebuild(request.app.state.root, request.app.state.cfg)


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
    return FileResponse(
        full,
        media_type=mimetypes.guess_type(full.name)[0] or "application/octet-stream",
        filename=full.name,
        content_disposition_type="inline" if entry["kind"] in INLINE_KINDS else "attachment",
    )


# ------------------------------------------------------------- Handy-Seiten

pages = APIRouter(include_in_schema=False)


def _page_context(request: Request, conn: sqlite3.Connection) -> dict:
    return {
        "kategorien": searchmod.list_categories(conn),
        "index": indexer.status(request.app.state.root),
        "schreibschutz": write_protected(request),
        "version": __version__,
    }


@pages.get("/", response_class=HTMLResponse)
def page_search(request: Request, q: str = "", kategorie: str = ""):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        hits = searchmod.search(conn, q, kategorie or None, 100)
    context.update({"q": q, "kategorie": kategorie, "treffer": hits})
    return templates.TemplateResponse(request, "index.html", context)


@pages.get("/p/{part}", response_class=HTMLResponse)
def page_part(request: Request, part: str):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    context.update({"q": "", "kategorie": "", "teil": found, "gesucht": part})
    return templates.TemplateResponse(
        request, "part.html", context, status_code=200 if found else 404
    )


@pages.post("/index/rebuild", dependencies=[Depends(require_write)])
def page_index_rebuild(request: Request):
    indexer.rebuild(request.app.state.root, request.app.state.cfg)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------- App


def create_app(root: Path, cfg: Optional[dict] = None) -> FastAPI:
    """Baut die Anwendung für einen Lager-Root. Der Index wird beim Start frisch eingelesen."""
    app = FastAPI(
        title="Lager",
        version=__version__,
        description="Bauteile-Lagersystem: Suche, Bauteile, Datenblätter und andere Dateien.",
    )
    app.state.root = Path(root)
    app.state.cfg = cfg if cfg is not None else load_config()

    @app.exception_handler(db.IndexDbError)
    def index_error(request: Request, error: db.IndexDbError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=500)

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.include_router(api, prefix="/api/v1")
    app.include_router(files)
    app.include_router(pages)

    indexer.rebuild(app.state.root, app.state.cfg)
    return app
