"""Wegwerf-Lager anlegen und den Web-Server darauf starten — für Sichtprüfungen im Browser.

Das echte Lager und die echte config.yaml bleiben unberührt: Das Skript legt in einem
neuen, leeren Ordner ein kleines Lager mit Beispiel-Bauteilen und einer eigenen
config.yaml an und startet den Server damit.

Aufruf (im Projektordner):

    .venv/Scripts/python.exe tools/demo_server.py [--port 8765] [--host 127.0.0.1] [--dir ORDNER]

Ohne --dir entsteht ein Ordner im Temp-Verzeichnis. Ein angegebener Ordner muss neu oder
leer sein; gelöscht wird nie etwas. Beenden mit Strg+C.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import uvicorn

from lager import categories, parts
from lager.server.app import create_app

CONFIG = """# Konfiguration des Wegwerf-Lagers (tools/demo_server.py)
lager_root: "lager"

server:
  host: "127.0.0.1"
  port: 8080
  public_url: ""

write_token: ""
"""


def build(base: Path) -> tuple[Path, Path]:
    """Legt unter `base` das Lager und seine config.yaml an; gibt beide Pfade zurück."""
    if base.exists() and any(base.iterdir()):
        raise SystemExit(f"{base} ist nicht leer. Bitte einen neuen oder leeren Ordner angeben.")
    root = base / "lager"
    root.mkdir(parents=True)
    config_path = base / "config.yaml"
    config_path.write_text(CONFIG, encoding="utf-8")

    categories.save(root, [])
    categories.add(root, "mosfets", "MOSFETs")
    categories.add(root, "microcontroller", "Microcontroller")
    categories.add(root, "Widerstände", "Widerstände")

    # Alle Angaben hier sind ausgedachte Beispiele für die Oberfläche, kein echter Bestand.
    irlz = parts.create_part(root, "mosfets", "IRLZ44N", {
        "name": "MOSFET N-Kanal 55 V / 47 A, TO-220", "manufacturer": "Infineon",
        "tags": ["n-kanal", "to-220"], "location": "A-03-2", "quantity": 5,
    })
    (irlz / "datasheet.pdf").write_bytes(b"%PDF-1.4 demo")
    (irlz / "3d").mkdir()
    (irlz / "3d" / "TO-220.step").write_bytes(b"step")
    parts.create_part(root, "mosfets", "IRF540N", {"name": "MOSFET N-Kanal 100 V / 33 A", "location": "A-03-3"})
    parts.create_part(root, "microcontroller", "ARDUINOMEGA", {"manufacturer": "Arduino", "quantity": 3})
    parts.create_part(root, "microcontroller", "Raspberry Pi Pico H", {"quantity": 10}, "Microcontroller")
    parts.create_part(root, "microcontroller", "WS2812 Arduino Shield", {"manufacturer": "joy-it"}, "Shields")
    for value in ("10R", "220R", "4K7", "10K", "100K"):
        parts.create_part(
            root, "widerstaende", f"R-{value}-0.25W",
            {"name": f"Widerstand {value}, 0,25 W, 1 %", "location": "C-01"},
        )
    return root, config_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Wegwerf-Lager mit Server für Sichtprüfungen.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 = auch fürs Handy im WLAN")
    parser.add_argument("--dir", type=Path, default=None, help="neuer oder leerer Ordner")
    args = parser.parse_args()

    base = args.dir if args.dir is not None else Path(tempfile.mkdtemp(prefix="lager-demo-"))
    root, config_path = build(base)
    print(f"Wegwerf-Lager: {root}", flush=True)
    print(f"Server: http://{args.host}:{args.port}  (Beenden mit Strg+C)", flush=True)
    app = create_app(root, {"write_token": ""}, config_path, bind_host=args.host)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
