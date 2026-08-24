# Proposal Lifecycle

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

The contract also carries the authoritative source service and stable source snapshot references.
Missing provenance is represented as unavailable or partial evidence; the service never substitutes
today's date, zero, pass, approval, or an inferred valuation. `lotus-core` remains the source-data
and simulation authority, while `lotus-advise` owns the lifecycle projection and does not recalculate
valuation, benchmark, limit, risk, suitability, or reporting methodology.
