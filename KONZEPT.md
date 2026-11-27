# Konzept — Bauteile-Lagersystem ("Lager")

Stand: 2026-11-27 · Version 0.7.0 · Status: Phase 0.1, 0.2, 1, 2 und 3a (QR-Etiketten) umgesetzt, dazu Verwalten mit Papierkorb; von Lukas am Handy geprüft (Seiten, PDF öffnen, QR-Code lesen) und am PC (Umbenennen, Löschen) · Als Nächstes: Automatisch ergänzen (§6d, geplant; Modelle getestet, Mouser-Schlüssel wartet auf Freigabe) · Stand je Phase: §10

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
├── _papierkorb/             # Gelöschtes, je Löschen ein Zeit-Ordner (§6b, D19, D22)
└── <kategorie>/             # Ebene 1 = Kategorie (Ordnername = id)
    └── <Unterkategorie>/    # optional, bis zu 3 Ebenen; Ordnername = Anzeigename
        └── <Bezeichnung>/   # Bauteil-Ordner, Name = Bezeichnung des Bauteils
            ├── part.yaml
            ├── datasheet.pdf   # (oder andere .pdf)
            ├── 3d/             # .step, .stp, .wrl, …
            ├── kicad/          # .kicad_mod, .kicad_sym, .kicad_pcb, …
            └── images/         # .png, .jpg
```

Namensregeln:

- Kategorie-`id`: `a-z 0-9 -` (Umlaute werden transliteriert: `Widerstände` → `widerstaende`)
- Bauteil-Bezeichnung (D17): bleibt so, wie sie eingegeben wurde, mit Groß- und Kleinbuchstaben,
  Leerzeichen und Umlauten, z. B. `IRLZ44N` oder `Arduino Mega 2560`. Erlaubt ist, was unter
  Windows und Linux ein Ordnername sein kann. Abgelehnt (nicht stillschweigend geändert) werden
  `< > : " / \ | ? *`, ein `_` oder `.` am Anfang, ein Punkt am Ende, Namen wie `CON` und mehr
  als 80 Zeichen. Nur überflüssige Leerzeichen fallen weg. Die Regeln stehen in `names.py`.
- Unterkategorie (D18): dieselben Regeln wie für die Bezeichnung; mehrere Ebenen mit `/`.
- Ordner mit Präfix `_` oder `.` werden vom Scanner ignoriert (intern/Reserve)
- Dateien werden automatisch nach Typ erkannt (Dateiendung) → keine manuelle Registrierung

## 4. Bewegbarer Root + Auto-Erkennung

`config.yaml` im Projektordner:

```yaml
lager_root: "lager"   # leer = Auto-Erkennung; relativ = zum Projektordner; absolut = direkt
```

**Jeder Rechner hat seine eigene `config.yaml` (D23).** Sie steht nicht in Git
(`.gitignore`). Eingecheckt ist die Vorlage `config.example.yaml` mit allen Einträgen und
Erklärungen. Fehlt die `config.yaml`, arbeitet das Programm mit Standardwerten (Lager-Ordner
über die Auto-Erkennung, also zuerst das Beispiel-Lager `lager/` im Projekt). Beim ersten
Speichern (`lager root set`, `lager init`, „Lager-Ordner ändern“, „Adresse merken“,
`lager qr url <adresse>`) legt das Programm sie als Kopie der Vorlage an; so bleiben die
Kommentare erhalten. Ein `git pull` kann die Einstellungen eines Rechners deshalb nie
überschreiben, und der spätere Server bekommt seine eigenen.

Auflösungsreihenfolge:

1. `lager_root` gesetzt und valid → wird verwendet (Quelle: `config`)
2. sonst Kandidaten: `<projekt>/lager/`, dann `~/lager/` (Quelle: `auto`)
3. Ein Kandidat ist **valid**, wenn er `categories.yaml` enthält (starker Marker)
   **oder** darunter `kategorie/<...>/part.yaml` existiert (Struktur passt)

Befehle: `lager init <pfad>`, `lager root set/unset/detect`, `lager status`.
Im Web steht der Lager-Ordner im Fußbereich jeder Seite und lässt sich dort ändern (§7).

**Echte Daten gehören nicht in den Projektordner.** Das Repository auf GitHub ist öffentlich,
und der Ordner `lager/` im Projekt ist das Beispiel-Lager, das mit eingecheckt wird. Das
eigene Lager liegt deshalb außerhalb, zum Beispiel unter `D:\Lager`.

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

### Unterkategorien (D18)

Eine Unterkategorie ist ein Ordner in einer Kategorie, der selbst kein Bauteil ist, zum
Beispiel `microcontroller/Shields/`. Es gibt dafür keine eigene Liste: Der Ordner ist die
Unterkategorie, und sein Name wird so angezeigt, wie er heißt.

- Anlegen: beim Anlegen oder Bearbeiten eines Bauteils im Feld „neue Unterkategorie“, in der
  CLI mit `lager part new … -s Shields` oder einfach als Ordner im Explorer.
- Auch eine leere Unterkategorie steht in der Auswahl (`lager category list`,
  `GET /api/v1/categories` → `subcategories`).
- Gibt es den Ordner schon in anderer Groß-/Kleinschreibung, wird der vorhandene genommen.
  So entstehen unter Linux nicht „Shields“ und „shields“ nebeneinander.
- Der Index führt die Unterkategorie je Bauteil im Feld `subcategory` (Pfad zwischen
  Kategorie und Bauteil); die Suche findet sie mit.

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

- `part` = Ordnername (kanonisch), in genau dieser Schreibweise
- Kategorie und Unterkategorie kommen aus dem Pfad → werden nicht doppelt gespeichert
- Nach einem Umbenennen steht die alte Bezeichnung in `aliases` (D20)
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
- **Wann der Index aktuell ist:** nach jedem `rebuild`, nach jedem ändernden Befehl der CLI
  (`part new/edit/rename/move/remove/attach/detach`, `category add/remove`; falls schon ein
  Index existiert), nach jeder Änderung im Web und bei jedem Start des Servers. Wer Dateien im Explorer ändert, liest danach neu
  ein: `lager index rebuild` oder Knopf „Ordner neu einlesen“ im Web.
- **Nach einem Programm-Update:** Der Index merkt sich, welche Version ihn aufgebaut hat
  (`meta.generator`). Passt sie nicht zur laufenden Version, wird er beim ersten Zugriff
  von selbst neu aufgebaut.
- **IDs sind nicht stabil:** `parts.id` wird bei jedem Neuaufbau neu vergeben. Dauerhafte
  Verweise (später `movements`) nutzen `parts.rel_path`.

Suche (`lager part search`, `/api/v1/parts`, Web): Jeder Begriff muss vorkommen, Groß- und
Kleinschreibung sowie Umlaute spielen keine Rolle, Teilwörter zählen (`44n` findet `IRLZ44N`).
Durchsucht werden Bezeichnung, Name, Hersteller, Aliase, Tags, Kategorie, Unterkategorie,
Lagerfach und die Dateinamen im Bauteil-Ordner (`pdf` findet also alle Bauteile mit PDF).
Vorn stehen Treffer, deren Bezeichnung der ganzen Eingabe entspricht oder mit ihr beginnt
(`arduino mega`), danach die, die mit dem ersten Begriff beginnen.

## 6b. Bauteile und Dateien verwalten (Phase 1, erweitert in 0.6.0 und 0.7.0 — umgesetzt)

Drei Wege führen zum selben Ergebnis im Ordner: die CLI, die Web-Oberfläche und der Explorer.

| Aufgabe | CLI | Web |
|---|---|---|
| Bauteil anlegen | `lager part new "<Bezeichnung>" -c <kategorie> [-s <Unterkategorie>] …` | Knopf „+“ oben, Formular „Neues Bauteil“ |
| Kategorie anlegen | `lager category add <id> --label "…"` | im Formular „Neues Bauteil“, Feld „neue Kategorie“ |
| Unterkategorie anlegen | `-s <Name>` bei `part new` oder `part move` | Felder „Unterkategorie“ und „neue Unterkategorie“ beim Anlegen und Bearbeiten |
| Dateien hinzufügen | `lager part attach <Bezeichnung> <datei> …` (`--move` verschiebt) | Bauteilseite, „Dateien hinzufügen“: lädt gleich nach der Auswahl hoch, mit Fortschrittsbalken |
| Datei löschen | `lager part detach <Bezeichnung> <datei> …` | Bauteilseite, Knopf „✕“ neben der Datei |
| Datenblatt öffnen | `lager part open <Bezeichnung>` (`--file`, `--folder`) | Knopf „PDF“ in der Trefferliste |
| Angaben ändern | `lager part edit <Bezeichnung> --location B-07 …` | Bauteilseite, Knopf „Bearbeiten“ |
| Umbenennen | `lager part rename <alt> "<neu>"` | Bauteilseite, Knopf „Umbenennen“ (eigene Seite) |
| In andere Kategorie oder Unterkategorie | `lager part move <Bezeichnung> -c <kategorie> -s <Unterkategorie>` | Seite „Bearbeiten“, Felder „Kategorie“ und „Unterkategorie“ |
| Bauteil löschen | `lager part remove <Bezeichnung>` | Bauteilseite, Knopf „Löschen“, dann Rückfrage „Ja, löschen“ |
| Papierkorb ansehen | `lager trash list` | Link „Papierkorb“ unten auf jeder Seite |
| Aus dem Papierkorb zurückholen | `lager trash restore <ID>` | Seite „Papierkorb“, Knopf „Wiederherstellen“ |
| Papierkorb im Explorer öffnen | `lager trash open` | Seite „Papierkorb“, Knopf „Im Explorer öffnen“ (nur am Server-PC) |

**Die Bauteilseite (D24)** zeigt unter der Bezeichnung drei gleich breite Knöpfe mit Symbol:
„Bearbeiten“, „Umbenennen“ und „Löschen“ (rot). Am Handy steht das Symbol über dem Wort, auf
breiten Bildschirmen daneben. Jeder Knopf führt auf eine eigene Seite: „Bearbeiten“ ändert die
Angaben und den Ort (Kategorie, Unterkategorie), „Umbenennen“ nur die Bezeichnung, „Löschen“
fragt nach und sagt, wohin das Bauteil kommt. Die Symbole sind eigene, einfache Zeichnungen
(`templates/_icons.html`), ohne zusätzliche Bibliothek.

Regeln:

- **Bezeichnung ist im ganzen Lager eindeutig (D11),** ohne Rücksicht auf Groß- und
  Kleinschreibung. Dieselbe Bezeichnung in zwei Kategorien wird abgelehnt, weil die Adresse
  `/p/<Bezeichnung>` und das QR-Etikett darauf zeigen.
- **Umbenennen und Verschieben (D20)** ändern den Ordner und die `part.yaml`; die Dateien
  ziehen mit. Die alte Bezeichnung kommt in die Aliase, und `/p/<alte Bezeichnung>` leitet
  auf die neue Seite weiter, solange nur ein Bauteil diesen Alias trägt. Ein schon gedrucktes
  QR-Etikett führt deshalb weiter zum Bauteil. Wechselt nur die Kategorie, landet das Bauteil
  direkt in der neuen Kategorie.
- **Löschen heißt in den Papierkorb (D19).** Ein gelöschtes Bauteil oder eine gelöschte Datei
  wird nach `<lager_root>/_papierkorb/<Zeitpunkt in UTC>/<derselbe Pfad wie im Lager>`
  verschoben und taucht in Suche und Index nicht mehr auf. Jedes Löschen bekommt einen eigenen
  Zeit-Ordner, auch zwei in derselben Sekunde (dann mit Nummer, `…Z-2`). Die `part.yaml`
  lässt sich nicht einzeln löschen. Ist eine Datei gerade geöffnet (etwa ein Datenblatt im
  PDF-Programm), lehnt Windows das Verschieben ab; das Programm meldet das und ändert nichts.
- **Der Papierkorb des Lagers ist nicht der Papierkorb von Windows.** Er ist ein Ordner im
  Lager. Damit man ihn findet, nennen ihn die Rückfrage vor dem Löschen und die Seite
  „Papierkorb“ mit vollem Pfad, und die Meldung nach dem Löschen verlinkt auf die Seite.
- **Zurückholen (D22):** Die Seite „Papierkorb“ (und `lager trash list`) zeigt je Eintrag
  Name, Art, alten Platz und Zeitpunkt. „Wiederherstellen“ bringt ein Bauteil in seine
  Kategorie und Unterkategorie zurück (eine fehlende Unterkategorie wird angelegt) und eine
  Datei in ihr Bauteil (bei gleichem Dateinamen mit Nummer, nichts wird überschrieben). Geht
  das nicht, steht der Grund am Eintrag, und es gibt keinen Knopf: Die Bezeichnung ist
  inzwischen wieder vergeben, am alten Platz liegt schon ein Ordner, die Kategorie fehlt, oder
  das Bauteil einer Datei gibt es an seinem alten Platz nicht mehr.
- **Endgültig gelöscht wird nur im Explorer.** Dort landet es dann im Papierkorb von Windows.
  Im Programm gibt es dafür bewusst keinen Knopf.
- **Hochladen im Web:** Mehrere Dateien auf einmal sind möglich. Mit JavaScript startet das
  Hochladen gleich nach der Auswahl im Dateifenster, ein Balken zeigt den Fortschritt, danach
  meldet die Seite, was hochgeladen wurde. Ohne JavaScript bleibt der Knopf „Hochladen“.
- **Dateien werden nach Art einsortiert (D12):** PDFs und unbekannte Arten direkt in den
  Bauteil-Ordner, 3D-Modelle nach `3d/`, KiCad-Dateien nach `kicad/`, Bilder nach `images/`.
- **Nichts wird überschrieben:** Gibt es den Dateinamen schon, bekommt die neue Datei eine
  Nummer (`datasheet-2.pdf`).
- **Dateinamen werden bereinigt:** Pfadanteile und unter Windows verbotene Zeichen fallen weg.
  `part.yaml` lässt sich nicht hochladen. Ein Upload ist auf 200 MB je Datei begrenzt.
- **Vorhandener Ordner wird übernommen:** Liegt schon ein Ordner mit PDFs, aber ohne
  `part.yaml` vor, legt „Bauteil anlegen“ nur die `part.yaml` dazu.

## 6c. QR-Etiketten (Phase 3a — umgesetzt)

Ein Etikett je Bauteil, für die Stelle im Regal, an der das Bauteil liegt. Der QR-Code
enthält nur die Adresse der Bauteilseite: `<Adresse des Servers>/p/<Bezeichnung>`. Die
normale Kamera-App des Handys öffnet sie; eine eigene App ist nicht nötig (D8).

- **Drucken (D15):** Die Seite `/etiketten` zeigt die Etiketten als A4-Seiten und druckt über
  den Browser auf normales Papier; ausgeschnitten wird an den gestrichelten Linien. Größen:
  Mini 25 × 15 mm, Klein 38 × 21 mm (Standard, 65 je Seite), Mittel 50 × 25 mm, Groß
  70 × 37 mm oder eigene Maße. Im Druckdialog gilt: A4, Skalierung 100 %.
- **Auswahl:** alle Bauteile, eine Suche, eine Kategorie (Link „QR-Etiketten für diese
  Auswahl“ unter der Trefferliste) oder ein einzelnes Bauteil (Link „Etikett drucken“ auf
  der Bauteilseite). Beschreibung und Lagerfach lassen sich weglassen.
- **Text auf dem Etikett:** Die Bezeichnung steht so groß wie möglich und bricht bei Bedarf
  auf zwei oder drei Zeilen um, bei Bezeichnungen mit Leerzeichen nur an den Leerzeichen.
  Passt sie trotzdem nicht, weist die Seite darauf hin.
- **Lesbarkeit:** Fehlerkorrektur M, Ruhezone 2 Punkte auf dem Etikett (4 in einzelnen
  Bildern). Werden die Punkte kleiner als 0,4 mm, warnt die Seite.
- **Adresse im Code (D16):** Sie steht in `config.yaml` unter `server.public_url` und wird
  auf der Seite `/etiketten` („Adresse merken“, nur am Server-PC) oder mit `lager qr url`
  gesetzt. Ein Name statt einer IP hält die Etiketten gültig, wenn sich die IP ändert. Viele
  Router lösen den Gerätenamen von selbst auf (FRITZ!Box: `<gerätename>.fritz.box`). Ist noch
  nichts gespeichert, schlägt das Programm einen solchen Namen vor, aber nur wenn er sich
  wirklich auf diesen PC auflösen lässt; sonst die IP. Vor dem Druck prüft die Seite die
  Adresse und warnt bei `localhost`, einer festen IP, `.local`, einem Kurznamen ohne Punkt
  oder einem Namen, der sich nicht oder auf ein anderes Gerät auflöst.
- **Dauerhaft gültig:** Wer das Gerät im Router nach dem Dienst benennt (z. B. `lager`, also
  `lager.fritz.box`), kann den Server später auf einen anderen Rechner umziehen, ohne neu zu
  drucken. Umbenannte Bauteile bleiben über ihren Alias erreichbar (D20).
- **Auf der Bauteilseite** steht derselbe QR-Code zum Aufklappen, etwa um ihn vom Bildschirm
  mit dem Handy zu lesen.
- **CLI:** `lager qr url [ADRESSE]` zeigt oder speichert die Adresse (mit Vorschlag und
  Hinweisen), `lager qr make <Bezeichnung> … [--format svg|png] [--out ORDNER]` schreibt
  einzelne QR-Bilder, z. B. für die App eines Etikettendruckers.
- **Technik:** Der Kern steht in `labels.py` (Paket `segno` für den QR-Code, sonst nur
  Rechnen in Millimetern). Das Druckbild ist HTML mit festen mm-Maßen; ein PDF wird nicht
  erzeugt, der Browser kann aber als PDF drucken.

## 6d. Automatisch ergänzen (geplant, D25)

Von Lukas am 2026-11-26 bestätigter Plan. Gebaut ist bisher nur das Probelauf-Skript
`tools/probelauf.py`; Ergebnisse siehe unten.

**Ziel.** Beim Anlegen eines Bauteils gibt Lukas einen Namen, ein Foto oder einen Screenshot
(z. B. einer Shop-Seite) ein und wählt „Automatisch ergänzen“. Das Programm sucht Datenblatt,
Kennwerte, KiCad-Dateien und 3D-Modell und legt daraus einen Vorschlag an. Lukas prüft und
speichert. Dieselbe Funktion soll später ein KI-Assistent anstoßen können.

**Grundsätze**

1. **Vorschlag statt Eintrag.** Ein Entwurf liegt im Lager unter `_entwuerfe/` (vom Scanner
   ignoriert). Ein Bauteil entsteht erst durch „Speichern“ von Lukas, egal wer gesucht hat.
2. **Jeder Wert mit Herkunft:** Schnittstelle, Quelle (Link und wörtliche Textstelle) oder leer.
3. **Die Schnittstelle liefert die Daten, die KI übersetzt nur.** Die KI macht aus der Eingabe
   Suchbegriffe und recherchiert, was keine Schnittstelle kennt. Sie entscheidet nicht, welches
   Bauteil es ist; der Originalbegriff wird immer mitgesucht.
4. **Belegprüfung ohne KI.** Ein von der KI gelesener Wert wird nur übernommen, wenn die
   genannte Textstelle in der geladenen Quelle wirklich vorkommt. Sonst erscheint er nur als
   Hinweis. So gilt „Nichts erfinden“ auch für die KI.
5. **Lokal.** Das Modell läuft über LM Studio auf Lukas' PC (zuerst Muse Glimmer). Aus dem Haus
   gehen nur Suchbegriffe an Mouser und Suchanfragen ans Web.
6. **Nichts in fremden Namen.** Shop-Seiten (Amazon, AliExpress) werden nicht automatisch
   abgerufen; sie sperren das. Eingabe ist ein Screenshot oder der kopierte Text. Formulare mit
   Lukas' Daten (Modell-Anfrage bei SamacSys) schickt Lukas selbst ab.

**Ablauf eines Vorschlags**

| Stufe | Was passiert | Herkunft im Vorschlag |
|---|---|---|
| 1 | Eingabe aufräumen (Leerzeichen, Groß/Klein), ohne KI | – |
| 2 | KI bildet Suchbegriffe und ordnet ein: Händlerteil, Modul/No-Name oder generisch (nur ein Wert, z. B. 10 kΩ) | Suchbegriffe sichtbar |
| 3 | Mouser: genau ein exakter Treffer wird vorausgewählt, mehrere ergeben eine Auswahlliste (Bild, Hersteller, Gehäuse), keiner geht an Stufe 5 | „Schnittstelle“ |
| 4 | KiCad und 3D: KiCad-Bibliothek über das Gehäuse, sonst Modell von Mouser/SamacSys; fehlt es, Knopf „Modell anfragen“ (Lukas schickt ab), am Bauteil „angefragt am …“, das gelieferte ZIP wird beim Hochladen einsortiert | „Bibliothek“ / „SamacSys“ |
| 5 | KI-Recherche nur für die Lücken: Websuche, Seite und PDF lesen, Bild ansehen; Belegprüfung; Fortschrittsseite mit jedem Schritt und Stopp-Knopf | „Quelle“ mit Link |
| 6 | Seite „Vorschlag prüfen“: jeder Wert mit Herkunft, Dateien zum Ansehen, „Speichern“ legt das Bauteil an | – |

**Umsetzung in dieser Reihenfolge**

0. Probelauf ohne Bauen: Mouser mit echten, auch ungenauen Eingaben; Tempo und Güte der
   lokalen Modelle (`tools/probelauf.py`).
1. Grundgerüst „Vorschlag“: Entwürfe, Seite „Vorschlag prüfen“, Speichern. Eingabe: Name.
2. Mouser anbinden: Suche, Auswahlliste, Datenblatt laden, Kennwerte.
3. Suchbegriffe durch die KI (Stufe 2).
4. KiCad und 3D (Stufe 4).
5. KI-Recherche für die Lücken mit Belegprüfung und Fortschrittsseite (Stufe 5).
6. Foto und Screenshot als Eingabe; am Handy über die Kamera (Dateifeld, geht ohne HTTPS),
   dazu der Barcode auf der Händlertüte.
7. MCP-Server (bisher Phase 4), damit LM Studio Bionic und spätere Assistenten dieselben
   Funktionen nutzen. Auch dann gilt: Gespeichert wird nur durch Lukas.

**Einstellungen** in der lokalen `config.yaml` (Vorlage: `config.example.yaml`):
`mouser.api_key` (nie in Git), `llm.base_url` (LM Studio, bei Lukas Port 1235), `llm.model`.

**Später zu entscheiden:** woher die Websuche für Stufe 5 kommt (eigene Suchmaschine SearXNG
oder eine Such-Schnittstelle mit Schlüssel); ob KiCad-Dateien von LCSC (`easyeda2kicad`)
genutzt werden (nur privat); welches Modell (Empfehlung nach dem Probelauf: Muse Glimmer,
Denkstufe „niedrig“, siehe unten).

**Bewusst nicht:** Meta Muse (Cloud-Agent): in der EU nicht verfügbar, läuft in Metas
Rechenzentrum und erreicht das Heimnetz nicht. LM Studio Bionic ist als Steuerpult am PC
möglich, über den MCP-Server (Schritt 7).

**Probelauf (Schritt 0)**

Gelaufen in der Nacht vom 26. auf den 27.11.2026 auf Lukas' PC (RTX 5070 Ti mit 16 GB, Ryzen 9
9900X3D, 31 GB RAM) mit `tools/probelauf.py reihe`: alle drei Modelle, die in LM Studio liegen,
jedes in zwei Denkstufen („standard“ und „niedrig“ = `reasoning_effort: low`, das Modell denkt
kürzer nach). Aufgaben:

- **A** Suchbegriffe bilden und einordnen, 12 Eingaben von genau (`ne555`) bis vage
  (`HW-130 Motor Shield aliexpress`); dazu `bc525`, das nicht zu einem bekannten Typ
  „verbessert“ werden darf.
- **B** acht Werte mit wörtlichem Beleg aus einem Shop-Text lesen; drei davon stehen nicht im
  Text und müssen leer bleiben (Abmessungen, Gewicht, Hersteller).
- **C** mit einem Such-Werkzeug (feste Trefferliste) das Datenblatt zum HW-130 finden; richtig
  ist das des Herstellers (TI), nicht eine Kopie.
- **D** ein Bauteil auf einem Foto erkennen (Raspberry Pi Pico).

| Modell (alle 4 Bit, Q4_K_M) | Denken | A Suchbegriffe | B Belege | C Hersteller-Datenblatt | D Bild | Tokens/s | s je Suchbegriff | Dauer gesamt |
|---|---|---|---|---|---|---|---|---|
| Gemma 4 12B (7,6 GB, ganz auf der Grafikkarte) | niedrig | 11 von 12 | 8 von 8, nichts erfunden | ja | richtig | 78 | 11 | 3 min |
| | standard | 11 von 12 | 8 von 8, nichts erfunden | ja | falsch („Raspberry Pi Model B+“) | 78 | 11 | 3 min |
| Muse Glimmer 28B (18 GB, 82 % auf der Grafikkarte) | niedrig | 11 von 12 | 8 von 8, nichts erfunden | ja | richtig | 16 | 19 | 5 min |
| | standard | 11 von 12 | 8 von 8, nichts erfunden | ja (nach 13 Suchen) | richtig | 16 | 74 | 18 min |
| Qwen 3.8 27B (18 GB, 80 % auf der Grafikkarte) | niedrig | 10 von 12 | 8 von 8, nichts erfunden | ja | richtig | 26 | 17 | 4 min |
| | standard | 11 von 12 | 8 von 8, nichts erfunden | ja | richtig | 26 | 74 | 17 min |

Was dabei auffiel:

- **HW-130:** Kein Modell weiß aus dem Namen allein, dass ein L293D darauf sitzt (der eine
  Fehler in A bei allen). Mit dem Such-Werkzeug (C) fanden es alle und wählten das Datenblatt
  von TI. Die Recherche-Stufe 5 ist also nötig und klappt.
- **Belege:** Alle Modelle haben jeden Wert wörtlich belegt und die drei Fallen leer gelassen.
- **Denkstufe:** „niedrig“ ist bei Muse Glimmer und Qwen etwa viermal so schnell, ohne
  schlechtere Ergebnisse (Qwen ordnete in „niedrig“ zusätzlich den LM317 als „generisch“ ein).
  Bei Gemma ändert die Stufe nichts am Tempo.
- **Selbsteinschätzung** (Feld „sicherheit“): Gemma meldet immer „hoch“, auch beim falschen
  Bild und bei `bc525`. Muse Glimmer meldet bei `bc525`, beim HW-130 und beim Joy-It-Shield
  „mittel“ oder „gering“. Das Programm prüft Belege ohnehin selbst; als Warnung taugt aber nur
  die Angabe von Muse Glimmer.
- **Ohne Beleg ergänzt:** Für `bc525` schreiben Gemma und Qwen (niedrig) ohne Beleg
  „NPN-Transistor“, Qwen (niedrig) dazu Hersteller, jeweils mit „hoch“. Muse Glimmer lässt beides
  leer. Gemma schreibt „unbekannt“ oder „N/A“, wo das Feld leer bleiben soll; das Programm muss
  solche Platzhalter leeren.
- **Tempo:** Gemma passt ganz auf die Grafikkarte und ist etwa fünfmal so schnell wie Muse
  Glimmer. Muse Glimmer lief mit 16 statt 9,5 Tokens/s am Vortag, weil mehr Grafikspeicher frei
  war (82 % statt 65 % des Modells auf der Karte).

**Empfehlung (entscheidet Lukas):** Muse Glimmer mit Denkstufe „niedrig“ als Standard: so
viele Treffer wie Gemma, das Bild in beiden Stufen richtig, ehrliche Selbsteinschätzung, nichts
ohne Beleg ergänzt. Rund 20 s je KI-Schritt; ein Vorschlag mit geschätzt drei bis sechs
KI-Schritten dauert damit ein bis zwei Minuten. Gemma 4 12B als schnelle Wahl (rund 10 s je
Schritt), wenn die Grafikkarte belegt ist; Bilder und Selbsteinschätzung dann mit Vorsicht.
Qwen bringt gegenüber Muse Glimmer keinen Vorteil. Zwei Modelle zugleich passen nicht in die
16 GB; eingestellt wird eines (`llm.model`). Die Denkstufe kommt in Schritt 3 als Einstellung
dazu.

**Mouser:** Der Schlüssel war am 26. und am 27.11. noch nicht freigegeben („Invalid unique
identifier“). Dieser Teil von Schritt 0 steht aus.

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
- **QR** (Phase 3a, §6c): `http://<name>:<port>/p/<Bezeichnung>` — jede Handy-Kamera öffnet die Seite
- **MCP** (Phase 4, jetzt Schritt 7 von §6d): Tools `search_parts, get_part, create_part, …` für die Datenpflege
  durch lokale Agenten

### Stand des Servers (2026-11-26)

Start: `lager serve` (Adresse und Port aus `config.yaml`, Standard `127.0.0.1:8080`).
Für das Handy im WLAN: `lager serve --host 0.0.0.0`, dann am Handy `http://<name-oder-IP-des-PCs>:8080`.
Nach einem Update des Programms den Server neu starten.

| Adresse | Zweck |
|---|---|
| `/` | Suche, Kategorien, Trefferliste; Knopf „PDF“ öffnet das Datenblatt direkt |
| `/p/<Bezeichnung>` | Bauteilseite: Datenblätter, Angaben, weitere Dateien (je mit „✕“ zum Löschen), QR-Code, „Dateien hinzufügen“. Eine alte Bezeichnung leitet auf die neue weiter. |
| `/neu` | Formular „Neues Bauteil“, auf Wunsch mit neuer Kategorie, Unterkategorie und Dateien |
| `/p/<Bezeichnung>/bearbeiten` | Angaben ändern, in andere Kategorie oder Unterkategorie verschieben |
| `/p/<Bezeichnung>/umbenennen` | Bezeichnung ändern; die alte wird Alias |
| `/p/<Bezeichnung>/loeschen` | Rückfrage vor dem Löschen; `POST` mit `sicher=1` löscht |
| `POST /p/<Bezeichnung>/dateien/loeschen` | Datei in den Papierkorb (Knopf „✕“) |
| `/papierkorb` | Inhalt des Papierkorbs; `POST /papierkorb/wiederherstellen` holt einen Eintrag zurück, `POST /papierkorb/oeffnen` öffnet den Ordner im Explorer (nur am Server-PC) |
| `/etiketten` | QR-Etiketten auswählen, ansehen und drucken; `POST /etiketten/adresse` merkt die Adresse (§6c) |
| `/suche?q=…` | nur die Trefferliste; `static/app.js` lädt sie beim Tippen im Suchfeld nach |
| `/anmelden`, `POST /abmelden` | Anmelden im Browser, wenn ein `write_token` gesetzt ist |
| `/files/<pfad wie im Lager-Ordner>` | Datei ausliefern; PDF und Bilder öffnet der Browser, alles andere wird geladen |
| Fußbereich jeder Seite | Zahl der Bauteile und Dateien, Zeitpunkt des Einlesens, Lager-Ordner, Link „Papierkorb“ mit Zahl der Einträge, „Ordner neu einlesen“, „Lager-Ordner ändern“ mit „Ordner auswählen …“ |
| `POST /einstellungen/lager-ordner`, `POST /einstellungen/ordner-waehlen` | Lager-Ordner umstellen; Ordner-Auswahlfenster am Server-PC öffnen (D21) |
| `/api/v1/parts?q=…`, `/api/v1/parts/<Bezeichnung>` | Suche und Bauteil als JSON |
| `POST /api/v1/parts`, `POST /api/v1/parts/<Bezeichnung>/files`, `POST /api/v1/categories` | Bauteil anlegen (auch mit `subcategory`), Dateien hochladen, Kategorie anlegen |
| `PATCH /api/v1/parts/<Bezeichnung>` | Angaben ändern; `part` benennt um, `category` und `subcategory` verschieben; nur mitgeschickte Felder werden gesetzt |
| `DELETE /api/v1/parts/<Bezeichnung>`, `DELETE /api/v1/parts/<Bezeichnung>/files/<pfad>` | Bauteil oder Datei in den Papierkorb |
| `/api/v1/trash`, `POST /api/v1/trash/<ID>/restore` | Inhalt des Papierkorbs; Eintrag zurückholen (404 = unbekannt, 409 = geht nicht, mit Grund) |
| `/api/v1/categories`, `/api/v1/index`, `/api/v1/health` | Kategorien mit Unterkategorien, Zustand des Index, Lebenszeichen |
| `POST /api/v1/index/rebuild` | Ordner neu einlesen |
| `/docs`, `/openapi.json` | API-Beschreibung, von FastAPI erzeugt |

**„Ordner neu einlesen“** baut den Such-Index aus den Ordnern neu auf (§6a). Nötig ist das nur,
wenn Dateien oder Ordner am Programm vorbei geändert wurden, etwa im Explorer. Danach zeigt
die Seite eine Rückmeldung: wie viele Bauteile, Dateien und Kategorien gefunden wurden, wie
lange es gedauert hat, und welche Hinweise es gab (z. B. eine unlesbare `part.yaml`).

**„Lager-Ordner ändern“** stellt den laufenden Server auf einen anderen Ordner um und trägt
ihn in die `config.yaml` ein; deren Kommentare bleiben erhalten. Mit Häkchen wird in einem
leeren oder neuen Ordner ein Lager angelegt. Ein Ordner mit fremdem Inhalt wird nie verändert.

**„Im Explorer öffnen“** auf der Seite „Papierkorb“ öffnet dessen Ordner am Server-PC.
Windows lässt ein Programm im Hintergrund kein Fenster vor den Browser holen; das neue
Explorer-Fenster liegt deshalb oft dahinter und ist über die Taskleiste zu erreichen. Die
Meldung sagt das.

**„Ordner auswählen …“ (D21)** öffnet das Ordner-Auswahlfenster des Betriebssystems, unter
Windows das des Explorers. Ein Browser verrät einer Webseite keinen vollständigen Ordnerpfad;
deshalb öffnet der Server das Fenster, der ja auf demselben PC läuft. Der gewählte Pfad steht
danach im Eingabefeld, umgestellt wird erst mit „Übernehmen“. Das Fenster läuft als eigener
kleiner Prozess (`python -m lager.folder_dialog`, tkinter) und liegt über den anderen
Fenstern. Fehlt tkinter oder ein Bildschirm (Server ohne Oberfläche), meldet die Seite das
und der Pfad wird eingetippt. Den Knopf gibt es nur mit JavaScript und nur am Server-PC.

Schutz (D13):

- **Lager-Ordner ändern, das Ordner-Auswahlfenster, „Im Explorer öffnen“ und „Adresse merken“
  gehen nur an dem PC, auf dem der Server läuft** (Aufruf über `127.0.0.1` oder `localhost`). Andere Geräte sehen
  den Pfad nur.
- **Ohne `write_token`** darf jedes Gerät im WLAN Bauteile anlegen, ändern, umbenennen und
  löschen, Dateien hochladen und löschen, aus dem Papierkorb zurückholen und neu einlesen. Das
  ist für das private Netz so gewollt; gelöscht wird dabei nur in den Papierkorb (D19).
- **Mit `write_token`** verlangen alle schreibenden Aufrufe das Kopffeld `X-Lager-Token` (API)
  oder eine Anmeldung im Browser (D14): Unter `/anmelden` gibt man den Token einmal ein, der
  Browser merkt ihn sich 30 Tage als Cookie. Ohne Anmeldung blenden die Seiten die
  Schreib-Funktionen aus. Ohne HTTPS geht der Token unverschlüsselt durchs WLAN.
- **SVG-Dateien** werden nicht im Browser geöffnet, sondern geladen, weil sie Skripte enthalten können.

- Ausgeliefert werden nur Dateien, die im Index stehen. Andere Pfade ergeben „nicht gefunden“.
- CLI (`--json`) und API geben dieselben Daten aus (D10): Datensätze mit den englischen
  Feldnamen aus Schema und `part.yaml` (`part`, `name`, `files`, …), Rahmenfelder wie in der
  bisherigen CLI auf Deutsch (`suche`, `anzahl`, `treffer`, `teile`, `warnungen`).
- Die Seiten kommen ohne zusätzliche Bibliothek aus (kein HTMX): Ein kleines Skript
  (`static/app.js`) lädt die Trefferliste beim Tippen nach, zeigt nur die Unterkategorien
  der gewählten Kategorie, lädt Dateien gleich nach der Auswahl mit Fortschrittsbalken hoch,
  fragt vor dem Löschen einer Datei nach und öffnet das Ordner-Auswahlfenster. Ohne
  JavaScript geht alles Wesentliche weiter über normale Formulare und Knöpfe.
- Noch nicht enthalten: Kategorien und Unterkategorien im Web umbenennen oder löschen (das
  geht mit `lager category remove` oder im Explorer, danach neu einlesen), den Papierkorb im
  Programm endgültig leeren (bewusst nur im Explorer), HTTPS.

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
| QR-Etiketten | segno, Druck über den Browser | qrcodegen, PDF-Bibliothek extra |
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
- Bezeichnungen und Unterkategorien werden ohne Rücksicht auf Groß-/Kleinschreibung
  verglichen und sind so eindeutig; auf einem Dateisystem, das Groß und Klein unterscheidet,
  entstehen deshalb keine zwei Ordner, die sich nur darin unterscheiden
- Namen, die nur unter Linux gingen (z. B. mit `:` oder `?`), werden abgelehnt, damit das
  Lager zwischen Windows und Linux verschiebbar bleibt
- keine Windows-APIs; SQLite/YAML/FastAPI plattformunabhängig
- Das Ordner-Auswahlfenster braucht tkinter und einen Bildschirm; ohne beides bleibt das
  Eintippen des Pfads (§7)
- Root-Pfad pro System neu setzen (`lager root set`)

## 10. Roadmap

| Phase | Inhalt | Status |
|---|---|---|
| 0.1 | Konfiguration, bewegbarer Root, Auto-Erkennung, Kategorien, part.yaml, CLI-Grundgerüst, Tests | ✅ |
| 0.2 | SQLite-Index über Bauteile und ihre Dateien (Datenblätter) + `lager index rebuild` | ✅ |
| 1 | Suche und Datenblätter in der CLI: Bauteil suchen, Dateien anzeigen, neues Datenblatt einem Bauteil zuordnen | ✅ `part search` (auch in Dateinamen), `part attach`, `part open` (§6a, §6b) |
| 2 | REST-API (FastAPI, OpenAPI) + Web-Oberfläche fürs Handy: Suche → Bauteilseite → PDF öffnen | ✅ Suche (auch beim Tippen), Bauteilseite, Dateien, Bauteil anlegen und bearbeiten, Dateien hochladen, Lager-Ordner ändern, Rückmeldung beim Einlesen, Anmelden bei Schreibschutz. Von Lukas am Handy geprüft (2026-11-13): Seiten und PDF öffnen funktionieren |
| 3a | QR-Etiketten: erzeugen, auf A4 drucken, mit dem Handy lesen; Adresse als Name statt IP | ✅ Seite `/etiketten`, QR-Code auf der Bauteilseite, `lager qr url`, `lager qr make` (§6c). Von Lukas geprüft (2026-11-13): Das Handy liest den Code und öffnet das Bauteil |
| – | Verwalten (Wünsche aus dem ersten größeren Test, 2026-11-14) | ✅ Bezeichnungen mit Leerzeichen und Kleinbuchstaben, Unterkategorien, Umbenennen, Verschieben, Bauteile und Dateien löschen (Papierkorb), Hochladen gleich nach der Auswahl mit Fortschritt, Ordner-Auswahlfenster für den Lager-Ordner (§6b, §7) |
| – | Rückmeldung zu 0.6.0 (2026-11-26) | ✅ Bauteilseite mit drei eigenen Knöpfen (Bearbeiten, Umbenennen, Löschen) und eigenen Seiten, Papierkorb als Seite mit Wiederherstellen, `config.yaml` nur noch lokal mit Vorlage `config.example.yaml` (0.7.0) |
| A | Automatisch ergänzen: Vorschlag aus Mouser, KiCad-Bibliothek und lokaler KI-Recherche, Prüfseite, Foto als Eingabe (§6d) | geplant (2026-11-26); Schritt 0: Modelle getestet (2026-11-27), Mouser-Schlüssel noch nicht freigegeben |
| 3b | HTTPS mit Kamera-Scanner in der Seite und Startbildschirm (PWA) | offen |
| 4 | MCP-Server für die Datenpflege durch lokale Agenten | geht in Schritt 7 von §6d auf |
| 5 | Mengen ein- und ausbuchen mit Verlauf (`movements`) | offen |
| 6 | Linux-Härtung, Packaging, Backup | offen |

Die Reihenfolge folgt den Prioritäten aus §1 und wurde am 2026-11-12 neu geordnet (D7).
Vorher standen Mengenbuchungen und MCP vor der Handy-Nutzung.

### Ideen für später (noch nicht eingeplant)

Zwei Wünsche von Lukas vom 2026-11-12, mit einer ersten Einschätzung. A ist inzwischen
eingeplant (§6d); über B ist noch nicht entschieden.

**A. Bauteil automatisch ergänzen lassen.** Seit 2026-11-26 eingeplant, siehe §6d und D25.
Die erste Einschätzung (Stufen A1 bis A3) ist dort aufgegangen: A1 entspricht der Mouser-Stufe,
A2 der KI-Stufe mit Belegprüfung, A3 der Recherche für Teile ohne Treffer.

**B. KiCad-Dateien als Bibliothek bereitstellen.** Die im Lager abgelegten Footprints und
Symbole erscheinen direkt in KiCad.

| Stufe | Inhalt | Aufwand |
|---|---|---|
| B1 | Ein Befehl sammelt alle `.kicad_mod` in einen Ordner `Lager.pretty` und alle Symbole in eine `Lager.kicad_sym`. Beide werden einmal in KiCad eingetragen; nach jedem Einlesen sind sie aktuell. | klein bis mittel |
| B2 | Pfade der 3D-Modelle in den Footprints auf das Lager umschreiben; Symbolfelder mit Datenblatt-Link, Hersteller und Lagerfach füllen. | mittel |
| B3 | Der Lager-Server als „HTTP-Bibliothek“ für KiCad: Bauteile erscheinen mit ihren Angaben im Symbol-Auswahlfenster. | mittel |

- B3 nutzt eine von KiCad vorgesehene Schnittstelle: KiCad fragt Kategorien und Bauteile
  über HTTP ab. Eine solche Bibliothek enthält selbst keine Symbole und Footprints, sondern
  verweist auf normale KiCad-Bibliotheken. B1 bleibt also die Grundlage, und je Bauteil muss
  hinterlegt sein, welches Symbol und welcher Footprint dazugehört (neue Felder in `part.yaml`).
- Offene Punkte: gleiche Dateinamen in mehreren Bauteilen (z. B. `TO-220.kicad_mod`),
  Zusammenführen mehrerer Symboldateien, getestete KiCad-Version.
- Empfehlung: B1 ist ein guter, abgeschlossener Schritt; B3 erst, wenn B1 läuft.

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
| D11 | 2026-11-12 | Die Bezeichnung eines Bauteils ist im ganzen Lager eindeutig, nicht nur je Kategorie (s. §6b) |
| D12 | 2026-11-12 | Aufgenommene Dateien werden nach Art einsortiert und überschreiben nie eine vorhandene Datei (s. §6b) |
| D13 | 2026-11-12 | Lager-Ordner im Web nur am Server-PC änderbar; übrige Schreibwege ohne `write_token` im WLAN offen (s. §7) |
| D14 | 2026-11-12 | Anmelden im Browser über den `write_token` als Cookie (30 Tage); Suche beim Tippen mit eigenem kleinem Skript statt HTMX (s. §7) |
| D15 | 2026-11-13 | QR-Etiketten: ein Etikett je Bauteil (nicht je Lagerfach); Druck über den Browser auf normales A4-Papier zum Ausschneiden; Größe beim Drucken wählbar; QR-Code mit dem Paket `segno` (von Lukas so gewählt, s. §6c) |
| D16 | 2026-11-13 | Adresse im QR-Code ist ein Name statt einer IP, gespeichert in `server.public_url`; das Programm schlägt einen auflösbaren Namen vor und prüft die Adresse vor dem Druck (s. §6c) |
| D17 | 2026-11-14 | Die Bezeichnung bleibt, wie sie eingegeben wurde (Groß/Klein, Leerzeichen, Umlaute). Erlaubt ist, was unter Windows und Linux ein Ordnername sein kann; Unzulässiges wird abgelehnt statt geändert (s. §3). Vorher: nur Großbuchstaben, Ziffern und `- _ . +` |
| D18 | 2026-11-14 | Unterkategorien sind Ordner in einer Kategorie; der Ordnername ist der Anzeigename; keine eigene Liste (s. §5) |
| D19 | 2026-11-14 | Löschen im Programm verschiebt in `<lager_root>/_papierkorb/`; endgültig gelöscht wird nur im Explorer (s. §6b) |
| D20 | 2026-11-14 | Umbenennen und Verschieben über das Programm; die alte Bezeichnung bleibt als Alias, und ihre Adresse leitet weiter, damit gedruckte QR-Etiketten gültig bleiben (s. §6b) |
| D21 | 2026-11-14 | Den Lager-Ordner wählt man im Auswahlfenster des Betriebssystems, das der Server am eigenen PC öffnet (eigener Prozess, tkinter); der Pfad wird erst mit „Übernehmen“ wirksam (s. §7) |
| D22 | 2026-11-26 | Der Papierkorb des Lagers hat eine eigene Seite (und `lager trash`): ansehen, wiederherstellen, im Explorer öffnen. Endgültig gelöscht wird weiter nur im Explorer. Anlass: Lukas hat den Ordner `_papierkorb` nicht gefunden (s. §6b) |
| D23 | 2026-11-26 | `config.yaml` steht nicht mehr in Git; eingecheckt ist die Vorlage `config.example.yaml`, aus der das Programm eine fehlende `config.yaml` beim ersten Speichern anlegt. Lukas: Die bisherige Konfiguration war nur zum Testen und enthält nichts Vertrauliches (s. §4) |
| D24 | 2026-11-26 | Bearbeiten, Umbenennen und Löschen sind drei eigene Knöpfe auf der Bauteilseite mit je eigener Seite; Löschen fragt auf einer eigenen Seite nach (statt Häkchen). Wunsch von Lukas (s. §6b) |
| D25 | 2026-11-26 | Plan „Automatisch ergänzen“: Vorschlag statt Eintrag; Mouser liefert die Daten, eine lokale KI (LM Studio) übersetzt nur Suchbegriffe und recherchiert die Lücken; jeder KI-Wert braucht einen Beleg, den das Programm prüft; Speichern nur durch Lukas; Meta Muse (Cloud) nicht, LM Studio Bionic optional über MCP. Von Lukas bestätigt (s. §6d) |
