# HANDOVER — Bauteile-Lagersystem „Lager“

**Stand:** 2026-11-26, Version 0.7.0
**Zuletzt bearbeitet von:** Claude Opus 5.5 (Claude Code), vorher Claude Fable 5.2
**Vorgeschichte:** begonnen von einem lokalen LM-Studio-Agenten am 2026-11-11; die ganze Historie steht in Git.

Dieses Dokument beschreibt den aktuellen Zustand. Regeln und Befehle in Kurzform stehen in
[CLAUDE.md](CLAUDE.md), Konzept und Entscheidungen (D1–D24) in [KONZEPT.md](KONZEPT.md).

---

## 0. Einstieg für den nächsten Agenten

**Der Stand ist abgeschlossen:** Alles bis Version 0.7.0 ist committet und auf `main` gepusht.
Es gibt keine angefangene Arbeit. 0.7.0 setzt Lukas' Rückmeldung zu 0.6.0 um (eigene Knöpfe,
Papierkorb-Seite, `config.yaml` lokal); seine Rückmeldung dazu ist der wahrscheinlichste
nächste Auftrag.

**In dieser Reihenfolge lesen:** `CLAUDE.md` (Regeln, Befehle, Stolpersteine), dieses Dokument,
dann von `KONZEPT.md` nur die Abschnitte, die zur Aufgabe gehören (§3 Ordner, §5 Kategorien,
§6a Index, §6b Verwalten, §6c Etiketten, §7 Server, §11 Entscheidungen).

**Die ersten Minuten:**

```bat
git status --short
.venv\Scripts\python.exe -m pytest tests -q
```

- `pytest` muss 342 bestandene Tests melden. Wenn nicht, zuerst das klären.
- `git status` zeigt zwei Einträge, die **absichtlich nicht eingecheckt** sind und so bleiben,
  bis Lukas entscheidet (§10): `lager/categories.yaml` (geändert) und `lager/microcontroller/`
  (neu). Nicht committen, nicht zurücksetzen, nicht löschen. Die `config.yaml` taucht nicht
  mehr auf: Sie steht seit 0.7.0 in `.gitignore` (D23).

**Drei Dinge, die hier leicht schiefgehen:**

1. **Die `config.yaml` im Projekt zeigt auf das Lager von Lukas** (laut Lukas derzeit ein
   Test-Lager, trotzdem seine Daten). Jeder schreibende
   `lager`-Befehl im Projektordner (`part new`, `part remove`, `part rename`, `category add` …)
   und jeder `lager serve` ändert also echte Daten. Zum Ausprobieren deshalb nur lesende
   Befehle nehmen (`status`, `part search`, `part show`, `index status`), sonst die Tests oder
   das Wegwerf-Lager aus `tools/demo_server.py` (§7a).
2. **Das Repository ist öffentlich.** Keine Rechnernamen, IP-Adressen, privaten Pfade, Tokens
   oder fremden Datenblätter in Code, Doku, Tests oder Commit-Nachrichten. Dateien einzeln
   vormerken (`git add <datei>`), nie `git add -A`.
3. **Vor jedem Commit fragen.** Zeigen, was geändert wurde, auf das Ja warten, dann committen
   und direkt auf `main` pushen.

**So wurde bisher gearbeitet** (hat sich bewährt): Kern in `src/lager/*.py` zuerst, mit Tests;
dann CLI und Server, die den Kern nur aufrufen; dann die Seiten; dann im Browser bei 375 px
ansehen und nachmessen; zuletzt `KONZEPT.md`, `HANDOVER.md` und `README.md` nachziehen. Bei
Unklarheit über Umfang oder Reihenfolge Lukas fragen statt raten.

**Was Lukas erwartet:** kurze, klare Antworten auf Deutsch; ehrlich gesagt, was geprüft ist
und was nicht; Entscheidungen, die er treffen muss, als konkrete Frage mit Vorschlag.

---

## 1. Worum es geht

Lukas verwaltet privat eine große Sammlung elektronischer Bauteile. Das System soll vor allem
**Datenblätter schnell finden und öffnen**, auch am Handy. Mengen sind nachrangig.

- Die **Ordnerstruktur ist die Quelle der Wahrheit**:
  `<lager_root>/<kategorie>/[<Unterkategorie>/]<Bezeichnung>/part.yaml` plus Dateien. Alles ist
  ohne das Programm im Explorer nutzbar.
- Ein **SQLite-Index** (`<lager_root>/.lager/parts.db`) ist daraus abgeleitet und dient der Suche.
- **CLI** (`lager`), **REST-API** und **Web-Seiten** nutzen denselben Kern und liefern dieselben Daten.
- **QR-Etiketten** an den Lagerplätzen öffnen am Handy die Seite des Bauteils.

## 2. Stand je Phase

| Phase | Inhalt | Stand |
|---|---|---|
| 0.1 | Konfiguration, beweglicher Lager-Ordner, Kategorien, `part.yaml`, CLI-Grundgerüst | fertig |
| 0.2 | SQLite-Index, `lager index rebuild` | fertig |
| 1 | Suche (auch in Dateinamen), Dateien aufnehmen, Datenblatt öffnen | fertig |
| 2 | Server: Suche (auch beim Tippen), Bauteilseite, Dateien, anlegen, bearbeiten, hochladen, Lager-Ordner ändern, Anmelden bei Schreibschutz | fertig; von Lukas am Handy geprüft |
| 3a | QR-Etiketten: Seite `/etiketten` (Druck auf A4), QR-Code auf der Bauteilseite, Adresse als Name, `lager qr url`, `lager qr make` | fertig; von Lukas geprüft: Das Handy liest den Code |
| – | Verwalten (0.6.0): freie Bezeichnungen, Unterkategorien, umbenennen, verschieben, löschen in den Papierkorb, Hochladen mit Fortschritt, Ordner-Auswahlfenster | fertig; von Lukas am PC ausprobiert: Umbenennen und Löschen gehen, den Papierkorb hat er nicht gefunden |
| – | Rückmeldung zu 0.6.0 (0.7.0): drei eigene Knöpfe mit neuem Design, eigene Seiten für Umbenennen und Löschen, Papierkorb-Seite mit Wiederherstellen, `config.yaml` lokal | fertig; von Lukas noch nicht ausprobiert |
| 3b | HTTPS mit Kamera-Scanner in der Seite und Startbildschirm | offen |
| 4 | MCP-Server für die Datenpflege durch lokale Agenten | offen |
| 5 | Mengen ein- und ausbuchen mit Verlauf | offen |
| 6 | Linux, Packaging, Backup | offen |

Zwei Ideen ohne festen Platz stehen in `KONZEPT.md` §10: (A) Bauteile automatisch ergänzen
lassen, (B) KiCad-Dateien als Bibliothek bereitstellen.

### Was in 0.5.0 bis 0.7.0 dazukam

- **0.5.0, QR-Etiketten (Phase 3a):** `labels.py`, Seite `/etiketten`, QR-Code auf der
  Bauteilseite, `server.public_url` mit Vorschlag und Prüfung, CLI-Gruppe `lager qr`.
- **0.6.0, Wünsche aus Lukas' erstem größeren Test:**
  - Bezeichnungen bleiben, wie sie eingegeben werden (Leerzeichen, Kleinbuchstaben; D17).
  - Unterkategorien beim Anlegen und Bearbeiten wählbar oder neu anlegbar (D18).
  - Bauteile umbenennen und verschieben; die alte Bezeichnung bleibt als Alias und ihre
    Adresse leitet weiter (D20).
  - Bauteile und einzelne Dateien löschen; beides wandert in `_papierkorb` (D19).
  - Hochladen startet gleich nach der Dateiauswahl, mit Fortschrittsbalken und Meldung;
    mehrere Dateien auf einmal.
  - „Ordner auswählen …“ beim Lager-Ordner öffnet das Auswahlfenster des Explorers (D21).
  - Etiketten: lange Bezeichnungen brechen auf bis zu drei Zeilen um; passt eine trotzdem
    nicht, weist die Seite darauf hin.
- **0.7.0, Rückmeldung von Lukas zu 0.6.0 (2026-11-26):**
  - Bauteilseite: drei eigene Knöpfe „Bearbeiten“, „Umbenennen“, „Löschen“ mit Symbolen
    (D24). Umbenennen und Löschen haben eigene Seiten; Löschen fragt auf einer eigenen Seite
    nach und nennt den Ort des Papierkorbs. Die Seite „Bearbeiten“ ändert nur noch Angaben
    und Ort.
  - Papierkorb-Seite `/papierkorb` mit vollem Pfad, Wiederherstellen und „Im Explorer
    öffnen“; Link im Fußbereich; die Meldung nach dem Löschen verlinkt darauf (D22). CLI:
    `lager trash list/restore/open`, API: `/api/v1/trash`. Anlass: Lukas hat den Ordner
    `_papierkorb` nicht gefunden; er lag im Lager-Ordner, nicht im Projektordner.
  - Fehler behoben: Zwei Löschungen in derselben Sekunde landeten im selben Zeit-Ordner.
  - `config.yaml` ist lokal (`.gitignore`), eingecheckt ist die Vorlage `config.example.yaml`
    (D23). Lukas: Die bisherige Konfiguration war nur zum Testen.

## 3. Arbeitsregeln

Sie stehen vollständig in `CLAUDE.md`. Die wichtigsten:

- **Vor jedem Commit fragen**; nach dem Ja committen und direkt auf `main` pushen.
- **Deutsch** für alles Sichtbare, englische Namen im Code.
- **Doku mitziehen** (`KONZEPT.md`, `HANDOVER.md`, bei neuen Befehlen auch `README.md`).
- **Tests müssen bestehen**, bevor etwas als fertig gilt. Sichtbares zusätzlich im Browser prüfen.
- **Nichts erfinden** (Bestände, Kennwerte, Datenblätter).
- **Nichts Privates ins öffentliche Repository:** keinen Rechnernamen, keine IP, keinen
  privaten Pfad in Code, Doku, Tests oder Commit-Nachrichten. Die `config.yaml` steht nicht in
  Git (D23).

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
| `lager category add/list/remove` | Kategorien; `list` zeigt auch die Unterkategorien |
| `lager part new "<TEIL>" -c <kategorie> [-s <Unterkategorie>] …` | Bauteil anlegen |
| `lager part edit <TEIL> --location … --quantity …` | Angaben ändern |
| `lager part rename <ALT> "<NEU>"` | umbenennen; die alte Bezeichnung wird Alias |
| `lager part move <TEIL> [-c <kategorie>] [-s <Unterkategorie>]` | verschieben; `-s ""` = direkt in die Kategorie |
| `lager part remove <TEIL>` | Bauteil in den Papierkorb |
| `lager part show <TEIL>` | `part.yaml` und Dateien aus dem Ordner zeigen |
| `lager part search [begriff] [-c kategorie]` | im Index suchen |
| `lager part attach <TEIL> <datei>… [--move]` | Dateien aufnehmen |
| `lager part detach <TEIL> <datei>…` | Dateien in den Papierkorb |
| `lager part open <TEIL> [--file PFAD \| --folder]` | Datenblatt, Datei oder Ordner öffnen |
| `lager index rebuild`, `lager index status` | Index neu aufbauen, Zustand zeigen |
| `lager qr url [ADRESSE]` | Adresse der QR-Codes zeigen (mit Vorschlag) oder speichern |
| `lager qr make <TEIL>… [--format svg\|png] [--out ORDNER] [--url BASIS]` | einzelne QR-Bilder schreiben |
| `lager trash list`, `lager trash restore <ID>`, `lager trash open` | Papierkorb ansehen, Eintrag zurückholen, Ordner im Explorer öffnen |
| `lager serve [--host H] [--port P]` | Web-Server starten; fürs Handy `--host 0.0.0.0` |

Jeder Befehl kennt `--json`. Fehler: Exit-Code ungleich 0 und deutsche Meldung auf stderr.

## 5. Aufbau des Codes

```
src/lager/
  config.py         config.yaml laden; set_lager_root und set_public_url ändern nur ihre Zeile;
                    ensure_config_file legt eine fehlende config.yaml aus der Vorlage an
  root.py           Lager-Ordner erkennen und prüfen; create_structure legt ein leeres Lager an
  names.py          Regeln für Ordnernamen (Bezeichnungen, Unterkategorien): clean, check
  categories.py     categories.yaml; normalize_id; Unterkategorien: normalize_subcategory,
                    subcategory_dir (vorhandene Ordner ohne Rücksicht auf Groß/Klein), subcategories
  parts.py          create_part, update_part, move_part (umbenennen, verschieben), delete_part,
                    find_part_dir, location_of
  files.py          Dateien aufnehmen (nach Art einsortieren, nie überschreiben); remove_file
  trash.py          Papierkorb: move_to_trash verschiebt nach <root>/_papierkorb/<Zeit>/<Pfad>;
                    entries, find_entry, restore_problem, restore; local_time für die Anzeige
  labels.py         QR-Etiketten: Adresse (Vorschlag, Prüfung), QR-Code, Text einpassen, A4-Seiten
  dialogs.py        pick_folder: Ordner-Auswahlfenster als eigener Prozess; reveal: Ordner im Explorer
  folder_dialog.py  das Auswahlfenster selbst (python -m lager.folder_dialog, tkinter)
  schema.sql        Schema des Index, reines SQL
  db.py             Index öffnen, Schema anlegen, Version prüfen
  indexer.py        Ordner einlesen (scan), Index aufbauen (rebuild), status, ensure_index
  search.py         search, get_part, find_by_alias, list_categories, find_file — einfache dicts
  cli.py            alle Befehle (Typer); main() stellt die Ausgabe auf UTF-8
  server/
    app.py          FastAPI: REST-API (/api/v1), /files, Seiten; create_app(root, cfg, config_path, bind_host)
    schemas.py      Antwort- und Eingabe-Formate der API
    templates/      base, index, _results (Trefferliste), part, new, edit, rename, delete, trash,
                    _subcategory, _icons (Symbole als SVG), labels, login
    static/         style.css, app.js (Suche beim Tippen, Unterkategorien, Hochladen mit
                    Fortschritt, Rückfrage vor dem Löschen, Ordner-Auswahl)
tests/
  conftest.py            Test-Lager (lager_voll), Test-Browser (client, phone, geschuetzt), Test-Netz (netz),
                         Sperre für echte Fenster (keine_fenster)
  test_core.py           Lager-Ordner, Kategorien, Bauteile, config
  test_index.py          Index und Suche
  test_files.py          Dateien aufnehmen, eindeutige Bezeichnung, Pfad in config.yaml
  test_cli.py            CLI: UTF-8, Index, Suche, attach, open
  test_server.py         Server lesend
  test_server_write.py   Server schreibend: anlegen, hochladen, Lager-Ordner, Rückmeldung
  test_phase2.py         bearbeiten (Kern, CLI, Web, API), Suche beim Tippen, Anmelden
  test_labels.py         QR-Etiketten: Adresse, Größen, QR-Code, Text, Seiten, Seite /etiketten, CLI
  test_manage.py         freie Bezeichnungen, Unterkategorien, umbenennen, verschieben, löschen,
                         Knöpfe der Bauteilseite, Meldungen beim Hochladen, Ordner-Auswahl
  test_trash.py          Papierkorb: Inhalt, Wiederherstellen, Seiten, API, CLI
tools/
  demo_server.py         Wegwerf-Lager mit Server für Sichtprüfungen im Browser (§7a)
lager/                   Beispiel-Lager (liegt im öffentlichen Repository)
config.example.yaml      Vorlage (in Git): lager_root, server.host/port/public_url, write_token, file_kinds
config.yaml              Einstellungen dieses Rechners (nicht in Git, wird aus der Vorlage angelegt)
```

## 6. Verträge

Ändern nur mit Eintrag in `KONZEPT.md` und hier.

- **Ordner:** `<root>/categories.yaml`, `<root>/<kategorie>/[<Unterkategorie>/…]<Bezeichnung>/part.yaml`.
  Ordner mit Präfix `_` oder `.` ignoriert der Scanner (`_vorlage`, `_papierkorb`, `.lager`).
  Dateien: PDFs direkt im Bauteil-Ordner, `3d/`, `kicad/`, `images/` für die anderen Arten.
- **Bezeichnung (D17):** so, wie sie eingegeben wurde; gültiger Ordnername unter Windows und Linux
  (`names.check`); im ganzen Lager eindeutig ohne Rücksicht auf Groß/Klein (D11). Sie ist der
  Ordnername und die Adresse `/p/<Bezeichnung>` (in Adressen kodiert, Leerzeichen als `%20`).
- **Kategorie-ID:** `a-z 0-9 -`. **Unterkategorie (D18):** Ordner in der Kategorie, Name =
  Anzeigename, bis zu 3 Ebenen. Beides kommt aus dem Pfad und steht nie in der `part.yaml`.
- **`part.yaml` (v1):** `part`, `name`, `manufacturer`, `aliases[]`, `quantity`, `unit`, `location`,
  `tags[]`, `notes`. Unbekannte Einträge bleiben beim Bearbeiten erhalten.
- **Umbenennen (D20):** Die alte Bezeichnung kommt in `aliases`; `/p/<alt>` leitet auf die neue
  Seite weiter, wenn genau ein Bauteil diesen Alias trägt (`search.find_by_alias`).
- **Löschen (D19):** nie endgültig, immer nach `_papierkorb/<JJJJMMTTTHHMMSSZ>/<Pfad im Lager>`.
  Jedes Löschen bekommt einen eigenen Zeit-Ordner (in derselben Sekunde mit `-2`, `-3`, …),
  darin genau ein Eintrag: ein Bauteil-Ordner oder eine Datei.
- **Papierkorb lesen (D22):** Die ID eines Eintrags ist der Name seines Zeit-Ordners. Der Weg
  vom Zeit-Ordner zum Eintrag besteht aus Ordnern mit genau einem Inhalt; ein Ordner mit
  `part.yaml` ist ein Bauteil, eine Datei am Ende eine Datei. Leere oder von Hand vermischte
  Zeit-Ordner werden übersprungen. Wiederherstellen schreibt nie über etwas: Fehlt der Platz
  oder ist die Bezeichnung vergeben, gibt es einen Grund statt einer Änderung.
- **Konfiguration (D23):** `config.yaml` ist je Rechner und steht nicht in Git; Vorlage ist
  `config.example.yaml`.
- **Index:** Tabellen `meta`, `categories`, `parts`, `part_aliases`, `part_tags`, `files`. Ein
  Neuaufbau leert und füllt sie in einer Transaktion. `parts.id` ist nicht stabil; dauerhafte
  Verweise nutzen `parts.rel_path`. `meta.generator` nennt die Programmversion; passt sie nicht,
  baut `ensure_index` neu auf. Das Schema ist seit 0.2 unverändert (Version 1).
- **JSON (D10):** Datensätze mit englischen Feldnamen (`part`, `name`, `category`, `subcategory`,
  `path`, `files[path, kind, ext, size, mtime]`), Rahmenfelder deutsch (`suche`, `anzahl`,
  `treffer`, `teile`, `dateien`, `warnungen`, `geloescht`, `papierkorb`).
- **Server-Routen:** lesend `/`, `/suche`, `/p/<teil>`, `/p/<teil>/bearbeiten`,
  `/p/<teil>/umbenennen`, `/p/<teil>/loeschen` (Rückfrage), `/neu`, `/etiketten`, `/papierkorb`,
  `/anmelden`, `/files/<pfad>`, `/api/v1/{health,parts,parts/<teil>,categories,index,trash}`,
  `/docs`. Schreibend `POST /neu`, `POST /p/<teil>/bearbeiten`, `POST /p/<teil>/umbenennen`,
  `POST /p/<teil>/loeschen` (mit `sicher=1`), `POST /p/<teil>/dateien`,
  `POST /p/<teil>/dateien/loeschen`, `POST /papierkorb/wiederherstellen`, `POST /index/rebuild`,
  `POST /einstellungen/lager-ordner`, `POST /einstellungen/ordner-waehlen`,
  `POST /papierkorb/oeffnen`, `POST /etiketten/adresse`, `POST /anmelden`, `POST /abmelden`,
  `POST /api/v1/{parts,parts/<teil>/files,categories,index/rebuild,trash/<id>/restore}`,
  `PATCH /api/v1/parts/<teil>`, `DELETE /api/v1/parts/<teil>`,
  `DELETE /api/v1/parts/<teil>/files/<pfad>`.
- **Meldungen nach einer Aktion** stehen in der Adresse der Zielseite und werden nur gezeigt,
  wenn sie stimmen: `/?hinweis=eingelesen|ordner|geloescht&teil=…`,
  `/p/<teil>?hochgeladen=…&geloescht=…&frueher=…&wiederhergestellt=…`,
  `/etiketten?hinweis=adresse`, `/papierkorb?hinweis=explorer`. Nach dem Löschen steht unter
  der Meldung ein Link zum Papierkorb (`erfolg_link` im Seiten-Kontext).
- **QR-Code (D15, D16):** Inhalt `<server.public_url>/p/<Bezeichnung>`; ein Etikett je Bauteil.
- **Schutz (D13, D14):** `/files/…` liefert nur Dateien aus dem Index, SVG nur als Download. Ohne
  `write_token` ist Schreiben im WLAN offen. Mit Token: Kopffeld `X-Lager-Token` oder Anmeldung im
  Browser (Cookie `lager_token`). Lager-Ordner ändern, Ordner-Auswahlfenster, „Im Explorer
  öffnen“ und „Adresse merken“ gehen nur bei einem Aufruf vom Server-PC selbst (`is_local`).

## 7. Stolpersteine

- **Shell und Anführungszeichen:** Dateien mit dem Write-Werkzeug anlegen. `cat <<EOF` bricht bei
  Texten mit Apostroph oder Anführungszeichen ab; das gilt auch für Python-Schnipsel in der Shell.
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
- **`save_config`** schreibt die ganze `config.yaml` neu und verliert Kommentare. Für Lager-Ordner
  und QR-Adresse immer `set_lager_root` und `set_public_url` nehmen.
- **Pfade unter Windows vergleichen:** `Path("a/IRF") == Path("a/irf")` ist dort wahr. Wo die
  Schreibweise zählt (Umbenennen nur in Groß/Klein), als Text vergleichen (`parts.move_part`).
- **Geöffnete Dateien:** Windows verschiebt keinen Ordner, aus dem eine Datei geöffnet ist.
  `move_part`, `delete_part` und `remove_file` melden das als Fehler und ändern nichts.
- **Kein echtes Netz und kein echtes Fenster in Tests:** Die Fixture `netz` ersetzt Rechnername,
  IP und Namensauflösung. Die Fixture `keine_fenster` (beide in `conftest.py`, für jeden Test)
  lässt jeden Test scheitern, der `dialogs._run_dialog` oder `dialogs.reveal` wirklich aufrufen
  würde. Wer sie braucht, ersetzt sie im Test durch eine Attrappe (Beispiel: Fixture `opened`
  in `test_trash.py`).
- **Explorer-Fenster kommen nicht nach vorn:** Windows lässt den Server (ein Programm im
  Hintergrund) kein Fenster vor den Browser holen. „Im Explorer öffnen“ öffnet das Fenster,
  es liegt aber oft dahinter; die Meldung sagt das. Das Ordner-Auswahlfenster ist davon nicht
  betroffen, weil es selbst „zuoberst“ angelegt wird.
- **`config.yaml` ist nicht mehr in Git:** Ein `git pull` in einem anderen Klon, in dem sie noch
  eingecheckt war, löscht dort die (unveränderte) Datei; das Programm nimmt dann die
  Standardwerte und legt sie beim nächsten Speichern aus der Vorlage neu an. Lukas hat einen
  zweiten, älteren Klon neben dem Projektordner.
- **Reihenfolge von Ordnern:** Windows sortiert Pfade ohne Rücksicht auf Groß/Klein, Linux nicht.
  Wo die Reihenfolge sichtbar ist, ausdrücklich sortieren (`categories.subcategories`).
- **Etiketten-Text:** Die Breite der Schrift wird geschätzt (`labels.CHAR_WIDTH`), nicht
  gemessen. Wer an `fit_text` ändert, misst das Ergebnis im Browser nach (Breite der Zeilen
  gegen die Breite des Textkastens).

## 7a. Im Browser prüfen, ohne das echte Lager anzufassen

```bat
.venv\Scripts\python.exe tools\demo_server.py
```

Das Skript legt in einem neuen Temp-Ordner ein kleines Lager mit eigener `config.yaml` an
(drei Kategorien, zehn Bauteile, darunter Bezeichnungen mit Leerzeichen und zwei
Unterkategorien) und startet den Server auf `http://127.0.0.1:8765`. Mit `--host 0.0.0.0`
ist er auch vom Handy erreichbar, mit `--port` auf einem anderen Port.

Für den Browser-Bereich der Claude-App gehört dazu eine `.claude/launch.json` (steht in
`.gitignore`, wird also nicht eingecheckt):

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "lager-demo",
      "runtimeExecutable": ".venv/Scripts/python.exe",
      "runtimeArgs": ["tools/demo_server.py", "--port", "8765"],
      "port": 8765
    }
  ]
}
```

Was sich bewährt hat:

- **Handy-Breite 375 px einstellen** und je Seite prüfen, dass nichts seitlich überläuft
  (`document.documentElement.scrollWidth - window.innerWidth` muss 0 sein).
- **Nachmessen statt nur ansehen:** Bildschirmfotos des Browser-Bereichs schlagen manchmal
  fehl. Verlässlich ist, das Ergebnis im Seiteninhalt abzufragen (Texte, Adressen, Maße).
- **Dateiauswahl nachstellen:** Ein Dateifeld lässt sich per Skript füllen
  (`DataTransfer` mit `File`-Objekten, dann ein `change`-Ereignis auslösen). So wurde das
  Hochladen mit Fortschritt geprüft.
- **Druckbild der Etiketten:** Edge ohne Fenster mit `--headless --print-to-pdf=…` erzeugt
  das PDF, wie es der Druckdialog täte.
- **Nach Code-Änderungen den Test-Server neu starten.**
- **Das Ordner-Auswahlfenster** erscheint beim Prüfen wirklich auf dem Bildschirm von Lukas.
  Nur prüfen, wenn es nötig ist, und das Fenster danach wieder schließen.

## 8. Geprüft und nicht geprüft

- **Geprüft:** `pytest` → 342 Tests bestehen (Kern 15, CLI 16, Index 26, Dateien 26, Server lesend
  20, Server schreibend 32, Phase 2 19, Etiketten 90, Verwalten 78, Papierkorb 20).
- **Im Browser geprüft für 0.7.0 (375 px und 900 px, hell und dunkel, Wegwerf-Lager):** drei
  Knöpfe auf der Bauteilseite (am Handy 109 px breit, Symbol über dem Wort, nichts läuft über;
  breit nebeneinander), Umbenennen mit Meldung, Rückfrage-Seite und Löschen mit Link zum
  Papierkorb, Datei löschen, Papierkorb-Seite mit zwei Einträgen, Wiederherstellen von Bauteil
  und Datei mit Meldung, Zahl der Einträge im Fußbereich. „Im Explorer öffnen“ einmal echt
  ausgelöst: Das Fenster öffnet den richtigen Ordner, liegt aber hinter dem Browser.
- **Im Browser geprüft (375 px Breite, Wegwerf-Lager):** neues Bauteil mit Unterkategorie (die
  Auswahl folgt der Kategorie), Bauteilseite, Hochladen gleich nach der Auswahl mit laufendem
  Balken (60-MB-Datei) und Meldung, Fehlerfall leere Datei, Datei löschen mit Rückfrage,
  Umbenennen und Verschieben mit Meldung, alte Adresse leitet weiter, Bauteil löschen,
  Etiketten-Seite (kein Überlauf; alle Bezeichnungen passen bei „Klein“ und „Mini“ in ihren
  Kasten). Das Ordner-Auswahlfenster öffnet sich über den anderen Fenstern; Abbrechen und
  Auswahl kommen im Eingabefeld an.
- **Von Lukas am Handy geprüft (Stand 0.5.0):** Seiten öffnen, PDF öffnen, QR-Code lesen.
- **Nicht geprüft:** 0.7.0 bei Lukas und am echten Handy; die Funktionen aus 0.6.0 am echten Handy; die Dateiauswahl über den echten
  Dateidialog (nur per Skript ausgelöst); Umbenennen oder Löschen, während eine Datei des
  Bauteils geöffnet ist (die Fehlermeldung ist vorgesehen, aber nicht ausgelöst worden); ein
  Ausdruck auf Papier mit den neuen dreizeiligen Bezeichnungen; das Auswahlfenster unter Linux;
  ein Lager mit mehreren tausend Bauteilen; Linux insgesamt.

### Bekannte Grenzen

Nichts davon ist ein Fehler im heutigen Gebrauch; es sind die Stellen, an denen ein größeres
Lager oder ein neuer Wunsch zuerst anstößt.

- **Jede Änderung liest das ganze Lager neu ein** (`_rebuild` im Server, `_refresh_index` in
  der CLI). Bei zehn Bauteilen dauert das Millisekunden; bei mehreren tausend, besonders auf
  einem Netzlaufwerk, wird es spürbar. Abhilfe: nur das geänderte Bauteil im Index ersetzen.
- **`parts.find_part_dir` durchsucht die Ordner** (`rglob`) statt den Index zu fragen. Gleiche
  Folge bei großen Lagern.
- **Groß/Klein in der Suche nur für ASCII:** SQLite kennt `lower()` und `COLLATE NOCASE` nur
  für A–Z. Der Suchtext wird in Python kleingeschrieben und findet Umlaute; die Adresse
  `/p/<Bezeichnung>` findet eine Bezeichnung mit Umlaut aber nur in genau ihrer Schreibweise.
- **Die Schriftbreite auf Etiketten ist geschätzt**, nicht gemessen (`labels.CHAR_WIDTH`).
  Die Schätzung ist vorsichtig; sehr breite Zeichenfolgen könnten trotzdem knapp werden.
- **Hochladen:** höchstens 200 MB je Datei, alle Dateien einer Auswahl in einer Anfrage.
  Bricht die Verbindung ab, ist nichts gespeichert. Beim Anlegen eines Bauteils (`/neu`)
  gibt es noch keinen Fortschrittsbalken.
- **Das Ordner-Auswahlfenster belegt einen Arbeitsfaden des Servers**, solange es offen ist
  (höchstens zehn Minuten), und es kann immer nur eines offen sein.
- **Kein Schutz gegen fremde Webseiten (CSRF)** und ohne `write_token` kein Schutz im WLAN.
  Für das private Netz so entschieden (D13); vor einem Betrieb außerhalb davon neu bewerten.
- **Der Vorschlag für die QR-Adresse** wird einmal je Serverstart ermittelt.
- **Papierkorb:** wächst, bis Lukas ihn im Explorer leert. Endgültig löschen gibt es im
  Programm bewusst nicht. Eine Datei kommt nur in den alten Bauteil-Ordner zurück; wurde das
  Bauteil inzwischen umbenannt oder verschoben, steht am Eintrag, dass es im Explorer geht.
- **Der Fußbereich zählt den Papierkorb bei jedem Seitenaufruf** (ein Blick in die Zeit-Ordner).
  Bei sehr vielen Einträgen ließe sich das zwischenspeichern.

## 9. Nächste Schritte

In dieser Reihenfolge, jeweils erst nach Absprache mit Lukas. Zu jedem Punkt steht, woran
man erkennt, dass er fertig ist.

1. **Rückmeldung von Lukas zu 0.7.0 einarbeiten.** Er probiert die Knöpfe und den Papierkorb
   an seinem Lager aus. Fertig, wenn er sie am PC und am Handy benutzt hat und nichts offen ist.
2. **Nur falls Lukas es möchte: endgültig löschen im Programm** (einzelne Einträge oder den
   ganzen Papierkorb). Nicht umkehrbar: nur mit ausdrücklicher Bestätigung auf einer eigenen
   Seite. Bis dahin geht es bewusst nur im Explorer (D22).
3. **Umgebungsvariable für eine andere `config.yaml`**, damit sich die CLI gefahrlos gegen ein
   Wegwerf-Lager ausprobieren lässt (heute zeigt die CLI im Projektordner immer auf Lukas'
   Lager). Fertig, wenn `tools/demo_server.py` und ein Test sie nutzen.
4. **Kategorien und Unterkategorien im Web verwalten:** umbenennen (Kategorie: nur der
   Anzeigename in `categories.yaml`; Unterkategorie: der Ordner), leere löschen. Eine
   Kategorie-ID zu ändern hieße, den Ordner umzubenennen; das ändert alle Pfade darunter und
   braucht eine eigene Entscheidung.
5. **Kleinigkeiten:** Fortschrittsbalken auch auf `/neu`; Favicon; Index nur für geänderte
   Bauteile aktualisieren (siehe „Bekannte Grenzen“), sobald ein Lager dafür groß genug ist.
6. **Phase 3b: HTTPS**, damit Kamera-Scanner in der Seite und Startbildschirm möglich werden.
   Vorher mit Lukas klären, wie das Zertifikat entstehen soll (selbst erzeugt und am Handy
   als vertrauenswürdig eingetragen, oder ein Rechner davor, der HTTPS übernimmt). Die schon
   gedruckten Etiketten zeigen auf `http://…`; eine Umstellung der Adresse macht sie ungültig,
   wenn `http` nicht weiter angeboten oder weitergeleitet wird.
7. **Phase 4 bis 6** und die Ideen A und B wie in `KONZEPT.md` §10 beschrieben.

## 10. Offene Fragen an Lukas

- **Test-Bauteile im Beispiel-Lager:** Unter `lager/microcontroller/` liegen drei Bauteile aus
  Lukas' Test, eines mit einem Datenblatt eines Herstellers. Sie sind nicht eingecheckt. Sollen
  sie ins Beispiel-Lager oder wieder weg?
- Soll das Gerät im Router nach dem Dienst heißen (z. B. `lager`), bevor viele Etiketten
  gedruckt werden?
- Soll der Server dauerhaft im WLAN lauschen (`server.host: "0.0.0.0"` in der `config.yaml`)?
- Auf welchem Gerät läuft der Server später (dieser PC oder ein eigener Linux-Rechner)?
- Endgültige Kategorien und ein Schema für Lagerfächer (z. B. „A-03-2“)?
- Soll es HTTPS geben (nötig für Kamera-Scanner und Startbildschirm)?

## 11. Daten im Beispiel-Lager

`lager/` enthält eingecheckt drei Test-Bauteile: `IRLZ44N`, `223-0.1W` und `BC525` (von Lukas
über das Web angelegt, Beschreibung „Transistor 42V 0,2A“). Für `BC525` wurde kein Datenblatt
gefunden; die Angaben sind deshalb nicht ergänzt. Mengen stehen auf 0. Nichts davon ist ein
echter Bestand. Lukas' eigenes Lager liegt außerhalb des Projektordners.
