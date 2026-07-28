# Dependency Hygiene Standard Alignment

Service: lotus-advise

This repository adopts the platform-wide standard defined in:
- `lotus-platform/Dependency Hygiene and Security Standard.md`
- `lotus-platform/Backend Foundation Standardization.md`

## Required Baseline

- No known high/critical dependency vulnerabilities are allowed.
- Dependency health must be validated in CI and before merge.
- Local and CI dependency checks should remain aligned.

## Execution Commands

- Local health check:
  - `python scripts/dependency_health_check.py --requirements requirements.txt --outdated-scope direct`
- Environment dependency consistency:
  - `python -m pip check`
- CI-aligned security audit target:
  - `make security-audit`
- License/IP release evidence:
  - `make dependency-lock`
  - `make dependency-lock-gate`
  - `make license-ip-inventory`
  - `make license-ip-gate`
- Report-only dependency inventory:
  - `python -m deptry . --config pyproject.toml --json-output output/deptry-report.json`

Deptry is calibrated as report-only. Current quality reports record whether the deptry
configuration is executable and the current issue count. Findings must be classified before deptry
becomes a fail-on-new-regression or blocking CI gate.

`make license-ip-gate` is blocking. It validates
`docs/standards/license-ip-inventory.v1.json` against
`docs/standards/license-ip-policy.v1.json` for runtime and development dependency graphs, including
transitive packages. Review-required license terms must have explicit owner-approved exceptions with
expiry dates; prohibited or unclassified terms fail the gate.

`make license-ip-inventory` and `make license-ip-gate` run the evidence generator inside a
temporary virtual environment installed from the governed runtime and development requirements
files. The temporary environment first pins pip/setuptools bootstrap tooling to governed versions and
runs pip in isolated mode so caller environment variables, pip user configuration, and bundled
`ensurepip` versions cannot determine license/IP release evidence. The inventory reflects the same
requirements graph that CI installs and the dependency-lock mirror validates.

`make dependency-lock-gate` is blocking. `uv.lock` is the generated dependency-lock mirror for the
requirements install strategy. It records requirement-file hashes, the license/IP inventory hash, and
the package closure used for local/CI/release evidence. Regenerate it with `make dependency-lock`
after any dependency manifest or generated dependency-inventory change.

## Update Cadence

- Patch/minor updates for tooling and low-risk libraries should be reviewed continuously.
- Runtime package major upgrades require explicit compatibility validation in unit, integration, and e2e buckets.
- Any dependency policy change must be documented in an ADR/RFC.

## Evidence

- CI job: `PR Merge Gate / Lint Typecheck Governance`
- Quality artifact: `quality/baseline_report.md`
- License/IP inventory: `docs/standards/license-ip-inventory.v1.json`
- License/IP policy: `docs/standards/license-ip-policy.v1.json`
- Dependency lock mirror: `uv.lock`
- Notice file: `NOTICE.md`
- Platform conformance artifacts under `lotus-platform/output/`
