.PHONY: install install-ci check check-all test test-unit test-integration test-e2e test-all test-fast test-all-fast test-all-no-cov test-all-parallel ci ci-local ci-local-docker ci-local-docker-down typecheck lint monetary-float-guard architecture-boundaries complexity-regression-gate dead-code-gate duplicate-code-gate unused-dependency-gate oversized-code-gate quality-trend-gate proposal-decision-vocabulary-gate docs-source-reference-gate observability-diagnostics advisory-domain-golden-regressions advisory-copilot-evaluation-gate advisory-copilot-safety-gate advisory-data-lifecycle-gate durable-state-recovery-gate external-adapter-contracts demo-assurance-gate demo-certification-live slo-capacity-gate migration-rollout-contract-gate trust-telemetry-freshness-gate trust-telemetry-certify dependency-lock dependency-lock-gate license-ip-inventory license-ip-gate release-image-provenance-gate docker-labels-check format clean run verify-dependencies check-deps check-deps-strict security-audit bandit-severity-regression-gate bandit-high-severity-gate openapi-gate openapi-spectral-report no-alias-gate api-vocabulary-gate domain-data-products-gate engineering-health engineering-health-json quality-baseline quality-baseline-check migration-smoke migration-apply coverage-combined changed-coverage-gate postgres-runtime-contracts-local production-profile-guardrail-negatives-local pre-commit docker-build docker-up docker-down

SERVICE_VERSION ?= 0.1.0
IMAGE_REPOSITORY ?= lotus-advise
GIT_SHA ?= $(shell git rev-parse --verify HEAD 2>/dev/null || echo local)
GIT_BRANCH ?= $(shell git rev-parse --abbrev-ref HEAD 2>/dev/null || echo local)
REPO_URL ?= https://github.com/sgajbi/lotus-advise
BUILD_TIMESTAMP ?= $(shell python -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'))")
CI_PIPELINE_ID ?= local
IMAGE_DIGEST ?= unknown
IMAGE_TAG ?= $(IMAGE_REPOSITORY):$(GIT_SHA)
QUALITY_BASE_REF ?= origin/main
QUALITY_HEAD_REF ?= HEAD

install: install-ci
	python -m pre_commit install

install-ci:
	python -m pip install -r requirements.txt
	python -m pip install -r requirements-dev.txt
	python -m pip install pre-commit

pre-commit:
	python -m pre_commit run --all-files

check: lint typecheck openapi-gate no-alias-gate api-vocabulary-gate proposal-decision-vocabulary-gate domain-data-products-gate trust-telemetry-freshness-gate advisory-data-lifecycle-gate durable-state-recovery-gate external-adapter-contracts advisory-copilot-evaluation-gate advisory-copilot-safety-gate docs-source-reference-gate slo-capacity-gate migration-rollout-contract-gate quality-baseline-check quality-trend-gate dead-code-gate duplicate-code-gate unused-dependency-gate oversized-code-gate bandit-severity-regression-gate dependency-lock-gate license-ip-gate release-image-provenance-gate test

ci: verify-dependencies lint typecheck openapi-gate no-alias-gate api-vocabulary-gate proposal-decision-vocabulary-gate domain-data-products-gate trust-telemetry-freshness-gate advisory-data-lifecycle-gate durable-state-recovery-gate advisory-copilot-evaluation-gate advisory-copilot-safety-gate docs-source-reference-gate slo-capacity-gate migration-rollout-contract-gate quality-baseline-check quality-trend-gate dead-code-gate duplicate-code-gate unused-dependency-gate oversized-code-gate migration-smoke security-audit dependency-lock-gate license-ip-gate release-image-provenance-gate coverage-combined changed-coverage-gate docker-build postgres-runtime-contracts-local production-profile-guardrail-negatives-local

test:
	$(MAKE) test-unit

test-unit:
	python -m pytest tests/unit

test-integration:
	python -m pytest tests/integration

test-e2e:
	python -m pytest tests/e2e

test-all:
	python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=97

# Fast local loop: unit tests only (no coverage)
test-fast:
	python -m pytest tests/unit -q

# Full suite with coverage gate, but without term-missing output overhead
test-all-fast:
	python -m pytest --cov=src --cov-report= --cov-fail-under=97

# Full suite without coverage for quickest full functional signal
test-all-no-cov:
	python -m pytest

# Full suite, optional parallel workers when pytest-xdist is installed
test-all-parallel:
	python -c "import importlib.util, subprocess, sys; args=[sys.executable,'-m','pytest','--cov=src','--cov-report=','--cov-fail-under=97']; args += (['-n','auto','--dist','loadscope'] if importlib.util.find_spec('xdist') else []); raise SystemExit(subprocess.call(args))"

# Local execution flow aligned with the Pull Request Merge Gate
ci-local: verify-dependencies lint typecheck openapi-gate no-alias-gate api-vocabulary-gate proposal-decision-vocabulary-gate domain-data-products-gate trust-telemetry-freshness-gate advisory-data-lifecycle-gate durable-state-recovery-gate docs-source-reference-gate slo-capacity-gate migration-rollout-contract-gate quality-baseline-check quality-trend-gate dead-code-gate duplicate-code-gate unused-dependency-gate oversized-code-gate migration-smoke security-audit dependency-lock-gate license-ip-gate release-image-provenance-gate coverage-combined changed-coverage-gate

CI_LOCAL_COMPOSE_PROJECT ?= $(shell python scripts/ci_local_compose_project.py)

ci-local-docker:
	docker compose --project-name "$(CI_LOCAL_COMPOSE_PROJECT)" -f docker-compose.ci-local.yml up --build --abort-on-container-exit --exit-code-from ci-local ci-local

ci-local-docker-down:
	docker compose --project-name "$(CI_LOCAL_COMPOSE_PROJECT)" -f docker-compose.ci-local.yml down -v --remove-orphans

check-all: lint typecheck proposal-decision-vocabulary-gate quality-trend-gate dead-code-gate duplicate-code-gate unused-dependency-gate oversized-code-gate test-all

typecheck:
	python -m mypy --config-file mypy.ini

openapi-gate:
	python scripts/openapi_quality_gate.py
	python -m pytest tests/unit/advisory/contracts/test_contract_openapi_lifecycle_docs.py -q
	$(MAKE) openapi-spectral-report

openapi-spectral-report:
	python scripts/openapi_spectral_report.py --output output/openapi-spectral-report.json

no-alias-gate:
	python scripts/no_alias_contract_guard.py

api-vocabulary-gate:
	python scripts/api_vocabulary_inventory.py
	python scripts/api_vocabulary_inventory.py --validate-only

proposal-decision-vocabulary-gate:
	python scripts/proposal_decision_vocabulary.py --validate-only

domain-data-products-gate:
	python scripts/validate_domain_data_product_declarations.py

trust-telemetry-freshness-gate:
	python scripts/trust_telemetry_freshness.py check

trust-telemetry-certify:
	python scripts/trust_telemetry_freshness.py certify

advisory-data-lifecycle-gate:
	python scripts/advisory_data_lifecycle_inventory.py

durable-state-recovery-gate:
	python scripts/durable_state_recovery_contract.py --emit-drill-evidence output/durable-state-recovery/recovery-drill-evidence.json

docs-source-reference-gate:
	python scripts/documentation_source_reference_check.py

slo-capacity-gate:
	python scripts/slo_capacity_contract.py --emit-smoke-plan output/slo-capacity-smoke-plan.json

migration-rollout-contract-gate:
	python scripts/postgres_migration_rollout_contract.py --emit-rehearsal-evidence output/postgres-migration-rollout-rehearsal.json

engineering-health:
	python scripts/engineering_health_report.py --output docs/architecture/ENGINEERING-HEALTH-BASELINE.md

engineering-health-json:
	python scripts/engineering_health_report.py --format json --output output/engineering-health-current.json

quality-baseline:
	python scripts/quality_baseline_report.py --output-dir quality

quality-baseline-check:
	python scripts/quality_baseline_report.py --output-dir quality --check

quality-trend-gate:
	python -m scripts.quality_trend_gate --base-ref "$(QUALITY_BASE_REF)" --head-ref "$(QUALITY_HEAD_REF)" --policy quality/quality-trend-policy.v1.json --output output/quality-trend-gate.json

migration-smoke:
	python -m pytest tests/unit/shared/dependencies/test_runtime_persistence.py tests/unit/shared/dependencies/test_production_cutover_contract.py tests/unit/shared/dependencies/test_postgres_migrate_targets.py tests/unit/shared/dependencies/test_workspace_runtime_repositories.py -q

migration-apply:
	python scripts/postgres_migrate.py --target all

lint:
	python -m ruff check .
	python -m ruff format --check .
	$(MAKE) monetary-float-guard
	$(MAKE) architecture-boundaries
	$(MAKE) complexity-regression-gate
	$(MAKE) refactored-complexity-gate

monetary-float-guard:
	python scripts/check_monetary_float_usage.py

architecture-boundaries:
	python -c "from importlinter.cli import lint_imports_command; lint_imports_command(args=['--config','.importlinter'], standalone_mode=True)"

complexity-regression-gate:
	python scripts/radon_complexity_gate.py --fail-rank C

refactored-complexity-gate:
	python scripts/radon_complexity_gate.py --source-path src/integrations/lotus_risk/enrichment.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/tactical_house_view.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/policy_packs/workflow_projection.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/narrative_ai.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/execution_status.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/integrations/lotus_core/stateful_context_translation.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/async_operations.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/async_operation_runner.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/async_payloads.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/command_validation.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/integrations/lotus_core/stateful_context_market_data.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/bank_demo_proof/artifact_refs.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/async_replay.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/common/canonical.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/idempotency.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/common/intent_dependencies.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory_copilot/record_text.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory_copilot/run_replay_policy.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/integrations/lotus_ai/runtime_config.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/artifact_evidence.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/artifact_portfolio.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/artifact_trades.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/alternatives_projection.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/decision_requirements.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/decision_material_changes.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/narrative_policy.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/advisory/decision_summary.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/memo_builder.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/memo_persistence.py --fail-rank B
	python scripts/radon_complexity_gate.py --source-path src/core/proposals/memo_response_projection.py --fail-rank B

dead-code-gate:
	python -m scripts.dead_code_gate --policy quality/dead-code-policy.v1.json --output output/dead-code-gate.json

duplicate-code-gate:
	python -m scripts.duplicate_code_gate --policy quality/duplicate-code-policy.v1.json --output output/duplicate-code-gate.json

unused-dependency-gate:
	python -m scripts.dependency_hygiene_gate --policy quality/dependency-hygiene-policy.v1.json --output output/dependency-hygiene-gate.json

oversized-code-gate:
	python -m scripts.oversized_code_gate --policy quality/oversized-code-policy.v1.json --output output/oversized-code-gate.json

observability-diagnostics:
	python -m pytest tests/unit/advisory/api/test_api_observability.py -q

advisory-domain-golden-regressions:
	python -m pytest tests/unit/advisory/golden -q

advisory-copilot-evaluation-gate:
	python scripts/advisory_copilot_evaluation_gate.py

advisory-copilot-safety-gate:
	python scripts/advisory_copilot_safety_gate.py

external-adapter-contracts:
	python -m pytest tests/unit/advisory/contracts/test_external_adapter_contract_fixtures.py -q

demo-assurance-gate: openapi-gate no-alias-gate api-vocabulary-gate domain-data-products-gate observability-diagnostics advisory-domain-golden-regressions
	@echo "Demo assurance gate passed"

demo-certification-live:
	python scripts/run_demo_pack_live.py --base-url $${LOTUS_ADVISE_DEMO_BASE_URL:-http://127.0.0.1:8000} --output $${LOTUS_ADVISE_DEMO_EVIDENCE:-output/demo-certification/latest/lotus-advise-demo-certification.json}

format:
	python -m ruff format .

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['__pycache__', '.pytest_cache', 'htmlcov', '.ruff_cache', '.mypy_cache']]; pathlib.Path('.coverage').unlink(missing_ok=True)"

run:
	python -m uvicorn src.api.main:app --reload --port 8000

verify-dependencies:
	python scripts/dependency_health_check.py --requirements requirements.txt --dev-requirements requirements-dev.txt --outdated-scope direct --target-python-version $${PYTHON_VERSION:-3.11} --skip-audit

check-deps:
	python scripts/dependency_health_check.py --requirements requirements.txt --dev-requirements requirements-dev.txt --outdated-scope direct --target-python-version $${PYTHON_VERSION:-3.11}

check-deps-strict:
	python scripts/dependency_health_check.py --requirements requirements.txt --dev-requirements requirements-dev.txt --outdated-scope direct --target-python-version $${PYTHON_VERSION:-3.11} --fail-on-outdated

security-audit:
	python scripts/dependency_health_check.py --requirements requirements.txt --dev-requirements requirements-dev.txt --outdated-scope direct --target-python-version $${PYTHON_VERSION:-3.11}
	$(MAKE) bandit-severity-regression-gate

bandit-severity-regression-gate:
	python scripts/bandit_high_severity_gate.py

bandit-high-severity-gate: bandit-severity-regression-gate

dependency-lock: license-ip-inventory
	python scripts/dependency_lock_evidence.py write-lock

dependency-lock-gate:
	python scripts/dependency_lock_evidence.py check-lock

license-ip-inventory:
	python scripts/license_ip_evidence.py write-inventory --isolated --commit-sha $(GIT_SHA) --image-digest $(IMAGE_DIGEST) --repository-url $(REPO_URL)

license-ip-gate:
	python scripts/license_ip_evidence.py check-inventory --isolated --commit-sha $(GIT_SHA) --image-digest $(IMAGE_DIGEST) --repository-url $(REPO_URL)

coverage-combined:
	COVERAGE_FILE=.coverage.unit python -m pytest tests/unit --cov=src --cov-report=
	COVERAGE_FILE=.coverage.integration python -m pytest tests/integration --cov=src --cov-report=
	COVERAGE_FILE=.coverage.e2e python -m pytest tests/e2e --cov=src --cov-report=
	python -m coverage combine .coverage.unit .coverage.integration .coverage.e2e
	python -m coverage report --fail-under=97

changed-coverage-gate:
	python scripts/changed_coverage_gate.py --base-ref "$(QUALITY_BASE_REF)" --head-ref "$(QUALITY_HEAD_REF)" --coverage-data .coverage --policy quality/quality-policy.v1.json --output output/changed-coverage-gate.json

postgres-runtime-contracts-local:
	python scripts/run_runtime_smoke_checks.py postgres-runtime-contracts

production-profile-guardrail-negatives-local:
	python scripts/run_runtime_smoke_checks.py production-profile-guardrail-negatives

docker-build:
	docker build \
		--build-arg LOTUS_BUILD_COMMIT_SHA=$(GIT_SHA) \
		--build-arg LOTUS_BUILD_GIT_BRANCH=$(GIT_BRANCH) \
		--build-arg LOTUS_BUILD_REPO_URL=$(REPO_URL) \
		--build-arg LOTUS_BUILD_VERSION=$(SERVICE_VERSION) \
		--build-arg LOTUS_BUILD_TIMESTAMP=$(BUILD_TIMESTAMP) \
		--build-arg LOTUS_CI_PIPELINE_ID=$(CI_PIPELINE_ID) \
		--build-arg LOTUS_IMAGE_DIGEST=$(IMAGE_DIGEST) \
		-t $(IMAGE_TAG) \
		-t lotus-advise:ci-test .
	$(MAKE) docker-labels-check

docker-labels-check:
	python scripts/release_image_evidence.py image-label-check --image-ref $(IMAGE_TAG) --expected-commit $(GIT_SHA) --expected-repo-url $(REPO_URL) --expected-ci-run-id $(CI_PIPELINE_ID)

release-image-provenance-gate:
	python scripts/release_image_evidence.py static-check

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down
