"""Tests für den CLI-Einstieg: Die Ausgabe muss immer UTF-8 sein."""
import io
import os
import subprocess
import sys

from lager import cli


def test_force_utf8_output(monkeypatch):
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    cli.force_utf8_output()
    sys.stdout.write("Widerstände")
    sys.stdout.flush()
    assert raw.getvalue() == "Widerstände".encode("utf-8")


def test_umgeleitete_ausgabe_ist_utf8():
    """Echter Aufruf mit umgeleiteter Ausgabe, ohne UTF-8-Hilfen aus der Umgebung."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONUTF8", "PYTHONIOENCODING")
    }
    env["COLUMNS"] = "200"
    result = subprocess.run(
        [sys.executable, "-m", "lager", "--help"],
        capture_output=True,
        env=env,
        check=True,
    )
    text = result.stdout.decode("utf-8")  # wirft bei falscher Kodierung
    assert "unterstützen" in text
