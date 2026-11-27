"""Antwort-Formate der REST-API (daraus entsteht die OpenAPI-Beschreibung).

Die Felder entsprechen genau dem, was die CLI mit --json ausgibt.
"""
from typing import Dict, List, Optional, Union

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    version: str


class FileEntry(BaseModel):
    path: str
    kind: str
    ext: str
    size: int
    mtime: str


class Part(BaseModel):
    part: str
    name: str
    manufacturer: str
    category: str
    category_label: str
    subcategory: str
    path: str
    quantity: int
    unit: str
    location: str
    notes: str
    aliases: List[str]
    tags: List[str]
    files: List[FileEntry]


class NewPart(BaseModel):
    part: str
    category: str
    subcategory: str = ""  # Ordner in der Kategorie, z. B. "Shields"; wird bei Bedarf angelegt
    name: str = ""
    manufacturer: str = ""
    quantity: int = 0
    unit: str = "Stk"
    location: str = ""
    aliases: List[str] = []
    tags: List[str] = []
    notes: str = ""


class PartChanges(BaseModel):
    """Nur die mitgeschickten Felder werden geändert.

    `part` benennt das Bauteil um, `category` und `subcategory` verschieben es.
    """

    part: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    quantity: Optional[int] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    aliases: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class NewCategory(BaseModel):
    id: str
    label: str = ""


class UploadResult(BaseModel):
    hinzugefuegt: List[str]
    fehler: List[str]
    teil: Part


class PartDeleteResult(BaseModel):
    geloescht: str  # Bezeichnung des Bauteils
    papierkorb: str  # neuer Ort, relativ zum Lager-Root


class FileDeleteResult(BaseModel):
    geloescht: str  # Pfad der Datei im Bauteil-Ordner
    papierkorb: str  # neuer Ort, relativ zum Lager-Root
    teil: Part


class DraftField(BaseModel):
    value: Union[str, List[str]]  # Liste bei aliases und tags
    # Herkunft: kind (input | api | library | web), dazu name, url, quote. Leer = keine.
    source: Dict[str, str]


class DraftFile(BaseModel):
    path: str  # relativ zum Ordner des Vorschlags
    size: int
    source: Dict[str, str]


class Draft(BaseModel):
    id: str  # Name des Ordners unter _entwuerfe, z. B. 20261127T091500Z
    created: str  # ISO 8601, UTC
    updated: str  # letzte Änderung des Stands, ISO 8601, UTC
    status: str  # queued (wartet) | running (in Arbeit) | ready (bereit zum Prüfen) | failed
    error: str  # Grund bei failed, sonst leer
    input: str  # was eingegeben wurde
    path: str  # relativ zum Lager-Root
    fields: Dict[str, DraftField]  # part, category, subcategory, name, manufacturer, aliases, tags, notes
    files: List[DraftFile]


class DraftList(BaseModel):
    ordner: str  # Ordner der Vorschläge (absolut)
    anzahl: int
    eintraege: List[Draft]


class NewDraft(BaseModel):
    input: str  # Name, Bestellnummer oder Suchbegriff


class DraftDiscardResult(BaseModel):
    verworfen: str  # ID des Vorschlags
    papierkorb: str  # Ort im Papierkorb, relativ zum Lager-Root


class TrashEntry(BaseModel):
    id: str  # Name des Zeit-Ordners im Papierkorb, z. B. 20261126T205502Z
    kind: str  # part | file | draft (verworfener Vorschlag)
    name: str  # Bezeichnung des Bauteils, Name der Datei bzw. Eingabe des Vorschlags
    part: str  # Bauteil, zu dem der Eintrag gehört(e); bei einem Vorschlag leer
    path: str  # alter Platz im Lager
    deleted_at: str  # ISO 8601, UTC
    location: str  # jetziger Ort, relativ zum Lager-Root
    problem: str  # warum er sich nicht zurückholen lässt; leer = es geht


class TrashList(BaseModel):
    papierkorb: str  # Ordner des Papierkorbs (absolut)
    anzahl: int
    eintraege: List[TrashEntry]


class TrashRestoreResult(BaseModel):
    wiederhergestellt: str  # neuer Ort, relativ zum Lager-Root
    eintrag: TrashEntry
    teil: Optional[Part] = None


class SearchResult(BaseModel):
    suche: str
    kategorie: str
    anzahl: int
    treffer: List[Part]


class Category(BaseModel):
    id: str
    label: str
    listed: bool
    parts: int
    subcategories: List[str] = []  # Ordner in der Kategorie, die kein Bauteil sind


class IndexWarning(BaseModel):
    pfad: str
    grund: str


class RebuildResult(BaseModel):
    aktion: str
    db: str
    kategorien: int
    teile: int
    dateien: int
    dateien_nach_art: Dict[str, int]
    warnungen: List[IndexWarning]
    dauer_ms: int


class IndexStatus(BaseModel):
    vorhanden: bool
    db: str
    schema_version: Optional[int] = None
    aufgebaut_am: Optional[str] = None
    erzeugt_von: Optional[str] = None
    kategorien: Optional[int] = None
    teile: Optional[int] = None
    dateien: Optional[int] = None
    dateien_nach_art: Optional[Dict[str, int]] = None
