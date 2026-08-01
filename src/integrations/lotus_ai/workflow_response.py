from __future__ import annotations

from typing import Any

_TRUNCATION_SUFFIX = "..."
_MODEL_IDENTITY_SOURCE_DISAGREEMENT = "MODEL_IDENTITY_SOURCE_DISAGREEMENT"


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_workflow_run_id(
    payload: dict[str, Any],
    *,
    max_length: int | None = None,
) -> str | None:
    workflow_pack_run = safe_dict(payload.get("workflow_pack_run"))
    return optional_text(workflow_pack_run.get("run_id"), max_length=max_length)


def extract_model_version(
    result: dict[str, Any],
    *,
    audit: dict[str, Any] | None = None,
    max_length: int | None = None,
) -> str | None:
    model_risk = _result_model_risk(result)
    audit_model_version = optional_text(safe_dict(audit).get("model_version"))
    asserted_model_version = _first_optional_text(
        result.get("model_version"),
        model_risk.get("approved_model_version"),
    )
    if audit_model_version is not None:
        if asserted_model_version is not None and asserted_model_version != audit_model_version:
            return _bounded_identity_disagreement(max_length=max_length)
        return optional_text(audit_model_version, max_length=max_length)
    return optional_text(asserted_model_version, max_length=max_length)


def extract_provider_id(
    result: dict[str, Any],
    *,
    audit: dict[str, Any] | None = None,
    max_length: int | None = None,
) -> str | None:
    model_risk = _result_model_risk(result)
    audit_provider_id = optional_text(safe_dict(audit).get("provider_id"))
    asserted_provider_id = _first_optional_text(
        result.get("provider_id"),
        result.get("provider"),
        result.get("model_provider"),
        safe_dict(result.get("model")).get("provider_id"),
        model_risk.get("approved_provider_id"),
    )
    if audit_provider_id is not None:
        if asserted_provider_id is not None and asserted_provider_id != audit_provider_id:
            return _bounded_identity_disagreement(max_length=max_length)
        return optional_text(audit_provider_id, max_length=max_length)
    return optional_text(asserted_provider_id, max_length=max_length)


def extract_error_detail(
    payload: dict[str, Any],
    *,
    default: str,
    max_length: int | None = None,
) -> str:
    detail = optional_text(payload.get("detail"), max_length=max_length)
    return detail if detail is not None else default


def optional_text(value: Any, *, max_length: int | None = None) -> str | None:
    normalized = _normalized_optional_text(value, collapse_whitespace=max_length is not None)
    if normalized is None or max_length is None:
        return normalized

    return _bounded_text(normalized, max_length=max_length)


def _result_model_risk(result: dict[str, Any]) -> dict[str, Any]:
    structured_output = safe_dict(result.get("structured_output"))
    return safe_dict(structured_output.get("model_risk"))


def _first_optional_text(*values: Any) -> str | None:
    for value in values:
        normalized = optional_text(value)
        if normalized is not None:
            return normalized
    return None


def _bounded_identity_disagreement(*, max_length: int | None) -> str:
    if max_length is None:
        return _MODEL_IDENTITY_SOURCE_DISAGREEMENT
    return _bounded_text(_MODEL_IDENTITY_SOURCE_DISAGREEMENT, max_length=max_length)


def _normalized_optional_text(value: Any, *, collapse_whitespace: bool) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = " ".join(value.split()) if collapse_whitespace else value.strip()
    return normalized or None


def _bounded_text(value: str, *, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    if max_length <= len(_TRUNCATION_SUFFIX):
        return _TRUNCATION_SUFFIX[:max_length]

    return value[: max_length - len(_TRUNCATION_SUFFIX)].rstrip() + _TRUNCATION_SUFFIX
