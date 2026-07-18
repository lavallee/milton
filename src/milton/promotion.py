"""Post-promotion procedure calibration over exact producer receipts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from milton.errors import RecordConflictError, ValidationError
from milton.model import (
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    canonical_json,
    format_datetime,
    parse_datetime,
    stable_id,
)
from milton.relations import RelationKind, TypedRef
from milton.store import MiltonStore

PROCEDURE_CALIBRATION_SCHEMA = "milton.procedure-calibration/v1"
_TUPLE_FIELDS = ("implementation", "profile", "model", "harness")


class ProcedureOutcomeState(StrEnum):
    IMPROVEMENT = "improvement"
    REGRESSION = "regression"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class ProcedureCalibrationRecord:
    result_id: str
    finding_id: str
    finding_revision_id: str
    chip_candidate_id: str
    chip_receipt_id: str
    spindle_evaluation_receipt_id: str
    spindle_promotion_receipt_id: str
    evaluation_tuple: dict[str, str]
    baseline_tuple: dict[str, str]
    metric: str | None
    direction: str | None
    baseline_score: float | None
    post_score: float | None
    state: ProcedureOutcomeState
    reasons: tuple[str, ...]
    fab_receipt_id: str | None
    somm_receipt_id: str | None
    evidence_event_ids: tuple[str, ...]
    recorded_at: datetime

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": PROCEDURE_CALIBRATION_SCHEMA,
            "result_id": self.result_id,
            "finding_id": self.finding_id,
            "finding_revision_id": self.finding_revision_id,
            "chip_candidate_id": self.chip_candidate_id,
            "chip_receipt_id": self.chip_receipt_id,
            "spindle_evaluation_receipt_id": self.spindle_evaluation_receipt_id,
            "spindle_promotion_receipt_id": self.spindle_promotion_receipt_id,
            "evaluation_tuple": cast(JsonValue, self.evaluation_tuple),
            "baseline_tuple": cast(JsonValue, self.baseline_tuple),
            "measurement": {
                "metric": self.metric,
                "direction": self.direction,
                "baseline_score": self.baseline_score,
                "post_score": self.post_score,
            },
            "state": self.state.value,
            "reasons": list(self.reasons),
            "fab_receipt_id": self.fab_receipt_id,
            "somm_receipt_id": self.somm_receipt_id,
            "evidence_event_ids": list(self.evidence_event_ids),
            "recorded_at": format_datetime(self.recorded_at),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProcedureCalibrationRecord:
        if raw.get("schema") != PROCEDURE_CALIBRATION_SCHEMA:
            raise ValidationError("unsupported procedure calibration schema")
        measurement = raw.get("measurement")
        if not isinstance(measurement, dict):
            raise ValidationError("procedure calibration measurement must be an object")
        return cls(
            result_id=str(raw["result_id"]),
            finding_id=str(raw["finding_id"]),
            finding_revision_id=str(raw["finding_revision_id"]),
            chip_candidate_id=str(raw["chip_candidate_id"]),
            chip_receipt_id=str(raw["chip_receipt_id"]),
            spindle_evaluation_receipt_id=str(raw["spindle_evaluation_receipt_id"]),
            spindle_promotion_receipt_id=str(raw["spindle_promotion_receipt_id"]),
            evaluation_tuple=_string_tuple(raw["evaluation_tuple"]),
            baseline_tuple=_string_tuple(raw["baseline_tuple"]),
            metric=_optional_string(measurement.get("metric")),
            direction=_optional_string(measurement.get("direction")),
            baseline_score=_optional_number(measurement.get("baseline_score")),
            post_score=_optional_number(measurement.get("post_score")),
            state=ProcedureOutcomeState(raw["state"]),
            reasons=tuple(str(value) for value in raw["reasons"]),
            fab_receipt_id=_optional_string(raw.get("fab_receipt_id")),
            somm_receipt_id=_optional_string(raw.get("somm_receipt_id")),
            evidence_event_ids=tuple(str(value) for value in raw["evidence_event_ids"]),
            recorded_at=parse_datetime(str(raw["recorded_at"])),
        )


class ProcedureCalibrationLedger:
    """Append-only reviewed outcome calibration; exact replay is a no-op."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[ProcedureCalibrationRecord, ...]:
        if not self.path.is_file():
            return ()
        records: list[ProcedureCalibrationRecord] = []
        for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record is not an object")
                records.append(ProcedureCalibrationRecord.from_dict(raw))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValidationError(
                    f"procedure calibration line {lineno} is invalid: {error}"
                ) from error
        return tuple(records)

    def append(self, record: ProcedureCalibrationRecord) -> bool:
        document = canonical_json(record.to_dict())
        for existing in self.load():
            if existing.result_id != record.result_id:
                continue
            if canonical_json(existing.to_dict()) == document:
                return False
            raise RecordConflictError(f"procedure calibration {record.result_id} conflicts")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(document + "\n")
        return True


def build_procedure_calibration(
    store: MiltonStore,
    *,
    spindle_promotion_receipt_id: str,
) -> ProcedureCalibrationRecord:
    """Compare one bound procedure with its baseline using exact public receipts."""

    promotion = store.event_for_ref(
        TypedRef("spindle.promotion-receipt", spindle_promotion_receipt_id)
    )
    if promotion is None:
        raise ValidationError("Spindle promotion receipt is not present in the store")
    origin = _mapping(promotion.attributes.get("origin"))
    evaluation_tuple = _string_tuple(promotion.attributes.get("evaluation_tuple"))
    baseline_tuple = _string_tuple(promotion.attributes.get("baseline_tuple"))
    finding_id = _required_string(origin, "milton_finding_id")
    revision_id = _required_string(origin, "milton_revision_id")
    chip_candidate_id = _required_string(origin, "chip_candidate_id")
    chip_receipt_id = _required_string(origin, "chip_receipt_id")
    evaluation_receipt_id = _required_string(promotion.attributes, "evaluation_receipt_id")
    reasons: list[str] = []
    evidence = {promotion.event_id}

    relation = next(
        (
            item
            for item in store.outgoing_relations(
                TypedRef("milton.finding-revision", revision_id),
                predicates=(RelationKind.PROMOTES,),
            )
            if item.object == TypedRef("spindle.promotion-receipt", spindle_promotion_receipt_id)
        ),
        None,
    )
    if relation is None:
        reasons.append("missing-finding-promotion-relation")
    else:
        evidence.update(relation.evidence_event_ids)

    fab = _matching_fab_outcome(
        store,
        spindle_promotion_receipt_id,
        revision_id,
        evaluation_tuple,
        baseline_tuple,
    )
    if fab is None:
        reasons.append("missing-exact-fab-outcome")
        fab_receipt_id = None
    else:
        evidence.add(fab.event_id)
        fab_receipt_id = _optional_string(fab.attributes.get("receipt_id"))
        if (
            not isinstance(fab.payload, OutcomePayload)
            or fab.payload.status is not OutcomeStatus.SUCCEEDED
        ):
            reasons.append("fab-outcome-not-successful")

    somm = _matching_somm_outcome(
        store,
        spindle_promotion_receipt_id,
        revision_id,
        evaluation_tuple,
        baseline_tuple,
    )
    metric = direction = None
    baseline_score = post_score = None
    somm_receipt_id = None
    if somm is None:
        reasons.append("missing-exact-somm-outcome")
    else:
        evidence.add(somm.event_id)
        somm_receipt_id = somm.source.native_id
        metric = _optional_string(somm.attributes.get("metric"))
        direction = _optional_string(somm.attributes.get("direction"))
        baseline_score = _optional_number(somm.attributes.get("baseline_score"))
        post_score = _optional_number(somm.attributes.get("post_score"))
        post = _mapping(somm.attributes.get("post_promotion"))
        if fab is not None and post.get("fab_receipt_id") != fab_receipt_id:
            reasons.append("fab-somm-receipt-mismatch")

    state = _classify(direction, baseline_score, post_score, reasons)
    recorded_at = max(event.recorded_at for event in (promotion, fab, somm) if event is not None)
    result_id = stable_id(
        "pcr",
        PROCEDURE_CALIBRATION_SCHEMA,
        spindle_promotion_receipt_id,
        evaluation_receipt_id,
        *(sorted(evidence)),
        state.value,
        *(sorted(set(reasons))),
        str(baseline_score),
        str(post_score),
    )
    return ProcedureCalibrationRecord(
        result_id,
        finding_id,
        revision_id,
        chip_candidate_id,
        chip_receipt_id,
        evaluation_receipt_id,
        spindle_promotion_receipt_id,
        evaluation_tuple,
        baseline_tuple,
        metric,
        direction,
        baseline_score,
        post_score,
        state,
        tuple(sorted(set(reasons))),
        fab_receipt_id,
        somm_receipt_id,
        tuple(sorted(evidence)),
        recorded_at,
    )


def _matching_fab_outcome(
    store: MiltonStore,
    promotion_id: str,
    revision_id: str,
    evaluation_tuple: dict[str, str],
    baseline_tuple: dict[str, str],
) -> NormalizedEvent | None:
    matches = [
        event
        for event in store.events(adapter="fab")
        if isinstance(event.payload, OutcomePayload)
        and event.payload.outcome_type == "fab.job"
        and event.attributes.get("spindle_promotion_receipt_id") == promotion_id
        and event.attributes.get("milton_revision_id") == revision_id
        and event.attributes.get("evaluation_tuple") == evaluation_tuple
        and event.attributes.get("baseline_tuple") == baseline_tuple
    ]
    semantic = [event for event in matches if event.attributes.get("semantic") is True]
    selected = semantic or matches
    return selected[-1] if len(selected) == 1 else None


def _matching_somm_outcome(
    store: MiltonStore,
    promotion_id: str,
    revision_id: str,
    evaluation_tuple: dict[str, str],
    baseline_tuple: dict[str, str],
) -> NormalizedEvent | None:
    matches = []
    for event in store.events(adapter="somm"):
        origin = _mapping(event.attributes.get("procedure_origin"))
        if (
            isinstance(event.payload, OutcomePayload)
            and event.payload.outcome_type == "somm.eval-receipt.procedure_outcome"
            and origin.get("spindle_promotion_receipt_id") == promotion_id
            and origin.get("milton_revision_id") == revision_id
            and event.attributes.get("evaluation_tuple") == evaluation_tuple
            and event.attributes.get("baseline_tuple") == baseline_tuple
        ):
            matches.append(event)
    return matches[0] if len(matches) == 1 else None


def _classify(
    direction: str | None,
    baseline_score: float | None,
    post_score: float | None,
    reasons: list[str],
) -> ProcedureOutcomeState:
    if reasons:
        return ProcedureOutcomeState.INCONCLUSIVE
    state = classify_procedure_outcome(direction, baseline_score, post_score)
    if (
        state is ProcedureOutcomeState.INCONCLUSIVE
        and baseline_score is not None
        and post_score is not None
        and baseline_score == post_score
    ):
        reasons.append("no-operational-difference")
    return state


def classify_procedure_outcome(
    direction: str | None,
    baseline_score: float | None,
    post_score: float | None,
) -> ProcedureOutcomeState:
    """Classify an exact baseline/post pair; missing or equal evidence abstains."""

    if direction not in {"higher", "lower"} or baseline_score is None or post_score is None:
        return ProcedureOutcomeState.INCONCLUSIVE
    delta = post_score - baseline_score
    if delta == 0:
        return ProcedureOutcomeState.INCONCLUSIVE
    improved = delta > 0 if direction == "higher" else delta < 0
    return ProcedureOutcomeState.IMPROVEMENT if improved else ProcedureOutcomeState.REGRESSION


def _mapping(value: object) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value) if isinstance(value, dict) else {}


def _string_tuple(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError("procedure tuple must be an object")
    result: dict[str, str] = {}
    for field in _TUPLE_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item:
            raise ValidationError(f"procedure tuple missing {field}")
        result[field] = item
    return result


def _required_string(value: dict[str, JsonValue], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValidationError(f"procedure origin missing {key}")
    return result


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
