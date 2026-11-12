# HANDOVER — Bauteile-Lagersystem „Lager“

**To:** Claude (Nachfolger-Agent)  
**From:** LM Studio Bionic Agent, Session 2026-11-11  
**Fortgeführt von:** Claude (Claude Code), seit 2026-11-12  
**Status (2026-11-12):** Phase 0.1 und 0.2 sind umgesetzt und getestet (siehe §5). Zusätzlich steht ein lauffähiges Grundgerüst für Phase 1 (Suche in der CLI) und Phase 2 (Server mit REST-API und Handy-Seiten). Was je Phase noch offen ist, steht in §7.

---

## 1. Kurzfassung

Ein System zur Pflege einer großen Sammlung elektronischer Bauteile (Widerstände, Transistoren/MOSFETs, ICs…) mit Suche, Datenblatt/CAD/KiCad-Zugriff, Mengennachhaltung und **offener, browsbarer Ordnerstruktur** (Windows jetzt, Linux später).  
Server + Client (Web), CLI, später Smartphone-QR.  
Alles läuft über einen gemeinsamen Kern (REST/OpenAPI), bedienbar per CLI und AI-Agent (Agentenvertrag: `--json`, später MCP).

**Prioritäten (Lukas, 2026-11-12):** Private Nutzung. Datenblätter schnell finden und einlesen ist der Hauptzweck und wichtiger als das Eintragen von Mengen. Direkt nach der Grundstruktur kommt die Nutzung am Handy, gebaut als Web-Oberfläche des Servers (D8).

---

## 2. Nutzer & Rahmen

- Name: Lukas
- Sprache: **Deutsch** für alle Kommunikation, UI, Docs, CLI-Meldungen. Code-Identifier auf Englisch.
- Arbeitsordner: `N:\lukas\Downloads\Wirtschaftssystem`
- Jetzt Windows 11, später Linux. `pathlib` nutzen, keine Windows-Only-APIs.
- Der Entwicklungsrechner ist nicht schwach (Ryzen 9, 31 GB RAM). Die frühere Notiz „Hardware schwach“ bezog sich nur auf die Laufzeit des lokalen LM-Studio-Agenten. Weiterhin: kein Docker, kleines venv.
- Lokale Agenten (LM Studio) bearbeiten künftig voraussichtlich nicht mehr den Code, sondern pflegen nur die Daten über CLI/MCP.
- Wünsche: Standards (SQLite, REST/OpenAPI, YAML, QR=URL), AI-Agent kann System bedienen **und** DB pflegen, bewegbarer Filesystem-Root.

---

## 3. Wichtige Entscheidungen

### Vom Nutzer explizit bestätigt / angefordert
- Bewegbarer Filesystem-Root: Pfad in einer Stelle konfigurierbar (`lager_root` in `config.yaml`), bei passender Struktur automatisch erkennen/validieren.
- Kategorien anlegbar, nicht von Anfang an festgezurrt – auch vom Agenten anlegbar.
- `part.yaml` nach Agent-Vorschlag gestalten.
- **D7 – Prioritäten:** private Nutzung; Datenblätter finden und einlesen vor Mengen; Roadmap entsprechend neu geordnet (§7).
- **D8 – Mobile App = Web-Oberfläche:** zuerst fürs Handy gestaltet, keine eigene Android-/iOS-App. Begründung und HTTPS-Einschränkung in `KONZEPT.md` §7.
- C++ prüfen. → Am 2026-11-12 ein zweites Mal geprüft; Lukas hat **Python bestätigt** (D1).
- **D6 – Sprachneutrale Datenhaltung:** Datenbanken und Dateien „allgemein“ anlegen, nichts Python-Spezifisches. Regeln stehen in `KONZEPT.md` §8 (Schema als reines SQL, nur Standardtypen, kein ORM, kein `pickle`).

### Entscheidungen des Agents (nicht final vom Nutzer bestätigt, aber dokumentiert)
**D1 (inzwischen bestätigt, s. o.):** Python 3.11+ (Typer, PyYAML; später FastAPI/Uvicorn, Jinja2+HTMX). C++ geprüft und verworfen: Mehraufwand, schwächere AI-Wartbarkeit, Performance irrelevant.
**D2:** Root-Auflösungsreihenfolge – konfiguriert `lager_root` zuerst (relativ = relativ zum Projektordner), sonst Kandidaten `<project>/lager/`, dann `~/lager/`. Valid wenn `categories.yaml` existiert **oder** Struktur `kategorie/<...>/part.yaml` gefunden.
**D3:** Kategorien leben in `<root>/categories.yaml` (`id` = normalisierter Ordnername `a-z0-9-`, `label` = Anzeigename mit Umlauten).
**D4:** `part.yaml` Schema v1: `part`, `name`, `manufacturer`, `aliases[]`, `quantity`, `unit`, `location`, `tags[]`, `notes`. **Kategorie kommt aus dem Pfad (Ebene 1), nie in part.yaml speichern.**
**D5:** Ordner mit Präfix `_` oder `.` vom Scanner ignoriert (`_vorlage/` = Template).

---

## 4. Vertrags-Spezifikation

### Ordnerstruktur
```
<lager_root>/
├── categories.yaml
├── _vorlage/part.yaml          # ignoriert
└── <kategorie>/[<subcat>/]<PARTID>/
    ├── part.yaml
    ├── *.pdf                   # Datenblätter
    ├── 3d/                     # step/stp/wrl…
    ├── kicad/                  # kicad_mod/kicad_sym…
    └── images/
```

- Kategorie-ID: `a-z0-9-` (Umlaute transliteriert)
- Bauteil-ID: `A-Z0-9\-_.+`, groß, z.B. `IRLZ44N`
- Scanner ignoriert Ordner mit `_`/`.`-Präfix.

### config.yaml
```yaml
lager_root: "lager"   # leer = Auto-Erkennung, relativ oder absolut
server:
  host: "127.0.0.1"
  port: 8080
  public_url: ""
write_token: ""
```

### categories.yaml
```yaml
categories:
- id: mosfets
  label: "MOSFETs"
```

### part.yaml (v1)
```yaml
part: IRLZ44N
name: "MOSFET N-Kanal 55 V / 47 A, TO-220"
manufacturer: Infineon
aliases: [IRLZ44NTR]
quantity: 24
unit: Stk
location: "A-03-2"
tags: [n-kanal, 55v, to-220]
notes: ""
```

### CLI-Agentenvertrag
Jeder Befehl unterstützt `--json`. Fehler → Exit ≠0 + deutsche Meldung auf stderr.  
Wichtig: `_require_root()` → config-Root falls gültig, sonst Auto-Erkennung, sonst Fehler.

### Index, Suche, Server (seit 2026-11-12)
Einzelheiten in `KONZEPT.md` §6a (Index) und §7 (Server). Kurzfassung:

- **Index:** `<lager_root>/.lager/parts.db`, Schema in `src/lager/schema.sql` (reines SQL, D6). Tabellen `categories`, `parts`, `part_aliases`, `part_tags`, `files`, `meta`. Abgeleitet, nicht in Git (`.gitignore`).
- **Befehle:** `lager index rebuild`, `lager index status`, `lager part search [begriff] [--category ID] [--limit N]`, `lager serve [--host H] [--port P]`.
- **Aktualität:** Der Index wird neu aufgebaut bei `index rebuild`, nach `part new` und `category add/remove` (nur wenn schon ein Index existiert) und bei jedem Serverstart. `part search` baut ihn auf, falls er fehlt.
- **JSON (D10):** CLI und REST-API geben dieselben dicts aus (`search.py`, `indexer.py`). Datensätze mit englischen Feldnamen (`part`, `name`, `category`, `path`, `files[path, kind, ext, size, mtime]`), Rahmenfelder deutsch (`suche`, `anzahl`, `treffer`, `teile`, `dateien`, `warnungen`).
- **Server:** FastAPI in `src/lager/server/app.py` (`create_app(root, cfg)`), Vorlagen in `server/templates`, Gestaltung in `server/static/style.css`. Routen: `/`, `/p/<teil>`, `/files/<pfad>`, `/api/v1/{health,parts,parts/<teil>,categories,index,index/rebuild}`, `/docs`.
- **Sicherheit:** `/files/...` liefert nur Dateien aus, die im Index stehen. Schreibende Aufrufe verlangen `X-Lager-Token`, falls `write_token` gesetzt ist.
- **SQLite im Server:** Jede Anfrage öffnet ihre Verbindung selbst (`open_index`), weil eine SQLite-Verbindung nur in dem Thread benutzt werden darf, der sie geöffnet hat.

---

## 5. Aktueller Stand 2026-11-12

### Vorhandene Dateien (auf Disk)
```
pyproject.toml
requirements.txt
.gitignore
config.yaml
KONZEPT.md
README.md
src/lager/__init__.py
src/lager/__main__.py
src/lager/config.py
src/lager/root.py
src/lager/categories.py
src/lager/parts.py
src/lager/cli.py
src/lager/schema.sql            # Index-Schema, reines SQL
src/lager/db.py                 # Index öffnen, Schema anlegen, Version prüfen
src/lager/indexer.py            # Ordner einlesen, Index aufbauen, Status
src/lager/search.py             # Suche und Abfragen auf dem Index
src/lager/server/__init__.py
src/lager/server/app.py         # FastAPI: REST-API, Dateien, Handy-Seiten
src/lager/server/schemas.py     # Antwort-Formate der API
src/lager/server/templates/     # base.html, index.html, part.html
src/lager/server/static/style.css
tests/conftest.py               # Test-Lager mit Bauteilen und Dateien
tests/test_core.py
tests/test_cli.py
tests/test_index.py
tests/test_server.py
lager/categories.yaml
lager/_vorlage/part.yaml
lager/mosfets/IRLZ44N/part.yaml
lager/widerstaende/223-0.1W/part.yaml
```

### Verifizierung (erfolgreich)

**2026-11-11, Sandbox Pyodide / Python 3.14**
- Syntax-Check aller 8 `.py` Dateien: OK.
- Test-Suite `tests/test_core.py` (12 Tests) mit echtem Modul-Code, minimaler YAML/Typer/Pytest-Stub (Sandbox hat keine Pakete):
  `test_check_root_marker`, `test_check_root_missing`, `test_check_root_schwaches_signal`, `test_ignoriert_underscore_ordner`,
  `test_category_normalisierung`, `test_category_doppelt_verboten`, `test_category_remove_nicht_leer`,
  `test_part_id_normalisierung`, `test_part_new_find`, `test_part_new_fehlende_kategorie`, `test_part_doppelt_verboten`,
  `test_config_roundtrip` → **12/12 PASS**
- CLI End-to-End Simulation (echte Befehlsfunktionen):
  `init` → `status` → `category add` (Umlaut-Normalisierung „Kondensatoren & Co“ → `kondensatoren-co`) → `part new` → `part show` (case-insensitive) → `cat list` → `root detect`
  + Fehlerpfade: doppelte Kategorie, unbekanntes Teil → Exit 1
  → **3/3 PASS**

**2026-11-12, echtes Python 3.14.10 unter Windows 11 (venv, PyYAML 6.0.3, Typer 0.29.1, pytest 9.2.0)**
- `pip install -r requirements.txt -e .` → OK
- `pytest tests -q` → **12/12 PASS**
- `lager --help`, `status --json`, `part show irlz44n --json`, `category list --json` → OK, Exit 0
- Fehlerpfad `part show gibtsnicht` → deutsche Meldung auf stderr, Exit 1
- **Gefunden und behoben:** Bei umgeleiteter Ausgabe (Pipe) schrieb die CLI Umlaute in Windows-1252 statt UTF-8
  (`Widerstände` → Byte `e4`), was den `--json`-Vertrag für andere Programme brach. Jetzt stellt
  `cli.main()` stdout und stderr fest auf UTF-8 (`force_utf8_output`). Der Einstiegspunkt ist deshalb
  `lager.cli:main` statt `lager.cli:app`. Tests dazu in `tests/test_cli.py` → jetzt **14/14 PASS**.
- Damit ist alles erledigt, was am 2026-11-11 mangels Python offen geblieben war: venv, `pytest` mit echten Paketen, `lager --help`, `git init` + erster Commit (Repository `ersd3/wwsystem`).

**2026-11-12, Phase 0.2 und Grundgerüst (Python 3.14.10, SQLite 3.50.4, FastAPI 0.162, Starlette 1.10)**
- `pytest tests -q` → **66/66 PASS** (Kern 12, CLI 10, Index und Suche 24, Server 20)
- Index gegen das echte Beispiel-Lager: `lager index rebuild --json` → 2 Kategorien, 2 Bauteile, keine Warnungen
- `lager part search irlz44n --json` → 1 Treffer; Suche mit Umlaut (`widerstände`) → findet `223-0.1W`
- `lager serve` echt gestartet: `/api/v1/health`, `/api/v1/parts?q=irlz44n`, `/` und `/docs` antworten mit 200
- Handy-Seiten im Browser bei 375 px Breite geprüft (hell und dunkel), mit einem Wegwerf-Lager samt Test-PDF:
  Suche, Bauteilseite, PDF öffnet im Browser (`inline`), andere Dateien werden geladen, kein seitliches Scrollen
- **Noch nicht geprüft:** Zugriff von einem echten Handy im WLAN (`lager serve --host 0.0.0.0`), ein Lager mit
  mehreren tausend Bauteilen (Dauer des Neuaufbaus), Linux

Python 3.14 ist seit 2026-11-12 für das Benutzerkonto installiert; das venv liegt in `.venv` (nicht in Git).

Sample-Daten: Menge = 0 mit Hinweis „Beispiel-Bauteil — Menge 0, bitte korrigieren“. **Keine realen Bestände erfinden.**

---

## 6. Setup-Anleitung

```bat
# Python 3.11+ installieren falls nicht vorhanden
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -e .
.venv\Scripts\lager --help
.venv\Scripts\python -m pytest tests -q
```

Smoke:
```bat
.venv\Scripts\lager status --json
.venv\Scripts\lager part show IRLZ44N --json
.venv\Scripts\lager index rebuild
.venv\Scripts\lager part search irlz44n
.venv\Scripts\lager serve
```

`lager serve` läuft dann unter `http://127.0.0.1:8080`. Fürs Handy im WLAN: `lager serve --host 0.0.0.0`.

---

## 7. Roadmap & Akzeptanzkriterien

Reihenfolge am 2026-11-12 nach den Prioritäten von Lukas neu geordnet (D7). Maßgeblich ist die Tabelle in `KONZEPT.md` §10.

**0.2 Index (SQLite) — fertig:** `<root>/.lager/parts.db` mit Tabellen `parts` und `files` (Datenblätter und andere Dateien je Bauteil). `lager index rebuild` idempotent. Schema nach D6 als reines SQL (`schema.sql`), sprachneutral. Die Tabelle `movements` kommt erst in Phase 5 und wird dann nie neu aufgebaut.  
**1 Suche + Datenblätter (CLI):** `lager part search <begriff>` case-insensitive über part/aliases/name/manufacturer/tags/category; Dateien eines Bauteils anzeigen; neues Datenblatt einem Bauteil zuordnen. Akzeptanz: `search irlz44n` findet IRLZ44N und zeigt dessen Datenblatt. **Stand:** Suche fertig. Offen: Datenblatt einem Bauteil zuordnen (`part attach` o. ä.), Suche auch in Dateinamen.  
**2 Server + Web fürs Handy:** FastAPI, OpenAPI, `/api/v1/...`, Jinja2+HTMX Deutsch, zuerst fürs Handy gestaltet, Dateiauslieferung, optional `X-Lager-Token`. Das ist zugleich die mobile App (D8). Akzeptanz: Am Handy im WLAN funktioniert Suche → Bauteilseite → PDF öffnen. **Stand:** Grundgerüst läuft (API, Dateien, Suche, Bauteilseite; ohne HTMX). Offen: am echten Handy prüfen, Daten über das Web ändern, Suche beim Tippen.  
**3 Handy-Komfort:** `lager qr print <teil>` PDF mit QR zu `public_url/p/<id>`. Später HTTPS, damit ein Kamera-Scanner in der Seite und der Startbildschirm (PWA) möglich werden. Akzeptanz: Handy-Kamera öffnet die Bauteilseite.  
**4 MCP:** MCP-Server `lager mcp` (stdio) mit Tools `search_parts`, `get_part`, `create_part`, `update_part`, `list_categories`, `add_category`, `reindex` für die Datenpflege durch lokale Agenten. Akzeptanz: LM Studio kann MCP ansteuern.  
**5 Mengen:** `lager stock in/out`, `lager stock list --low N`, Verlauf in `movements`, MCP-Tool `set_quantity`.  
**6 Linux:** Portabilität, Packaging, Backup.

---

## 8. Arbeitsregeln für Nachfolger

- **Vor dem Commit fragen:** Lokal darf direkt geschrieben werden. Vor jedem Commit zeigen, was geändert wurde, und auf das Ja von Lukas warten (festgelegt am 2026-11-12).
- **Danach direkt hochladen:** nach dem Ja committen und ohne weitere Rückfrage direkt auf `main` zu GitHub pushen (`ersd3/wwsystem`). Kein eigener Branch, kein Pull Request.
- **Doku immer aktuell:** `KONZEPT.md` und `HANDOVER.md` bei jeder Änderung mitziehen. Lukas verfolgt darüber den Projektfortschritt.
- `main` immer lauffähig, kleine Commits, Tests vor Features.
- CLI `--json` Vertrag ist heilig.
- Ordner/part.yaml-Vertrag nicht brechen ohne `KONZEPT.md` + `HANDOVER.md` aktualisieren.
- Explizites `--force` für destruktive Deletes.
- Keine Windows-Only-APIs. `pathlib` nutzen.
- Nie reale Lagerbestände erfinden, Sample-Teile bleiben bei Menge 0 mit Hinweis.

---

## 9. Offene Fragen an Lukas

- ~~Ist Python/FastAPI als Stack bestätigt?~~ Ja, am 2026-11-12 von Lukas bestätigt.
- Finale Kategorienliste (jetzt Platzhalter)?
- Lagerfach-Schema (z.B. „A-03-2“)?
- LAN-Name/IP für `public_url` (für QR, Phase 3)?
- Auf welchem Gerät läuft der Server später im WLAN (dieser PC oder ein eigener Linux-Rechner)? Wichtig ab Phase 2.
- Soll es HTTPS geben (nötig für Kamera-Scanner in der Seite und Startbildschirm, Phase 3)?

---

## Anhang A — Vollständige Phase-0.1-Quellen (Stand 2026-11-11)

*Hinweis: Dateien im Projektordner sind maßgeblich. Der Anhang ist 1:1-Kopie, falls nur die .md übertragen wird.*

*Achtung: Der Anhang zeigt den Stand vom 2026-11-11 und ist nicht mehr vollständig aktuell. Seitdem geändert: `pyproject.toml`, `src/lager/__main__.py`, `src/lager/cli.py` (Einstiegspunkt `main()`, UTF-8-Ausgabe); neu: `tests/test_cli.py`. Der aktuelle Code liegt im Repository `ersd3/wwsystem`.*

### pyproject.toml
```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "lager"
version = "0.1.0"
description = "Bauteile-Lagersystem: offene Ordnerstruktur, bewegbarer Root, Kategorien und part.yaml (CLI)"
requires-python = ">=3.9"
dependencies = [
    "typer>=0.9",
    "PyYAML>=6.0",
    "pytest>=7.0",
]

[project.scripts]
lager = "lager.cli:app"

[tool.setuptools.packages.find]
where = ["src"]
```

### requirements.txt
```
typer>=0.9
PyYAML>=6.0
pytest>=7.0
```

### .gitignore
```
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
build/
dist/
*.egg-info/
```

### config.yaml
```yaml
# Konfiguration — Lagersystem
#
# lager_root: Pfad zum Lager-Root (die Ordnerstruktur mit Kategorien und Bauteilen).
#   leer     = Auto-Erkennung (Projektordner/lager, dann ~/lager)
#   relativ  = relativ zu diesem Projektordner (gut zum Verschieben)
#   absolut  = wird direkt verwendet
# Ändern: Lager verschieben? -> `lager root set <neuer-pfad>`
lager_root: "lager"

server:
  host: "127.0.0.1"
  port: 8080
  # URL, die später auf QR-Etiketten stehen soll (muss vom Handy erreichbar sein),
  # z. B. "http://192.168.1.50:8080"
  public_url: ""

# Token für Schreiboperationen (Server/Phase 2+); leer = ohne Schreibschutz
# (für privates LAN gedacht)
write_token: ""
```

### src/lager/__init__.py
```python
"""Lager — Bauteile-Lagersystem.

Offene Ordnerstruktur als Quelle der Wahrheit, abgeleiteter SQLite-Index
und mehrere Clients (CLI, Web, MCP) über einen gemeinsamen Kern.
"""

__version__ = "0.1.0"
```

### src/lager/__main__.py
```python
from lager.cli import app

if __name__ == "__main__":
    app()
```

### src/lager/config.py
```python
"""Konfiguration: Laden, Speichern, Pfade auflösen."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_DIR / "config.yaml"

DEFAULTS: dict[str, Any] = {
    "lager_root": "",
    "server": {"host": "127.0.0.1", "port": 8080, "public_url": ""},
    "write_token": "",
}

def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = dict(DEFAULTS)
    merged.update(data)
    server = dict(DEFAULTS["server"])
    server.update(data.get("server") or {})
    merged["server"] = server
    return merged

def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

def resolve_lager_root(cfg: dict[str, Any], config_path: Path = CONFIG_PATH) -> Path | None:
    raw = str(cfg.get("lager_root") or "").strip()
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = config_path.resolve().parent / p
    return p

def set_lager_root(value: str, config_path: Path = CONFIG_PATH) -> Path:
    cfg = load_config(config_path)
    target = Path(os.path.expanduser(value)).resolve()
    try:
        rel = target.relative_to(config_path.resolve().parent)
        cfg["lager_root"] = rel.as_posix()
    except ValueError:
        cfg["lager_root"] = str(target)
    save_config(cfg, config_path)
    return target
```

### src/lager/root.py
```python
"""Erkennung und Validierung des Lager-Roots."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_DIR, load_config, resolve_lager_root

CATEGORY_MARKER = "categories.yaml"
IGNORED_PREFIXES = ("_", ".")

@dataclass
class Check:
    path: Path
    valid: bool
    reason: str
    parts: int = 0
    categories: int = 0

def _visible_dirs(d: Path) -> list[Path]:
    try:
        return [x for x in sorted(d.iterdir()) if x.is_dir() and not x.name.startswith(IGNORED_PREFIXES)]
    except OSError:
        return []

def is_part_dir(d: Path) -> bool:
    return d.is_dir() and (d / "part.yaml").is_file()

def count_parts(root: Path) -> int:
    total = 0
    def walk(d: Path) -> None:
        nonlocal total
        for child in _visible_dirs(d):
            if is_part_dir(child):
                total += 1
            else:
                walk(child)
    walk(root)
    return total

def count_categories(root: Path) -> int:
    return len([d for d in _visible_dirs(root) if not is_part_dir(d)])

def check_root(path: Path) -> Check:
    if not path.is_dir():
        return Check(path, False, "existiert nicht oder ist kein Ordner")
    n_cats = count_categories(path)
    n_parts = sum(1 for d in _visible_dirs(path) if is_part_dir(d))
    n_parts += sum(count_parts(d) for d in _visible_dirs(path) if not is_part_dir(d))
    if (path / CATEGORY_MARKER).is_file():
        return Check(path, True, "categories.yaml gefunden (Marker)", n_parts, n_cats)
    if n_parts > 0:
        return Check(path, True, f"Teil-Struktur erkannt ({n_parts} Bauteile mit part.yaml)", n_parts, n_cats)
    return Check(path, False, "kein categories.yaml und keine Teil-Struktur (kategorie/<teil>/part.yaml)", 0, n_cats)

def candidate_roots(cfg: dict | None = None) -> list[Path]:
    if cfg is None:
        cfg = load_config()
    cands: list[Path] = []
    explicit = resolve_lager_root(cfg)
    if explicit is not None:
        cands.append(explicit)
    cands.append(PROJECT_DIR / "lager")
    cands.append(Path.home() / "lager")
    seen: set[str] = set()
    out: list[Path] = []
    for c in cands:
        key = str(c).lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out

def detect(cfg: dict | None = None) -> tuple[Check | None, list[Check]]:
    checks = [check_root(c) for c in candidate_roots(cfg)]
    found = next((c for c in checks if c.valid), None)
    return found, checks
```

### src/lager/categories.py
```python
"""Kategorien: categories.yaml lesen/schreiben, anlegen, entfernen."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

HEADER = """# Kategorien des Lagers.
# id    = Ordnername (normalisiert: a-z, 0-9, '-')
# label = Anzeigename (darf Umlaute enthalten)
# Reihenfolge = Anzeige-Reihenfolge.
# Anlegen: lager category add <id> [--label "Anzeigename"]
"""

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_UMLAUTS = str.maketrans({"ä":"ae","ö":"oe","ü":"ue","ß":"ss","Ä":"ae","Ö":"oe","Ü":"ue","ẞ":"ss"})

def normalize_id(raw: str) -> str:
    s = raw.strip().translate(_UMLAUTS).lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s

def path(root: Path) -> Path:
    return root / "categories.yaml"

def load(root: Path) -> list[dict]:
    p = path(root)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cats = data.get("categories") or []
    return [c for c in cats if isinstance(c, dict) and c.get("id")]

def save(root: Path, cats: list[dict]) -> None:
    body = yaml.safe_dump({"categories": cats}, allow_unicode=True, sort_keys=False)
    path(root).write_text(HEADER + body, encoding="utf-8")

def add(root: Path, cat_id: str, label: str = "") -> dict:
    cat_id = normalize_id(cat_id)
    if not _ID_RE.match(cat_id or ""):
        raise ValueError(f"Ungültige Kategorie-ID: {cat_id!r}")
    cats = load(root)
    if any(c["id"] == cat_id for c in cats):
        raise ValueError(f"Kategorie existiert bereits: {cat_id}")
    entry = {"id": cat_id, "label": label or cat_id.replace("-", " ").title()}
    cats.append(entry)
    save(root, cats)
    (root / cat_id).mkdir(parents=True, exist_ok=True)
    return entry

def remove(root: Path, cat_id: str, force: bool = False) -> None:
    cats = load(root)
    if not any(c["id"] == cat_id for c in cats):
        raise KeyError(f"Kategorie nicht gefunden: {cat_id}")
    d = root / cat_id
    if d.exists():
        if any(d.iterdir()) and not force:
            raise ValueError(f"Ordner nicht leer: {d} (mit --force löschen)")
        if force:
            shutil.rmtree(d)
    save(root, [c for c in cats if c["id"] != cat_id])
```

### src/lager/parts.py
```python
"""Bauteile: Bezeichnungen normalisieren, part.yaml anlegen und lesen."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

PART_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.+]*$")
_DISALLOWED = re.compile(r"[^A-Z0-9\-_.+]")

HEADER = """# part.yaml — Metadaten eines Bauteils
# part       kanonische Bezeichnung (= Ordnername)
# name       Beschreibung (menschlich)
# aliases    weitere Suchbegriffe (Bestell-, Hersteller-, Alt-Bezeichnungen)
# quantity   aktuelle Lagermenge
# unit       Mengeneinheit
# location   Lagerfach (frei wählbar, z. B. "A-03-2")
# tags       freie Schlagwörter
# Kategorie  kommt aus dem Pfad (1. Ebene unter lager_root) — nicht hier speichern
"""

def normalize_part_id(raw: str) -> str:
    s = raw.strip().upper().replace(" ", "")
    return _DISALLOWED.sub("", s)

def part_dir(root: Path, category_id: str, part_id: str) -> Path:
    return root / category_id / part_id

def read_part(root: Path, category_id: str, part_id: str) -> dict:
    p = part_dir(root, category_id, part_id) / "part.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Teil nicht gefunden: {category_id}/{part_id}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

def find_part(root: Path, raw_id: str) -> tuple[Path, dict] | None:
    target = normalize_part_id(raw_id).lower()
    if not target:
        return None
    for py in sorted(root.rglob("part.yaml")):
        if any(part.startswith(("_", ".")) for part in py.parts):
            continue
        if py.parent.name.lower() == target:
            data = yaml.safe_load(py.read_text(encoding="utf-8")) or {}
            return py.parent, data
    return None

def empty_doc_yaml() -> str:
    doc = {
        "part": "BEZEICHNUNG",
        "name": "",
        "manufacturer": "",
        "aliases": [],
        "quantity": 0,
        "unit": "Stk",
        "location": "",
        "tags": [],
        "notes": "",
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)

def create_part(root: Path, category_id: str, raw_id: str, data: dict) -> Path:
    part_id = normalize_part_id(raw_id)
    if not part_id or not PART_ID_RE.match(part_id):
        raise ValueError(f"Ungültige Bauteil-Bezeichnung: {raw_id!r}")
    cat_dir = root / category_id
    if not cat_dir.is_dir():
        raise ValueError(f"Kategorie existiert nicht: {category_id} (erst: lager category add {category_id})")
    pdir = cat_dir / part_id
    if (pdir / "part.yaml").exists():
        raise ValueError(f"Teil existiert bereits: {pdir}")
    pdir.mkdir(parents=False)
    doc = {
        "part": part_id,
        "name": data.get("name", ""),
        "manufacturer": data.get("manufacturer", ""),
        "aliases": list(data.get("aliases") or []),
        "quantity": int(data.get("quantity", 0)),
        "unit": data.get("unit", "Stk"),
        "location": data.get("location", ""),
        "tags": list(data.get("tags") or []),
        "notes": data.get("notes", ""),
    }
    (pdir / "part.yaml").write_text(HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return pdir
```

### src/lager/cli.py
```python
"""Lager-CLI — für Menschen und AI-Agenten.

Agentenvertrag: Jeder Befehl unterstützt --json und liefert dann ein
striktes JSON-Objekt. Fehler gehen mit Statuscode != 0 und deutscher
Meldung auf stderr.
"""
from __future__ import annotations

import json
from pathlib import Path
import typer
from . import __version__, categories as catmod
from . import parts as partmod
from . import root as rootmod
from .config import CONFIG_PATH, load_config, resolve_lager_root, save_config, set_lager_root

app = typer.Typer(name="lager", help="Lager-CLI — Bauteile verwalten. Alle Befehle unterstützen --json.", no_args_is_help=True)
root_app = typer.Typer(help="Lager-Root verwalten (bewegbar).")
cat_app = typer.Typer(help="Kategorien verwalten (anlegbar, nichts hardcodiert).")
part_app = typer.Typer(help="Bauteile verwalten (part.yaml).")
app.add_typer(root_app, name="root")
app.add_typer(cat_app, name="category")
app.add_typer(part_app, name="part")

def _print(data: dict, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        for k, v in data.items():
            typer.echo(f"{k}: {v}")

def _require_root() -> Path:
    cfg = load_config()
    explicit = resolve_lager_root(cfg)
    if explicit is not None and rootmod.check_root(explicit).valid:
        return explicit
    found, _ = rootmod.detect(cfg)
    if found is not None:
        return found.path
    typer.echo("Fehler: Kein gültiger Lager-Root gefunden. Nutze `lager init <pfad>` oder `lager root set <pfad>`.", err=True)
    raise typer.Exit(1)

@app.command()
def version() -> None:
    typer.echo(f"lager {__version__}")

@app.command()
def init(pfad: Path = typer.Argument(...), force: bool = typer.Option(False, "--force"), as_json: bool = typer.Option(False, "--json")) -> None:
    target = Path(pfad).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not force:
        typer.echo(f"Zielordner existiert und ist nicht leer: {target} (mit --force übernehmen)", err=True)
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
    _print({"aktion":"init","root":str(target),"config":str(CONFIG_PATH),"gueltig":check.valid,"grund":check.reason}, as_json)

@app.command()
def status(as_json: bool = typer.Option(False, "--json")) -> None:
    cfg = load_config()
    explicit = resolve_lager_root(cfg)
    found, checks = rootmod.detect(cfg)
    quelle = "config" if found is not None and explicit is not None and found.path == explicit else "auto" if found is not None else "keine"
    data = {"config":str(CONFIG_PATH),"lager_root_config":str(explicit) if explicit else "","lager_root_aktiv":str(found.path) if found else "","quelle":quelle,"kandidaten":[{"pfad":str(c.path),"gueltig":c.valid,"grund":c.reason,"teile":c.parts,"kategorien":c.categories} for c in checks]}
    if found is not None:
        data["kategorien"] = len(catmod.load(found.path))
        data["teile"] = found.parts
    _print(data, as_json)
    if found is None and not as_json:
        typer.echo("Tipp: lager init <pfad>  oder  lager root set <pfad>")

@root_app.command("set")
def root_set(pfad: Path = typer.Argument(...), as_json: bool = typer.Option(False, "--json")) -> None:
    target = Path(pfad).expanduser().resolve()
    check = rootmod.check_root(target)
    set_lager_root(str(target))
    _print({"lager_root":str(target),"gueltig":check.valid,"grund":check.reason}, as_json)
    if not check.valid and not as_json:
        typer.echo("Warnung: Struktur nicht valid. Tipp: lager init <pfad>")

@root_app.command("unset")
def root_unset(as_json: bool = typer.Option(False, "--json")) -> None:
    cfg = load_config()
    cfg["lager_root"] = ""
    save_config(cfg)
    _print({"lager_root":""}, as_json)

@root_app.command("detect")
def root_detect(as_json: bool = typer.Option(False, "--json")) -> None:
    found, checks = rootmod.detect()
    _print({"erkannt":str(found.path) if found else "","kandidaten":[{"pfad":str(c.path),"gueltig":c.valid,"grund":c.reason,"teile":c.parts,"kategorien":c.categories} for c in checks]}, as_json)

@cat_app.command("add")
def cat_add(kategorie: str = typer.Argument(...), label: str = typer.Option("", "--label"), as_json: bool = typer.Option(False, "--json")) -> None:
    root = _require_root()
    try:
        entry = catmod.add(root, kategorie, label)
    except ValueError as e:
        typer.echo(f"Fehler: {e}", err=True)
        raise typer.Exit(1)
    _print({"kategorie":entry,"pfad":str(root/entry["id"])}, as_json)

@cat_app.command("list")
def cat_list(as_json: bool = typer.Option(False, "--json")) -> None:
    root = _require_root()
    cats = []
    for c in catmod.load(root):
        d = root / c["id"]
        cats.append({"id":c["id"],"label":c.get("label",c["id"]),"teile":rootmod.count_parts(d) if d.is_dir() else 0})
    _print({"kategorien":cats}, as_json)

@cat_app.command("remove")
def cat_remove(kategorie: str = typer.Argument(...), force: bool = typer.Option(False, "--force"), as_json: bool = typer.Option(False, "--json")) -> None:
    root = _require_root()
    try:
        catmod.remove(root, kategorie, force=force)
    except (KeyError, ValueError) as e:
        typer.echo(f"Fehler: {e.args[0] if e.args else e}", err=True)
        raise typer.Exit(1)
    _print({"entfernt":kategorie}, as_json)

@part_app.command("new")
def part_new(bezeichnung: str = typer.Argument(...), category: str = typer.Option(..., "--category","-c"), name: str = typer.Option("", "--name","-n"), manufacturer: str = typer.Option("", "--manufacturer","-m"), quantity: int = typer.Option(0, "--quantity","-q"), location: str = typer.Option("", "--location","-l"), tags: str = typer.Option("", "--tags"), aliases: str = typer.Option("", "--aliases"), as_json: bool = typer.Option(False, "--json")) -> None:
    root = _require_root()
    data = {"name":name,"manufacturer":manufacturer,"quantity":quantity,"location":location,"tags":[t.strip() for t in tags.split(",") if t.strip()],"aliases":[a.strip() for a in aliases.split(",") if a.strip()]}
    try:
        pdir = partmod.create_part(root, category, bezeichnung, data)
    except ValueError as e:
        typer.echo(f"Fehler: {e}", err=True)
        raise typer.Exit(1)
    _print({"teil":str(pdir)}, as_json)

@part_app.command("show")
def part_show(bezeichnung: str = typer.Argument(...), as_json: bool = typer.Option(False, "--json")) -> None:
    root = _require_root()
    found = partmod.find_part(root, bezeichnung)
    if found is None:
        typer.echo(f"Fehler: Teil nicht gefunden: {bezeichnung}", err=True)
        raise typer.Exit(1)
    pdir, data = found
    files = [{"pfad":f.relative_to(pdir).as_posix(),"typ":f.suffix.lower().lstrip(".")} for f in sorted(pdir.rglob("*")) if f.is_file() and f.name != "part.yaml"]
    _print({"ordner":str(pdir),"daten":data,"dateien":files}, as_json)
```

### tests/test_core.py
```python
"""Tests für die Kern-Logik (Root-Erkennung, Kategorien, Bauteile, Config)."""
from pathlib import Path
import pytest
from lager import categories, parts, root
from lager import config

@pytest.fixture()
def lager(tmp_path: Path) -> Path:
    r = tmp_path / "lager"
    r.mkdir()
    categories.save(r, [])
    return r

def test_check_root_marker(lager):
    c = root.check_root(lager)
    assert c.valid
    assert "categories.yaml" in c.reason

def test_check_root_missing(tmp_path):
    c = root.check_root(tmp_path / "nichts")
    assert not c.valid

def test_check_root_schwaches_signal(lager):
    (lager / "categories.yaml").unlink()
    assert not root.check_root(lager).valid
    (lager / "mosfets" / "IRLZ44N").mkdir(parents=True)
    (lager / "mosfets" / "IRLZ44N" / "part.yaml").write_text("part: IRLZ44N\n", encoding="utf-8")
    c = root.check_root(lager)
    assert c.valid
    assert c.parts == 1

def test_ignoriert_underscore_ordner(lager):
    (lager / "_vorlage" / "part.yaml").parent.mkdir(parents=True)
    (lager / "_vorlage" / "part.yaml").write_text("part: X\n", encoding="utf-8")
    c = root.check_root(lager)
    assert c.valid
    assert c.parts == 0

def test_category_normalisierung(lager):
    e = categories.add(lager, "Widerstände & Co", "Widerstände")
    assert e["id"] == "widerstaende-co"
    assert e["label"] == "Widerstände"
    assert (lager / "widerstaende-co").is_dir()

def test_category_doppelt_verboten(lager):
    categories.add(lager, "mosfets")
    with pytest.raises(ValueError):
        categories.add(lager, "mosfets")

def test_category_remove_nicht_leer(lager):
    categories.add(lager, "mosfets")
    (lager / "mosfets" / "etwas.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        categories.remove(lager, "mosfets")
    categories.remove(lager, "mosfets", force=True)
    assert not (lager / "mosfets").exists()
    assert categories.load(lager) == []

def test_part_id_normalisierung():
    assert parts.normalize_part_id(" iRLz44n ") == "IRLZ44N"
    assert parts.normalize_part_id("ATMEGA328P-PU") == "ATMEGA328P-PU"

def test_part_new_find(lager):
    categories.add(lager, "mosfets")
    pdir = parts.create_part(lager, "mosfets", " Irlz44n ", {"quantity": 5, "tags": ["a"]})
    assert pdir.name == "IRLZ44N"
    found = parts.find_part(lager, "irlz44n")
    assert found is not None
    _, data = found
    assert data["quantity"] == 5

def test_part_new_fehlende_kategorie(lager):
    with pytest.raises(ValueError):
        parts.create_part(lager, "keine", "X1", {})

def test_part_doppelt_verboten(lager):
    categories.add(lager, "mosfets")
    parts.create_part(lager, "mosfets", "IRLZ44N", {})
    with pytest.raises(ValueError):
        parts.create_part(lager, "mosfets", "irlz44n", {})

def test_config_roundtrip(tmp_path):
    cp = tmp_path / "config.yaml"
    cfg = config.load_config(cp)
    assert cfg["lager_root"] == ""
    config.set_lager_root(str(tmp_path / "lager"), cp)
    assert config.load_config(cp)["lager_root"] == "lager"
    resolved = config.resolve_lager_root(config.load_config(cp), cp)
    assert resolved == tmp_path / "lager"
```

### lager/categories.yaml
```yaml
categories:
- id: mosfets
  label: MOSFETs
- id: widerstaende
  label: Widerstände
```

### lager/_vorlage/part.yaml
```yaml
# part.yaml — Metadaten eines Bauteils
# part       kanonische Bezeichnung (= Ordnername)
# name       Beschreibung (menschlich)
# aliases    weitere Suchbegriffe (Bestell-, Hersteller-, Alt-Bezeichnungen)
# quantity   aktuelle Lagermenge
# unit       Mengeneinheit
# location   Lagerfach (frei wählbar, z. B. "A-03-2")
# tags       freie Schlagwörter
# Kategorie  kommt aus dem Pfad (1. Ebene unter lager_root) — nicht hier speichern
part: BEZEICHNUNG
name: ''
manufacturer: ''
aliases: []
quantity: 0
unit: Stk
location: ''
tags: []
notes: ''
```

### lager/mosfets/IRLZ44N/part.yaml
```yaml
part: IRLZ44N
name: MOSFET N-Kanal 55 V / 47 A, TO-220
manufacturer: Infineon
aliases:
- IRLZ44NTR
quantity: 0
unit: Stk
location: ''
tags:
- mosfet
- n-kanal
- to-220
notes: Beispiel-Bauteil aus der Projektanlegung (Menge 0, bitte korrigieren).
```

### lager/widerstaende/223-0.1W/part.yaml
```yaml
part: 223-0.1W
name: Widerstand 22 kOhm, 0.1 W, 5 %
manufacturer: ''
aliases: []
quantity: 0
unit: Stk
location: ''
tags:
- widerstand
- 22k
notes: Beispiel-Bauteil aus der Projektanlegung (Menge 0, bitte korrigieren).
```

---

*Ende HANDOVER. Nächste Aktion: mit Lukas den Server am echten Handy im WLAN prüfen, dann Phase 1 abschließen (Datenblatt zuordnen). Vor jedem Commit fragen.*
