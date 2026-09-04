# Lotus Advise API Governance

Lotus Advise API governance is enforced progressively through repo-native OpenAPI gates,
vocabulary checks, no-alias checks, and enforced Spectral OpenAPI rules.

## Current Standards

- Endpoint documentation should include summaries, descriptions, tags, operation IDs, response
  models, request models where applicable, examples, and standard error responses.
- Private-banking vocabulary should remain business-facing and avoid unsupported client-ready,
  legal, regulatory, OMS, order, fill, or settlement claims.
- Supportability boundaries must be explicit when an endpoint exposes internal review, proposal,
  or advisory-copilot output.
- Mutating workflows should define idempotency behavior, deterministic state-conflict behavior,
  and audit/lineage posture.
- Correlation IDs should be accepted or propagated where API workflow tracing matters.

## Current Evidence

- `make openapi-gate`
- `make openapi-spectral-report`
- `make no-alias-gate`
- `make api-vocabulary` intentionally refreshes the tracked inventory after an API change.
- `make api-vocabulary-gate` validates the committed inventory without modifying the worktree.
- `.spectral.yaml` for enforced API documentation rules and warning inventory
- `quality/api_governance_rules.md`

## Current Gaps

- Spectral is enforced through `make openapi-gate`; current inventory is zero findings.
- RFC 7807/problem-details is a future migration unless a route family already implements it.
- Filtering, sorting, pagination, and deprecation rules still need full cross-endpoint inventory.
