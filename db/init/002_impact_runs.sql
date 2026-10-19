-- Full impact-engine output per event (paths, shares, weather evidence) for the API / UI.
-- impact_scores keeps the per-entity numbers for SQL; this keeps the whole story.
CREATE TABLE IF NOT EXISTS impact_runs (
    event_id   TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    result     JSONB NOT NULL,
    max_score  REAL,
    countries  INT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_impact_runs_score ON impact_runs (max_score DESC);
