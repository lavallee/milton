from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from milton.cli import main
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    ModelCallPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SessionPayload,
    SourceRef,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore
from milton.tuple_evidence import (
    SCHEMA,
    OutcomeTuple,
    TupleEvidenceState,
    build_tuple_evidence,
)

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
JOB = "job-1"
ATTEMPT = "job-1:attempt:0"
CALL = "call-1"
SHA = "a" * 40


def _populate(store: MiltonStore, *, competing_commit: bool = False) -> None:
    session = NormalizedEvent.create(
        source=SourceRef("fab", JOB),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=SessionPayload("project", "/work/project", "submitted", "codex"),
    )
    call = NormalizedEvent.create(
        source=SourceRef("somm", CALL),
        occurred_at=NOW + timedelta(seconds=1),
        recorded_at=NOW + timedelta(seconds=1),
        payload=ModelCallPayload("provider", "model-1", CallStatus.SUCCEEDED, "stop"),
        attributes={"workload_id": "profile-1"},
    )
    cost = NormalizedEvent.create(
        source=SourceRef("somm", f"cost:{CALL}"),
        occurred_at=call.occurred_at,
        recorded_at=call.recorded_at,
        parent_event_id=call.event_id,
        payload=CostPayload(
            Decimal("0.25"),
            10,
            2,
            0,
            "provider",
            "model-1",
            basis=CostBasis.COMPUTED,
            kind=CostKind.MARGINAL,
            accuracy=CostAccuracy.ESTIMATED,
            authority="somm",
            accounting_key=f"somm.call={CALL}",
            accounting_key_scope=CostKeyScope.SOURCE,
            observation_role=CostObservationRole.PRODUCTION,
        ),
    )
    attempt = NormalizedEvent.create(
        source=SourceRef("fab", ATTEMPT),
        occurred_at=NOW + timedelta(seconds=2),
        recorded_at=NOW + timedelta(seconds=2),
        payload=OutcomePayload("fab.attempt", OutcomeStatus.SUCCEEDED, JOB),
        session_id=session.event_id,
        attributes={"backend": "codex"},
    )
    job = NormalizedEvent.create(
        source=SourceRef("fab", "delivery:job-1"),
        occurred_at=NOW + timedelta(seconds=3),
        recorded_at=NOW + timedelta(seconds=3),
        payload=OutcomePayload("fab.job", OutcomeStatus.SUCCEEDED, JOB),
        session_id=session.event_id,
    )
    commit = NormalizedEvent.create(
        source=SourceRef("git", f"project#{SHA}"),
        occurred_at=NOW + timedelta(seconds=4),
        recorded_at=NOW + timedelta(seconds=4),
        payload=OutcomePayload("git.commit", OutcomeStatus.SUCCEEDED, SHA),
    )
    events = [session, call, cost, attempt, job, commit]
    relations = [
        RelationRecord.create(
            subject=TypedRef("fab.attempt", ATTEMPT),
            predicate=RelationKind.PRODUCED,
            object=TypedRef("somm.call", CALL),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            recorded_at=attempt.occurred_at,
        ),
        RelationRecord.create(
            subject=TypedRef("fab.attempt", ATTEMPT),
            predicate=RelationKind.ATTEMPT_OF,
            object=TypedRef("fab.job", JOB),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            recorded_at=attempt.occurred_at,
        ),
        RelationRecord.create(
            subject=TypedRef("fab.attempt", ATTEMPT),
            predicate=RelationKind.PRODUCED,
            object=TypedRef("git.commit", SHA),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            recorded_at=commit.occurred_at,
        ),
    ]
    if competing_commit:
        other_sha = "b" * 40
        other = NormalizedEvent.create(
            source=SourceRef("git", f"project#{other_sha}"),
            occurred_at=commit.occurred_at,
            recorded_at=commit.recorded_at,
            payload=OutcomePayload("git.commit", OutcomeStatus.SUCCEEDED, other_sha),
        )
        events.append(other)
        relations.append(
            RelationRecord.create(
                subject=TypedRef("fab.attempt", ATTEMPT),
                predicate=RelationKind.PRODUCED,
                object=TypedRef("git.commit", other_sha),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                recorded_at=other.occurred_at,
            )
        )
    store.append_events(events)
    for relation in relations:
        store.append_relation(relation)


def test_tuple_snapshot_is_versioned_exact_and_evidence_only(tmp_path: Path) -> None:
    with MiltonStore(tmp_path / "store.sqlite") as store:
        _populate(store)
        snapshot = build_tuple_evidence(
            store,
            OutcomeTuple(SHA, "profile-1", "model-1", "codex"),
            since=NOW - timedelta(minutes=1),
            cutoff=NOW + timedelta(minutes=1),
            minimum_observations=1,
            generated_at=NOW + timedelta(minutes=2),
        )

    document = snapshot.to_dict()
    assert document["schema"] == SCHEMA
    assert snapshot.state is TupleEvidenceState.READY
    assert snapshot.observations == 1
    assert snapshot.attributed_observations == 1
    assert snapshot.selected_usd == Decimal("0.25")
    assert snapshot.outcome_statuses == {"succeeded": 1}
    uncertainty = document["uncertainty"]
    assert isinstance(uncertainty, dict)
    assert uncertainty["policy_effect"] == "evidence_only"
    assert snapshot.evidence[0]["relation_ids"]


def test_direct_somm_eval_receipt_binds_native_harness_to_commit(tmp_path: Path) -> None:
    call = NormalizedEvent.create(
        source=SourceRef("somm", "eval-call"),
        occurred_at=NOW,
        recorded_at=NOW,
        payload=ModelCallPayload("minimax", "MiniMax-M3", CallStatus.SUCCEEDED, "ok"),
        attributes={"workload_id": "wl-source-score", "origin": "native"},
    )
    cost = NormalizedEvent.create(
        source=SourceRef("somm", "cost:eval-call"),
        occurred_at=NOW,
        recorded_at=NOW,
        parent_event_id=call.event_id,
        payload=CostPayload(
            Decimal("0.01"),
            10,
            2,
            0,
            "minimax",
            "MiniMax-M3",
            basis=CostBasis.COMPUTED,
            kind=CostKind.MARGINAL,
            accuracy=CostAccuracy.ESTIMATED,
            authority="somm",
            accounting_key="somm.call=eval-call",
            accounting_key_scope=CostKeyScope.SOURCE,
            observation_role=CostObservationRole.PRODUCTION,
        ),
    )
    receipt = NormalizedEvent.create(
        source=SourceRef("somm", "eval-receipt:receipt-1"),
        occurred_at=NOW + timedelta(seconds=1),
        recorded_at=NOW + timedelta(seconds=1),
        payload=OutcomePayload(
            "somm.eval-receipt.dataset_run", OutcomeStatus.SUCCEEDED, "eval-call"
        ),
    )
    commit = NormalizedEvent.create(
        source=SourceRef("git", f"project#{SHA}"),
        occurred_at=NOW + timedelta(seconds=2),
        recorded_at=NOW + timedelta(seconds=2),
        payload=OutcomePayload("git.commit", OutcomeStatus.SUCCEEDED, SHA),
    )
    relations = [
        RelationRecord.create(
            subject=TypedRef("somm.eval-receipt", "eval-receipt:receipt-1"),
            predicate=RelationKind.EVALUATES,
            object=TypedRef("somm.call", "eval-call"),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            recorded_at=receipt.occurred_at,
        ),
        RelationRecord.create(
            subject=TypedRef("somm.call", "eval-call"),
            predicate=RelationKind.EVALUATES,
            object=TypedRef("git.commit", SHA),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            recorded_at=receipt.occurred_at,
        ),
    ]
    with MiltonStore(tmp_path / "direct-somm.sqlite") as store:
        store.append_events((call, cost, receipt, commit))
        for relation in relations:
            store.append_relation(relation)
        snapshot = build_tuple_evidence(
            store,
            OutcomeTuple(SHA, "wl-source-score", "MiniMax-M3", "somm"),
            cutoff=NOW + timedelta(minutes=1),
            minimum_observations=1,
        )

    assert snapshot.state is TupleEvidenceState.READY, snapshot.to_dict()
    assert snapshot.attributed_observations == 1


def test_tuple_snapshot_fails_safe_when_sparse_or_confounding(tmp_path: Path) -> None:
    with MiltonStore(tmp_path / "sparse.sqlite") as store:
        _populate(store)
        sparse = build_tuple_evidence(
            store,
            OutcomeTuple(SHA, "profile-1", "model-1", "codex"),
            cutoff=NOW + timedelta(minutes=1),
            minimum_observations=2,
        )
    assert sparse.state is TupleEvidenceState.SPARSE

    with MiltonStore(tmp_path / "confounded.sqlite") as store:
        _populate(store, competing_commit=True)
        confounded = build_tuple_evidence(
            store,
            OutcomeTuple(SHA, "profile-1", "model-1", "codex"),
            cutoff=NOW + timedelta(minutes=1),
            minimum_observations=1,
        )
    assert confounded.state is TupleEvidenceState.CONFOUNDED
    assert confounded.ambiguous_observations == 1


def test_tuple_snapshot_is_unavailable_without_exact_tuple(tmp_path: Path) -> None:
    with MiltonStore(tmp_path / "store.sqlite") as store:
        _populate(store)
        snapshot = build_tuple_evidence(
            store,
            OutcomeTuple(SHA, "other-profile", "model-1", "codex"),
            cutoff=NOW + timedelta(minutes=1),
            minimum_observations=1,
        )
    assert snapshot.state is TupleEvidenceState.UNAVAILABLE
    assert snapshot.observations == 0


def test_tuple_snapshot_cli_exports_consumer_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "store.sqlite"
    with MiltonStore(path) as store:
        _populate(store)
    assert (
        main(
            [
                "evidence",
                "export-tuple",
                "--store",
                str(path),
                "--implementation",
                SHA,
                "--profile",
                "profile-1",
                "--served-model",
                "model-1",
                "--harness",
                "codex",
                "--cutoff",
                (NOW + timedelta(minutes=1)).isoformat(),
                "--minimum-observations",
                "1",
            ]
        )
        == 0
    )
    assert f'"schema":"{SCHEMA}"' in capsys.readouterr().out
