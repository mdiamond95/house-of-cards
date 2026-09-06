-- House of Cards — canonical schema.
--
-- Rebuilt from data/seed + data/reference by scripts/load_seed.py. Everything in
-- outputs/ is regenerated from this database.
--
-- Design notes that are binding (see scenarios/legacy/RECONSTRUCTION.md):
--   * The game runs more than one era-cohort of Section 10 events in parallel, so
--     `events.era_cohort` and `climate.era_cohort` exist and climate is never a
--     single scalar (CLAUDE.md hard rule 8).
--   * There is no universal calendar. Personal clocks are per house
--     (`clocks`, `event_houses.personal_year`) and may be NULL: personal years
--     were not recovered, and a NULL here means "not recovered", never zero.
--   * Nullable name/text columns exist so unrecovered facts can be stored as
--     missing rather than invented (CLAUDE.md hard rule 1).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- reference --

CREATE TABLE ridings (
    fed_id   TEXT PRIMARY KEY,
    name_en  TEXT NOT NULL,
    name_fr  TEXT NOT NULL,
    province TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE
);

CREATE TABLE adjacency (
    fed_id_a       TEXT NOT NULL REFERENCES ridings(fed_id),
    fed_id_b       TEXT NOT NULL REFERENCES ridings(fed_id),
    adjacency_type TEXT NOT NULL CHECK (adjacency_type IN ('land', 'water')),
    PRIMARY KEY (fed_id_a, fed_id_b),
    CHECK (fed_id_a < fed_id_b)
);

CREATE INDEX idx_adjacency_b ON adjacency(fed_id_b);

-- -------------------------------------------------------------- houses etc. --

CREATE TABLE houses (
    house         TEXT PRIMARY KEY,
    peerage       TEXT,
    rank          TEXT,
    status        TEXT NOT NULL CHECK (status IN ('active', 'removed')),
    primary_hex   TEXT,
    secondary_hex TEXT,
    notes         TEXT
);

-- name is nullable precisely so an unrecovered holder can exist as a row without
-- an invented name; confidence carries how well the row is attested.
CREATE TABLE holders (
    id                   INTEGER PRIMARY KEY,
    house                TEXT NOT NULL REFERENCES houses(house),
    name                 TEXT,
    generation           TEXT,
    acceded              TEXT,
    bio_age_at_accession TEXT,
    predecessor          TEXT,
    heir_apparent        TEXT,
    is_current           INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    source               TEXT,
    confidence           TEXT,
    notes                TEXT
);

CREATE INDEX idx_holders_house ON holders(house);
CREATE UNIQUE INDEX idx_holders_one_current_per_house
    ON holders(house) WHERE is_current = 1;

-- Section 5 house blocks: the long-form prose record of a house — founder,
-- holder, heir, holdings, economic/political/cultural position, personal clock.
-- `field` is a free-form label rather than a column per heading, because the
-- workbook's headings varied by house and more are expected as Tier B recovery
-- continues. Narrative may only draw on house detail that is recorded here or
-- in holders/holdings/relations/events (CLAUDE.md hard rule 9).
CREATE TABLE house_blocks (
    house  TEXT NOT NULL REFERENCES houses(house),
    field  TEXT NOT NULL,
    text   TEXT,
    source TEXT,
    PRIMARY KEY (house, field)
);

-- ------------------------------------------------------------------- turns --

CREATE TABLE turns (
    turn_id    INTEGER PRIMARY KEY,
    directive  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL
);

-- ------------------------------------------------------------------ events --

CREATE TABLE events (
    id                INTEGER PRIMARY KEY,
    turn_id           INTEGER REFERENCES turns(turn_id),
    kind              TEXT NOT NULL CHECK (kind IN (
                          'founding', 'expansion', 'relational', 'incursion',
                          'challenge', 'succession', 'societal', 'elevation',
                          'transfer', 'other')),
    era_cohort        TEXT,
    title             TEXT NOT NULL,
    narrative         TEXT,
    mechanical_delta  TEXT,  -- JSON
    source            TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX idx_events_kind ON events(kind);
CREATE INDEX idx_events_era_cohort ON events(era_cohort);

-- personal_year is the event's placement on THAT house's clock; NULL where the
-- placement was never recorded. Global events never sync clocks.
CREATE TABLE event_houses (
    event_id      INTEGER NOT NULL REFERENCES events(id),
    house         TEXT NOT NULL REFERENCES houses(house),
    role          TEXT NOT NULL,
    personal_year INTEGER,
    PRIMARY KEY (event_id, house)
);

CREATE INDEX idx_event_houses_house ON event_houses(house);

-- ---------------------------------------------------------------- holdings --

-- A holding is open while released_event_id IS NULL. History is kept by
-- releasing rather than deleting, so the uniqueness rules are partial.
CREATE TABLE holdings (
    id                INTEGER PRIMARY KEY,
    house             TEXT NOT NULL REFERENCES houses(house),
    fed_id            TEXT NOT NULL REFERENCES ridings(fed_id),
    seat_order        INTEGER NOT NULL,
    hex               TEXT NOT NULL,
    acquired_event_id INTEGER REFERENCES events(id),
    released_event_id INTEGER REFERENCES events(id)
);

CREATE UNIQUE INDEX idx_holdings_one_house_per_riding
    ON holdings(fed_id) WHERE released_event_id IS NULL;
CREATE UNIQUE INDEX idx_holdings_seat_order
    ON holdings(house, seat_order) WHERE released_event_id IS NULL;
CREATE INDEX idx_holdings_house ON holdings(house);

-- ------------------------------------------------------------- successions --

CREATE TABLE successions (
    seq           INTEGER PRIMARY KEY,
    house         TEXT NOT NULL REFERENCES houses(house),
    predecessor   TEXT,
    successor     TEXT,
    transition    TEXT,
    personal_date TEXT,
    nature        TEXT,
    batch         TEXT,
    source        TEXT
);

CREATE INDEX idx_successions_house ON successions(house);

-- --------------------------------------------------------------- relations --

-- marker is the v1 relation glyph vocabulary (◎, +, ◉+, Sig-, ⊖, ⚔, ~) plus
-- 'kin', added in Phase 9c for houses joined by marriage or by partition. It is
-- free text rather than a CHECK because the v1 glyph set was recovered, not
-- specified, and an unrecognised marker must be storable rather than rejected.
CREATE TABLE relations (
    id         INTEGER PRIMARY KEY,
    house_a    TEXT NOT NULL REFERENCES houses(house),
    house_b    TEXT NOT NULL REFERENCES houses(house),
    marker     TEXT,
    event_id   INTEGER REFERENCES events(id),
    event_text TEXT,
    source     TEXT,
    CHECK (house_a <> house_b)
);

CREATE INDEX idx_relations_house_a ON relations(house_a);
CREATE INDEX idx_relations_house_b ON relations(house_b);

-- ----------------------------------------------------------------- climate --

-- cumulative_after is TEXT and stored exactly as the source stated it ("+1",
-- "-2", "0"). The per-event delta rule was never recovered and must not be
-- inferred from these numbers.
-- era_cohort holds an era band id from rules/eras.json ('confederation',
-- 'dominion', 'late') for engine-played games, and the v1 cohort labels for the
-- reconstructed one. Never collapse the ledgers into one number (hard rule 8).
CREATE TABLE climate (
    id               INTEGER PRIMARY KEY,
    era_cohort       TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    event            TEXT NOT NULL,
    magnitude        TEXT,
    tag              TEXT,
    cumulative_after TEXT,
    event_id         INTEGER REFERENCES events(id),
    source           TEXT,
    UNIQUE (era_cohort, seq)
);

-- ------------------------------------------------------------------ clocks --

-- One row per house. personal_year NULL means the clock position was not
-- recovered; basis records what is known about where the clock stands.
CREATE TABLE clocks (
    house         TEXT PRIMARY KEY REFERENCES houses(house),
    personal_year INTEGER,
    basis         TEXT
);

-- ------------------------------------------------- watch / threads / handoff --

CREATE TABLE watch (
    id     INTEGER PRIMARY KEY,
    text   TEXT NOT NULL,
    status TEXT
);

CREATE TABLE threads (
    id   INTEGER PRIMARY KEY,
    text TEXT NOT NULL
);

CREATE TABLE handoff (
    key  TEXT PRIMARY KEY,
    text TEXT
);

-- ------------------------------------------------- autoplay engine (Phase 9c) --

-- The variable half of a house, as §4 defines it. One row per house, created at
-- founding. capital/influence/cohesion are clamped 0-100 and ambition 0-10 by
-- the engine, not by CHECKs: a rule that would push a stat out of range is a bug
-- worth catching in the engine's own clamp, not a constraint that aborts a
-- season mid-write. removed_season is NULL while the house is active.
CREATE TABLE house_stats (
    house           TEXT PRIMARY KEY REFERENCES houses(house),
    capital         INTEGER NOT NULL,
    influence       INTEGER NOT NULL,
    cohesion        INTEGER NOT NULL,
    ambition        INTEGER NOT NULL,
    enclosed        INTEGER NOT NULL DEFAULT 0 CHECK (enclosed IN (0, 1)),
    enclosed_since  INTEGER,
    community       TEXT,
    region          TEXT,
    tradition       TEXT,
    tag             TEXT,
    province        TEXT,
    founded_season  INTEGER,
    removed_season  INTEGER
);

CREATE INDEX idx_house_stats_removed ON house_stats(removed_season);

-- Named people: the holder, up to two named heirs, and anyone else the engine
-- needs to remember. age is biological and is never reset by a clock reset
-- (hard rule 5). A dead person keeps their row: the record is the history.
CREATE TABLE persons (
    id      INTEGER PRIMARY KEY,
    house   TEXT NOT NULL REFERENCES houses(house),
    name    TEXT NOT NULL,
    gender  TEXT,
    age     INTEGER,
    role    TEXT NOT NULL CHECK (role IN ('holder', 'heir', 'heir2', 'other')),
    alive   INTEGER NOT NULL DEFAULT 1 CHECK (alive IN (0, 1)),
    born_season   INTEGER,
    died_season   INTEGER
);

CREATE INDEX idx_persons_house ON persons(house);
CREATE UNIQUE INDEX idx_persons_one_living_holder
    ON persons(house) WHERE role = 'holder' AND alive = 1;

-- A house holds up to three objectives (§5). satisfied_season NULL means still
-- held; a satisfied objective keeps its row so the history stays readable.
CREATE TABLE objectives (
    id                INTEGER PRIMARY KEY,
    house             TEXT NOT NULL REFERENCES houses(house),
    objective         TEXT NOT NULL,
    acquired_season   INTEGER NOT NULL,
    satisfied_season  INTEGER
);

CREATE INDEX idx_objectives_house ON objectives(house);

-- One row per played season: the seed it was played under, where its log lives,
-- and the two counts the smoke test watches. rules_version records which
-- rules/CHANGELOG.md version the season was played under, so a later rules
-- change never silently reinterprets an old season (§11).
CREATE TABLE seasons (
    season_no      INTEGER PRIMARY KEY,
    seed           INTEGER NOT NULL,
    json_path      TEXT,
    houses_after   INTEGER NOT NULL,
    ridings_after  INTEGER NOT NULL,
    rules_version  TEXT,
    created_at     TEXT
);

-- ------------------------------------------------------------------- views --

-- Hard rule 4: the primary colour is the colour of the principal seat, which is
-- the seat_order = 1 holding — never a count-based or rarity rule. Secondary is
-- the seat_order = 2 holding where the house holds one, else the colour recorded
-- on the house. The COALESCE on primary keeps a retired house's recorded palette
-- visible after its holdings are gone.
CREATE VIEW v_house_colours AS
SELECT
    h.house                                AS house,
    COALESCE(seat1.hex, h.primary_hex)     AS primary_hex,
    COALESCE(seat2.hex, h.secondary_hex)   AS secondary_hex
FROM houses h
LEFT JOIN holdings seat1
       ON seat1.house = h.house
      AND seat1.seat_order = 1
      AND seat1.released_event_id IS NULL
LEFT JOIN holdings seat2
       ON seat2.house = h.house
      AND seat2.seat_order = 2
      AND seat2.released_event_id IS NULL;

-- Latest recorded climate position per era-cohort. Never collapse these rows
-- into a single number (hard rule 8).
CREATE VIEW v_current_climate AS
SELECT c.era_cohort, c.cumulative_after
FROM climate c
JOIN (
    SELECT era_cohort, MAX(seq) AS max_seq
    FROM climate
    GROUP BY era_cohort
) latest
  ON latest.era_cohort = c.era_cohort
 AND latest.max_seq = c.seq;
