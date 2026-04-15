-- Migration 001 — schema inicial obsidian-master-kit.
-- Ref: docs/BRIEF-v1.md §4.
-- PRAGMAs (foreign_keys, journal_mode=WAL, synchronous=NORMAL) aplicados em connect().
-- vec_notes (virtual table vec0) eh criada em ensure_schema() DEPOIS das migrations,
-- somente se sqlite-vec carregou com sucesso. notes_embedding_blob eh o fallback.

-- ---------------------------------------------------------------------------
-- schema_version — controle idempotente de migrations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- areas — areas dinamicas descobertas via HDBSCAN (Opcao C)
-- ---------------------------------------------------------------------------
CREATE TABLE areas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    label        TEXT    NOT NULL,
    folder       TEXT,
    is_canonical INTEGER NOT NULL DEFAULT 0,
    sensitive    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- notes — linha por arquivo .md
-- ---------------------------------------------------------------------------
CREATE TABLE notes (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    path                     TEXT    NOT NULL UNIQUE,
    title                    TEXT,
    area_id                  INTEGER,
    type                     TEXT,
    status                   TEXT,
    created                  TEXT,
    updated                  TEXT,
    mtime                    REAL,
    word_count               INTEGER,
    char_count               INTEGER,
    body_hash                TEXT,
    frontmatter_json         TEXT,
    confidence               REAL,
    source                   TEXT,
    project                  TEXT,
    generated_by             TEXT,
    sensitive                INTEGER NOT NULL DEFAULT 0,
    embedding_model          TEXT,
    embedding_dim            INTEGER,
    embedding_generated_at   TEXT,
    in_degree                INTEGER NOT NULL DEFAULT 0,
    out_degree               INTEGER NOT NULL DEFAULT 0,
    pagerank                 REAL,
    indexed_at               TEXT,
    deleted_at               TEXT,
    FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- notes_embedding_blob — fallback de embedding quando sqlite-vec nao carrega
-- ---------------------------------------------------------------------------
CREATE TABLE notes_embedding_blob (
    note_id INTEGER PRIMARY KEY,
    vec     BLOB NOT NULL,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- tags — tags hierarquicas como path string (ex: "profissional/projeto")
-- ---------------------------------------------------------------------------
CREATE TABLE tags (
    id  INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT    NOT NULL UNIQUE COLLATE NOCASE
);

-- ---------------------------------------------------------------------------
-- note_tags — N:N entre notes e tags
-- ---------------------------------------------------------------------------
CREATE TABLE note_tags (
    note_id INTEGER NOT NULL,
    tag_id  INTEGER NOT NULL,
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id)  REFERENCES tags(id)  ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- aliases — apelidos declarados no frontmatter de uma nota
-- ---------------------------------------------------------------------------
CREATE TABLE aliases (
    note_id INTEGER NOT NULL,
    alias   TEXT    NOT NULL,
    PRIMARY KEY (note_id, alias),
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- links — preserva intencao mesmo quando link eh quebrado
-- to_note_id eh nullable; to_target guarda o alvo cru (resolve depois)
-- ---------------------------------------------------------------------------
CREATE TABLE links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_note_id    INTEGER NOT NULL,
    to_note_id      INTEGER,
    to_target       TEXT    NOT NULL,
    link_type       TEXT    NOT NULL DEFAULT 'wikilink',
    context_snippet TEXT,
    FOREIGN KEY (from_note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (to_note_id)   REFERENCES notes(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- events — serie temporal, 10 event_types validados por CHECK
-- ---------------------------------------------------------------------------
CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id       INTEGER,
    area_id       INTEGER,
    event_type    TEXT    NOT NULL CHECK (event_type IN (
        'note_created',
        'note_updated',
        'note_deleted',
        'link_added',
        'link_removed',
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

-- ---------------------------------------------------------------------------
-- clusters — output do HDBSCAN
-- ---------------------------------------------------------------------------
CREATE TABLE clusters (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT    NOT NULL,
    label                TEXT,
    label_source         TEXT,
    algorithm            TEXT    NOT NULL,
    similarity_threshold REAL,
    note_count           INTEGER NOT NULL DEFAULT 0,
    proposed_area_id     INTEGER,
    proposed_moc_path    TEXT,
    created_at           TEXT    NOT NULL,
    FOREIGN KEY (proposed_area_id) REFERENCES areas(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- cluster_notes — N:N entre clusters e notes
-- ---------------------------------------------------------------------------
CREATE TABLE cluster_notes (
    cluster_id           INTEGER NOT NULL,
    note_id              INTEGER NOT NULL,
    distance_to_centroid REAL,
    PRIMARY KEY (cluster_id, note_id),
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE,
    FOREIGN KEY (note_id)    REFERENCES notes(id)    ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- duplicate_candidates — pares com cos >= 0.92 esperando verdict humano
-- ---------------------------------------------------------------------------
CREATE TABLE duplicate_candidates (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    note_a_id          INTEGER NOT NULL,
    note_b_id          INTEGER NOT NULL,
    cosine_similarity  REAL    NOT NULL,
    detected_at        TEXT    NOT NULL,
    verdict            TEXT,
    FOREIGN KEY (note_a_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (note_b_id) REFERENCES notes(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- suggestions_cache — TTL 24h, reasoning NOT NULL (anti-opacidade)
-- ---------------------------------------------------------------------------
CREATE TABLE suggestions_cache (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at     TEXT    NOT NULL,
    expires_at       TEXT    NOT NULL,
    kind             TEXT    NOT NULL,
    target_note_ids  TEXT    NOT NULL,
    content          TEXT    NOT NULL,
    reasoning        TEXT    NOT NULL,
    score            REAL,
    dismissed        INTEGER NOT NULL DEFAULT 0,
    dismissed_at     TEXT,
    acted_on         INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- alerts_cache — severity so pode ser 'info' ou 'warn' (anti-tom-vigilante)
-- ---------------------------------------------------------------------------
CREATE TABLE alerts_cache (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at     TEXT    NOT NULL,
    expires_at       TEXT    NOT NULL,
    kind             TEXT    NOT NULL,
    target_note_ids  TEXT    NOT NULL,
    content          TEXT    NOT NULL,
    reasoning        TEXT    NOT NULL,
    severity         TEXT    NOT NULL CHECK (severity IN ('info', 'warn')),
    dismissed        INTEGER NOT NULL DEFAULT 0,
    dismissed_at     TEXT
);

-- ---------------------------------------------------------------------------
-- migration_plan — Opcao C por batch
-- ---------------------------------------------------------------------------
CREATE TABLE migration_plan (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path          TEXT    NOT NULL,
    current_location   TEXT    NOT NULL,
    proposed_location  TEXT    NOT NULL,
    proposed_area_id   INTEGER,
    cluster_id         INTEGER,
    reason             TEXT,
    confidence         REAL,
    batch_id           INTEGER NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',
    decided_at         TEXT,
    applied_at         TEXT,
    FOREIGN KEY (proposed_area_id) REFERENCES areas(id)    ON DELETE SET NULL,
    FOREIGN KEY (cluster_id)       REFERENCES clusters(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- temporal_patterns — pre-computado para dashboard (<50ms)
-- ---------------------------------------------------------------------------
CREATE TABLE temporal_patterns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type  TEXT    NOT NULL,
    detected_at   TEXT    NOT NULL,
    confidence    REAL,
    metadata_json TEXT
);

-- ===========================================================================
-- Indexes criticos (BRIEF §4)
-- ===========================================================================
CREATE INDEX idx_notes_area    ON notes(area_id);
CREATE INDEX idx_notes_updated ON notes(updated DESC);
CREATE INDEX idx_notes_mtime   ON notes(mtime DESC);
CREATE INDEX idx_notes_hash    ON notes(body_hash);

-- Prefix-aware: permite range queries tipo tag LIKE 'profissional/%'
CREATE INDEX idx_tags_prefix   ON tags(tag COLLATE NOCASE);

CREATE INDEX idx_note_tags_tag ON note_tags(tag_id);

CREATE INDEX idx_links_from    ON links(from_note_id);
CREATE INDEX idx_links_to      ON links(to_note_id);
CREATE INDEX idx_links_target  ON links(to_target);

CREATE INDEX idx_events_ts         ON events(ts);
CREATE INDEX idx_events_date_type  ON events(date, event_type);
CREATE INDEX idx_events_area_date  ON events(area_id, date);
CREATE INDEX idx_events_note       ON events(note_id);

CREATE INDEX idx_sugg_active       ON suggestions_cache(dismissed, kind, expires_at);

CREATE INDEX idx_migration_batch   ON migration_plan(batch_id, status);
