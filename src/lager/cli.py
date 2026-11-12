"""Lager-CLI — für Menschen und AI-Agenten.

Agentenvertrag: Jeder Befehl unterstützt --json und liefert dann ein
striktes JSON-Objekt. Fehler gehen mit Statuscode != 0 und deutscher
Meldung auf stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from . import __version__, categories as catmod
from . import parts as partmod
from . import root as rootmod
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
part_app = typer.Typer(help="Bauteile verwalten (part.yaml).")
app.add_typer(root_app, name="root")
app.add_typer(cat_app, name="category")
app.add_typer(part_app, name="part")


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
    target.mkdir(parents=True, exist_ok=True)
    if not (target / rootmod.CATEGORY_MARKER).exists():
        catmod.save(target, [])
    vorlage = target / "_vorlage"
    vorlage.mkdir(exist_ok=True)
    template = vorlage / "part.yaml"
    if not template.exists():
        template.write_text(partmod.HEADER + partmod.empty_doc_yaml(), encoding="utf-8")
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
