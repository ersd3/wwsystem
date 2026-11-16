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
from urllib.parse import quote, urlencode

from fastapi import (
    APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, db, indexer
from .. import categories as catmod
from .. import dialogs as dialogmod
from .. import files as filesmod
from .. import labels as labelmod
from .. import parts as partmod
from .. import root as rootmod
from .. import search as searchmod
from .. import trash as trashmod
from ..config import CONFIG_PATH, load_config, set_lager_root, set_public_url
from .schemas import (
    Category, FileDeleteResult, Health, IndexStatus, NewCategory, NewPart, Part, PartChanges,
    PartDeleteResult, RebuildResult, SearchResult, UploadResult,
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
# Cookie, das der Browser nach dem Anmelden mit dem write_token bekommt (30 Tage).
TOKEN_COOKIE = "lager_token"
TOKEN_COOKIE_MAX_AGE = 30 * 24 * 3600
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
def _mm(value: float) -> str:
    """Maß für CSS: zwei Nachkommastellen, Punkt als Dezimalzeichen, ohne Endnullen."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


templates.env.filters["filesize"] = _filesize
templates.env.filters["mm"] = _mm
templates.env.filters["mm_de"] = labelmod.format_mm
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
    teil: str = "",
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        hits = searchmod.search(conn, q, kategorie or None, 100)
        gone = bool(teil) and searchmod.get_part(conn, teil) is None
    erfolg, warnungen = _rebuild_notice(request, hinweis)
    if hinweis == "geloescht" and gone:
        erfolg = (
            f"{teil} ist gelöscht. Der Ordner liegt im Papierkorb des Lagers "
            f"(Ordner {trashmod.TRASH_DIR})."
        )
    context.update(
        {
            "q": q, "kategorie": kategorie, "treffer": hits, "meldung": meldung,
            "erfolg": erfolg, "warnungen": warnungen,
        }
    )
    return templates.TemplateResponse(request, "index.html", context, status_code=status)


def _part_notice(found: dict, hochgeladen: Sequence[str], geloescht: str, frueher: str) -> str:
    """Erfolgsmeldung der Bauteilseite. Gemeldet wird nur, was am Bauteil auch stimmt."""
    notes: List[str] = []
    paths = {f["path"] for f in found["files"]}
    uploaded = [name for name in hochgeladen if name in paths]
    if uploaded:
        notes.append(f"{_count(len(uploaded), 'Datei', 'Dateien')} hochgeladen: {', '.join(uploaded)}.")
    if geloescht and geloescht not in paths:
        notes.append(
            f"{geloescht} ist gelöscht. Die Datei liegt im Papierkorb des Lagers "
            f"(Ordner {trashmod.TRASH_DIR})."
        )
    if frueher and frueher.lower() in (alias.lower() for alias in found["aliases"]):
        notes.append(f"„{frueher}“ heißt jetzt „{found['part']}“.")
    return " ".join(notes)


def _part_page(
    request: Request,
    part: str,
    meldung: str = "",
    status: Optional[int] = None,
    hochgeladen: Sequence[str] = (),
    geloescht: str = "",
    frueher: str = "",
):
    with open_index(request) as conn:
        context = _page_context(request, conn)
        found = searchmod.get_part(conn, part)
    qr = None
    if found:
        base, _source = label_base_url(request)
        if base:
            qr = labelmod.make_qr(labelmod.part_url(base, found["part"]))
        context["erfolg"] = _part_notice(found, hochgeladen, geloescht, frueher)
    context.update({"teil": found, "gesucht": part, "meldung": meldung, "qr": qr})
    if status is None:
        status = 200 if found else 404
    return templates.TemplateResponse(request, "part.html", context, status_code=status)


def _new_page(request: Request, form: dict, meldung: str = "", status: int = 200):
    with open_index(request) as conn:
        context = _page_context(request, conn)
    context.update(
        {
            "form": form,
            "meldung": meldung,
            "unterkategorien": _subcategory_options(request, context["kategorien"]),
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
        request, part, hochgeladen=hochgeladen, geloescht=geloescht, frueher=frueher
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
            "bezeichnung": found["part"], "kategorie": found["category"],
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
    bezeichnung: str = Form(""),
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
    """Speichert die Angaben; neue Bezeichnung, Kategorie oder Unterkategorie verschieben den Ordner."""
    form = {
        "bezeichnung": bezeichnung, "kategorie": kategorie, "unterkategorie": unterkategorie,
        "neue_unterkategorie": neue_unterkategorie,
        "name": name, "hersteller": hersteller, "lagerfach": lagerfach, "menge": menge,
        "einheit": einheit, "tags": tags, "aliase": aliase, "notizen": notizen,
    }
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    root = request.app.state.root
    old_category, old_sub = partmod.location_of(root, part_dir)
    # Leere Felder für Bezeichnung und Kategorie heißen: bleibt, wie es ist.
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
    try:
        moved = partmod.move_part(
            root, part_dir.name, bezeichnung.strip() or None, category, subcategory
        )
    except ValueError as e:
        _rebuild(request)
        return _edit_page(
            request, part, form, f"Die übrigen Angaben sind gespeichert. Aber: {e}", 400
        )
    _rebuild(request)
    target = f"/p/{quote(moved.name)}"
    if moved.name.lower() != part_dir.name.lower():
        target += "?" + urlencode({"frueher": part_dir.name})
    return RedirectResponse(target, status_code=303)


@pages.post("/p/{part}/loeschen", dependencies=[Depends(require_write)])
def page_delete_part(request: Request, part: str, sicher: str = Form("")):
    """Löscht ein Bauteil: Sein Ordner wandert in den Papierkorb des Lagers.

    Das Häkchen „Ja, löschen“ im Formular schützt vor einem versehentlichen Tippen.
    """
    part_dir = _part_dir(request, part)
    if part_dir is None:
        return _part_page(request, part)
    if not sicher:
        return _edit_page(request, part, None, "Zum Löschen bitte das Häkchen setzen.", 400)
    try:
        partmod.delete_part(request.app.state.root, part_dir.name)
    except ValueError as e:
        return _edit_page(request, part, None, str(e), 400)
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
def page_new(request: Request, kategorie: str = ""):
    return _new_page(request, {"kategorie": kategorie, "menge": "0"})


@pages.post("/neu", dependencies=[Depends(require_write)])
def page_new_submit(
    request: Request,
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
    dateien: FormFiles = File(default=[]),
):
    form = {
        "bezeichnung": bezeichnung, "kategorie": kategorie, "neue_kategorie": neue_kategorie,
        "unterkategorie": unterkategorie, "neue_unterkategorie": neue_unterkategorie,
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
        # Bei einer neu eingetippten Kategorie kann die Auswahl darunter nicht passen.
        new_cat = bool(neue_kategorie.strip())
        effective = catmod.normalize_id(neue_kategorie) if new_cat else kategorie
        subcategory = _chosen_subcategory(
            effective, unterkategorie, neue_unterkategorie, lenient=new_cat
        )
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
            subcategory,
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
    app = FastAPI(
        title="Lager",
        version=__version__,
        description="Bauteile-Lagersystem: Suche, Bauteile, Datenblätter und andere Dateien.",
    )
    app.state.root = Path(root)
    app.state.cfg = cfg if cfg is not None else load_config(config_path)
    app.state.config_path = Path(config_path)
    app.state.bind_host = bind_host
    app.state.label_suggestion = None  # wird beim ersten Bedarf ermittelt

    @app.exception_handler(db.IndexDbError)
    def index_error(request: Request, error: db.IndexDbError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=500)

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.include_router(api, prefix="/api/v1")
    app.include_router(files)
    app.include_router(pages)

    app.state.last_rebuild = indexer.rebuild(app.state.root, app.state.cfg)
    return app
