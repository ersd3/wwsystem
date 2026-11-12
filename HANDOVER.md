# HANDOVER — Bauteile-Lagersystem „Lager“

**Stand:** 2026-11-12, Version 0.4.0
**Übergabe von:** Claude Fable 5.2 (Claude Code) **an:** den nächsten Claude-Agenten
**Vorgeschichte:** begonnen von einem lokalen LM-Studio-Agenten am 2026-11-11; die ganze Historie steht in Git.

Dieses Dokument beschreibt den aktuellen Zustand. Regeln und Befehle in Kurzform stehen in
[CLAUDE.md](CLAUDE.md), Konzept und Entscheidungen (D1–D14) in [KONZEPT.md](KONZEPT.md).

---

## 1. Worum es geht

Lukas verwaltet privat eine große Sammlung elektronischer Bauteile. Das System soll vor allem
**Datenblätter schnell finden und öffnen**, auch am Handy. Mengen sind nachrangig.

- Die **Ordnerstruktur ist die Quelle der Wahrheit**: `<lager_root>/<kategorie>/<BEZEICHNUNG>/part.yaml`
  plus Dateien. Alles ist ohne das Programm im Explorer nutzbar.
- Ein **SQLite-Index** (`<lager_root>/.lager/parts.db`) ist daraus abgeleitet und dient der Suche.
- **CLI** (`lager`), **REST-API** und **Web-Seiten** nutzen denselben Kern und liefern dieselben Daten.

## 2. Stand je Phase

| Phase | Inhalt | Stand |
|---|---|---|
| 0.1 | Konfiguration, beweglicher Lager-Ordner, Kategorien, `part.yaml`, CLI-Grundgerüst | fertig |
| 0.2 | SQLite-Index, `lager index rebuild` | fertig |
| 1 | Suche (auch in Dateinamen), Dateien aufnehmen, Datenblatt öffnen | fertig |
| 2 | Server: Suche (auch beim Tippen), Bauteilseite, Dateien, anlegen, bearbeiten, hochladen, Lager-Ordner ändern, Anmelden bei Schreibschutz | fertig; **am echten Handy im WLAN noch nicht geprüft** |
| 3 | QR-Etiketten (PDF), später HTTPS mit Kamera-Scanner und Startbildschirm | offen, **als Nächstes** |
| 4 | MCP-Server für die Datenpflege durch lokale Agenten | offen |
| 5 | Mengen ein- und ausbuchen mit Verlauf | offen |
| 6 | Linux, Packaging, Backup | offen |

Zwei Ideen ohne festen Platz stehen in `KONZEPT.md` §10: (A) Bauteile automatisch ergänzen
lassen, (B) KiCad-Dateien als Bibliothek bereitstellen.

## 3. Arbeitsregeln

Sie stehen vollständig in `CLAUDE.md`. Die wichtigsten:

- **Vor jedem Commit fragen**; nach dem Ja committen und direkt auf `main` pushen.
- **Deutsch** für alles Sichtbare, englische Namen im Code.
- **Doku mitziehen** (`KONZEPT.md`, `HANDOVER.md`, bei neuen Befehlen auch `README.md`).
- **Tests müssen bestehen**, bevor etwas als fertig gilt. Sichtbares zusätzlich im Browser prüfen.
- **Nichts erfinden** (Bestände, Kennwerte, Datenblätter).

## 4. Einrichten und Befehle

Python 3.14 ist für das Benutzerkonto installiert. Das venv liegt in `.venv` (nicht in Git).

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt -e .
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\lager.exe status
.venv\Scripts\lager.exe serve
```

| Befehl | Zweck |
|---|---|
| `lager status`, `lager init <pfad>`, `lager root set/unset/detect` | Lager-Ordner anzeigen, anlegen, einstellen |
| `lager category add/list/remove` | Kategorien |
| `lager part new <TEIL> -c <kategorie> …` | Bauteil anlegen |
| `lager part edit <TEIL> --location … --quantity …` | Angaben ändern |
| `lager part show <TEIL>` | `part.yaml` und Dateien aus dem Ordner zeigen |
| `lager part search [begriff] [-c kategorie]` | im Index suchen |
| `lager part attach <TEIL> <datei>… [--move]` | Dateien aufnehmen |
| `lager part open <TEIL> [--file PFAD \| --folder]` | Datenblatt, Datei oder Ordner öffnen |
| `lager index rebuild`, `lager index status` | Index neu aufbauen, Zustand zeigen |
| `lager serve [--host H] [--port P]` | Web-Server starten |

Jeder Befehl kennt `--json`. Fehler: Exit-Code ungleich 0 und deutsche Meldung auf stderr.

## 5. Aufbau des Codes

```
src/lager/
  config.py      config.yaml laden; set_lager_root ändert nur die eine Zeile (Kommentare bleiben)
  root.py        Lager-Ordner erkennen und prüfen; create_structure legt ein leeres Lager an
  categories.py  categories.yaml lesen und schreiben; normalize_id („Widerstände“ → widerstaende)
  parts.py       create_part, update_part, find_part_dir; Regeln für Bezeichnungen
  files.py       Dateien in Bauteil-Ordner aufnehmen (nach Art einsortieren, nie überschreiben)
  schema.sql     Schema des Index, reines SQL
  db.py          Index öffnen, Schema anlegen, Version prüfen
  indexer.py     Ordner einlesen (scan), Index aufbauen (rebuild), status, ensure_index
  search.py      search, get_part, list_categories, find_file — liefern einfache dicts
  cli.py         alle Befehle (Typer); main() stellt die Ausgabe auf UTF-8
  server/
    app.py       FastAPI: REST-API (/api/v1), /files, Seiten; create_app(root, cfg, config_path)
    schemas.py   Antwort- und Eingabe-Formate der API
    templates/   base, index, _results (Trefferliste), part, new, edit, login
    static/      style.css, app.js (Suche beim Tippen)
tests/
  conftest.py            Test-Lager (lager_voll) und Test-Browser (client, phone, geschuetzt)
  test_core.py           Lager-Ordner, Kategorien, Bauteile, config
  test_index.py          Index und Suche
  test_files.py          Dateien aufnehmen, eindeutige Bezeichnung, Pfad in config.yaml
  test_cli.py            CLI: UTF-8, Index, Suche, attach, open
  test_server.py         Server lesend
  test_server_write.py   Server schreibend: anlegen, hochladen, Lager-Ordner, Rückmeldung
  test_phase2.py         bearbeiten (Kern, CLI, Web, API), Suche beim Tippen, Anmelden
lager/                   Beispiel-Lager (liegt im öffentlichen Repository)
config.yaml              lager_root, server.host/port/public_url, write_token, optional file_kinds
```

## 6. Verträge

Ändern nur mit Eintrag in `KONZEPT.md` und hier.

- **Ordner:** `<root>/categories.yaml`, `<root>/<kategorie>/[<unterkategorie>/]<BEZEICHNUNG>/part.yaml`.
  Ordner mit Präfix `_` oder `.` ignoriert der Scanner. Dateien: PDFs direkt im Bauteil-Ordner,
  `3d/`, `kicad/`, `images/` für die anderen Arten.
- **Bezeichnung:** `A-Z 0-9 - _ . +`, groß, im ganzen Lager eindeutig (D11). Sie ist der Ordnername
  und die Adresse `/p/<BEZEICHNUNG>`.
- **Kategorie-ID:** `a-z 0-9 -`. Die Kategorie kommt aus dem Pfad und steht nie in der `part.yaml`.
- **`part.yaml` (v1):** `part`, `name`, `manufacturer`, `aliases[]`, `quantity`, `unit`, `location`,
  `tags[]`, `notes`. Unbekannte Einträge bleiben beim Bearbeiten erhalten.
- **Index:** Tabellen `meta`, `categories`, `parts`, `part_aliases`, `part_tags`, `files`. Ein
  Neuaufbau leert und füllt sie in einer Transaktion. `parts.id` ist nicht stabil; dauerhafte
  Verweise nutzen `parts.rel_path`. `meta.generator` nennt die Programmversion; passt sie nicht,
  baut `ensure_index` neu auf.
- **JSON (D10):** Datensätze mit englischen Feldnamen (`part`, `name`, `category`, `path`,
  `files[path, kind, ext, size, mtime]`), Rahmenfelder deutsch (`suche`, `anzahl`, `treffer`,
  `teile`, `dateien`, `warnungen`). CLI und API geben dieselben dicts aus.
- **Server-Routen:** lesend `/`, `/suche`, `/p/<teil>`, `/p/<teil>/bearbeiten`, `/neu`, `/anmelden`,
  `/files/<pfad>`, `/api/v1/{health,parts,parts/<teil>,categories,index}`, `/docs`. Schreibend
  `POST /neu`, `POST /p/<teil>/bearbeiten`, `POST /p/<teil>/dateien`, `POST /index/rebuild`,
  `POST /einstellungen/lager-ordner`, `POST /anmelden`, `POST /abmelden`,
  `POST /api/v1/{parts,parts/<teil>/files,categories,index/rebuild}`, `PATCH /api/v1/parts/<teil>`.
- **Schutz (D13, D14):** `/files/…` liefert nur Dateien aus dem Index, SVG nur als Download. Ohne
  `write_token` ist Schreiben im WLAN offen. Mit Token: Kopffeld `X-Lager-Token` oder Anmeldung im
  Browser (Cookie `lager_token`). Den Lager-Ordner ändert nur ein Aufruf vom Server-PC selbst.

## 7. Stolpersteine

- **Shell und Anführungszeichen:** Dateien mit dem Write-Werkzeug anlegen. `cat <<EOF` bricht bei
  Texten mit Apostroph oder Anführungszeichen ab.
- **Gesperrte `lager.exe`:** Läuft ein `lager serve`, scheitert `pip install -e .` am Starter. Der
  Import funktioniert danach trotzdem. Sauber: Server beenden, dann installieren.
- **Alter Stand im Browser:** Nach Code-Änderungen den Server neu starten. Geänderte CSS- oder
  JS-Dateien lädt der Browser erst nach einem harten Neuladen.
- **Leeres Dateifeld:** Browser schicken es als leeren Text; deshalb `FormFiles` in `app.py`.
- **SQLite und Threads:** Verbindung in der Route öffnen (`open_index`), nicht per `Depends`.
- **Echte `config.yaml`:** Server-Tests übergeben immer `config_path` aus der Fixture.
- **Pfadnamen in Tests:** Der Temp-Ordner enthält den Testnamen. Prüfungen wie
  `"bearbeiten" not in seite` schlagen deshalb fehl; auf genaue Stücke prüfen, etwa `href="…"`.
- **UTF-8:** `cli.main()` stellt stdout und stderr fest auf UTF-8, sonst kommen Umlaute bei
  umgeleiteter Ausgabe unter Windows kaputt an.
- **`save_config`** schreibt die ganze `config.yaml` neu und verliert Kommentare. Für den
  Lager-Ordner immer `set_lager_root` nehmen.

## 8. Geprüft und nicht geprüft

- **Geprüft:** `pytest` → 151 Tests bestehen (Kern 12, CLI 16, Index 26, Dateien 26, Server lesend 20,
  Server schreibend 32, Phase 2 19). Im Browser bei 375 px Breite mit einem Wegwerf-Lager: Suche,
  Suche beim Tippen, Bauteilseite, neues Bauteil, Dateien hochladen, bearbeiten, „Ordner neu
  einlesen“ mit Rückmeldung, „Lager-Ordner ändern“. `lager serve` echt gestartet.
- **Nicht geprüft:** Zugriff von einem echten Handy im WLAN (`lager serve --host 0.0.0.0`),
  Dateiauswahl über den Dateidialog des Browsers (nur per Skript), Anmelden im echten Browser (nur
  in Tests), `lager part open` mit echtem Standardprogramm (im Test abgefangen), ein Lager mit
  mehreren tausend Bauteilen, Linux.

## 9. Nächste Schritte

In dieser Reihenfolge, jeweils erst nach Absprache mit Lukas.

1. **Handy-Test mit Lukas (Akzeptanz Phase 2).** `lager serve --host 0.0.0.0`, am Handy
   `http://<IP-des-PCs>:8080`. Fertig, wenn Suche → Bauteilseite → PDF öffnen am Handy klappt.
   Gefundene Fehler beheben.
2. **Phase 3a: QR-Etiketten.** Befehl `lager qr print <TEIL>…` erzeugt ein PDF mit QR-Code zu
   `<server.public_url>/p/<BEZEICHNUNG>` und der Bezeichnung als Text. Vorher mit Lukas klären:
   Etikettengröße, Drucker, Wert für `public_url`. Fertig, wenn die Handy-Kamera vom Ausdruck die
   Bauteilseite öffnet. Neue Pakete (z. B. `qrcode`, `reportlab`) erst nach Rückfrage.
3. **Kleinere Lücken:** Bauteil löschen (nur mit ausdrücklicher Bestätigung, `--force`),
   umbenennen, in andere Kategorie verschieben; Favicon; Index nur für geänderte Bauteile
   aktualisieren, falls ein großes Lager das Einlesen langsam macht.
4. **Phase 3b: HTTPS**, damit Kamera-Scanner in der Seite und Startbildschirm möglich werden.
5. **Phase 4 bis 6** und die Ideen A und B wie in `KONZEPT.md` §10 beschrieben.

## 10. Offene Fragen an Lukas

- Wo soll das echte Lager liegen? Es soll später außerhalb des Projektordners laufen
  (`lager init D:\Lager` oder „Lager-Ordner ändern“ im Web).
- Auf welchem Gerät läuft der Server später im WLAN (dieser PC oder ein eigener Linux-Rechner)?
- Welche Adresse soll auf den QR-Etiketten stehen (`server.public_url`)?
- Endgültige Kategorien und ein Schema für Lagerfächer (z. B. „A-03-2“)?
- Soll es HTTPS geben (nötig für Kamera-Scanner und Startbildschirm)?

## 11. Daten im Beispiel-Lager

`lager/` enthält drei Test-Bauteile: `IRLZ44N`, `223-0.1W` und `BC525` (von Lukas über das Web
angelegt, Beschreibung „Transistor 42V 0,2A“). Für `BC525` wurde kein Datenblatt gefunden; die
Angaben sind deshalb nicht ergänzt. Mengen stehen auf 0. Nichts davon ist ein echter Bestand.
