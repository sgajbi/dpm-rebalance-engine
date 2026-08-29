# Dependency Hygiene Standard Alignment

Service: lotus-advise

This repository adopts the platform-wide standard defined in:
- `lotus-platform/Dependency Hygiene and Security Standard.md`
- `lotus-platform/Backend Foundation Standardization.md`

## Required Baseline

- No known high/critical dependency vulnerabilities are allowed.
- Dependency health, installation consistency, lock integrity, and licence posture must be
  validated in CI and before merge.
- Availability of a newer direct-package release is maintenance evidence, not a change-attributable
  merge failure. Strict freshness is evaluated by the scheduled maintenance lane.
- Local and CI dependency checks should remain aligned.

## Execution Commands

- Local health check:
  - `python scripts/dependency_health_check.py --requirements requirements.txt --outdated-scope direct`
- Environment dependency consistency:
  - `python -m pip check`
- CI-aligned security audit target:
  - `make security-audit`
- Strict direct-package freshness maintenance target:
  - `make check-deps-strict`
- License/IP release evidence:
  - `make dependency-lock`
  - `make dependency-lock-gate`
  - `make license-ip-inventory`
  - `make license-ip-gate`
- Unused-dependency regression gate:
  - `make unused-dependency-gate`
  - `python -m scripts.dependency_hygiene_gate --policy quality/dependency-hygiene-policy.v1.json --output output/dependency-hygiene-gate.json`

Deptry `0.25.1` is now a fail-closed, no-new-regression gate. The policy and baseline are
content-hashed and the gate rejects tool-version drift, malformed output, new findings, resolved
baseline findings, duplicate normalized fingerprints, expired owner/reason entries, and stale
policy/baseline hashes. The current inventory has 13 explicitly classified entries: twelve pinned
runtime-closure constraints and the command-invoked `uvicorn` launcher. The local
`ci_local_compose_project` import is configured as first-party and therefore is not an exception.
The gate emits policy, tool, current/baseline counts, new/resolved findings, and provenance in
`output/dependency-hygiene-gate.json` and runs in local `check`/`ci` targets plus Feature Lane, PR
Merge Gate, and Main Releasability.

`make license-ip-gate` is blocking. It validates
`docs/standards/license-ip-inventory.v1.json` against
`docs/standards/license-ip-policy.v1.json` for runtime and development dependency graphs, including
transitive packages. Review-required license terms must have explicit owner-approved exceptions with
expiry dates; prohibited or unclassified terms fail the gate.

`make license-ip-inventory` and `make license-ip-gate` run the evidence generator inside a
temporary virtual environment installed from the governed runtime and development requirements
files. The temporary environment first pins pip/setuptools bootstrap tooling to governed versions,
projects exact package constraints from `uv.lock`, and runs pip in isolated mode so caller
environment variables, pip user configuration, bundled `ensurepip` versions, or an upstream
transitive release cannot determine license/IP release evidence. The inventory reflects the same
requirements graph that CI installs and the dependency-lock mirror validates.

The blocking comparison treats a transitive version-only change as non-governance drift, because the
lock projection controls the installed version. New transitive packages, license-term changes,
policy-classification changes, dependency-group changes, and exception changes remain blocking and
print the affected package plus current/expected evidence. Direct requirement and policy changes
still require the committed inventory and lock evidence to be regenerated deliberately.

The Starlette TestClient posture is explicit: development and CI installs include the stable,
directly pinned `httpx2` compatibility client because Starlette 1.6 deprecates its fallback to
`httpx`. Production adapters remain on the separately governed `httpx` runtime dependency; this
test-only compatibility dependency must not be used to imply a production HTTP-client migration.
The dependency regression test runs a real FastAPI TestClient probe with deprecation warnings
treated as errors.

`make dependency-lock-gate` is blocking. `uv.lock` is the generated dependency-lock mirror for the
requirements install strategy. It records requirement-file hashes, the license/IP inventory hash, and
the package closure used for local/CI/release evidence. Regenerate it with `make dependency-lock`
after any dependency manifest or generated dependency-inventory change.

## Update Cadence

- The `Dependency Maintenance` workflow runs `make check-deps-strict` nightly and supports manual
  dispatch. Its failure is an explicit dependency-refresh prompt owned outside unrelated feature
  PRs.
- Patch/minor updates for tooling and low-risk libraries should be reviewed continuously.
- Runtime package major upgrades require explicit compatibility validation in unit, integration, and e2e buckets.
- Any dependency policy change must be documented in an ADR/RFC.

## Evidence

- CI job: `PR Merge Gate / Lint Typecheck Governance`
- Scheduled job: `Dependency Maintenance / Direct Dependency Freshness`
- Quality artifact: `quality/baseline_report.md`
- License/IP inventory: `docs/standards/license-ip-inventory.v1.json`
- License/IP policy: `docs/standards/license-ip-policy.v1.json`
- Dependency lock mirror: `uv.lock`
- Notice file: `NOTICE.md`
- Platform conformance artifacts under `lotus-platform/output/`
