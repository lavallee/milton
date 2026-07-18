from datetime import UTC, datetime
from decimal import Decimal

from milton.accounting import build_accounting
from milton.model import (
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
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
