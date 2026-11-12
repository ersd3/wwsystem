"""Konfiguration: Laden, Speichern, Pfade auflösen."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Projekt-Root: zwei Ebenen über src/lager/config.py
PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_DIR / "config.yaml"

DEFAULTS: dict[str, Any] = {
    "lager_root": "",
    "server": {"host": "127.0.0.1", "port": 8080, "public_url": ""},
    "write_token": "",
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Lädt config.yaml; eine fehlende Datei liefert die Defaults."""
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = dict(DEFAULTS)
    merged.update(data)
    server = dict(DEFAULTS["server"])
    server.update(data.get("server") or {})
    merged["server"] = server
    return merged


def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def resolve_lager_root(cfg: dict[str, Any], config_path: Path = CONFIG_PATH) -> Path | None:
    """Gibt den konfigurierten Lager-Root zurück (None, wenn leer).

    Relative Pfade werden relativ zum Ordner der config.yaml aufgelöst.
    """
    raw = str(cfg.get("lager_root") or "").strip()
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = config_path.resolve().parent / p
    return p


def set_lager_root(value: str, config_path: Path = CONFIG_PATH) -> Path:
    """Schreibt lager_root in die config.yaml.

    Pfade innerhalb des Projektordners werden relativ gespeichert, damit
    Projekt und Lager gemeinsam verschoben werden können.
    """
    cfg = load_config(config_path)
    target = Path(os.path.expanduser(value)).resolve()
    try:
        rel = target.relative_to(config_path.resolve().parent)
        cfg["lager_root"] = rel.as_posix()
    except ValueError:
        cfg["lager_root"] = str(target)
    save_config(cfg, config_path)
    return target
