import re
import subprocess
import sys
from pathlib import Path

from scripts.ci_local_compose_project import compose_project_name


def test_local_docker_compose_uses_canonical_upstream_urls() -> None:
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert (
        "LOTUS_CORE_BASE_URL=${LOTUS_CORE_BASE_URL:-http://core-control.dev.lotus}" in compose_text
    )
    assert (
        "LOTUS_CORE_QUERY_BASE_URL=${LOTUS_CORE_QUERY_BASE_URL:-http://core-query.dev.lotus}"
        in compose_text
    )
    assert "LOTUS_RISK_BASE_URL=${LOTUS_RISK_BASE_URL:-http://risk.dev.lotus}" in compose_text
    assert "LOTUS_ADVISE_TENANT_ID=${LOTUS_ADVISE_TENANT_ID:-tenant-sg-001}" in compose_text
    assert '"core-control.dev.lotus:host-gateway"' in compose_text
    assert '"core-query.dev.lotus:host-gateway"' in compose_text
    assert '"risk.dev.lotus:host-gateway"' in compose_text


def test_ci_local_compose_uses_symmetric_checkout_specific_project_identity() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "CI_LOCAL_COMPOSE_PROJECT ?= $(shell python scripts/ci_local_compose_project.py)"
        in makefile
    )
    assert (
        'docker compose --project-name "$(CI_LOCAL_COMPOSE_PROJECT)" '
        "-f docker-compose.ci-local.yml up --build --abort-on-container-exit "
        "--exit-code-from ci-local ci-local"
    ) in makefile
    assert (
        'docker compose --project-name "$(CI_LOCAL_COMPOSE_PROJECT)" '
        "-f docker-compose.ci-local.yml down -v --remove-orphans"
    ) in makefile
    assert "docker compose -f docker-compose.ci-local.yml down" not in makefile


def test_ci_local_compose_project_name_is_stable_and_checkout_specific(tmp_path: Path) -> None:
    first_checkout = tmp_path / "first" / "lotus-advise"
    second_checkout = tmp_path / "second" / "lotus-advise"

    first_name = compose_project_name(first_checkout)

    assert first_name == compose_project_name(first_checkout)
    assert first_name != compose_project_name(second_checkout)
    assert first_name.startswith("lotus-advise-ci-local-lotus-advise-")
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", first_name)


def test_ci_local_compose_project_cli_is_independent_of_caller_directory(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "ci_local_compose_project.py"
    repository_root = script_path.parents[1]
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == compose_project_name(repository_root)


def test_runtime_dockerfile_carries_release_metadata_labels_and_readiness_healthcheck() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    for required in (
        "FROM python:3.11-slim AS dependency-builder",
        "FROM python:3.11-slim",
        "COPY --from=dependency-builder /opt/venv /opt/venv",
        'PATH="/opt/venv/bin:${PATH}"',
        "ARG LOTUS_BUILD_COMMIT_SHA",
        "ARG LOTUS_BUILD_GIT_BRANCH",
        "ARG LOTUS_BUILD_REPO_URL",
        "ARG LOTUS_BUILD_VERSION",
        "ARG LOTUS_BUILD_TIMESTAMP",
        "ARG LOTUS_CI_PIPELINE_ID",
        "ARG LOTUS_IMAGE_DIGEST",
        'org.opencontainers.image.revision="${LOTUS_BUILD_COMMIT_SHA}"',
        'org.opencontainers.image.ref.name="${LOTUS_BUILD_GIT_BRANCH}"',
        'org.opencontainers.image.source="${LOTUS_BUILD_REPO_URL}"',
        'org.opencontainers.image.version="${LOTUS_BUILD_VERSION}"',
        'org.opencontainers.image.created="${LOTUS_BUILD_TIMESTAMP}"',
        'com.lotus.ci.run-id="${LOTUS_CI_PIPELINE_ID}"',
        'com.lotus.image.digest="${LOTUS_IMAGE_DIGEST}"',
        'LOTUS_BUILD_COMMIT_SHA="${LOTUS_BUILD_COMMIT_SHA}"',
        'LOTUS_IMAGE_DIGEST="${LOTUS_IMAGE_DIGEST}"',
        "http://127.0.0.1:8000/health/ready",
    ):
        assert required in dockerfile


def test_runtime_dockerfile_excludes_installer_tooling_from_final_image() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "/opt/venv/bin/python -m pip install --upgrade pip setuptools wheel" in dockerfile
    assert "/opt/venv/bin/pip install --no-cache-dir -r requirements-prod.txt" in dockerfile
    assert "/usr/local/lib/python3.11/site-packages/setuptools" in dockerfile
    assert "/usr/local/lib/python3.11/site-packages/wheel" in dockerfile
    assert "/opt/venv/lib/python3.11/site-packages/setuptools" in dockerfile
    assert "/opt/venv/lib/python3.11/site-packages/wheel" in dockerfile
    assert "/opt/venv/bin/pip" in dockerfile


def test_release_image_provenance_is_repo_native() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "release-image-provenance-gate" in makefile
    assert "scripts/release_image_evidence.py static-check" in makefile
    assert "-t $(IMAGE_TAG)" in makefile
    assert "-t lotus-advise:ci-test" in makefile
    assert "scripts/release_image_evidence.py image-label-check" in makefile


def test_local_docker_compose_does_not_publish_internal_postgres_port() -> None:
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres:\n" in compose_text
    assert '"5432:5432"' not in compose_text


def test_local_docker_compose_wires_required_workspace_postgres_dsn() -> None:
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert (
        "WORKSPACE_POSTGRES_DSN=${WORKSPACE_POSTGRES_DSN:"
        "-${PROPOSAL_POSTGRES_DSN:"
        "-postgresql://advise:advise@postgres:5432/advise_supportability}}" in compose_text
    )


def test_readme_documents_canonical_local_docker_urls() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "http://core-control.dev.lotus" in readme
    assert "http://core-query.dev.lotus" in readme
    assert "http://risk.dev.lotus" in readme


def test_public_docs_reference_current_capability_route() -> None:
    docs = [
        Path("README.md"),
        Path("wiki/API-Surface.md"),
        Path("wiki/Supported-Features.md"),
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "GET /platform/capabilities" in text
        assert "GET /integration/capabilities" not in text


def test_local_compose_uses_version_endpoint_for_container_readiness() -> None:
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8000/version" in compose_text


def test_production_compose_is_environment_neutral_and_secret_safe() -> None:
    compose_text = Path("docker-compose.production.yml").read_text(encoding="utf-8")

    forbidden_fragments = (
        ".dev.lotus",
        "host-gateway",
        "postgresql://",
        "POSTGRES_PASSWORD",
        "build:",
        "image: lotus-advise:latest",
        "http://127.0.0.1:8000/version",
    )
    for fragment in forbidden_fragments:
        assert fragment not in compose_text

    required_fragments = (
        "image: ${LOTUS_ADVISE_IMAGE_DIGEST_REF:",
        "LOTUS_CORE_BASE_URL=${LOTUS_CORE_BASE_URL:?",
        "LOTUS_CORE_QUERY_BASE_URL=${LOTUS_CORE_QUERY_BASE_URL:?",
        "LOTUS_RISK_BASE_URL=${LOTUS_RISK_BASE_URL:?",
        "LOTUS_REPORT_BASE_URL=${LOTUS_REPORT_BASE_URL:?",
        "LOTUS_AI_BASE_URL=${LOTUS_AI_BASE_URL:?",
        "LOTUS_ADVISE_TENANT_ID=${LOTUS_ADVISE_TENANT_ID:?",
        "PROPOSAL_POSTGRES_DSN=${PROPOSAL_POSTGRES_DSN:?",
        "POLICY_POSTGRES_DSN=${POLICY_POSTGRES_DSN:?",
        "WORKSPACE_POSTGRES_DSN=${WORKSPACE_POSTGRES_DSN:?",
        "http://127.0.0.1:8000/health/ready",
    )
    for fragment in required_fragments:
        assert fragment in compose_text


def test_only_local_compose_supplies_canonical_dev_tenant_fixture() -> None:
    local_compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    production_compose = Path("docker-compose.production.yml").read_text(encoding="utf-8")

    assert "LOTUS_ADVISE_TENANT_ID=${LOTUS_ADVISE_TENANT_ID:-tenant-sg-001}" in local_compose
    assert "LOTUS_ADVISE_TENANT_ID=${LOTUS_ADVISE_TENANT_ID:-" not in production_compose
    assert "LOTUS_ADVISE_TENANT_ID=${LOTUS_ADVISE_TENANT_ID:?" in production_compose
