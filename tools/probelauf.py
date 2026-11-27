"""Probelauf für „Automatisch ergänzen“ (KONZEPT.md §6d, Schritt 0), bevor etwas gebaut wird.

  mouser  – ob der Mouser-Schlüssel geht und was bei ungenauen Namen zurückkommt
  modell  – wie schnell und wie gut ein lokales Modell (LM Studio) die Aufgaben löst
  reihe   – alle Modelle in LM Studio nacheinander laden und testen, auch später geladene

Aufruf im Projektordner:

    .venv/Scripts/python.exe tools/probelauf.py mouser [Begriff …] [--exakt]
    .venv/Scripts/python.exe tools/probelauf.py modell [--model ID] [--bild PFAD] [--json DATEI]
    .venv/Scripts/python.exe tools/probelauf.py reihe --ordner ORDNER [--bild PFAD] [--stunden 8]

Der Mouser-Schlüssel steht in der lokalen config.yaml unter `mouser.api_key` (nie in Git)
und wird nie ausgegeben. Für `modell` muss LM Studio laufen (`lms server start`) und das
Modell geladen sein (`lms load <modell>`). Nur Standardbibliothek, keine weiteren Pakete.

Die Aufgaben im Modell-Test entsprechen den geplanten Stufen:
  A  Suchbegriffe bilden und einordnen (Schritt 3)
  B  Werte aus einem Text lesen, jeder mit wörtlichem Beleg (Schritt 5, Belegprüfung)
  C  Werkzeug aufrufen und die richtige Quelle wählen (Schritt 5, Recherche)
  D  Bauteil auf einem Bild erkennen (Schritt 6), nur mit --bild
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lager.config import load_config  # noqa: E402

for stream in (sys.stdout, sys.stderr):  # Umlaute auch bei umgeleiteter Ausgabe
    stream.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------- Mouser

MOUSER = "https://api.mouser.com/api/v1/search"
MOUSER_BEGRIFFE = ["irlz44", "IRLZ44N", "pico h", "bc525", "lm317", "HW-130", "TP4056"]


def mouser_request(key: str, path: str, body: dict) -> dict:
    url = f"{MOUSER}/{path}?apiKey={urllib.parse.quote(key)}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # die Adresse (mit Schlüssel) wird nicht ausgegeben
        text = e.read().decode("utf-8", errors="replace")[:500]
        return {"Errors": [{"Message": f"HTTP {e.code}: {text}"}]}
    except urllib.error.URLError as e:
        return {"Errors": [{"Message": f"keine Verbindung: {e.reason}"}]}


def cmd_mouser(args: argparse.Namespace) -> int:
    key = str((load_config().get("mouser") or {}).get("api_key") or "").strip()
    if not key:
        print("Kein Schlüssel: in der config.yaml unter mouser.api_key eintragen.")
        return 1
    for term in args.begriffe or MOUSER_BEGRIFFE:
        if args.exakt:
            body = {"SearchByPartRequest": {"mouserPartNumber": term, "partSearchOptions": "Exact"}}
            data = mouser_request(key, "partnumber", body)
        else:
            body = {
                "SearchByKeywordRequest": {
                    "keyword": term, "records": args.anzahl, "startingRecord": 0,
                    "searchOptions": "", "searchWithYourSignUpLanguage": "",
                }
            }
            data = mouser_request(key, "keyword", body)
        print(f"\n=== {term!r}")
        errors = data.get("Errors") or []
        if errors:
            for error in errors:
                print("  Fehler:", error.get("Message") or error)
            continue
        results = data.get("SearchResults") or {}
        found = results.get("Parts") or []
        print(f"  {results.get('NumberOfResult', 0)} Treffer insgesamt, die ersten {len(found)}:")
        for part in found:
            sheet = "Datenblatt" if part.get("DataSheetUrl") else "ohne Datenblatt"
            print(
                f"  - {part.get('ManufacturerPartNumber')} | {part.get('Manufacturer')} | "
                f"{(part.get('Description') or '')[:70]} | {sheet}"
            )
    return 0


# ------------------------------------------------------------------- Modell

SYSTEM_A = """Du hilfst, elektronische Bauteile in einem privaten Lager zu erfassen.
Aus der Eingabe bildest du Suchbegriffe für die Suche bei einem Bauteile-Händler (Mouser).
Regeln:
- Erfinde nichts. Behalte die Bezeichnung aus der Eingabe bei und ergänze höchstens übliche
  Schreibweisen derselben Hersteller-Teilenummer.
- Ändere nie eine Bezeichnung in ein anderes, ähnliches Bauteil.
- art: "haendlerteil" = ein bestimmtes Bauteil oder Board mit Hersteller-Teilenummer, das ein
  Händler führt; "modul" = Platine oder No-Name-Ware (z. B. Amazon, AliExpress); nenne dann
  unter hauptchips die Chips darauf, wenn du sie sicher kennst; "generisch" = Standardbauteil,
  das nur über seinen Wert bestimmt ist (z. B. Widerstand 10 kOhm).
- Unbekanntes bleibt leer. sicherheit sagt, wie sicher du dir bei der Einordnung bist."""

SCHEMA_A = {
    "type": "object",
    "properties": {
        "suchbegriffe": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "art": {"type": "string", "enum": ["haendlerteil", "modul", "generisch"]},
        "hauptchips": {"type": "array", "items": {"type": "string"}},
        "hersteller": {"type": "string"},
        "gehaeuse": {"type": "string"},
        "beschreibung": {"type": "string"},
        "sicherheit": {"type": "string", "enum": ["hoch", "mittel", "gering"]},
    },
    "required": ["suchbegriffe", "art", "hauptchips", "hersteller", "gehaeuse", "beschreibung", "sicherheit"],
    "additionalProperties": False,
}

# Eingabe, Textstücke, von denen eines in Suchbegriffen oder Hauptchips vorkommen muss,
# erlaubte Einordnungen, Textstücke, die nicht vorkommen dürfen (falsche „Korrektur“).
FAELLE_A = [
    ("irlz44 mosfet to220", ["IRLZ44"], {"haendlerteil"}, []),
    ("pico h", ["PICO"], {"haendlerteil", "modul"}, []),
    ("bc525", ["BC525"], {"haendlerteil"}, ["BC547", "BC327", "BC337", "BC557"]),
    ("lm317 spannungsregler", ["LM317"], {"haendlerteil"}, []),
    ("10k widerstand 0,25w", [], {"generisch"}, []),
    ("HW-130 Motor Shield aliexpress", ["L293D"], {"modul"}, []),
    ("TP4056 Lademodul USB-C", ["TP4056"], {"modul"}, []),
    ("ESP32 DevKit 38 pin", ["ESP32"], {"modul", "haendlerteil"}, []),
    ("ne555", ["NE555"], {"haendlerteil"}, []),
    ("Arduino Mega", ["MEGA"], {"haendlerteil", "modul"}, []),
    ("ams1117 3.3", ["AMS1117"], {"haendlerteil"}, []),
    ("2812 Arduino Shield joy-it", ["2812"], {"modul", "haendlerteil"}, []),
]

TEXT_B = """TP4056 1A Lipo Akku Ladeplatine Lademodul mit Schutzschaltung, USB-C Buchse
Eingangsspannung: 4,5V - 5,5V
Ladeschlussspannung: 4,2V ±1%
Ladestrom: 1A (über Widerstand R3 einstellbar)
Schutz-ICs: DW01A und FS8205A
Tiefentladeschutz: 2,5V
Überstromschutz: 3A
LED rot = lädt, LED blau = voll
Lieferumfang: 5 Stück"""
FELDER_B = {  # Feld -> muss gefunden werden (True) oder darf nicht erfunden werden (False)
    "hauptchip": True,
    "eingangsspannung": True,
    "ladestrom": True,
    "ladeschlussspannung": True,
    "schutzchips": True,
    "abmessungen": False,
    "gewicht": False,
    "hersteller": False,
}
SYSTEM_B = """Du liest technische Angaben aus einem Text. Für jedes Feld gibst du den Wert und als
beleg die wörtliche Stelle aus dem Text, auf der er beruht (genau so geschrieben wie im Text).
Steht ein Wert nicht im Text, bleiben wert und beleg leer. Nichts schätzen, nichts ergänzen."""

TOOLS_C = [
    {
        "type": "function",
        "function": {
            "name": "websuche",
            "description": "Sucht im Web und liefert Titel und Adressen der Treffer.",
            "parameters": {
                "type": "object",
                "properties": {"anfrage": {"type": "string"}},
                "required": ["anfrage"],
            },
        },
    }
]
TREFFER_C = [
    {"titel": "HW-130 Motor Drive Shield Expansion Board – AliExpress", "adresse": "https://www.aliexpress.com/item/1005001.html"},
    {"titel": "L293x Quadruple Half-H Drivers datasheet (Rev. D) – Texas Instruments", "adresse": "https://www.ti.com/lit/ds/symlink/l293d.pdf"},
    {"titel": "L293D Motor Driver Tutorial – Hobby-Blog", "adresse": "https://beispiel-blog.de/l293d-tutorial"},
    {"titel": "L293D pdf, L293D Datasheet – Datenblatt-Sammlung", "adresse": "https://datenblatt-sammlung.example/l293d.pdf"},
]
SYSTEM_C = """Du recherchierst Datenblätter für elektronische Bauteile. Nutze das Werkzeug websuche.
Bevorzuge das Datenblatt direkt vom Hersteller des Chips. Antworte am Ende nur mit der Adresse
des Datenblatts und einem Satz Begründung."""


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class Client:
    def __init__(self, base_url: str, model: str, extra: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.extra = dict(extra or {})  # z. B. {"reasoning_effort": "low"}
        self.calls: list[dict] = []

    def chat(self, messages, schema=None, tools=None, max_tokens=4000, name=""):
        # Denkende Modelle schreiben vor der Antwort oft 1000 Tokens und mehr; mit zu kleinem
        # max_tokens bricht die Antwort ab (am 26.11. bei Muse Glimmer mit 1500 passiert).
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
        body.update(self.extra)
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "antwort", "strict": True, "schema": schema},
            }
        if tools is not None:
            body["tools"] = tools
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=900) as response:
            data = json.loads(response.read().decode("utf-8"))
        seconds = time.perf_counter() - started
        usage = data.get("usage") or {}
        out_tokens = int(usage.get("completion_tokens") or 0)
        self.calls.append(
            {
                "aufgabe": name,
                "sekunden": round(seconds, 1),
                "tokens_ein": usage.get("prompt_tokens"),
                "tokens_aus": out_tokens,
                "tokens_pro_s": round(out_tokens / seconds, 1) if seconds else None,
            }
        )
        say(f"    {name}: {seconds:.0f} s, {out_tokens} Tokens")
        return data["choices"][0]["message"], seconds


def task_a(client: Client) -> list[dict]:
    results = []
    for eingabe, erwartet, arten, verboten in FAELLE_A:
        message, seconds = client.chat(
            [{"role": "system", "content": SYSTEM_A}, {"role": "user", "content": eingabe}],
            schema=SCHEMA_A, name=f"A {eingabe}",
        )
        try:
            answer = json.loads(message.get("content") or "")
        except json.JSONDecodeError:
            results.append({"eingabe": eingabe, "ok": False, "grund": "kein gültiges JSON", "sekunden": round(seconds, 1)})
            continue
        terms = [str(t) for t in answer.get("suchbegriffe", [])] + [str(c) for c in answer.get("hauptchips", [])]
        joined = " ".join(terms).upper()
        problems = []
        if erwartet and not any(e.upper() in joined for e in erwartet):
            problems.append(f"erwartet {erwartet}")
        if answer.get("art") not in arten:
            problems.append(f"Einordnung {answer.get('art')}, erwartet {sorted(arten)}")
        wrong = [v for v in verboten if v.upper() in joined]
        if wrong:
            problems.append(f"falsch korrigiert zu {wrong}")
        results.append(
            {
                "eingabe": eingabe, "ok": not problems, "grund": "; ".join(problems),
                "sekunden": round(seconds, 1), "antwort": answer,
            }
        )
    return results


def task_b(client: Client) -> dict:
    field_schema = {
        "type": "object",
        "properties": {"wert": {"type": "string"}, "beleg": {"type": "string"}},
        "required": ["wert", "beleg"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {name: field_schema for name in FELDER_B},
        "required": list(FELDER_B),
        "additionalProperties": False,
    }
    message, seconds = client.chat(
        [
            {"role": "system", "content": SYSTEM_B},
            {"role": "user", "content": f"Felder: {', '.join(FELDER_B)}\n\nText:\n{TEXT_B}"},
        ],
        schema=schema, name="B Belege",
    )
    answer = json.loads(message.get("content") or "{}")
    text = normalize(TEXT_B)
    checks = {}
    for name, should_exist in FELDER_B.items():
        entry = answer.get(name) or {}
        value, quote = str(entry.get("wert") or "").strip(), str(entry.get("beleg") or "").strip()
        if not should_exist:
            checks[name] = "ok (leer)" if not value else f"ERFUNDEN: {value!r}"
        elif not value:
            checks[name] = "fehlt"
        elif quote and normalize(quote) in text:
            checks[name] = f"ok: {value!r}"
        else:
            checks[name] = f"BELEG NICHT IM TEXT: {value!r} / {quote!r}"
    return {"sekunden": round(seconds, 1), "pruefung": checks, "antwort": answer}


def task_c(client: Client) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_C},
        {"role": "user", "content": "Finde das Datenblatt des Treiber-Chips auf dem HW-130 Motor Shield."},
    ]
    queries, total, final = [], 0.0, ""
    rounds = 6
    for number in range(rounds):
        last = number == rounds - 1
        if last:  # genug gesucht: jetzt ohne Werkzeug antworten lassen
            messages.append({"role": "user", "content": "Gib jetzt deine Antwort: die Adresse des Datenblatts."})
        message, seconds = client.chat(messages, tools=None if last else TOOLS_C, name="C Werkzeug")
        total += seconds
        calls = message.get("tool_calls") or []
        if not calls:
            final = message.get("content") or ""
            break
        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        for call in calls:
            try:
                query = json.loads(call["function"]["arguments"]).get("anfrage", "")
            except (KeyError, json.JSONDecodeError):
                query = "(ungültige Argumente)"
            queries.append(query)
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(TREFFER_C, ensure_ascii=False)}
            )
    return {
        "sekunden": round(total, 1),
        "suchanfragen": queries,
        "antwort": final.strip(),
        "ok": bool(queries) and "ti.com" in final,
    }


def task_d(client: Client, image: Path) -> dict:
    mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode()}"
    message, seconds = client.chat(
        [
            {"role": "system", "content": SYSTEM_A},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Welches Bauteil ist auf dem Bild? Bilde die Suchbegriffe."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        schema=SCHEMA_A, name="D Bild",
    )
    return {"sekunden": round(seconds, 1), "antwort": json.loads(message.get("content") or "{}")}


def say(text: str = "") -> None:
    """Ausgabe sofort schreiben, auch wenn sie in eine Datei umgeleitet ist (Fortschritt sichtbar)."""
    print(text, flush=True)


def run_probe(client: Client, bild: str = "") -> dict:
    """Alle Aufgaben mit einem Modell. Ein Fehler in einer Aufgabe bricht die anderen nicht ab."""
    say(f"Modell: {client.model}")
    report: dict = {"modell": client.model, "fehler": {}}
    started = time.perf_counter()

    def attempt(key: str, title: str, func):
        say(f"\n{key}  {title}")
        try:
            report[key] = func()
        except Exception as e:  # noqa: BLE001 – Bericht statt Abbruch
            report["fehler"][key] = f"{type(e).__name__}: {e}"
            say(f"  FEHLER: {report['fehler'][key]}")
            return False
        return True

    if attempt("A", "Suchbegriffe bilden", lambda: task_a(client)):
        for r in report["A"]:
            a = r.get("antwort") or {}
            mark = "ok  " if r["ok"] else "FEHL"
            say(f"  {mark} {r['eingabe']!r:34} {r['sekunden']:6.1f} s  {a.get('art', '?'):12} "
                f"{a.get('suchbegriffe')} chips={a.get('hauptchips')} {r['grund']}")
    if attempt("B", "Werte mit Beleg aus einem Text", lambda: task_b(client)):
        for name, verdict in report["B"]["pruefung"].items():
            say(f"  {name:20} {verdict}")
        say(f"  ({report['B']['sekunden']} s)")
    if attempt("C", "Werkzeug aufrufen, Quelle wählen", lambda: task_c(client)):
        say(f"  Suchanfragen: {report['C']['suchanfragen']}")
        say(f"  Antwort: {report['C']['antwort'][:200]}")
        say(f"  {'ok' if report['C']['ok'] else 'FEHL'} ({report['C']['sekunden']} s)")
    if bild and attempt("D", "Bauteil auf einem Bild", lambda: task_d(client, Path(bild))):
        say(f"  {report['D']['antwort']} ({report['D']['sekunden']} s)")

    report["aufrufe"] = client.calls
    report["sekunden_gesamt"] = round(time.perf_counter() - started, 1)
    report["zusammenfassung"] = summarize(report)
    say(f"\nZusammenfassung: {json.dumps(report['zusammenfassung'], ensure_ascii=False)}")
    return report


def summarize(report: dict) -> dict:
    a = report.get("A") or []
    b = (report.get("B") or {}).get("pruefung") or {}
    speeds = sorted(c["tokens_pro_s"] for c in report.get("aufrufe", []) if c.get("tokens_pro_s"))
    return {
        "A_richtig": f"{sum(r['ok'] for r in a)} von {len(a)}" if a else "–",
        "B_ok": sum(v.startswith("ok") for v in b.values()) if b else None,
        "B_erfunden": sum(v.startswith("ERFUNDEN") for v in b.values()) if b else None,
        "B_ohne_beleg": sum(v.startswith("BELEG") for v in b.values()) if b else None,
        "C_ok": (report.get("C") or {}).get("ok"),
        "D_suchbegriffe": ((report.get("D") or {}).get("antwort") or {}).get("suchbegriffe"),
        "tokens_pro_s_median": speeds[len(speeds) // 2] if speeds else None,
        "sekunden_je_suchbegriff": round(sum(r["sekunden"] for r in a) / len(a), 1) if a else None,
        "sekunden_gesamt": report.get("sekunden_gesamt"),
        "fehler": sorted(report.get("fehler", {})),
    }


def base_url_from_config(explicit: str = "") -> str:
    cfg = load_config().get("llm") or {}
    return explicit or cfg.get("base_url") or "http://127.0.0.1:1234/v1"


DENKSTUFEN = {"standard": {}, "niedrig": {"reasoning_effort": "low"}}


def cmd_modell(args: argparse.Namespace) -> int:
    cfg = load_config().get("llm") or {}
    client = Client(base_url_from_config(args.base_url), args.model or cfg.get("model") or "meta/muse-glimmer",
                    DENKSTUFEN[args.denken])
    report = run_probe(client, args.bild)
    report["denken"] = args.denken
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        say(f"Bericht: {args.json}")
    return 0


# ------------------------------------------------------------- Testreihe


def lms_path() -> str:
    found = shutil.which("lms")
    if found:
        return found
    candidate = Path.home() / ".lmstudio" / "bin" / ("lms.exe" if sys.platform == "win32" else "lms")
    return str(candidate)


def lms(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        [lms_path(), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


def free_vram_gb() -> float | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip().splitlines()[0]
        total, used = (float(x) for x in out.split(","))
        return (total - used) / 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def gpu_ratio(size_gb: float, free_gb: float | None) -> str:
    """Anteil des Modells auf der Grafikkarte: alles, wenn es passt, sonst so viel wie Platz ist."""
    if free_gb is None:
        return "max"
    usable = free_gb - 1.5  # Platz für Kontext und Puffer
    if size_gb <= usable:
        return "max"
    return f"{max(min(usable / size_gb, 1.0), 0.1):.2f}"


def model_list() -> list[dict]:
    done = lms("ls", "--json", timeout=60)
    try:
        return [m for m in json.loads(done.stdout) if m.get("type") == "llm"]
    except json.JSONDecodeError:
        return []


def other_probe_running() -> bool:
    """Läuft noch ein einzelner Probelauf (z. B. vor dem Start der Reihe angestoßen)?"""
    if sys.platform != "win32":
        return False
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
        "$_.CommandLine -like '*probelauf.py modell*' }"
        " | Measure-Object | Select-Object -ExpandProperty Count"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return out.isdigit() and int(out) > 0


def safe_name(model_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_key)


def cmd_reihe(args: argparse.Namespace) -> int:
    """Testet nacheinander jedes Modell in LM Studio, auch solche, die erst später fertig geladen sind."""
    outdir = Path(args.ordner)
    outdir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.stunden * 3600
    base_url = base_url_from_config(args.base_url)
    skip = {s.strip() for s in args.ohne if s.strip()}
    say(f"Testreihe bis {time.strftime('%H:%M', time.localtime(deadline))}, Berichte in {outdir}")

    while other_probe_running():  # einen laufenden Einzeltest nicht stören
        if time.time() > deadline:
            say("Zeit abgelaufen, während ein anderer Probelauf lief.")
            return 1
        say("Ein anderer Probelauf läuft noch, warte …")
        time.sleep(60)

    # Ergebnis eines vorher einzeln gelaufenen Tests übernehmen (MODELL=DATEI), wenn es da ist.
    for item in args.uebernehmen:
        model_key, _, path = item.partition("=")
        source = Path(path)
        target = outdir / f"{safe_name(model_key)}.json"
        if source.is_file() and not target.exists():
            report = json.loads(source.read_text(encoding="utf-8"))
            report["modell"] = model_key
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            say(f"Ergebnis für {model_key} übernommen aus {source.name}")

    lms("server", "start", timeout=120)
    tried: set[str] = set()
    while True:
        pending = [
            m for m in sorted(model_list(), key=lambda m: m.get("sizeBytes", 0))
            if m["modelKey"] not in tried and m["modelKey"] not in skip
            and not all((outdir / f"{safe_name(m['modelKey'])}__{d}.json").exists() for d in args.denkstufen)
        ]
        if not pending:
            if time.time() + args.warten * 60 > deadline:
                break
            say(f"{time.strftime('%H:%M')} keine neuen Modelle, schaue in {args.warten} Minuten wieder nach")
            time.sleep(args.warten * 60)
            continue
        model = pending[0]
        key = model["modelKey"]
        tried.add(key)
        size_gb = model.get("sizeBytes", 0) / 1024**3
        for number in range(1, args.versuche + 1):
            say(f"\n===== {time.strftime('%H:%M')} {key} ({size_gb:.1f} GB), Versuch {number}")
            lms("unload", "--all", timeout=300)
            ratio = gpu_ratio(size_gb, free_vram_gb())
            loaded = lms("load", key, "-c", "8192", "--gpu", ratio, "--ttl", "7200",
                         "--identifier", "probe", "-y", timeout=1800)
            if loaded.returncode != 0:
                say(f"  Laden fehlgeschlagen (GPU-Anteil {ratio}): {loaded.stdout[-300:]} {loaded.stderr[-300:]}")
                continue
            say(f"  geladen, GPU-Anteil {ratio}")
            broken = False
            for stufe in args.denkstufen:
                target = outdir / f"{safe_name(key)}__{stufe}.json"
                if target.exists():
                    continue
                say(f"\n--- Denkstufe {stufe}")
                try:
                    report = run_probe(Client(base_url, "probe", DENKSTUFEN[stufe]),
                                       args.bild if model.get("vision") else "")
                except Exception as e:  # noqa: BLE001
                    say(f"  Abbruch: {type(e).__name__}: {e}")
                    broken = True
                    break
                report.update({"modell": key, "denken": stufe, "groesse_gb": round(size_gb, 1),
                               "gpu_anteil": ratio, "versuch": number,
                               "quantisierung": (model.get("quantization") or {}).get("name")})
                if len(report["fehler"]) >= 2 and number < args.versuche:
                    say("  Mehrere Aufgaben gescheitert, neuer Versuch.")
                    broken = True
                    break
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not broken:
                break
    lms("unload", "--all", timeout=300)
    lms("server", "stop", timeout=120)
    write_overview(outdir)
    say(f"\nFertig {time.strftime('%H:%M')}. Übersicht: {outdir / 'uebersicht.md'}")
    return 0


def write_overview(outdir: Path) -> None:
    rows = []
    for path in sorted(outdir.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        s = report.get("zusammenfassung") or summarize(report)
        rows.append(
            f"| {report.get('modell')} | {report.get('denken', 'standard')} "
            f"| {report.get('groesse_gb', '?')} GB, GPU {report.get('gpu_anteil', '?')} "
            f"| {s['A_richtig']} | {s['B_ok']} ok, {s['B_erfunden']} erfunden, {s['B_ohne_beleg']} ohne Beleg "
            f"| {'ja' if s['C_ok'] else 'nein'} | {s['D_suchbegriffe']} | {s['tokens_pro_s_median']} "
            f"| {s['sekunden_je_suchbegriff']} | {s['sekunden_gesamt']} | {', '.join(s['fehler']) or '–'} |"
        )
    head = (
        "| Modell | Denken | Größe | A Suchbegriffe | B Belege | C Quelle gewählt | D Bild | Tokens/s | s je Suchbegriff | s gesamt | Fehler |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    (outdir / "uebersicht.md").write_text(head + "\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probelauf für „Automatisch ergänzen“.")
    sub = parser.add_subparsers(dest="befehl", required=True)
    mouser = sub.add_parser("mouser", help="Mouser-Schlüssel und Trefferlisten prüfen")
    mouser.add_argument("begriffe", nargs="*")
    mouser.add_argument("--exakt", action="store_true", help="Teilenummer-Suche „genau“ statt Stichwortsuche")
    mouser.add_argument("--anzahl", type=int, default=5)
    modell = sub.add_parser("modell", help="ein geladenes Modell über LM Studio testen")
    modell.add_argument("--model", default="")
    modell.add_argument("--base-url", default="")
    modell.add_argument("--bild", default="", help="Foto oder Bild eines Bauteils (PNG/JPEG)")
    modell.add_argument("--json", default="", help="Bericht als JSON-Datei schreiben")
    modell.add_argument("--denken", choices=sorted(DENKSTUFEN), default="standard",
                        help="niedrig = kürzeres Nachdenken (reasoning_effort low)")
    reihe = sub.add_parser("reihe", help="alle Modelle in LM Studio nacheinander laden und testen")
    reihe.add_argument("--ordner", required=True, help="Ordner für die Berichte (je Modell eine JSON-Datei)")
    reihe.add_argument("--bild", default="", help="Bild für Aufgabe D (nur bei Modellen mit Bildverständnis)")
    reihe.add_argument("--stunden", type=float, default=8, help="so lange auf neue Modelle warten")
    reihe.add_argument("--warten", type=int, default=10, help="Minuten zwischen zwei Blicken auf neue Modelle")
    reihe.add_argument("--versuche", type=int, default=2)
    reihe.add_argument("--denkstufen", nargs="+", choices=sorted(DENKSTUFEN), default=["niedrig", "standard"])
    reihe.add_argument("--ohne", nargs="*", default=[], help="Modelle, die nicht getestet werden")
    reihe.add_argument("--base-url", default="")
    reihe.add_argument("--uebernehmen", nargs="*", default=[],
                       help="fertige Einzelergebnisse übernehmen: MODELL=DATEI (wird dann nicht erneut getestet)")
    args = parser.parse_args()
    commands = {"mouser": cmd_mouser, "modell": cmd_modell, "reihe": cmd_reihe}
    return commands[args.befehl](args)


if __name__ == "__main__":
    raise SystemExit(main())
