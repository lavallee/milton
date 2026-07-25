from datetime import UTC, datetime
from decimal import Decimal

from milton.model import (
    CallStatus,
    CostKeyScope,
    CostPayload,
    ModelCallPayload,
    NormalizedEvent,
    SourceRef,
)
from milton.report import build_report

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def claude_code_cost_event(
    native_id: str, *, request_id: str, output_tokens: int
) -> NormalizedEvent:
    """A claude-code cost event: recovered usage, no priced amount."""

    return NormalizedEvent.create(
        source=SourceRef("claude-code", native_id),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=CostPayload(
            amount_usd=None,
            input_tokens=120,
            output_tokens=output_tokens,
            cached_input_tokens=900,
            cache_write_tokens=30,
            provider="anthropic",
            model="claude",
            authority="claude-code",
            accounting_key=f"anthropic.request={request_id}",
            accounting_key_scope=CostKeyScope.SHARED,
        ),
    )


def test_report_rolls_up_tokens_for_amount_unavailable_claude_code_costs() -> None:
    events = [
        NormalizedEvent.create(
            source=SourceRef("claude-code", "model:1"),
            occurred_at=NOW,
            recorded_at=NOW,
            payload=ModelCallPayload(
                provider="anthropic",
                model="claude",
                status=CallStatus.SUCCEEDED,
                finish_reason="end_turn",
            ),
        ),
        claude_code_cost_event("usage:1", request_id="req-1", output_tokens=250),
        claude_code_cost_event("usage:2", request_id="req-2", output_tokens=750),
    ]

    report = build_report(events)
    summary = report.adapters["claude-code"]

    # The recovered token counts must appear even though every amount is
    # unavailable, and the dollar roll-up stays honestly zero.
    assert summary.output_tokens == 1000
    assert summary.input_tokens == 240
    assert summary.cached_input_tokens == 1800
    assert summary.cache_write_tokens == 60
    assert summary.cost_usd == Decimal(0)

    adapters = report.to_dict()["adapters"]
    assert isinstance(adapters, dict)
    payload = adapters["claude-code"]
    assert isinstance(payload, dict)
    tokens = payload["tokens"]
    assert isinstance(tokens, dict)
    assert tokens["output"] == 1000
    assert payload["cost_usd"] == "0"
