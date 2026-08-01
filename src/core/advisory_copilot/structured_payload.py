from __future__ import annotations

import re
from typing import Any

from src.core.advisory_copilot.business_text import contains_copilot_business_technical_detail

RAW_AI_STORAGE_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "raw_output",
        "unsafe_output",
        "provider_response",
        "model_response",
        "provider_payload",
        "instruction",
        "raw_payload",
        "raw_source",
        "system_instruction",
        "trace_id",
    }
)

MAX_SAFE_STRUCTURED_PAYLOAD_DEPTH = 8
MAX_SAFE_STRUCTURED_PAYLOAD_ITEMS = 64
MAX_SAFE_STRUCTURED_PAYLOAD_TEXT_LENGTH = 4000

_LINEAGE_SENSITIVE_TEXT_FRAGMENTS = frozenset(
    {
        "authorization",
        "bearer token",
        "access token",
        "cookie",
        "credential",
        "password",
        "secret",
        "api key",
        "apikey",
        "raw prompt",
        "provider response",
        "provider output",
        "run ledger",
        "raw payload",
        "raw source",
    }
)
_LINEAGE_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\btrace[-_ ]?id\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bcorrelation[-_ ]?id\s*[:=]\s*\S+", re.IGNORECASE),
)


def assert_safe_structured_payload(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_SAFE_STRUCTURED_PAYLOAD_DEPTH:
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TOO_LARGE")
    if isinstance(value, dict):
        _assert_safe_structured_mapping(value, depth=depth)
    elif isinstance(value, list | tuple):
        _assert_safe_structured_sequence(value, depth=depth)
    elif isinstance(value, str):
        _assert_safe_structured_text(value)


def assert_safe_lineage_payload(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_SAFE_STRUCTURED_PAYLOAD_DEPTH:
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TOO_LARGE")
    if isinstance(value, dict):
        _assert_safe_lineage_mapping(value, depth=depth)
    elif isinstance(value, list | tuple):
        _assert_safe_lineage_sequence(value, depth=depth)
    elif isinstance(value, str):
        _assert_safe_lineage_text(value)


def _assert_safe_structured_mapping(value: dict[Any, Any], *, depth: int) -> None:
    _assert_safe_structured_item_count(value)
    for key, nested in value.items():
        _assert_safe_structured_key(key)
        assert_safe_structured_payload(nested, depth=depth + 1)


def _assert_safe_structured_sequence(value: list[Any] | tuple[Any, ...], *, depth: int) -> None:
    _assert_safe_structured_item_count(value)
    for item in value:
        assert_safe_structured_payload(item, depth=depth + 1)


def _assert_safe_lineage_mapping(value: dict[Any, Any], *, depth: int) -> None:
    _assert_safe_structured_item_count(value)
    for key, nested in value.items():
        _assert_safe_structured_key(key)
        assert_safe_lineage_payload(nested, depth=depth + 1)


def _assert_safe_lineage_sequence(value: list[Any] | tuple[Any, ...], *, depth: int) -> None:
    _assert_safe_structured_item_count(value)
    for item in value:
        assert_safe_lineage_payload(item, depth=depth + 1)


def _assert_safe_structured_item_count(value: dict[Any, Any] | list[Any] | tuple[Any, ...]) -> None:
    if len(value) > MAX_SAFE_STRUCTURED_PAYLOAD_ITEMS:
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TOO_LARGE")


def _assert_safe_structured_key(value: Any) -> None:
    if normalize_structured_payload_key(value) in RAW_AI_STORAGE_KEYS:
        raise ValueError("COPILOT_RAW_AI_PAYLOAD_NOT_ALLOWED")


def _assert_safe_structured_text(value: str) -> None:
    if len(value) > MAX_SAFE_STRUCTURED_PAYLOAD_TEXT_LENGTH:
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TOO_LARGE")
    if contains_copilot_business_technical_detail(value):
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TECHNICAL_DETAIL")


def _assert_safe_lineage_text(value: str) -> None:
    if len(value) > MAX_SAFE_STRUCTURED_PAYLOAD_TEXT_LENGTH:
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TOO_LARGE")
    normalized = value.lower().replace("-", " ").replace("_", " ")
    if any(pattern.search(value) for pattern in _LINEAGE_SENSITIVE_TEXT_PATTERNS):
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TECHNICAL_DETAIL")
    if any(fragment in normalized for fragment in _LINEAGE_SENSITIVE_TEXT_FRAGMENTS):
        raise ValueError("COPILOT_STRUCTURED_PAYLOAD_TECHNICAL_DETAIL")


def normalize_structured_payload_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")
