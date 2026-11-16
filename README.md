# Lagersystem — Bauteile verwalten

Offene Ordnerstruktur, Such-Index (SQLite), CLI, Web-Server mit Seiten fürs Handy und
QR-Etiketten für die Lagerplätze (später: MCP).
Details: [KONZEPT.md](KONZEPT.md) · Stand und Übergabe: [HANDOVER.md](HANDOVER.md)

## Installation (Windows)

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -e .
```

Danach steht `lager` im venv:

```bat
.venv\Scripts\lager --help
```

(Linux: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -e .`)

## Schnellstart

```bat
lager status
lager category add kondensatoren --label "Kondensatoren"
lager part new 100nF-50V --category kondensatoren --name "Keramik-Kondensator 100 nF / 50 V" -q 50
lager part new "Arduino Mega 2560" --category microcontroller --subcategory Boards
lager part show irlz44n
```

Die Bezeichnung eines Bauteils ist zugleich sein Ordnername und bleibt so geschrieben, wie sie
eingegeben wurde, auch mit Leerzeichen und Kleinbuchstaben (in der Kommandozeile dann in
Anführungszeichen). Nicht erlaubt sind `< > : " / \ | ? *`. Eine Unterkategorie ist ein Ordner
in der Kategorie und wird bei Bedarf angelegt.

## Suchen

```bat
lager part search irlz44n
lager part search mosfet 100 --category mosfets
lager part search irlz44n --json
```

Gesucht wird in Bezeichnung, Beschreibung, Hersteller, Aliasen, Tags, Kategorie, Lagerfach
und in den Dateinamen. Die Suche läuft über einen Index, der aus den Ordnern aufgebaut wird.
Nach Änderungen im Explorer (z. B. ein neues Datenblatt in einen Bauteil-Ordner gelegt) neu
einlesen:

```bat
lager index rebuild
lager index status
```

## Datenblätter und andere Dateien

```bat
lager part attach IRLZ44N C:\Downloads\irlz44n.pdf
lager part attach IRLZ44N TO-220.step TO-220.kicad_mod --move
lager part open IRLZ44N
lager part open IRLZ44N --folder
```

`attach` kopiert Dateien in den Ordner des Bauteils: PDFs direkt hinein, 3D-Modelle nach
`3d/`, KiCad-Dateien nach `kicad/`, Bilder nach `images/`. Vorhandene Dateien werden nie
überschrieben. `open` öffnet das Datenblatt mit dem Standardprogramm.

## Umbenennen, verschieben, löschen

```bat
lager part rename ARDUINOMEGA "Arduino Mega 2560"
lager part move "Arduino Mega 2560" --category microcontroller --subcategory Boards
lager part detach IRLZ44N altes-datenblatt.pdf
lager part remove BC547
```

- Nach `rename` steht die alte Bezeichnung in den Aliasen. Das Bauteil wird weiter unter ihr
  gefunden, und ein schon gedrucktes QR-Etikett führt weiter zu ihm.
- `detach` und `remove` löschen nichts endgültig: Datei oder Bauteil-Ordner wandern in den
  Ordner `_papierkorb` im Lager. Von dort lassen sie sich im Explorer zurückholen oder
  endgültig löschen.

## Web-Oberfläche (auch fürs Handy)

```bat
lager serve
```

Dann im Browser `http://127.0.0.1:8080` öffnen. Die API-Beschreibung steht unter `/docs`.

- **Suchen:** Suchfeld oben; der Knopf „PDF“ in der Trefferliste öffnet das Datenblatt direkt.
- **Neues Bauteil:** Knopf „+“ oben. Im Formular lassen sich auch eine neue Kategorie oder
  Unterkategorie anlegen und gleich Dateien mitgeben.
- **Ändern, umbenennen, verschieben, löschen:** auf der Seite des Bauteils, „Bearbeiten,
  umbenennen oder löschen“. Dort stehen Bezeichnung, Kategorie, Unterkategorie und die
  übrigen Angaben, ganz unten „Bauteil löschen“. In der CLI:
  `lager part edit IRLZ44N --location B-07 --quantity 12`.
- **Dateien hinzufügen:** auf der Seite des Bauteils, ganz unten. Eine oder mehrere Dateien
  auswählen; das Hochladen startet von selbst und zeigt einen Fortschrittsbalken.
- **Datei löschen:** Knopf „✕“ neben der Datei. Sie wandert in den Papierkorb des Lagers.
- **QR-Etiketten:** siehe unten.
- **Schreibschutz:** Ist in der `config.yaml` ein `write_token` gesetzt, muss man sich im
  Browser einmal unter „Anmelden“ (Fußbereich) mit diesem Token anmelden, um zu ändern.
- **Ordner neu einlesen:** im Fußbereich. Nötig, wenn Dateien im Explorer geändert wurden.
  Danach zeigt die Seite, was gefunden wurde.
- **Lager-Ordner ändern:** im Fußbereich, nur an dem PC, auf dem der Server läuft. „Ordner
  auswählen …“ öffnet das Ordner-Auswahlfenster des Explorers; der gewählte Pfad gilt erst
  nach „Übernehmen“.

Nach einem Update des Programms den Server beenden (Strg+C) und neu starten.

Fürs Handy im selben WLAN den Server für andere Geräte freigeben und am Handy
`http://<name-oder-IP-des-PCs>:8080` öffnen:

```bat
lager serve --host 0.0.0.0
```

Windows fragt beim ersten Mal, ob der Zugriff durch die Firewall erlaubt werden soll.
Ohne `write_token` in der `config.yaml` kann jedes Gerät im WLAN die Daten lesen und ändern:
Bauteile anlegen, umbenennen und löschen, Dateien hochladen und löschen.

## QR-Etiketten

Ein Etikett je Bauteil, zum Aufkleben am Lagerplatz. Die Kamera-App des Handys liest den Code
und öffnet die Seite des Bauteils.

1. Server für das WLAN starten: `lager serve --host 0.0.0.0`.
2. Am PC `http://127.0.0.1:8080/etiketten` öffnen (oder unter der Trefferliste „QR-Etiketten
   für diese Auswahl“, oder auf einer Bauteilseite „Etikett drucken“).
3. Größe wählen, die Adresse prüfen und einmal „Adresse merken“.
4. „Drucken“: Papier A4, Skalierung 100 %. An den gestrichelten Linien ausschneiden.
5. Vor einem großen Druck ein Etikett mit dem Handy probelesen.

**Die Adresse im Code** sollte ein Name sein, keine IP, damit die Etiketten gültig bleiben,
wenn der Router dem PC eine andere IP gibt. Viele Router lösen den Namen des PCs von selbst
auf, eine FRITZ!Box zum Beispiel als `<gerätename>.fritz.box`. Das Programm schlägt einen
solchen Namen vor, wenn er funktioniert, und warnt bei Adressen, die ein Handy nicht erreicht.
Wer das Gerät im Router nach dem Dienst benennt (etwa `lager`, also
`http://lager.fritz.box:8080`), kann den Server später auf einen anderen Rechner umziehen,
ohne neu zu drucken. Das Handy muss im selben WLAN sein, nicht im Gastnetz.

```bat
lager qr url
lager qr url http://lager.fritz.box:8080
lager qr make IRLZ44N "Arduino Mega 2560" --format png --out etiketten
```

`qr url` zeigt oder speichert die Adresse, `qr make` schreibt einzelne QR-Bilder.

## Eigenes Lager anlegen oder verschieben

Der Ordner `lager/` im Projekt ist nur das Beispiel-Lager und wird mit auf GitHub
hochgeladen. Das eigene Lager gehört an einen Ort außerhalb des Projektordners:

```bat
lager init D:\Lager
```

Ein vorhandenes Lager an einem neuen Ort einstellen:

```bat
lager root set D:\neuer\Pfad\zum\Lager
```

Beides geht auch im Web über „Lager-Ordner ändern“ im Fußbereich.

## Tests

```bat
.venv\Scripts\python -m pytest tests -q
```
