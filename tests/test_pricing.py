import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from milton.errors import MiltonError
from milton.fleet import FLEET_NAME, merge_fleet
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostKind,
    CostObservationRole,
    CostPayload,
    CoverageStatus,
    ModelCallPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
)
from milton.pricing import (
    NOTIONAL_PRICING_VERSION,
    PriceTable,
    build_notional_summary,
    normalize_model,
    notional_amount,
    with_notional,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
TABLE = PriceTable.builtin()


def usage(
    provider: str,
    model: str | None,
    *,
    input_tokens: int | None = 0,
    cached: int | None = 0,
    write: int | None = 0,
    output: int | None = 0,
    amount: str | None = None,
    role: CostObservationRole = CostObservationRole.PRODUCTION,
) -> CostPayload:
    return CostPayload(
        Decimal(amount) if amount is not None else None,
        input_tokens,
        output,
        cached,
        provider,
        model,
        cache_write_tokens=write,
        observation_role=role,
    )


def cost_event(payload: CostPayload, native_id: str, parent: str | None = None) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("claude-code", native_id),
        occurred_at=NOW,
        recorded_at=NOW,
        parent_event_id=parent,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("anthropic/claude-opus-4.6", "claude-opus-4-6"),
        ("claude-sonnet-5-20260801", "claude-sonnet-5"),
        ("GPT-6.2-Sol", "gpt-6.2-sol"),
    ],
)
def test_normalize_model(raw: str, expected: str) -> None:
    assert normalize_model(raw) == expected


def test_anthropic_cache_reads_are_separate_from_input() -> None:
    # Opus 5.5: $4 input, $0.20 cache read, $5 cache write, $20 output per MTok.
    payload = usage(
        "anthropic",
        "claude-opus-5-5",
        input_tokens=1_000_000,
        cached=10_000_000,
        write=1_000_000,
        output=100_000,
    )
    assert notional_amount(payload, TABLE) == Decimal("4") + Decimal("2") + Decimal("5") + Decimal(
        "2"
    )


def test_openai_cached_tokens_are_a_subset_of_input() -> None:
    # gpt-6.2-astra: $8 input, $0.40 cached, $40 output; 9M of 10M input were cached.
    payload = usage(
        "openai", "gpt-6.2-astra", input_tokens=10_000_000, cached=9_000_000, output=1_000_000
    )
    assert notional_amount(payload, TABLE) == Decimal("8") + Decimal("3.6") + Decimal("40")


def test_unknown_model_and_missing_tokens_are_not_valued() -> None:
    assert notional_amount(usage("openai", "codex-auto-review", input_tokens=5), TABLE) is None
    assert notional_amount(usage("anthropic", None, input_tokens=5), TABLE) is None
    no_tokens = usage(
        "anthropic", "claude-opus-5-5", input_tokens=None, cached=None, write=None, output=None
    )
    assert notional_amount(no_tokens, TABLE) is None


def test_with_notional_copies_only_unpriced_production_costs() -> None:
    unpriced = cost_event(usage("anthropic", "claude-sonnet-5-5", output=1_000_000), "u")
    priced = cost_event(usage("anthropic", "claude-sonnet-5-5", output=5, amount="0.01"), "p")
    rollup = cost_event(
        usage("anthropic", "claude-sonnet-5-5", output=5, role=CostObservationRole.ROLLUP), "r"
    )
    unknown = cost_event(usage("openai", "codex-auto-review", output=5), "x")

    result = with_notional((unpriced, priced, rollup, unknown))

    copy = result[0]
    assert copy.event_id == unpriced.event_id
    assert isinstance(copy.payload, CostPayload)
    assert copy.payload.amount_usd == Decimal("10")
    assert copy.payload.kind is CostKind.NOTIONAL
    assert copy.payload.basis is CostBasis.COMPUTED
    assert copy.payload.accuracy is CostAccuracy.ESTIMATED
    assert copy.payload.pricing_version == NOTIONAL_PRICING_VERSION
    assert copy.coverage["amount_usd"] is CoverageStatus.INFERRED
    assert result[1:] == (priced, rollup, unknown)
    assert isinstance(unpriced.payload, CostPayload)
    assert unpriced.payload.amount_usd is None

    summary: Any = build_notional_summary((unpriced, priced, rollup, unknown)).to_dict()
    assert summary["unpriced_cost_events"] == 2
    assert summary["valued_events"] == 1
    assert Decimal(str(summary["amount_usd"])) == Decimal("10")
    assert summary["unvalued_models"] == {"codex-auto-review": 1}


def test_price_table_file_overrides_builtin(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            {
                "version": "ops/2026-12",
                "models": [
                    {
                        "provider": "openai",
                        "model": "codex-auto-review",
                        "input": "1",
                        "cached_input": "0.1",
                        "cache_write": "1",
                        "output": "4",
                    }
                ],
            }
        )
    )
    table = PriceTable.from_file(path)
    assert table.version == "ops/2026-12"
    payload = usage("openai", "codex-auto-review", input_tokens=1_000_000, output=1_000_000)
    assert notional_amount(payload, table) == Decimal("5")
    path.write_text("{}")
    with pytest.raises(MiltonError):
        PriceTable.from_file(path)


def _host_store(
    path: Path, events: tuple[NormalizedEvent, ...], relations: tuple[RelationRecord, ...] = ()
) -> None:
    path.parent.mkdir(parents=True)
    with MiltonStore(path) as store:
        store.append_events(events)
        for relation in relations:
            store.append_relation(relation)


def test_merged_fleet_attributes_spend_across_hosts(tmp_path: Path) -> None:
    call = NormalizedEvent.create(
        source=SourceRef("somm", "call-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=ModelCallPayload("anthropic", "claude-opus-5-5", CallStatus.SUCCEEDED, "stop"),
    )
    spend = NormalizedEvent.create(
        source=SourceRef("somm", "cost:call-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        parent_event_id=call.event_id,
        payload=usage("anthropic", "claude-opus-5-5", output=1_000_000),
    )
    outcome = NormalizedEvent.create(
        source=SourceRef("fab", "terminal:job-1"),
        occurred_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
        payload=OutcomePayload("fab.job", OutcomeStatus.SUCCEEDED, "job-1"),
    )
    relation = RelationRecord.create(
        subject=TypedRef("fab.job", "job-1"),
        predicate=RelationKind.PRODUCED,
        object=TypedRef("somm.call", "call-1"),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        recorded_at=NOW,
    )
    # The spend is on one host; the outcome and its receipt are on another.
    _host_store(tmp_path / "spender" / "events.db", (call, spend))
    _host_store(tmp_path / "runner" / "events.db", (outcome,), (relation,))
    since = NOW - timedelta(days=1)

    snapshot: Any = json.loads(
        json.dumps(merge_fleet(tmp_path, ["spender", "runner"], since=since))
    )

    assert snapshot["host"] == FLEET_NAME
    assert snapshot["merge"] == {
        "spender": {"events": 2, "duplicates": 0, "conflicts": 0, "links": 0},
        "runner": {"events": 1, "duplicates": 0, "conflicts": 0, "links": 1},
    }
    # Priced accounting has nothing to attribute: the usage carries no amount.
    assert Decimal(snapshot["outcomes"]["amounts_usd"]["selected_total"]) == 0
    notional = snapshot["notional_outcomes"]
    assert Decimal(notional["amounts_usd"]["attributed"]) == Decimal("20")
    assert Decimal(notional["denominators"]["fab.job"]["cost_per_outcome_usd"]) == 20
    assert (tmp_path / FLEET_NAME / "events.db").exists()

    # Re-merging rebuilds from host stores; it is not cumulative.
    again: Any = json.loads(json.dumps(merge_fleet(tmp_path, ["spender", "runner"], since=since)))
    assert again["merge"] == snapshot["merge"]
