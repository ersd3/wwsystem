"""Antwort-Formate der REST-API (daraus entsteht die OpenAPI-Beschreibung).

Die Felder entsprechen genau dem, was die CLI mit --json ausgibt.
"""
from typing import Dict, List, Optional

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


class TrashEntry(BaseModel):
    id: str  # Name des Zeit-Ordners im Papierkorb, z. B. 20261126T205502Z
    kind: str  # part | file
    name: str  # Bezeichnung des Bauteils bzw. Name der Datei
    part: str  # Bauteil, zu dem der Eintrag gehört(e)
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
