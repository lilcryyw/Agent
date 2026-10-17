-- Схема когнитивной памяти (SQLite).
-- Правило: журнал событий (events) — источник истины, только добавление.
-- Всё остальное (эпизоды, факты, карточки) можно перестроить из него.

CREATE TABLE IF NOT EXISTS persons (
    id          TEXT PRIMARY KEY,           -- 'owner', 'mama', ...
    name        TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'family' CHECK (role IN ('owner','family','guest')),
    timezone    TEXT NOT NULL DEFAULT 'Europe/Paris',
    entity_id   INTEGER,                    -- сущность-схема этого человека
    created_at  REAL NOT NULL
);

-- Сенсорный журнал: каждая реплика и событие дословно.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    person_id   TEXT NOT NULL REFERENCES persons(id),
    speaker     TEXT NOT NULL CHECK (speaker IN ('user','assistant','device','system')),
    channel     TEXT NOT NULL DEFAULT 'text',
    device      TEXT,
    kind        TEXT NOT NULL DEFAULT 'utterance',
    text        TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}',
    episode_id  INTEGER NOT NULL,
    importance  REAL NOT NULL DEFAULT 0.3,
    emotion     REAL NOT NULL DEFAULT 0.0,
    source_kind TEXT NOT NULL DEFAULT 'user_stated'
                CHECK (source_kind IN ('user_stated','assistant','observed','external')),
    visibility  TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','family')),
    embedding   BLOB
);
CREATE INDEX IF NOT EXISTS ix_events_person_ts ON events(person_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_episode ON events(episode_id);

-- Журнал нельзя менять задним числом. Удаление разрешено только через «забудь» (с аудитом).
CREATE TRIGGER IF NOT EXISTS events_append_only
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events: журнал только для добавления');
END;

-- Эпизоды и иерархические сводки (день/неделя/месяц/год).
CREATE TABLE IF NOT EXISTS episodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    TEXT NOT NULL REFERENCES persons(id),
    level        TEXT NOT NULL DEFAULT 'episode' CHECK (level IN ('episode','day','week','month','year')),
    period_key   TEXT,                       -- '2026-03-14', '2026-W11', '2026-03', '2026'
    start_ts     REAL NOT NULL,
    end_ts       REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','encoded')),
    title        TEXT NOT NULL DEFAULT '',
    gist         TEXT NOT NULL DEFAULT '',
    context      TEXT NOT NULL DEFAULT '{}',
    importance   REAL NOT NULL DEFAULT 0.3,
    surprise     REAL NOT NULL DEFAULT 0.0,
    emotion      REAL NOT NULL DEFAULT 0.0,
    visibility   TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','family')),
    parent_id    INTEGER,
    event_count  INTEGER NOT NULL DEFAULT 0,
    embedding    BLOB,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_episodes_person ON episodes(person_id, level, start_ts);
CREATE UNIQUE INDEX IF NOT EXISTS ux_episodes_period ON episodes(person_id, level, period_key)
    WHERE period_key IS NOT NULL;

-- Сущности-схемы: люди, места, устройства, организации, темы, сам Джарвис.
CREATE TABLE IF NOT EXISTS entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL DEFAULT 'other'
                  CHECK (kind IN ('person','place','device','org','object','topic','pet','self','other')),
    name          TEXT NOT NULL,
    card          TEXT NOT NULL DEFAULT '',  -- карточка-схема (сводка знаний)
    owner_person  TEXT,
    visibility    TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','family')),
    importance    REAL NOT NULL DEFAULT 0.3,
    merged_into   INTEGER,
    embedding     BLOB,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

-- Словарь имён и прозвищ (в нормализованном виде) → сущности.
-- person_scope: для чьей речи действует прозвище («мама» у каждого своя); '' — для всех.
CREATE TABLE IF NOT EXISTS aliases (
    alias_norm   TEXT NOT NULL,
    entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    person_scope TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (alias_norm, entity_id, person_scope)
);

-- Факты: двухвременная модель.
--   valid_from/valid_to      — когда факт был верен в мире;
--   recorded_at/invalidated_at — когда Джарвис его узнал и когда перестал считать актуальным.
-- Старые факты не удаляются, а закрываются.
CREATE TABLE IF NOT EXISTS facts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id       INTEGER NOT NULL REFERENCES entities(id),
    predicate        TEXT NOT NULL,
    object_id        INTEGER REFERENCES entities(id),
    value            TEXT,
    statement        TEXT NOT NULL,
    valid_from       REAL,
    valid_to         REAL,
    recorded_at      REAL NOT NULL,
    invalidated_at   REAL,
    superseded_by    INTEGER,
    confidence       REAL NOT NULL DEFAULT 0.8,
    importance       REAL NOT NULL DEFAULT 0.4,
    protected        INTEGER NOT NULL DEFAULT 0,  -- защищённый факт: менять только с подтверждением
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending_review','rejected')),
    source_kind      TEXT NOT NULL DEFAULT 'user_stated'
                     CHECK (source_kind IN ('user_stated','assistant','observed','inferred','external')),
    source_event_ids TEXT NOT NULL DEFAULT '[]',
    source_episode_id INTEGER,
    owner_person     TEXT,
    visibility       TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','family')),
    embedding        BLOB
);
CREATE INDEX IF NOT EXISTS ix_facts_subject ON facts(subject_id, predicate);
CREATE INDEX IF NOT EXISTS ix_facts_current ON facts(invalidated_at, status);

-- Ассоциативные связи между любыми единицами памяти (с весом — для переконсолидации).
CREATE TABLE IF NOT EXISTS links (
    src_type   TEXT NOT NULL,
    src_id     INTEGER NOT NULL,
    dst_type   TEXT NOT NULL,
    dst_id     INTEGER NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'assoc',
    weight     REAL NOT NULL DEFAULT 0.5,
    updated_at REAL NOT NULL,
    PRIMARY KEY (src_type, src_id, dst_type, dst_id, kind)
);
CREATE INDEX IF NOT EXISTS ix_links_dst ON links(dst_type, dst_id);

-- Следы обращений (ACT-R): создание, извлечение, реальное использование в ответе.
CREATE TABLE IF NOT EXISTS access_traces (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_type TEXT NOT NULL,
    unit_id   INTEGER NOT NULL,
    ts        REAL NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'used' CHECK (kind IN ('created','retrieved','used'))
);
CREATE INDEX IF NOT EXISTS ix_traces_unit ON access_traces(unit_type, unit_id);

-- Процедурная память: рецепты действий.
CREATE TABLE IF NOT EXISTS procedures (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     TEXT,
    name          TEXT NOT NULL,
    trigger_text  TEXT NOT NULL,
    steps         TEXT NOT NULL DEFAULT '[]',
    version       INTEGER NOT NULL DEFAULT 1,
    successes     INTEGER NOT NULL DEFAULT 0,
    failures      INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','candidate','broken','retired')),
    visibility    TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','family')),
    last_used     REAL,
    embedding     BLOB,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

-- Проспективная память: намерения «не забыть».
CREATE TABLE IF NOT EXISTS intentions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id       TEXT NOT NULL,
    trigger_kind    TEXT NOT NULL CHECK (trigger_kind IN ('time','event','person','place')),
    due_ts          REAL,
    trigger_text    TEXT NOT NULL DEFAULT '',
    action_text     TEXT NOT NULL,
    recurrence      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','fired','done','cancelled')),
    source_event_id INTEGER,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_intentions_due ON intentions(status, due_ts);

-- Ядро: то, что всегда в контексте (профиль человека, личность Джарвиса, общее семейное).
CREATE TABLE IF NOT EXISTS core_blocks (
    person_id  TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('profile','self','family')),
    content    TEXT NOT NULL DEFAULT '',
    version    INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (person_id, kind)
);
CREATE TABLE IF NOT EXISTS core_versions (
    person_id TEXT NOT NULL,
    kind      TEXT NOT NULL,
    version   INTEGER NOT NULL,
    content   TEXT NOT NULL,
    ts        REAL NOT NULL,
    reason    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (person_id, kind, version)
);

-- Очередь фоновых задач (идемпотентная: уникальный ключ).
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL UNIQUE,
    payload     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    run_after   REAL NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_ready ON jobs(status, run_after);

-- Аудит всех изменений памяти — для «почему» и для отката.
CREATE TABLE IF NOT EXISTS memory_audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    actor     TEXT NOT NULL,
    op        TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    unit_id   INTEGER,
    before    TEXT,
    after     TEXT,
    reason    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_unit ON memory_audit(unit_type, unit_id);

-- Учёт расхода токенов и денег.
CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    model         TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_read    INTEGER NOT NULL DEFAULT 0,
    cache_write   INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0
);

-- Полнотекстовый индекс по основам слов (русский стемминг делаем сами до записи).
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    unit_type UNINDEXED,
    unit_id UNINDEXED,
    text,
    tokenize = 'unicode61 remove_diacritics 2'
);
