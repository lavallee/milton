from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from milton.activity import build_activity
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod, JoinState
from milton.errors import RecordConflictError
from milton.model import (
    CostPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SessionPayload,
    SourceRef,
    format_datetime,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def cost_event(native_id: str = "cost-1") -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("codex", native_id),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=CostPayload(
            amount_usd=Decimal("0.42"),
            input_tokens=1000,
            output_tokens=250,
            cached_input_tokens=None,
            provider="openai",
            model="example",
        ),
    )


def test_event_ingestion_is_idempotent_but_rejects_conflicts(tmp_path: Path) -> None:
    with MiltonStore(tmp_path / "events.db") as store:
        event = cost_event()
        assert store.append_event(event)
        assert not store.append_event(event)
        assert store.get_event(event.event_id) == event

        conflicting = replace(
            event,
            payload=replace(event.payload, output_tokens=251),  # type: ignore[arg-type]
        )
        with pytest.raises(RecordConflictError, match="conflicting content"):
            store.append_event(conflicting)


def test_report_accounts_for_cost_and_coverage_gaps(tmp_path: Path) -> None:
    with MiltonStore(tmp_path / "events.db") as store:
        store.append_event(cost_event())
        store.append_event(cost_event("cost-2"))
        report = store.report()

    assert report.event_count == 2
    assert report.total_cost_usd == Decimal("0.84")
    assert report.adapters["codex"].input_tokens == 2000
    assert report.adapters["codex"].gaps == {
        "cost.accounting_key:unavailable": 2,
        "cost.authority:unavailable": 2,
        "cost.cache_write_tokens:unavailable": 2,
        "cost.cached_input_tokens:unavailable": 2,
        "cost.pricing_version:unavailable": 2,
        "cost.reasoning_tokens:unavailable": 2,
    }
    assert "cost.cached_input_tokens:unavailable (2)" in report.to_text()


def test_crosswalk_refutations_are_retained(tmp_path: Path) -> None:
    asserted = CrosswalkRecord.create(
        left=ExternalIdentity("codex.session", "abc"),
        right=ExternalIdentity("git.commit", "deadbeef"),
        confidence=0.9,
        method=JoinMethod.TEMPORAL,
        evidence_event_ids=("evt_one",),
        recorded_at=NOW,
    )
    refuted = asserted.refute(
        note="human checked the commit",
        evidence_event_ids=("evt_two",),
        recorded_at=NOW + timedelta(seconds=1),
    )

    with MiltonStore(tmp_path / "events.db") as store:
        assert store.append_crosswalk(asserted)
        assert store.append_crosswalk(refuted)
        history = list(store.crosswalk_history(asserted.link_id))

    assert [item.state for item in history] == [JoinState.ASSERTED, JoinState.REFUTED]
    assert history[-1].supersedes == history[0].record_id


def test_activity_projection_traverses_george_fab_and_harness_identity(tmp_path: Path) -> None:
    george = NormalizedEvent.create(
        source=SourceRef("george", "entry-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=OutcomePayload("george.done", OutcomeStatus.SUCCEEDED, "todo-1"),
    )
    fab = NormalizedEvent.create(
        source=SourceRef("fab", "job-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=SessionPayload("widgets", None, "submitted", "codex"),
    )
    codex = NormalizedEvent.create(
        source=SourceRef("codex", "thread-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=SessionPayload("widgets", "/work/widgets", None, "codex"),
    )
    cost = NormalizedEvent.create(
        source=SourceRef("codex", "cost-thread-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=CostPayload(Decimal("0.50"), 100, 20, 5, "openai", "example"),
        session_id=codex.event_id,
    )
    george_to_fab = CrosswalkRecord.create(
        left=ExternalIdentity("george.entry", "entry-1"),
        right=ExternalIdentity("fab.job", "job-1"),
        confidence=1,
        method=JoinMethod.EXPLICIT,
        recorded_at=NOW,
    )
    fab_to_codex = CrosswalkRecord.create(
        left=ExternalIdentity("fab.job", "job-1"),
        right=ExternalIdentity("codex.session", "thread-1"),
        confidence=1,
        method=JoinMethod.EXPLICIT,
        recorded_at=NOW,
    )

    with MiltonStore(tmp_path / "events.db") as store:
        store.append_events((george, fab, codex, cost))
        store.append_crosswalk(george_to_fab)
        store.append_crosswalk(fab_to_codex)
        snapshot = build_activity(store, ExternalIdentity("george.entry", "entry-1"))

        assert snapshot.report.total_cost_usd == Decimal("0.50")
        assert snapshot.report.event_count == 4
        assert {item.namespace for item in snapshot.related_identities} == {
            "george.entry",
            "fab.job",
            "codex.session",
        }
        assert len(snapshot.links) == 2
        assert snapshot.relations == ()
        assert "Trace links:" in snapshot.to_text()

        produced = RelationRecord.create(
            subject=TypedRef("george.entry", "entry-1"),
            predicate=RelationKind.PRODUCED,
            object=TypedRef("fab.job", "job-1"),
            confidence=1,
            method=RelationMethod.EXPLICIT,
            recorded_at=NOW,
        )
        store.append_relation(produced)
        with_relation = build_activity(store, ExternalIdentity("george.entry", "entry-1"))
        assert with_relation.relations == (produced,)
        assert "Directed relations:" in with_relation.to_text()

        store.append_crosswalk(
            fab_to_codex.refute(
                note="receipt was associated with the wrong job",
                recorded_at=NOW + timedelta(seconds=1),
            )
        )
        revised = build_activity(store, ExternalIdentity("george.entry", "entry-1"))
        assert revised.report.total_cost_usd == 0
        assert {item.namespace for item in revised.related_identities} == {
            "george.entry",
            "fab.job",
        }
        assert len(revised.links) == 1


def test_event_family_finds_children_when_window_omits_parent(tmp_path: Path) -> None:
    omitted_parent_id = "evt_omitted"
    child = NormalizedEvent.create(
        source=SourceRef("fab", "terminal:job-1"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=OutcomePayload("fab.job", OutcomeStatus.SUCCEEDED, "job-1"),
        session_id=omitted_parent_id,
    )
    with MiltonStore(tmp_path / "events.db") as store:
        store.append_event(child)
        assert store.event_family((omitted_parent_id,)) == (child,)


def test_report_filters_time_and_exposes_zero_event_adapter_coverage(tmp_path: Path) -> None:
    with MiltonStore(tmp_path / "events.db") as store:
        store.append_event(cost_event("before"))
        after = replace(
            cost_event("after"),
            occurred_at=NOW + timedelta(days=1),
            recorded_at=NOW + timedelta(days=1),
        )
        store.append_event(after)
        store.record_adapter_run(
            adapter="opencode",
            status="ok",
            content_policy="metadata",
            since_at=None,
            sources_discovered=1,
            sources_read=1,
            sources_unchanged=0,
            sources_outside_window=0,
            sources_failed=0,
            source_records=0,
            malformed_records=0,
            events_inserted=0,
            crosswalks_inserted=0,
            ingested_at=format_datetime(NOW),
        )
        report = store.report(since=format_datetime(NOW + timedelta(hours=12)))

    assert report.event_count == 1
    assert report.source_coverage["opencode"].status == "ok"
    assert report.source_coverage["opencode"].sources_read == 1
    assert "opencode: ok; 1 read" in report.to_text()
