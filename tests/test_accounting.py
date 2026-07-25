from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from milton.accounting import build_accounting, select_cost_events, select_token_events
from milton.model import (
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    NormalizedEvent,
    SourceRef,
)

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def cost_event(
    adapter: str,
    native_id: str,
    amount: str,
    *,
    key: str,
    scope: CostKeyScope = CostKeyScope.SHARED,
    basis: CostBasis,
    accuracy: CostAccuracy,
    kind: CostKind = CostKind.MARGINAL,
) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef(adapter, native_id),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=CostPayload(
            amount_usd=Decimal(amount),
            input_tokens=10,
            output_tokens=2,
            cached_input_tokens=0,
            provider="provider",
            model="model",
            basis=basis,
            kind=kind,
            accuracy=accuracy,
            authority=adapter,
            accounting_key=key,
            accounting_key_scope=scope,
        ),
    )


def test_projection_deduplicates_only_exact_shared_keys_with_explicit_precedence() -> None:
    events = [
        cost_event(
            "somm",
            "computed",
            "1.00",
            key="provider.request=req-1",
            basis=CostBasis.COMPUTED,
            accuracy=CostAccuracy.ESTIMATED,
        ),
        cost_event(
            "provider",
            "reported",
            "1.10",
            key="provider.request=req-1",
            basis=CostBasis.REPORTED,
            accuracy=CostAccuracy.ACTUAL,
        ),
        cost_event(
            "somm",
            "notional",
            "4.00",
            key="provider.request=req-1",
            basis=CostBasis.COMPUTED,
            accuracy=CostAccuracy.ESTIMATED,
            kind=CostKind.NOTIONAL,
        ),
    ]

    projection = build_accounting(events)

    assert projection.raw_observed_usd == Decimal("6.10")
    assert projection.selected_total_usd == Decimal("5.10")
    assert projection.suppressed_usd == Decimal("1.00")
    assert projection.suppressed_observations == 1
    assert projection.selected_by_kind[CostKind.MARGINAL] == Decimal("1.10")
    assert projection.selected_by_kind[CostKind.NOTIONAL] == Decimal("4.00")
    assert projection.decisions[0].selected_adapter == "provider"


def test_actual_computed_amount_beats_a_reported_estimate() -> None:
    projection = build_accounting(
        [
            cost_event(
                "upstream",
                "estimate",
                "2.00",
                key="provider.request=req-2",
                basis=CostBasis.REPORTED,
                accuracy=CostAccuracy.ESTIMATED,
            ),
            cost_event(
                "ledger",
                "actual",
                "2.10",
                key="provider.request=req-2",
                basis=CostBasis.COMPUTED,
                accuracy=CostAccuracy.ACTUAL,
            ),
        ]
    )

    assert projection.selected_total_usd == Decimal("2.10")
    assert projection.decisions[0].selected_adapter == "ledger"


def test_source_local_keys_do_not_collapse_across_adapters() -> None:
    projection = build_accounting(
        [
            cost_event(
                "one",
                "a",
                "1.00",
                key="call=1",
                scope=CostKeyScope.SOURCE,
                basis=CostBasis.REPORTED,
                accuracy=CostAccuracy.ACTUAL,
            ),
            cost_event(
                "two",
                "b",
                "1.00",
                key="call=1",
                scope=CostKeyScope.SOURCE,
                basis=CostBasis.REPORTED,
                accuracy=CostAccuracy.ACTUAL,
            ),
        ]
    )

    assert projection.selected_total_usd == Decimal("2.00")
    assert projection.suppressed_observations == 0
    assert projection.source_key_observations == 2
    assert "does not deduplicate them by timestamp" in projection.to_text()


def _output_tokens(events: Iterable[NormalizedEvent]) -> int:
    total = 0
    for event in events:
        assert isinstance(event.payload, CostPayload)
        total += event.payload.output_tokens or 0
    return total


def usage_only_cost_event(
    native_id: str,
    *,
    key: str,
    output_tokens: int,
) -> NormalizedEvent:
    """A claude-code-shaped cost event: recovered usage but no priced amount."""

    return NormalizedEvent.create(
        source=SourceRef("claude-code", native_id),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=CostPayload(
            amount_usd=None,
            input_tokens=100,
            output_tokens=output_tokens,
            cached_input_tokens=7,
            cache_write_tokens=3,
            provider="anthropic",
            model="claude",
            authority="claude-code",
            accounting_key=key,
            accounting_key_scope=CostKeyScope.SOURCE,
        ),
    )


def test_token_selection_retains_amount_unavailable_observations() -> None:
    events = [
        usage_only_cost_event("m1", key="claude-code.message=s:1", output_tokens=11),
        usage_only_cost_event("m2", key="claude-code.message=s:2", output_tokens=22),
    ]

    # Monetary selection correctly drops both: neither carries a priced amount.
    assert select_cost_events(events) == ()
    assert build_accounting(events).amount_unavailable == 2

    # Token selection retains both so their recovered usage is not lost.
    selected = select_token_events(events)
    assert len(selected) == 2
    assert _output_tokens(selected) == 33


def test_token_selection_excludes_rollups_and_dedups_exact_duplicates() -> None:
    shared_key = "anthropic.request=req-9"
    events = [
        # Two observations of the same billable unit (shared key): one wins.
        NormalizedEvent.create(
            source=SourceRef("somm", "priced"),
            occurred_at=NOW,
            recorded_at=NOW,
            payload=CostPayload(
                amount_usd=Decimal("1.00"),
                input_tokens=100,
                output_tokens=40,
                cached_input_tokens=0,
                provider="anthropic",
                model="claude",
                basis=CostBasis.REPORTED,
                accuracy=CostAccuracy.ACTUAL,
                authority="somm",
                accounting_key=shared_key,
                accounting_key_scope=CostKeyScope.SHARED,
            ),
        ),
        # The same billable unit observed again with only recovered usage.
        NormalizedEvent.create(
            source=SourceRef("claude-code", "dup"),
            occurred_at=NOW,
            recorded_at=NOW,
            payload=CostPayload(
                amount_usd=None,
                input_tokens=100,
                output_tokens=40,
                cached_input_tokens=0,
                provider="anthropic",
                model="claude",
                authority="claude-code",
                accounting_key=shared_key,
                accounting_key_scope=CostKeyScope.SHARED,
            ),
        ),
        # A rollup summarizes child tokens and must never be counted.
        NormalizedEvent.create(
            source=SourceRef("somm", "rollup"),
            occurred_at=NOW,
            recorded_at=NOW,
            payload=CostPayload(
                amount_usd=Decimal("1.00"),
                input_tokens=1000,
                output_tokens=400,
                cached_input_tokens=0,
                provider="anthropic",
                model="claude",
                observation_role=CostObservationRole.ROLLUP,
                accounting_key="campaign=x",
                accounting_key_scope=CostKeyScope.SOURCE,
            ),
        ),
    ]

    selected = select_token_events(events)
    # One representative for the shared-key pair, rollup excluded entirely.
    assert len(selected) == 1
    assert _output_tokens(selected) == 40
