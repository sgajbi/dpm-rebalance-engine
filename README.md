# lotus-advise

Advisor-led proposal simulation, advisory workspace, and persisted proposal lifecycle service for Lotus.

Repository-local engineering context:
[REPOSITORY-ENGINEERING-CONTEXT.md](REPOSITORY-ENGINEERING-CONTEXT.md)

Upstream contract-family map:
[docs/architecture/RFC-0082-upstream-contract-family-map.md](docs/architecture/RFC-0082-upstream-contract-family-map.md)

## Start Here By Audience

| Audience | First stop | What it gives you |
| --- | --- | --- |
| Business and demo reviewers | [wiki/Demo-Readiness-Guide.md](wiki/Demo-Readiness-Guide.md) | Current demo story, proof checklist, safe talk track, and blocked claims. |
| Sales and pre-sales | [docs/commercial/RFC-0028-bank-demo-client-proof-materials.md](docs/commercial/RFC-0028-bank-demo-client-proof-materials.md) | Claim-controlled product, RFP, security, architecture, ROI, and demo wording. |
| Operators | [wiki/Operations-Runbook.md](wiki/Operations-Runbook.md) | Readiness checks, proof-pack stop conditions, and runtime diagnostics. |
| Engineers | [wiki/API-Surface.md](wiki/API-Surface.md) and [docs/rfcs/README.md](docs/rfcs/README.md) | Route families, contract notes, and implementation history. |
| New agents | [REPOSITORY-ENGINEERING-CONTEXT.md](REPOSITORY-ENGINEERING-CONTEXT.md) | Repository role, boundaries, commands, and current implementation posture. |

## Demo Readiness Fast Path

For a demo, use the governed proof flow instead of ad hoc screenshots or slide language:

1. validate the service and dependencies with the repo-native gates below,
2. run or review `make demo-certification-live` evidence for the target runtime,
3. validate the canonical front-office path for `PB_SG_GLOBAL_BAL_001` before screenshots,
4. review [wiki/Demo-Readiness-Guide.md](wiki/Demo-Readiness-Guide.md) for audience-specific
   preparation,
5. use [docs/commercial/RFC-0028-bank-demo-client-proof-materials.md](docs/commercial/RFC-0028-bank-demo-client-proof-materials.md)
   for claim-controlled demo and RFP wording,
6. keep these blocked claims visible: client-ready publication, external client communication,
   legal/regulatory advice, bank-specific certification, completed approval/sign-off authority, and
   OMS/order/fill/settlement.

## Purpose And Scope

`lotus-advise` owns advisory-only workflow behavior in the Lotus ecosystem.

It is responsible for:

- advisory proposal simulation orchestration
- deterministic proposal artifact generation
- advisory workspace drafting and handoff
- persisted proposal lifecycle state and immutable versioning
- approvals, consent, and execution-readiness posture
- backend-owned `proposal_decision_summary` and `proposal_alternatives`
- advisor-review proposal narrative evidence with governed review/replay, downstream
  report/render/archive posture, Gateway/Workbench exposure, data-product declaration, trust
  telemetry, capability discovery, live runtime proof, and governed Workbench canonical proof
- enterprise policy-pack catalog and advisor/compliance policy evaluation evidence with governed
  fail-closed applicability across jurisdiction, booking center, legal entity, client segment, and
  product scope, source readiness, finalized evaluation records, replay, workflow/sign-off posture,
  report-package lineage, bounded AI evidence, Gateway/Workbench exposure, active data-product
  declaration, and trust telemetry
- advisory copilot evidence packets, workflow-pack output, persisted run/review records, and
  claim-level source grounding that marks unsupported or unverifiable AI output as not
  review-ready without raw provider payload retention
- source-owned tactical house-view affected cohorts from bank-authored house-view instructions and
  caller-supplied source-backed candidate portfolios
- source-safe `lotus-idea` proposal intake that turns accepted conversion intent into one durable,
  portfolio-scoped adviser-review work item and an append-only Advise-owned initial outcome, with
  trusted local/dev caller scope and exact replay; an explicit compare-and-set reconciliation route
  links an existing same-portfolio Advise proposal and emits bounded source-owned terminal outcomes
  without inferring suitability, client publication, orders, fills, settlement, or execution
  success from transport

It does not own discretionary management workflows, portfolio source data, risk methodology,
performance methodology, reporting ownership, or downstream execution ownership.

## Ownership And Boundaries

`lotus-advise` sits between product consumers and authoritative upstream services.

It depends on:

- `lotus-core`
  canonical portfolio context, source-data reads, and advisory simulation authority
- `lotus-risk`
  risk-lens enrichment and concentration authority
- `lotus-report`
  report-request integration boundary
- `lotus-ai`
  workspace-rationale integration boundary
- `lotus-gateway`
  primary integrated product-facing consumer

Boundary rules that matter:

1. advisory-only workflows belong here; management workflows belong in `lotus-manage`
2. proposal alternatives and decision-summary semantics are backend-owned surfaces, not UI-derived interpretations
3. proposal simulation and alternatives must stay anchored to canonical upstream authorities
4. tactical house-view cohorts consume source-backed candidate portfolios and do not discover the
   global portfolio universe, open rebalance waves, approve trades, or integrate with OMS
5. execution handoff, status, and delivery responses carry explicit ownership-boundary evidence;
   `lotus-advise` records advisory posture while downstream providers remain execution systems of
   record
6. REST/OpenAPI remains the governed integration contract for current upstream calls
7. `lotus-core` projected transaction effects are mapped through
   `CoreProjectedTransactionEffects`; any Core-returned suitability, gate, decision-summary,
   alternatives, or next-step fields are non-authoritative compatibility evidence, while Advise
   recomputes advisory decisions through its own suitability and workflow policy modules

## Current Operational Posture

1. `lotus-advise` is scoped to advisory-only workflows after the split from `lotus-manage`.
2. Proposal simulation, artifact, workspace, replay, and lifecycle flows now expose persisted
   backend-owned `proposal_decision_summary` and `proposal_alternatives`.
3. Runtime smoke and production-profile guardrail validation are part of the actual CI contract.
4. Live operator evidence covers canonical and degraded decision-summary and alternatives posture.
5. `TacticalHouseViewAffectedCohort:v1` is a governed source-owned cohort product for downstream
   discretionary portfolio-management workflows in `lotus-manage`, bounded to supplied eligible
   candidates and preserved lineage.
6. `AdvisoryPolicyEvaluationRecord:v1` is an active advisor/compliance policy evidence product for
   RFC-0025. Runtime catalog, activation, audit, idempotency, and evaluation state is backed by
   policy repository ports and the `policy_packs` Postgres migration namespace with
   adapter-transactional record/catalog, audit-event, and immutable idempotency writes. The generic
   policy-evaluation event API is review-only; sign-off, report/archive, AI-evidence, and
   finalization events are recorded only by their specialized Advise commands with event-authority
   contract checks. Policy validation, activation, evaluation finalization, review event,
   sign-off, report-package, and AI-evidence commands now bind actor authority to trusted
   `X-Actor-Id`, `X-Role`, `X-Tenant-Id`, `X-Legal-Entity-Code`, `X-Correlation-Id`,
   service-identity, capability, proposal, and portfolio headers; request-body actor fields are
   compatibility echoes and are rejected when they do not match the trusted principal. Finalized
   policy workflow receipts also persist source-owned `as_of_date`, trusted legal-entity,
   booking-center, proposal, version, and portfolio scope, plus source-safe tenant, service,
   correlation, and trace hashes so `lotus-idea` can reconcile producer evidence without seeing raw
   caller identifiers. Production identity-provider binding remains outside this local/dev trusted
   header boundary. Completed approval/waiver authority, client-ready policy publication, and
   external client communication remain gated.
7. `AdvisoryCopilotInteractionRecord:v1` is active for governed internal advisor/reviewer copilot
   interactions. Completed copilot output must pass the Advise-owned approved provider/model
   inventory in `contracts/advisory-copilot/approved-model-inventory.v1.json`, return matching
   `lotus-ai` provider/model lineage, pass the executable evaluation gate backed by
   `contracts/advisory-copilot/evaluation-corpus.v1.json` and
   `scripts/advisory_copilot_evaluation_gate.py`, pass the executable safety-abuse corpus backed by
   `contracts/advisory-copilot/safety-abuse-corpus.v1.json` and
   `scripts/advisory_copilot_safety_gate.py`, satisfy the AI data-boundary contract in
   `contracts/advisory-copilot/ai-data-boundary.v1.json`, satisfy the runtime budget contract in
   `contracts/advisory-copilot/runtime-budget.v1.json`, and pass claim-level source grounding
   before it can remain review-ready. Missing, retired, mismatched, or environment-incompatible
   model identity returns a stable unavailable posture; failed evaluation or safety evidence
   quarantines output as unsupported or guardrail-rejected. Outbound AI payloads use tokenized
   portfolio/proposal/source identifiers and explicit no-training, retention, residency, and
   deletion controls; retry, timeout, token, payload, cost, and concurrency budget breaches return
   stable unavailable posture with bounded lineage telemetry. Review actions bind reviewer
   authority to trusted `X-Actor-Id`, `X-Role`,
   `X-Tenant-Id`,
   `X-Legal-Entity-Code`, `X-Correlation-Id`, service-identity, capability, proposal, and
   portfolio headers. Request-body `actor_id` is only a compatibility echo; mismatches, missing
   scope, wrong tenant, missing capability, wrong role, self-review, and changed-actor idempotency
   replay fail before review state mutates.
8. `AdvisorCockpitOperatingSnapshot:v1` and `AdvisoryActionItemRegister:v1` are active
   source-owned RFC-0026 advisor operating workflow products. They cover Advise action items,
   snapshot, supportability, acknowledgements, Gateway/Workbench consumption, and canonical
   `PB_SG_GLOBAL_BAL_001` proof while client-ready publication, external client communication,
   CRM system-of-record behavior, OMS lifecycle, and completed policy approval authority remain
   gated. RFC-0028 bank-demo/RFP proof is governed separately through supported claims.
9. RFC-0028 bank-demo proof is implemented through the Advise scenario contract, supported-claim
   register, sanitized proof-pack capture, Gateway publication, Platform canonical contract
   registration, and Workbench `advisory.bank_demo_proof` surface. Canonical validation for
   `PB_SG_GLOBAL_BAL_001` records `BANK_DEMO_PROOF_PACK_CREATED` and keeps client-ready
   publication, external client communication, OMS/order/fill/settlement, and unsupported
   RFP/demo collateral claims blocked. Claim-controlled commercial material is governed by the
   supported-claim register. Slice 9 adds
   `AdvisoryJourneyIntegrationProofSummary:v1` and
   `journey-integration-proof-summary.json` so the backend proof pack now carries sanitized
   AI/model-risk, policy, and advisor-cockpit boundary evidence without promoting AI authority,
   legal advice, policy approval, or client-ready publication. Slice 10 adds claim-controlled
   commercial, RFP, security, architecture, ROI, demo, feature-matrix, proof-guide, boundary, and
   operator material through `docs/commercial/RFC-0028-bank-demo-client-proof-materials.md` and
   `commercial-material-pack.json`, while keeping client-ready publication, external client
   communication, bank-specific attestations, legal/regulatory advice, completed sign-off, and
   OMS/order/fill/settlement claims blocked. Slice 11 adds sanitized runtime security posture,
   integer `latency_ms` evidence, runtime URL hygiene, and sensitive-summary redaction to
   `runtime-posture.json` and `sanitized-runtime-summary.json`. Slice 12 makes that product truth
   explicit in README and wiki source so operators, pre-sales, and engineers use the same
   implementation-backed proof boundaries. Slice 13/14 closes final implementation proof and
   hardening through local artifact-reference normalization, safe HTTP 422 validation error
   responses that do not echo rejected sensitive input, targeted proof tests, PR Merge Gate, and
   Main Releasability Gate run `26573760885` on merge
   `a99474e5457dcdd4c87e79faf83bc8f64580544b`. Slice 15/16 closes durable
   docs/context/wiki truth and post-completion communication evidence through `lotus-platform`
   PR #369 at `26d74e65e231ac3d62457187c6eb7f787a4d9f88`, Main Releasability Gate run
   `26574820026`, and
   `lotus-platform/thought-leadership/linkedin/drafts/LI-2026-05-28-043-demo-proof-should-show-the-boundary.md`.
   Current proof capture also validates ready `/platform/capabilities` runtime evidence and blocks
   stale proof reuse when `advisory.bank_demo_proof` or `advisory_bank_demo_proof` is missing.
9. The `lotus-idea` advisory proposal intake and realization boundary is implemented at
   `POST /advisory/proposals/idea-intake` with contract evidence under
   `contracts/idea-proposal-intake/`. It proves an executable handoff with trusted
   local/dev caller headers, durable restart-safe v1.6 idempotency conflict detection, exact-payload replay, and
   bounded accepted/rejected outcomes. An accepted review intent creates one deterministic durable
   work item in `PENDING_ADVISER_REVIEW` and an `ACCEPTED_FOR_REVIEW` outcome; unsupported intent is
   recorded as `REJECTED_BEFORE_WORK` without creating work. `GET
   /advisory/proposals/idea-intake/{intake_id}/realization` exposes that Advise-owned truth only to
   an exactly scoped reader. If the intake response is lost after Advise commits, read-only `GET
   /advisory/proposals/idea-intake/realization?conversion_intent_id={conversion_intent_id}`
   recovers the same aggregate from Idea's source-owned conversion identity without replaying the
   POST, accepting a raw idempotency key, or disclosing cross-scope existence. The request requires
   the opaque conversion identity as an encoded query value so every previously accepted printable
   identity remains recoverable, plus the producer-authorized canonical
   `portfolio_id`; Advise includes it in deterministic identity and request fingerprinting and
   persists it in the receipt, so changed-portfolio key reuse fails closed without inferring scope
   from opaque identifiers. A pre-v1.6 claim has no trustworthy portfolio scope: reconcile its
   receipt before submitting the scoped request with a new idempotency key. Intake replay claims retain a 24-hour reuse window; expired
   claims are purged in target-prioritized batches of at most 128 before a new claim unless an
   authorized records process has placed them on legal hold. Each deletion writes sanitized,
   append-only purge evidence in the same database transaction. Purging a replay claim never
   deletes the durable review work or outcome history. An adviser-created same-portfolio proposal
   is explicitly linked through `POST
   /advisory/proposals/idea-intake/{intake_id}/realization/proposal-reconciliation` using
   compare-and-set source-event progression. Advise emits `PROPOSAL_LINKED` and only maps
   authoritative terminal proposal states to bounded advisory outcomes. The route does not
   auto-create proposals, grant suitability authority, authorize client publication, create or
   independently prove orders/fills/settlement, certify a data product, or convert transport
   success into a business outcome. See
   [Idea Conversion Realization](docs/architecture/idea-conversion-realization.md).

## Architecture At A Glance

Main runtime surfaces come from [src/api/main.py](src/api/main.py):

- advisory simulation
  `POST /advisory/proposals/simulate`
  `POST /advisory/proposals/artifact`
- advisory proposal lifecycle
  create, version, transition, approval, delivery, execution, async, and support routes under
  `/advisory/proposals/*`
  plus source-safe `POST /advisory/proposals/idea-intake` and scoped
  `GET /advisory/proposals/idea-intake/{intake_id}/realization`, read-only lost-response recovery by
  scoped conversion intent, plus explicit
  `POST /advisory/proposals/idea-intake/{intake_id}/realization/proposal-reconciliation` routes for
  `lotus-idea` conversion-intent handoff, proposal linkage, and Advise-owned outcomes
- advisory workspace
  iterative draft, save, resume, compare, rationale, and lifecycle handoff under
  `/advisory/workspaces/*`
- tactical house view
  source-owned affected-cohort evaluation under `/advisory/tactical-house-view/*`
- advisor cockpit
  source-owned action, snapshot, supportability, and acknowledgement routes under
  `/advisory/cockpit/*`
- bank demo proof
  source-owned scenario contract, supported-claim register, and sanitized proof-pack capture through
  `GET /advisory/bank-demo-proof/scenario-contract`,
  `GET /advisory/bank-demo-proof/supported-claim-register`, and
  `POST /advisory/bank-demo-proof/proof-packs`
- integration capabilities
  `GET /platform/capabilities`
- platform surfaces
  `/health`, `/health/live`, `/health/ready`, `/version`, `/docs`

Key code areas:

- `src/api/`
  FastAPI app wiring, route families, and runtime support
- `src/core/advisory/`
  advisory artifact, funding, alternatives, decision summary, and policy logic
- `src/core/proposals/`
  persisted proposal lifecycle models and services
- `src/core/workspace/`
  advisory workspace contracts and state
- `src/core/advisor_cockpit/`
  RFC-0026 advisor cockpit action construction, source read model, SLA/acknowledgement policy, and
  supportability projection
- `src/integrations/`
  Lotus Core, Risk, AI, Report, and Performance integration boundaries
- `docs/`
  repo-local architecture, RFCs, demo payloads, and runbooks

## Repository Layout

- `src/api/`
  HTTP entrypoints and route families
- `src/core/`
  advisory domain, lifecycle, replay, and workspace logic
- `src/integrations/`
  upstream and adjacent service adapters
- `src/infrastructure/`
  Postgres migrations and proposal persistence implementations
- `docs/`
  repo-local architecture, RFCs, demo material, and runbooks
- `tests/`
  unit, integration, and e2e coverage
- `wiki/`
  canonical authored source for GitHub wiki publication

## Quick Start

### Prerequisites

Resolved from `PATH`. Nothing here assumes an operating system, drive or workspace layout:

| tool | version | source of the claim |
|---|---|---|
| Python | 3.11 | every CI lane pins `PYTHON_VERSION: "3.11"`; `pyproject.toml` declares no `requires-python`, so CI is the only authority |
| `make` | any | every gate and lane is a make target. Absent on Windows by default; this workstation uses GNU Make 4.4.1 from the winget package `ezwinports.make` (Chocolatey, Scoop and MSYS2 also provide it, untested here) |
| Docker | any recent | container path and compose runs |
| `git` | any recent | version control |

### Install

`make install` pips into whatever `python` resolves to, so create and activate a virtualenv
first — on PEP 668 distributions a system-wide install is refused. `venv/` is this repository's
conventional location and is already gitignored.
[wiki/Getting-Started.md](wiki/Getting-Started.md) explains why CI never encounters this.

```bash
python3 -m venv venv && . venv/bin/activate && make install
```

```powershell
python -m venv venv; .\venv\Scripts\Activate.ps1; make install
```

### Run

```bash
make run
```

This serves on `http://127.0.0.1:8000`, matching the container, which EXPOSEs and listens on 8000
and is mapped `8000:8000` by compose. Use that address if you have not set up dev ingress.

Canonical local service identity for cross-app and demo-oriented flows:

- `http://advise.dev.lotus`

That hostname is NOT automatic. It resolves only once the dev-ingress host entries are applied
(they are listed in `lotus-platform/platform-stack/dev-ingress/hosts.example` and applied by that
repository's `Sync-Dev-Ingress-Hosts` automation), and it additionally requires the dev ingress
itself to be running. Without both, the probes below fail while the service is perfectly healthy
on `127.0.0.1:8000`.

Quick probes:

```bash
curl http://advise.dev.lotus/health
curl http://advise.dev.lotus/health/ready
curl http://advise.dev.lotus/version
```

OpenAPI UI:

- `/docs`

Important local Docker runtime bindings:

- `LOTUS_CORE_BASE_URL`
- `LOTUS_CORE_QUERY_BASE_URL`
- `LOTUS_RISK_BASE_URL`
- `LOTUS_RISK_TIMEOUT_SECONDS`
- `LOTUS_RISK_RETRY_ATTEMPTS`
- `LOTUS_RISK_RETRY_BACKOFF_SECONDS`

Canonical local Docker upstream defaults:

- `LOTUS_CORE_BASE_URL=http://core-control.dev.lotus`
- `LOTUS_CORE_QUERY_BASE_URL=http://core-query.dev.lotus`
- `LOTUS_RISK_BASE_URL=http://risk.dev.lotus`
- `LOTUS_ADVISE_TENANT_ID=tenant-sg-001` for app-local and canonical Workbench developer startup

The local Compose manifest supplies the canonical developer tenant fixture so cross-app Workbench
bring-up can start without an external identity provider. Production Compose remains fail-closed and
requires deployment-owned `LOTUS_ADVISE_TENANT_ID`; do not treat the local fixture as production
tenant or entitlement proof.

Lotus Risk enrichment uses bounded retries for transient `5xx`, `429`, and network failures.
`LOTUS_RISK_RETRY_ATTEMPTS` defaults to `2` and must be between `1` and `5`;
`LOTUS_RISK_RETRY_BACKOFF_SECONDS` defaults to `0.1` seconds and must be between `0.001`
and `2.0` seconds. Explicit malformed or out-of-range numeric integration settings fail
startup/readiness instead of falling back silently.

## Common Commands

- `make install`
  install dependencies
- `make check`
  fast local quality gate
- `make ci`
  PR-grade local proof with dependency health, coverage, Docker build, Postgres runtime smoke, and
  production-profile guardrail validation
- `make ci-local`
  local feature-lane proof
- `make ci-local-docker`
  Linux container parity for the host-side CI contract
- `make release-image-provenance-gate`
  static release-image metadata contract check for Dockerfile labels, Docker build args, and
  support-safe build metadata names
- `make license-ip-gate`
  validates runtime/development dependency license inventory, approved exceptions, and NOTICE
  posture in a temporary virtual environment installed from the governed runtime/development
  requirements files with pinned pip/setuptools bootstrap tooling and pip isolated from caller
  configuration
- `make dependency-lock-gate`
  validates `uv.lock` as the generated mirror of requirements files plus dependency inventory
- `make trust-telemetry-freshness-gate`
  validates repo-owned trust telemetry freshness and blocks stale evidence that still claims
  current promotion posture
- `make advisory-data-lifecycle-gate`
  validates the advisory evidence and telemetry field inventory for classification, retention,
  masking, projection, and telemetry-label decisions
- `make run`
  local runtime

## Validation And CI Lanes

`lotus-advise` follows the Lotus multi-lane model:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

Repo-native gate mapping:

- `make check`
  fast local quality gate
- `make ci`
  PR-grade validation with dependency health, OpenAPI, vocabulary, no-alias governance, migration
  rollout contract evidence, trust telemetry freshness, migration smoke, dependency-lock evidence,
  license/IP evidence, release-image provenance, coverage, Docker build, Postgres runtime smoke, and
  production-profile guardrail checks
- `make ci-local`
  local feature-lane proof
- `make ci-local-docker`
  container parity

## API Contract Notes

Important public route groups:

1. advisory simulation and artifact
2. persisted proposal lifecycle
3. advisory operations and support
4. advisory workspace
5. tactical house-view affected-cohort evaluation
6. policy-pack catalog and policy-evaluation evidence
7. advisor cockpit action, snapshot, supportability, and acknowledgement evidence
8. bank-demo proof contract and proof-pack capture
9. integration capabilities

Contract rules that are easy to get wrong:

1. proposal simulation and artifact flows require `Idempotency-Key`
2. lifecycle persistence is immutable-by-version
3. support and delivery posture derive from append-only workflow history
4. workspace rationale and RFC-0023 advisor-review proposal narrative are separate governed AI
   integration boundaries; advisor-review narrative is implemented for proposal artifact,
   review/replay, reviewed report-request package, report/render/archive, Gateway posture,
   Workbench posture, standalone read, and non-persistent regeneration, while client-ready
   narrative remains gated
5. tactical house-view cohort responses must preserve upstream source refs and supportability posture
   instead of recomputing portfolio source facts locally
6. policy evaluation endpoints preserve selector applicability, source/policy/evaluation/replay
   hashes, source-owned as-of date, trusted scope identity, source-safe
   tenant/service/correlation/trace hashes, trusted policy-control principal metadata, and must not imply legal advice, completed
   approval/waiver authority, completed sign-off authority, production IdP binding, or client-ready
   publication. Policy command body actor fields are not authoritative identity; they must match the
   trusted policy-control principal and authorized scope headers
7. advisor cockpit endpoints preserve source refs, action lineage, SLA/acknowledgement posture, and
   unsupported-claim boundaries; acknowledgements do not approve policy, clear blockers, contact
   clients, create CRM tasks, or initiate orders
8. bank-demo proof APIs return Advise-owned scenario, supported-claim, runtime-posture, and
   proof-pack truth for Gateway and Workbench consumption. `POST
   /advisory/bank-demo-proof/proof-packs` fails with HTTP 409 when material proof fields drift from
   the supported-claim register, rejects runtime base URLs that include credentials, query strings,
   or fragments, rejects proof artifact references that include URL/query/fragment/traversal or
   sensitive access-token, credential, AI-input, or implementation-payload path material, redacts
   secrets, tokens, prompts, implementation payloads, trace IDs, and correlation IDs from
   summaries, does not echo rejected sensitive input in HTTP 422 validation responses, and records
   bounded integer `latency_ms` endpoint evidence. Ready `/platform/capabilities` runtime evidence
   must include `advisory.bank_demo_proof` and `advisory_bank_demo_proof` before proof artifacts
   are reused.
   These APIs do not approve
   client-ready publication, external client communication, bank-specific attestations,
   legal/regulatory advice, completed sign-off/approval, or OMS/order/fill/settlement.
9. `GET /platform/capabilities` separates feature enablement from operational readiness and returns
   bounded dependency evidence through `runtime_probe_enabled`, `readiness_basis`, and
   `degraded_reason` without exposing dependency base URLs. Capability publication is
   deployment-scoped and informational; it does not evaluate tenant-specific entitlement policy or
   authorize endpoint access.

## Integration Boundaries

- primary downstream consumer:
  `lotus-gateway`
- governed tactical house-view cohort consumer:
  `lotus-manage`
- key upstreams:
  `lotus-core`, `lotus-risk`
- bounded adjacent integration boundaries:
  `lotus-report`, `lotus-ai`

Contract rule:

`lotus-advise` may orchestrate, persist, and shape advisory workflow evidence, but it must not
become the authority for source portfolio data, risk methodology, performance analytics, report
generation, or downstream execution truth.

## Operations And Runtime Posture

- use `advise.dev.lotus` for canonical local cross-app validation
- use `/health/ready` to confirm local process, persistence, runtime configuration, and proposal
  boot posture before treating the pod as healthy
- use `/platform/capabilities` to confirm upstream dependency and workflow readiness before
  claiming an advisory workflow, demo, or release evidence path is operational
- use `make slo-capacity-gate` to validate
  `docs/standards/advisory-slo-capacity-budgets.v1.json` and emit the load-smoke plan before
  claiming SLO/capacity evidence
- use `/version` to compare runtime build metadata with retained Main Releasability image release
  evidence
- treat upstream simulation and risk failures as dependency issues first, not as reasons to invent local fallback truth
- keep proposal decision-summary and alternatives behavior aligned to canonical and degraded live evidence
- capture RFC-0028 backend proof with `scripts/capture_rfc0028_backend_proof.py` and review
  `proof-pack.json`, `runtime-posture.json`, `sanitized-runtime-summary.json`, and
  `commercial-material-pack.json` before using demo or RFP material
- keep `live_suite_result_ref`, `live_suite_bundle_ref`, and `output_ref_prefix` as local relative
  proof-artifact references; use `--artifact-ref-prefix` when writing proof artifacts to an
  absolute `--output-dir` so proof-pack asset references remain portable and sanitized
- URL, query, fragment, traversal, and sensitive access-token material is rejected before proof
  capture can proceed
- treat `RFC0028_BACKEND_PROOF_MATERIAL_REVIEW_BLOCKED` and HTTP 409 proof-pack responses as
  material-drift defects that require code, seed, or documentation correction before demo evidence
  is reused

## Documentation Map

- architecture and business overview:
  [docs/documentation/project-overview.md](docs/documentation/project-overview.md)
- upstream contract-family map:
  [docs/architecture/RFC-0082-upstream-contract-family-map.md](docs/architecture/RFC-0082-upstream-contract-family-map.md)
- demo scenarios:
  [docs/demo/README.md](docs/demo/README.md)
- demo readiness guide:
  [wiki/Demo-Readiness-Guide.md](wiki/Demo-Readiness-Guide.md)
- RFC-0028 bank-demo commercial proof material:
  [docs/commercial/RFC-0028-bank-demo-client-proof-materials.md](docs/commercial/RFC-0028-bank-demo-client-proof-materials.md)
- development workflow:
  [docs/operations/development-workflow-and-ci-strategy.md](docs/operations/development-workflow-and-ci-strategy.md)
- Postgres rollout runbook:
  [docs/documentation/postgres-migration-rollout-runbook.md](docs/documentation/postgres-migration-rollout-runbook.md)
- RFC index:
  [docs/rfcs/README.md](docs/rfcs/README.md)

## Wiki Source

Repository-authored wiki pages live under [wiki/](wiki). Keep `wiki/` as the canonical authored
source and treat any separate `*.wiki.git` clone as publication plumbing only.
