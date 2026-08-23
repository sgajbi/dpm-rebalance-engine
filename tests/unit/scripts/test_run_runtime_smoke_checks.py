from __future__ import annotations

import io
import subprocess

import pytest

from scripts import run_runtime_smoke_checks


def test_runtime_smoke_compose_uses_checkout_specific_project_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("CI_LOCAL_COMPOSE_PROJECT", "advise-ci-test")
    monkeypatch.setattr(
        run_runtime_smoke_checks.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )

    run_runtime_smoke_checks._run_docker_compose(["down", "-v", "--remove-orphans"])

    assert calls == [
        [
            "docker",
            "compose",
            "--project-name",
            "advise-ci-test",
            "-f",
            "docker-compose.ci-local.yml",
            "down",
            "-v",
            "--remove-orphans",
        ]
    ]


def test_runtime_smoke_compose_derives_project_when_override_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.delenv("CI_LOCAL_COMPOSE_PROJECT", raising=False)
    monkeypatch.setattr(
        run_runtime_smoke_checks,
        "compose_project_name",
        lambda checkout: "derived-ci-test",
    )
    monkeypatch.setattr(
        run_runtime_smoke_checks.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )

    run_runtime_smoke_checks._run_docker_compose(["up", "-d", "postgres"])

    assert calls[0][3] == "derived-ci-test"


def test_postgres_env_honors_injected_ci_dsns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PROPOSAL_POSTGRES_DSN", "postgresql://lotus:lotus@127.0.0.1:5432/lotus_advise"
    )
    monkeypatch.setenv(
        "PROPOSAL_POSTGRES_INTEGRATION_DSN",
        "postgresql://lotus:lotus@127.0.0.1:5432/lotus_advise_integration",
    )
    monkeypatch.setenv(
        "POLICY_POSTGRES_DSN", "postgresql://lotus:lotus@127.0.0.1:5432/lotus_policy"
    )
    monkeypatch.setenv(
        "WORKSPACE_POSTGRES_DSN", "postgresql://lotus:lotus@127.0.0.1:5432/lotus_workspace"
    )

    env = run_runtime_smoke_checks._postgres_env()

    assert env["PROPOSAL_POSTGRES_DSN"] == "postgresql://lotus:lotus@127.0.0.1:5432/lotus_advise"
    assert (
        env["PROPOSAL_POSTGRES_INTEGRATION_DSN"]
        == "postgresql://lotus:lotus@127.0.0.1:5432/lotus_advise_integration"
    )
    assert env["POLICY_POSTGRES_DSN"] == "postgresql://lotus:lotus@127.0.0.1:5432/lotus_policy"
    assert (
        env["WORKSPACE_POSTGRES_DSN"] == "postgresql://lotus:lotus@127.0.0.1:5432/lotus_workspace"
    )


def test_postgres_env_uses_integration_fallback_when_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROPOSAL_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("PROPOSAL_POSTGRES_INTEGRATION_DSN", raising=False)
    monkeypatch.delenv("POLICY_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("WORKSPACE_POSTGRES_DSN", raising=False)

    env = run_runtime_smoke_checks._postgres_env()

    assert (
        env["PROPOSAL_POSTGRES_DSN"]
        == "postgresql://advise:advise@127.0.0.1:5432/advise_supportability"
    )
    assert env["PROPOSAL_POSTGRES_INTEGRATION_DSN"] == env["PROPOSAL_POSTGRES_DSN"]
    assert env["POLICY_POSTGRES_DSN"] == env["PROPOSAL_POSTGRES_DSN"]
    assert env["WORKSPACE_POSTGRES_DSN"] == env["PROPOSAL_POSTGRES_DSN"]


def test_postgres_runtime_contracts_always_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.delenv("PROPOSAL_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("PROPOSAL_POSTGRES_INTEGRATION_DSN", raising=False)

    def fake_run_docker_compose(arguments: list[str]) -> None:
        events.append(" ".join(arguments))

    def fake_postgres_migration_smoke() -> None:
        events.append("postgres-migration-smoke")
        raise RuntimeError("smoke failed")

    monkeypatch.setattr(run_runtime_smoke_checks, "_run_docker_compose", fake_run_docker_compose)
    monkeypatch.setattr(
        run_runtime_smoke_checks,
        "_wait_for_postgres_ready",
        lambda dsn: events.append(dsn),
    )
    monkeypatch.setattr(
        run_runtime_smoke_checks, "run_postgres_migration_smoke", fake_postgres_migration_smoke
    )
    monkeypatch.setattr(
        run_runtime_smoke_checks,
        "run_production_profile_smoke",
        lambda: events.append("production-profile-smoke"),
    )

    with pytest.raises(RuntimeError, match="smoke failed"):
        run_runtime_smoke_checks.run_postgres_runtime_contracts()

    assert events == [
        "up -d --remove-orphans postgres",
        "postgresql://advise:advise@127.0.0.1:5432/advise_supportability",
        "postgres-migration-smoke",
        "down -v --remove-orphans",
    ]


class _GuardrailProcess:
    def __init__(self, output: str, *, exits: bool = True) -> None:
        self.stdout = io.StringIO(output)
        self._exits = exits
        self.stopped = False

    def wait(self, timeout: float | None = None) -> int:
        if not self._exits and not self.stopped:
            raise subprocess.TimeoutExpired(cmd="uvicorn", timeout=timeout)
        return 1

    def terminate(self) -> None:
        self.stopped = True

    def kill(self) -> None:
        self.stopped = True


def test_guardrail_failure_waits_for_startup_exit_before_reading_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _GuardrailProcess("RuntimeError: PROPOSAL_STORE_BACKEND_UNSUPPORTED")
    monkeypatch.setattr(
        run_runtime_smoke_checks,
        "_start_uvicorn",
        lambda *, env, port: process,
    )

    run_runtime_smoke_checks._assert_guardrail_failure(
        env={},
        port=8004,
        expected_messages=("PROPOSAL_STORE_BACKEND_UNSUPPORTED",),
        timeout_seconds=0.1,
    )

    assert process.stopped is False


def test_guardrail_failure_rejects_process_that_stays_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _GuardrailProcess("", exits=False)
    monkeypatch.setattr(
        run_runtime_smoke_checks,
        "_start_uvicorn",
        lambda *, env, port: process,
    )

    with pytest.raises(RuntimeError, match="API stayed alive"):
        run_runtime_smoke_checks._assert_guardrail_failure(
            env={},
            port=8004,
            expected_messages=("PROPOSAL_STORE_BACKEND_UNSUPPORTED",),
            timeout_seconds=0.1,
        )

    assert process.stopped is True


def test_production_profile_guardrail_negatives_include_malformed_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[str, ...], str | None, str | None]] = []
    monkeypatch.delenv("LOTUS_CORE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("PROPOSAL_STORE_BACKEND", raising=False)
    monkeypatch.delenv("WORKSPACE_STORE_BACKEND", raising=False)

    def fake_assert_guardrail_failure(
        *,
        env: dict[str, str],
        port: int,
        expected_messages: tuple[str, ...],
    ) -> None:
        calls.append(
            (
                port,
                expected_messages,
                env.get("LOTUS_CORE_TIMEOUT_SECONDS"),
                env.get("PROPOSAL_STORE_BACKEND"),
            )
        )

    monkeypatch.setattr(
        run_runtime_smoke_checks,
        "_assert_guardrail_failure",
        fake_assert_guardrail_failure,
    )

    run_runtime_smoke_checks.run_production_profile_guardrail_negatives()

    assert calls == [
        (8003, ("LOTUS_CORE_TIMEOUT_SECONDS",), "invalid", None),
        (
            8004,
            (
                "PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES",
                "PROPOSAL_STORE_BACKEND_UNSUPPORTED",
            ),
            None,
            "IN_MEMORY",
        ),
        (
            8007,
            ("PERSISTENCE_PROFILE_REQUIRES_ADVISORY_POSTGRES_DSN",),
            None,
            "POSTGRES",
        ),
        (
            8008,
            ("PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES",),
            None,
            "POSTGRES",
        ),
        (
            8009,
            ("PERSISTENCE_PROFILE_REQUIRES_WORKSPACE_POSTGRES_DSN",),
            None,
            "POSTGRES",
        ),
    ]
