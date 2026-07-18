"""Adapter for Chip's public, append-only candidate receipt ledger."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

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

CHIP_CANDIDATE_RECEIPT_SCHEMA = "chip.candidate-receipt/v1"


class _ChipReceipt(TypedDict):
    receiptId: str
    recordedAt: str
    candidateId: str
    sourceId: str
    sourceRevision: str
    occurrenceRefs: list[str]
    counterexampleRefs: list[str]
    fixtureRefs: list[str]
    sourceLimits: dict[str, JsonValue]


class ChipAdapter:
    """Read stable Chip custody receipts without opening Chip's candidate store."""

    name = "chip"

    def default_roots(self) -> tuple[Path, ...]:
        explicit = os.environ.get("MILTON_CHIP_RECEIPTS")
        if explicit:
            return (Path(explicit),)
        sibling = Path.cwd().parent / "chip" / "candidate-receipts.jsonl"
        if sibling.is_file():
            return (sibling,)
        return (Path.cwd() / ".chip" / "candidate-receipts.jsonl",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = (
                [expanded] if expanded.is_file() else expanded.rglob("candidate-receipts*.jsonl")
            )
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
        del content_policy, until  # Receipt fields are already bounded metadata.
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            try:
                handle = source.open(encoding="utf-8")
            except OSError as error:
                stats.warn("source-unreadable", str(error), source)
                return

            with handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    stats.source_records += 1
                    try:
                        raw = json.loads(line)
                        receipt = _validated_receipt(raw)
                        timestamp = parse_datetime(receipt["recordedAt"])
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                        stats.malformed_records += 1
                        stats.warn("malformed-candidate-receipt", str(error), source, line_number)
                        continue
                    if since is not None and timestamp < since:
                        stats.skipped_records += 1
                        continue

                    receipt_id = receipt["receiptId"]
                    candidate_id = receipt["candidateId"]
                    finding_id = _coordinate_value(receipt["sourceId"], "milton.finding=")
                    revision_id = _coordinate_value(
                        receipt["sourceRevision"], "milton.finding-revision="
                    )
                    event = NormalizedEvent.create(
                        source=SourceRef(self.name, receipt_id, str(source)),
                        occurred_at=timestamp,
                        recorded_at=timestamp,
                        payload=OutcomePayload(
                            outcome_type="chip.candidate",
                            status=OutcomeStatus.SUCCEEDED,
                            reference=candidate_id,
                        ),
                        attributes={
                            "candidate_id": candidate_id,
                            "finding_id": finding_id,
                            "finding_revision_id": revision_id,
                            "occurrence_refs": cast(JsonValue, receipt["occurrenceRefs"]),
                            "counterexample_refs": cast(JsonValue, receipt["counterexampleRefs"]),
                            "fixture_refs": cast(JsonValue, receipt["fixtureRefs"]),
                            "source_limits": cast(JsonValue, receipt["sourceLimits"]),
                            "semantic_outcome": "candidate-recorded",
                        },
                    )
                    stats.emitted_records += 1
                    yield event

                    for relation in _receipt_relations(
                        receipt_id,
                        candidate_id,
                        revision_id,
                        event.event_id,
                        timestamp,
                    ):
                        stats.emitted_records += 1
                        yield relation

        return SourceRead(records(), stats)


def _validated_receipt(raw: object) -> _ChipReceipt:
    if not isinstance(raw, dict):
        raise ValueError("candidate receipt is not an object")
    if raw.get("schema") != CHIP_CANDIDATE_RECEIPT_SCHEMA:
        raise ValueError(f"unsupported candidate receipt schema: {raw.get('schema')!r}")
    for key in (
        "receiptId",
        "recordedAt",
        "candidateId",
        "sourceId",
        "sourceRevision",
    ):
        if not isinstance(raw.get(key), str) or not str(raw[key]).strip():
            raise ValueError(f"candidate receipt {key!r} must be a non-empty string")
    for key in ("occurrenceRefs", "counterexampleRefs", "fixtureRefs"):
        values = raw.get(key)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"candidate receipt {key!r} must be a list of strings")
        if values != sorted(set(values)):
            raise ValueError(f"candidate receipt {key!r} must be sorted and unique")
    if not isinstance(raw.get("sourceLimits"), dict):
        raise ValueError("candidate receipt 'sourceLimits' must be an object")
    if raw.get("semanticOutcome") != "candidate-recorded":
        raise ValueError("candidate receipt has an unsupported semanticOutcome")
    _coordinate_value(str(raw["sourceId"]), "milton.finding=")
    _coordinate_value(str(raw["sourceRevision"]), "milton.finding-revision=")
    return cast(_ChipReceipt, raw)


def _coordinate_value(coordinate: str, prefix: str) -> str:
    if not coordinate.startswith(prefix) or not coordinate[len(prefix) :]:
        raise ValueError(f"candidate receipt coordinate must start with {prefix!r}")
    return coordinate[len(prefix) :]


def _receipt_relations(
    receipt_id: str,
    candidate_id: str,
    revision_id: str,
    evidence_event_id: str,
    timestamp: datetime,
) -> Iterator[RelationRecord]:
    evidence = (evidence_event_id,)
    candidate = TypedRef("chip.candidate", candidate_id)
    yield RelationRecord.create(
        subject=TypedRef("milton.finding-revision", revision_id),
        predicate=RelationKind.PRODUCED,
        object=candidate,
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=evidence,
        recorded_at=timestamp,
        note="Chip receipt preserves the exact Milton finding revision origin",
    )
    yield RelationRecord.create(
        subject=TypedRef("chip.candidate-receipt", receipt_id),
        predicate=RelationKind.VERIFIES,
        object=candidate,
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=evidence,
        recorded_at=timestamp,
        note="Chip receipt verifies idempotent candidate custody",
    )
