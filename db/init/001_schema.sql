-- Core relational schema for SUPPLYCHAIN-X.
-- Postgres holds reference data + analytical results the API serves.
-- The raw/big data stays in the Parquet lake; the graph lives in Neo4j.

CREATE TABLE countries (
    country_id   SERIAL PRIMARY KEY,
    iso3         CHAR(3) UNIQUE NOT NULL,      -- e.g. IND, CHN
    country_name TEXT NOT NULL,
    region       TEXT,
    latitude     DOUBLE PRECISION,
    longitude    DOUBLE PRECISION
);

CREATE TABLE commodities (
    commodity_id   SERIAL PRIMARY KEY,
    hs_code        VARCHAR(6) UNIQUE NOT NULL, -- HS2 / HS4 / HS6
    commodity_name TEXT NOT NULL,
    category       TEXT
);

CREATE TABLE ports (
    port_id    SERIAL PRIMARY KEY,
    port_name  TEXT NOT NULL,
    country_id INT REFERENCES countries(country_id),
    latitude   DOUBLE PRECISION,
    longitude  DOUBLE PRECISION,
    capacity   TEXT                            -- World Port Index gives a size class, not a number
);

-- Aggregated trade flows (gold layer is loaded here, not the full raw dump)
CREATE TABLE trade (
    trade_id         BIGSERIAL PRIMARY KEY,
    year             SMALLINT NOT NULL,
    month            SMALLINT,
    reporter_country INT NOT NULL REFERENCES countries(country_id),
    partner_country  INT NOT NULL REFERENCES countries(country_id),
    commodity_id     INT NOT NULL REFERENCES commodities(commodity_id),
    flow             VARCHAR(1) NOT NULL CHECK (flow IN ('M', 'X')),  -- import / export
    trade_value      NUMERIC(20, 2),
    quantity         NUMERIC(20, 2)
);
CREATE INDEX idx_trade_lookup ON trade (partner_country, commodity_id, year);

CREATE TABLE events (
    event_id   TEXT PRIMARY KEY,              -- keep the source id (GDACS / EM-DAT / replay id)
    ts         TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    country_id INT REFERENCES countries(country_id),
    port_id    INT REFERENCES ports(port_id),
    latitude   DOUBLE PRECISION,
    longitude  DOUBLE PRECISION,
    severity   REAL CHECK (severity BETWEEN 0 AND 1),
    source     TEXT
);
CREATE INDEX idx_events_ts ON events (ts);

-- How much target_country relies on source_country for a commodity
CREATE TABLE dependencies (
    dependency_id    BIGSERIAL PRIMARY KEY,
    source_country   INT NOT NULL REFERENCES countries(country_id),
    target_country   INT NOT NULL REFERENCES countries(country_id),
    commodity_id     INT NOT NULL REFERENCES commodities(commodity_id),
    year             SMALLINT NOT NULL,
    trade_share      REAL,                    -- share of target's imports from source
    dependency_score REAL,
    UNIQUE (source_country, target_country, commodity_id, year)
);

CREATE TABLE impact_scores (
    impact_id        BIGSERIAL PRIMARY KEY,
    event_id         TEXT NOT NULL REFERENCES events(event_id),
    entity_type      TEXT NOT NULL,           -- country / commodity / port / industry
    entity_id        TEXT NOT NULL,
    hop_level        SMALLINT NOT NULL,       -- 0 = directly hit
    exposure_score   REAL,
    centrality_score REAL,
    impact_score     REAL,
    created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_impact_event ON impact_scores (event_id);

CREATE TABLE alerts (
    alert_id   BIGSERIAL PRIMARY KEY,
    event_id   TEXT REFERENCES events(event_id),
    severity   TEXT CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    message    TEXT,
    status     TEXT DEFAULT 'OPEN',
    created_at TIMESTAMPTZ DEFAULT now()
);
