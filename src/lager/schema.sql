-- Lager-Index — Schema-Version 1
--
-- Diese Datenbank ist ein ABGELEITETER Index. Die Quelle der Wahrheit sind die
-- Ordner und part.yaml-Dateien im Lager-Root. `lager index rebuild` leert alle
-- Tabellen dieser Datei und füllt sie aus den Ordnern neu.
--
-- Regeln (KONZEPT.md §8, Entscheidung D6 — sprachneutrale Daten):
--   * nur TEXT (UTF-8), INTEGER, REAL
--   * Zeitpunkte als ISO-8601-Text in UTC, z. B. 2026-11-12T14:03:00Z
--   * Wahrheitswerte als 0/1
--   * Pfade relativ und mit '/' als Trenner, nie absolut (das Lager bleibt verschiebbar)
--   * parts.id und files.id sind NICHT stabil über einen Neuaufbau hinweg.
--     Dauerhafte Verweise nutzen parts.rel_path.

-- Angaben zum Index selbst: built_at (Zeitpunkt des letzten Aufbaus), generator.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Kategorien = Ordner der ersten Ebene im Lager-Root.
CREATE TABLE categories (
    id       TEXT PRIMARY KEY,                          -- Ordnername
    label    TEXT NOT NULL,                             -- Anzeigename aus categories.yaml
    position INTEGER NOT NULL,                          -- Anzeige-Reihenfolge
    listed   INTEGER NOT NULL CHECK (listed IN (0, 1))  -- 1 = in categories.yaml eingetragen
);

-- Bauteile = Ordner mit einer part.yaml.
CREATE TABLE parts (
    id           INTEGER PRIMARY KEY,
    part         TEXT NOT NULL,                         -- Bezeichnung = Ordnername
    category_id  TEXT NOT NULL REFERENCES categories(id),
    subcategory  TEXT NOT NULL DEFAULT '',              -- Ordner zwischen Kategorie und Bauteil
    rel_path     TEXT NOT NULL UNIQUE,                  -- z. B. mosfets/IRLZ44N
    name         TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    quantity     INTEGER NOT NULL DEFAULT 0,
    unit         TEXT NOT NULL DEFAULT '',
    location     TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    -- Alle Suchfelder in Kleinbuchstaben, durch Leerzeichen getrennt:
    -- Bezeichnung, Name, Hersteller, Aliase, Tags, Kategorie, Unterkategorie, Lagerfach.
    -- Suche: search_text LIKE '%begriff%' mit dem Begriff in Kleinbuchstaben.
    search_text  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX parts_part ON parts (part COLLATE NOCASE);
CREATE INDEX parts_category ON parts (category_id);

CREATE TABLE part_aliases (
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL,
    PRIMARY KEY (part_id, alias)
);

CREATE TABLE part_tags (
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (part_id, tag)
);

-- Dateien in einem Bauteil-Ordner (ohne part.yaml und ohne versteckte Dateien).
CREATE TABLE files (
    id       INTEGER PRIMARY KEY,
    part_id  INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,     -- relativ zum Bauteil-Ordner, z. B. kicad/TO-220.kicad_mod
    kind     TEXT NOT NULL,     -- datasheet | cad3d | kicad | image | other (einstellbar)
    ext      TEXT NOT NULL,     -- Dateiendung klein, ohne Punkt
    size     INTEGER NOT NULL,  -- Bytes
    mtime    TEXT NOT NULL,     -- letzte Änderung, ISO 8601 UTC
    UNIQUE (part_id, rel_path)
);

CREATE INDEX files_part ON files (part_id);
CREATE INDEX files_kind ON files (kind);

PRAGMA user_version = 1;
