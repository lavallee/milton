from __future__ import annotations

import builtins
import copy
import json
import sqlite3
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from milton.adapters import (
    BUILTIN_ADAPTERS,
    BarnowlResearchOutcomeAdapter,
    ContentPolicy,
    SommAdapter,
)
from milton.adapters.base import AdapterRecord
from milton.crosswalk import CrosswalkRecord
from milton.ingest import Ingestor
from milton.model import ModelCallPayload, NormalizedEvent, OutcomePayload, OutcomeStatus
from milton.outcomes import OUTCOME_PRECEDENCE, AttributionState
from milton.relations import RelationKind, RelationMethod, RelationRecord
from milton.store import MiltonStore

FIXTURES = Path(__file__).parent / "fixtures" / "barnowl_research_outcome"
OUTCOMES = FIXTURES / "research-outcomes.jsonl"
SOMM_SQL = FIXTURES / "somm.sql"
JUDGED_EVENT_ID = "11111111-1111-4111-8111-111111111111"
ERROR_EVENT_ID = "22222222-2222-4222-8222-222222222222"


def _events(records: Iterable[AdapterRecord]) -> list[NormalizedEvent]:
    return [record for record in records if isinstance(record, NormalizedEvent)]


def _fixture_events() -> list[dict[str, Any]]:
    return [json.loads(line) for line in OUTCOMES.read_text(encoding="utf-8").splitlines()]


def _materialize_somm(tmp_path: Path) -> Path:
    path = tmp_path / "somm.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(SOMM_SQL.read_text(encoding="utf-8"))
    connection.commit()
    connection.close()
    return path


def test_adapter_requires_explicit_jsonl_and_discovers_deterministically(tmp_path: Path) -> None:
    adapter = BarnowlResearchOutcomeAdapter()
    assert adapter.default_roots() == ()
    assert list(adapter.discover(adapter.default_roots())) == []
    assert BUILTIN_ADAPTERS[adapter.name] is BarnowlResearchOutcomeAdapter

    direct = tmp_path / "z.jsonl"
    direct.write_text("{}\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    earlier = nested / "a.jsonl"
    earlier.write_text("{}\n", encoding="utf-8")
    (tmp_path / "ignored.json").write_text("{}\n", encoding="utf-8")

    discovered = list(adapter.discover((direct, tmp_path, earlier)))
    assert discovered == sorted((direct, earlier), key=lambda item: str(item.resolve()))


def test_valid_fixture_is_metadata_only_and_does_not_import_barnowl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def reject_barnowl_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "barnowl" or name.startswith("barnowl."):
            raise AssertionError("adapter imported Barnowl")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_barnowl_import)
    adapter = BarnowlResearchOutcomeAdapter()
    metadata_read = adapter.read(OUTCOMES)
    metadata_records = list(metadata_read.records)
    full_records = list(adapter.read(OUTCOMES, content_policy=ContentPolicy.FULL).records)

    assert [record.to_dict() for record in metadata_records] == [
        record.to_dict() for record in full_records
    ]
    events = _events(metadata_records)
    assert [event.source.native_id for event in events] == [JUDGED_EVENT_ID, ERROR_EVENT_ID]
    assert [event.payload for event in events] == [
        OutcomePayload("barnowl.research-outcome", OutcomeStatus.SUCCEEDED, JUDGED_EVENT_ID),
        OutcomePayload("barnowl.research-outcome", OutcomeStatus.FAILED, ERROR_EVENT_ID),
    ]
    assert events[0].attributes["somm_calls"] == [
        {
            "vote_index": 1,
            "call_id": "fixture-call-1",
            "served_provider": "fixture-provider-a",
            "served_model": "fixture-model-a",
        },
        {
            "vote_index": 2,
            "call_id": "fixture-call-2",
            "served_provider": "fixture-provider-b",
            "served_model": "fixture-model-b",
        },
    ]
    assert events[0].attributes["correlation"] == {
        "namespace": "somm.correlation",
        "correlation_id": "correlation-retry-1",
    }
    assert "content" not in json.dumps([event.to_dict() for event in events])

    receipt_relations = [
        record
        for record in metadata_records
        if isinstance(record, RelationRecord) and record.predicate is RelationKind.PRODUCED
    ]
    assert [(record.subject.namespace, record.subject.value) for record in receipt_relations] == [
        ("somm.call", "fixture-call-1"),
        ("somm.call", "fixture-call-2"),
    ]
    assert all(
        record.object.namespace == "barnowl.research-outcome" for record in receipt_relations
    )
    assert all(record.object.value == JUDGED_EVENT_ID for record in receipt_relations)
    assert all(record.method is RelationMethod.SOURCE_RECEIPT for record in receipt_relations)
    assert all(record.evidence_event_ids == (events[0].event_id,) for record in receipt_relations)
    assert len([record for record in metadata_records if isinstance(record, CrosswalkRecord)]) == 2
    assert metadata_read.stats.malformed_records == 0


def test_invalid_lines_are_diagnosed_independently_without_suppressing_neighbors(
    tmp_path: Path,
) -> None:
    judged, error = _fixture_events()

    unknown = copy.deepcopy(judged)
    unknown["authority"]["extra"] = "not allowed"

    forbidden_telemetry = copy.deepcopy(judged)
    forbidden_telemetry["authority"]["cost_usd"] = "not allowed"

    forbidden_content = copy.deepcopy(judged)
    forbidden_content["authority"]["prompt_body"] = "not allowed"

    malformed_coordinate = copy.deepcopy(judged)
    malformed_coordinate["attempt"]["attempt_id"] = " padded"

    duplicate_vote = copy.deepcopy(judged)
    duplicate_vote["somm_calls"][1]["vote_index"] = 1

    duplicate_call = copy.deepcopy(judged)
    duplicate_call["somm_calls"][1]["call_id"] = "fixture-call-1"

    source = tmp_path / "mixed.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps(judged),
                json.dumps(unknown),
                json.dumps(forbidden_telemetry),
                json.dumps(forbidden_content),
                json.dumps(malformed_coordinate),
                json.dumps(duplicate_vote),
                json.dumps(duplicate_call),
                "{not json",
                json.dumps(error),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    read = BarnowlResearchOutcomeAdapter().read(source)
    records = list(read.records)
    assert [event.source.native_id for event in _events(records)] == [
        JUDGED_EVENT_ID,
        ERROR_EVENT_ID,
    ]
    assert read.stats.source_records == 9
    assert read.stats.malformed_records == 7
    assert [(item.line, item.code) for item in read.stats.diagnostics] == [
        (2, "unknown-field"),
        (3, "forbidden-field"),
        (4, "forbidden-field"),
        (5, "invalid-coordinate"),
        (6, "invalid-call-coordinate"),
        (7, "duplicate-call-id"),
        (8, "malformed-jsonl"),
    ]


@pytest.mark.parametrize(
    ("coordinate", "value"),
    [
        (("event_id",), "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        (("occurred_at",), "2026-07-18T12:00:00+00:00"),
        (("prompt_coordinate", "prompt_sha256"), "B" * 64),
    ],
)
def test_uuid_timestamp_and_digest_coordinates_must_be_canonical(
    tmp_path: Path,
    coordinate: tuple[str, ...],
    value: str,
) -> None:
    judged = _fixture_events()[0]
    target: dict[str, Any] = judged
    for field in coordinate[:-1]:
        target = target[field]
    target[coordinate[-1]] = value
    source = tmp_path / "noncanonical.jsonl"
    source.write_text(json.dumps(judged) + "\n", encoding="utf-8")

    read = BarnowlResearchOutcomeAdapter().read(source)
    assert list(read.records) == []
    assert [(item.line, item.code) for item in read.stats.diagnostics] == [
        (1, "invalid-coordinate")
    ]


def test_exact_receipt_paths_are_idempotent_and_conserve_matching_somm_cost(
    tmp_path: Path,
) -> None:
    somm_path = _materialize_somm(tmp_path)
    store_path = tmp_path / "milton.sqlite"

    with MiltonStore(store_path) as store:
        first = Ingestor(store).run(
            (SommAdapter(), BarnowlResearchOutcomeAdapter()),
            roots={"somm": (somm_path,), "barnowl-research-outcome": (OUTCOMES,)},
            force=True,
        )
        second = Ingestor(store).run(
            (SommAdapter(), BarnowlResearchOutcomeAdapter()),
            roots={"somm": (somm_path,), "barnowl-research-outcome": (OUTCOMES,)},
            force=True,
        )
        projection = store.outcome_attribution(outcome_types=("barnowl.research-outcome",))
        barnowl_events = tuple(store.events(adapter="barnowl-research-outcome"))
        somm_events = tuple(store.events(adapter="somm"))
        relations = store.current_relations()

    first_barnowl = next(
        item for item in first.adapters if item.adapter == "barnowl-research-outcome"
    )
    second_barnowl = next(
        item for item in second.adapters if item.adapter == "barnowl-research-outcome"
    )
    assert (first_barnowl.events_inserted, first_barnowl.relations_inserted) == (2, 6)
    assert first_barnowl.crosswalks_inserted == 2
    assert second_barnowl.events_inserted == 0
    assert second_barnowl.relations_inserted == 0
    assert second_barnowl.crosswalks_inserted == 0
    assert second_barnowl.replayed == 10

    calls = [
        payload for event in somm_events if isinstance((payload := event.payload), ModelCallPayload)
    ]
    assert [(call.provider, call.model) for call in calls] == [
        ("fixture-provider-a", "fixture-model-a"),
        ("fixture-provider-b", "fixture-model-b"),
    ]
    judged = next(event for event in barnowl_events if event.source.native_id == JUDGED_EVENT_ID)
    assert judged.attributes["attempt"] == {
        "namespace": "fixture.barnowl-attempt",
        "attempt_id": "attempt-retry-1",
    }
    assert judged.attributes["correlation"] == {
        "namespace": "somm.correlation",
        "correlation_id": "correlation-retry-1",
    }

    exact_relations = [
        relation
        for relation in relations
        if relation.predicate is RelationKind.PRODUCED
        and relation.object.namespace == "barnowl.research-outcome"
    ]
    assert {relation.subject.value for relation in exact_relations} == {
        "fixture-call-1",
        "fixture-call-2",
    }
    assert {relation.object.value for relation in exact_relations} == {JUDGED_EVENT_ID}

    assert OUTCOME_PRECEDENCE[:4] == (
        "git.commit",
        "george.entry",
        "fab.job",
        "fab.attempt",
    )
    assert OUTCOME_PRECEDENCE[-1] == "barnowl.research-outcome"
    assert projection.selected_total_usd == Decimal("0.30")
    assert projection.attributed_total_usd == Decimal("0.30")
    assert projection.ambiguous_total_usd == Decimal(0)
    assert projection.unallocated_total_usd == Decimal(0)
    assert projection.selected_total_usd == (
        projection.attributed_total_usd
        + projection.ambiguous_total_usd
        + projection.unallocated_total_usd
    )
    assert len(projection.records) == 2
    assert all(record.state is AttributionState.ATTRIBUTED for record in projection.records)
    assert all(record.outcome is not None for record in projection.records)
    assert all(
        record.outcome is not None and record.outcome.reference.value == JUDGED_EVENT_ID
        for record in projection.records
    )
    assert all(
        record.path is not None and len(record.path.steps) == 1 for record in projection.records
    )
    assert all(
        record.path is not None
        and record.path.steps[0].predicate == RelationKind.PRODUCED.value
        and record.path.steps[0].direction == "forward"
        for record in projection.records
    )
    assert len(projection.outcomes) == 1
    assert projection.outcomes[0].amount_usd == Decimal("0.30")
    assert projection.outcomes[0].observations == 2
