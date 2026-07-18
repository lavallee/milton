from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from milton.accounting import select_cost_events
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
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
    SourceRef,
    format_datetime,
)
from milton.outcomes import AttributionReason, AttributionState, build_outcome_attribution
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def model_call(call_id: str, *, offset: int = 0) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("somm", call_id),
        occurred_at=NOW + timedelta(seconds=offset),
        recorded_at=NOW + timedelta(seconds=offset),
        payload=ModelCallPayload("provider", "model", CallStatus.SUCCEEDED, "stop"),
    )


def cost(
    call: NormalizedEvent,
    amount: str,
    *,
    native_id: str | None = None,
    key: str | None = None,
    basis: CostBasis = CostBasis.COMPUTED,
    accuracy: CostAccuracy = CostAccuracy.ESTIMATED,
    kind: CostKind = CostKind.MARGINAL,
    role: CostObservationRole = CostObservationRole.PRODUCTION,
) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("somm", native_id or f"cost:{call.source.native_id}"),
        occurred_at=call.occurred_at,
        recorded_at=call.recorded_at,
        parent_event_id=call.event_id,
        payload=CostPayload(
            Decimal(amount),
            10,
            2,
            0,
            "provider",
            "model",
            basis=basis,
            kind=kind,
            accuracy=accuracy,
            authority="somm",
            accounting_key=key or f"somm.call={call.source.native_id}",
            accounting_key_scope=(CostKeyScope.SHARED if key else CostKeyScope.SOURCE),
            observation_role=role,
        ),
    )


def fab_outcome(job_id: str, *, status: OutcomeStatus = OutcomeStatus.SUCCEEDED) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("fab", f"terminal:{job_id}"),
        occurred_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
        payload=OutcomePayload("fab.job", status, job_id),
    )


def git_outcome(sha: str) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("git", f"/work/repo#{sha}"),
        occurred_at=NOW + timedelta(minutes=2),
        recorded_at=NOW + timedelta(minutes=2),
        payload=OutcomePayload("git.commit", OutcomeStatus.SUCCEEDED, sha),
    )


def george_outcome(entry_id: str) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("george", entry_id),
        occurred_at=NOW + timedelta(minutes=2),
        recorded_at=NOW + timedelta(minutes=2),
        payload=OutcomePayload("george.done", OutcomeStatus.SUCCEEDED, None),
    )


def produced(subject: TypedRef, object: TypedRef, *, offset: int = 0) -> RelationRecord:
    return RelationRecord.create(
        subject=subject,
        predicate=RelationKind.PRODUCED,
        object=object,
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        recorded_at=NOW + timedelta(seconds=offset),
    )


@pytest.mark.parametrize(
    ("attributed_amount", "ambiguous_amount", "association_amount", "rootless_amount"),
    [
        ("1", "2", "3", "4"),
        ("0.01", "0.02", "0.03", "0.04"),
        ("10.25", "0", "7.125", "2.625"),
    ],
)
def test_mixed_projection_conserves_every_selected_amount(
    attributed_amount: str,
    ambiguous_amount: str,
    association_amount: str,
    rootless_amount: str,
) -> None:
    attributed_call = model_call("call-attributed")
    ambiguous_call = model_call("call-ambiguous", offset=1)
    association_call = model_call("call-association", offset=2)
    rootless_call = model_call("call-rootless", offset=3)
    costs = (
        cost(attributed_call, attributed_amount),
        cost(ambiguous_call, ambiguous_amount),
        cost(association_call, association_amount),
        NormalizedEvent.create(
            source=SourceRef("somm", "cost:rootless"),
            occurred_at=rootless_call.occurred_at,
            recorded_at=rootless_call.recorded_at,
            payload=CostPayload(
                Decimal(rootless_amount),
                1,
                1,
                0,
                "provider",
                "model",
                observation_role=CostObservationRole.PRODUCTION,
            ),
        ),
    )
    outcomes = (
        fab_outcome("job-attributed"),
        git_outcome("sha-a"),
        git_outcome("sha-b"),
        fab_outcome("job-association"),
    )
    relations = (
        produced(TypedRef("fab.job", "job-attributed"), TypedRef("somm.call", "call-attributed")),
        produced(TypedRef("fab.job", "job-ambiguous"), TypedRef("somm.call", "call-ambiguous")),
        produced(TypedRef("fab.job", "job-ambiguous"), TypedRef("git.commit", "sha-a")),
        produced(TypedRef("fab.job", "job-ambiguous"), TypedRef("git.commit", "sha-b")),
    )
    association = CrosswalkRecord.create(
        left=ExternalIdentity("somm.call", "call-association"),
        right=ExternalIdentity("fab.job", "job-association"),
        confidence=1,
        method=JoinMethod.EXPLICIT,
        recorded_at=NOW,
    )

    projection = build_outcome_attribution(
        (*costs, attributed_call, ambiguous_call, association_call, rootless_call, *outcomes),
        (association,),
        relations,
    )

    expected = sum((Decimal(item) for item in costs_amounts(costs)), Decimal(0))
    assert projection.selected_total_usd == expected
    assert projection.attributed_total_usd == Decimal(attributed_amount)
    assert projection.ambiguous_total_usd == Decimal(ambiguous_amount)
    assert projection.unallocated_total_usd == Decimal(association_amount) + Decimal(
        rootless_amount
    )
    assert projection.selected_total_usd == (
        projection.attributed_total_usd
        + projection.ambiguous_total_usd
        + projection.unallocated_total_usd
    )
    assert [record.state for record in projection.records] == [
        AttributionState.ATTRIBUTED,
        AttributionState.AMBIGUOUS,
        AttributionState.UNALLOCATED,
        AttributionState.UNALLOCATED,
    ]
    assert {record.reason for record in projection.records} >= {
        AttributionReason.EXACT_DIRECTED_PATH,
        AttributionReason.COMPETING_OUTCOMES,
        AttributionReason.ASSOCIATION_ONLY,
        AttributionReason.NO_ROOT_REFERENCE,
    }


def costs_amounts(costs: tuple[NormalizedEvent, ...]) -> tuple[str, ...]:
    return tuple(
        str(event.payload.amount_usd)
        for event in costs
        if isinstance(event.payload, CostPayload) and event.payload.amount_usd is not None
    )


def test_exact_precedence_selects_git_and_records_every_path_id() -> None:
    call = model_call("call-1")
    cost_event = cost(call, "1.25")
    fab = fab_outcome("job-1")
    george = george_outcome("entry-1")
    git = git_outcome("abc123")
    fab_to_call = produced(TypedRef("fab.job", "job-1"), TypedRef("somm.call", "call-1"))
    george_to_fab = RelationRecord.create(
        subject=TypedRef("george.entry", "entry-1"),
        predicate=RelationKind.VERIFIES,
        object=TypedRef("fab.job", "job-1"),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=(george.event_id,),
        recorded_at=NOW,
    )
    fab_to_git = produced(TypedRef("fab.job", "job-1"), TypedRef("git.commit", "abc123"))

    projection = build_outcome_attribution(
        (call, cost_event, fab, george, git),
        (),
        (fab_to_call, george_to_fab, fab_to_git),
    )

    record = projection.records[0]
    assert record.state is AttributionState.ATTRIBUTED
    assert record.source_adapter == "somm"
    assert record.source_native_id == "cost:call-1"
    assert record.authority == "somm"
    assert record.accounting_key == "somm.call=call-1"
    assert record.accounting_key_scope == "source"
    assert record.observation_role == "production"
    assert record.outcome is not None
    assert record.outcome.outcome_type == "git.commit"
    assert record.path is not None
    assert record.path.relation_ids == tuple(
        sorted((fab_to_call.relation_id, fab_to_git.relation_id))
    )
    assert record.path.relation_record_ids == tuple(
        sorted((fab_to_call.record_id, fab_to_git.record_id))
    )
    assert {cost_event.event_id, call.event_id, git.event_id} <= set(record.path.event_ids)
    assert {candidate.candidate.outcome_type for candidate in record.candidates} == {
        "fab.job",
        "george.entry",
        "git.commit",
    }


def test_accounting_winner_and_rollup_exclusion_carry_through_once() -> None:
    call = model_call("call-1")
    computed = cost(
        call,
        "1.00",
        native_id="computed",
        key="provider.request=req-1",
        basis=CostBasis.COMPUTED,
        accuracy=CostAccuracy.ESTIMATED,
    )
    reported = cost(
        call,
        "1.10",
        native_id="reported",
        key="provider.request=req-1",
        basis=CostBasis.REPORTED,
        accuracy=CostAccuracy.ACTUAL,
    )
    rollup = cost(
        call,
        "9.99",
        native_id="rollup",
        key="rollup=one",
        role=CostObservationRole.ROLLUP,
    )
    relation = produced(TypedRef("fab.job", "job-1"), TypedRef("somm.call", "call-1"))

    projection = build_outcome_attribution(
        (call, computed, reported, rollup, fab_outcome("job-1")),
        (),
        (relation,),
    )

    assert select_cost_events((computed, reported, rollup)) == (reported,)
    assert projection.accounting.rollup_events == 1
    assert projection.accounting.suppressed_observations == 1
    assert projection.selected_total_usd == Decimal("1.10")
    assert len(projection.records) == 1
    assert projection.outcomes[0].amount_usd == Decimal("1.10")
    assert projection.outcomes[0].observations == 1


@pytest.mark.parametrize(
    "status",
    (OutcomeStatus.FAILED, OutcomeStatus.REVERTED, OutcomeStatus.ABANDONED),
)
def test_failed_and_reverted_runner_outcomes_remain_attributable(
    status: OutcomeStatus,
) -> None:
    call = model_call(f"call-{status.value}")
    job_id = f"job-{status.value}"
    relation = produced(TypedRef("fab.job", job_id), TypedRef("somm.call", call.source.native_id))
    projection = build_outcome_attribution(
        (call, cost(call, "0.50"), fab_outcome(job_id, status=status)),
        (),
        (relation,),
    )

    assert projection.attributed_total_usd == Decimal("0.50")
    assert projection.outcomes[0].status == status.value


def test_inverted_relation_direction_abstains_even_when_endpoints_are_reachable() -> None:
    call = model_call("call-inverted")
    inverted = produced(
        TypedRef("somm.call", "call-inverted"),
        TypedRef("fab.job", "job-inverted"),
    )
    projection = build_outcome_attribution(
        (call, cost(call, "0.50"), fab_outcome("job-inverted")),
        (),
        (inverted,),
    )

    assert projection.unallocated_total_usd == Decimal("0.50")
    assert projection.records[0].reason is AttributionReason.ASSOCIATION_ONLY


def test_economic_kinds_stay_separate_for_one_outcome() -> None:
    call = model_call("call-kinds")
    marginal = cost(
        call,
        "1.00",
        native_id="marginal",
        key="request=one",
        kind=CostKind.MARGINAL,
    )
    notional = cost(
        call,
        "4.00",
        native_id="notional",
        key="request=one",
        kind=CostKind.NOTIONAL,
    )
    relation = produced(TypedRef("fab.job", "job-1"), TypedRef("somm.call", "call-kinds"))
    projection = build_outcome_attribution(
        (call, marginal, notional, fab_outcome("job-1")),
        (),
        (relation,),
    )

    assert projection.selected_total_usd == Decimal("5.00")
    assert {(item.economic_kind, item.amount_usd) for item in projection.outcomes} == {
        ("marginal", Decimal("1.00")),
        ("notional", Decimal("4.00")),
    }


def test_relation_replay_and_refutation_change_current_projection(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    call = model_call("call-refuted")
    cost_event = cost(call, "0.75")
    outcome = fab_outcome("job-refuted")
    relation = produced(TypedRef("fab.job", "job-refuted"), TypedRef("somm.call", "call-refuted"))
    with MiltonStore(path) as store:
        store.append_events((call, cost_event, outcome))
        assert store.append_relation(relation)
        assert not store.append_relation(relation)
        before = store.outcome_attribution()
        store.append_relation(
            relation.refute(
                note="producer withdrew the work receipt",
                recorded_at=NOW + timedelta(seconds=1),
            )
        )
        after = store.outcome_attribution()

    assert before.attributed_total_usd == Decimal("0.75")
    assert after.unallocated_total_usd == Decimal("0.75")
    assert after.records[0].reason is AttributionReason.NO_OUTCOME_PATH


def test_store_time_window_is_exclusive_and_conserves_selected_subset(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    before_call = model_call("call-before")
    after_call = model_call("call-after", offset=86_400)
    before_cost = cost(before_call, "1.00")
    after_cost = cost(after_call, "2.00")
    before_outcome = fab_outcome("job-before")
    after_outcome = NormalizedEvent.create(
        source=SourceRef("fab", "terminal:job-after"),
        occurred_at=NOW + timedelta(days=1, minutes=1),
        recorded_at=NOW + timedelta(days=1, minutes=1),
        payload=OutcomePayload("fab.job", OutcomeStatus.SUCCEEDED, "job-after"),
    )
    relations = (
        produced(TypedRef("fab.job", "job-before"), TypedRef("somm.call", "call-before")),
        produced(TypedRef("fab.job", "job-after"), TypedRef("somm.call", "call-after")),
    )
    with MiltonStore(path) as store:
        store.append_events(
            (before_call, after_call, before_cost, after_cost, before_outcome, after_outcome)
        )
        for relation in relations:
            store.append_relation(relation)
        projection = store.outcome_attribution(
            since=format_datetime(NOW + timedelta(hours=12)),
            until=format_datetime(NOW + timedelta(days=2)),
        )

    assert projection.selected_total_usd == Decimal("2.00")
    assert projection.attributed_total_usd == Decimal("2.00")
    assert [record.cost_event_id for record in projection.records] == [after_cost.event_id]
