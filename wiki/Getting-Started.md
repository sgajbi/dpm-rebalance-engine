# Getting Started

Current scope: every command below is implemented and runs against this repository today.

## Reader Map

| Read this section | When you need |
|---|---|
| [Before The First Command](#before-the-first-command) | a fresh checkout, before running anything |
| [Key Commands](#key-commands) | the repo-native install, check and run targets |
| [Local Expectations](#local-expectations) | what upstream integrations local Docker validation assumes |
| [API Discovery](#api-discovery) | finding the route families and contract surface |
| [Demo Scenarios](#demo-scenarios) | running the governed demo path rather than ad hoc calls |

## Before The First Command

`make install` resolves to `install-ci`, which runs `python -m pip install` directly rather than
into a managed environment. Create and activate a virtualenv FIRST: PEP 668 distributions (most
current Linux packages, and Homebrew Python on macOS) mark the system interpreter externally
managed and refuse a system-wide `pip install`. This has not been reproduced by the maintainers;
it is the specified behaviour of PEP 668. CI does not need the step because `actions/setup-python`
supplies an isolated interpreter, which is why the requirement stays invisible in a green
pipeline.

`venv/` is this repository's conventional location and is already gitignored.

On Linux or macOS:

```bash
python3 -m venv venv
. venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

## Key Commands

- `make install`
- `make check`
- `make ci`
- `make ci-local-docker`
- `make run`

## Local Expectations

`lotus-advise` expects canonical upstream integrations to be explicit during local Docker validation:

- `LOTUS_CORE_BASE_URL`
- `LOTUS_CORE_QUERY_BASE_URL`
- `LOTUS_RISK_BASE_URL`
- `LOTUS_RISK_TIMEOUT_SECONDS`
- `LOTUS_RISK_RETRY_ATTEMPTS`
- `LOTUS_RISK_RETRY_BACKOFF_SECONDS`
- `LOTUS_ADVISE_TENANT_ID`

These bindings keep proposal simulation and advisory risk-lens behavior aligned to the actual upstream authorities instead of local stand-ins.
The app-local Compose manifest supplies `LOTUS_ADVISE_TENANT_ID=tenant-sg-001` as the canonical
developer fixture so standalone Advise and Workbench-orchestrated local startup do not require an
external identity provider. Production Compose still requires deployment-owned tenant configuration
and must not use the local fixture as tenant-isolation or entitlement proof.
Lotus Risk enrichment retries transient `5xx`, `429`, and network failures with bounded operator
configuration: retry attempts default to `2` and cap at `5`, while retry backoff defaults to `0.1`
seconds and caps at `2.0` seconds.

## API Discovery

Once the service is running:

- OpenAPI UI: `/docs`
- health: `/health`
- liveness: `/health/live`
- readiness: `/health/ready`

## Demo Scenarios

The repository includes grounded demo payloads under `docs/demo/`.

Representative flows:

- proposal simulation via `POST /advisory/proposals/simulate`
- artifact generation via `POST /advisory/proposals/artifact`
- persisted proposal creation via `POST /advisory/proposals`

The demo set also covers:

- auto-funding
- blocked FX cases
- drift analytics
- suitability outcomes
- artifact generation
- lifecycle transitions
- client consent and compliance approval
- execution-ready and executed state progression
