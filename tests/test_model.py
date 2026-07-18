from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from milton.errors import ValidationError
from milton.model import (
    CostPayload,
    CoverageStatus,
    NormalizedEvent,
    SourceRef,
    coverage_for,
)

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def test_event_identity_is_stable_and_round_trips() -> None:
    payload = CostPayload(
        amount_usd=Decimal("1.2300"),
        input_tokens=100,
        output_tokens=20,
        cached_input_tokens=None,
        provider="example",
        model="model-1",
    )
    event = NormalizedEvent.create(
        source=SourceRef("codex", "call-123", "/tmp/session.jsonl"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=payload,
    )
    replay = NormalizedEvent.create(
        source=SourceRef("codex", "call-123", "/moved/session.jsonl"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=payload,
    )

    assert event.event_id == replay.event_id
    assert event.coverage["cached_input_tokens"] is CoverageStatus.UNAVAILABLE
    assert NormalizedEvent.from_dict(event.to_dict()) == event


def test_coverage_must_describe_reality_and_every_field() -> None:
    payload = CostPayload(None, None, None, None, None, None)
    dishonest = coverage_for(payload)
    dishonest["amount_usd"] = CoverageStatus.RECOVERED

    with pytest.raises(ValidationError, match="absent but marked recovered"):
        NormalizedEvent.create(
            source=SourceRef("adapter", "native"),
            occurred_at=NOW,
            recorded_at=NOW,
            payload=payload,
            coverage=dishonest,
        )

    with pytest.raises(ValidationError, match="coverage must be complete"):
        NormalizedEvent.create(
            source=SourceRef("adapter", "native"),
            occurred_at=NOW,
            recorded_at=NOW,
            payload=payload,
            coverage={"amount_usd": CoverageStatus.UNAVAILABLE},
        )


def test_cost_values_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="amount_usd"):
        CostPayload(Decimal("-0.01"), 1, 1, 0, "provider", "model")


def test_payload_kind_cannot_be_forged() -> None:
    event = NormalizedEvent.create(
        source=SourceRef("adapter", "native"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=CostPayload(Decimal("1"), 1, 1, 0, "provider", "model"),
    )
    with pytest.raises(ValidationError, match="cannot be used"):
        replace(event, kind="session")  # type: ignore[arg-type]
