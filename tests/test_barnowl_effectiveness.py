from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from milton.barnowl_effectiveness import build_barnowl_effectiveness
from milton.cli import main
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.errors import ValidationError
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    JsonValue,
    ModelCallPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
    canonical_json,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _document(value: dict[str, JsonValue]) -> dict[str, Any]:
    return cast(dict[str, Any], value)


def _receipt(
    coordinate: str,
    offset: int,
    *,
    judgment: str | None = None,
    error_kind: str | None = None,
    calls: tuple[str | None, ...] = (),
    predecessor: str | None = None,
    domain: tuple[str, str, str] = ("fixture.domain", "claim", "private-object"),
    treatment: tuple[str, str] = ("fixture.treatment", HASH_A),
    workload: str = "fixture-workload",
    attempt: str | None = None,
) -> NormalizedEvent:
    if (judgment is None) == (error_kind is None):
        raise AssertionError("receipt needs exactly one judgment or error kind")
    outcome = (
        {"kind": "judged", "judgment": judgment}
        if judgment is not None
        else {"kind": "error", "error_kind": error_kind}
    )
    attributes: dict[str, object] = {
        "workload": workload,
        "attempt": {
            "namespace": "fixture.attempt",
            "attempt_id": attempt or f"private-attempt-{coordinate}",
        },
        "correlation": {
            "namespace": "fixture.correlation",
            "correlation_id": f"private-correlation-{coordinate}",
        },
        "somm_calls": [
            {
                "vote_index": index,
                "call_id": call_id,
                "served_provider": "private-provider",
                "served_model": "private-model",
            }
            for index, call_id in enumerate(calls, 1)
        ],
        "treatment_manifest": {
            "namespace": treatment[0],
            "manifest_sha256": treatment[1],
        },
        "prompt_coordinate": {
            "namespace": "fixture.prompt",
            "prompt_id": f"private-prompt-{coordinate}",
            "prompt_sha256": "c" * 64,
        },
        "domain_object": {
            "namespace": domain[0],
            "object_type": domain[1],
            "object_id": domain[2],
        },
        "outcome": outcome,
        "authority": {
            "namespace": "fixture.authority",
            "authority_id": f"private-authority-{coordinate}",
        },
        "private_extension": {"body": f"PRIVATE_BODY_{coordinate}"},
    }
    if predecessor is not None:
        attributes["supersedes_event_id"] = predecessor
    occurred_at = NOW + timedelta(seconds=offset)
    return NormalizedEvent.create(
        source=SourceRef(
            "barnowl-research-outcome",
            coordinate,
            f"/private/source/{coordinate}.jsonl",
        ),
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        payload=OutcomePayload(
            BARNOWL_OUTCOME_TYPE,
            OutcomeStatus.SUCCEEDED if judgment is not None else OutcomeStatus.FAILED,
            coordinate,
        ),
        attributes=cast(dict[str, JsonValue], attributes),
    )


BARNOWL_OUTCOME_TYPE = "barnowl.research-outcome"


def _call_and_cost(
    call_id: str,
    offset: int,
    amount: str,
    *,
    adapter: str = "somm",
) -> tuple[NormalizedEvent, NormalizedEvent]:
    occurred_at = NOW + timedelta(seconds=offset)
    call = NormalizedEvent.create(
        source=SourceRef(adapter, call_id, "/private/somm.sqlite"),
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        payload=ModelCallPayload(
            "private-provider",
            "private-model",
            CallStatus.SUCCEEDED,
            "private-finish-reason",
        ),
    )
    cost = NormalizedEvent.create(
        source=SourceRef(adapter, f"private-cost-{call_id}", "/private/somm.sqlite"),
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        parent_event_id=call.event_id,
        payload=CostPayload(
            Decimal(amount),
            10,
            2,
            0,
            "private-provider",
            "private-model",
            basis=CostBasis.COMPUTED,
            kind=CostKind.MARGINAL,
            accuracy=CostAccuracy.ESTIMATED,
            authority="somm",
            accounting_key=f"somm.call={call_id}",
            accounting_key_scope=CostKeyScope.SOURCE,
            observation_role=CostObservationRole.PRODUCTION,
        ),
    )
    return call, cost


def _exact_relation(call_id: str, receipt: NormalizedEvent) -> RelationRecord:
    payload = receipt.payload
    assert isinstance(payload, OutcomePayload)
    return RelationRecord.create(
        subject=TypedRef("somm.call", call_id),
        predicate=RelationKind.PRODUCED,
        object=TypedRef(BARNOWL_OUTCOME_TYPE, str(payload.reference)),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=(receipt.event_id,),
        recorded_at=receipt.occurred_at,
    )


def _materialize(
    path: Path,
    events: tuple[NormalizedEvent, ...],
    relations: tuple[RelationRecord, ...] = (),
    crosswalks: tuple[CrosswalkRecord, ...] = (),
) -> None:
    with MiltonStore(path) as store:
        store.append_events(events)
        for relation in relations:
            store.append_relation(relation)
        for crosswalk in crosswalks:
            store.append_crosswalk(crosswalk)


def test_standardized_funnel_and_aggregate_dimensions_are_exact_and_eligible() -> None:
    admitted = _receipt("receipt-admitted", 10, judgment="ADMITTED", calls=("call-a",))
    corroborated = _receipt(
        "receipt-corroborated",
        20,
        judgment="CORROBORATED",
        calls=("call-b",),
        predecessor="receipt-admitted",
    )
    rejected = _receipt(
        "receipt-rejected",
        30,
        judgment="REJECTED",
        calls=("call-c",),
        domain=("fixture.domain", "claim", "private-rejected-object"),
        treatment=("fixture.treatment", HASH_B),
        workload="second-workload",
    )
    error = _receipt(
        "receipt-error",
        40,
        error_kind="transport_error",
        calls=(None,),
        domain=("fixture.domain", "claim", "private-error-object"),
        treatment=("fixture.treatment", HASH_B),
        workload="second-workload",
    )
    call_a, cost_a = _call_and_cost("call-a", 9, "1.10")
    call_b, cost_b = _call_and_cost("call-b", 19, "2.20")
    call_c, cost_c = _call_and_cost("call-c", 29, "3.30")
    relations = (
        _exact_relation("call-a", admitted),
        _exact_relation("call-b", corroborated),
        _exact_relation("call-c", rejected),
    )

    projection = build_barnowl_effectiveness(
        (admitted, corroborated, rejected, error, call_a, cost_a, call_b, cost_b, call_c, cost_c),
        (),
        relations,
        join_coverage_threshold=Decimal("1"),
    )
    document = _document(projection.to_dict())
    coverage = document["receipt_coordinate_coverage"]
    allocation = document["selected_window_allocation"]
    funnel = document["semantic_funnel"]
    assert isinstance(coverage, dict)
    assert isinstance(allocation, dict)
    assert isinstance(funnel, dict)

    assert coverage == {
        "total_call_slots": 4,
        "null_call_ids": 1,
        "non_null_call_id_occurrences": 3,
        "distinct_call_ids": 3,
        "duplicate_call_ids_across_receipts": 0,
        "duplicate_call_id_occurrences": 0,
        "exact_selected_cost_observations_joined": 3,
        "receipt_call_id_occurrences_exactly_joined": 3,
        "receipt_call_id_occurrences_without_selected_cost": 0,
        "distinct_receipt_call_ids_without_selected_cost": 0,
        "exact_join_percentage": "100",
    }
    assert allocation["amounts_usd"] == {
        "selected": "6.60",
        "attributed": {"amount": "6.60", "percentage": "100"},
        "ambiguous": {"amount": "0", "percentage": "0"},
        "unallocated": {"amount": "0", "percentage": "0"},
    }
    assert funnel["valid_domain_chains"] == 3
    assert funnel["chains_containing_admitted"] == 1
    assert funnel["later_corroborated_chains"] == 1
    assert funnel["terminal_rejected_chains"] == 1
    assert funnel["terminal_error_chains"] == 1
    assert funnel["admitted_chain_cost_usd"] == "3.30"
    assert funnel["cost_per_admitted_result_usd"] == "3.30"
    assert funnel["cost_per_later_corroborated_result_usd"] == "3.30"
    assert document["semantic_effectiveness"] == {"status": "eligible", "reasons": ["eligible"]}

    dimensions = document["raw_outcome_dimensions"]
    workloads = document["workload_groups"]
    treatments = document["treatment_groups"]
    assert isinstance(dimensions, list) and len(dimensions) == 4
    assert isinstance(workloads, list) and len(workloads) == 2
    assert isinstance(treatments, list) and len(treatments) == 2
    second = next(
        row for row in workloads if isinstance(row, dict) and row["workload"] == "second-workload"
    )
    assert second["receipt_outcomes"] == 2
    assert second["raw_yields"]["REJECTED"]["percentage"] == "50"
    assert second["raw_yields"]["error"]["percentage"] == "50"


def test_unmapped_labels_never_become_semantic_successes() -> None:
    evidenced = _receipt("receipt-evidenced", 10, judgment="EVIDENCED", calls=("call-e",))
    partial = _receipt(
        "receipt-partial",
        20,
        judgment="PARTIAL",
        calls=("call-p",),
        domain=("fixture.domain", "claim", "private-p"),
    )
    unanswered = _receipt(
        "receipt-unanswered",
        30,
        judgment="UNANSWERED",
        calls=("call-u",),
        domain=("fixture.domain", "claim", "private-u"),
    )
    verified = _receipt(
        "receipt-verified",
        40,
        judgment="verified",
        calls=("call-v",),
        domain=("fixture.domain", "claim", "private-v"),
    )
    calls_and_costs = tuple(
        item
        for call_id, offset in (("call-e", 9), ("call-p", 19), ("call-u", 29), ("call-v", 39))
        for item in _call_and_cost(call_id, offset, "0.25")
    )
    relations = tuple(
        _exact_relation(call_id, receipt)
        for call_id, receipt in (
            ("call-e", evidenced),
            ("call-p", partial),
            ("call-u", unanswered),
            ("call-v", verified),
        )
    )

    document = _document(
        build_barnowl_effectiveness(
            (evidenced, partial, unanswered, verified, *calls_and_costs), (), relations
        ).to_dict()
    )
    funnel = document["semantic_funnel"]
    status = document["semantic_effectiveness"]
    assert isinstance(funnel, dict) and isinstance(status, dict)
    assert funnel["chains_containing_admitted"] == 0
    assert funnel["later_corroborated_chains"] == 0
    assert funnel["terminal_unmapped_chains"] == 4
    assert status["status"] == "not_claimable"
    assert status["reasons"] == [
        "ambiguous_or_invalid_followup",
        "no_standardized_admissions",
    ]


def test_all_invalid_followup_shapes_are_explicit_and_excluded() -> None:
    cross_root = _receipt("cross-root", 10, judgment="ADMITTED")
    cross_successor = _receipt(
        "cross-successor",
        20,
        judgment="CORROBORATED",
        predecessor="cross-root",
        domain=("other.domain", "claim", "private-cross"),
    )
    missing = _receipt(
        "missing-successor", 30, judgment="CORROBORATED", predecessor="does-not-exist"
    )
    fork_root = _receipt(
        "fork-root", 40, judgment="ADMITTED", domain=("fixture.domain", "claim", "fork")
    )
    fork_one = _receipt(
        "fork-one",
        50,
        judgment="CORROBORATED",
        predecessor="fork-root",
        domain=("fixture.domain", "claim", "fork"),
    )
    fork_two = _receipt(
        "fork-two",
        51,
        judgment="REJECTED",
        predecessor="fork-root",
        domain=("fixture.domain", "claim", "fork"),
    )
    cycle_one = _receipt(
        "cycle-one",
        60,
        judgment="ADMITTED",
        predecessor="cycle-two",
        domain=("fixture.domain", "claim", "cycle"),
    )
    cycle_two = _receipt(
        "cycle-two",
        70,
        judgment="CORROBORATED",
        predecessor="cycle-one",
        domain=("fixture.domain", "claim", "cycle"),
    )
    late_predecessor = _receipt(
        "late-predecessor",
        90,
        judgment="ADMITTED",
        domain=("fixture.domain", "claim", "nonincrease"),
    )
    early_successor = _receipt(
        "early-successor",
        80,
        judgment="CORROBORATED",
        predecessor="late-predecessor",
        domain=("fixture.domain", "claim", "nonincrease"),
    )
    receipts = (
        cross_root,
        cross_successor,
        missing,
        fork_root,
        fork_one,
        fork_two,
        cycle_one,
        cycle_two,
        late_predecessor,
        early_successor,
    )

    document = _document(
        build_barnowl_effectiveness(receipts, (), (), join_coverage_threshold=Decimal(0)).to_dict()
    )
    funnel = document["semantic_funnel"]
    status = document["semantic_effectiveness"]
    assert isinstance(funnel, dict) and isinstance(status, dict)
    assert funnel["gap_counts"] == {
        "outside_window": 0,
        "missing_target": 1,
        "cross_domain": 1,
        "fork": 1,
        "cycle": 1,
        "non_increasing_timestamp": 2,
    }
    assert funnel["valid_domain_chains"] == 0
    assert funnel["excluded_invalid_receipt_outcomes"] == len(receipts)
    assert "ambiguous_or_invalid_followup" in status["reasons"]


def test_duplicate_missing_exact_association_and_unrelated_costs_conserve_once() -> None:
    duplicate_one = _receipt("duplicate-one", 20, judgment="REJECTED", calls=("call-dup",))
    duplicate_two = _receipt(
        "duplicate-two",
        21,
        judgment="REJECTED",
        calls=("call-dup",),
        domain=("fixture.domain", "claim", "duplicate-two"),
    )
    missing_cost = _receipt(
        "missing-cost",
        30,
        judgment="REJECTED",
        calls=("call-missing",),
        domain=("fixture.domain", "claim", "missing-cost"),
    )
    exact = _receipt(
        "exact",
        40,
        judgment="REJECTED",
        calls=("call-exact",),
        domain=("fixture.domain", "claim", "exact"),
    )
    call_dup, cost_dup = _call_and_cost("call-dup", 19, "1.00")
    call_exact, cost_exact = _call_and_cost("call-exact", 39, "2.00")
    call_association, cost_association = _call_and_cost("call-association", 45, "3.00")
    call_unrelated, cost_unrelated = _call_and_cost("call-unrelated", 46, "4.00")
    crosswalk = CrosswalkRecord.create(
        left=ExternalIdentity("somm.call", "call-association"),
        right=ExternalIdentity(BARNOWL_OUTCOME_TYPE, "exact"),
        confidence=1,
        method=JoinMethod.EXPLICIT,
        recorded_at=NOW + timedelta(seconds=45),
    )
    relations = (
        _exact_relation("call-dup", duplicate_one),
        _exact_relation("call-dup", duplicate_two),
        _exact_relation("call-exact", exact),
    )
    events = (
        duplicate_one,
        duplicate_two,
        missing_cost,
        exact,
        call_dup,
        cost_dup,
        call_exact,
        cost_exact,
        call_association,
        cost_association,
        call_unrelated,
        cost_unrelated,
    )

    document = _document(build_barnowl_effectiveness(events, (crosswalk,), relations).to_dict())
    coverage = document["receipt_coordinate_coverage"]
    allocation = document["selected_window_allocation"]
    status = document["semantic_effectiveness"]
    assert isinstance(coverage, dict) and isinstance(allocation, dict) and isinstance(status, dict)
    assert coverage["non_null_call_id_occurrences"] == 4
    assert coverage["distinct_call_ids"] == 3
    assert coverage["duplicate_call_ids_across_receipts"] == 1
    assert coverage["duplicate_call_id_occurrences"] == 2
    assert coverage["exact_selected_cost_observations_joined"] == 1
    assert coverage["receipt_call_id_occurrences_exactly_joined"] == 1
    assert coverage["receipt_call_id_occurrences_without_selected_cost"] == 1
    assert coverage["exact_join_percentage"] == "25"
    assert allocation["observations"] == {
        "selected": 4,
        "attributed": {"count": 1, "percentage": "25"},
        "ambiguous": {"count": 1, "percentage": "25"},
        "unallocated": {"count": 2, "percentage": "50"},
    }
    assert allocation["amounts_usd"] == {
        "selected": "10.00",
        "attributed": {"amount": "2.00", "percentage": "20"},
        "ambiguous": {"amount": "1.00", "percentage": "10"},
        "unallocated": {"amount": "7.00", "percentage": "70"},
    }
    assert allocation["reason_counts"] == {
        "association-only": 1,
        "competing-outcomes": 1,
        "exact-directed-path": 1,
        "no-outcome-path": 1,
    }
    assert allocation["conservation"]["satisfied"] is True
    assert status["reasons"][0] == "below_join_threshold"


def test_receipt_coverage_does_not_treat_a_non_somm_coordinate_as_selected_cost() -> None:
    receipt = _receipt(
        "adapter-collision",
        20,
        judgment="REJECTED",
        calls=("same-native-call-id",),
    )
    call, cost = _call_and_cost(
        "same-native-call-id",
        19,
        "1.00",
        adapter="codex",
    )

    document = _document(build_barnowl_effectiveness((receipt, call, cost), (), ()).to_dict())
    coverage = document["receipt_coordinate_coverage"]
    assert coverage["receipt_call_id_occurrences_without_selected_cost"] == 1
    assert coverage["distinct_receipt_call_ids_without_selected_cost"] == 1
    assert coverage["receipt_call_id_occurrences_exactly_joined"] == 0
    assert coverage["exact_join_percentage"] == "0"


def test_threshold_boundary_zero_denominators_and_validation() -> None:
    exact = _receipt("boundary-exact", 20, judgment="REJECTED", calls=("boundary-call",))
    missing = _receipt(
        "boundary-missing",
        30,
        judgment="REJECTED",
        calls=("missing-call",),
        domain=("fixture.domain", "claim", "boundary-missing"),
    )
    call, cost = _call_and_cost("boundary-call", 19, "1.00")
    relation = _exact_relation("boundary-call", exact)
    events = (exact, missing, call, cost)

    boundary = _document(
        build_barnowl_effectiveness(
            events, (), (relation,), join_coverage_threshold=Decimal("0.5")
        ).to_dict()
    )
    above = _document(
        build_barnowl_effectiveness(
            events, (), (relation,), join_coverage_threshold=Decimal("0.5001")
        ).to_dict()
    )
    assert "below_join_threshold" not in boundary["semantic_effectiveness"]["reasons"]
    assert "below_join_threshold" in above["semantic_effectiveness"]["reasons"]

    zero = _document(build_barnowl_effectiveness((), (), ()).to_dict())
    zero_coverage = zero["receipt_coordinate_coverage"]
    zero_allocation = zero["selected_window_allocation"]
    assert isinstance(zero_coverage, dict) and isinstance(zero_allocation, dict)
    assert zero_coverage["exact_join_percentage"] is None
    assert zero_allocation["observations"]["attributed"]["percentage"] is None
    assert zero_allocation["amounts_usd"]["attributed"]["percentage"] is None
    assert zero["semantic_funnel"]["cost_per_admitted_result_usd"] is None
    assert zero["semantic_funnel"]["cost_per_later_corroborated_result_usd"] is None

    with pytest.raises(ValidationError, match="between 0 and 1"):
        build_barnowl_effectiveness((), (), (), join_coverage_threshold=Decimal("1.01"))
    with pytest.raises(ValidationError, match="earlier than until"):
        build_barnowl_effectiveness((), (), (), since=NOW, until=NOW)


def test_mixed_treatment_chain_stays_mixed() -> None:
    admitted = _receipt("mixed-admitted", 10, judgment="ADMITTED", treatment=("one", HASH_A))
    corroborated = _receipt(
        "mixed-corroborated",
        20,
        judgment="CORROBORATED",
        predecessor="mixed-admitted",
        treatment=("two", HASH_B),
    )
    document = _document(
        build_barnowl_effectiveness(
            (admitted, corroborated), (), (), join_coverage_threshold=Decimal(0)
        ).to_dict()
    )
    semantic_groups = document["semantic_funnel"]["treatment_groups"]
    assert semantic_groups == [
        {
            "bucket": "mixed",
            "treatment_namespace": None,
            "manifest_sha256": None,
            "domain_chains": 1,
            "attributed_observations": 0,
            "attributed_cost_usd": "0",
            "chains_containing_admitted": 1,
            "later_corroborated_chains": 1,
            "cost_per_admitted_result_usd": "0",
            "cost_per_later_corroborated_result_usd": "0",
        }
    ]


def test_since_until_is_reproducible_and_outside_predecessor_is_not_followed(
    tmp_path: Path,
) -> None:
    predecessor = _receipt("outside-predecessor", 10, judgment="ADMITTED", calls=("before",))
    successor = _receipt(
        "inside-successor",
        20,
        judgment="CORROBORATED",
        calls=("inside",),
        predecessor="outside-predecessor",
    )
    call, cost = _call_and_cost("inside", 19, "1.25")
    relation = _exact_relation("inside", successor)
    path = tmp_path / "events.db"
    _materialize(path, (predecessor, successor, call, cost), (relation,))
    since = NOW + timedelta(seconds=15)
    until = NOW + timedelta(seconds=30)
    with MiltonStore(path, read_only=True) as store:
        before = store.barnowl_effectiveness(since=since, until=until)

    later = _receipt(
        "after-cutoff",
        40,
        judgment="CORROBORATED",
        calls=("after",),
        predecessor="inside-successor",
    )
    after_call, after_cost = _call_and_cost("after", 39, "9.99")
    refutation = relation.refute(
        note="synthetic post-cutoff refutation",
        recorded_at=NOW + timedelta(seconds=35),
    )
    _materialize(
        path,
        (later, after_call, after_cost),
        (_exact_relation("after", later), refutation),
    )
    with MiltonStore(path, read_only=True) as store:
        after = store.barnowl_effectiveness(since=since, until=until)

    assert canonical_json(before.to_dict()) == canonical_json(after.to_dict())
    assert before.to_text() == after.to_text()
    before_document = _document(before.to_dict())
    funnel = before_document["semantic_funnel"]
    assert isinstance(funnel, dict)
    assert funnel["gap_counts"]["outside_window"] == 1
    assert funnel["valid_domain_chains"] == 0
    assert before_document["window"] == {
        "since_inclusive": "2026-07-19T12:00:15Z",
        "until_exclusive": "2026-07-19T12:00:30Z",
    }


def test_json_and_text_are_deterministic_and_do_not_leak_private_coordinates() -> None:
    admitted = _receipt(
        "PRIVATE_EVENT_COORDINATE",
        10,
        judgment="ADMITTED",
        calls=("PRIVATE_CALL_ID",),
        domain=("safe.domain", "safe-type", "PRIVATE_DOMAIN_OBJECT_ID"),
        attempt="PRIVATE_ATTEMPT_ID",
    )
    call, cost = _call_and_cost("PRIVATE_CALL_ID", 9, "1.00")
    relation = _exact_relation("PRIVATE_CALL_ID", admitted)
    projection = build_barnowl_effectiveness((admitted, call, cost), (), (relation,))
    first_json = canonical_json(projection.to_dict())
    second_json = canonical_json(projection.to_dict())
    first_text = projection.to_text()
    second_text = projection.to_text()
    assert first_json == second_json
    assert first_text == second_text
    combined = first_json + first_text
    forbidden = (
        "PRIVATE_EVENT_COORDINATE",
        "PRIVATE_CALL_ID",
        "PRIVATE_DOMAIN_OBJECT_ID",
        "PRIVATE_ATTEMPT_ID",
        "private-correlation",
        "private-prompt",
        "private-authority",
        "private-provider",
        "private-model",
        "/private/",
        "PRIVATE_BODY",
        admitted.event_id,
        call.event_id,
        cost.event_id,
    )
    assert all(value not in combined for value in forbidden)
    assert HASH_A in combined
    assert "safe.domain" in combined
    assert "safe-type" in combined


def test_cli_json_text_help_read_only_and_argument_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt = _receipt("cli-receipt", 20, judgment="REJECTED", calls=("cli-call",))
    call, cost = _call_and_cost("cli-call", 19, "0.75")
    relation = _exact_relation("cli-call", receipt)
    path = tmp_path / "events.db"
    _materialize(path, (receipt, call, cost), (relation,))
    source_files_before = {
        item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()
    }

    args = [
        "effectiveness",
        "barnowl",
        "--store",
        str(path),
        "--join-coverage-threshold",
        "1",
        "--format",
        "json",
    ]
    assert main(args) == 0
    first_json = capsys.readouterr().out
    assert main(args) == 0
    assert capsys.readouterr().out == first_json
    assert '"schema_version":"milton.barnowl-effectiveness/v1"' in first_json

    text_args = [*args[:-1], "text"]
    assert main(text_args) == 0
    first_text = capsys.readouterr().out
    assert main(text_args) == 0
    assert capsys.readouterr().out == first_text
    assert "Amounts are selected observations" in first_text
    assert "Receipt coordinate coverage" in first_text
    assert "Selected-window allocation" in first_text
    assert "not claimable" in first_text
    source_files_after = {
        item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()
    }
    assert source_files_after == source_files_before

    assert main([*args[:-4], "--join-coverage-threshold", "1.1"]) == 1
    assert "must be between 0 and 1" in capsys.readouterr().err
    assert (
        main(
            [
                "effectiveness",
                "barnowl",
                "--store",
                str(path),
                "--since",
                "2026-07-20T00:00:00Z",
                "--until",
                "2026-07-19T00:00:00Z",
            ]
        )
        == 1
    )
    assert "--since must be earlier than --until" in capsys.readouterr().err


def test_store_replay_is_stable_and_read_only_mode_rejects_writes(tmp_path: Path) -> None:
    receipt = _receipt("replay-receipt", 20, judgment="REJECTED", calls=("replay-call",))
    call, cost = _call_and_cost("replay-call", 19, "0.50")
    relation = _exact_relation("replay-call", receipt)
    path = tmp_path / "events.db"
    with MiltonStore(path) as store:
        store.append_events((receipt, call, cost))
        store.append_relation(relation)
        before = canonical_json(store.barnowl_effectiveness().to_dict())
        assert store.append_events((receipt, call, cost)) == (0, 3)
        assert not store.append_relation(relation)
        after = canonical_json(store.barnowl_effectiveness().to_dict())
    assert before == after

    with MiltonStore(path, read_only=True) as store:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            store.append_event(_receipt("write-must-fail", 50, judgment="REJECTED"))


def test_read_only_snapshot_includes_committed_wal_without_touching_source_sidecars(
    tmp_path: Path,
) -> None:
    path = tmp_path / "live.db"
    receipt = _receipt("wal-receipt", 20, judgment="REJECTED")
    with MiltonStore(path) as writer:
        writer.append_event(receipt)
        source_files_before = {
            item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()
        }
        assert "live.db-wal" in source_files_before

        with MiltonStore(path, read_only=True) as reader:
            assert reader.get_event(receipt.event_id) is not None

        source_files_after = {
            item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()
        }
        assert source_files_after == source_files_before
