WITH recovered_claims AS (
    SELECT COALESCE(
        jsonb_typeof(response_json::jsonb) = 'object'
        AND response_json::jsonb ?& ARRAY[
            'intake_id', 'intake_status', 'supportability_status', 'source_authority',
            'proposal_authority', 'target_product', 'route_existence_proven',
            'portfolio_id',
            'intake_receipt_accepted', 'idempotency_replay', 'idempotency_key_hash',
            'request_fingerprint', 'trusted_scope', 'outcome_reason_codes',
            'proposal_record_created', 'suitability_authority_granted', 'order_created',
            'client_publication_authorized', 'certification_blockers', 'evidence_refs',
            'received_at', 'correlation_id'
        ]
        AND registry_key ~ '^[0-9a-f]{64}:sha256:[0-9a-f]{64}$'
        AND request_fingerprint ~ '^sha256:[0-9a-f]{12}$'
        AND response_json::jsonb ->> 'intake_id' ~ '^ipi_[0-9a-f]{12}$'
        AND response_json::jsonb ->> 'idempotency_key_hash' ~ '^sha256:[0-9a-f]{12}$'
        AND response_json::jsonb ->> 'request_fingerprint' = request_fingerprint
        AND response_json::jsonb ->> 'supportability_status' = 'not_certified'
        AND response_json::jsonb ->> 'source_authority' = 'lotus-idea'
        AND response_json::jsonb ->> 'proposal_authority' = 'lotus-advise'
        AND response_json::jsonb ->> 'target_product'
            = 'lotus-advise:AdvisoryProposalLifecycleRecord:v1'
        AND length(btrim(response_json::jsonb ->> 'portfolio_id')) BETWEEN 1 AND 160
        AND response_json::jsonb ->> 'portfolio_id'
            = btrim(response_json::jsonb ->> 'portfolio_id')
        AND response_json::jsonb ->> 'portfolio_id' !~ '[[:cntrl:]]'
        AND (response_json::jsonb ->> 'route_existence_proven')::boolean IS TRUE
        AND (response_json::jsonb ->> 'proposal_record_created')::boolean IS FALSE
        AND (response_json::jsonb ->> 'suitability_authority_granted')::boolean IS FALSE
        AND (response_json::jsonb ->> 'order_created')::boolean IS FALSE
        AND (response_json::jsonb ->> 'client_publication_authorized')::boolean IS FALSE
        AND (response_json::jsonb ->> 'idempotency_replay')::boolean IS FALSE
        AND response_json::jsonb ->> 'intake_status' IN ('ACCEPTED', 'REJECTED')
        AND (
            (
                response_json::jsonb ->> 'intake_status' = 'ACCEPTED'
                AND (response_json::jsonb ->> 'intake_receipt_accepted')::boolean IS TRUE
                AND response_json::jsonb -> 'outcome_reason_codes'
                    = '["idea_intake_receipt_accepted"]'::jsonb
            )
            OR (
                response_json::jsonb ->> 'intake_status' = 'REJECTED'
                AND (response_json::jsonb ->> 'intake_receipt_accepted')::boolean IS FALSE
                AND response_json::jsonb -> 'outcome_reason_codes'
                    = '["advisory_proposal_creation_not_certified", "idea_intake_receipt_rejected_no_proposal_created"]'::jsonb
            )
        )
        AND response_json::jsonb -> 'certification_blockers' = '[
            "suitability_policy_authority_remains_lotus_advise",
            "advisory_proposal_creation_not_certified",
            "advisory_review_work_realization_not_certified",
            "source_owned_outcome_stream_not_certified",
            "client_publication_authority_blocked"
        ]'::jsonb
        AND response_json::jsonb -> 'evidence_refs' = '[
            "contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json",
            "src/api/proposals/routes_idea_intake.py",
            "src/core/proposals/idea_proposal_intake.py",
            "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql"
        ]'::jsonb
        AND (response_json::jsonb ->> 'received_at')::timestamptz = created_at_utc
        AND length(response_json::jsonb ->> 'correlation_id') > 0
        AND jsonb_typeof(response_json::jsonb -> 'trusted_scope') = 'object'
        AND response_json::jsonb -> 'trusted_scope' ?& ARRAY[
            'subject', 'role', 'tenant_id', 'legal_entity_code', 'correlation_id',
            'service_identity', 'capability'
        ]
        AND response_json::jsonb -> 'trusted_scope' ->> 'role' = 'SERVICE'
        AND response_json::jsonb -> 'trusted_scope' ->> 'service_identity' = 'lotus-idea'
        AND response_json::jsonb -> 'trusted_scope' ->> 'capability'
            = 'advisory.idea_proposal_intake.accept'
        AND response_json::jsonb -> 'trusted_scope' ->> 'correlation_id'
            = response_json::jsonb ->> 'correlation_id'
        AND expires_at_utc = created_at_utc + INTERVAL '24 hours'
        AND pg_typeof(legal_hold) = 'boolean'::regtype,
        FALSE
    ) AS is_valid
    FROM proposal_idea_intakes
), recovered_purge_events AS (
    SELECT COALESCE(
        registry_key_digest ~ '^[0-9a-f]{64}:sha256:[0-9a-f]{64}$'
        AND request_fingerprint ~ '^sha256:[0-9a-f]{12}$'
        AND claim_expired_at_utc = claim_created_at_utc + INTERVAL '24 hours'
        AND purged_at_utc >= claim_expired_at_utc
        AND reason_code = 'REPLAY_WINDOW_EXPIRED',
        FALSE
    ) AS is_valid
    FROM proposal_idea_intake_purge_events
)
SELECT
    COALESCE((SELECT bool_and(is_valid) FROM recovered_claims), TRUE)
    AND COALESCE((SELECT bool_and(is_valid) FROM recovered_purge_events), TRUE);
