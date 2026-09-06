# RFC-0017: Execution Integration Interface

- Status: DRAFT
- Date: 2026-04-05
- Owners: lotus-advise
- Requires Approval From: lotus-advise maintainers
- Depends On: RFC-0011, RFC-0012, RFC-0013

## Summary

`lotus-advise` already exposes advisory-side execution-handoff APIs and execution-status reads.

What it does not yet have is a finalized execution integration contract covering:

1. normalized execution request identity,
2. downstream execution update ingestion,
3. advisory-side reconciliation semantics,
4. clean separation between advisory ownership and OMS or broker ownership.

This RFC should now be interpreted as the execution-boundary RFC for `lotus-advise`, not as a
placeholder for full broker implementation detail.

## Why This Is Next

Execution is no longer hypothetical in the advisory model:

1. lifecycle already includes execution-ready posture,
2. execution handoff is already part of the shipped advisory surface,
3. `RFC-0019` needs a stable execution contract before it can close the reconciliation loop.

Without this RFC:

1. advisory execution ownership stays underspecified,
2. downstream status updates will be implemented ad hoc,
3. lifecycle and execution reconciliation risk drifting into mixed ownership.

## Problem Statement

The current service can record advisory intent to hand off execution, but it does not yet define
the full authoritative contract for what happens next.

The unresolved questions are:

1. what is the canonical advisory execution request identity,
2. what execution states and events are stable enough for advisory-side lifecycle reconciliation,
3. how should downstream systems return updates,
4. what data belongs in `lotus-advise` versus what remains external execution truth.

## Decision

`lotus-advise` should define one vendor-neutral execution integration contract with two clear
boundaries:

1. advisory-owned execution handoff and reconciliation,
2. downstream-owned order routing and fill execution.

The first implementation should stay narrow:

1. deterministic execution request and ticket lineage,
2. idempotent handoff semantics,
3. downstream update ingestion contract,
4. advisory-side execution status and reconciliation model.

## Cross-RFC Boundaries

### This RFC owns

1. advisory execution request shape,
2. execution ticket and dependency lineage,
3. downstream execution update contract,
4. advisory-side execution state and reconciliation semantics.

### This RFC does not own

1. proposal artifact structure, which remains under
   [RFC-0011](../../docs/rfcs/RFC-0011-proposal-artifact.md),
2. workflow gate semantics, which remain under
   [RFC-0012](../../docs/rfcs/RFC-0012-advisory-workflow-gates.md),
3. lifecycle persistence and audit ownership, which remain under
   [RFC-0013](../../docs/rfcs/RFC-0013-proposal-persistence-workflow-lifecycle.md),
4. broad runtime closure and evidence convergence, which remain under
   [RFC-0019](../../docs/rfcs/RFC-0019-authoritative-context-runtime-and-workspace-closure.md),
5. post-trade surveillance and oversight, which remain under
   [RFC-0018](../../docs/rfcs/RFC-0018-monitoring-surveillance-post-trade-controls.md).

## Architecture Direction

### 1. Canonical Execution Request

An execution request should identify:

1. proposal aggregate and immutable version,
2. advisory actor and submission context,
3. execution policy options,
4. deterministic lineage to the advisory artifact and intent ordering.

### 2. Deterministic Ticket Model

Trade tickets should remain deterministic and dependency-aware.

Required direction:

1. stable ticket identity derived from advisory lineage,
2. explicit dependency ordering,
3. explicit mapping from advisory intents to execution requests.

### 3. Downstream Update Contract

`lotus-advise` should define one stable ingestion path for downstream execution events.

Required direction:

1. idempotent update handling,
2. stable correlation keys,
3. append-only event posture for support and audit,
4. explicit terminal and non-terminal execution outcomes.

### 4. Advisory-Side Reconciliation

`lotus-advise` should reconcile execution outcomes back into advisory lifecycle truth without
claiming to be the execution engine itself.

Required direction:

1. accepted, rejected, partial, executed, cancelled, and expired outcomes must be explicit,
2. lifecycle and execution posture must remain explainable from durable evidence,
3. unmatched or inconsistent downstream updates must surface as reviewable exceptions.

## Delivery Slices

### Slice 1: Canonical Handoff and Ticket Contract

Outcome:

1. finalize advisory execution request identity,
2. finalize deterministic ticket and dependency lineage.

Acceptance gate:

1. handoff payload and execution lineage are documented and tested,
2. the advisory contract stays vendor-neutral.

### Slice 2: Downstream Update Ingestion Contract

Outcome:

1. one stable webhook or ingestion contract for downstream execution updates,
2. idempotent event handling and durable event history.

Acceptance gate:

1. downstream updates can be correlated deterministically to advisory execution requests,
2. duplicate updates do not create ambiguous execution state.

### Slice 3: Advisory Reconciliation Baseline

Outcome:

1. advisory execution posture derives from handoff plus downstream updates,
2. lifecycle reconciliation semantics are explicit enough for `RFC-0019` slice 4.

Acceptance gate:

1. accepted, rejected, partial, executed, cancelled, and expired postures are supported,
2. advisory-side execution state is explainable from persisted evidence.

## Test and Validation Expectations

1. Unit tests for deterministic ticket generation and execution-state transitions.
2. Integration tests for idempotent downstream update ingestion.
3. Contract tests for execution-handoff and update payloads.

## Rollout and Compatibility

1. Existing execution-handoff APIs should be extended, not replaced.
2. External OMS-specific adapters should remain a later implementation detail.
3. `RFC-0019` execution-reconciliation work should build on this RFC rather than redefining the
   execution contract itself.

## Risks

1. execution scope could drift into OMS implementation detail,
2. lifecycle ownership and execution ownership could blur,
3. reconciliation could be attempted before durable evidence is strong enough.

Mitigations:

1. keep the contract vendor-neutral,
2. keep order execution ownership downstream,
3. align closely with RFC-0013 lifecycle evidence and RFC-0019 closure sequencing.

## Acceptance Criteria

1. `lotus-advise` has one stable execution integration contract.
2. Downstream execution update ingestion and advisory reconciliation semantics are explicit.
3. RFC-0019 can build execution closure on top of this RFC without redefining execution basics.

## Approval Requested

Approve RFC-0017 as the execution-boundary RFC that stabilizes advisory-side handoff, downstream
update ingestion, and reconciliation semantics.
