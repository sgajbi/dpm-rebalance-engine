# RFC-0014: Data Quality, Snapshots, and Replayability

- Status: DRAFT
- Date: 2026-04-05
- Owners: lotus-advise
- Requires Approval From: lotus-advise maintainers
- Depends On: RFC-0007, RFC-0011, RFC-0013

## Summary

`lotus-advise` already produces deterministic proposal outputs, proposal artifacts, lineage
hashes, and replay-oriented evidence. It also supports `stateful` workspace context through the
Lotus Core seam.

What is still missing is one normalized replay and data-quality baseline that all advisory flows
can rely on.

This RFC defines that baseline:

1. canonical snapshot identity and provenance,
2. explicit data-quality posture for advisory inputs,
3. deterministic replay expectations across advisory outcomes,
4. stable evidence conventions that other RFCs can build on.

This RFC should be treated as the minimal truth-layer prerequisite for the next closure work in
`RFC-0019`.

## Why This Is Next

`lotus-advise` now has enough implemented lifecycle and workspace behavior that replayability can
no longer remain an implicit property.

Without this RFC:

1. authoritative context resolution can expand without one stable evidence vocabulary,
2. workspace replay and proposal replay can drift into different conventions,
3. execution reconciliation will have weaker before/after evidence anchors,
4. audit and support workflows will remain more manual than they should be.

## Problem Statement

Replay-related information exists today, but it is still fragmented:

1. proposal lineage and artifact hashes exist,
2. workspace saved versions carry replay evidence,
3. stateful workspaces return resolved context,
4. async operations carry their own status payloads.

What is not yet fully defined is:

1. the canonical snapshot identity model,
2. the minimum advisory data-quality contract,
3. the exact replay invariants shared across workspace, proposal, and async surfaces.

## Decision

`lotus-advise` should introduce one explicit replay and data-quality baseline that every advisory
surface can reuse.

The first version should stay narrow and practical.

It should define:

1. snapshot identity, source, and `as_of` semantics,
2. minimum required versus advisory-enrichment-only fields,
3. deterministic request and snapshot lineage hashing rules,
4. replay evidence references for workspace, proposal, and execution-adjacent flows,
5. stable data-quality diagnostics for missing, stale, or incomplete advisory inputs.

## Cross-RFC Boundaries

### This RFC owns

1. snapshot identity and provenance semantics,
2. minimum replay invariants,
3. minimum advisory data-quality diagnostics and blocking posture,
4. the shared evidence vocabulary that later closure work can reference.

### This RFC does not own

1. workspace contract shape, which remains under
   [RFC-0004](../../docs/rfcs/RFC-0004-iterative-advisory-proposal-workspace-contract.md),
2. lifecycle aggregate and audit ownership, which remains under
   [RFC-0013](../../docs/rfcs/RFC-0013-proposal-persistence-workflow-lifecycle.md),
3. policy-pack and jurisdiction behavior, which remains under
   [RFC-0015](../../docs/rfcs/RFC-0015-jurisdiction-policy-packs.md),
4. costs and frictions, which remain under
   [RFC-0016](../../docs/rfcs/RFC-0016-costs-fees-frictions-v1.md),
5. execution integration specifics, which remain under
   [RFC-0017](../../docs/rfcs/RFC-0017-execution-integration-interface.md),
6. broader runtime closure, which remains under
   [RFC-0019](../../docs/rfcs/RFC-0019-authoritative-context-runtime-and-workspace-closure.md).

## Architecture Direction

### 1. Snapshot Identity

Every major advisory input snapshot should carry stable provenance:

1. snapshot identifier,
2. source system or authority,
3. `as_of` timestamp,
4. schema version where needed,
5. canonical lineage hash or equivalent stable evidence reference.

### 2. Minimum Data-Quality Contract

The advisory runtime should distinguish:

1. data required for simulation correctness,
2. data required for suitability or gating quality,
3. enrichment that improves explanation but should not silently redefine core validity.

Missing or stale data should not produce ambiguous behavior. It should either:

1. block deterministically, or
2. degrade explicitly with stable advisory diagnostics.

### 3. Replay Invariants

The replay model should define which evidence elements are required to explain an advisory outcome:

1. request lineage,
2. snapshot lineage,
3. policy and configuration lineage where relevant,
4. result and artifact lineage,
5. resolved-context lineage for `stateful` operation.

### 4. Shared Evidence Vocabulary

The replay and data-quality contract should become the common evidence vocabulary reused by:

1. workspace save, compare, resume, and handoff,
2. proposal create and version flows,
3. async operation status and recovery,
4. future execution reconciliation.

## Delivery Slices

### Slice 1: Snapshot Identity and Lineage Baseline

Outcome:

1. one documented identity model for advisory snapshots and resolved context,
2. stable lineage references across proposal and workspace evidence.

Acceptance gate:

1. proposal and workspace evidence reference the same snapshot lineage vocabulary,
2. tests verify deterministic lineage generation.

### Slice 2: Minimum Data-Quality Posture

Outcome:

1. explicit advisory diagnostics for missing, stale, or incomplete inputs,
2. clear blocking versus degraded behavior for core data-quality failures.

Acceptance gate:

1. missing and stale data behaviors are explicit and tested,
2. no advisory flow silently succeeds with unverifiable core inputs.

### Slice 3: Replay Contract Alignment

Outcome:

1. workspace and lifecycle replay expectations align,
2. the evidence model is documented clearly enough for `RFC-0019` to build on directly.

Acceptance gate:

1. one saved workspace and one persisted proposal version can each be explained through the same
   replay vocabulary,
2. the documentation no longer leaves replay semantics implicit.

## Test and Validation Expectations

1. Unit tests for deterministic lineage and data-quality classification rules.
2. Contract tests for replay-oriented evidence fields in advisory models and OpenAPI docs.
3. Integration tests for replay-safe stateful context lineage where applicable.

## Rollout and Compatibility

1. This RFC should be implemented narrowly first.
2. Existing evidence fields may remain during transition, but the documented replay vocabulary
   should converge rather than proliferate.
3. `RFC-0019` should not be implemented beyond planning depth until the minimum slices here are
   stable.

## Risks

1. replay scope could expand into a full data-platform RFC,
2. data-quality policy could overlap too heavily with policy-pack ownership,
3. evidence models could become too verbose if payload design is not disciplined.

Mitigations:

1. keep this RFC focused on minimum replay and DQ invariants,
2. leave jurisdiction-specific policy under RFC-0015,
3. prefer stable references and concise diagnostics over oversized raw payload duplication.

## Acceptance Criteria

1. `lotus-advise` has one documented snapshot and replay baseline.
2. Minimum data-quality behavior is explicit for advisory-critical inputs.
3. Workspace and proposal evidence use the same replay vocabulary.
4. RFC-0019 can depend on this RFC without redefining replay semantics.

## Approval Requested

Approve RFC-0014 as the minimum replay and data-quality backbone required before broader runtime
closure work proceeds.
