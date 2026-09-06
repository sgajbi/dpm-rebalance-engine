# Proposal Lifecycle

Current scope: every stage below is implemented and persisted. Evidence sections state what is
recorded at each transition rather than what is planned.

## Reader Map

| Read this section | When you need |
|---|---|
| [Core Model](#core-model) | the aggregate, versions, events and approval records |
| [What Creation Does](#what-creation-does) | what is written when a proposal first appears |
| [Versioning](#versioning) | how immutable versions relate to the aggregate |
| [Transitions And Approvals](#transitions-and-approvals) | which state changes are legal, and who records them |
| [Delivery And Execution Posture](#delivery-and-execution-posture) | how posture is derived from workflow history |
| [Decision Summary And Alternatives](#decision-summary-and-alternatives) | what a proposal records about the choice it represents |
| [Valuation-Context Evidence](#valuation-context-evidence) | the valuation facts captured alongside a decision |
| [Benchmark And Mandate-Limit Evidence](#benchmark-and-mandate-limit-evidence) | benchmark and limit checks retained for audit |

## Core Model

The lifecycle surface persists advisory proposals as:

- one proposal aggregate
- immutable versions
- append-only workflow events
- structured approval records
- delivery and execution posture derived from workflow history

## What Creation Does

`POST /advisory/proposals` does more than storage. It:

1. runs advisory simulation,
2. builds the deterministic proposal artifact,
3. persists the first immutable version,
4. creates workflow audit history,
5. stores idempotency mapping.

## Versioning

New versions are created through `POST /advisory/proposals/{proposal_id}/versions`.

The model is immutable-by-version. A later version does not overwrite the earlier one. That keeps replay, support, and audit continuity intact.

### Proposal-create replay compatibility

When a preserved proposal-create idempotency key is retried, Advise first checks the canonical
command hash. For older records whose request-model or narrative enrichment evolved, it may use
the persisted proposal, resolved context, and narrative request semantics to return the original
proposal/version. The idempotency command hash and the immutable proposal-version request hash
describe different canonicalization domains and are not required to be equal. A change to the
creator, portfolio, lifecycle context, metadata, requested narrative, or other command semantics
still fails with an idempotency conflict; callers must preserve the original key and must not
delete durable state or rotate the key to bypass that decision. Stateful legacy matching compares
each resolved proposal field exactly: omitted metadata does not act as a wildcard, while a field
that is absent on both sides remains a valid match when both stored and expected values are null.

## Transitions And Approvals

The lifecycle API separates:

- generic state transitions
- explicit approval recording

Approval and consent are structured workflow actions, not ad hoc annotations. The repository demo set includes grounded examples for:

- transition to compliance review
- client consent approval
- compliance approval
- transition to executed

## Delivery And Execution Posture

`lotus-advise` tracks advisory-owned delivery posture without taking over reporting or execution ownership.

It can:

- request a report payload through the `lotus-report` integration boundary
- record an execution handoff
- ingest vendor-neutral execution updates
- expose delivery summary, delivery history, and execution status

Execution handoff events and execution posture responses include structured ownership-boundary
evidence. The advisory role is handoff request and status reconciliation. The downstream execution
provider remains the execution system of record.

## Decision Summary And Alternatives

Persisted proposal surfaces expose backend-owned:

- `proposal_decision_summary`
- `proposal_alternatives`

These are part of the lifecycle evidence story and should remain tied to canonical upstream simulation and enrichment.

## Valuation-Context Evidence

Lifecycle create, version, simulation, and workspace-evaluation responses carry an additive
`valuation_context` contract inside the proposal result. It publishes separate typed evidence for
the current and simulated states:

- requested and effective as-of date or timestamp
- requested and effective reporting currency
- `READY`, `PARTIAL`, `RESTRICTED`, `UNAVAILABLE`, or `NOT_SUPPORTED` supportability
- stable reason codes when source dates disagree, a request is not honoured, or evidence is absent

Requested date and currency fields are populated only when the caller explicitly provides those
dimensions; a portfolio base currency is effective source evidence, not a synthesized request.
Stateful workspace-to-proposal handoff preserves those caller-requested dimensions through the
typed valuation context for both the current and simulated proposal states while retaining the
workspace's edited simulation payload. A source-context override changes context authority only;
it does not discard draft trades, cash flows, options, or other workspace-owned simulation input.
`ProposalResolvedContext.as_of` is an optional lifecycle context date used for evaluation, replay,
or upstream routing. Direct/stateless requests do not synthesize a current date when no reference
model or source-owned date is present. It is not authoritative valuation evidence: consumers must use
`valuation_context.current_state.effective_as_of_date` or
`valuation_context.simulated_state.effective_as_of_date`. When both requested date and currency
are not honored, `reason_code` reports the primary date reason and is not a complete mismatch list.
Core-authoritative stateful proposal create, version, and simulation resolution fails closed with
`WORKSPACE_STATEFUL_CONTEXT_AS_OF_MISSING` when the resolved source context omits its required date;
this does not change the honest nullable-date behavior for direct/stateless requests.
Normalized proposal replay evidence preserves the same lifecycle context with `as_of: null` when
the direct/stateless source context has no explicit date; it does not discard the portfolio or
snapshot identity.

The contract also carries the authoritative source service and stable source snapshot references.
Missing provenance is represented as unavailable or partial evidence; the service never substitutes
today's date, zero, pass, approval, or an inferred valuation. `lotus-core` remains the source-data
and simulation authority, while `lotus-advise` owns the lifecycle projection and does not recalculate
valuation, benchmark, limit, risk, suitability, or reporting methodology.

## Benchmark And Mandate-Limit Evidence

Proposal simulation and immutable lifecycle-version responses also carry the additive
`proposal_review_evidence` envelope. It keeps the requested benchmark and mandate identifiers and
requested as-of context separate from effective source evidence:

- `benchmark_assignment` contains requested/effective identifiers, requested/effective as-of dates,
  source references, and supportability.
- `current_mandate_limits` and `simulated_mandate_limits` are separate state projections with typed
  observations, units, thresholds, outcomes, severity, and source references when an authoritative
  producer supplies them.
- Advise does not currently consume Core's existing benchmark-assignment route, and no mapped
  source-owned mandate-limit observation contract is available to this envelope. The contract
  therefore returns `UNAVAILABLE`, null effective values, empty observations, and stable reason
  codes rather than promoting a selector or interpreting generic `rule_results` as mandate evidence.

This is an explicit capability boundary, not a positive benchmark/limit claim. Advise does not
calculate benchmark returns, limit breaches, materiality, or acceptability. A future adapter/producer
mapping must supply source authority, effective dates, and stable references before the envelope can
move beyond the unavailable posture. The existing Core route is a named revisit point; Advise must
not silently leave the published unavailable posture in place after adding that route to its Core
client.

### Memo report-package source-date handoff

The reviewed-memo report-package request maps its Lotus Report `as_of_date` from the typed
`valuation_context.current_state.effective_as_of_date` and
`valuation_context.simulated_state.effective_as_of_date` source evidence. Advise submits the
request only when those supported source values resolve to exactly one normalized date. Missing
or conflicting current/simulated dates fail closed before the downstream call; Advise never uses
the current clock date, a request-body fallback, or a guessed portfolio date.

If source mapping or the Lotus Report provider is unavailable, the API returns the documented
503 unavailable contract and does not leak an unhandled 500. Idempotent replay remains owned by
the memo event operation and does not create a downstream report job after a replayed event is
found.
