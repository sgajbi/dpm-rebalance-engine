from __future__ import annotations

from fastapi import status

from src.api.http_status import HTTP_422_UNPROCESSABLE

MEMO_RUNTIME_UNAVAILABLE_RESPONSE = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "Proposal runtime persistence is unavailable or misconfigured."
    },
}

MEMO_NOT_FOUND_RESPONSE = {
    status.HTTP_404_NOT_FOUND: {
        "description": "Proposal, immutable proposal version, or persisted memo was not found."
    },
}

MEMO_CREATE_RESPONSES = {
    status.HTTP_404_NOT_FOUND: {
        "description": "Proposal or immutable proposal version was not found."
    },
    status.HTTP_409_CONFLICT: {
        "description": "Idempotency key was reused with a different memo-create payload."
    },
    HTTP_422_UNPROCESSABLE: {
        "description": (
            "Memo creation failed validation or finalization is blocked by "
            "source-readiness posture."
        )
    },
    **MEMO_RUNTIME_UNAVAILABLE_RESPONSE,
}

MEMO_READ_RESPONSES = {
    **MEMO_NOT_FOUND_RESPONSE,
    **MEMO_RUNTIME_UNAVAILABLE_RESPONSE,
}

MEMO_REVIEW_RESPONSES = {
    **MEMO_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {
        "description": "Idempotency key was reused with a different memo-review payload."
    },
    HTTP_422_UNPROCESSABLE: {
        "description": (
            "Review request is invalid, stale, or attempts unsupported client-ready release."
        )
    },
    **MEMO_RUNTIME_UNAVAILABLE_RESPONSE,
}

MEMO_REPORT_PACKAGE_EVENT_RESPONSES = {
    **MEMO_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {
        "description": "Idempotency key was reused with a different report-package event payload."
    },
    HTTP_422_UNPROCESSABLE: {
        "description": "Report-package event is invalid or references a stale memo hash."
    },
    **MEMO_RUNTIME_UNAVAILABLE_RESPONSE,
}

MEMO_REPORT_PACKAGE_RESPONSES = {
    **MEMO_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {
        "description": "Idempotency key was reused with a different report-package request payload."
    },
    HTTP_422_UNPROCESSABLE: {
        "description": (
            "Report-package request is invalid, references a stale memo hash, lacks "
            "advisor-use review, or attempts client-ready document release."
        )
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": (
            "lotus-report report/render/archive materialization or required source-derived "
            "as-of/reporting context is unavailable."
        )
    },
}

MEMO_AI_COMMENTARY_RESPONSES = {
    **MEMO_NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {
        "description": "Idempotency key was reused with a different AI commentary payload."
    },
    HTTP_422_UNPROCESSABLE: {
        "description": (
            "AI commentary request is invalid, references a stale memo hash, or lacks "
            "advisor-use review."
        )
    },
    **MEMO_RUNTIME_UNAVAILABLE_RESPONSE,
}

MEMO_LINEAGE_RESPONSES = {
    status.HTTP_404_NOT_FOUND: {"description": "Proposal was not found."},
    **MEMO_RUNTIME_UNAVAILABLE_RESPONSE,
}
