"""Lager-CLI — für Menschen und AI-Agenten.

Agentenvertrag: Jeder Befehl unterstützt --json und liefert dann ein
striktes JSON-Objekt. Fehler gehen mit Statuscode != 0 und deutscher
Meldung auf stderr.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import typer

from . import __version__, categories as catmod
from . import db as dbmod
from . import files as filesmod
from . import indexer
from . import parts as partmod
from . import root as rootmod
from . import search as searchmod
from .config import (
    CONFIG_PATH,
    load_config,
    resolve_lager_root,
    save_config,
    set_lager_root,
)

app = typer.Typer(
    name="lager",
    help="Lager-CLI — Bauteile verwalten. Alle Befehle unterstützen --json.",
    no_args_is_help=True,
)
root_app = typer.Typer(help="Lager-Root verwalten (bewegbar).")
cat_app = typer.Typer(help="Kategorien verwalten (anlegbar, nichts hardcodiert).")
part_app = typer.Typer(help="Bauteile verwalten (part.yaml) und suchen.")
index_app = typer.Typer(help="Such-Index (SQLite) verwalten. Er wird aus den Ordnern aufgebaut.")
app.add_typer(root_app, name="root")
app.add_typer(cat_app, name="category")
app.add_typer(part_app, name="part")
app.add_typer(index_app, name="index")


def force_utf8_output() -> None:
    """Stellt stdout und stderr fest auf UTF-8.

    Bei umgeleiteter Ausgabe nimmt Python unter Windows sonst die lokale
    Codepage (z. B. Windows-1252). Umlaute kämen dann bei anderen Programmen
    kaputt an, und JSON muss laut Standard UTF-8 sein.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> None:
    """Einstiegspunkt für `lager` und `python -m lager`."""
    force_utf8_output()
    app()


def _print(data: dict, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        for k, v in data.items():
            typer.echo(f"{k}: {v}")


def _require_root() -> Path:
    """Aktiven Root liefern (config, sonst Auto-Erkennung), sonst Fehler."""
    cfg = load_config()
    explicit = resolve_lager_root(cfg)
    if explicit is not None and rootmod.check_root(explicit).valid:
        return explicit
    found, _ = rootmod.detect(cfg)
    if found is not None:
        return found.path
    typer.echo(
        "Fehler: Kein gültiger Lager-Root gefunden. "
        "Nutze `lager init <pfad>` oder `lager root set <pfad>`.",
        err=True,
    )
    raise typer.Exit(1)


def _fail(message: str) -> None:
    typer.echo(f"Fehler: {message}", err=True)
    raise typer.Exit(1)


def _refresh_index(root: Path) -> None:
    """Hält einen vorhandenen Index nach einer Änderung über die CLI aktuell.

    Die Änderung an den Ordnern ist zu diesem Zeitpunkt schon erfolgt. Ein
    Fehler hier bricht den Befehl deshalb nicht ab, sondern gibt nur eine Warnung.
    """
    if not dbmod.db_path(root).exists():
        return
    try:
        indexer.rebuild(root, load_config())
    except (dbmod.IndexDbError, sqlite3.Error, OSError) as e:
        typer.echo(f"Warnung: Index nicht aktualisiert ({e}). Nachholen: lager index rebuild", err=True)


@app.command()
def version() -> None:
    """Zeigt die Version."""
    typer.echo(f"lager {__version__}")


@app.command()
def init(
    pfad: Path = typer.Argument(..., help="Zielordner für das Lager."),
    force: bool = typer.Option(
        False, "--force", help="Nicht leeren Zielordner ohne Prüfung übernehmen."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Legt die Lager-Struktur an und setzt lager_root in config.yaml."""
    target = Path(pfad).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not force:
        typer.echo(
            f"Zielordner existiert und ist nicht leer: {target} (mit --force übernehmen)",
            err=True,
        )
        raise typer.Exit(1)
    rootmod.create_structure(target)
    set_lager_root(str(target))
    check = rootmod.check_root(target)
    _print(
        {
            "aktion": "init",
            "root": str(target),
            "config": str(CONFIG_PATH),
            "gueltig": check.valid,
            "grund": check.reason,
        },
        as_json,
    )


@app.command()
def status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Zeigt Konfiguration, aktiven Root, Erkennung und Zählungen."""
    cfg = load_config()
    explicit = resolve_lager_root(cfg)
    found, checks = rootmod.detect(cfg)
    quelle = (
        "config"
        if found is not None and explicit is not None and found.path == explicit
        else "auto" if found is not None else "keine"
    )
    data: dict = {
        "config": str(CONFIG_PATH),
        "lager_root_config": str(explicit) if explicit else "",
        "lager_root_aktiv": str(found.path) if found else "",
        "quelle": quelle,
        "kandidaten": [
            {
                "pfad": str(c.path),
                "gueltig": c.valid,
                "grund": c.reason,
                "teile": c.parts,
                "kategorien": c.categories,
            }
            for c in checks
        ],
    }
    if found is not None:
        data["kategorien"] = len(catmod.load(found.path))
        data["teile"] = found.parts
    _print(data, as_json)
    if found is None and not as_json:
        typer.echo("Tipp: lager init <pfad>  oder  lager root set <pfad>")


# ---------------------------------------------------------------- root


@root_app.command("set")
def root_set(
    pfad: Path = typer.Argument(..., help="Neuer Lager-Root."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Setzt lager_root in config.yaml (relativ, wenn im Projektordner)."""
    target = Path(pfad).expanduser().resolve()
    check = rootmod.check_root(target)
    set_lager_root(str(target))
    _print(
        {"lager_root": str(target), "gueltig": check.valid, "grund": check.reason},
        as_json,
    )
    if not check.valid and not as_json:
        typer.echo("Warnung: Struktur nicht valid. Tipp: lager init <pfad>")


@root_app.command("unset")
def root_unset(as_json: bool = typer.Option(False, "--json")) -> None:
    """Entfernt lager_root aus config.yaml (Auto-Erkennung wird aktiv)."""
    cfg = load_config()
    cfg["lager_root"] = ""
    save_config(cfg)
    _print({"lager_root": ""}, as_json)


@root_app.command("detect")
def root_detect(as_json: bool = typer.Option(False, "--json")) -> None:
    """Zeigt alle Kandidaten und ob deren Struktur passt (Auto-Erkennung)."""
    found, checks = rootmod.detect()
    _print(
        {
            "erkannt": str(found.path) if found else "",
            "kandidaten": [
                {
                    "pfad": str(c.path),
                    "gueltig": c.valid,
                    "grund": c.reason,
                    "teile": c.parts,
                    "kategorien": c.categories,
                }
                for c in checks
            ],
        },
        as_json,
    )


# ------------------------------------------------------------- category


@cat_app.command("add")
def cat_add(
    kategorie: str = typer.Argument(
        ..., help="Kategorie-ID (wird normalisiert), z. B. mosfets"
    ),
    label: str = typer.Option("", "--label", help="Anzeigename, z. B. 'MOSFETs'"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Legt eine Kategorie an (Ordner + Eintrag in categories.yaml)."""
    root = _require_root()
    try:
        entry = catmod.add(root, kategorie, label)
    except ValueError as e:
        typer.echo(f"Fehler: {e}", err=True)
        raise typer.Exit(1)
    _refresh_index(root)
    _print({"kategorie": entry, "pfad": str(root / entry["id"])}, as_json)


@cat_app.command("list")
def cat_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """Listet Kategorien mit Teil-Anzahl."""
    root = _require_root()
    cats = []
    for c in catmod.load(root):
        d = root / c["id"]
        cats.append(
            {
                "id": c["id"],
                "label": c.get("label", c["id"]),
                "teile": rootmod.count_parts(d) if d.is_dir() else 0,
            }
        )
    _print({"kategorien": cats}, as_json)


@cat_app.command("remove")
def cat_remove(
    kategorie: str = typer.Argument(..., help="Kategorie-ID"),
    force: bool = typer.Option(
        False, "--force", help="Ordner auch dann löschen, wenn er nicht leer ist."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Entfernt eine Kategorie (nur wenn der Ordner leer ist, sonst --force)."""
    root = _require_root()
    try:
        catmod.remove(root, kategorie, force=force)
    except (KeyError, ValueError) as e:
        typer.echo(f"Fehler: {e.args[0] if e.args else e}", err=True)
        raise typer.Exit(1)
    _refresh_index(root)
    _print({"entfernt": kategorie}, as_json)


# ----------------------------------------------------------------- part


@part_app.command("new")
def part_new(
    bezeichnung: str = typer.Argument(..., help="Bauteil-Bezeichnung, z. B. IRLZ44N"),
    category: str = typer.Option(..., "--category", "-c", help="Kategorie-ID"),
    name: str = typer.Option("", "--name", "-n", help="Beschreibung"),
    manufacturer: str = typer.Option("", "--manufacturer", "-m", help="Hersteller"),
    quantity: int = typer.Option(0, "--quantity", "-q", help="Anfangsmenge"),
    location: str = typer.Option("", "--location", "-l", help="Lagerfach"),
    tags: str = typer.Option("", "--tags", help="Kommagetrennt, z. B. 'mosfet,55v'"),
    aliases: str = typer.Option("", "--aliases", help="Kommagetrennt"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Legt ein neues Bauteil an (Ordner + part.yaml)."""
    root = _require_root()
    data = {
        "name": name,
        "manufacturer": manufacturer,
        "quantity": quantity,
        "location": location,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "aliases": [a.strip() for a in aliases.split(",") if a.strip()],
    }
    try:
        pdir = partmod.create_part(root, category, bezeichnung, data)
    except ValueError as e:
        typer.echo(f"Fehler: {e}", err=True)
        raise typer.Exit(1)
    _refresh_index(root)
    _print({"teil": str(pdir)}, as_json)


@part_app.command("show")
def part_show(
    bezeichnung: str = typer.Argument(
        ..., help="Bauteil-Bezeichnung (wird in allen Kategorien gesucht)."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Zeigt part.yaml und vorhandene Dateien eines Bauteils."""
    root = _require_root()
    found = partmod.find_part(root, bezeichnung)
    if found is None:
        typer.echo(f"Fehler: Teil nicht gefunden: {bezeichnung}", err=True)
        raise typer.Exit(1)
    pdir, data = found
    files = [
        {
            "pfad": f.relative_to(pdir).as_posix(),
            "typ": f.suffix.lower().lstrip("."),
        }
        for f in sorted(pdir.rglob("*"))
        if f.is_file() and f.name != "part.yaml"
    ]
    _print({"ordner": str(pdir), "daten": data, "dateien": files}, as_json)


@part_app.command("attach")
def part_attach(
    bezeichnung: str = typer.Argument(..., help="Bauteil-Bezeichnung, z. B. IRLZ44N"),
    dateien: List[Path] = typer.Argument(
        ..., help="Eine oder mehrere Dateien (Datenblatt, STEP, KiCad, Bild …)"
    ),
    move: bool = typer.Option(
        False, "--move", help="Dateien verschieben statt kopieren (Original wird gelöscht)."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Nimmt Dateien in den Ordner eines Bauteils auf (PDF direkt, 3D/KiCad/Bilder in Unterordner)."""
    root = _require_root()
    pdir = partmod.find_part_dir(root, bezeichnung)
    if pdir is None:
        _fail(f"Teil nicht gefunden: {bezeichnung}")
    missing = [str(f) for f in dateien if not f.is_file()]
    if missing:
        _fail(f"Datei nicht gefunden: {', '.join(missing)}")
    cfg = load_config()
    added: list[str] = []
    try:
        for source in dateien:
            target = filesmod.add_file_from_path(pdir, source, cfg, move=move)
            added.append(target.relative_to(pdir).as_posix())
    except (ValueError, OSError) as e:
        if added:
            _refresh_index(root)
        _fail(f"{e} (bereits aufgenommen: {', '.join(added) or 'nichts'})")
    _refresh_index(root)
    _print({"teil": pdir.name, "ordner": str(pdir), "hinzugefuegt": added}, as_json)


def _open_with_default_app(path: Path) -> None:
    """Öffnet eine Datei oder einen Ordner mit dem Standardprogramm des Systems."""
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


@part_app.command("open")
def part_open(
    bezeichnung: str = typer.Argument(..., help="Bauteil-Bezeichnung, z. B. IRLZ44N"),
    datei: str = typer.Option(
        "", "--file", "-f", help="Bestimmte Datei im Bauteil-Ordner, z. B. 3d/TO-220.step"
    ),
    folder: bool = typer.Option(False, "--folder", help="Den Bauteil-Ordner statt einer Datei öffnen."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Öffnet das Datenblatt eines Bauteils (oder eine andere Datei, oder den Ordner)."""
    root = _require_root()
    pdir = partmod.find_part_dir(root, bezeichnung)
    if pdir is None:
        _fail(f"Teil nicht gefunden: {bezeichnung}")
    if folder:
        target = pdir
    elif datei:
        target = (pdir / datei).resolve()
        if pdir.resolve() not in target.parents or not target.is_file():
            _fail(f"Datei nicht im Bauteil-Ordner gefunden: {datei}")
    else:
        found = indexer.scan_files(pdir, indexer.kind_by_ext_map(load_config()))
        sheets = [f for f in found if f.kind == indexer.DATASHEET_KIND]
        if not sheets:
            _fail(f"Kein Datenblatt im Ordner von {pdir.name}. Hinzufügen: lager part attach {pdir.name} <datei>")
        target = pdir / sheets[0].rel_path
    try:
        _open_with_default_app(target)
    except OSError as e:
        _fail(f"Konnte nicht geöffnet werden: {target} ({e})")
    _print({"teil": pdir.name, "geoeffnet": str(target)}, as_json)


@part_app.command("edit")
def part_edit(
    bezeichnung: str = typer.Argument(..., help="Bauteil-Bezeichnung, z. B. IRLZ44N"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Beschreibung"),
    manufacturer: Optional[str] = typer.Option(None, "--manufacturer", "-m", help="Hersteller"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Menge"),
    unit: Optional[str] = typer.Option(None, "--unit", help="Mengeneinheit, z. B. Stk"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Lagerfach"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Kommagetrennt; ersetzt die bisherigen"),
    aliases: Optional[str] = typer.Option(None, "--aliases", help="Kommagetrennt; ersetzt die bisherigen"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Notizen"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Ändert Angaben eines Bauteils. Nur die genannten Felder werden gesetzt ("" leert ein Feld)."""
    root = _require_root()
    changes: dict = {}
    for key, value in (
        ("name", name), ("manufacturer", manufacturer), ("quantity", quantity),
        ("unit", unit), ("location", location), ("notes", notes),
    ):
        if value is not None:
            changes[key] = value
    if tags is not None:
        changes["tags"] = [t.strip() for t in tags.split(",")]
    if aliases is not None:
        changes["aliases"] = [a.strip() for a in aliases.split(",")]
    if not changes:
        _fail("Nichts zu ändern. Mindestens eine Option angeben, z. B. --name oder --location.")
    try:
        pdir = partmod.update_part(root, bezeichnung, changes)
    except ValueError as e:
        _fail(str(e))
    _refresh_index(root)
    _print({"teil": pdir.name, "ordner": str(pdir), "geaendert": sorted(changes)}, as_json)


@part_app.command("search")
def part_search(
    begriff: str = typer.Argument(
        "", help="Suchbegriffe (alle müssen vorkommen). Leer = alle Bauteile."
    ),
    category: str = typer.Option("", "--category", "-c", help="Nur in dieser Kategorie-ID"),
    limit: int = typer.Option(50, "--limit", help="Höchstzahl der Treffer"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Sucht Bauteile im Index (Bezeichnung, Name, Hersteller, Aliase, Tags, Kategorie, Dateinamen)."""
    root = _require_root()
    try:
        indexer.ensure_index(root, load_config())
        conn = dbmod.connect(root, create=False)
    except dbmod.IndexDbError as e:
        _fail(str(e))
    try:
        hits = searchmod.search(conn, begriff, category or None, limit)
    finally:
        conn.close()

    if as_json:
        _print(
            {"suche": begriff, "kategorie": category, "anzahl": len(hits), "treffer": hits},
            True,
        )
        return
    if not hits:
        typer.echo(f"Keine Treffer für: {begriff}" if begriff else "Keine Bauteile im Index.")
        return
    for hit in hits:
        typer.echo(f"{hit['part']}  ·  {hit['category_label']}  ·  {hit['name']}")
        sheets = [f["path"] for f in hit["files"] if f["kind"] == "datasheet"]
        if sheets:
            typer.echo(f"    Datenblatt: {', '.join(sheets)}")
        typer.echo(f"    Ordner: {root / hit['path']}")


# ---------------------------------------------------------------- index


@index_app.command("rebuild")
def index_rebuild(as_json: bool = typer.Option(False, "--json")) -> None:
    """Baut den Such-Index aus der Ordnerstruktur neu auf (beliebig oft ausführbar)."""
    root = _require_root()
    try:
        result = indexer.rebuild(root, load_config())
    except dbmod.IndexDbError as e:
        _fail(str(e))
    if as_json:
        _print(result, True)
        return
    typer.echo(
        f"Index aufgebaut: {result['teile']} Bauteile, {result['kategorien']} Kategorien, "
        f"{result['dateien']} Dateien ({result['dauer_ms']} ms)"
    )
    typer.echo(f"Datei: {result['db']}")
    for warning in result["warnungen"]:
        typer.echo(f"Warnung: {warning['pfad']}: {warning['grund']}")


@index_app.command("status")
def index_status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Zeigt, ob es einen Index gibt, wann er aufgebaut wurde und was er enthält."""
    root = _require_root()
    try:
        result = indexer.status(root)
    except dbmod.IndexDbError as e:
        _fail(str(e))
    _print(result, as_json)
    if not result["vorhanden"] and not as_json:
        typer.echo("Tipp: lager index rebuild")


# ---------------------------------------------------------------- serve


@app.command()
def serve(
    host: str = typer.Option("", "--host", help="Adresse (Standard: server.host aus config.yaml)"),
    port: int = typer.Option(0, "--port", help="Port (Standard: server.port aus config.yaml)"),
) -> None:
    """Startet den Web-Server (REST-API und Handy-Seiten)."""
    root = _require_root()
    cfg = load_config()
    try:
        import uvicorn

        from .server.app import create_app
    except ImportError as e:
        _fail(f"Server-Pakete fehlen ({e.name}). Installieren: pip install -r requirements.txt")
    bind_host = host or str(cfg["server"]["host"])
    bind_port = port or int(cfg["server"]["port"])
    typer.echo(f"Lager-Server: http://{bind_host}:{bind_port}  (Beenden mit Strg+C)")
    uvicorn.run(create_app(root, cfg), host=bind_host, port=bind_port, log_level="info")
