from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "external-adapter-contracts"
    / "lotus-advise-external-adapter-contracts.v1.json"
)
REQUIRED_ADAPTERS = {"lotus_core", "lotus_risk", "lotus_report", "lotus_ai"}
REQUIRED_CASE_IDS = {
    "valid_provider_response",
    "malformed_json",
    "missing_fields",
    "identity_as_of_mismatch",
    "partial_data",
    "auth_failure",
    "timeout",
    "retry",
    "duplicate_response",
    "provider_error_mapping",
    "no_raw_payload_or_secret",
}
SENSITIVE_KEY_FRAGMENTS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "provider_response",
    "raw_output",
    "raw_payload",
    "raw_prompt",
    "secret",
    "token",
}
SENSITIVE_VALUE_FRAGMENTS = {
    "access_token=",
    "api_key=",
    "authorization:",
    "bearer ",
    "password=",
}


def _manifest() -> dict[str, Any]:
    return json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))


def test_external_adapter_contract_manifest_declares_all_authority_seams() -> None:
    manifest = _manifest()

    assert manifest["manifest_version"] == "lotus-advise.external-adapter-contracts.v1"
    assert manifest["fixture_revision"] == "2026-08-28.issue-557"
    assert set(manifest["required_case_ids"]) == REQUIRED_CASE_IDS
    assert set(manifest["adapters"]) == REQUIRED_ADAPTERS

    for adapter_name, adapter in manifest["adapters"].items():
        provider_contract = adapter["provider_contract"]
        assert provider_contract["version"].endswith(".v1"), adapter_name
        assert provider_contract["fixture_revision"] == manifest["fixture_revision"]
        assert provider_contract["schema_ref"].startswith("src/integrations/")
        assert adapter["authority"]
        assert adapter["valid_request"]
        assert adapter["valid_response"]


def test_lotus_core_contract_declares_source_effect_decision_ownership() -> None:
    manifest = _manifest()
    core_response = manifest["adapters"]["lotus_core"]["valid_response"]

    assert core_response["provider_schema"] == "CoreProjectedTransactionEffects"
    assert core_response["parity_snapshot_field"] == "non_authoritative_core_decisions"

    source_effect_fields = set(core_response["source_effect_authority_fields"])
    non_authoritative_fields = set(core_response["non_authoritative_decision_fields"])
    advise_decision_fields = set(core_response["advise_decision_authority_fields"])

    provider_fixture = (
        REPO_ROOT / manifest["adapters"]["lotus_core"]["provider_contract"]["provider_fixture_ref"]
    )
    assert provider_fixture.is_file()
    assert json.loads(provider_fixture.read_text(encoding="utf-8"))["product_name"] == (
        "PortfolioStateSnapshot"
    )

    assert {
        "before",
        "after_simulated",
        "intents",
        "reconciliation",
        "rule_results",
        "allocation_lens",
        "lineage",
    } <= source_effect_fields
    assert {
        "status",
        "suitability",
        "gate_decision",
        "proposal_decision_summary",
        "proposal_alternatives",
    } <= non_authoritative_fields
    assert advise_decision_fields <= non_authoritative_fields
    assert source_effect_fields.isdisjoint(non_authoritative_fields)


def test_external_adapter_contract_cases_cover_required_failure_modes() -> None:
    manifest = _manifest()

    for adapter_name, adapter in manifest["adapters"].items():
        case_ids = {case["case_id"] for case in adapter["cases"]}
        assert case_ids == REQUIRED_CASE_IDS, adapter_name
        for case in adapter["cases"]:
            assert case["expected_behavior"], (adapter_name, case["case_id"])
            assert case["test_references"], (adapter_name, case["case_id"])


def test_external_adapter_contract_manifest_references_existing_regression_tests() -> None:
    manifest = _manifest()

    for adapter in manifest["adapters"].values():
        for case in adapter["cases"]:
            for reference in case["test_references"]:
                path_text, test_name = reference.split("::", maxsplit=1)
                test_path = REPO_ROOT / path_text
                assert test_path.exists(), reference
                source = test_path.read_text(encoding="utf-8")
                assert f"def {test_name}(" in source, reference


def test_external_adapter_contract_fixtures_do_not_carry_raw_or_secret_material() -> None:
    manifest = _manifest()

    for adapter_name, adapter in manifest["adapters"].items():
        _assert_safe_fixture(adapter["valid_request"], path=(adapter_name, "valid_request"))
        _assert_safe_fixture(adapter["valid_response"], path=(adapter_name, "valid_response"))


def test_external_adapter_contract_lane_is_repo_native_and_part_of_check() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "external-adapter-contracts:" in makefile
    assert "external-adapter-contracts" in _make_target_prerequisites(makefile, "check")
    assert "test_external_adapter_contract_fixtures.py" in makefile


def _make_target_prerequisites(makefile: str, target: str) -> set[str]:
    for line in makefile.splitlines():
        if line.startswith(f"{target}:"):
            return set(line.split(":", maxsplit=1)[1].split())
    raise AssertionError(f"missing Make target: {target}")


def _assert_safe_fixture(value: Any, *, path: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            assert not any(fragment in key_text for fragment in SENSITIVE_KEY_FRAGMENTS), (
                path,
                key,
            )
            _assert_safe_fixture(item, path=(*path, str(key)))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_safe_fixture(item, path=(*path, str(index)))
        return
    if isinstance(value, str):
        normalized = value.lower()
        assert not any(fragment in normalized for fragment in SENSITIVE_VALUE_FRAGMENTS), path
