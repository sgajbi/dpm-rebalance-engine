from __future__ import annotations

from src.integrations.lotus_ai.workflow_response import (
    extract_error_detail,
    extract_model_version,
    extract_provider_id,
    extract_workflow_run_id,
    optional_text,
    safe_dict,
)


def test_safe_dict_rejects_untrusted_non_object_payloads() -> None:
    assert safe_dict({"execution": {"status": "COMPLETED"}}) == {
        "execution": {"status": "COMPLETED"}
    }
    assert safe_dict(["not", "an", "object"]) == {}
    assert safe_dict(None) == {}


def test_extract_workflow_run_id_and_model_version_trim_optional_lineage_values() -> None:
    payload = {"workflow_pack_run": {"run_id": "  packrun_advisory_001  "}}
    result = {"model_version": "  lotus-ai-governed-model.v1  "}

    assert extract_workflow_run_id(payload) == "packrun_advisory_001"
    assert extract_model_version(result) == "lotus-ai-governed-model.v1"
    assert extract_workflow_run_id({"workflow_pack_run": {"run_id": " "}}) is None
    assert extract_model_version({"model_version": 42}) is None


def test_extract_provider_and_model_identity_falls_back_to_task_audit() -> None:
    result = {"structured_output": {"state": "REVIEW_REQUIRED"}}
    audit = {
        "provider_id": " lotus-ai ",
        "model_version": " lotus-ai-governed-model.v1 ",
    }

    assert extract_provider_id(result, audit=audit) == "lotus-ai"
    assert extract_model_version(result, audit=audit) == "lotus-ai-governed-model.v1"


def test_extract_provider_and_model_identity_from_model_risk_output() -> None:
    result = {
        "structured_output": {
            "model_risk": {
                "approved_provider_id": " lotus-ai ",
                "approved_model_version": " lotus-ai-governed-model.v1 ",
            }
        }
    }
    audit = {
        "provider_id": "text.stub",
        "model_version": None,
    }

    assert extract_provider_id(result, audit=audit) == "lotus-ai"
    assert extract_model_version(result, audit=audit) == "lotus-ai-governed-model.v1"


def test_extract_error_detail_uses_default_for_blank_or_structured_details() -> None:
    assert (
        extract_error_detail({"detail": "  WORKFLOW_PACK_DISABLED  "}, default="UNAVAILABLE")
        == "WORKFLOW_PACK_DISABLED"
    )
    assert extract_error_detail({"detail": {"message": "ignored"}}, default="UNAVAILABLE") == (
        "UNAVAILABLE"
    )
    assert extract_error_detail({}, default="UNAVAILABLE") == "UNAVAILABLE"


def test_optional_text_can_bound_copilot_lineage_without_leaking_long_provider_text() -> None:
    assert optional_text("  line \n break  ", max_length=160) == "line break"

    bounded = optional_text("x" * 200, max_length=12)

    assert bounded == "xxxxxxxxx..."
    assert len(bounded) == 12


def test_optional_text_honors_tiny_provider_text_bounds() -> None:
    bounded = optional_text("sensitive provider response detail", max_length=2)

    assert bounded == ".."
    assert len(bounded) == 2
