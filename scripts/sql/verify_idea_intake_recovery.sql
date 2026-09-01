WITH recovered_claims AS (
    SELECT
        registry_key ~ '^[0-9a-f]{64}:sha256:[0-9a-f]{64}$'
        AND request_fingerprint ~ '^sha256:[0-9a-f]{12}$'
        AND response_json::jsonb ->> 'request_fingerprint' = request_fingerprint
        AND response_json::jsonb ->> 'idempotency_replay' = 'false'
        AND response_json::jsonb ->> 'intake_status' IN ('ACCEPTED', 'REJECTED')
        AND response_json::jsonb ->> 'received_at' IS NOT NULL
        AND (response_json::jsonb ->> 'received_at')::timestamptz = created_at_utc
        AND jsonb_typeof(response_json::jsonb -> 'trusted_scope') = 'object'
        AS is_valid
    FROM proposal_idea_intakes
)
SELECT COALESCE(bool_and(is_valid), true)
FROM recovered_claims;
