# Lotus Advise Architecture Rules

## Enforcement Phase

- Current phase: regression-enforced for the configured architecture contracts and complexity
  rank boundary.
- Direction: preserve fail-on-new-regression controls while classifying stricter B-ranked Radon,
  Xenon, and absolute architecture thresholds.

## Boundary Rules

- API routers call application services or use cases only.
- API routers must not call repositories, database clients, HTTP clients, Kafka, Redis, or
  downstream adapters directly.
- Middleware stays thin and business-logic-free.
- Core domain and application modules must not depend on FastAPI, Starlette, framework request
  objects, infrastructure clients, or persistence adapters.
- Infrastructure sits behind repository, gateway, or adapter ports.
- DTOs and persistence models must not leak into domain decision logic.

## Current Evidence

- `.importlinter` defines the API-to-infrastructure, core-to-FastAPI, and infrastructure-to-API
  dependency boundaries; the `make lint` recipe invokes `make architecture-boundaries` to
  execute those contracts.
- The `make lint` recipe invokes `make complexity-regression-gate`, which fails C/D/E/F-ranked
  Radon blocks, and `make refactored-complexity-gate`, which keeps the previously remediated
  B-ranked modules below their stricter boundary.
- `quality/baseline_report.md` records the executable import-linter inventory and the current
  C/D/E/F complexity enforcement evidence.

## Remaining Calibration

- Classify current B-ranked helpers before tightening Radon or introducing stricter Xenon
  thresholds.
- Classify absolute architecture thresholds separately from the already enforced contract
  regression checks.
