CREATE TABLE IF NOT EXISTS proposal_idea_intakes (
    registry_key TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proposal_idea_intakes_created_at
    ON proposal_idea_intakes (created_at_utc, registry_key);
