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

Die Suche läuft über einen Index, der aus den Ordnern aufgebaut wird. Nach Änderungen
im Explorer (z. B. ein neues Datenblatt in einen Bauteil-Ordner gelegt) neu einlesen:

```bat
lager index rebuild
lager index status
```

## Web-Oberfläche (auch fürs Handy)

```bat
lager serve
```

Dann im Browser `http://127.0.0.1:8080` öffnen. Die API-Beschreibung steht unter `/docs`.

Fürs Handy im selben WLAN den Server für andere Geräte freigeben und am Handy
`http://<IP-des-PCs>:8080` öffnen:

```bat
lager serve --host 0.0.0.0
```

Windows fragt beim ersten Mal, ob der Zugriff durch die Firewall erlaubt werden soll.
Ohne `write_token` in der `config.yaml` kann jedes Gerät im WLAN die Daten lesen.

## Lager verschieben

```bat
lager root set D:\neuer\Pfad\zum\Lager
```

## Tests

```bat
.venv\Scripts\python -m pytest tests -q
```
