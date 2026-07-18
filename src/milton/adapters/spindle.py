"""Adapter for Spindle's public procedure evaluation and promotion receipts."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from milton.adapters.base import AdapterRecord, ContentPolicy, ReadStats, SourceRead
from milton.model import (
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
    parse_datetime,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef

EVALUATION_SCHEMA = "spindle.evaluation-receipt/v2"
PROMOTION_SCHEMA = "spindle.procedure-promotion/v1"
ORIGIN_SCHEMA = "spindle.procedure-origin/v1"
_ORIGIN_FIELDS = (
    "milton_finding_id",
    "milton_revision_id",
    "chip_candidate_id",
    "chip_receipt_id",
)
_TUPLE_FIELDS = ("implementation", "profile", "model", "harness")


class SpindleAdapter:
    name = "spindle"

    def default_roots(self) -> tuple[Path, ...]:
        explicit = os.environ.get("MILTON_SPINDLE_RECEIPTS")
        if explicit:
            return (Path(explicit),)
        return (Path(os.environ.get("SPINDLE_HOME", Path.home() / ".spindle")) / "receipts",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = [expanded] if expanded.is_file() else expanded.rglob("*receipt*.json")
            for candidate in candidates:
                resolved = candidate.resolve()
                if candidate.is_file() and resolved not in seen:
                    seen.add(resolved)
                    yield candidate

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del content_policy, until  # Procedure receipts contain bounded coordinates and scores.
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            stats.source_records += 1
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
                receipt = _validated_receipt(raw)
                timestamp = parse_datetime(str(receipt["recorded_at"]))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                stats.malformed_records += 1
                stats.warn("malformed-spindle-receipt", str(error), source)
                return
            if since is not None and timestamp < since:
                stats.skipped_records += 1
                return

            schema = str(receipt["schema"])
            receipt_id = str(receipt["receipt_id"])
            origin = cast(dict[str, str], receipt["origin"])
            evaluation_tuple = cast(dict[str, str], receipt["evaluation_tuple"])
            baseline_tuple = cast(dict[str, str], receipt["baseline_tuple"])
            if schema == EVALUATION_SCHEMA:
                promotion = cast(dict[str, object], receipt["promotion"])
                eligible = promotion.get("eligible") is True
                outcome_type = "spindle.evaluation"
                status = OutcomeStatus.SUCCEEDED if eligible else OutcomeStatus.FAILED
                reference = str(receipt["evaluation_id"])
                attributes: dict[str, JsonValue] = {
                    "evaluation_id": reference,
                    "evaluation_tuple": cast(JsonValue, evaluation_tuple),
                    "baseline_tuple": cast(JsonValue, baseline_tuple),
                    "origin": cast(JsonValue, origin),
                    "eligible": eligible,
                    "observed_delta": _number(promotion.get("observed_delta")),
                    "required_improvement": _number(promotion.get("required_improvement")),
                }
                receipt_namespace = "spindle.evaluation-receipt"
            else:
                decision = cast(dict[str, object], receipt["decision"])
                binding = cast(dict[str, object], receipt["binding"])
                outcome_type = "spindle.promotion"
                status = (
                    OutcomeStatus.SUCCEEDED
                    if decision.get("eligible") is True
                    else OutcomeStatus.FAILED
                )
                reference = str(binding["coordinate"])
                attributes = {
                    "evaluation_receipt_id": str(receipt["evaluation_receipt_id"]),
                    "evaluation_tuple": cast(JsonValue, evaluation_tuple),
                    "baseline_tuple": cast(JsonValue, baseline_tuple),
                    "origin": cast(JsonValue, origin),
                    "binding": cast(JsonValue, binding),
                    "eligible": decision.get("eligible") is True,
                    "observed_delta": _number(decision.get("observed_delta")),
                    "required_improvement": _number(decision.get("required_improvement")),
                }
                receipt_namespace = "spindle.promotion-receipt"

            event = NormalizedEvent.create(
                source=SourceRef(self.name, receipt_id, str(source)),
                occurred_at=timestamp,
                recorded_at=timestamp,
                payload=OutcomePayload(outcome_type, status, reference),
                attributes=attributes,
            )
            stats.emitted_records += 1
            yield event
            for relation in _receipt_relations(
                schema,
                receipt_namespace,
                receipt_id,
                origin,
                receipt,
                event.event_id,
                timestamp,
            ):
                stats.emitted_records += 1
                yield relation

        return SourceRead(records(), stats)


def _validated_receipt(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema") not in {
        EVALUATION_SCHEMA,
        PROMOTION_SCHEMA,
    }:
        raise ValueError("unsupported Spindle procedure receipt schema")
    for key in ("receipt_id", "origin", "evaluation_tuple", "baseline_tuple"):
        if key not in raw:
            raise ValueError(f"Spindle receipt missing {key}")
    origin = raw["origin"]
    if not isinstance(origin, dict) or origin.get("schema") != ORIGIN_SCHEMA:
        raise ValueError("Spindle receipt has invalid procedure origin")
    _require_strings(origin, _ORIGIN_FIELDS, "origin")
    for name in ("evaluation_tuple", "baseline_tuple"):
        value = raw[name]
        if not isinstance(value, dict):
            raise ValueError(f"Spindle receipt {name} must be an object")
        _require_strings(value, _TUPLE_FIELDS, name)
    if raw["schema"] == EVALUATION_SCHEMA:
        if not isinstance(raw.get("created_at"), str):
            raise ValueError("Spindle evaluation receipt missing created_at")
        raw["recorded_at"] = raw["created_at"]
        if not isinstance(raw.get("promotion"), dict) or not isinstance(
            raw.get("evaluation_id"), str
        ):
            raise ValueError("Spindle evaluation receipt is incomplete")
    else:
        if not isinstance(raw.get("recorded_at"), str):
            raise ValueError("Spindle promotion receipt missing recorded_at")
        if not isinstance(raw.get("decision"), dict) or not isinstance(raw.get("binding"), dict):
            raise ValueError("Spindle promotion receipt is incomplete")
        if not isinstance(raw.get("evaluation_receipt_id"), str):
            raise ValueError("Spindle promotion receipt has no evaluation receipt")
    return raw


def _receipt_relations(
    schema: str,
    receipt_namespace: str,
    receipt_id: str,
    origin: dict[str, str],
    receipt: dict[str, Any],
    evidence_event_id: str,
    timestamp: datetime,
) -> Iterator[RelationRecord]:
    evidence = (evidence_event_id,)
    receipt_ref = TypedRef(receipt_namespace, receipt_id)
    predicate = RelationKind.EVALUATES if schema == EVALUATION_SCHEMA else RelationKind.PROMOTES
    yield RelationRecord.create(
        subject=TypedRef("milton.finding-revision", origin["milton_revision_id"]),
        predicate=predicate,
        object=receipt_ref,
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=evidence,
        recorded_at=timestamp,
        note="Spindle receipt preserves exact Milton procedure origin",
    )
    yield RelationRecord.create(
        subject=receipt_ref,
        predicate=predicate,
        object=TypedRef("chip.candidate", origin["chip_candidate_id"]),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=evidence,
        recorded_at=timestamp,
        note="Spindle evaluates or promotes the exact Chip candidate",
    )
    if schema == PROMOTION_SCHEMA:
        binding = cast(dict[str, object], receipt["binding"])
        yield RelationRecord.create(
            subject=receipt_ref,
            predicate=RelationKind.PRODUCED,
            object=TypedRef("spindle.binding", str(binding["coordinate"])),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=evidence,
            recorded_at=timestamp,
            note="Spindle promotion receipt names the evaluated binding",
        )


def _require_strings(value: dict[str, object], fields: tuple[str, ...], name: str) -> None:
    if any(
        not isinstance(value.get(field), str) or not str(value[field]).strip() for field in fields
    ):
        raise ValueError(f"Spindle receipt {name} must contain {', '.join(fields)}")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
