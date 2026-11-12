# Lagersystem — Bauteile verwalten

Offene Ordnerstruktur + CLI (später: Web-UI, REST, MCP, QR-App).
Details: [KONZEPT.md](KONZEPT.md) · Übergabe an einen anderen Agenten: [HANDOVER.md](HANDOVER.md)

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

## Lager verschieben

```bat
lager root set D:\neuer\Pfad\zum\Lager
```

## Tests

```bat
.venv\Scripts\python -m pytest tests -q
```
