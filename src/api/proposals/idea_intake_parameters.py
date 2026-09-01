from __future__ import annotations

from typing import Annotated

from fastapi import Header

from src.core.common.idempotency import MAX_IDEMPOTENCY_KEY_LENGTH

IdeaProposalIntakeCorrelationIdHeader = Annotated[
    str | None,
    Header(
        alias="X-Correlation-Id",
        description="Optional source-safe correlation id supplied by lotus-idea.",
        max_length=128,
        examples=["corr-idea-proposal-001"],
    ),
]

IdeaProposalIntakeIdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        description=(
            "Required replay-safe key for lotus-idea conversion-intent intake. "
            "Replays with the same request return the original receipt posture; conflicting "
            "payloads with the same key are rejected."
        ),
        min_length=1,
        max_length=MAX_IDEMPOTENCY_KEY_LENGTH,
        examples=["idea-intake-idem-001"],
    ),
]

IdeaProposalRealizationPortfolioHeader = Annotated[
    str,
    Header(
        alias="X-Portfolio-Id",
        description=(
            "Required producer-authorized portfolio scope for realization reads. It must match "
            "the durable Advise review-work scope."
        ),
        min_length=1,
        max_length=160,
        examples=["PB_SG_GLOBAL_BAL_001"],
    ),
]
