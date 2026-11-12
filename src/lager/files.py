"""Dateien in einen Bauteil-Ordner aufnehmen (Datenblätter, CAD, KiCad, Bilder).

Wird von der CLI (`lager part attach`) und vom Server (Hochladen) genutzt.
Vorhandene Dateien werden nie überschrieben: Gibt es den Namen schon, bekommt
die neue Datei eine Nummer angehängt (datasheet-2.pdf).
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from . import indexer

# Unterordner je Dateiart (Ordner-Vertrag, KONZEPT.md §3). Alle anderen Arten,
# auch Datenblätter, liegen direkt im Bauteil-Ordner.
KIND_FOLDERS = {"cad3d": "3d", "kicad": "kicad", "image": "images"}
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
_CHUNK = 1024 * 1024
_FORBIDDEN_CHARS = set('<>:"/\\|?*')
# Namen, die Windows nicht als Dateiname zulässt.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}


def safe_filename(raw: str) -> str:
    """Macht aus einem angelieferten Namen einen sicheren Dateinamen ohne Pfad."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch not in _FORBIDDEN_CHARS and ord(ch) >= 32)
    name = name.strip().lstrip(".").rstrip(". ")
    if not name:
        raise ValueError("Dateiname fehlt oder ist ungültig.")
    if name.lower() == "part.yaml":
        raise ValueError("part.yaml kann nicht als Datei hinzugefügt werden.")
    if Path(name).stem.upper() in _RESERVED:
        name = f"datei-{name}"
    return name


def _free_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    stem, suffix = Path(name).stem, Path(name).suffix
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{number}{suffix}"
        number += 1
    return candidate


def target_dir(part_dir: Path, filename: str, cfg: dict | None = None) -> Path:
    """Ordner, in den eine Datei dieses Namens gehört (nach ihrer Art)."""
    ext = Path(filename).suffix.lower().lstrip(".")
    kind = indexer.kind_by_ext_map(cfg).get(ext, indexer.OTHER_KIND)
    folder = KIND_FOLDERS.get(kind)
    return part_dir / folder if folder else part_dir


def add_file(
    part_dir: Path,
    filename: str,
    source: BinaryIO,
    cfg: dict | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Path:
    """Schreibt `source` als neue Datei in den Bauteil-Ordner und gibt ihren Pfad zurück."""
    name = safe_filename(filename)
    folder = target_dir(part_dir, name, cfg)
    folder.mkdir(parents=True, exist_ok=True)
    target = _free_path(folder, name)
    written = 0
    try:
        with open(target, "xb") as out:
            while True:
                chunk = source.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(
                        f"{name} ist größer als {max_bytes // (1024 * 1024)} MB."
                    )
                out.write(chunk)
        if written == 0:
            raise ValueError(f"{name} ist leer.")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def add_file_from_path(
    part_dir: Path, source: Path, cfg: dict | None = None, move: bool = False
) -> Path:
    """Kopiert (oder verschiebt) eine vorhandene Datei in den Bauteil-Ordner."""
    if not source.is_file():
        raise ValueError(f"Datei nicht gefunden: {source}")
    with open(source, "rb") as handle:
        target = add_file(part_dir, source.name, handle, cfg, max_bytes=2**63 - 1)
    if move:
        source.unlink()
    return target
