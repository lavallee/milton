"""Append-only storage for graded, evidence-bearing findings."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import IO, Any

from milton.errors import LedgerCorruptionError, RecordConflictError, ValidationError
from milton.model import (
    JsonValue,
    canonical_json,
    format_datetime,
    parse_datetime,
    stable_id,
    utc_now,
)
from milton.relations import RelationKind, RelationRecord, RelationState, TypedRef
from milton.store import MiltonStore

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


class FindingKind(StrEnum):
    COST_PER_OUTCOME = "cost-per-outcome"
    STALE_GATE = "stale-gate"
    FAILURE_MOTIF = "failure-motif"
    PROCEDURE_CANDIDATE = "procedure-candidate"
    MEMORY_HYGIENE = "memory-hygiene"
    DRIFT = "drift"


class FindingGrade(StrEnum):
    LEAD = "lead"
    CANDIDATE = "candidate"
    CORROBORATED = "corroborated"
    REFUTED = "refuted"


class FindingDisposition(StrEnum):
    NONE = "none"
    EVALUATED = "evaluated"
    ACTED_ON = "acted_on"
    REFUTED = "refuted"
    PROMOTED = "promoted"
    CONFLICTED = "conflicted"


class ReceiptValidity(StrEnum):
    VALID = "valid"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class ReceiptFreshness(StrEnum):
    CURRENT = "current"
    UNKNOWN = "unknown"
    INVALID = "invalid"
    NOT_APPLICABLE = "not_applicable"


ACTION_RELATION_KINDS = (
    RelationKind.ACTS_ON,
    RelationKind.REFUTES,
    RelationKind.EVALUATES,
    RelationKind.PROMOTES,
)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    event_id: str
    role: str

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.role.strip():
            raise ValidationError("evidence event_id and role must not be empty")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"event_id": self.event_id, "role": self.role}


@dataclass(frozen=True, slots=True)
class FindingManifest:
    """The reproducibility and coverage boundary of a finding projection."""

    source_snapshot: str
    generator: str
    scope: dict[str, JsonValue]
    coverage: float
    coverage_gaps: tuple[str, ...]
    generated_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_snapshot.strip() or not self.generator.strip():
            raise ValidationError("manifest source_snapshot and generator must not be empty")
        if not 0 <= self.coverage <= 1:
            raise ValidationError("manifest coverage must be between 0 and 1")
        format_datetime(self.generated_at)
        if self.expires_at is not None:
            format_datetime(self.expires_at)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source_snapshot": self.source_snapshot,
            "generator": self.generator,
            "scope": self.scope,
            "coverage": self.coverage,
            "coverage_gaps": list(self.coverage_gaps),
            "generated_at": format_datetime(self.generated_at),
            "expires_at": format_datetime(self.expires_at) if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FindingManifest:
        return cls(
            source_snapshot=raw["source_snapshot"],
            generator=raw["generator"],
            scope=raw["scope"],
            coverage=float(raw["coverage"]),
            coverage_gaps=tuple(raw["coverage_gaps"]),
            generated_at=parse_datetime(raw["generated_at"]),
            expires_at=parse_datetime(raw["expires_at"]) if raw.get("expires_at") else None,
        )


@dataclass(frozen=True, slots=True)
class FindingRevision:
    """One immutable state in a finding's grading history."""

    revision_id: str
    finding_id: str
    kind: FindingKind
    grade: FindingGrade
    summary: str
    details: dict[str, JsonValue]
    evidence: tuple[EvidenceRef, ...]
    manifest: FindingManifest
    recorded_at: datetime
    supersedes: str | None = None

    def __post_init__(self) -> None:
        if not self.finding_id.strip() or not self.summary.strip():
            raise ValidationError("finding_id and summary must not be empty")
        if not self.evidence:
            raise ValidationError("a finding must carry at least one evidence reference")
        format_datetime(self.recorded_at)

    @classmethod
    def create(
        cls,
        *,
        subject: str,
        kind: FindingKind,
        grade: FindingGrade,
        summary: str,
        details: dict[str, JsonValue],
        evidence: tuple[EvidenceRef, ...],
        manifest: FindingManifest,
        recorded_at: datetime | None = None,
        supersedes: str | None = None,
        finding_id: str | None = None,
    ) -> FindingRevision:
        timestamp = recorded_at or utc_now()
        resolved_finding_id = finding_id or stable_id("fnd", kind.value, subject)
        revision_id = stable_id("fnr", resolved_finding_id, format_datetime(timestamp))
        return cls(
            revision_id=revision_id,
            finding_id=resolved_finding_id,
            kind=kind,
            grade=grade,
            summary=summary,
            details=details,
            evidence=evidence,
            manifest=manifest,
            recorded_at=timestamp,
            supersedes=supersedes,
        )

    def revise(
        self,
        *,
        grade: FindingGrade,
        summary: str | None = None,
        details: dict[str, JsonValue] | None = None,
        evidence: tuple[EvidenceRef, ...] | None = None,
        manifest: FindingManifest | None = None,
        recorded_at: datetime | None = None,
    ) -> FindingRevision:
        return FindingRevision.create(
            subject=self.finding_id,
            finding_id=self.finding_id,
            kind=self.kind,
            grade=grade,
            summary=summary or self.summary,
            details=details if details is not None else self.details,
            evidence=evidence if evidence is not None else self.evidence,
            manifest=manifest or self.manifest,
            recorded_at=recorded_at,
            supersedes=self.revision_id,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "revision_id": self.revision_id,
            "finding_id": self.finding_id,
            "kind": self.kind.value,
            "grade": self.grade.value,
            "summary": self.summary,
            "details": self.details,
            "evidence": [item.to_dict() for item in self.evidence],
            "manifest": self.manifest.to_dict(),
            "recorded_at": format_datetime(self.recorded_at),
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FindingRevision:
        if raw.get("schema_version") != 1:
            raise ValidationError(
                f"unsupported finding schema version: {raw.get('schema_version')!r}"
            )
        return cls(
            revision_id=raw["revision_id"],
            finding_id=raw["finding_id"],
            kind=FindingKind(raw["kind"]),
            grade=FindingGrade(raw["grade"]),
            summary=raw["summary"],
            details=raw["details"],
            evidence=tuple(EvidenceRef(**item) for item in raw["evidence"]),
            manifest=FindingManifest.from_dict(raw["manifest"]),
            recorded_at=parse_datetime(raw["recorded_at"]),
            supersedes=raw.get("supersedes"),
        )


@dataclass(frozen=True, slots=True)
class FindingActionReceipt:
    """Validation state for one action relation's authoritative receipt."""

    relation: RelationRecord
    active: bool
    current_finding_revision: bool
    validity: ReceiptValidity
    freshness: ReceiptFreshness
    receipt_event_id: str | None
    invalidated_by_relation_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "relation": self.relation.to_dict(),
            "active": self.active,
            "current_finding_revision": self.current_finding_revision,
            "validity": self.validity.value,
            "freshness": self.freshness.value,
            "receipt_event_id": self.receipt_event_id,
            "invalidated_by_relation_ids": list(self.invalidated_by_relation_ids),
        }


@dataclass(frozen=True, slots=True)
class FindingActivityProjection:
    """Current and historical action state derived without mutable flags."""

    finding: FindingRevision
    disposition: FindingDisposition
    ever_acted_on: bool
    freshness: ReceiptFreshness
    acted_on: bool
    refuted: bool
    evaluated: bool
    promoted: bool
    receipts: tuple[FindingActionReceipt, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "finding": self.finding.to_dict(),
            "disposition": self.disposition.value,
            "ever_acted_on": self.ever_acted_on,
            "freshness": self.freshness.value,
            "state": {
                "acted_on": self.acted_on,
                "refuted": self.refuted,
                "evaluated": self.evaluated,
                "promoted": self.promoted,
            },
            "receipts": [receipt.to_dict() for receipt in self.receipts],
        }

    def to_text(self) -> str:
        lines = [
            f"Finding {self.finding.finding_id}",
            "",
            f"Grade: {self.finding.grade.value}",
            f"Disposition: {self.disposition.value}",
            f"Ever acted on: {'yes' if self.ever_acted_on else 'no'}",
            f"Receipt freshness: {self.freshness.value}",
            f"Summary: {self.finding.summary}",
            "",
            f"Evidence: {len(self.finding.evidence)}",
        ]
        for evidence in self.finding.evidence:
            lines.append(f"  {evidence.event_id}: {evidence.role}")
        lines.extend(
            [
                "",
                f"Manifest: {self.finding.manifest.generator}",
                f"  snapshot: {self.finding.manifest.source_snapshot}",
                f"  coverage: {self.finding.manifest.coverage:g}",
                "  expires: "
                + (
                    format_datetime(self.finding.manifest.expires_at)
                    if self.finding.manifest.expires_at
                    else "never"
                ),
                "",
                f"Action receipts: {len(self.receipts)}",
            ]
        )
        for receipt in self.receipts:
            relation = receipt.relation
            lines.append(
                f"  {relation.predicate.value} -> "
                f"{relation.object.namespace}={relation.object.value}: "
                f"{relation.state.value}, {receipt.validity.value}, "
                f"freshness={receipt.freshness.value}"
            )
        return "\n".join(lines)


@contextmanager
def _exclusive_lock(handle: IO[str]) -> Iterator[None]:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class FindingLedger:
    """A JSONL audit log that never updates or deletes finding history."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _read_handle(self, handle: IO[str]) -> list[FindingRevision]:
        handle.seek(0)
        records: list[FindingRevision] = []
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValidationError("finding record must be an object")
                records.append(FindingRevision.from_dict(raw))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise LedgerCorruptionError(
                    f"cannot read {self.path} line {line_number}: {error}"
                ) from error
        return records

    def records(self) -> Iterator[FindingRevision]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            yield from self._read_handle(handle)

    def current(self) -> dict[str, FindingRevision]:
        return {record.finding_id: record for record in self.records()}

    def history(self, finding_id: str) -> tuple[FindingRevision, ...]:
        return tuple(record for record in self.records() if record.finding_id == finding_id)

    def append(self, record: FindingRevision) -> bool:
        self.initialize()
        with self.path.open("a+", encoding="utf-8") as handle, _exclusive_lock(handle):
            records = self._read_handle(handle)
            by_revision = {item.revision_id: item for item in records}
            existing_revision = by_revision.get(record.revision_id)
            if existing_revision is not None:
                if existing_revision == record:
                    return False
                raise RecordConflictError(
                    f"finding revision {record.revision_id} has conflicting content"
                )

            current = {item.finding_id: item for item in records}.get(record.finding_id)
            if current is None:
                if record.supersedes is not None:
                    raise ValidationError(
                        "the first revision of a finding cannot supersede a record"
                    )
            else:
                if record.kind is not current.kind:
                    raise ValidationError("a finding's kind cannot change")
                if record.supersedes != current.revision_id:
                    raise ValidationError(
                        f"finding revision must supersede current revision {current.revision_id}"
                    )
                if record.recorded_at <= current.recorded_at:
                    raise ValidationError("finding revisions must move forward in time")
                self._validate_transition(current.grade, record.grade)

            handle.seek(0, os.SEEK_END)
            handle.write(canonical_json(record.to_dict()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return True

    @staticmethod
    def _validate_transition(previous: FindingGrade, current: FindingGrade) -> None:
        ranks = {
            FindingGrade.LEAD: 0,
            FindingGrade.CANDIDATE: 1,
            FindingGrade.CORROBORATED: 2,
        }
        if previous is FindingGrade.REFUTED and current is not FindingGrade.REFUTED:
            raise ValidationError("a refuted finding cannot be silently revived")
        if current is not FindingGrade.REFUTED and ranks[current] < ranks[previous]:
            raise ValidationError("a finding cannot move backward on the grading ladder")


def build_finding_activity(
    store: MiltonStore,
    ledger: FindingLedger,
    finding_id: str,
) -> FindingActivityProjection:
    """Derive disposition from exact finding revisions and valid receipts."""

    revisions = ledger.history(finding_id)
    if not revisions:
        raise ValidationError(f"finding does not exist: {finding_id}")
    current = revisions[-1]
    revision_refs = {
        TypedRef("milton.finding-revision", revision.revision_id): revision
        for revision in revisions
    }
    histories: dict[str, list[RelationRecord]] = {}
    for revision_ref in revision_refs:
        for relation in store.relation_records(
            subject=revision_ref,
            predicates=ACTION_RELATION_KINDS,
        ):
            histories.setdefault(relation.relation_id, []).append(relation)

    receipts: list[FindingActionReceipt] = []
    current_ref = TypedRef("milton.finding-revision", current.revision_id)
    for history in histories.values():
        relation = history[-1]
        active = relation.state is RelationState.ASSERTED
        validity, freshness, event_id, invalidators = _validate_action_receipt(store, relation)
        receipts.append(
            FindingActionReceipt(
                relation=relation,
                active=active,
                current_finding_revision=relation.subject == current_ref,
                validity=validity,
                freshness=freshness,
                receipt_event_id=event_id,
                invalidated_by_relation_ids=invalidators,
            )
        )
    receipts.sort(
        key=lambda item: (
            item.relation.recorded_at,
            item.relation.predicate.value,
            item.relation.relation_id,
        )
    )

    current_valid = tuple(
        receipt
        for receipt in receipts
        if receipt.active
        and receipt.current_finding_revision
        and receipt.validity is ReceiptValidity.VALID
    )
    predicates = {receipt.relation.predicate for receipt in current_valid}
    promoted = RelationKind.PROMOTES in predicates
    acted_on = RelationKind.ACTS_ON in predicates or promoted
    refuted = RelationKind.REFUTES in predicates
    evaluated = RelationKind.EVALUATES in predicates
    disposition = _disposition(
        acted_on=acted_on,
        refuted=refuted,
        evaluated=evaluated,
        promoted=promoted,
    )
    ever_acted_on = any(
        receipt.active
        and receipt.validity is ReceiptValidity.VALID
        and receipt.relation.predicate in (RelationKind.ACTS_ON, RelationKind.PROMOTES)
        for receipt in receipts
    )
    current_receipts = tuple(
        receipt for receipt in receipts if receipt.active and receipt.current_finding_revision
    )
    return FindingActivityProjection(
        finding=current,
        disposition=disposition,
        ever_acted_on=ever_acted_on,
        freshness=_projection_freshness(current_receipts),
        acted_on=acted_on,
        refuted=refuted,
        evaluated=evaluated,
        promoted=promoted,
        receipts=tuple(receipts),
    )


def build_finding_export(
    store: MiltonStore,
    ledger: FindingLedger,
    finding_id: str,
) -> dict[str, JsonValue]:
    """Build a deterministic, immutable finding and receipt custody document."""

    history = ledger.history(finding_id)
    if not history:
        raise ValidationError(f"finding does not exist: {finding_id}")
    relation_history: list[RelationRecord] = []
    for revision in history:
        relation_history.extend(
            store.relation_records(
                subject=TypedRef("milton.finding-revision", revision.revision_id),
                predicates=ACTION_RELATION_KINDS,
            )
        )
    export_id = stable_id(
        "fex",
        *(revision.revision_id for revision in history),
        *(relation.record_id for relation in relation_history),
    )
    return {
        "schema_version": 1,
        "export_id": export_id,
        "finding_id": finding_id,
        "finding_history": [revision.to_dict() for revision in history],
        "relation_history": [relation.to_dict() for relation in relation_history],
        "activity": build_finding_activity(store, ledger, finding_id).to_dict(),
    }


def _validate_action_receipt(
    store: MiltonStore,
    relation: RelationRecord,
) -> tuple[ReceiptValidity, ReceiptFreshness, str | None, tuple[str, ...]]:
    invalidators = tuple(
        item.relation_id
        for item in store.incoming_relations(
            relation.object,
            predicates=(RelationKind.REFUTES,),
        )
        if item.subject.namespace != "milton.finding-revision"
    )
    event = store.event_for_ref(relation.object)
    adapter = event.source.adapter if event is not None else store.adapter_for_ref(relation.object)
    freshness = _adapter_freshness(store, adapter)
    if invalidators:
        return (
            ReceiptValidity.INVALID,
            ReceiptFreshness.INVALID,
            (event.event_id if event else None),
            invalidators,
        )
    if event is not None:
        return ReceiptValidity.VALID, freshness, event.event_id, ()
    if freshness is ReceiptFreshness.CURRENT:
        return ReceiptValidity.INVALID, ReceiptFreshness.INVALID, None, ()
    return ReceiptValidity.UNKNOWN, ReceiptFreshness.UNKNOWN, None, ()


def _adapter_freshness(store: MiltonStore, adapter: str | None) -> ReceiptFreshness:
    if adapter is None:
        return ReceiptFreshness.UNKNOWN
    coverage = store.source_coverage().get(adapter)
    if coverage is None:
        return ReceiptFreshness.UNKNOWN
    if coverage.status != "ok" or coverage.sources_failed or coverage.sources_outside_window:
        return ReceiptFreshness.UNKNOWN
    return ReceiptFreshness.CURRENT


def _projection_freshness(
    receipts: tuple[FindingActionReceipt, ...],
) -> ReceiptFreshness:
    if not receipts:
        return ReceiptFreshness.NOT_APPLICABLE
    values = {receipt.freshness for receipt in receipts}
    if ReceiptFreshness.INVALID in values:
        return ReceiptFreshness.INVALID
    if ReceiptFreshness.UNKNOWN in values:
        return ReceiptFreshness.UNKNOWN
    return ReceiptFreshness.CURRENT


def _disposition(
    *, acted_on: bool, refuted: bool, evaluated: bool, promoted: bool
) -> FindingDisposition:
    if refuted and acted_on:
        return FindingDisposition.CONFLICTED
    if promoted:
        return FindingDisposition.PROMOTED
    if acted_on:
        return FindingDisposition.ACTED_ON
    if refuted:
        return FindingDisposition.REFUTED
    if evaluated:
        return FindingDisposition.EVALUATED
    return FindingDisposition.NONE
