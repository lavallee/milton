"""Typed, directed, refutable workflow and causal relations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from milton.crosswalk import ExternalIdentity
from milton.errors import ValidationError
from milton.model import JsonValue, format_datetime, parse_datetime, stable_id, utc_now


class RelationKind(StrEnum):
    """The deliberately bounded v1 relation vocabulary."""

    PART_OF = "part_of"
    ATTEMPT_OF = "attempt_of"
    PRODUCED = "produced"
    VERIFIES = "verifies"
    EVALUATES = "evaluates"
    ACTS_ON = "acts_on"
    REFUTES = "refutes"
    PROMOTES = "promotes"


class RelationMethod(StrEnum):
    """How a producer established a directed relation."""

    EXPLICIT = "explicit"
    EXACT = "exact"
    SOURCE_RECEIPT = "source_receipt"
    INFERRED = "inferred"
    HUMAN = "human"


class RelationState(StrEnum):
    ASSERTED = "asserted"
    REFUTED = "refuted"


class RelationDirection(StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass(frozen=True, order=True, slots=True)
class TypedRef:
    """A typed reference used as one endpoint of a directed relation."""

    namespace: str
    value: str

    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.value.strip():
            raise ValidationError("reference namespace and value must not be empty")
        if self.namespace != self.namespace.strip() or self.value != self.value.strip():
            raise ValidationError("reference namespace and value must not have outer whitespace")

    @classmethod
    def from_identity(cls, identity: ExternalIdentity) -> TypedRef:
        return cls(identity.namespace, identity.value)

    def to_identity(self) -> ExternalIdentity:
        return ExternalIdentity(self.namespace, self.value)

    def to_dict(self) -> dict[str, JsonValue]:
        return {"namespace": self.namespace, "value": self.value}

    @classmethod
    def from_dict(cls, raw: object) -> TypedRef:
        if not isinstance(raw, dict):
            raise ValidationError("relation endpoint must be an object")
        namespace = raw.get("namespace")
        value = raw.get("value")
        if not isinstance(namespace, str) or not isinstance(value, str):
            raise ValidationError("relation endpoint namespace and value must be strings")
        return cls(namespace, value)


@dataclass(frozen=True, slots=True)
class RelationRecord:
    """One immutable revision of a directed relation."""

    record_id: str
    relation_id: str
    subject: TypedRef
    predicate: RelationKind
    object: TypedRef
    state: RelationState
    confidence: float
    method: RelationMethod
    evidence_event_ids: tuple[str, ...]
    recorded_at: datetime
    supersedes: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.subject == self.object:
            raise ValidationError("a relation cannot point a reference to itself")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("relation confidence must be between 0 and 1")
        if tuple(sorted(set(self.evidence_event_ids))) != self.evidence_event_ids:
            raise ValidationError("relation evidence_event_ids must be unique and sorted")
        if any(not item.strip() for item in self.evidence_event_ids):
            raise ValidationError("relation evidence ids must not be empty")
        if self.note is not None and not self.note.strip():
            raise ValidationError("relation note must not be empty")
        if self.state is RelationState.ASSERTED and self.supersedes is not None:
            raise ValidationError("an asserted relation cannot supersede another revision")
        if self.state is RelationState.REFUTED:
            if self.supersedes is None:
                raise ValidationError("a relation refutation must supersede an assertion")
            if self.confidence != 0:
                raise ValidationError("a relation refutation must have zero confidence")
            if self.note is None:
                raise ValidationError("a relation refutation must explain why")
        format_datetime(self.recorded_at)
        if self.relation_id != self._relation_id():
            raise ValidationError("relation_id does not match its directed endpoints")
        if self.record_id != self._record_id():
            raise ValidationError("relation record_id does not match its revision content")

    def _relation_id(self) -> str:
        return self._derive_relation_id(self.subject, self.predicate, self.object)

    @staticmethod
    def _derive_relation_id(
        subject: TypedRef, predicate: RelationKind, object_ref: TypedRef
    ) -> str:
        return stable_id(
            "rel",
            subject.namespace,
            subject.value,
            predicate.value,
            object_ref.namespace,
            object_ref.value,
        )

    def _record_id(self) -> str:
        return self._derive_record_id(
            relation_id=self.relation_id,
            state=self.state,
            confidence=self.confidence,
            method=self.method,
            evidence_event_ids=self.evidence_event_ids,
            recorded_at=self.recorded_at,
            supersedes=self.supersedes,
            note=self.note,
        )

    @staticmethod
    def _derive_record_id(
        *,
        relation_id: str,
        state: RelationState,
        confidence: float,
        method: RelationMethod,
        evidence_event_ids: tuple[str, ...],
        recorded_at: datetime,
        supersedes: str | None,
        note: str | None,
    ) -> str:
        return stable_id(
            "rrv",
            relation_id,
            state.value,
            str(float(confidence)),
            method.value,
            format_datetime(recorded_at),
            supersedes or "",
            note or "",
            *evidence_event_ids,
        )

    @classmethod
    def create(
        cls,
        *,
        subject: TypedRef,
        predicate: RelationKind,
        object: TypedRef,
        confidence: float,
        method: RelationMethod,
        evidence_event_ids: tuple[str, ...] = (),
        recorded_at: datetime | None = None,
        note: str | None = None,
    ) -> RelationRecord:
        timestamp = recorded_at or utc_now()
        evidence = tuple(sorted(set(evidence_event_ids)))
        relation_id = cls._derive_relation_id(subject, predicate, object)
        record_id = cls._derive_record_id(
            relation_id=relation_id,
            state=RelationState.ASSERTED,
            confidence=float(confidence),
            method=method,
            evidence_event_ids=evidence,
            recorded_at=timestamp,
            supersedes=None,
            note=note,
        )
        return cls(
            record_id=record_id,
            relation_id=relation_id,
            subject=subject,
            predicate=predicate,
            object=object,
            state=RelationState.ASSERTED,
            confidence=float(confidence),
            method=method,
            evidence_event_ids=evidence,
            recorded_at=timestamp,
            note=note,
        )

    def refute(
        self,
        *,
        note: str,
        recorded_at: datetime | None = None,
        evidence_event_ids: tuple[str, ...] = (),
    ) -> RelationRecord:
        if self.state is RelationState.REFUTED:
            raise ValidationError("a refuted relation cannot be refuted again")
        timestamp = recorded_at or utc_now()
        evidence = tuple(sorted(set(evidence_event_ids)))
        record_id = self._derive_record_id(
            relation_id=self.relation_id,
            state=RelationState.REFUTED,
            confidence=0,
            method=self.method,
            evidence_event_ids=evidence,
            recorded_at=timestamp,
            supersedes=self.record_id,
            note=note,
        )
        return RelationRecord(
            record_id=record_id,
            relation_id=self.relation_id,
            subject=self.subject,
            predicate=self.predicate,
            object=self.object,
            state=RelationState.REFUTED,
            confidence=0,
            method=self.method,
            evidence_event_ids=evidence,
            recorded_at=timestamp,
            supersedes=self.record_id,
            note=note,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "record_id": self.record_id,
            "relation_id": self.relation_id,
            "subject": self.subject.to_dict(),
            "predicate": self.predicate.value,
            "object": self.object.to_dict(),
            "state": self.state.value,
            "confidence": self.confidence,
            "method": self.method.value,
            "evidence_event_ids": list(self.evidence_event_ids),
            "recorded_at": format_datetime(self.recorded_at),
            "supersedes": self.supersedes,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RelationRecord:
        if raw.get("schema_version") != 1:
            raise ValidationError(
                f"unsupported relation schema version: {raw.get('schema_version')!r}"
            )
        confidence = raw.get("confidence")
        if not isinstance(confidence, int | float):
            raise ValidationError("relation confidence must be numeric")
        evidence = raw.get("evidence_event_ids")
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            raise ValidationError("relation evidence_event_ids must be a string list")
        try:
            return cls(
                record_id=str(raw["record_id"]),
                relation_id=str(raw["relation_id"]),
                subject=TypedRef.from_dict(raw.get("subject")),
                predicate=RelationKind(str(raw["predicate"])),
                object=TypedRef.from_dict(raw.get("object")),
                state=RelationState(str(raw["state"])),
                confidence=float(confidence),
                method=RelationMethod(str(raw["method"])),
                evidence_event_ids=tuple(evidence),
                recorded_at=parse_datetime(str(raw["recorded_at"])),
                supersedes=(str(raw["supersedes"]) if raw.get("supersedes") is not None else None),
                note=str(raw["note"]) if raw.get("note") is not None else None,
            )
        except KeyError as error:
            raise ValidationError(f"missing relation field: {error.args[0]}") from error
        except ValueError as error:
            raise ValidationError(f"invalid relation enum value: {error}") from error
