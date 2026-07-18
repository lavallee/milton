"""Generator-neutral, immutable finding-quality evaluation contracts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from milton.errors import LedgerCorruptionError, RecordConflictError, ValidationError
from milton.model import JsonValue, canonical_json, format_datetime, parse_datetime, stable_id

EVALUATION_SCHEMA = "milton.finding-evaluation/v1"
CALIBRATION_SCHEMA = "milton.finding-calibration/v1"


class EvaluationPartition(StrEnum):
    TUNING = "tuning"
    HELDOUT = "heldout"
    CALIBRATION = "calibration"


class EvaluationDecision(StrEnum):
    SURFACE = "surface"
    NARROW = "narrow"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class EvaluationTuple:
    """Exact implementation envelope whose quality is being measured."""

    generator: str
    model: str
    harness: str
    parameters_digest: str
    source_snapshot: str

    def __post_init__(self) -> None:
        for name in ("generator", "model", "harness", "parameters_digest", "source_snapshot"):
            if not getattr(self, name).strip():
                raise ValidationError(f"evaluation tuple {name} must not be empty")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "generator": self.generator,
            "model": self.model,
            "harness": self.harness,
            "parameters_digest": self.parameters_digest,
            "source_snapshot": self.source_snapshot,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvaluationTuple:
        return cls(
            generator=str(raw["generator"]),
            model=str(raw["model"]),
            harness=str(raw["harness"]),
            parameters_digest=str(raw["parameters_digest"]),
            source_snapshot=str(raw["source_snapshot"]),
        )


@dataclass(frozen=True, slots=True)
class EvaluationFloors:
    promotion_precision: float = 0.9
    narrow_precision: float = 0.8
    recurrence: int = 1
    aggregation: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.narrow_precision <= self.promotion_precision <= 1:
            raise ValidationError("evaluation floors must satisfy 0 <= narrow <= promotion <= 1")
        if self.recurrence <= 0 or self.aggregation <= 0:
            raise ValidationError("recurrence and aggregation floors must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "promotion_precision": self.promotion_precision,
            "narrow_precision": self.narrow_precision,
            "recurrence": self.recurrence,
            "aggregation": self.aggregation,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvaluationFloors:
        return cls(
            promotion_precision=float(raw["promotion_precision"]),
            narrow_precision=float(raw["narrow_precision"]),
            recurrence=int(raw["recurrence"]),
            aggregation=int(raw["aggregation"]),
        )


@dataclass(frozen=True, slots=True)
class FindingEvaluationCase:
    case_id: str
    partition: EvaluationPartition
    expected_finding: bool | None
    expected_disposition: str | None
    rationale: str
    source_coordinates: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.rationale.strip():
            raise ValidationError("evaluation case id and rationale must not be empty")
        if not self.source_coordinates or not self.evidence_ids:
            raise ValidationError("evaluation cases require source coordinates and evidence")
        _require_sorted_unique("source coordinates", self.source_coordinates)
        _require_sorted_unique("evidence ids", self.evidence_ids)
        if self.expected_disposition is not None and not self.expected_disposition.strip():
            raise ValidationError("expected disposition must not be empty")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "case_id": self.case_id,
            "partition": self.partition.value,
            "expected_finding": self.expected_finding,
            "expected_disposition": self.expected_disposition,
            "rationale": self.rationale,
            "source_coordinates": list(self.source_coordinates),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class FindingPrediction:
    case_id: str
    finding: bool | None
    disposition: str | None
    independent_recurrences: tuple[str, ...]
    aggregation_size: int

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValidationError("prediction case id must not be empty")
        _require_sorted_unique("independent recurrences", self.independent_recurrences)
        if self.aggregation_size < 0:
            raise ValidationError("prediction aggregation size must not be negative")
        if self.disposition is not None and not self.disposition.strip():
            raise ValidationError("prediction disposition must not be empty")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "case_id": self.case_id,
            "finding": self.finding,
            "disposition": self.disposition,
            "independent_recurrences": list(self.independent_recurrences),
            "aggregation_size": self.aggregation_size,
        }


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    cases: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    abstained: int
    exact_matches: int
    disposition_matches: int
    precision: float | None
    coverage: float
    recurrence_violations: int
    aggregation_violations: int

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "cases": self.cases,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "abstained": self.abstained,
            "exact_matches": self.exact_matches,
            "disposition_matches": self.disposition_matches,
            "precision": self.precision,
            "coverage": self.coverage,
            "recurrence_violations": self.recurrence_violations,
            "aggregation_violations": self.aggregation_violations,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvaluationMetrics:
        precision = raw.get("precision")
        return cls(
            cases=int(raw["cases"]),
            true_positive=int(raw["true_positive"]),
            false_positive=int(raw["false_positive"]),
            true_negative=int(raw["true_negative"]),
            false_negative=int(raw["false_negative"]),
            abstained=int(raw["abstained"]),
            exact_matches=int(raw["exact_matches"]),
            disposition_matches=int(raw["disposition_matches"]),
            precision=float(precision) if precision is not None else None,
            coverage=float(raw["coverage"]),
            recurrence_violations=int(raw["recurrence_violations"]),
            aggregation_violations=int(raw["aggregation_violations"]),
        )


@dataclass(frozen=True, slots=True)
class FindingEvaluationResult:
    result_id: str
    corpus_snapshot: str
    evaluation_tuple: EvaluationTuple
    floors: EvaluationFloors
    tuning_cases: int
    heldout: EvaluationMetrics
    calibration: EvaluationMetrics
    decision: EvaluationDecision

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": EVALUATION_SCHEMA,
            "result_id": self.result_id,
            "corpus_snapshot": self.corpus_snapshot,
            "evaluation_tuple": self.evaluation_tuple.to_dict(),
            "floors": self.floors.to_dict(),
            "tuning_cases": self.tuning_cases,
            "heldout": self.heldout.to_dict(),
            "calibration": self.calibration.to_dict(),
            "decision": self.decision.value,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FindingEvaluationResult:
        if raw.get("schema") != EVALUATION_SCHEMA:
            raise ValidationError(f"unsupported evaluation schema: {raw.get('schema')!r}")
        return cls(
            result_id=str(raw["result_id"]),
            corpus_snapshot=str(raw["corpus_snapshot"]),
            evaluation_tuple=EvaluationTuple.from_dict(raw["evaluation_tuple"]),
            floors=EvaluationFloors.from_dict(raw["floors"]),
            tuning_cases=int(raw["tuning_cases"]),
            heldout=EvaluationMetrics.from_dict(raw["heldout"]),
            calibration=EvaluationMetrics.from_dict(raw["calibration"]),
            decision=EvaluationDecision(raw["decision"]),
        )


def evaluate_findings(
    cases: tuple[FindingEvaluationCase, ...],
    predictions: tuple[FindingPrediction, ...],
    *,
    evaluation_tuple: EvaluationTuple,
    floors: EvaluationFloors | None = None,
) -> FindingEvaluationResult:
    """Evaluate a frozen corpus; only held-out cases authorize surfacing."""

    _validate_corpus(cases)
    resolved_floors = floors or EvaluationFloors()
    predictions_by_id = {prediction.case_id: prediction for prediction in predictions}
    if len(predictions_by_id) != len(predictions):
        raise ValidationError("prediction case ids must be unique")
    evaluated_ids = {
        case.case_id for case in cases if case.partition is not EvaluationPartition.TUNING
    }
    missing = evaluated_ids - predictions_by_id.keys()
    extra = predictions_by_id.keys() - evaluated_ids
    if missing or extra:
        raise ValidationError(
            f"predictions must exactly cover held-out and calibration cases; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    corpus_snapshot = stable_id(
        "evc",
        EVALUATION_SCHEMA,
        *(canonical_json(case.to_dict()) for case in sorted(cases, key=lambda item: item.case_id)),
    )
    heldout = _metrics(
        tuple(case for case in cases if case.partition is EvaluationPartition.HELDOUT),
        predictions_by_id,
        resolved_floors,
    )
    calibration = _metrics(
        tuple(case for case in cases if case.partition is EvaluationPartition.CALIBRATION),
        predictions_by_id,
        resolved_floors,
    )
    if (
        heldout.precision is not None
        and heldout.true_positive > 0
        and heldout.precision >= resolved_floors.promotion_precision
        and heldout.recurrence_violations == 0
        and heldout.aggregation_violations == 0
    ):
        decision = EvaluationDecision.SURFACE
    elif (
        heldout.precision is not None
        and heldout.true_positive > 0
        and heldout.precision >= resolved_floors.narrow_precision
        and heldout.recurrence_violations == 0
        and heldout.aggregation_violations == 0
    ):
        decision = EvaluationDecision.NARROW
    else:
        decision = EvaluationDecision.OFFLINE
    result_id = stable_id(
        "evr",
        EVALUATION_SCHEMA,
        corpus_snapshot,
        canonical_json(evaluation_tuple.to_dict()),
        canonical_json(resolved_floors.to_dict()),
        *(
            canonical_json(item.to_dict())
            for item in sorted(predictions, key=lambda row: row.case_id)
        ),
    )
    return FindingEvaluationResult(
        result_id=result_id,
        corpus_snapshot=corpus_snapshot,
        evaluation_tuple=evaluation_tuple,
        floors=resolved_floors,
        tuning_cases=sum(case.partition is EvaluationPartition.TUNING for case in cases),
        heldout=heldout,
        calibration=calibration,
        decision=decision,
    )


@dataclass(frozen=True, slots=True)
class CalibrationLabel:
    """Append-only reviewed label derived from a later source-owned disposition."""

    label_id: str
    finding_revision_id: str
    receipt_id: str
    expected_finding: bool | None
    expected_disposition: str
    rationale: str
    source_coordinates: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    recorded_at: datetime

    @classmethod
    def create(
        cls,
        *,
        finding_revision_id: str,
        receipt_id: str,
        expected_finding: bool | None,
        expected_disposition: str,
        rationale: str,
        source_coordinates: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        recorded_at: datetime,
    ) -> CalibrationLabel:
        label_id = stable_id(
            "cal",
            finding_revision_id,
            receipt_id,
            expected_disposition,
            str(expected_finding),
        )
        return cls(
            label_id,
            finding_revision_id,
            receipt_id,
            expected_finding,
            expected_disposition,
            rationale,
            source_coordinates,
            evidence_ids,
            recorded_at,
        )

    def __post_init__(self) -> None:
        for name in (
            "label_id",
            "finding_revision_id",
            "receipt_id",
            "expected_disposition",
            "rationale",
        ):
            if not getattr(self, name).strip():
                raise ValidationError(f"calibration {name} must not be empty")
        _require_sorted_unique("source coordinates", self.source_coordinates)
        _require_sorted_unique("evidence ids", self.evidence_ids)
        format_datetime(self.recorded_at)

    def to_case(self) -> FindingEvaluationCase:
        return FindingEvaluationCase(
            case_id=self.label_id,
            partition=EvaluationPartition.CALIBRATION,
            expected_finding=self.expected_finding,
            expected_disposition=self.expected_disposition,
            rationale=self.rationale,
            source_coordinates=self.source_coordinates,
            evidence_ids=self.evidence_ids,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": CALIBRATION_SCHEMA,
            "label_id": self.label_id,
            "finding_revision_id": self.finding_revision_id,
            "receipt_id": self.receipt_id,
            "expected_finding": self.expected_finding,
            "expected_disposition": self.expected_disposition,
            "rationale": self.rationale,
            "source_coordinates": list(self.source_coordinates),
            "evidence_ids": list(self.evidence_ids),
            "recorded_at": format_datetime(self.recorded_at),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CalibrationLabel:
        if raw.get("schema") != CALIBRATION_SCHEMA:
            raise ValidationError(f"unsupported calibration schema: {raw.get('schema')!r}")
        return cls(
            label_id=str(raw["label_id"]),
            finding_revision_id=str(raw["finding_revision_id"]),
            receipt_id=str(raw["receipt_id"]),
            expected_finding=raw.get("expected_finding"),
            expected_disposition=str(raw["expected_disposition"]),
            rationale=str(raw["rationale"]),
            source_coordinates=tuple(str(item) for item in raw["source_coordinates"]),
            evidence_ids=tuple(str(item) for item in raw["evidence_ids"]),
            recorded_at=parse_datetime(str(raw["recorded_at"])),
        )


class CalibrationLedger:
    """Small append-only ledger; adding labels never rewrites an evaluation result."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> tuple[CalibrationLabel, ...]:
        if not self.path.exists():
            return ()
        rows: list[CalibrationLabel] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise ValidationError("calibration row must be an object")
                    rows.append(CalibrationLabel.from_dict(raw))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    raise LedgerCorruptionError(
                        f"invalid calibration ledger row {self.path}:{line_number}: {error}"
                    ) from error
        return tuple(rows)

    def append(self, label: CalibrationLabel) -> bool:
        existing = {item.label_id: item for item in self.read()}
        current = existing.get(label.label_id)
        if current is not None:
            if current != label:
                raise RecordConflictError(f"calibration label conflicts: {label.label_id}")
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (canonical_json(label.to_dict()) + "\n").encode()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True


def _validate_corpus(cases: tuple[FindingEvaluationCase, ...]) -> None:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValidationError("evaluation case ids must be unique")
    partitions = {
        partition: tuple(case for case in cases if case.partition is partition)
        for partition in EvaluationPartition
    }
    for left, right in (
        (EvaluationPartition.TUNING, EvaluationPartition.HELDOUT),
        (EvaluationPartition.TUNING, EvaluationPartition.CALIBRATION),
        (EvaluationPartition.HELDOUT, EvaluationPartition.CALIBRATION),
    ):
        left_coordinates = {
            coordinate for case in partitions[left] for coordinate in case.source_coordinates
        }
        right_coordinates = {
            coordinate for case in partitions[right] for coordinate in case.source_coordinates
        }
        overlap = left_coordinates & right_coordinates
        if overlap:
            raise ValidationError(
                f"{left.value} and {right.value} source coordinates overlap: {sorted(overlap)}"
            )
        left_evidence = {event for case in partitions[left] for event in case.evidence_ids}
        right_evidence = {event for case in partitions[right] for event in case.evidence_ids}
        evidence_overlap = left_evidence & right_evidence
        if evidence_overlap:
            raise ValidationError(
                f"{left.value} and {right.value} evidence ids overlap: {sorted(evidence_overlap)}"
            )


def _metrics(
    cases: tuple[FindingEvaluationCase, ...],
    predictions: dict[str, FindingPrediction],
    floors: EvaluationFloors,
) -> EvaluationMetrics:
    tp = fp = tn = fn = abstained = exact = disposition_matches = 0
    recurrence_violations = aggregation_violations = 0
    for case in cases:
        prediction = predictions[case.case_id]
        if prediction.finding is None:
            abstained += 1
        elif prediction.finding:
            if case.expected_finding is True:
                tp += 1
            else:
                fp += 1
            recurrence_violations += int(
                len(prediction.independent_recurrences) < floors.recurrence
            )
            aggregation_violations += int(prediction.aggregation_size < floors.aggregation)
        elif case.expected_finding is True:
            fn += 1
        else:
            tn += 1
        finding_matches = prediction.finding is case.expected_finding
        disposition_matches += int(
            case.expected_disposition is not None
            and prediction.disposition == case.expected_disposition
        )
        exact += int(
            finding_matches
            and (
                case.expected_disposition is None
                or prediction.disposition == case.expected_disposition
            )
        )
    precision = tp / (tp + fp) if tp + fp else None
    coverage = (len(cases) - abstained) / len(cases) if cases else 0.0
    return EvaluationMetrics(
        cases=len(cases),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        abstained=abstained,
        exact_matches=exact,
        disposition_matches=disposition_matches,
        precision=precision,
        coverage=coverage,
        recurrence_violations=recurrence_violations,
        aggregation_violations=aggregation_violations,
    )


def _require_sorted_unique(name: str, values: tuple[str, ...]) -> None:
    if tuple(sorted(set(values))) != values:
        raise ValidationError(f"{name} must be sorted and unique")
