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
        AND (
            (
                NOT response_json::jsonb ?| ARRAY[
                    'realization_id', 'review_work_id', 'review_work_status',
                    'realization_status', 'source_event_version',
                    'source_evidence_fingerprint'
                ]
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
            )
            OR (
                response_json::jsonb ?& ARRAY[
                    'realization_id', 'review_work_id', 'review_work_status',
                    'realization_status', 'source_event_version',
                    'source_evidence_fingerprint'
                ]
                AND response_json::jsonb ->> 'realization_id' ~ '^ipr_[0-9a-f]{12}$'
                AND (response_json::jsonb ->> 'source_event_version')::integer = 1
                AND response_json::jsonb ->> 'source_evidence_fingerprint'
                    ~ '^sha256:[0-9a-f]{64}$'
                AND (
                    (
                        response_json::jsonb ->> 'intake_status' = 'ACCEPTED'
                        AND response_json::jsonb ->> 'realization_status'
                            = 'ACCEPTED_FOR_REVIEW'
                        AND response_json::jsonb ->> 'review_work_id'
                            ~ '^iarw_[0-9a-f]{12}$'
                        AND response_json::jsonb ->> 'review_work_status'
                            = 'PENDING_ADVISER_REVIEW'
                    )
                    OR (
                        response_json::jsonb ->> 'intake_status' = 'REJECTED'
                        AND response_json::jsonb ->> 'realization_status'
                            = 'REJECTED_BEFORE_WORK'
                        AND response_json::jsonb -> 'review_work_id' = 'null'::jsonb
                        AND response_json::jsonb -> 'review_work_status' = 'null'::jsonb
                    )
                )
                AND response_json::jsonb -> 'certification_blockers' = '[
                    "suitability_policy_authority_remains_lotus_advise",
                    "advisory_proposal_creation_not_certified",
                    "proposal_linkage_outcome_not_certified",
                    "terminal_realization_outcomes_not_certified",
                    "client_publication_authority_blocked"
                ]'::jsonb
                AND response_json::jsonb -> 'evidence_refs' = '[
                    "contracts/idea-proposal-intake/lotus-advise-idea-proposal-intake.v1.json",
                    "src/api/proposals/routes_idea_intake.py",
                    "src/core/proposals/idea_proposal_intake.py",
                    "src/core/proposals/idea_review_realization.py",
                    "src/infrastructure/postgres_migrations/proposals/0011_idea_proposal_intakes.sql",
                    "src/infrastructure/postgres_migrations/proposals/0012_idea_review_realizations.sql"
                ]'::jsonb
                AND EXISTS (
                    SELECT 1
                    FROM proposal_idea_review_realizations realization
                    WHERE realization.intake_id = response_json::jsonb ->> 'intake_id'
                      AND realization.realization_id
                          = response_json::jsonb ->> 'realization_id'
                      AND realization.tenant_id
                          = response_json::jsonb -> 'trusted_scope' ->> 'tenant_id'
                      AND realization.legal_entity_code
                          = response_json::jsonb -> 'trusted_scope' ->> 'legal_entity_code'
                      AND realization.portfolio_id
                          = response_json::jsonb ->> 'portfolio_id'
                      AND realization.review_work_id IS NOT DISTINCT FROM
                          response_json::jsonb ->> 'review_work_id'
                      AND realization.review_work_status IS NOT DISTINCT FROM
                          response_json::jsonb ->> 'review_work_status'
                      AND realization.current_status
                          = response_json::jsonb ->> 'realization_status'
                      AND realization.current_source_event_version
                          = (response_json::jsonb ->> 'source_event_version')::integer
                      AND realization.source_evidence_fingerprint
                          = response_json::jsonb ->> 'source_evidence_fingerprint'
                )
            )
        )
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
), recovered_realizations AS (
    SELECT COALESCE(
        realization_id ~ '^ipr_[0-9a-f]{12}$'
        AND intake_id ~ '^ipi_[0-9a-f]{12}$'
        AND source_evidence_fingerprint ~ '^sha256:[0-9a-f]{64}$'
        AND idea_candidate_id = btrim(idea_candidate_id) AND idea_candidate_id <> ''
        AND idea_candidate_id !~ '[[:cntrl:]]'
        AND conversion_intent_id = btrim(conversion_intent_id)
        AND conversion_intent_id <> ''
        AND conversion_intent_id !~ '[[:cntrl:]]'
        AND tenant_id = btrim(tenant_id) AND tenant_id <> ''
        AND legal_entity_code = btrim(legal_entity_code) AND legal_entity_code <> ''
        AND portfolio_id = btrim(portfolio_id) AND portfolio_id <> ''
        AND current_source_event_version = 1
        AND intake_id = 'ipi_' || left(
            encode(
                sha256(
                    convert_to(
                        idea_candidate_id || '|' || conversion_intent_id || '|'
                            || CASE current_status
                                WHEN 'ACCEPTED_FOR_REVIEW'
                                    THEN 'REVIEW_FOR_ADVISORY_PROPOSAL'
                                ELSE 'CREATE_ADVISORY_PROPOSAL_DRAFT'
                            END
                            || '|' || portfolio_id || '|'
                            || split_part(source_evidence_fingerprint, ':', 2),
                        'UTF8'
                    )
                ),
                'hex'
            ),
            12
        )
        AND realization_id = 'ipr_' || left(
            encode(
                sha256(
                    convert_to(
                        tenant_id || '|' || legal_entity_code || '|' || portfolio_id || '|'
                            || conversion_intent_id,
                        'UTF8'
                    )
                ),
                'hex'
            ),
            12
        )
        AND updated_at_utc >= created_at_utc
        AND (
            (
                current_status = 'ACCEPTED_FOR_REVIEW'
                AND review_work_id ~ '^iarw_[0-9a-f]{12}$'
                AND review_work_id = 'iarw_' || left(
                    encode(
                        sha256(convert_to(realization_id || '|review-work', 'UTF8')),
                        'hex'
                    ),
                    12
                )
                AND review_work_status = 'PENDING_ADVISER_REVIEW'
            ) OR (
                current_status = 'REJECTED_BEFORE_WORK'
                AND review_work_id IS NULL
                AND review_work_status IS NULL
            )
        )
        AND (
            SELECT count(*)
            FROM proposal_idea_realization_outcomes outcome
            WHERE outcome.realization_id = realization.realization_id
        ) = current_source_event_version
        AND EXISTS (
            SELECT 1
            FROM proposal_idea_realization_outcomes current_outcome
            WHERE current_outcome.realization_id = realization.realization_id
              AND current_outcome.source_event_version
                  = realization.current_source_event_version
              AND current_outcome.status = realization.current_status
              AND current_outcome.review_work_id
                  IS NOT DISTINCT FROM realization.review_work_id
        ),
        FALSE
    ) AS is_valid
    FROM proposal_idea_review_realizations realization
), recovered_outcomes AS (
    SELECT COALESCE(
        outcome_id ~ '^ipro_[0-9a-f]{12}$'
        AND outcome_id = 'ipro_' || left(
            encode(
                sha256(
                    convert_to(realization_id || '|' || source_event_version::text, 'UTF8')
                ),
                'hex'
            ),
            12
        )
        AND source_event_version = 1
        AND proposal_id IS NULL
        AND EXISTS (
            SELECT 1
            FROM proposal_idea_review_realizations realization
            WHERE realization.realization_id = outcome.realization_id
              AND outcome.occurred_at_utc = realization.created_at_utc
              AND outcome.occurred_at_utc = realization.updated_at_utc
        )
        AND (
            (
                status = 'ACCEPTED_FOR_REVIEW'
                AND reason_code = 'idea_conversion_accepted_for_adviser_review'
                AND review_work_id ~ '^iarw_[0-9a-f]{12}$'
                AND terminal IS FALSE
            ) OR (
                status = 'REJECTED_BEFORE_WORK'
                AND reason_code = 'idea_conversion_rejected_before_advisory_work'
                AND review_work_id IS NULL
                AND terminal IS TRUE
            )
        ),
        FALSE
    ) AS is_valid
    FROM proposal_idea_realization_outcomes outcome
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
    AND COALESCE((SELECT bool_and(is_valid) FROM recovered_realizations), TRUE)
    AND COALESCE((SELECT bool_and(is_valid) FROM recovered_outcomes), TRUE)
    AND COALESCE((SELECT bool_and(is_valid) FROM recovered_purge_events), TRUE);
