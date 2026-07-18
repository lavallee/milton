from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from milton.errors import ValidationError
from milton.evaluation import (
    CalibrationLabel,
    CalibrationLedger,
    EvaluationDecision,
    EvaluationFloors,
    EvaluationPartition,
    EvaluationTuple,
    FindingEvaluationCase,
    FindingPrediction,
    evaluate_findings,
)


def case(
    case_id: str,
    partition: EvaluationPartition,
    expected: bool | None,
) -> FindingEvaluationCase:
    return FindingEvaluationCase(
        case_id=case_id,
        partition=partition,
        expected_finding=expected,
        expected_disposition=None,
        rationale=f"reviewed {case_id}",
        source_coordinates=(f"source={case_id}",),
        evidence_ids=(f"event-{case_id}",),
    )


def envelope() -> EvaluationTuple:
    return EvaluationTuple(
        generator="milton.test/v1",
        model="deterministic",
        harness="pytest/v1",
        parameters_digest="params-1",
        source_snapshot="source-1",
    )


def test_evaluation_is_reproducible_and_enforces_all_promotion_floors() -> None:
    cases = (
        case("tune", EvaluationPartition.TUNING, True),
        case("positive", EvaluationPartition.HELDOUT, True),
        case("negative", EvaluationPartition.HELDOUT, False),
    )
    predictions = (
        FindingPrediction("positive", True, None, ("run-1",), 2),
        FindingPrediction("negative", False, None, (), 0),
    )
    floors = EvaluationFloors(recurrence=2, aggregation=3)

    first = evaluate_findings(cases, predictions, evaluation_tuple=envelope(), floors=floors)
    replay = evaluate_findings(
        cases,
        tuple(reversed(predictions)),
        evaluation_tuple=envelope(),
        floors=floors,
    )

    assert first == replay
    assert first.decision is EvaluationDecision.OFFLINE
    assert first.heldout.precision == 1.0
    assert first.heldout.recurrence_violations == 1
    assert first.heldout.aggregation_violations == 1

    eligible = evaluate_findings(
        cases,
        (
            FindingPrediction("positive", True, None, ("run-1", "run-2"), 3),
            predictions[1],
        ),
        evaluation_tuple=envelope(),
        floors=floors,
    )
    assert eligible.decision is EvaluationDecision.SURFACE
    assert eligible.result_id != first.result_id


def test_corpus_partitions_reject_coordinate_and_evidence_leakage() -> None:
    tuning = case("tuning", EvaluationPartition.TUNING, True)
    heldout = FindingEvaluationCase(
        case_id="heldout",
        partition=EvaluationPartition.HELDOUT,
        expected_finding=True,
        expected_disposition=None,
        rationale="leaked held-out case",
        source_coordinates=tuning.source_coordinates,
        evidence_ids=("heldout-event",),
    )
    with pytest.raises(ValidationError, match="source coordinates overlap"):
        evaluate_findings(
            (tuning, heldout),
            (FindingPrediction("heldout", True, None, ("run",), 1),),
            evaluation_tuple=envelope(),
        )


def test_refuted_live_finding_appends_calibration_without_rewriting_old_result(
    tmp_path: Path,
) -> None:
    heldout = case("heldout", EvaluationPartition.HELDOUT, True)
    prediction = FindingPrediction("heldout", True, None, ("run-1",), 1)
    original = evaluate_findings((heldout,), (prediction,), evaluation_tuple=envelope())
    original_document = original.to_dict()

    label = CalibrationLabel.create(
        finding_revision_id="fnr-live",
        receipt_id="george-disposition-refuted",
        expected_finding=False,
        expected_disposition="refuted",
        rationale="George reviewed the exact live lead and refuted its current applicability",
        source_coordinates=("george.gate=live-refuted",),
        evidence_ids=("evt-disposition", "evt-live-source"),
        recorded_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    ledger = CalibrationLedger(tmp_path / "calibration.jsonl")
    assert ledger.append(label)
    assert not ledger.append(label)
    assert ledger.read() == (label,)

    updated = evaluate_findings(
        (heldout, label.to_case()),
        (
            prediction,
            FindingPrediction(label.label_id, True, "refuted", ("run-live",), 1),
        ),
        evaluation_tuple=envelope(),
    )

    assert original.to_dict() == original_document
    assert updated.result_id != original.result_id
    assert updated.heldout == original.heldout
    assert updated.calibration.false_positive == 1
    assert updated.calibration.disposition_matches == 1
