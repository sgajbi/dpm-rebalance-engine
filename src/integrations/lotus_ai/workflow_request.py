from __future__ import annotations

import os
from typing import Any

from src.integrations.lotus_ai.runtime_config import resolve_lotus_ai_tenant_id

_WORKFLOW_PACK_ENVIRONMENT = "LOTUS_AI_WORKFLOW_PACK_ENVIRONMENT"
_DEFAULT_WORKFLOW_PACK_ENVIRONMENT = "DEVELOPMENT"
_CALLER_APP = "lotus-advise"
_CALLER_APP_HEADER = "X-Caller-App"
_CALLER_IDENTITY_CLASS = "INTERNAL_SERVICE"
_DEFAULT_INPUT_MODE = "STRUCTURED_CONTEXT"


def build_workflow_pack_execute_request(
    *,
    pack_id: str,
    version: str,
    workflow_surface: str,
    task_id: str,
    correlation_id: str,
    requested_by: Any,
    context_summary: str,
    context_payload: dict[str, Any],
    source_refs: list[str],
    expected_output_label: str,
    input_mode: str = _DEFAULT_INPUT_MODE,
) -> dict[str, object]:
    return {
        "pack_id": pack_id,
        "version": version,
        "environment": workflow_pack_environment(),
        "caller_identity_class": _CALLER_IDENTITY_CLASS,
        "workflow_surface": workflow_surface,
        "task_request": {
            "task_id": task_id,
            "input_mode": input_mode,
            "caller": {
                "caller_app": _CALLER_APP,
                "correlation_id": correlation_id,
                "requested_by": requested_by,
                "tenant_id": resolve_lotus_ai_tenant_id(),
            },
            "context": {
                "summary": context_summary,
                "payload": context_payload,
                "source_refs": source_refs,
            },
            "expected_output_label": expected_output_label,
        },
    }


def workflow_pack_environment() -> str:
    return os.getenv(
        _WORKFLOW_PACK_ENVIRONMENT,
        _DEFAULT_WORKFLOW_PACK_ENVIRONMENT,
    )


def workflow_pack_authenticated_headers() -> dict[str, str]:
    return {_CALLER_APP_HEADER: _CALLER_APP}
