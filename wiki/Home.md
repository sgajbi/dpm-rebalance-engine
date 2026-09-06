# Lotus Advise Wiki

`lotus-advise` is the Lotus advisory workflow service. It owns advisor-led proposal simulation orchestration, proposal lifecycle state, approvals and consent workflow behavior, advisory workspace drafting, execution readiness posture, and bounded tactical house-view affected-cohort evaluation.

It does not own canonical portfolio source data, risk methodology, performance methodology, or downstream execution. Those responsibilities stay with upstream or adjacent Lotus services and are consumed through governed integration boundaries.

## Current Scope And Evidence Posture

The implemented surface is backend-owned advisory workflow and evidence production. Supported
claims must trace to code, tests, RFCs, contracts, API routes, or generated proof artifacts in this
repository. Client-ready publication, OMS execution, report rendering ownership, risk methodology,
performance methodology, and canonical portfolio source authority remain outside `lotus-advise`
unless a supported-feature page and implementation evidence say otherwise.

## Reader Paths

- Business and product readers: start with [Overview](Overview), [Supported Features](Supported-Features), and [Proposal Lifecycle](Proposal-Lifecycle).
- Sales, pre-sales, and demo readers: use [Demo Readiness Guide](Demo-Readiness-Guide) and [Demo and Commercial Proof](Demo-and-Commercial-Proof).
- Operations and support readers: use [Operations Runbook](Operations-Runbook), [Troubleshooting](Troubleshooting), and [Validation and CI](Validation-and-CI).
- Engineering readers: use [Architecture](Architecture), [API Surface](API-Surface), [Integrations](Integrations), and [Development Workflow](Development-Workflow).
- Agent and governance readers: use [Security and Governance](Security-and-Governance), [RFC Index](RFC-Index), and [Mesh Data Products](Mesh-Data-Products).

## Common Commands

- `make check`
- `make demo-certification-live`
- `python scripts/postgres_migrate.py --target all`
- `make wiki-quality-gate` — runs the platform-owned wiki audit against this repository's `wiki/`, resolving the auditor path itself so no workspace layout is assumed

## Service Identity

- Service: `lotus-advise`
- API docs: `/docs`
- Health probes: `/health`, `/health/live`, `/health/ready`

## Navigation

- [Overview](Overview)
- [Getting Started](Getting-Started)
- [Architecture](Architecture)
- [API Surface](API-Surface)
- [Supported Features](Supported-Features)
- [Demo Readiness Guide](Demo-Readiness-Guide)
- [Demo and Commercial Proof](Demo-and-Commercial-Proof)
- [Proposal Lifecycle](Proposal-Lifecycle)
- [Advisory Workspace](Advisory-Workspace)
- [Development Workflow](Development-Workflow)
- [Operations Runbook](Operations-Runbook)
- [Security and Governance](Security-and-Governance)
- [Troubleshooting](Troubleshooting)
- [Integrations](Integrations)
- [Validation and CI](Validation-and-CI)
- [RFC Index](RFC-Index)
- [Mesh Data Products](Mesh-Data-Products)

## Grounding Sources

- `README.md`
- `docs/architecture/RFC-0082-upstream-contract-family-map.md`
- `docs/demo/README.md`
- `docs/operations/development-workflow-and-ci-strategy.md`
- `docs/rfcs/README.md`
- `contracts/domain-data-products/lotus-advise-products.v1.json`
- FastAPI route families under `src/api/`
