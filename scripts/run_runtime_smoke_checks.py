from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

from scripts.ci_local_compose_project import compose_project_name

_LOCAL_PROPOSAL_POSTGRES_DSN = "postgresql://advise:advise@127.0.0.1:5432/advise_supportability"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(command: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=_repo_root(), env=env, check=True)


def _run_docker_compose(arguments: list[str]) -> None:
    project_name = os.environ.get("CI_LOCAL_COMPOSE_PROJECT") or compose_project_name(_repo_root())
    subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "-f",
            "docker-compose.ci-local.yml",
            *arguments,
        ],
        cwd=_repo_root(),
        check=True,
    )


def _wait_for_postgres_ready(*, dsn: str, timeout_seconds: float = 25.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return
        except Exception as exc:  # pragma: no cover - exercised by runtime smoke
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for Postgres readiness: {last_error}")


def _start_uvicorn(*, env: dict[str, str], port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=_repo_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_process(process: subprocess.Popen[str]) -> str:
    output = ""
    if process.stdout is not None:
        try:
            process.terminate()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        output = process.stdout.read()
    return output


def _wait_for_http_ready(*, port: int, paths: list[str], timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        all_ready = True
        for path in paths:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=2
                ) as response:
                    if response.status >= 400:
                        all_ready = False
                        break
            except (urllib.error.URLError, TimeoutError):
                all_ready = False
                break
        if all_ready:
            return
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for HTTP endpoints on port {port}")


def _assert_guardrail_failure(
    *,
    env: dict[str, str],
    port: int,
    expected_messages: tuple[str, ...],
    timeout_seconds: float = 15.0,
) -> None:
    process = _start_uvicorn(env=env, port=port)
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        output = _stop_process(process)
        raise RuntimeError(
            "Expected production-profile guardrail startup failure, but API stayed alive.\n"
            f"Captured output:\n{output}"
        )
    output = ""
    if process.stdout is not None:
        output = process.stdout.read()
    if not any(message in output for message in expected_messages):
        raise RuntimeError(
            "Expected one of guardrail messages "
            f"{expected_messages!r} but none were found.\nCaptured output:\n{output}"
        )


def _postgres_env() -> dict[str, str]:
    env = os.environ.copy()
    proposal_postgres_dsn = (
        env.get("PROPOSAL_POSTGRES_DSN", "").strip() or _LOCAL_PROPOSAL_POSTGRES_DSN
    )
    proposal_postgres_integration_dsn = (
        env.get("PROPOSAL_POSTGRES_INTEGRATION_DSN", "").strip() or proposal_postgres_dsn
    )
    env["PROPOSAL_POSTGRES_DSN"] = proposal_postgres_dsn
    env["PROPOSAL_POSTGRES_INTEGRATION_DSN"] = proposal_postgres_integration_dsn
    env["POLICY_POSTGRES_DSN"] = env.get("POLICY_POSTGRES_DSN", "").strip() or proposal_postgres_dsn
    env["WORKSPACE_POSTGRES_DSN"] = (
        env.get("WORKSPACE_POSTGRES_DSN", "").strip() or proposal_postgres_dsn
    )
    return env


def run_postgres_migration_smoke() -> None:
    env = _postgres_env()
    _run([sys.executable, "scripts/postgres_migrate.py", "--target", "all"], env=env)
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/integration/advisory/engine/test_engine_proposal_repository_postgres_integration.py",
        ],
        env=env,
    )


def run_production_profile_smoke() -> None:
    env = _postgres_env()
    env["PROPOSAL_STORE_BACKEND"] = "POSTGRES"
    env["POLICY_STORE_BACKEND"] = "POSTGRES"
    env["WORKSPACE_STORE_BACKEND"] = "POSTGRES"
    _run([sys.executable, "scripts/postgres_migrate.py", "--target", "all"], env=env)
    process = _start_uvicorn(env=env, port=8002)
    try:
        _wait_for_http_ready(port=8002, paths=["/docs", "/health", "/advisory/proposals?limit=1"])
    finally:
        _stop_process(process)


def run_production_profile_guardrail_negatives() -> None:
    malformed_runtime_env = os.environ.copy()
    malformed_runtime_env["LOTUS_CORE_TIMEOUT_SECONDS"] = "invalid"
    _assert_guardrail_failure(
        env=malformed_runtime_env,
        port=8003,
        expected_messages=("LOTUS_CORE_TIMEOUT_SECONDS",),
    )

    unsupported_env = os.environ.copy()
    unsupported_env["PROPOSAL_STORE_BACKEND"] = "IN_MEMORY"
    _assert_guardrail_failure(
        env=unsupported_env,
        port=8004,
        expected_messages=(
            "PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES",
            "PROPOSAL_STORE_BACKEND_UNSUPPORTED",
        ),
    )

    missing_dsn_env = os.environ.copy()
    missing_dsn_env["PROPOSAL_STORE_BACKEND"] = "POSTGRES"
    _assert_guardrail_failure(
        env=missing_dsn_env,
        port=8007,
        expected_messages=("PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES_DSN",),
    )

    unsupported_workspace_env = os.environ.copy()
    unsupported_workspace_env["PROPOSAL_STORE_BACKEND"] = "POSTGRES"
    unsupported_workspace_env["PROPOSAL_POSTGRES_DSN"] = _LOCAL_PROPOSAL_POSTGRES_DSN
    unsupported_workspace_env["POLICY_STORE_BACKEND"] = "POSTGRES"
    unsupported_workspace_env["WORKSPACE_STORE_BACKEND"] = "IN_MEMORY"
    _assert_guardrail_failure(
        env=unsupported_workspace_env,
        port=8008,
        expected_messages=("PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES",),
    )

    missing_workspace_dsn_env = os.environ.copy()
    missing_workspace_dsn_env["PROPOSAL_STORE_BACKEND"] = "POSTGRES"
    missing_workspace_dsn_env["PROPOSAL_POSTGRES_DSN"] = _LOCAL_PROPOSAL_POSTGRES_DSN
    missing_workspace_dsn_env["POLICY_STORE_BACKEND"] = "POSTGRES"
    missing_workspace_dsn_env["WORKSPACE_STORE_BACKEND"] = "POSTGRES"
    missing_workspace_dsn_env.pop("WORKSPACE_POSTGRES_DSN", None)
    _assert_guardrail_failure(
        env=missing_workspace_dsn_env,
        port=8009,
        expected_messages=("PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES_DSN",),
    )


def run_postgres_runtime_contracts() -> None:
    _run_docker_compose(["up", "-d", "--remove-orphans", "postgres"])
    try:
        _wait_for_postgres_ready(dsn=_postgres_env()["PROPOSAL_POSTGRES_DSN"])
        run_postgres_migration_smoke()
        run_production_profile_smoke()
    finally:
        _run_docker_compose(["down", "-v", "--remove-orphans"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run lotus-advise runtime smoke checks")
    parser.add_argument(
        "mode",
        choices=(
            "postgres-migration-smoke",
            "production-profile-smoke",
            "production-profile-guardrail-negatives",
            "postgres-runtime-contracts",
        ),
    )
    args = parser.parse_args()

    if args.mode == "postgres-migration-smoke":
        run_postgres_migration_smoke()
    elif args.mode == "production-profile-smoke":
        run_production_profile_smoke()
    elif args.mode == "postgres-runtime-contracts":
        run_postgres_runtime_contracts()
    else:
        run_production_profile_guardrail_negatives()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
