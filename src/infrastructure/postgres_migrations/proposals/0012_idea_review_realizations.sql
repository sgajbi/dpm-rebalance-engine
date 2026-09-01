CREATE TABLE IF NOT EXISTS proposal_idea_review_realizations (
    realization_id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL,
    source_claim_registry_key TEXT NOT NULL,
    review_work_id TEXT UNIQUE,
    review_work_status TEXT,
    tenant_id TEXT NOT NULL,
    legal_entity_code TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    idea_candidate_id TEXT NOT NULL,
    conversion_intent_id TEXT NOT NULL,
    source_evidence_fingerprint TEXT NOT NULL,
    current_status TEXT NOT NULL,
    current_source_event_version INTEGER NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_proposal_idea_realization_conversion_scope
        UNIQUE (tenant_id, legal_entity_code, portfolio_id, conversion_intent_id),
    CONSTRAINT uq_proposal_idea_realization_intake_scope
        UNIQUE (tenant_id, legal_entity_code, portfolio_id, intake_id),
    CONSTRAINT ck_proposal_idea_realization_id
        CHECK (realization_id ~ '^ipr_[0-9a-f]{12}$'),
    CONSTRAINT ck_proposal_idea_realization_source_claim
        CHECK (source_claim_registry_key ~ '^[0-9a-f]{64}:sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_proposal_idea_review_work_id
        CHECK (review_work_id IS NULL OR review_work_id ~ '^iarw_[0-9a-f]{12}$'),
    CONSTRAINT ck_proposal_idea_realization_required_scope
        CHECK (
            tenant_id = BTRIM(tenant_id) AND tenant_id <> ''
            AND legal_entity_code = BTRIM(legal_entity_code) AND legal_entity_code <> ''
            AND portfolio_id = BTRIM(portfolio_id) AND portfolio_id <> ''
        ),
    CONSTRAINT ck_proposal_idea_realization_source_evidence
        CHECK (source_evidence_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_proposal_idea_realization_status
        CHECK (current_status IN ('ACCEPTED_FOR_REVIEW', 'REJECTED_BEFORE_WORK')),
    CONSTRAINT ck_proposal_idea_review_work_status
        CHECK (review_work_status IS NULL OR review_work_status = 'PENDING_ADVISER_REVIEW'),
    CONSTRAINT ck_proposal_idea_realization_work_posture
        CHECK (
            (
                current_status = 'ACCEPTED_FOR_REVIEW'
                AND review_work_id IS NOT NULL
                AND review_work_status = 'PENDING_ADVISER_REVIEW'
            ) OR (
                current_status = 'REJECTED_BEFORE_WORK'
                AND review_work_id IS NULL
                AND review_work_status IS NULL
            )
        ),
    CONSTRAINT ck_proposal_idea_realization_event_version
        CHECK (current_source_event_version >= 1),
    CONSTRAINT ck_proposal_idea_realization_timestamp_order
        CHECK (updated_at_utc >= created_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_proposal_idea_review_realizations_scope
    ON proposal_idea_review_realizations (
        tenant_id, legal_entity_code, portfolio_id, created_at_utc, realization_id
    );

CREATE TABLE IF NOT EXISTS proposal_idea_realization_outcomes (
    outcome_id TEXT PRIMARY KEY,
    realization_id TEXT NOT NULL
        REFERENCES proposal_idea_review_realizations(realization_id) ON DELETE RESTRICT,
    source_event_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    occurred_at_utc TIMESTAMPTZ NOT NULL,
    review_work_id TEXT,
    proposal_id TEXT,
    terminal BOOLEAN NOT NULL,
    CONSTRAINT uq_proposal_idea_realization_outcome_version
        UNIQUE (realization_id, source_event_version),
    CONSTRAINT ck_proposal_idea_realization_outcome_id
        CHECK (outcome_id ~ '^ipro_[0-9a-f]{12}$'),
    CONSTRAINT ck_proposal_idea_realization_outcome_version
        CHECK (source_event_version >= 1),
    CONSTRAINT ck_proposal_idea_realization_outcome_status
        CHECK (status IN ('ACCEPTED_FOR_REVIEW', 'REJECTED_BEFORE_WORK')),
    CONSTRAINT ck_proposal_idea_realization_outcome_reason
        CHECK (
            reason_code IN (
                'idea_conversion_accepted_for_adviser_review',
                'idea_conversion_rejected_before_advisory_work'
            )
        ),
    CONSTRAINT ck_proposal_idea_realization_outcome_initial_posture
        CHECK (
            (
                status = 'ACCEPTED_FOR_REVIEW'
                AND review_work_id IS NOT NULL
                AND proposal_id IS NULL
                AND terminal = FALSE
            ) OR (
                status = 'REJECTED_BEFORE_WORK'
                AND review_work_id IS NULL
                AND proposal_id IS NULL
                AND terminal = TRUE
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_proposal_idea_realization_outcomes_history
    ON proposal_idea_realization_outcomes (realization_id, source_event_version);
