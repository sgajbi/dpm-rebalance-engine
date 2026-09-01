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

CREATE TABLE IF NOT EXISTS proposal_idea_intake_purge_events (
    registry_key_digest TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    claim_created_at_utc TIMESTAMPTZ NOT NULL,
    claim_expired_at_utc TIMESTAMPTZ NOT NULL,
    purged_at_utc TIMESTAMPTZ NOT NULL,
    reason_code TEXT NOT NULL,
    PRIMARY KEY (registry_key_digest, claim_expired_at_utc),
    CONSTRAINT ck_proposal_idea_intake_purge_registry_digest
        CHECK (registry_key_digest ~ '^[0-9a-f]{64}:sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_proposal_idea_intake_purge_request_fingerprint
        CHECK (request_fingerprint ~ '^sha256:[0-9a-f]{12}$'),
    CONSTRAINT ck_proposal_idea_intake_purge_retention_window
        CHECK (claim_expired_at_utc = claim_created_at_utc + INTERVAL '24 hours'),
    CONSTRAINT ck_proposal_idea_intake_purge_timestamp_order
        CHECK (purged_at_utc >= claim_expired_at_utc),
    CONSTRAINT ck_proposal_idea_intake_purge_reason
        CHECK (reason_code = 'REPLAY_WINDOW_EXPIRED')
);

CREATE INDEX IF NOT EXISTS idx_proposal_idea_intake_purge_events_purged_at
    ON proposal_idea_intake_purge_events (purged_at_utc, registry_key_digest);
