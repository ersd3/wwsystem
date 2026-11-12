# Lagersystem — Bauteile verwalten

Offene Ordnerstruktur, Such-Index (SQLite), CLI und Web-Server mit Seiten fürs Handy
(später: QR-Etiketten, MCP).
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
lager part show irlz44n
```

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

## Web-Oberfläche (auch fürs Handy)

```bat
lager serve
```

Dann im Browser `http://127.0.0.1:8080` öffnen. Die API-Beschreibung steht unter `/docs`.

- **Suchen:** Suchfeld oben; der Knopf „PDF“ in der Trefferliste öffnet das Datenblatt direkt.
- **Neues Bauteil:** Knopf „+“ oben. Im Formular lassen sich auch eine neue Kategorie anlegen
  und gleich Dateien mitgeben.
- **Dateien hinzufügen:** auf der Seite des Bauteils, ganz unten.
- **Ordner neu einlesen:** im Fußbereich. Nötig, wenn Dateien im Explorer geändert wurden.
  Danach zeigt die Seite, was gefunden wurde.
- **Lager-Ordner ändern:** im Fußbereich, nur an dem PC, auf dem der Server läuft.

Nach einem Update des Programms den Server beenden (Strg+C) und neu starten.

Fürs Handy im selben WLAN den Server für andere Geräte freigeben und am Handy
`http://<IP-des-PCs>:8080` öffnen:

```bat
lager serve --host 0.0.0.0
```

Windows fragt beim ersten Mal, ob der Zugriff durch die Firewall erlaubt werden soll.
Ohne `write_token` in der `config.yaml` kann jedes Gerät im WLAN die Daten lesen, Bauteile
anlegen und Dateien hochladen.

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
