"""Refutable joins between identifiers owned by different systems."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from milton.errors import ValidationError
from milton.model import JsonValue, format_datetime, parse_datetime, stable_id, utc_now


class JoinMethod(StrEnum):
    EXPLICIT = "explicit"
    EXACT = "exact"
    TEMPORAL = "temporal"
    INFERRED = "inferred"
    HUMAN = "human"


class JoinState(StrEnum):
    ASSERTED = "asserted"
    REFUTED = "refuted"


@dataclass(frozen=True, order=True, slots=True)
class ExternalIdentity:
    namespace: str
    value: str

    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.value.strip():
            raise ValidationError("identity namespace and value must not be empty")


@dataclass(frozen=True, slots=True)
class CrosswalkRecord:
    """One immutable revision of a cross-system identity join."""

    record_id: str
    link_id: str
    left: ExternalIdentity
    right: ExternalIdentity
    state: JoinState
    confidence: float
    method: JoinMethod
    evidence_event_ids: tuple[str, ...]
    recorded_at: datetime
    supersedes: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.left == self.right:
            raise ValidationError("a crosswalk cannot link an identity to itself")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("crosswalk confidence must be between 0 and 1")
        if self.state is JoinState.REFUTED and self.supersedes is None:
            raise ValidationError("a refutation must supersede an asserted record")
        format_datetime(self.recorded_at)

    @classmethod
    def create(
        cls,
        *,
        left: ExternalIdentity,
        right: ExternalIdentity,
        confidence: float,
        method: JoinMethod,
        evidence_event_ids: tuple[str, ...] = (),
        recorded_at: datetime | None = None,
        note: str | None = None,
    ) -> CrosswalkRecord:
        left, right = sorted((left, right))
        timestamp = recorded_at or utc_now()
        link_id = stable_id("xwl", left.namespace, left.value, right.namespace, right.value)
        record_id = stable_id("xwr", link_id, JoinState.ASSERTED.value, format_datetime(timestamp))
        return cls(
            record_id=record_id,
            link_id=link_id,
            left=left,
            right=right,
            state=JoinState.ASSERTED,
            confidence=confidence,
            method=method,
            evidence_event_ids=evidence_event_ids,
            recorded_at=timestamp,
            note=note,
        )

    def refute(
        self,
        *,
        note: str,
        recorded_at: datetime | None = None,
        evidence_event_ids: tuple[str, ...] = (),
    ) -> CrosswalkRecord:
        timestamp = recorded_at or utc_now()
        return CrosswalkRecord(
            record_id=stable_id(
                "xwr", self.link_id, JoinState.REFUTED.value, format_datetime(timestamp)
            ),
            link_id=self.link_id,
            left=self.left,
            right=self.right,
            state=JoinState.REFUTED,
            confidence=0,
            method=self.method,
            evidence_event_ids=evidence_event_ids,
            recorded_at=timestamp,
            supersedes=self.record_id,
            note=note,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "record_id": self.record_id,
            "link_id": self.link_id,
            "left": {"namespace": self.left.namespace, "value": self.left.value},
            "right": {"namespace": self.right.namespace, "value": self.right.value},
            "state": self.state.value,
            "confidence": self.confidence,
            "method": self.method.value,
            "evidence_event_ids": list(self.evidence_event_ids),
            "recorded_at": format_datetime(self.recorded_at),
            "supersedes": self.supersedes,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> CrosswalkRecord:
        if raw.get("schema_version") != 1:
            raise ValidationError(
                f"unsupported crosswalk schema version: {raw.get('schema_version')!r}"
            )
        left = raw["left"]
        right = raw["right"]
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise ValidationError("crosswalk identities must be objects")
        evidence = raw["evidence_event_ids"]
        if not isinstance(evidence, list):
            raise ValidationError("crosswalk evidence_event_ids must be a list")
        confidence = raw["confidence"]
        if not isinstance(confidence, int | float):
            raise ValidationError("crosswalk confidence must be numeric")
        return cls(
            record_id=str(raw["record_id"]),
            link_id=str(raw["link_id"]),
            left=ExternalIdentity(str(left["namespace"]), str(left["value"])),
            right=ExternalIdentity(str(right["namespace"]), str(right["value"])),
            state=JoinState(str(raw["state"])),
            confidence=float(confidence),
            method=JoinMethod(str(raw["method"])),
            evidence_event_ids=tuple(str(item) for item in evidence),
            recorded_at=parse_datetime(str(raw["recorded_at"])),
            supersedes=str(raw["supersedes"]) if raw.get("supersedes") is not None else None,
            note=str(raw["note"]) if raw.get("note") is not None else None,
        )
