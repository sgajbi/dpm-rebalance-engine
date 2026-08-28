from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from scripts.license_ip_evidence import (
    ISOLATED_ENV_FLAG,
    PIP_BOOTSTRAP_PACKAGES,
    LicensePolicy,
    _governed_python_command,
    _run_in_isolated_environment,
    _validate_installed_packages_against_lock,
    _write_lock_constraints,
    build_license_inventory,
    validate_license_inventory,
    validate_license_inventory_against_expected,
)

CONSTRAINT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures/dependency_constraint_cases.json"
)
CONSTRAINT_CASES = json.loads(CONSTRAINT_FIXTURE.read_text(encoding="utf-8"))


class FakeDistribution:
    def __init__(
        self,
        *,
        name: str,
        version: str = "1.0.0",
        license_expression: str | None = "MIT",
        requires: list[str] | None = None,
    ) -> None:
        self.metadata = Message()
        self.metadata["Name"] = name
        if license_expression is not None:
            self.metadata["License-Expression"] = license_expression
        self.version = version
        self.requires = requires or []


def test_isolated_inventory_regeneration_permits_a_fresh_dependency_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setenv("PIP_CONFIG_FILE", "ambient-pip.conf")
    monkeypatch.setenv("PYTHONHOME", "ambient-python-home")
    monkeypatch.setenv("PYTHONPATH", "ambient-python-path")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        stdout = (
            json.dumps({"installed": [{"metadata": {"name": "fresh-child", "version": "1.0"}}]})
            if "inspect" in command
            else None
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(
        "scripts.license_ip_evidence.sys.version_info",
        (3, 11, 9, "final", 0),
    )
    monkeypatch.setattr("scripts.license_ip_evidence.subprocess.run", fake_run)

    result = _run_in_isolated_environment(
        _isolated_args("write-inventory"),
        venv_root=tmp_path / "venv",
    )

    assert result == 0
    assert calls[0][0][1:4] == ["-I", "-m", "venv"]
    assert calls[1][0][1:7] == [
        "-I",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "install",
    ]
    assert "--upgrade" in calls[1][0]
    assert calls[1][0][-2:] == list(PIP_BOOTSTRAP_PACKAGES)
    assert calls[2][0][1:7] == [
        "-I",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "install",
    ]
    assert calls[2][0][-2] == "-r"
    assert Path(calls[2][0][-1]).name == "requirements-prod.txt"
    assert "--constraint" in calls[2][0]
    assert Path(calls[2][0][calls[2][0].index("--constraint") + 1]).name == (
        "license-ip-constraints.txt"
    )
    assert calls[3][0][1:7] == [
        "-I",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "install",
    ]
    assert Path(calls[3][0][-1]).name == "requirements-dev.txt"
    assert (tmp_path / "license-ip-constraints.txt").read_text(encoding="utf-8") == (
        "# Fresh inventory resolution.\n"
    )
    assert calls[4][0][1:4] == ["-X", "utf8", "-I"]
    assert (calls[4][0][-2:], calls[4][1]["capture_output"]) == (["inspect", "--local"], True)
    assert calls[5][0][1] == "-I"
    assert calls[5][0][2].endswith("scripts/license_ip_evidence.py") or calls[5][0][2].endswith(
        "scripts\\license_ip_evidence.py"
    )
    assert "--no-isolation" in calls[5][0]
    assert calls[5][1]["env"][ISOLATED_ENV_FLAG] == "1"
    for pip_call in calls[1:4]:
        assert pip_call[1]["env"]["PIP_CONFIG_FILE"] == os.devnull
    for _, kwargs in calls:
        assert {"PYTHONHOME", "PYTHONPATH"}.isdisjoint(kwargs["env"])


def test_lock_constraints_project_exact_versions(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    constraints = tmp_path / "constraints.txt"
    lock.write_text(
        '[[package]]\nname = "zeta-pkg"\nversion = "2.0.0"\ndirect = false\n\n'
        '[[package]]\nname = "alpha_pkg"\nversion = "1.0.0"\ndirect = false\n',
        encoding="utf-8",
    )

    _write_lock_constraints(lock, constraints)

    assert constraints.read_text(encoding="utf-8") == (
        "# Generated at runtime from uv.lock; do not edit.\nalpha-pkg==1.0.0\nzeta-pkg==2.0.0\n"
    )


@pytest.mark.parametrize("case", CONSTRAINT_CASES["refresh_cases"], ids=lambda case: case["id"])
def test_lock_constraint_refresh_is_bounded_by_authoritative_roots(
    tmp_path: Path, case: dict[str, Any]
) -> None:
    lock = tmp_path / "uv.lock"
    constraints = tmp_path / "constraints.txt"
    lock.write_text(case["lock"], encoding="utf-8")
    requirement_paths = []
    for index, content in enumerate(case["requirements"]):
        path = tmp_path / f"requirements-{index}.txt"
        path.write_text(content, encoding="utf-8")
        requirement_paths.append(path)
    if error := case.get("error"):
        with pytest.raises(RuntimeError, match=error):
            _write_lock_constraints(lock, constraints, requirement_paths=requirement_paths)
        assert not constraints.exists()
    else:
        _write_lock_constraints(lock, constraints, requirement_paths=requirement_paths)
        assert constraints.read_text(encoding="utf-8") == case["expected"]


@pytest.mark.parametrize("case", CONSTRAINT_CASES["installed_cases"], ids=lambda case: case["id"])
def test_installed_dependency_graph_must_be_fully_locked(case: dict[str, Any]) -> None:
    verify = lambda: _validate_installed_packages_against_lock(  # noqa: E731
        case["packages"],
        case.get("constraints", {"direct": "2.0.0", "child": "1.0.0"}),
        tuple(case.get("dependency_metadata", ())),
        frozenset(case.get("direct_names", ())),
    )
    if error := case.get("error"):
        with pytest.raises(RuntimeError, match=error):
            verify()
    else:
        verify()


@pytest.mark.parametrize(
    ("lock_contents", "expected_error"),
    [
        ("not valid TOML", "Cannot read authoritative dependency lock"),
        (
            '[[package]]\nname = "missing-version"\n',
            "packages must include name and version",
        ),
        (
            '[[package]]\nname = "conflicting"\nversion = "1.0.0"\ndirect = false\n\n'
            '[[package]]\nname = "conflicting"\nversion = "2.0.0"\ndirect = false\n',
            "conflicting versions for conflicting",
        ),
        ("", "contains no package constraints"),
    ],
)
def test_lock_constraints_fail_closed_for_invalid_authoritative_shapes(
    tmp_path: Path,
    lock_contents: str,
    expected_error: str,
) -> None:
    lock = tmp_path / "uv.lock"
    constraints = tmp_path / "constraints.txt"
    lock.write_text(lock_contents, encoding="utf-8")

    with pytest.raises(RuntimeError) as error:
        _write_lock_constraints(lock, constraints)

    assert expected_error in str(error.value)
    assert not constraints.exists()


def test_governed_python_command_uses_current_supported_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.license_ip_evidence.sys.version_info",
        (3, 11, 9, "final", 0),
    )

    assert _governed_python_command(env={}) == (sys.executable,)


def test_governed_python_command_selects_python_311_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    expected_candidate = ("py", "-3.11") if os.name == "nt" else ("python3.11",)
    monkeypatch.setattr(
        "scripts.license_ip_evidence.sys.version_info",
        (3, 13, 0, "final", 0),
    )

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        if tuple(command[:-1]) == expected_candidate and command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="Python 3.11.9\n")
        return subprocess.CompletedProcess(command, 1, stderr="not found")

    monkeypatch.setattr("scripts.license_ip_evidence.subprocess.run", fake_run)

    assert _governed_python_command(env={"PATH": "test-path"}) == expected_candidate
    assert calls[0][0] == [*expected_candidate, "--version"]
    assert calls[0][1]["env"] == {"PATH": "test-path"}


def test_governed_python_command_skips_missing_launcher_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("scripts.license_ip_evidence.os.name", "nt")
    monkeypatch.setattr(
        "scripts.license_ip_evidence.sys.version_info",
        (3, 13, 0, "final", 0),
    )

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(command)
        if command[:2] == ["py", "-3.11"]:
            raise FileNotFoundError("py launcher missing")
        return subprocess.CompletedProcess(command, 0, stdout="Python 3.11.9\n")

    monkeypatch.setattr("scripts.license_ip_evidence.subprocess.run", fake_run)

    assert _governed_python_command(env={}) == ("python3.11",)
    assert calls == [["py", "-3.11", "--version"], ["python3.11", "--version"]]


def test_isolated_license_inventory_stops_on_install_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 17 if "pip" in command else 0)

    monkeypatch.setattr(
        "scripts.license_ip_evidence.sys.version_info",
        (3, 11, 9, "final", 0),
    )
    monkeypatch.setattr("scripts.license_ip_evidence.subprocess.run", fake_run)

    result = _run_in_isolated_environment(
        _isolated_args("write-inventory"),
        venv_root=tmp_path / "venv",
    )

    assert result == 17
    assert len(calls) == 2


def test_isolated_license_inventory_returns_two_before_any_install_when_lock_projection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("scripts.license_ip_evidence.REPO_ROOT", tmp_path)
    monkeypatch.setattr("scripts.license_ip_evidence.sys.version_info", (3, 11, 9, "final", 0))
    (tmp_path / "uv.lock").write_text("not valid TOML", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.license_ip_evidence.parse_requirement_roots", lambda *_args, **_kwargs: ()
    )

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("scripts.license_ip_evidence.subprocess.run", fake_run)

    result = _run_in_isolated_environment(
        _isolated_args("check-inventory"),
        venv_root=tmp_path / "venv",
    )

    assert result == 2
    assert len(calls) == 1
    assert "pip" not in calls[0]
    assert not (tmp_path / "license-ip-constraints.txt").exists()


def test_isolated_license_inventory_rejects_nested_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ISOLATED_ENV_FLAG, "1")

    with pytest.raises(RuntimeError, match="nested license/IP isolated execution"):
        _run_in_isolated_environment(_isolated_args("check-inventory"))


def test_license_inventory_includes_transitive_dependency(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg"),
        ],
    )

    packages = {package["name"]: package for package in inventory["packages"]}

    assert packages["directpkg"]["relationship"] == "direct"
    assert packages["childpkg"]["relationship"] == "transitive"
    assert packages["childpkg"]["policy_classification"] == "ALLOWED"


def test_license_inventory_records_direct_requirement_pin(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==2.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[FakeDistribution(name="directpkg", version="1.0.0")],
    )

    packages = {package["name"]: package for package in inventory["packages"]}

    assert packages["directpkg"]["version"] == "2.0.0"


def test_license_inventory_fails_direct_pin_metadata_mismatch(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==2.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[FakeDistribution(name="directpkg", version="1.0.0")],
    )

    failures = validate_license_inventory(inventory, _policy())

    assert inventory["packages"][0]["metadata_available"] is False
    assert (
        "directpkg installed metadata version 1.0.0 does not match pinned version 2.0.0; "
        "install requirements before regenerating license/IP inventory."
    ) in failures


def test_license_inventory_uses_repo_relative_release_graph_paths() -> None:
    inventory = build_license_inventory(
        runtime_requirements=Path("requirements-prod.txt"),
        development_requirements=Path("requirements-dev.txt"),
        policy=_policy(),
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="anyio"),
            FakeDistribution(name="coverage"),
            FakeDistribution(name="fastapi"),
            FakeDistribution(name="httpx"),
            FakeDistribution(name="orjson"),
            FakeDistribution(name="pandas"),
            FakeDistribution(name="pydantic"),
            FakeDistribution(name="pydantic-settings"),
            FakeDistribution(name="python-dotenv"),
            FakeDistribution(name="sqlalchemy"),
            FakeDistribution(name="structlog"),
            FakeDistribution(name="uvicorn"),
        ],
    )

    assert inventory["release_graphs"] == {
        "runtime": "requirements-prod.txt",
        "development": "requirements-dev.txt",
    }


def test_license_inventory_fails_stale_package_version(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==2.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[FakeDistribution(name="directpkg", version="2.0.0")],
    )
    stale_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="stale",
        image_digest="stale",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-10T00:00:00Z",
        distributions=[FakeDistribution(name="directpkg", version="2.0.0")],
    )
    stale_inventory["packages"][0]["version"] = "1.0.0"

    failures = validate_license_inventory_against_expected(
        stale_inventory,
        expected_inventory,
        _policy(),
    )

    assert "License/IP inventory is stale. Regenerate with `make license-ip-inventory`." in failures


def test_license_inventory_staleness_ignores_transitive_version_only_drift(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg", version="1.0.0"),
        ],
    )
    current_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg", version="1.0.1"),
        ],
    )

    failures = validate_license_inventory_against_expected(
        current_inventory,
        expected_inventory,
        _policy(),
    )

    assert failures == []


def test_license_inventory_staleness_detects_transitive_license_drift(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    current_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg", license_expression="Apache-2.0"),
        ],
    )
    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg", license_expression="MIT"),
        ],
    )

    failures = validate_license_inventory_against_expected(
        current_inventory,
        expected_inventory,
        _policy(),
    )

    assert any(
        "License/IP governance evidence changed for transitive package childpkg" in failure
        and "version '1.0.0' -> '1.0.0'" in failure
        and "license_term 'Apache-2.0' -> 'MIT'" in failure
        for failure in failures
    )


def test_license_inventory_staleness_detects_transitive_membership_drift(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    current_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg"),
        ],
    )
    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1", "newchild>=1"]),
            FakeDistribution(name="childpkg"),
            FakeDistribution(name="newchild"),
        ],
    )

    failures = validate_license_inventory_against_expected(
        current_inventory,
        expected_inventory,
        _policy(),
    )

    assert any(
        "License/IP inventory is missing new transitive package evidence: "
        "newchild (version '1.0.0', license 'MIT')" in failure
        for failure in failures
    )


def test_license_inventory_staleness_allows_platform_specific_extra_transitive_package(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    current_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["platformchild>=1"]),
            FakeDistribution(name="platformchild"),
        ],
    )
    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg"),
        ],
    )

    failures = validate_license_inventory_against_expected(
        current_inventory,
        expected_inventory,
        _policy(),
    )

    assert failures == []


def test_license_inventory_staleness_detects_transitive_dependency_group_drift(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\ndevpkg==1.0.0\n", encoding="utf-8")

    current_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg"),
            FakeDistribution(name="devpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg"),
        ],
    )
    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="devpkg", requires=["childpkg>=1"]),
            FakeDistribution(name="childpkg"),
        ],
    )

    failures = validate_license_inventory_against_expected(
        current_inventory,
        expected_inventory,
        _policy(),
    )

    assert any(
        "License/IP governance evidence changed for transitive package childpkg" in failure
        and "dependency_groups ['development'] -> ['development', 'runtime']" in failure
        for failure in failures
    )


def test_license_inventory_staleness_detects_transitive_exception_drift(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    current_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(exception_expiry="2099-01-01"),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["reviewpkg>=1"]),
            FakeDistribution(name="reviewpkg", license_expression="LGPL-3.0-only"),
        ],
    )
    expected_inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(exception_expiry="2100-01-01"),
        commit_sha="expected",
        image_digest="expected",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", requires=["reviewpkg>=1"]),
            FakeDistribution(name="reviewpkg", license_expression="LGPL-3.0-only"),
        ],
    )

    failures = validate_license_inventory_against_expected(
        current_inventory,
        expected_inventory,
        _policy(exception_expiry="2100-01-01"),
    )

    assert "reviewpkg license exception evidence is stale" in failures
    assert any(
        "License/IP governance evidence changed for transitive package reviewpkg" in failure
        and "exception_expires_on '2099-01-01' -> '2100-01-01'" in failure
        for failure in failures
    )


def test_license_inventory_policy_validation_detects_stale_classification(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("directpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="current",
        image_digest="current",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-12T00:00:00Z",
        distributions=[
            FakeDistribution(name="directpkg", license_expression="MIT-0"),
        ],
    )
    inventory["packages"][0]["policy_classification"] = "ALLOWED"

    failures = validate_license_inventory_against_expected(
        inventory,
        inventory,
        _policy(),
    )

    assert (
        "directpkg license classification ALLOWED does not match "
        "policy-derived classification REVIEW_REQUIRED"
    ) in failures


def test_license_inventory_fails_missing_package_metadata(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("missingpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[],
    )

    failures = validate_license_inventory(inventory, _policy())

    assert inventory["packages"][0]["metadata_available"] is False
    assert "missingpkg requires license/IP review for UNKNOWN" in failures


def test_license_inventory_allows_owned_unexpired_exception(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("reviewpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=_policy(),
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[FakeDistribution(name="reviewpkg", license_expression="LGPL-3.0-only")],
    )

    package = inventory["packages"][0]
    failures = validate_license_inventory(inventory, _policy())

    assert package["policy_classification"] == "APPROVED_EXCEPTION"
    assert package["exception_id"] == "TEST-LIC-001"
    assert failures == []


def test_license_inventory_blocks_expired_exception(tmp_path: Path) -> None:
    runtime = tmp_path / "requirements-prod.txt"
    development = tmp_path / "requirements-dev.txt"
    runtime.write_text("reviewpkg==1.0.0\n", encoding="utf-8")
    development.write_text("-r requirements-prod.txt\n", encoding="utf-8")
    policy = _policy(exception_expiry="2020-01-01")

    inventory = build_license_inventory(
        runtime_requirements=runtime,
        development_requirements=development,
        policy=policy,
        commit_sha="abc123",
        image_digest="sha256:abc123",
        repository_url="https://github.com/sgajbi/lotus-advise",
        generated_at_utc="2026-07-11T00:00:00Z",
        distributions=[FakeDistribution(name="reviewpkg", license_expression="LGPL-3.0-only")],
    )

    failures = validate_license_inventory(inventory, policy)

    assert "reviewpkg license exception TEST-LIC-001 expired on 2020-01-01" in failures


def _policy(*, exception_expiry: str = "2099-01-01") -> LicensePolicy:
    return LicensePolicy(
        allowed_terms=frozenset({"MIT", "Apache-2.0"}),
        review_required_terms=frozenset({"LGPL-3.0-only", "UNKNOWN"}),
        prohibited_terms=frozenset({"AGPL-3.0-only"}),
        exceptions=(
            {
                "id": "TEST-LIC-001",
                "package": "reviewpkg",
                "license_term": "LGPL-3.0-only",
                "owner": "test-owner",
                "expires_on": exception_expiry,
            },
        ),
    )


def _isolated_args(command: str) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        runtime_requirements="requirements-prod.txt",
        development_requirements="requirements-dev.txt",
        policy="docs/standards/license-ip-policy.v1.json",
        inventory="docs/standards/license-ip-inventory.v1.json",
        repository_url="https://github.com/sgajbi/lotus-advise",
        commit_sha="abc123",
        image_digest="sha256:abc123",
        generated_at_utc="2026-07-11T00:00:00Z",
        isolated=True,
    )
