# RFC-0019: Authoritative Context, Durable Runtime, and Workspace Closure

- Status: IMPLEMENTED
- Date: 2026-04-05
- Owners: lotus-advise
- Requires Approval From: lotus-advise maintainers
- Depends On: RFC-0004, RFC-0005, RFC-0006, RFC-0011, RFC-0013, RFC-0014, RFC-0017

## Summary

`lotus-advise` already has the core advisory surface:

1. proposal simulation, artifact generation, workflow gates, and lifecycle persistence,
2. iterative workspaces for `stateless` and `stateful` operation,
3. readiness-aware capability reporting,
4. advisory AI rationale, report-request, and execution-handoff seams,
5. RFC-0067 OpenAPI and vocabulary governance.

This RFC does not propose another broad product expansion wave.

It defines the narrower closure work required to make the current product shape operationally
authoritative:

1. unify authoritative context resolution across proposal APIs, not just workspace flows,
2. harden async proposal operations into durable runtime truth,
3. converge workspace, proposal, and async evidence into one replay model,
4. close the loop on execution updates and advisory-side reconciliation.

## Why This Is Next

The implemented baseline proves the product direction, but it still leaves transitional seams:

1. `stateful` context is stronger in workspace flows than in proposal lifecycle flows,
2. async contracts exist, but enterprise-grade runtime semantics are not yet fully explicit,
3. replay evidence exists, but remains spread across workspace, lifecycle, and async surfaces,
4. execution handoff exists, but downstream status and reconciliation are not yet complete.

Those are now the highest-value remaining gaps.

## Problem Statement

`lotus-advise` has crossed the line from demo-grade advisory engine to real advisory workflow
service, but it is not yet the complete system of workflow truth for advisor-led proposal
management.

The unresolved problems are:

1. proposal APIs still lean more heavily on caller-assembled context than the target operating
   model implies,
2. async operation truth needs clearer claim, retry, restart, and retention semantics,
3. support and audit users still need to piece together replay truth from multiple evidence models,
4. execution remains handoff-ready more than fully reconciled.

## Decision

`lotus-advise` should complete a two-wave closure program.

### Wave 1

Wave 1 hardens the platform spine:

1. authoritative context policy for proposal APIs,
2. durable async runtime semantics,
3. unified evidence and replay lineage.

### Wave 2

Wave 2 hardens the business closure loop:

1. durable workspace-to-lifecycle evidence continuity,
2. governed rationale and collaboration metadata hardening,
3. execution update ingestion and reconciliation.

The sequencing is intentional. The service should not widen product surface area again before the
current seams become authoritative.

## Cross-RFC Boundaries

RFC-0019 is intentionally a closure RFC. It does not reopen or replace the implemented advisory
foundation.

### Already implemented and not redefined here

1. [RFC-0004](../../docs/rfcs/RFC-0004-iterative-advisory-proposal-workspace-contract.md)
   owns the existence and baseline shape of the workspace contract.
2. [RFC-0005](../../docs/rfcs/RFC-0005-postgres-only-advisory-runtime-hard-cutover.md)
   owns the Postgres runtime and persistence posture.
3. [RFC-0006](../../docs/rfcs/RFC-0006-lotus-advise-target-operating-model-and-integration-architecture.md)
   owns service boundary and upstream/downstream ownership rules.
4. [RFC-0007](../../docs/rfcs/RFC-0007-advisory-proposal-simulate-mvp.md),
   [RFC-0008](../../docs/rfcs/RFC-0008-advisory-proposal-auto-funding.md),
   [RFC-0009](../../docs/rfcs/RFC-0009-drift-analytics.md), and
   [RFC-0010](../../docs/rfcs/RFC-0010-suitability-scanner-v1.md)
   own the current advisory evaluation baseline.
5. [RFC-0011](../../docs/rfcs/RFC-0011-proposal-artifact.md)
   owns the artifact payload shape.
6. [RFC-0012](../../docs/rfcs/RFC-0012-advisory-workflow-gates.md)
   owns workflow gate and next-step semantics.
7. [RFC-0013](../../docs/rfcs/RFC-0013-proposal-persistence-workflow-lifecycle.md)
   owns proposal persistence, lifecycle, lineage, and audit model.

### Future RFCs that remain in force after RFC-0019

1. [RFC-0014](../../docs/rfcs/RFC-0014-data-quality-snapshots-replayability.md)
   should own detailed snapshot and data-quality policy. RFC-0019 only requires evidence
   convergence, not a full DQ policy rewrite.
2. [RFC-0015](../../docs/rfcs/RFC-0015-jurisdiction-policy-packs.md)
   should continue owning jurisdiction and policy-pack behavior.
3. [RFC-0016](../../docs/rfcs/RFC-0016-costs-fees-frictions-v1.md)
   should continue owning transaction-cost and friction modeling.
4. [RFC-0017](../../docs/rfcs/RFC-0017-execution-integration-interface.md)
   should continue owning external execution integration specifics. RFC-0019 only closes the
   advisory-side runtime and reconciliation seam.
5. [RFC-0018](../../docs/rfcs/RFC-0018-monitoring-surveillance-post-trade-controls.md)
   should continue owning broader post-trade surveillance and oversight.

## Architecture Direction

### 1. Authoritative Context Across Proposal APIs

The same `stateless` and `stateful` context model used in workspace flows should become a
first-class proposal-runtime concern.

Required direction:

1. proposal simulation, create, and version-create flows should support identifier-based context
   resolution through the same Lotus Core seam already used by stateful workspaces,
2. explicit overrides and fallback behavior must be captured in evidence,
3. no proposal flow should silently degrade from authoritative context to local assumptions,
4. `simulate` and `workspace` must remain two API surfaces for different operating modes, but
   they must converge on one evaluation contract underneath,
5. when `simulate` and `workspace` evaluate the same canonical `ProposalSimulateRequest`, they
   must produce the same advisory result semantics, subject only to intentionally different
   envelope metadata such as correlation id, workspace session metadata, or replay evidence.

Consistency rule:

1. `simulate` is the stateless deterministic evaluation contract,
2. `workspace` is the stateful drafting contract,
3. both must resolve to the same canonical evaluation request shape and invoke the same
   authoritative evaluation logic,
4. differences between the two surfaces must be limited to state-management concerns, not
   advisory calculation behavior.

### 2. Durable Async Runtime Truth

The existing Postgres-backed async operation record should become the authoritative source of async
runtime truth.

Required direction:

1. explicit claim, attempt, retry, and terminal-state semantics,
2. restart-safe operation handling,
3. retention and recovery posture,
4. supportability reads derived from persisted state, not process-local memory.

### 3. Unified Evidence and Replay Model

`lotus-advise` should converge its current evidence surfaces into one explainable advisory replay
model spanning:

1. resolved context lineage,
2. proposal lineage and artifact hashes,
3. workspace saved-version and handoff lineage,
4. async operation lineage,
5. execution-handoff and reconciliation lineage.

### 4. Execution Closure

`lotus-advise` should remain the advisory owner of handoff and reconciliation while leaving actual
order execution ownership downstream.

Required direction:

1. ingest downstream execution updates idempotently,
2. reconcile lifecycle and execution posture deterministically,
3. make partial, rejected, cancelled, expired, and executed outcomes explicit.

## Delivery Slices

### Slice 1: Proposal API Context Unification

Outcome:

1. shared advisory context policy across workspace and proposal lifecycle flows,
2. additive `stateful` proposal flows,
3. explicit lineage for overrides and degraded resolution.

Acceptance gate:

1. proposal APIs run in `stateless` and `stateful` modes with stable evidence,
2. context-resolution failure modes are explicit and tested,
3. OpenAPI and vocabulary artifacts remain RFC-0067-compliant,
4. contract and integration tests prove that a stateless workspace evaluation and direct
   simulation produce equivalent advisory outcomes when given the same canonical input.

### Slice 2: Async Runtime Hardening

Outcome:

1. durable claim, retry, restart, and retention semantics for proposal async operations,
2. authoritative async inspection surfaces for support and operators.

Acceptance gate:

1. restart-safe async behavior is covered by integration tests,
2. operation status remains correct after restart and failure scenarios,
3. runtime truth does not depend on in-process-only state.

### Slice 3: Evidence Convergence

Outcome:

1. one normalized replay model across workspace, proposal lifecycle, and async execution,
2. stable evidence continuity through workspace save, compare, resume, and handoff.

Acceptance gate:

1. a saved workspace and a persisted proposal version can each be replayed and explained from
   documented evidence references,
2. workspace-to-lifecycle handoff preserves evidence continuity.

### Slice 4: Execution Reconciliation Closure

Outcome:

1. downstream execution updates are ingested into advisory-visible history,
2. execution posture and proposal lifecycle reconcile deterministically.

Acceptance gate:

1. execution updates are idempotent and correlation-safe,
2. advisory execution posture supports accepted, rejected, partial, executed, cancelled, and
   expired outcomes consistently,
3. RFC-0017 remains focused on external integration specifics instead of basic advisory closure.

## Test and Validation Expectations

1. Unit tests for context policy, evidence assembly, and reconciliation logic.
2. Integration tests for Postgres-backed async restart safety and execution update ingestion.
3. Contract tests for OpenAPI examples, no-alias governance, and vocabulary drift.
4. End-to-end coverage for:
   1. `stateful` workspace to lifecycle handoff,
   2. durable async proposal create,
   3. execution handoff followed by downstream status reconciliation.
5. Explicit parity tests for:
   1. direct `simulate` versus `workspace` reevaluation on identical canonical input,
   2. lifecycle create/version versus reevaluated workspace handoff input equivalence,
   3. degraded-resolution and authoritative-resolution evidence differences without calculation
      drift.

## Rollout and Compatibility

1. Existing `stateless` proposal and workspace flows remain supported.
2. `stateful` proposal flows should be additive first and become the preferred production path only
   after validation.
3. Async hardening should preserve current endpoint shapes where possible.
4. Execution update ingestion should extend the current handoff model, not replace it.

## Risks

1. context-resolution expansion could blur ownership with `lotus-core`,
2. async hardening could over-expand into premature queue infrastructure,
3. evidence convergence could create oversized stored payloads,
4. execution reconciliation could drift into OMS ownership.

Mitigations:

1. keep upstream authority seams explicit,
2. stay Postgres-first for the initial durable async runtime,
3. prefer reference-plus-lineage storage over opaque duplication,
4. keep execution ownership downstream and advisory reconciliation upstream-facing.

## Acceptance Criteria

1. `lotus-advise` supports authoritative `stateful` proposal flows beyond workspace-only seams.
2. Async proposal operations are durable, restart-safe, and supportable from persisted state.
3. Workspace, proposal lifecycle, and async evidence share one documented replay model.
4. Execution handoff is extended with downstream update and reconciliation semantics.
5. `simulate` and `workspace` are documented as different operating surfaces over one consistent
   evaluation contract.
6. New contracts and docs remain aligned with `lotus-platform` and RFC-0067.

## Implementation Record

RFC-0019 is now implemented in `lotus-advise`.

Delivered closure:

1. proposal lifecycle create/version flows now support normalized `stateless` and `stateful`
   advisory context resolution through the same Lotus Core seam used by workspace flows,
2. direct `simulate` and artifact generation now support the same normalized context contract while
   preserving legacy payload compatibility,
3. async proposal operations are restart-safe and derived from persisted runtime truth,
4. workspace, lifecycle, and async surfaces now share normalized replay evidence contracts,
5. execution handoff is extended with downstream update ingestion and deterministic reconciliation.

Validation evidence:

1. `python -m pytest` -> `375 passed`
2. `python -m ruff check src tests` -> passed
3. `python -m mypy src` -> passed
4. `python scripts/openapi_quality_gate.py` -> passed
5. `python scripts/no_alias_contract_guard.py` -> passed
6. `python scripts/api_vocabulary_inventory.py --validate-only` -> passed
