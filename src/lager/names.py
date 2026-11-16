"""Namen für Ordner im Lager prüfen (Bauteil-Bezeichnungen, Unterkategorien).

Eine Bezeichnung ist zugleich der Ordnername. Erlaubt ist deshalb alles, was unter
Windows und Linux als Ordnername funktioniert: Groß- und Kleinbuchstaben, Ziffern,
Leerzeichen, Umlaute und die meisten Sonderzeichen. Nichts wird stillschweigend
verändert, außer überflüssigen Leerzeichen; was nicht geht, wird mit Grund abgelehnt.
"""
from __future__ import annotations

# Zeichen, die Windows in Datei- und Ordnernamen nicht zulässt.
FORBIDDEN_CHARS = '<>:"/\\|?*'
# Namen, die Windows nicht als Datei- oder Ordnername zulässt (auch mit Endung).
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}
# Ordner mit diesen Anfangszeichen überspringt das Lager (_vorlage, _papierkorb, .lager).
IGNORED_PREFIXES = ("_", ".")
MAX_LENGTH = 80


def clean(raw: str) -> str:
    """'  Arduino   Mega ' -> 'Arduino Mega': außen keine, innen einfache Leerzeichen."""
    return " ".join(str(raw or "").split())


def check(name: str, what: str = "Die Bezeichnung") -> None:
    """Prüft einen (schon bereinigten) Namen. Ein ungültiger Name löst einen ValueError aus."""
    if not name:
        raise ValueError(f"{what} fehlt.")
    if len(name) > MAX_LENGTH:
        raise ValueError(f"{what} ist zu lang (höchstens {MAX_LENGTH} Zeichen).")
    bad = sorted({ch for ch in name if ch in FORBIDDEN_CHARS or ord(ch) < 32})
    if bad:
        shown = " ".join(ch if ord(ch) >= 32 else "(Steuerzeichen)" for ch in bad)
        raise ValueError(
            f"{what} darf diese Zeichen nicht enthalten: {shown} "
            '(in Ordnernamen nicht erlaubt sind < > : " / \\ | ? *).'
        )
    if name.startswith(IGNORED_PREFIXES):
        raise ValueError(
            f"{what} darf nicht mit _ oder . beginnen (solche Ordner überspringt das Lager)."
        )
    if name.endswith("."):
        raise ValueError(f"{what} darf nicht mit einem Punkt enden.")
    if name.split(".")[0].strip().upper() in RESERVED:
        raise ValueError(f"{name} ist unter Windows kein erlaubter Ordnername.")
