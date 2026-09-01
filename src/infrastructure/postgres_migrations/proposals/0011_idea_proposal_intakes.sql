CREATE TABLE IF NOT EXISTS proposal_idea_intakes (
    registry_key TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    expires_at_utc TIMESTAMPTZ NOT NULL,
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_proposal_idea_intakes_retention_window
        CHECK (expires_at_utc > created_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_proposal_idea_intakes_expiry
    ON proposal_idea_intakes (expires_at_utc, registry_key)
    WHERE legal_hold = FALSE;
