# Security and Governance

## Governing Posture

`lotus-advise` is governed by Lotus platform CI, OpenAPI, vocabulary, and context standards.

## Current Scope

This page records security, release-governance, claim-control, and evidence hygiene rules that are
currently enforced or required before `lotus-advise` capabilities are promoted.

## Reader Map

| Reader | Start here |
| --- | --- |
| Agent or developer | Hard Rules, Security Baseline Governance, License/IP Evidence Governance |
| Release operator | Release Metadata Governance |
| Demo or RFP reviewer | RFC-0028 Proof Artifact Governance |

Locally relevant governance includes:

- RFC-0066 advisory and manage split
- RFC-0067 API vocabulary and OpenAPI governance
- RFC-0072 multi-lane CI governance
- RFC-0073 ecosystem context governance
- RFC-0082 upstream contract-family classification

## Sensitive Boundaries

The highest-risk documentation and implementation drift usually appears at these integration boundaries:

1. advisory versus management ownership
2. local interpretation versus upstream core or risk authority
3. workspace assistance versus decision authority
4. reporting or execution request posture versus actual ownership

## Hard Rules

1. UI and support layers must not generate or rerank proposal alternatives
2. decision-summary posture must remain backend-owned
3. local fallback or degraded behavior must not be presented as canonical upstream truth
4. live runtime evidence matters when advisory behavior changes materially
5. outbound report and AI calls must not substitute synthetic tenant or actor defaults; trusted
   identity must be bounded and present before downstream submission
6. policy-control write routes must authorize an Advise `PolicyControlPrincipal` before state
   mutation; body actor fields are compatibility echoes and cannot satisfy role, capability,
   maker-checker, tenant, legal-entity, proposal, or portfolio scope on their own
7. advisory copilot review routes must authorize a trusted reviewer principal before state
   mutation; body `actor_id` is only a compatibility echo and cannot satisfy role, capability,
   maker-checker, tenant, proposal, portfolio, or idempotency replay authority on its own
8. advisory copilot Lotus AI execution must match the approved provider/model inventory in
   `contracts/advisory-copilot/approved-model-inventory.v1.json`; unknown, retired, mismatched, or
   environment-incompatible model identity returns unavailable before completed output can become
   review-ready
9. advisory copilot model-risk evaluation must pass the executable corpus gate in
   `contracts/advisory-copilot/evaluation-corpus.v1.json`; failed groundedness, review posture, or
   guardrail evidence quarantines output before it can become review-ready
10. advisory copilot safety-abuse controls must pass the executable corpus gate in
   `contracts/advisory-copilot/safety-abuse-corpus.v1.json`; indirect prompt injection, obfuscated
   forbidden actions, sensitive output, and client-ready publication claims return stable
   guardrail-rejected posture
11. advisory copilot AI data-boundary controls must use
   `contracts/advisory-copilot/ai-data-boundary.v1.json`; outbound payloads carry tokenized
   identifiers, classified evidence fields, and provider no-training, retention, residency, and
   deletion controls
12. Advisor Cockpit reads and acknowledgements must derive caller role, advisor scope, and portfolio
    scope from trusted headers; query parameters cannot authorize role or advisor impersonation
13. outbound report calls must preserve source-derived as-of date, reporting currency, and
   jurisdiction instead of silently applying market or current-date defaults
14. release images must be built and pushed by CI only, tagged by Git SHA, labelled with support-safe
   OCI metadata, accompanied by digest-bearing release evidence, SBOM, scan, signature, and
   provenance attestation, and deployed by digest
15. Bandit findings must pass `make bandit-severity-regression-gate`: high findings are blocked,
   current medium/low entries must match the governed baseline, and new, stale, expired, or
   worsened medium/low entries fail CI
16. dependency license/IP posture must pass `make license-ip-gate`: runtime and development graphs,
    including transitive packages, must match the committed inventory and any review-required terms
    must have owner-approved expiring exceptions
17. dependency lock posture must pass `make dependency-lock-gate`: `uv.lock` must match the
    requirements install strategy, requirement-file hashes, and dependency inventory hash
18. HTTP boundary posture must fail closed for unsafe production-like host/origin configuration:
    trusted hosts are service-owned, browser origins are deny-by-default, security headers are
    applied to API responses, and write-payload limits remain enforced at the API boundary

## Advisor Cockpit Principal Governance

Advisor Cockpit action, detail, snapshot, preparation-packet, supportability, and acknowledgement
routes derive authority from trusted gateway/service headers: `X-Actor-Id`, `X-Role`,
`X-Tenant-Id`, `X-Legal-Entity-Code`, `X-Correlation-Id`, service identity, route capability,
`X-Authorized-Advisor-Id`, and `X-Authorized-Portfolio-Id`. Caller-controlled `role` and
`advisor_id` query parameters are rejected at the API boundary. Requested `portfolio_id` values
must match trusted authorized portfolio scope before source records are loaded.

Acknowledgement writes require `advisory.advisor_cockpit.acknowledge`, bind body
`acknowledged_by` to the trusted actor, and retain trusted-principal authorization metadata in
append-only acknowledgement audit evidence. Read routes require
`advisory.advisor_cockpit.read` and use trusted role headers for owner-role projection.

## Policy-Control Principal Governance

Policy-pack validation/activation and policy-evaluation finalization, review-event, sign-off,
report-package, and AI-evidence writes derive authority from trusted policy-control headers:
`X-Actor-Id`, `X-Role`, `X-Tenant-Id`, `X-Legal-Entity-Code`, `X-Correlation-Id`, service identity,
route capability, and evaluation-scoped proposal/portfolio authorization. Supported roles are
domain-specific: `POLICY_STEWARD` validates packs and can record review events,
`POLICY_CHECKER` activates packs and records sign-off/report-package commands, `ADVISOR` finalizes
evaluations, and `COMPLIANCE_REVIEWER` records review and AI-evidence requests where allowed.

Request-body actor fields remain for compatibility with existing consumers, but they are not an
identity source. Advise rejects body/header actor mismatches, missing/expired principals, wrong
roles, missing capabilities, and cross-scope proposal, portfolio, tenant, or legal-entity access
before application state transitions. Successful audit events retain trusted subject, role, tenant,
legal entity, correlation id, service identity, and capability metadata.

Finalized policy-evaluation workflow receipts use the same trusted principal boundary. Receipt
identity fails closed unless Advise observes a trace context and the evidence bundle carries a
source-owned as-of date from context resolution, portfolio snapshot, or market-data snapshot
metadata. Replay metadata exposes legal entity, booking center, proposal, version, and portfolio
scope plus source-safe hashes for tenant, service identity, observed correlation id, and observed
trace id. This is a local/dev trusted-header control; production identity-provider session and
token-claim binding remains a separately tracked platform/gateway dependency.

## Advisory Copilot Review Principal Governance

Advisory copilot action execution is model-governed before output can become review-ready. Advise
uses `src/core/advisory_copilot/model_governance.py` and
`contracts/advisory-copilot/approved-model-inventory.v1.json` to validate the approved `lotus-ai`
provider/model, workflow-pack id/version, prompt-template, output-schema, evaluation pack,
environment, owner, approval reference, release evidence, change reference, and rollback posture.
The `lotus-ai` response must report matching provider/model identity. Missing, unknown, retired,
mismatched, or environment-incompatible identity produces a stable unavailable posture and no
completed output sections.

Advise also runs an executable evaluation-pack gate through
`src/core/advisory_copilot/evaluation_gate.py`. `make advisory-copilot-evaluation-gate` expands the
sanitized corpus in `contracts/advisory-copilot/evaluation-corpus.v1.json` across all six action
families and writes evidence to `output/advisory-copilot/evaluation-evidence.json`. Runtime lineage
records evaluator version, dataset id, thresholds, metrics, failure reasons, and evaluation hash.
Failed evaluation posture quarantines output before it can remain review-ready.

Advise also runs executable safety-abuse controls through `src/core/advisory_copilot/guardrails.py`.
`make advisory-copilot-safety-gate` runs the sanitized corpus in
`contracts/advisory-copilot/safety-abuse-corpus.v1.json` through typed preflight and postflight
policy inputs and writes evidence to `output/advisory-copilot/safety-evidence.json`. Runtime
preflight separates user instruction from source evidence; runtime postflight separates generated
output from both. Prompt injection, obfuscated forbidden actions, sensitive output, and client-ready
publication claims return stable guardrail reason codes before output can remain review-ready.

Advise applies AI data-boundary minimization through
`src/core/advisory_copilot/ai_data_boundary.py` and
`contracts/advisory-copilot/ai-data-boundary.v1.json`. Outbound workflow-pack payloads use
tokenized portfolio, proposal, and source identifiers, preserve classified evidence fields only,
and carry explicit provider no-training, zero-provider-retention, Singapore residency, and deletion
policy controls. Stable source refs remain in workflow context for claim grounding; unredacted AI
instructions and provider content remain forbidden from payloads, logs, traces, and durable
records.

Advisory copilot review writes derive authority from trusted reviewer headers before application
state transitions. Supported reviewer roles are `ADVISORY_SUPERVISOR`, `COMPLIANCE_REVIEWER`, and
`POLICY_CHECKER`; the required capability is `advisory.copilot.review`. The authorized portfolio
must match the persisted run portfolio, the authorized proposal must match when the run is
proposal-scoped, and the trusted tenant must match the run tenant.

Request-body `actor_id` remains a compatibility echo for existing consumers, but it is not an
identity source. Advise rejects body/header actor mismatches, missing principals, wrong roles,
missing capabilities, cross-scope access, tenant mismatch, and self-review before review state or
idempotency state can mutate. Successful review audit records retain trusted principal metadata
and maker-checker authorization evidence alongside the review reason.

## Release Metadata Governance

`GET /version` exposes support-safe build metadata only: service name/version, Git commit, branch,
repository URL, build timestamp, CI run ID, and image digest when injected by release/deployment.
It must not expose runtime configuration, DSNs, tokens, tenant identifiers, actor identifiers, raw
headers, or downstream base URLs.

The release-image evidence path is intentionally split:

1. PR/local builds validate Dockerfile build args, OCI labels, and label content without pushing.
2. Main Releasability pushes the Git-SHA image, records the registry digest, validates dependency
   lock evidence, generates SBOM, license/IP inventory, a full vulnerability inventory, and a
   passing high/critical fixable-vulnerability scan artifact, signs the digest, creates provenance
   attestation, and uploads the release manifest.
3. Deployment must reference the digest from the retained manifest and promote the same immutable
   image across environments.

## HTTP Boundary Governance

Advise owns the first service-local HTTP boundary after ingress. The FastAPI application enforces
configured trusted hosts, deny-by-default CORS, approved security headers, enterprise write-payload
limits, and enterprise audit/authorization denials without removing correlation, request, trace, or
policy-version response headers.

Production-like deployments must configure `HTTP_BOUNDARY_TRUSTED_HOSTS` and enable
`ENTERPRISE_ENFORCE_RUNTIME_CONFIG=true` so unsafe defaults fail at startup. `HTTP_BOUNDARY_ALLOWED_ORIGINS`
is optional and must list explicit browser origins when browser clients are approved. Wildcard
trusted hosts and wildcard CORS origins are not accepted in production-like environments.

Ingress, gateway, and platform security still own TLS termination, external WAF/rate limiting,
edge DDoS protection, and bank identity-provider integration. Route-specific caller-context
authorization, entitlement resolution, and business-object access checks remain implemented in the
owning route/application slices rather than inferred from generic HTTP headers alone.

## Security Baseline Governance

`quality/bandit_security_baseline.v1.json` is the governed Bandit medium/low baseline. It is not a
security certification claim. Each accepted entry carries a stable fingerprint, owner, rationale,
expiry, linked remediation, and compensating control. The current baseline records `0` high, `26`
medium, and `0` low findings, with remediation tracked in issue #435.

Use `make bandit-severity-regression-gate` for the direct gate. `make security-audit` runs the same
gate after dependency health. `make bandit-high-severity-gate` remains only as a compatibility alias.

## License/IP Evidence Governance

`docs/standards/license-ip-policy.v1.json` classifies allowed, review-required, and prohibited
dependency license terms. `docs/standards/license-ip-inventory.v1.json` records the current runtime
and development dependency graphs, including transitive packages, policy classification, and
approved exceptions. `NOTICE.md` records the third-party notice posture.

Use `make license-ip-inventory` to regenerate the committed inventory after dependency changes, and
`make license-ip-gate` to verify release posture. New unclassified, prohibited, missing-metadata, or
expired-exception findings fail CI.

Both commands run the license/IP evidence generator inside an isolated virtual environment installed
from the governed runtime/development requirements files. This keeps release evidence tied to the
CI-installed graph, pins pip/setuptools bootstrap tooling, runs pip in isolated mode, and prevents
ambient developer or runner site-packages, pip environment variables, or pip user configuration from
changing the inventory.

## Dependency Lock Governance

`uv.lock` is the generated lock mirror for the current requirements-based install strategy. It
records requirement-file hashes, the license/IP inventory hash, direct pins, transitive package
versions, package groups, extras, and requirement-line hashes.

Use `make dependency-lock` after changing `requirements.txt`, `requirements-prod.txt`,
`requirements-dev.txt`, or generated dependency inventory. `make dependency-lock-gate` fails on
missing packages, version drift, stale manifest hashes, or Python-runtime incompatibility.

## RFC-0028 Proof Artifact Governance

RFC-0028 bank-demo proof is governed as implementation evidence, not marketing copy. The supported
claim register controls which product, security, RFP, demo, and proof-guide statements can be used
by business-facing material. Claims must stay in one of the documented postures: implementation
backed, blocked, planned, local-only, or secret material. Commercial wording must map back to the
supported-claim register and proof-pack evidence before it is reused outside engineering.

Runtime proof artifacts are sanitized before they become commit-safe or demo-supporting evidence:

1. runtime base URLs must not include credentials, query strings, or fragments
2. proof artifact references must stay as local relative paths and must not include URL schemes,
   authorities, credentials, query strings, fragments, absolute paths, parent-directory traversal,
   control characters, or sensitive credential, AI-input, or runtime-payload path material
3. HTTP 422 request-validation errors must not echo rejected sensitive input values
4. summaries redact credential, AI-input, runtime-payload, trace, and correlation material
5. endpoint posture records bounded integer `latency_ms` values only
6. local-only runtime outputs under `output/` must not be treated as wiki or README source truth
7. committed proof assets must use commit-safe or customer-consumable access classes,
   `COMMIT_SOURCE` retention, and a canonical content hash

The proof boundary remains deliberately conservative. RFC-0028 does not certify bank-specific
attestations, legal/regulatory advice, completed policy sign-off/approval, external client
communication, client-ready publication, or OMS/order/fill/settlement. Any future promotion of
those claims requires implementation evidence, tests at the owning layer, and updated API/wiki/RFC
truth in the same slice.

## RFC-0027 Copilot Evidence Governance

Governed advisory copilot output is internal advisor/reviewer evidence, not client-ready advice or
model authority. Evidence-section models, unsupported-evidence messages, action projections, and
copilot structured-payload persistence reject unredacted AI input, provider-output,
trace/correlation, run-ledger, and unrestricted runtime-payload wording at the lowest boundary.
This keeps UI, API, persistence, and replay paths aligned with the same business-copy redaction
rule.
