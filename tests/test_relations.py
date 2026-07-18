from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.errors import ValidationError
from milton.relations import (
    RelationDirection,
    RelationKind,
    RelationMethod,
    RelationRecord,
    TypedRef,
)
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def fab_to_somm(*, recorded_at: datetime = NOW) -> RelationRecord:
    return RelationRecord.create(
        subject=TypedRef("fab.job", "job-1"),
        predicate=RelationKind.ATTEMPT_OF,
        object=TypedRef("somm.call", "call-1"),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=("evt_two", "evt_one", "evt_one"),
        recorded_at=recorded_at,
        note="Fab recorded the delegated call identity",
    )


def test_relation_identity_and_revision_round_trip_deterministically() -> None:
    first = fab_to_somm()
    replay = fab_to_somm()

    assert first == replay
    assert first.evidence_event_ids == ("evt_one", "evt_two")
    assert RelationRecord.from_dict(first.to_dict()) == first

    reversed_relation = RelationRecord.create(
        subject=first.object,
        predicate=first.predicate,
        object=first.subject,
        confidence=1,
        method=first.method,
        recorded_at=NOW,
    )
    assert reversed_relation.relation_id != first.relation_id


def test_relation_deserialization_rejects_invalid_predicates_and_ids() -> None:
    document = fab_to_somm().to_dict()
    document["predicate"] = "depends_on"
    with pytest.raises((ValidationError, ValueError)):
        RelationRecord.from_dict(document)

    document = fab_to_somm().to_dict()
    document["relation_id"] = "rel_tampered"
    with pytest.raises(ValidationError, match="relation_id"):
        RelationRecord.from_dict(document)


def test_relation_history_rejects_stale_assertions_and_backward_revisions(
    tmp_path: Path,
) -> None:
    asserted = fab_to_somm()
    with MiltonStore(tmp_path / "events.db") as store:
        assert store.append_relation(asserted)
        assert not store.append_relation(asserted)

        stale_assertion = fab_to_somm(recorded_at=NOW + timedelta(seconds=1))
        with pytest.raises(ValidationError, match="requires new evidence"):
            store.append_relation(stale_assertion)

        backward = asserted.refute(
            note="producer withdrew the receipt",
            recorded_at=NOW - timedelta(seconds=1),
        )
        with pytest.raises(ValidationError, match="forward in time"):
            store.append_relation(backward)

        refuted = asserted.refute(
            note="producer withdrew the receipt",
            recorded_at=NOW + timedelta(seconds=1),
        )
        assert store.append_relation(refuted)
        assert list(store.relation_history(asserted.relation_id)) == [asserted, refuted]
        assert store.current_relations() == ()

        forged_reassertion = fab_to_somm(
            recorded_at=NOW + timedelta(seconds=2),
        )
        with pytest.raises(ValidationError, match="closed history"):
            store.append_relation(forged_reassertion)


def test_relation_history_retains_independent_corroborating_assertions(
    tmp_path: Path,
) -> None:
    asserted = fab_to_somm()
    corroborated = RelationRecord.create(
        subject=asserted.subject,
        predicate=asserted.predicate,
        object=asserted.object,
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=("evt_independent",),
        recorded_at=NOW - timedelta(minutes=1),
        note="A second producer asserted the same directed fact",
    )

    with MiltonStore(tmp_path / "events.db") as store:
        assert store.append_relation(asserted)
        assert store.append_relation(corroborated)
        assert list(store.relation_history(asserted.relation_id)) == [asserted, corroborated]
        assert store.current_relations() == (corroborated,)

        refuted = corroborated.refute(
            note="the shared directed fact was withdrawn",
            recorded_at=NOW + timedelta(seconds=1),
            evidence_event_ids=("evt_withdrawal",),
        )
        assert store.append_relation(refuted)
        assert store.current_relations() == ()


def test_crosswalk_and_relation_remain_separate_for_the_same_trace(tmp_path: Path) -> None:
    association = CrosswalkRecord.create(
        left=ExternalIdentity("fab.job", "job-1"),
        right=ExternalIdentity("somm.call", "call-1"),
        confidence=1,
        method=JoinMethod.EXPLICIT,
        recorded_at=NOW,
    )
    relation = fab_to_somm()

    with MiltonStore(tmp_path / "events.db") as store:
        store.append_crosswalk(association)
        store.append_relation(relation)

        assert store.current_crosswalks() == (association,)
        assert store.current_relations() == (relation,)
        assert list(store.crosswalk_history(association.link_id)) == [association]
        assert list(store.relation_history(relation.relation_id)) == [relation]


def test_relation_traversal_respects_direction_depth_and_refutation(tmp_path: Path) -> None:
    george = TypedRef("george.entry", "entry-1")
    fab = TypedRef("fab.job", "job-1")
    somm = TypedRef("somm.call", "call-1")
    george_to_fab = RelationRecord.create(
        subject=george,
        predicate=RelationKind.PRODUCED,
        object=fab,
        confidence=1,
        method=RelationMethod.EXPLICIT,
        recorded_at=NOW,
    )
    fab_to_somm_record = RelationRecord.create(
        subject=fab,
        predicate=RelationKind.PRODUCED,
        object=somm,
        confidence=1,
        method=RelationMethod.EXPLICIT,
        recorded_at=NOW,
    )

    with MiltonStore(tmp_path / "events.db") as store:
        store.append_relation(george_to_fab)
        store.append_relation(fab_to_somm_record)

        refs, records = store.traverse_relations(
            george, direction=RelationDirection.OUTGOING, max_depth=1
        )
        assert refs == (fab, george)
        assert records == (george_to_fab,)

        refs, records = store.traverse_relations(
            george, direction=RelationDirection.OUTGOING, max_depth=2
        )
        assert refs == (fab, george, somm)
        assert records == (george_to_fab, fab_to_somm_record)

        assert store.traverse_relations(
            george, direction=RelationDirection.INCOMING, max_depth=2
        ) == ((george,), ())

        store.append_relation(
            fab_to_somm_record.refute(
                note="wrong downstream call",
                recorded_at=NOW + timedelta(seconds=1),
            )
        )
        refs, records = store.traverse_relations(
            george, direction=RelationDirection.OUTGOING, max_depth=2
        )
        assert refs == (fab, george)
        assert records == (george_to_fab,)
