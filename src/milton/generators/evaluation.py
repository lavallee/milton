"""Held-out evaluation contract for deterministic George gate rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from milton.errors import ValidationError
from milton.evaluation import (
    EvaluationDecision,
    EvaluationFloors,
    EvaluationPartition,
    EvaluationTuple,
    FindingEvaluationCase,
    FindingEvaluationResult,
    FindingPrediction,
    evaluate_findings,
)
from milton.generators.george_gates import (
    GEORGE_GATE_GENERATOR,
    GateAssessmentState,
    GateDetectorConfig,
    GateRule,
    GateSourceState,
    detect_george_gates,
)
from milton.model import JsonValue, canonical_json, parse_datetime, stable_id
from milton.store import MiltonStore

GATE_EVALUATOR = "milton.george-gates-eval/v1"


class GateCaseLabel(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"
    DUPLICATE = "duplicate"


class GateCasePartition(StrEnum):
    TUNING = "tuning"
    HELDOUT = "heldout"


GateSurfaceDecision = EvaluationDecision


@dataclass(frozen=True, slots=True)
class GateEvaluationCase:
    case_id: str
    partition: GateCasePartition
    rule: GateRule
    label: GateCaseLabel
    rationale: str
    source_coordinates: tuple[str, ...]
    event_ids: tuple[str, ...]
    config: GateDetectorConfig

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.rationale.strip():
            raise ValidationError("gate evaluation case id and rationale must not be empty")
        if not self.source_coordinates or not self.event_ids:
            raise ValidationError("gate evaluation cases require source coordinates and events")
        if tuple(sorted(set(self.source_coordinates))) != self.source_coordinates:
            raise ValidationError("source coordinates must be sorted and unique")
        if tuple(sorted(set(self.event_ids))) != self.event_ids:
            raise ValidationError("event ids must be sorted and unique")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GateEvaluationCase:
        config = raw.get("config")
        if not isinstance(config, dict):
            raise ValidationError("gate evaluation case config must be an object")
        return cls(
            case_id=str(raw["case_id"]),
            partition=GateCasePartition(raw["partition"]),
            rule=GateRule(raw["rule"]),
            label=GateCaseLabel(raw["label"]),
            rationale=str(raw["rationale"]),
            source_coordinates=tuple(sorted(set(str(item) for item in raw["source_coordinates"]))),
            event_ids=tuple(sorted(set(str(item) for item in raw["event_ids"]))),
            config=GateDetectorConfig(
                since=parse_datetime(str(config["since"])),
                cutoff=parse_datetime(str(config["cutoff_exclusive"])),
                source_state=GateSourceState(config["source_state"]),
                remint_threshold=int(config.get("remint_threshold", 3)),
                remint_window_days=int(config.get("remint_window_days", 7)),
                old_after_days=int(config.get("old_after_days", 7)),
                expires_after_days=int(config.get("expires_after_days", 7)),
            ),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "case_id": self.case_id,
            "partition": self.partition.value,
            "rule": self.rule.value,
            "label": self.label.value,
            "rationale": self.rationale,
            "source_coordinates": list(self.source_coordinates),
            "event_ids": list(self.event_ids),
            "config": self.config.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class GateRuleEvaluation:
    rule: GateRule
    heldout_cases: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    abstained: int
    exact_matches: int
    precision: float | None
    coverage: float
    decision: GateSurfaceDecision
    evaluation_result_id: str
    recurrence_violations: int
    aggregation_violations: int

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "rule": self.rule.value,
            "heldout_cases": self.heldout_cases,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "abstained": self.abstained,
            "exact_matches": self.exact_matches,
            "precision": self.precision,
            "coverage": self.coverage,
            "decision": self.decision.value,
            "evaluation_result_id": self.evaluation_result_id,
            "recurrence_violations": self.recurrence_violations,
            "aggregation_violations": self.aggregation_violations,
        }


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    corpus_snapshot: str
    promotion_floor: float
    narrow_floor: float
    tuning_cases: int
    rules: tuple[GateRuleEvaluation, ...]
    measured_results: tuple[FindingEvaluationResult, ...]

    @property
    def surface_rules(self) -> tuple[GateRule, ...]:
        return tuple(
            item.rule for item in self.rules if item.decision is GateSurfaceDecision.SURFACE
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 2,
            "evaluator": GATE_EVALUATOR,
            "corpus_snapshot": self.corpus_snapshot,
            "promotion_floor": self.promotion_floor,
            "narrow_floor": self.narrow_floor,
            "tuning_cases": self.tuning_cases,
            "surface_rules": [rule.value for rule in self.surface_rules],
            "rules": [item.to_dict() for item in self.rules],
            "measured_results": [item.to_dict() for item in self.measured_results],
        }


def read_gate_cases(path: Path) -> tuple[GateEvaluationCase, ...]:
    cases: list[GateEvaluationCase] = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError as error:
        raise ValidationError(f"cannot read gate evaluation corpus {path}: {error}") from error
    with handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValidationError("case must be an object")
                cases.append(GateEvaluationCase.from_dict(raw))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValidationError(
                    f"cannot read gate evaluation corpus {path}:{line_number}: {error}"
                ) from error
    if not cases:
        raise ValidationError("gate evaluation corpus is empty")
    return tuple(cases)


def evaluate_gate_cases(
    cases: tuple[GateEvaluationCase, ...],
    store: MiltonStore,
    *,
    promotion_floor: float = 0.9,
    narrow_floor: float = 0.8,
    recurrence_floor: int = 1,
    aggregation_floor: int = 1,
) -> GateEvaluation:
    _validate_corpus(cases)
    snapshot = stable_id(
        "evl",
        GATE_EVALUATOR,
        *(canonical_json(case.to_dict()) for case in sorted(cases, key=lambda item: item.case_id)),
    )
    predictions: dict[str, GateAssessmentState] = {}
    for case in cases:
        events = []
        for event_id in case.event_ids:
            event = store.get_event(event_id)
            if event is None:
                raise ValidationError(
                    f"evaluation case {case.case_id} references missing event {event_id}"
                )
            events.append(event)
        projection = detect_george_gates(events, case.config)
        selected = [item for item in projection.assessments if item.rule is case.rule]
        if len(selected) != 1:
            raise ValidationError(
                f"evaluation case {case.case_id} produced {len(selected)} assessments for "
                f"{case.rule.value}; expected exactly one"
            )
        predictions[case.case_id] = selected[0].state

    floors = EvaluationFloors(
        promotion_precision=promotion_floor,
        narrow_precision=narrow_floor,
        recurrence=recurrence_floor,
        aggregation=aggregation_floor,
    )
    measured_results = tuple(
        _evaluate_rule_contract(
            rule,
            cases,
            predictions,
            floors,
        )
        for rule in GateRule
    )
    evaluations = tuple(
        _gate_rule_evaluation(rule, result)
        for rule, result in zip(GateRule, measured_results, strict=True)
    )
    return GateEvaluation(
        corpus_snapshot=snapshot,
        promotion_floor=promotion_floor,
        narrow_floor=narrow_floor,
        tuning_cases=sum(case.partition is GateCasePartition.TUNING for case in cases),
        rules=evaluations,
        measured_results=measured_results,
    )


def _validate_corpus(cases: tuple[GateEvaluationCase, ...]) -> None:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValidationError("gate evaluation case ids must be unique")
    tuning = {
        coordinate
        for case in cases
        if case.partition is GateCasePartition.TUNING
        for coordinate in case.source_coordinates
    }
    heldout = {
        coordinate
        for case in cases
        if case.partition is GateCasePartition.HELDOUT
        for coordinate in case.source_coordinates
    }
    overlap = tuning & heldout
    if overlap:
        raise ValidationError(f"tuning and held-out source coordinates overlap: {sorted(overlap)}")
    tuning_events = {
        event_id
        for case in cases
        if case.partition is GateCasePartition.TUNING
        for event_id in case.event_ids
    }
    heldout_events = {
        event_id
        for case in cases
        if case.partition is GateCasePartition.HELDOUT
        for event_id in case.event_ids
    }
    event_overlap = tuning_events & heldout_events
    if event_overlap:
        raise ValidationError(f"tuning and held-out event ids overlap: {sorted(event_overlap)}")


def _evaluate_rule_contract(
    rule: GateRule,
    cases: tuple[GateEvaluationCase, ...],
    predictions: dict[str, GateAssessmentState],
    floors: EvaluationFloors,
) -> FindingEvaluationResult:
    selected = tuple(case for case in cases if case.rule is rule)
    generic_cases = tuple(
        FindingEvaluationCase(
            case_id=case.case_id,
            partition=EvaluationPartition(case.partition.value),
            expected_finding=(
                True
                if case.label is GateCaseLabel.SUPPORTED
                else None
                if case.label is GateCaseLabel.AMBIGUOUS
                else False
            ),
            expected_disposition=None,
            rationale=case.rationale,
            source_coordinates=case.source_coordinates,
            evidence_ids=case.event_ids,
        )
        for case in selected
    )
    heldout = tuple(case for case in selected if case.partition is GateCasePartition.HELDOUT)
    generic_predictions = tuple(
        FindingPrediction(
            case_id=case.case_id,
            finding=(
                True
                if predictions[case.case_id] is GateAssessmentState.DETECTED
                else None
                if predictions[case.case_id] is GateAssessmentState.ABSTAIN
                else False
            ),
            disposition=None,
            independent_recurrences=(
                case.event_ids if predictions[case.case_id] is GateAssessmentState.DETECTED else ()
            ),
            aggregation_size=(
                len(case.source_coordinates)
                if predictions[case.case_id] is GateAssessmentState.DETECTED
                else 0
            ),
        )
        for case in heldout
    )
    parameters_digest = stable_id(
        "par",
        *(canonical_json(case.config.to_dict()) for case in selected),
    )
    source_snapshot = stable_id(
        "src",
        *(event_id for case in selected for event_id in case.event_ids),
    )
    return evaluate_findings(
        generic_cases,
        generic_predictions,
        evaluation_tuple=EvaluationTuple(
            generator=f"{GEORGE_GATE_GENERATOR}:{rule.value}",
            model="deterministic",
            harness=GATE_EVALUATOR,
            parameters_digest=parameters_digest,
            source_snapshot=source_snapshot,
        ),
        floors=floors,
    )


def _gate_rule_evaluation(rule: GateRule, result: FindingEvaluationResult) -> GateRuleEvaluation:
    metrics = result.heldout
    return GateRuleEvaluation(
        rule=rule,
        heldout_cases=metrics.cases,
        true_positive=metrics.true_positive,
        false_positive=metrics.false_positive,
        true_negative=metrics.true_negative,
        false_negative=metrics.false_negative,
        abstained=metrics.abstained,
        exact_matches=metrics.exact_matches,
        precision=metrics.precision,
        coverage=metrics.coverage,
        decision=result.decision,
        evaluation_result_id=result.result_id,
        recurrence_violations=metrics.recurrence_violations,
        aggregation_violations=metrics.aggregation_violations,
    )
