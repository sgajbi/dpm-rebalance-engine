# Mesh Data Products

## Current Scope

Current scope: this page lists the repo-native Advise data products that are implementation-backed
today, their approved consumers, and the product boundaries that must remain visible in Gateway,
Workbench, platform catalog, and future-agent work. Source declarations, trust telemetry, and
platform mesh validators are the evidence posture; planned or blocked client-publication claims are
not promoted here.

## Reader Map

| Reader | Use this page to decide | Evidence anchor |
| --- | --- | --- |
| Platform/catalog reviewer | Which Advise products are source-owned and active | `contracts/domain-data-products/` and `contracts/trust-telemetry/` |
| Gateway/Workbench consumer | Which products can be consumed without rebuilding Advise truth | Approved downstream consumer rows |
| Operations/support | Which boundaries remain unsupported or gated | Operating rule and product role rows |
| Future agent | Whether a new claim belongs in Advise or another Lotus app | Product role, owner boundary, and approved consumer fields |

## Mesh role

`lotus-advise` is a maturity-wave producer in the Lotus enterprise data mesh.

## Governed products

- Product ID: `lotus-advise:AdvisoryProposalLifecycleRecord:v1`
- Product role: governed advisory proposal lifecycle record for downstream management, reporting, gateway, and Workbench discovery flows
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/`
- Approved downstream consumers: `lotus-gateway`, `lotus-idea`
- Lotus Idea boundary: consumes lifecycle posture as opportunity-intelligence input; advisory
  workflow state and proposal-event truth remain source-owned by `lotus-advise`.
- Lotus Idea intake realization: `POST /advisory/proposals/idea-intake` accepts source-safe
  conversion intent and creates deterministic durable adviser-review work plus an initial
  Advise-owned outcome when review is supported. Scoped consumers read the realization through
  `GET /advisory/proposals/idea-intake/{intake_id}/realization`. Explicit reconciliation through
  `POST /advisory/proposals/idea-intake/{intake_id}/realization/proposal-reconciliation` links one
  existing same-portfolio proposal and emits bounded terminal outcomes only from authoritative
  Advise proposal state. Supportability remains `not_certified`; production IdP binding,
  cross-repository Idea consumer proof, suitability, client publication, and supported-feature
  promotion remain blocked until certified runtime evidence exists.

- Product ID: `lotus-advise:TacticalHouseViewAffectedCohort:v1`
- Product role: source-owned affected-cohort evaluation for bank-authored tactical house-view instructions and caller-supplied source-backed candidate portfolios
- Source declaration: `contracts/domain-data-products/`
- Approved downstream consumer: `lotus-manage`

- Product ID: `lotus-advise:ProposalNarrativeEvidence:v1`
- Product role: advisor-review proposal narrative evidence for immutable proposal-version reads,
  regeneration candidates, narrative review/replay, reviewed report-request package propagation,
  and delivery-summary posture
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/proposal-narrative-evidence.telemetry.v1.json`
- Approved downstream consumers: `lotus-gateway`, `lotus-report`, `lotus-render`,
  `lotus-archive`

- Product ID: `lotus-advise:AdvisoryProposalMemoEvidencePack:v1`
- Product role: advisor-use proposal memo evidence for persisted memo records, advisor projection,
  review posture, report-package handoff, archive refs, AI commentary lineage, and replay hashes
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/advisory-proposal-memo-evidence-pack.telemetry.v1.json`
- Approved downstream consumers: `lotus-gateway`, `lotus-report`, `lotus-render`,
  `lotus-archive`, `lotus-workbench`

- Product ID: `lotus-advise:AdvisoryPolicyEvaluationRecord:v1`
- Product role: source-owned advisory policy evaluation record for proposal-version policy
  evidence, review queue posture, replay, lineage, sign-off workflow, report packages, and bounded
  AI evidence lineage
- Source declaration: `contracts/domain-data-products/`
- Approved downstream consumers: `lotus-gateway`, `lotus-report`, `lotus-render`,
  `lotus-archive`, `lotus-workbench`, `lotus-ai`, `lotus-idea`
- Lotus Idea boundary: consumes policy-evaluation posture as governed opportunity constraint and
  evidence input; policy evaluation, waiver/sign-off workflow, and advisory compliance truth remain
  source-owned by `lotus-advise`.

- Product ID: `lotus-advise:AdvisorCockpitOperatingSnapshot:v1`
- Product role: source-owned RFC-0026 advisor operating snapshot for action counts, top-priority
  actions, unsupported-capability posture, supportability, Gateway publication, Workbench rendering,
  and canonical `PB_SG_GLOBAL_BAL_001` proof
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/advisor-cockpit-operating-snapshot.telemetry.v1.json`
- Approved downstream consumers: `lotus-gateway`, `lotus-workbench`

- Product ID: `lotus-advise:AdvisoryActionItemRegister:v1`
- Product role: source-owned RFC-0026 advisor action-item register for action identity, status,
  priority, owner role, SLA aging, evidence, lineage, and acknowledgement posture
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/advisory-action-item-register.telemetry.v1.json`
- Approved downstream consumers: `lotus-gateway`, `lotus-workbench`

- Product ID: `lotus-advise:AdvisoryCopilotInteractionRecord:v1`
- Product role: reviewed internal advisor/reviewer copilot interaction record for proposal-version
  evidence packets, persisted run/review records, workflow-pack lineage, claim-level source
  grounding, guardrail posture, and supportability posture
- Source declaration: `contracts/domain-data-products/`
- Approved downstream consumers: `lotus-gateway`, `lotus-workbench`, `lotus-idea`
- Lotus Idea boundary: consumes reviewed copilot interaction posture as decision-support signal;
  AI execution, review evidence, and advisory copilot controls remain source-owned by
  `lotus-advise` and `lotus-ai` according to their respective contracts.

## Platform relationship

`lotus-platform` aggregates the repo-native declaration, validates trust telemetry, applies mesh SLO/access/evidence policies, and includes this product in generated catalog, dependency graph, live certification, maturity matrix, evidence packs, and RFC-0092 operating reports.

### Telemetry evidence lifecycle

| Evidence | Location | Purpose |
| --- | --- | --- |
| Historical source fixture | `contracts/trust-telemetry/` | Preserves the original observation and derived stale/blocking posture |
| CI-certified runtime snapshot | `output/trust-telemetry/runtime/` | Proves the checked-out commit currently satisfies contract, lineage, completeness, and data-quality prerequisites |
| Platform certification output | `lotus-platform/output/mesh-certification/` | Applies cross-product SLO, access, lifecycle, evidence, publication, and consumption gates |

Runtime snapshots are generated by `make trust-telemetry-certify` with a full Git SHA and non-local
CI run identity. The platform prefers runtime evidence per product and falls back to historical
fixtures only when runtime evidence is absent. Invalid runtime evidence fails closed and cannot be
hidden by a fixture. Certification does not confer approval, suitability, compliance, or client
publication authority.

## Operating rule

Advisory lifecycle truth remains in `lotus-advise`. Tactical house-view cohort truth is bounded to
source-backed candidates and must not be replaced by decorative gateway or Workbench status.
`lotus-manage` owns discretionary portfolio-management workflows, policies, campaigns, and
evidence after consuming the cohort product.
Proposal narrative evidence truth remains advisor-review only. Compliance-review, client-draft,
client-ready publication, and external client communication remain unsupported unless a later
source-owned RFC implements and proves those controls.
Proposal memo evidence truth is active for advisor-use support only; client-ready memo publication
and external client communication remain blocked. RFC-0028 governs bank-demo/RFP proof through
supported claims without promoting client-ready memo publication.
Advisor cockpit product truth is active for source-owned advisor operating workflow evidence only.
Cockpit acknowledgements do not clear blockers, approve policy findings, contact clients, create
CRM system-of-record tasks, initiate OMS order lifecycle activity, or support full RFC-0028
demo/RFP package claims.
The `lotus-idea` proposal-intake foundation is not a data-product certification event. It preserves
the `AdvisoryProposalLifecycleRecord:v1` source boundary while allowing `lotus-idea` to prove a
future handoff path without cloning Advise suitability, proposal lifecycle, approval, or client
publication logic.
