-- 002_add_note_moved_event.sql
-- Adiciona 'note_moved' ao CHECK constraint de events.event_type.
-- SQLite nao suporta ALTER CHECK diretamente; rebuild da tabela.
-- Preserva exatamente a estrutura de 001_initial (FKs ON DELETE SET NULL,
-- AUTOINCREMENT no id) — essa migration SO adiciona um valor ao CHECK.

PRAGMA foreign_keys=OFF;

CREATE TABLE events_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id       INTEGER,
    area_id       INTEGER,
    event_type    TEXT    NOT NULL CHECK (event_type IN (
        'note_created',
        'note_updated',
        'note_deleted',
        'link_added',
        'link_removed',
        'note_moved',
        'dashboard_open',
        'scan_run',
        'suggestion_shown',
        'suggestion_accepted',
        'suggestion_dismissed'
    )),
    ts            TEXT    NOT NULL,
    date          TEXT    NOT NULL,
    word_delta    INTEGER,
    metadata_json TEXT,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE SET NULL,
    FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE SET NULL
);

INSERT INTO events_new(id, note_id, area_id, event_type, ts, date, word_delta, metadata_json)
  SELECT id, note_id, area_id, event_type, ts, date, word_delta, metadata_json FROM events;

DROP TABLE events;
ALTER TABLE events_new RENAME TO events;

CREATE INDEX idx_events_ts ON events(ts);
CREATE INDEX idx_events_date_type ON events(date, event_type);
CREATE INDEX idx_events_area_date ON events(area_id, date);
CREATE INDEX idx_events_note ON events(note_id);

PRAGMA foreign_keys=ON;
