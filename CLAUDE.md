# Lagersystem — Arbeitsanweisung für Claude

Bauteile-Lagersystem von Lukas: Ordner mit `part.yaml` und Datenblättern, SQLite-Such-Index,
CLI `lager`, Web-Server mit Seiten fürs Handy. Python 3.14, Windows 11 (später Linux).

**Lies zuerst [HANDOVER.md](HANDOVER.md).** Dort stehen Stand, Aufbau, Stolpersteine und die
nächsten Schritte. Entscheidungen und Begründungen stehen in [KONZEPT.md](KONZEPT.md).

## Regeln von Lukas (gehen vor)

1. **Sprache:** Antworten, Doku, Meldungen und Oberfläche auf Deutsch. Namen im Code auf Englisch.
2. **Vor jedem Commit fragen.** Lokal darfst du direkt schreiben. Zeig, was geändert wurde,
   und warte auf das Ja. Danach committen und ohne weitere Rückfrage direkt auf `main` pushen
   (`origin` = `github.com/ersd3/wwsystem`, öffentlich). Kein eigener Branch, kein Pull Request.
3. **Doku mitziehen:** `KONZEPT.md` und `HANDOVER.md` bei jeder Änderung aktualisieren. Lukas
   verfolgt den Fortschritt darüber.
4. **Sprachneutrale Daten (D6):** nichts Python-Spezifisches in Datenbank oder Dateien. Schema
   als reines SQL in `src/lager/schema.sql`, nur TEXT/INTEGER/REAL, Zeit als ISO-8601 in UTC,
   Listen als eigene Tabellen, kein ORM, kein `pickle`, YAML nur mit `safe_load`/`safe_dump`.
5. **Nichts erfinden:** keine ausgedachten Bestände, Kennwerte oder Datenblätter. Unbekanntes
   bleibt leer und wird gesagt.
6. **Prioritäten:** Datenblätter schnell finden und öffnen, dann Nutzung am Handy; Mengen sind nachrangig.

## Befehle (PowerShell oder Git Bash, im Projektordner)

```bash
.venv/Scripts/python.exe -m pytest tests -q        # alle Tests, müssen bestehen
.venv/Scripts/lager.exe --help                     # CLI
.venv/Scripts/lager.exe serve                      # Server auf http://127.0.0.1:8080
.venv/Scripts/python.exe -m pip install -r requirements.txt -e .   # nach neuen Paketen
```

## So arbeitest du hier

- **Kleine Schritte:** eine Funktion, ihre Tests, dann die Doku. Erst wenn alle Tests bestehen, weiter.
- **Tests zuerst lesen:** Für fast alles gibt es ein Muster in `tests/`. Neue Tests kommen in die
  passende Datei und nutzen die Fixtures aus `tests/conftest.py`.
- **Ein Kern, mehrere Clients:** Logik gehört in `src/lager/*.py`. CLI (`cli.py`) und Server
  (`server/app.py`) rufen nur auf. Beide geben dieselben Daten aus.
- **Oberfläche prüfen:** Was im Browser sichtbar ist, im Browser ansehen (Handy-Breite 375 px),
  nicht nur testen.
- **Unsicher?** Fragen statt raten. Lukas entscheidet über Umfang und Reihenfolge.

## Stolpersteine (kosten sonst Zeit)

- **Neue Dateien mit dem Write-Werkzeug anlegen**, nicht per `cat <<EOF` in der Shell: Texte mit
  Anführungszeichen oder Apostroph brechen dort ab.
- **Läuft noch ein `lager serve`**, ist `.venv/Scripts/lager.exe` gesperrt und `pip install -e .`
  bricht ab. Den Server von Lukas nicht ungefragt beenden; die Tests laufen trotzdem.
- **Nach Änderungen am Code den Server neu starten**, sonst läuft der alte Stand weiter.
- **Server-Tests** brauchen immer die Fixture `config_path`, damit nie die echte `config.yaml`
  geändert wird. `client` ist der Browser am Server-PC, `phone` ein anderes Gerät, `geschuetzt`
  ein Server mit `write_token` „geheim“.
- **Formulare mit Dateifeld:** Ein leeres Dateifeld schickt der Browser als leeren Text. Deshalb
  der Typ `FormFiles` in `server/app.py`.
- **SQLite im Server:** Verbindung in der Route selbst öffnen (`with open_index(request)`), nicht
  über `Depends`.
- **Umlaute:** Dateien immer mit `encoding="utf-8"` lesen und schreiben.
- **Echte Daten:** Der Ordner `lager/` im Projekt ist das Beispiel-Lager und liegt im öffentlichen
  Repository. Keine privaten Daten oder fremden Datenblätter hinein committen.
