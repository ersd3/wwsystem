"""QR-Etiketten (Phase 3a): Adresse der Bauteilseite, QR-Code und Etiketten auf A4.

Ein Etikett gehört zu einem Bauteil und kommt an dessen Lagerplatz. Sein QR-Code
enthält die Adresse der Bauteilseite (<Adresse>/p/<BEZEICHNUNG>); die normale
Handy-Kamera öffnet sie ohne App. Gedruckt wird über die Web-Seite /etiketten auf
normales A4-Papier; ausgeschnitten wird an den Schnittlinien.

Alle Maße in Millimetern. Die Funktionen hier kennen weder Server noch CLI.
"""
from __future__ import annotations

import io
import ipaddress
import itertools
import math
import re
import socket
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlsplit, urlunsplit

import segno

# Papier: A4 hochkant. Der Rand ist so breit, dass jeder übliche Drucker ihn bedrucken kann.
PAGE_WIDTH = 210.0
PAGE_HEIGHT = 297.0
PAGE_MARGIN = 10.0

# QR-Code: Fehlerkorrektur "M" (15 %, segno erhöht sie, wenn es ohne größeren Code geht).
# Ruhezone 2 Module im Etikett; die Norm empfiehlt 4, Handys lesen 2 zuverlässig, und der
# Innenrand des Etiketts kommt noch dazu.
QR_ERROR = "m"
QR_BORDER = 2
QR_IMAGE_BORDER = 4  # einzelne QR-Bilder (PNG/SVG zum Herunterladen) mit voller Ruhezone

# Lesbarkeit: Unter dieser Kantenlänge eines QR-Punkts müssen Handys sehr nah heran.
MIN_MODULE_MM = 0.4
# Kleinste Schrifthöhe, die noch gedruckt wird (ca. 5 pt).
MIN_TEXT_MM = 1.7
# Mittlere Breite eines fett gesetzten Großbuchstabens, gemessen in Schrifthöhen (Arial).
CHAR_WIDTH = 0.68
LINE_HEIGHT = 1.2


# ---------------------------------------------------------------- Größen


@dataclass(frozen=True)
class LabelSize:
    id: str
    name: str
    width: float
    height: float

    @property
    def title(self) -> str:
        return f"{self.name} · {format_mm(self.width)} × {format_mm(self.height)} mm"


SIZES: tuple[LabelSize, ...] = (
    LabelSize("mini", "Mini", 25, 15),
    LabelSize("klein", "Klein", 38, 21),
    LabelSize("mittel", "Mittel", 50, 25),
    LabelSize("gross", "Groß", 70, 37),
)
DEFAULT_SIZE = "klein"
CUSTOM_SIZE = "eigen"
MIN_WIDTH, MIN_HEIGHT = 15.0, 10.0
MAX_WIDTH = PAGE_WIDTH - 2 * PAGE_MARGIN
MAX_HEIGHT = PAGE_HEIGHT - 2 * PAGE_MARGIN


def format_mm(value: float, digits: int = 1) -> str:
    """Zahl in deutscher Schreibweise ohne überflüssige Nullen: 38.0 -> '38', 0.55 -> '0,55'."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def parse_mm(raw: Any) -> float:
    """Liest ein Maß in Millimetern; Komma und Punkt sind erlaubt."""
    text = str("" if raw is None else raw).strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"Keine gültige Zahl für ein Maß: {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"Keine gültige Zahl für ein Maß: {raw!r}")
    return round(value, 1)


def resolve_size(size_id: str = "", width: Any = None, height: Any = None) -> LabelSize:
    """Etikettengröße aus einer der festen Größen oder aus eigenen Maßen ("eigen")."""
    key = (size_id or DEFAULT_SIZE).strip().lower()
    if key == CUSTOM_SIZE:
        w, h = parse_mm(width), parse_mm(height)
        if not (MIN_WIDTH <= w <= MAX_WIDTH and MIN_HEIGHT <= h <= MAX_HEIGHT):
            raise ValueError(
                f"Eigene Größe muss zwischen {format_mm(MIN_WIDTH)} × {format_mm(MIN_HEIGHT)} mm "
                f"und {format_mm(MAX_WIDTH)} × {format_mm(MAX_HEIGHT)} mm liegen."
            )
        return LabelSize(CUSTOM_SIZE, "Eigene Größe", w, h)
    for size in SIZES:
        if size.id == key:
            return size
    raise ValueError(f"Unbekannte Etikettengröße: {size_id}")


# --------------------------------------------------------------- Adresse


def part_url(base_url: str, part: str) -> str:
    """Adresse der Bauteilseite, wie sie im QR-Code steht."""
    return f"{base_url.rstrip('/')}/p/{quote(part, safe='+')}"


# Namensendungen, unter denen übliche Heimrouter ihre Geräte im Netz bekannt machen
# (FRITZ!Box: <gerätename>.fritz.box). Sie dienen nur dem Vorschlag einer Adresse;
# gedruckt wird immer, was im Feld "Adresse" steht.
LOCAL_DOMAINS = ("fritz.box", "home.arpa", "lan", "home", "internal", "localdomain")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_EXAMPLE_URL = "http://lager.fritz.box:8080"

Resolver = Callable[[str], list[str]]


def lan_ipv4() -> str | None:
    """IPv4-Adresse dieses PCs im lokalen Netz, oder None.

    Der UDP-Socket wird nur "verbunden", damit das System die Route nachschlägt;
    dabei wird nichts gesendet.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.254.254.254", 1))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    if not ip or ip.startswith("127.") or ip == "0.0.0.0":
        return None
    return ip


def local_hostname() -> str:
    """Name dieses PCs, wie ihn das Betriebssystem kennt."""
    return socket.gethostname()


def resolve_ipv4(host: str) -> list[str]:
    """IPv4-Adressen, auf die ein Name zeigt; leer, wenn er sich nicht auflösen lässt."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except (OSError, UnicodeError):
        return []
    return sorted({info[4][0] for info in infos})


def own_ipv4() -> set[str]:
    """Alle IPv4-Adressen dieses PCs, auch die virtueller Netzwerkadapter."""
    addresses = set(resolve_ipv4(local_hostname()))
    lan = lan_ipv4()
    if lan:
        addresses.add(lan)
    return {ip for ip in addresses if not ip.startswith("127.")}


def _with_port(host: str, port: int) -> str:
    return f"http://{host}" if int(port) == 80 else f"http://{host}:{int(port)}"


def suggest_base_url(
    port: int,
    hostname: str | None = None,
    lan_ip: str | None = None,
    resolve: Resolver | None = None,
) -> str:
    """Vorschlag für die Adresse in den QR-Codes, oder "" ohne Netz.

    Bevorzugt wird ein Name, den der Router auflöst (z. B. meinpc.fritz.box): Er bleibt
    gültig, wenn der PC eine andere IP bekommt. Vorgeschlagen wird ein Name nur, wenn er
    nachweislich auf diesen PC zeigt. Sonst kommt die IP im lokalen Netz.
    """
    resolve = resolve or resolve_ipv4
    ip = lan_ipv4() if lan_ip is None else lan_ip
    if not ip:
        return ""
    name = (local_hostname() if hostname is None else hostname).strip().lower()
    if _HOSTNAME_RE.match(name):
        for domain in LOCAL_DOMAINS:
            candidate = f"{name}.{domain}"
            if ip in resolve(candidate):
                return _with_port(candidate, port)
    return _with_port(ip, port)


def normalize_base_url(raw: Any) -> str:
    """Prüft und vereinheitlicht die Adresse für die QR-Codes.

    "lager.fritz.box:8080/" wird zu "http://lager.fritz.box:8080". Fehler als ValueError.
    """
    text = str("" if raw is None else raw).strip()
    if not text:
        raise ValueError(f"Bitte eine Adresse angeben, zum Beispiel {_EXAMPLE_URL}.")
    if any(ch.isspace() for ch in text):
        raise ValueError("Die Adresse darf keine Leerzeichen enthalten.")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        parts.port  # löst bei einem ungültigen Port einen ValueError aus
    except ValueError:
        raise ValueError(f"Die Adresse ist nicht gültig: {raw}") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(
            f"Die Adresse muss mit http:// oder https:// beginnen und einen Namen oder "
            f"eine IP enthalten, zum Beispiel {_EXAMPLE_URL}."
        )
    if parts.query or parts.fragment or parts.username:
        raise ValueError("Die Adresse darf nur aus Name, Port und Pfad bestehen.")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def check_base_url(
    url: str, own_ips: Iterable[str] | None = None, resolve: Resolver | None = None
) -> list[str]:
    """Hinweise zu einer Adresse, bevor sie auf Etiketten gedruckt wird (leer = unauffällig).

    Geprüft wird von diesem PC aus. Ob das Handy die Adresse erreicht, zeigt erst ein
    Scan; die häufigsten Fehler (Tippfehler im Namen, localhost) fallen aber hier auf.
    """
    resolve = resolve or resolve_ipv4
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost" or host == "::1" or host.startswith("127."):
        return [
            f"„{host}“ erreicht nur dieser PC selbst. Ein Handy kommt mit diesem Code nicht an."
        ]
    own = own_ipv4() if own_ips is None else set(own_ips)
    if _is_ip(host):
        notes = []
        if own and host not in own:
            notes.append(f"Die Adresse {host} gehört nicht zu diesem PC ({', '.join(sorted(own))}).")
        notes.append(
            "Im Code steht eine feste IP. Ändert sie sich oder zieht der Server um, müssen "
            "die Etiketten neu gedruckt werden. Ein Name wie lager.fritz.box bleibt gültig."
        )
        return notes

    notes = []
    if "." not in host:
        notes.append(
            f"Kurznamen ohne Punkt lösen viele Handys nicht auf. Besser den vollen Namen "
            f"nehmen, zum Beispiel {host}.fritz.box."
        )
    elif host.endswith(".local"):
        notes.append("Namen mit der Endung .local lösen nicht alle Handys auf.")
    addresses = resolve(host)
    if not addresses:
        notes.append(
            f"Der Name {host} lässt sich an diesem PC nicht auflösen. "
            "Schreibweise und den Eintrag im Router prüfen."
        )
    elif own and not own.intersection(addresses):
        notes.append(f"{host} zeigt auf {', '.join(addresses)} und nicht auf diesen PC.")
    return notes


# --------------------------------------------------------------- QR-Code


@dataclass(frozen=True)
class QrCode:
    data: str
    svg: str  # Inline-SVG ohne feste Größe; skaliert auf die Größe seines Kastens
    modules: int  # Kantenlänge in QR-Punkten, einschließlich Ruhezone

    def module_mm(self, edge_mm: float) -> float:
        """Kantenlänge eines QR-Punkts, wenn der Code `edge_mm` breit gedruckt wird."""
        return edge_mm / self.modules


def make_qr(data: str) -> QrCode:
    code = segno.make(data, error=QR_ERROR, micro=False)
    svg = code.svg_inline(scale=1, border=QR_BORDER, omitsize=True, svgclass="qr-code")
    return QrCode(data, svg, code.symbol_size(scale=1, border=QR_BORDER)[0])


def qr_image(data: str, kind: str = "svg", scale: int = 10) -> bytes:
    """Einzelner QR-Code als Datei (SVG oder PNG), z. B. für eine Etikettendrucker-App."""
    if kind not in ("svg", "png"):
        raise ValueError(f"Unbekanntes Bildformat: {kind}")
    if not 1 <= int(scale) <= 50:
        raise ValueError("Der Maßstab muss zwischen 1 und 50 liegen.")
    buffer = io.BytesIO()
    code = segno.make(data, error=QR_ERROR, micro=False)
    code.save(buffer, kind=kind, scale=int(scale), border=QR_IMAGE_BORDER)
    return buffer.getvalue()


# ------------------------------------------------------- Aufbau Etikett


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class LabelGeometry:
    size: LabelSize
    padding: float
    qr: Box
    text: Box
    stacked: bool  # True: Bezeichnung unter dem QR-Code (schmale Etiketten), sonst daneben


def geometry(size: LabelSize) -> LabelGeometry:
    """Lage von QR-Code und Text innerhalb eines Etiketts."""
    w, h = size.width, size.height
    pad = round(min(max(min(w, h) * 0.07, 1.0), 3.0), 2)
    if w >= 1.4 * h:
        q = min(h - 2 * pad, (w - 3 * pad) * 0.6)
        return LabelGeometry(
            size, pad, Box(pad, (h - q) / 2, q, q), Box(2 * pad + q, pad, w - 3 * pad - q, h - 2 * pad), False
        )
    id_height = min(max(h * 0.16, 2.0), 6.0)
    q = min(w - 2 * pad, h - 2 * pad - id_height - pad / 2)
    return LabelGeometry(
        size, pad, Box((w - q) / 2, pad, q, q), Box(pad, pad + q + pad / 2, w - 2 * pad, id_height), True
    )


@dataclass(frozen=True)
class LabelText:
    id_size: float  # Schrifthöhe der Bezeichnung in mm
    small_size: float  # Schrifthöhe von Beschreibung und Lagerfach in mm
    name_lines: int  # 0 = Beschreibung weglassen
    show_location: bool
    id_parts: tuple[str, ...] = ()  # die Bezeichnung zeilenweise; zwei Teile = zwei Zeilen
    id_fits: bool = True  # False: zu lang für dieses Etikett, wird am Rand abgeschnitten

    @property
    def id_lines(self) -> int:
        return max(len(self.id_parts), 1)


# Wird die Bezeichnung in einer Zeile kleiner als das, kommt sie auf zwei Zeilen.
TWO_LINE_BELOW_MM = 2.6
# Nach diesen Zeichen darf eine Bezeichnung umbrechen.
BREAK_AFTER = " -_.+/"


def split_id(part_id: str) -> tuple[str, str]:
    """Teilt eine Bezeichnung für zwei Zeilen.

    Bevorzugt nach einem Leer- oder Trennzeichen nahe der Mitte ("Arduino" / "Mega 2560",
    "R-10K-" / "0.25W"). Gibt es dort keines, wird in der Mitte geteilt ("ATMEGA3" /
    "28P-PU"), damit beide Zeilen etwa gleich lang sind und die Schrift groß bleiben kann.
    """
    length = len(part_id)
    middle = math.ceil(length / 2)
    cuts = [i + 1 for i, char in enumerate(part_id[:-1]) if char in BREAK_AFTER]
    balanced = [cut for cut in cuts if max(cut, length - cut) <= middle + 1]
    cut = min(balanced, key=lambda c: (abs(c - length / 2), c)) if balanced else middle
    return part_id[:cut].rstrip(), part_id[cut:].lstrip()


def wrap_words(part_id: str, count: int) -> tuple[str, ...] | None:
    """Verteilt die Wörter einer Bezeichnung auf `count` Zeilen ("WS2812" / "Arduino" / "Shield").

    Umbrochen wird nur an Leerzeichen, und zwar so, dass die längste Zeile möglichst kurz
    bleibt. Hat die Bezeichnung weniger Wörter als Zeilen, ist das Ergebnis None.
    """
    words = part_id.split()
    if count < 2 or len(words) < count:
        return None
    best: tuple[int, tuple[str, ...]] | None = None
    for cuts in itertools.combinations(range(1, len(words)), count - 1):
        edges = (0, *cuts, len(words))
        lines = tuple(" ".join(words[a:b]) for a, b in zip(edges, edges[1:]))
        longest = max(len(line) for line in lines)
        if best is None or longest < best[0]:
            best = (longest, lines)
    return best[1] if best else None


def even_split(part_id: str, count: int) -> tuple[str, ...]:
    """Teilt eine Bezeichnung ohne Rücksicht auf Trennzeichen in etwa gleich lange Stücke."""
    step = math.ceil(len(part_id) / count)
    pieces = (part_id[i:i + step].strip() for i in range(0, len(part_id), step))
    return tuple(piece for piece in pieces if piece)


# Anteil der Texthöhe, den eine Zeile der Bezeichnung höchstens bekommt, je Zeilenzahl.
_ID_SHARE = {1: 0.3, 2: 0.22, 3: 0.19}


def fit_text(
    geo: LabelGeometry,
    part_id: str,
    name: str = "",
    location: str = "",
    show_name: bool = True,
    show_location: bool = True,
) -> LabelText:
    """Schriftgrößen so wählen, dass die Bezeichnung ganz zu lesen ist.

    Sie steht in einer Zeile. Würde sie dabei sehr klein (lange Bezeichnung auf einem
    kleinen Etikett), wird sie auf zwei oder drei Zeilen verteilt und dafür größer gesetzt:
    eine Bezeichnung mit Leerzeichen nur an den Leerzeichen, eine Typnummer ohne Leerzeichen
    nach einem Trennzeichen oder in der Mitte. Passt sie auch dann nicht, sagt das `id_fits`
    (die Seite weist darauf hin).
    """
    box = geo.text

    def by_width(rows: tuple[str, ...]) -> float:
        """Größte Schrift, bei der die längste Zeile noch in die Breite passt."""
        return box.width / (CHAR_WIDTH * max(max(len(row) for row in rows), 3))

    def best_size(rows: tuple[str, ...]) -> float:
        return min(box.height * _ID_SHARE[len(rows)], by_width(rows), 6.0)

    def fits(rows: tuple[str, ...], size: float) -> bool:
        return by_width(rows) >= size and len(rows) * size * LINE_HEIGHT <= box.height + 0.01

    if geo.stacked:
        id_size = max(min(box.height * 0.8, by_width((part_id,)), 6.0), MIN_TEXT_MM)
        return LabelText(round(id_size, 2), 0.0, 0, False, (part_id,), fits((part_id,), id_size))

    id_parts: tuple[str, ...] = (part_id,)
    id_size = max(best_size(id_parts), MIN_TEXT_MM)
    if " " in part_id:
        options = [wrap_words(part_id, 2), wrap_words(part_id, 3)]
    else:
        options = [split_id(part_id) if len(part_id) >= 4 else None]
    # Mehr Zeilen nur, wenn die Schrift dadurch deutlich größer wird.
    for rows in options:
        if rows is None or id_size >= TWO_LINE_BELOW_MM:
            continue
        if best_size(rows) >= id_size * 1.25:
            id_size, id_parts = best_size(rows), rows
    if not fits(id_parts, id_size):
        # Passt nicht: der erste Umbruch nehmen, der passt, notfalls mitten im Wort.
        # Passt keiner, bleibt der mit der größten Schrift (und `id_fits` wird False).
        forced = [rows for rows in options if rows is not None]
        if len(part_id) >= 4:
            forced.append(split_id(part_id))
        if len(part_id) >= 9:
            forced.append(even_split(part_id, 3))
        fitting = [rows for rows in forced if fits(rows, max(best_size(rows), MIN_TEXT_MM))]
        id_parts = fitting[0] if fitting else max([id_parts, *forced], key=best_size)
        id_size = max(best_size(id_parts), MIN_TEXT_MM)
    id_fits = fits(id_parts, id_size)

    small = min(max(id_size * 0.62, MIN_TEXT_MM), 3.5)
    remaining = box.height - len(id_parts) * id_size * LINE_HEIGHT
    with_location = bool(show_location and location.strip() and remaining >= small * LINE_HEIGHT)
    if with_location:
        remaining -= small * LINE_HEIGHT
    name_lines = 0
    if show_name and name.strip():
        name_lines = max(min(int(remaining // (small * LINE_HEIGHT)), 4), 0)
    return LabelText(
        round(id_size, 2), round(small, 2), name_lines, with_location, id_parts, id_fits
    )


# ------------------------------------------------------- Seiten (A4)


@dataclass(frozen=True)
class SheetLayout:
    columns: int
    rows: int
    offset_x: float  # linker Rand bis zur ersten Spalte
    offset_y: float  # oberer Rand bis zur ersten Zeile

    @property
    def per_sheet(self) -> int:
        return self.columns * self.rows


def sheet_layout(size: LabelSize) -> SheetLayout:
    """Wie viele Etiketten auf eine A4-Seite passen; das Raster liegt mittig."""
    usable_w = PAGE_WIDTH - 2 * PAGE_MARGIN
    usable_h = PAGE_HEIGHT - 2 * PAGE_MARGIN
    columns = max(int((usable_w + 1e-6) // size.width), 1)
    rows = max(int((usable_h + 1e-6) // size.height), 1)
    return SheetLayout(
        columns,
        rows,
        round((PAGE_WIDTH - columns * size.width) / 2, 2),
        round((PAGE_HEIGHT - rows * size.height) / 2, 2),
    )


@dataclass(frozen=True)
class Label:
    part: dict
    url: str
    qr: QrCode
    text: LabelText
    x: float  # Lage auf der Seite (linke obere Ecke)
    y: float


@dataclass(frozen=True)
class LabelSheets:
    size: LabelSize
    geometry: LabelGeometry
    layout: SheetLayout
    sheets: list[list[Label]]
    count: int
    min_module_mm: float  # kleinster QR-Punkt aller Etiketten (0, wenn keine)
    clipped: tuple[str, ...] = ()  # Bezeichnungen, die auf dieser Größe nicht ganz Platz haben


def prepare(
    parts: Iterable[dict],
    base_url: str,
    size: LabelSize,
    show_name: bool = True,
    show_location: bool = True,
) -> LabelSheets:
    """Etiketten für Bauteile (dicts wie aus search.get_part) auf A4-Seiten verteilen."""
    geo = geometry(size)
    layout = sheet_layout(size)
    sheets: list[list[Label]] = []
    min_module = 0.0
    count = 0
    clipped: list[str] = []
    for index, part in enumerate(parts):
        slot = index % layout.per_sheet
        if slot == 0:
            sheets.append([])
        column, row = slot % layout.columns, slot // layout.columns
        url = part_url(base_url, part["part"])
        qr = make_qr(url)
        module = qr.module_mm(geo.qr.width)
        min_module = module if count == 0 else min(min_module, module)
        text = fit_text(
            geo, part["part"], part.get("name", ""), part.get("location", ""), show_name, show_location
        )
        if not text.id_fits:
            clipped.append(part["part"])
        sheets[-1].append(
            Label(
                part,
                url,
                qr,
                text,
                round(layout.offset_x + column * size.width, 2),
                round(layout.offset_y + row * size.height, 2),
            )
        )
        count += 1
    return LabelSheets(size, geo, layout, sheets, count, round(min_module, 3), tuple(clipped))
