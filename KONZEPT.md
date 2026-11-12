# Konzept — Bauteile-Lagersystem ("Lager")

Stand: 2026-11-12 · Status: Phase 0.1 und 0.2 umgesetzt · Grundgerüst für Suche (Phase 1) und Server mit Handy-Seiten (Phase 2) steht · Stand je Phase: §10

## 1. Ziel

Ein System zur Pflege einer großen Sammlung elektronischer Bauteile
(Widerstände, Kondensatoren, Transistoren/MOSFETs, ICs, …) mit:

- Suche nach Bauteil, Alias, Name, Tag, Kategorie
- Abruf von Datenblättern (PDF), CAD-Modellen, KiCad-Dateien
- Mengennachhaltung (ein/ausbuchen, Lagerfach)
- **offener, sichtbarer Ordnerstruktur** (Windows & Linux, im Explorer sichtbar)
- Server + Web-Client, CLI und später Smartphone (QR) — alle bedienen denselben Kern
- Bedien- und pflegebar durch AI-Agenten (CLI mit `--json`, REST, MCP)

### Prioritäten (von Lukas, 2026-11-12)

Das System ist in erster Linie für die **private Nutzung** gedacht.

1. **Datenblätter schnell finden und einlesen.** Das ist der Hauptzweck: Bauteil suchen,
   Datenblatt öffnen und lesen, ein neues Datenblatt schnell aufnehmen.
2. **Nutzung am Handy.** Sie wird direkt nach der Grundstruktur gebaut (als Web-Oberfläche, D8).
3. **Mengen eintragen.** Nachrangig. Das Feld `quantity` in der `part.yaml` bleibt und kann
   von Hand gepflegt werden; Buchungen mit Verlauf kommen erst spät (Phase 5).

## 2. Grundprinzipien

| # | Prinzip |
|---|---------|
| P1 | **Ordnerstruktur = Quelle der Wahrheit** für Dateien und Kategorie. Alles nutzbar ohne das Programm (Explorer, Backup, Kopieren, Verschieben). |
| P2 | **`part.yaml`** = Metadaten je Bauteil (Menge, Ort, Hersteller, Aliase, Tags). Mensch- und maschinenlesbar. |
| P3 | **SQLite = abgeleiteter Index + Buchhaltung** (Phase 0.2). Jederzeit aus den Ordnern neu aufbaubar (`lager index rebuild`); die DB ist nie die einzige Kopie der Daten. |
| P4 | **Ein Kern, mehrere Clients:** Die REST-API (OpenAPI) ist die Kerneschnittstelle. Web-UI, CLI, MCP-Server und Smartphone-App sind nur Clients davon. |
| P5 | **Beweglicher Root:** Der Lager-Pfad ist eine einzige Konfig-Eigenschaft (`lager_root` in `config.yaml`). Die Struktur wird automatisch erkannt und validiert. |
| P6 | **Nichts hardcodiert:** Kategorien, Dateitypen, Pfade — alles Daten/Konfiguration, anpassbar per CLI (also auch per AI-Agent). |
| P7 | **Standards:** SQLite, REST/OpenAPI, YAML, QR = normale URL, PDF, KiCad-Originalformate. |
| P8 | **Sprachneutrale Daten:** Datenbank und Dateien enthalten nichts Python-Spezifisches. Jedes Programm in jeder Sprache kann sie mit Standardwerkzeugen lesen und schreiben (Regeln in §8, D6). |

## 3. Ordnerstruktur (Vertrag)

```
<lager_root>/
├── categories.yaml          # Kategorien (Marker + Liste)
├── _vorlage/                # ignoriert vom Scanner (Unterstrich-/Punkt-Präfix)
│   └── part.yaml
└── <kategorie>/             # Ebene 1 = Kategorie (Ordnername = id)
    └── <kategorie2>/        # Ebene 2 optional = Unterkategorie
        └── <BEZEICHNUNG>/   # Bauteil-Ordner, Name = normalisierte Bezeichnung
            ├── part.yaml
            ├── datasheet.pdf   # (oder andere .pdf)
            ├── 3d/             # .step, .stp, .wrl, …
            ├── kicad/          # .kicad_mod, .kicad_sym, .kicad_pcb, …
            └── images/         # .png, .jpg
```

Namensregeln:

- Kategorie-`id`: `a-z 0-9 -` (Umlaute werden transliteriert: `Widerstände` → `widerstaende`)
- Bauteil-`BEZEICHNUNG`: `A-Z 0-9 - _ . +`, großgeschrieben, z. B. `IRLZ44N`
- Ordner mit Präfix `_` oder `.` werden vom Scanner ignoriert (intern/Reserve)
- Dateien werden automatisch nach Typ erkannt (Dateiendung) → keine manuelle Registrierung

## 4. Bewegbarer Root + Auto-Erkennung

`config.yaml` im Projektordner:

```yaml
lager_root: "lager"   # leer = Auto-Erkennung; relativ = zum Projektordner; absolut = direkt
```

Auflösungsreihenfolge:

1. `lager_root` gesetzt und valid → wird verwendet (Quelle: `config`)
2. sonst Kandidaten: `<projekt>/lager/`, dann `~/lager/` (Quelle: `auto`)
3. Ein Kandidat ist **valid**, wenn er `categories.yaml` enthält (starker Marker)
   **oder** darunter `kategorie/<...>/part.yaml` existiert (Struktur passt)

Befehle: `lager init <pfad>`, `lager root set/unset/detect`, `lager status`.

## 5. Kategorien (anlegbar, nicht fix)

`<lager_root>/categories.yaml`:

```yaml
categories:
  - id: mosfets
    label: "MOSFETs"
```

- Anlegen: `lager category add mosfets --label "MOSFETs"` → Eintrag + Ordner
- Das Programm kennt **keine** feste Kategorienliste; es liest nur diese Datei
- Dadurch kann auch ein AI-Agent Kategorien anlegen (gleiche CLI, später MCP-Tool)

## 6. part.yaml (Schema v1)

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

- `part` = Ordnername (kanonisch)
- Die Kategorie kommt aus dem Pfad (1. Ebene) → wird nicht doppelt gespeichert
- `quantity` ist der Ist-Stand in `part.yaml`; jede Änderung erzeugt (ab Phase 5)
  zusätzlich einen Eintrag in der SQLite-Tabelle `movements` (historisch, mit Quelle)

## 6a. Such-Index (SQLite, Phase 0.2 — umgesetzt)

Der Index liegt unter `<lager_root>/.lager/parts.db` und wandert mit dem Lager. Er ist
abgeleitet: Die Ordner bleiben die Quelle der Wahrheit (P1, P3). Das Schema steht als
reines SQL in `src/lager/schema.sql` (D6).

| Tabelle | Inhalt |
|---|---|
| `categories` | Ordner der ersten Ebene; `label` und Reihenfolge aus `categories.yaml`; `listed` = 0, wenn der Ordner dort fehlt |
| `parts` | ein Bauteil je Ordner mit `part.yaml`: Bezeichnung, Kategorie, Unterkategorie, Pfad, Felder der `part.yaml`, Suchtext |
| `part_aliases`, `part_tags` | Aliase und Tags, je eine Zeile |
| `files` | Dateien im Bauteil-Ordner: Pfad, Art (`kind`), Endung, Größe, Änderungszeit |
| `meta` | `built_at` (letzter Aufbau), `generator` |

Regeln (D9):

- **Neuaufbau:** `lager index rebuild` leert alle Tabellen und füllt sie neu, in einer
  einzigen Transaktion. Schlägt er fehl, bleibt der alte Index erhalten. Beliebig oft ausführbar.
- **Fehler in den Ordnern brechen nicht ab:** Eine unlesbare `part.yaml`, ein Bauteil ohne
  Kategorie oder eine doppelte Bezeichnung erscheinen als Warnung im Ergebnis.
- **Dateiart nach Endung:** `datasheet` (pdf), `cad3d`, `kicad`, `image`, sonst `other`.
  Die Zuordnung ist in `config.yaml` unter `file_kinds` änderbar (P6).
- **Nicht im Index:** `part.yaml` selbst, Dateien und Ordner mit `.`-Präfix, `Thumbs.db`, `desktop.ini`.
- **Wann der Index aktuell ist:** nach jedem `rebuild`, nach `part new`, `category add/remove`
  (falls schon ein Index existiert) und bei jedem Start des Servers. Wer Dateien im Explorer
  ändert, liest danach neu ein: `lager index rebuild` oder Knopf „Ordner neu einlesen“ im Web.
- **IDs sind nicht stabil:** `parts.id` wird bei jedem Neuaufbau neu vergeben. Dauerhafte
  Verweise (später `movements`) nutzen `parts.rel_path`.

Suche (`lager part search`, `/api/v1/parts`, Web): Jeder Begriff muss vorkommen, Groß- und
Kleinschreibung sowie Umlaute spielen keine Rolle, Teilwörter zählen (`44n` findet `IRLZ44N`).
Durchsucht werden Bezeichnung, Name, Hersteller, Aliase, Tags, Kategorie, Unterkategorie und
Lagerfach. Treffer, deren Bezeichnung mit dem ersten Begriff beginnt, stehen vorn.

## 7. Architektur (Zielbild)

```
 Browser ─────► Web UI (Jinja2 + HTMX)
                      │
 AI-Agent ─────► MCP-Server ─┐
                             ▼
                      REST-API (FastAPI, OpenAPI/Swagger)
                             │
 CLI ───────────► CORE: Index, Dateien, Kategorien, Buchungen
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
          SQLite (Index ab 0.2,  Ordnerstruktur (Quelle der
          movements ab 5)        Wahrheit: part.yaml + Dateien)
```

Schnittstellen:

- **REST** (Phase 2): `/api/v1/…` + OpenAPI + Swagger-UI
- **CLI** (Grundgerüst fertig in 0.1): `lager …` — jeder Befehl mit `--json`
- **Web** (Phase 2): zuerst fürs Handy gestaltet — Suche, Kategorie-Browse, Bauteilseite,
  Datenblatt öffnen. Das ist zugleich die mobile App (D8).
- **QR** (Phase 3): `http://<host>:<port>/p/<BEZEICHNUNG>` — jede Handy-Kamera öffnet die Seite
- **MCP** (Phase 4): Tools `search_parts, get_part, create_part, …` für die Datenpflege
  durch lokale Agenten

### Stand des Server-Grundgerüsts (2026-11-12)

Start: `lager serve` (Adresse und Port aus `config.yaml`, Standard `127.0.0.1:8080`).
Für das Handy im WLAN: `lager serve --host 0.0.0.0`, dann am Handy `http://<IP-des-PCs>:8080`.

| Adresse | Zweck |
|---|---|
| `/` | Suche, Kategorien, Trefferliste; Knopf „PDF“ öffnet das Datenblatt direkt |
| `/p/<BEZEICHNUNG>` | Bauteilseite: Datenblätter, Angaben, weitere Dateien |
| `/files/<pfad wie im Lager-Ordner>` | Datei ausliefern; PDF und Bilder öffnet der Browser, alles andere wird geladen |
| `/api/v1/parts?q=…`, `/api/v1/parts/<BEZEICHNUNG>` | Suche und Bauteil als JSON |
| `/api/v1/categories`, `/api/v1/index`, `/api/v1/health` | Kategorien, Zustand des Index, Lebenszeichen |
| `POST /api/v1/index/rebuild` | Ordner neu einlesen (mit `X-Lager-Token`, falls `write_token` gesetzt) |
| `/docs`, `/openapi.json` | API-Beschreibung, von FastAPI erzeugt |

- Ausgeliefert werden nur Dateien, die im Index stehen. Andere Pfade ergeben „nicht gefunden“.
- CLI (`--json`) und API geben dieselben Daten aus (D10): Datensätze mit den englischen
  Feldnamen aus Schema und `part.yaml` (`part`, `name`, `files`, …), Rahmenfelder wie in der
  bisherigen CLI auf Deutsch (`suche`, `anzahl`, `treffer`, `teile`, `warnungen`).
- Noch nicht enthalten: Ändern von Daten über das Web, Suche während des Tippens (HTMX),
  QR-Etiketten, HTTPS.

### Mobile App = Web-Oberfläche (D8)

Die mobile App ist die Web-Oberfläche des Servers, zuerst fürs Handy gestaltet. Es gibt
keine eigene Android- oder iOS-App.

- Handy und PC nutzen dieselbe Seite; es gibt nur einen Code.
- Kein App-Store, keine App-Werkzeuge: Das Handy öffnet die Adresse des Servers im WLAN.
- PDFs öffnet der Handy-Browser direkt.
- Ein QR-Etikett enthält nur die Adresse der Bauteilseite; die normale Kamera-App öffnet sie.

Einschränkung: Ein Kamera-Scanner innerhalb der Seite und das Installieren auf dem
Startbildschirm (PWA) verlangen im Browser eine verschlüsselte Verbindung (HTTPS). Im
reinen WLAN-Betrieb ohne HTTPS geht beides nicht; das Scannen mit der normalen Kamera-App
funktioniert trotzdem. HTTPS ist deshalb ein eigener, späterer Schritt in Phase 3.
Falls später doch eine echte App gewünscht ist, lässt sich die Web-Oberfläche in eine
App-Hülle einbetten.

### Was MCP ist

MCP („Model Context Protocol“) ist ein offener Standard, über den ein KI-Assistent wie
LM Studio feste Funktionen eines anderen Programms aufrufen kann. Für das Lager ist das
ein kleines Zusatzprogramm mit Funktionen wie „Bauteil suchen“ oder „Bauteil anlegen“.
Der Agent kann dann nur tun, was diese Funktionen erlauben, und die Eingaben werden
geprüft. Ein Agent mit Terminalzugriff kann dasselbe schon über die CLI mit `--json`.

## 8. Technologie-Entscheidung

**Entscheidung D1: Python 3.11+ (Typer, PyYAML; später FastAPI, SQLite, Jinja2+HTMX).**
Von Lukas am 2026-11-12 bestätigt, nach einer zweiten Prüfung von C++.

C++ wurde geprüft und verworfen:

| Kriterium | Python | C++ |
|---|---|---|
| Laufzeit | venv nötig (oder PyInstaller) | keine, Single-Binary |
| Entwicklungsgeschwindigkeit | hoch | ~3–5× langsamer |
| Web/API | FastAPI + OpenAPI aus der Box | Crow/httplib, OpenAPI selbst bauen |
| YAML/JSON | PyYAML, stdlib | yaml-cpp, nlohmann/json (extern) |
| SQLite | stdlib | Amalgamation einbinden |
| QR + PDF-Etiketten | qrcode, reportlab | qrcodegen, PDF-Bibliothek extra |
| MCP-Server | fertige SDKs | JSON-RPC selbst implementieren |
| Wartbarkeit durch AI-Agenten | sehr gut (viel Trainingsmaterial) | schlechter (mehr Boilerplate) |
| Performance | für 10³–10⁶ Teile völlig ausreichend | Overkill |

C++ ist machbar (Crow + SQLite + yaml-cpp + qrcodegen) und brächte ein Single-Binary,
kostet aber deutlich Entwicklungsaufwand und erschwert genau die Punkte, die im
Vordergrund stehen: Erweiterbarkeit und AI-Pflege. Alle Dateiformate (Ordner, YAML,
SQLite) sind sprachunabhängig — bei einem späteren Wechsel würde nur `src/` neu
geschrieben, die Daten nicht.

Ergänzungen aus der zweiten Prüfung (2026-11-12):

- Für C++ gibt es kein offizielles MCP-SDK, nur Community-Bibliotheken.
- OpenAPI aus dem Code erzeugt in C++ nur oatpp; sonst wird die Beschreibung von Hand gepflegt.
- Umlaute unter Windows (Pfade, Konsole, Argumente) müssen in C++ von Hand auf UTF-8 gebracht werden.
- Der Entwicklungsrechner ist nicht schwach (Ryzen 9, 31 GB RAM). Die Leistung der Hardware
  ist kein Argument für oder gegen eine der beiden Sprachen.
- Lokale Agenten (LM Studio) pflegen künftig nur die Daten über CLI/MCP, nicht den Code.

### Sprachneutrale Datenhaltung (D6)

Python ist die Sprache des Programms, nicht der Daten. Für alles, was auf der Platte
landet oder über eine Schnittstelle geht, gilt:

- **SQLite-Schema als reines SQL** in einer eigenen Datei (`schema.sql`), nicht aus einem
  ORM erzeugt. Keine ORM-Hilfstabellen.
- **Nur Standardtypen:** `TEXT` (UTF-8), `INTEGER`, `REAL`. Zeitpunkte als ISO-8601-Text
  in UTC (`2026-11-12T14:03:00Z`), Wahrheitswerte als `0`/`1`.
- **Listen** (Aliase, Tags) als eigene Tabellen. Keine serialisierten Python-Objekte:
  kein `pickle`, kein `repr()`.
- **Schema-Version** in `PRAGMA user_version`; Schemaänderungen als nummerierte `.sql`-Dateien.
- **Regeln in der Datenbank**, wo möglich (`NOT NULL`, `CHECK`, `FOREIGN KEY`), damit sie
  auch für andere Programme gelten.
- **YAML ohne sprachspezifische Tags** (nur `safe_load`/`safe_dump`), JSON nach Standard.
- **Volltextsuche**, falls nötig, über das in SQLite eingebaute FTS5.

Prüfstein: Die Datenbank muss sich mit dem `sqlite3`-Kommandozeilenprogramm oder einem
beliebigen SQLite-Browser vollständig lesen und sinnvoll bearbeiten lassen.

## 9. Linux-Kompatibilität (von Tag 1)

- `pathlib` für alle Pfade
- normalisierte Ordnernamen (Groß-/Kleinschreibung fix) → case-sensitive FS ok
- keine Windows-APIs; SQLite/YAML/FastAPI plattformunabhängig
- Root-Pfad pro System neu setzen (`lager root set`)

## 10. Roadmap

| Phase | Inhalt | Status |
|---|---|---|
| 0.1 | Konfiguration, bewegbarer Root, Auto-Erkennung, Kategorien, part.yaml, CLI-Grundgerüst, Tests | ✅ |
| 0.2 | SQLite-Index über Bauteile und ihre Dateien (Datenblätter) + `lager index rebuild` | ✅ |
| 1 | Suche und Datenblätter in der CLI: Bauteil suchen, Dateien anzeigen, neues Datenblatt einem Bauteil zuordnen | Grundgerüst: Suche fertig (`lager part search`). Offen: Datenblatt zuordnen, Suche in Dateinamen |
| 2 | REST-API (FastAPI, OpenAPI) + Web-Oberfläche fürs Handy: Suche → Bauteilseite → PDF öffnen | Grundgerüst: API, Dateiauslieferung, Suche und Bauteilseite laufen (`lager serve`). Offen: am echten Handy im WLAN prüfen, Daten ändern, Suche beim Tippen |
| 3 | Handy-Komfort: QR-Etiketten (PDF); später HTTPS mit Kamera-Scanner und Startbildschirm (PWA) | offen |
| 4 | MCP-Server für die Datenpflege durch lokale Agenten | offen |
| 5 | Mengen ein- und ausbuchen mit Verlauf (`movements`) | offen |
| 6 | Linux-Härtung, Packaging, Backup | offen |

Die Reihenfolge folgt den Prioritäten aus §1 und wurde am 2026-11-12 neu geordnet (D7).
Vorher standen Mengenbuchungen und MCP vor der Handy-Nutzung.

## 11. Entscheidungsprotokoll

| ID | Datum | Entscheidung |
|---|---|---|
| D1 | 2026-11-09 | Tech-Stack Python (C++ geprüft, verworfen — Begründung s. o.) |
| D2 | 2026-11-11 | `lager_root` in `config.yaml`, Auto-Erkennung, validierte Struktur |
| D3 | 2026-11-11 | Kategorien in `categories.yaml`, anlegbar per CLI/Agent, nichts hardcodiert |
| D4 | 2026-11-11 | part.yaml-Schema v1 (s. o.); Kategorie kommt aus dem Pfad |
| D5 | 2026-11-11 | Ordner mit `_`/`.`-Präfix werden vom Scanner ignoriert |
| D1 | 2026-11-12 | Python von Lukas bestätigt (C++ ein zweites Mal geprüft, verworfen) |
| D6 | 2026-11-12 | Sprachneutrale Datenhaltung: Datenbank und Dateien ohne Python-Spezifisches (s. §8) |
| D7 | 2026-11-12 | Prioritäten: private Nutzung; Datenblätter finden und einlesen vor Mengen; Roadmap neu geordnet (s. §1, §10) |
| D8 | 2026-11-12 | Mobile App = Web-Oberfläche des Servers, zuerst fürs Handy gestaltet; keine eigene App (s. §7) |
| D9 | 2026-11-12 | Index in `<lager_root>/.lager/parts.db`; Neuaufbau in einer Transaktion; Warnungen statt Abbruch; Dateiarten einstellbar; IDs nicht stabil (s. §6a) |
| D10 | 2026-11-12 | CLI (`--json`) und REST-API geben dieselben Daten aus; Datensätze mit englischen Feldnamen, Rahmenfelder deutsch (s. §7) |
