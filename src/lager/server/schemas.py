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
