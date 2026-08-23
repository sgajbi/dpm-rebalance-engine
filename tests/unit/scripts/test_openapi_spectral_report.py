import json
from pathlib import Path
from subprocess import CompletedProcess

from scripts import openapi_spectral_report


def test_spectral_command_uses_windows_npx_executable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(openapi_spectral_report.sys, "platform", "win32")

    assert openapi_spectral_report._spectral_command(tmp_path) == [
        "npx.cmd",
        "--yes",
        "@stoplight/spectral-cli@6.16.0",
    ]


def test_spectral_report_normalizes_findings(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".spectral.yaml").write_text("rules: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        openapi_spectral_report.app,
        "openapi",
        lambda: {"paths": {"/advisory/example": {}}},
    )

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        payload = [
            {
                "code": "operation-description",
                "severity": 1,
                "path": ["paths", "/advisory/example", "get"],
                "message": "Operation description is required.",
            }
        ]
        return CompletedProcess(args=args, returncode=1, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(openapi_spectral_report.subprocess, "run", fake_run)

    report = openapi_spectral_report.build_spectral_report(tmp_path)

    assert report["spectralExecutable"] is True
    assert report["openapiPathCount"] == 1
    assert report["issueCount"] == 1
    assert report["severityInventory"] == {"warn": 1}
    assert report["findings"] == [
        {
            "code": "operation-description",
            "severity": "warn",
            "path": "paths./advisory/example.get",
            "message": "Operation description is required.",
        }
    ]


def test_spectral_report_records_execution_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        openapi_spectral_report.app,
        "openapi",
        lambda: {"paths": {"/advisory/example": {}}},
    )

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(
            args=args,
            returncode=2,
            stdout="",
            stderr="Error running Spectral!",
        )

    monkeypatch.setattr(openapi_spectral_report.subprocess, "run", fake_run)

    report = openapi_spectral_report.build_spectral_report(tmp_path)

    assert report["spectralExecutable"] is False
    assert report["returnCode"] == 2
    assert report["issueCount"] is None
    assert report["stderr"] == "Error running Spectral!"


def test_spectral_report_cli_fails_closed_when_spectral_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        openapi_spectral_report.app,
        "openapi",
        lambda: {"paths": {"/advisory/example": {}}},
    )

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=args, returncode=127, stdout="", stderr="node: not found")

    monkeypatch.setattr(openapi_spectral_report.subprocess, "run", fake_run)
    output_path = tmp_path / "spectral-report.json"

    exit_code = openapi_spectral_report.main(
        ["--repo-root", str(tmp_path), "--output", str(output_path)]
    )

    assert exit_code == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["spectralExecutable"] is False
    assert report["returnCode"] == 127


def test_spectral_report_accepts_empty_success_output(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        openapi_spectral_report.app,
        "openapi",
        lambda: {"paths": {"/advisory/example": {}}},
    )

    def fake_run(*args, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(
            args=args,
            returncode=0,
            stdout="[]No results with a severity of 'error' found!",
            stderr="",
        )

    monkeypatch.setattr(openapi_spectral_report.subprocess, "run", fake_run)

    report = openapi_spectral_report.build_spectral_report(tmp_path)

    assert report["spectralExecutable"] is True
    assert report["openapiPathCount"] == 1
    assert report["issueCount"] == 0
    assert report["severityInventory"] == {}
    assert report["findings"] == []
