"""Typed, source-independent records used by every Milton adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, cast

from milton.errors import ValidationError

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class EventKind(StrEnum):
    SESSION = "session"
    TURN = "turn"
    TOOL_CALL = "tool-call"
    MODEL_CALL = "model-call"
    COST = "cost"
    OUTCOME = "outcome"
    GATE_EVIDENCE = "gate-evidence"
    MEMORY_EVIDENCE = "memory-evidence"


class CoverageStatus(StrEnum):
    """How an adapter populated one field of a normalized payload."""

    RECOVERED = "recovered"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"


class CallStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class OutcomeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVERTED = "reverted"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class GateEvidenceKind(StrEnum):
    """Which source-owned event was observed in a gate lifecycle."""

    MINT = "mint"
    CONSULT = "consult"
    DECISION = "decision"
    DISPOSITION = "disposition"


class GateStatus(StrEnum):
    """Producer-declared gate state; absence is represented separately by coverage."""

    OPEN = "open"
    RESOLVED = "resolved"
    RETIRED = "retired"
    REFUTED = "refuted"
    DEFERRED = "deferred"
    ACTED = "acted"
    UNKNOWN = "unknown"


class GateConsultation(StrEnum):
    """Explicit consultation evidence; missing read evidence remains ``None``."""

    CONSULTED = "consulted"
    NOT_CONSULTED = "not_consulted"


class MemoryStage(StrEnum):
    INVENTORY = "inventory"
    LOADED = "loaded"
    RETRIEVED = "retrieved"
    REFERENCED = "referenced"
    APPLIED = "applied"
    UNKNOWN = "unknown"


class MemoryItemKind(StrEnum):
    FILE = "file"
    RULE = "rule"
    SKILL = "skill"
    DECISION = "decision"


class MemoryEvidenceState(StrEnum):
    OBSERVED = "observed"
    NOT_OBSERVED = "not_observed"


class CostBasis(StrEnum):
    """How the monetary amount entered the source record."""

    REPORTED = "reported"
    COMPUTED = "computed"
    UNKNOWN = "unknown"


class CostKind(StrEnum):
    """Which economic quantity an amount represents."""

    MARGINAL = "marginal"
    NOTIONAL = "notional"
    INCLUDED = "included"
    UNKNOWN = "unknown"


class CostAccuracy(StrEnum):
    """Whether the source considers the amount settled or estimated."""

    ACTUAL = "actual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class CostKeyScope(StrEnum):
    """Whether an accounting key can be compared across source systems."""

    SOURCE = "source"
    SHARED = "shared"
    UNKNOWN = "unknown"


class CostObservationRole(StrEnum):
    """The operational role of one monetary observation."""

    PRODUCTION = "production"
    SHADOW_GOLD = "shadow_gold"
    SHADOW_JUDGE = "shadow_judge"
    EVAL = "eval"
    IMPORTED = "imported"
    ROLLUP = "rollup"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """The native identity of a record before normalization."""

    adapter: str
    native_id: str
    location: str | None = None

    def __post_init__(self) -> None:
        if not self.adapter.strip():
            raise ValidationError("source adapter must not be empty")
        if not self.native_id.strip():
            raise ValidationError("source native_id must not be empty")


@dataclass(frozen=True, slots=True)
class SessionPayload:
    project: str | None
    working_directory: str | None
    status: str | None
    harness: str | None = None

    KIND: ClassVar[EventKind] = EventKind.SESSION


@dataclass(frozen=True, slots=True)
class TurnPayload:
    role: str | None
    content: str | None
    content_sha256: str | None = None
    content_chars: int | None = None

    KIND: ClassVar[EventKind] = EventKind.TURN


@dataclass(frozen=True, slots=True)
class ToolCallPayload:
    tool_name: str | None
    status: CallStatus
    input: JsonValue
    output: JsonValue
    error: str | None

    KIND: ClassVar[EventKind] = EventKind.TOOL_CALL


@dataclass(frozen=True, slots=True)
class ModelCallPayload:
    provider: str | None
    model: str | None
    status: CallStatus
    finish_reason: str | None

    KIND: ClassVar[EventKind] = EventKind.MODEL_CALL


@dataclass(frozen=True, slots=True)
class CostPayload:
    amount_usd: Decimal | None
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    provider: str | None
    model: str | None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    basis: CostBasis = CostBasis.UNKNOWN
    kind: CostKind = CostKind.UNKNOWN
    accuracy: CostAccuracy = CostAccuracy.UNKNOWN
    authority: str | None = None
    pricing_version: str | None = None
    accounting_key: str | None = None
    accounting_key_scope: CostKeyScope = CostKeyScope.UNKNOWN
    observation_role: CostObservationRole = CostObservationRole.UNKNOWN

    KIND: ClassVar[EventKind] = EventKind.COST

    def __post_init__(self) -> None:
        if self.amount_usd is not None and self.amount_usd < 0:
            raise ValidationError("amount_usd must not be negative")
        for name in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValidationError(f"{name} must not be negative")
        for name in ("authority", "pricing_version", "accounting_key"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValidationError(f"{name} must not be empty")
        if self.accounting_key is None and self.accounting_key_scope is not CostKeyScope.UNKNOWN:
            raise ValidationError("accounting_key_scope requires accounting_key")


@dataclass(frozen=True, slots=True)
class OutcomePayload:
    outcome_type: str | None
    status: OutcomeStatus
    reference: str | None

    KIND: ClassVar[EventKind] = EventKind.OUTCOME


@dataclass(frozen=True, slots=True)
class GateEvidencePayload:
    evidence_kind: GateEvidenceKind
    coordinate: str | None
    mint_id: str | None
    status: GateStatus
    consultation: GateConsultation | None = None
    disposition: str | None = None

    KIND: ClassVar[EventKind] = EventKind.GATE_EVIDENCE

    def __post_init__(self) -> None:
        for name in ("coordinate", "mint_id", "disposition"):
            value = getattr(self, name)
            if value is not None and (not value.strip() or value != value.strip()):
                raise ValidationError(f"gate {name} must be non-empty without outer whitespace")


@dataclass(frozen=True, slots=True)
class MemoryEvidencePayload:
    system: str
    item_id: str
    item_kind: MemoryItemKind
    stage: MemoryStage
    state: MemoryEvidenceState
    evidence_reference: str | None = None
    superseded_by: str | None = None

    KIND: ClassVar[EventKind] = EventKind.MEMORY_EVIDENCE

    def __post_init__(self) -> None:
        for name in ("system", "item_id"):
            value = getattr(self, name)
            if not value.strip() or value != value.strip():
                raise ValidationError(f"memory {name} must be non-empty without outer whitespace")
        for name in ("evidence_reference", "superseded_by"):
            value = getattr(self, name)
            if value is not None and (not value.strip() or value != value.strip()):
                raise ValidationError(f"memory {name} must be non-empty without outer whitespace")
        if self.stage is MemoryStage.UNKNOWN:
            raise ValidationError("unknown is a projection state, not source evidence")


type EventPayload = (
    SessionPayload
    | TurnPayload
    | ToolCallPayload
    | ModelCallPayload
    | CostPayload
    | OutcomePayload
    | GateEvidencePayload
    | MemoryEvidencePayload
)

_PAYLOAD_TYPES: dict[EventKind, type[EventPayload]] = {
    payload_type.KIND: payload_type
    for payload_type in (
        SessionPayload,
        TurnPayload,
        ToolCallPayload,
        ModelCallPayload,
        CostPayload,
        OutcomePayload,
        GateEvidencePayload,
        MemoryEvidencePayload,
    )
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError("timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def canonical_json(value: JsonValue) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def payload_to_dict(payload: EventPayload) -> dict[str, JsonValue]:
    raw = asdict(payload)
    if isinstance(payload, CostPayload) and payload.amount_usd is not None:
        raw["amount_usd"] = str(payload.amount_usd)
    return cast(dict[str, JsonValue], raw)


def _payload_from_dict(kind: EventKind, raw: dict[str, Any]) -> EventPayload:
    payload_type = _PAYLOAD_TYPES[kind]
    values = dict(raw)
    if kind in {EventKind.TOOL_CALL, EventKind.MODEL_CALL}:
        values["status"] = CallStatus(values["status"])
    elif kind is EventKind.OUTCOME:
        values["status"] = OutcomeStatus(values["status"])
    elif kind is EventKind.GATE_EVIDENCE:
        values["evidence_kind"] = GateEvidenceKind(values["evidence_kind"])
        values["status"] = GateStatus(values["status"])
        if values.get("consultation") is not None:
            values["consultation"] = GateConsultation(values["consultation"])
    elif kind is EventKind.MEMORY_EVIDENCE:
        values["item_kind"] = MemoryItemKind(values["item_kind"])
        values["stage"] = MemoryStage(values["stage"])
        values["state"] = MemoryEvidenceState(values["state"])
    elif kind is EventKind.COST:
        if values.get("amount_usd") is not None:
            values["amount_usd"] = Decimal(values["amount_usd"])
        values["basis"] = CostBasis(values.get("basis", CostBasis.UNKNOWN))
        values["kind"] = CostKind(values.get("kind", CostKind.UNKNOWN))
        values["accuracy"] = CostAccuracy(values.get("accuracy", CostAccuracy.UNKNOWN))
        values["accounting_key_scope"] = CostKeyScope(
            values.get("accounting_key_scope", CostKeyScope.UNKNOWN)
        )
        values["observation_role"] = CostObservationRole(
            values.get("observation_role", CostObservationRole.UNKNOWN)
        )
    return payload_type(**values)


def coverage_for(
    payload: EventPayload,
    /,
    **overrides: CoverageStatus,
) -> dict[str, CoverageStatus]:
    """Build a complete coverage declaration, treating absent values honestly."""

    result = {
        field.name: CoverageStatus.UNAVAILABLE
        if getattr(payload, field.name) is None
        else CoverageStatus.RECOVERED
        for field in fields(payload)
    }
    unknown = set(overrides).difference(result)
    if unknown:
        raise ValidationError(f"coverage names unknown payload fields: {sorted(unknown)}")
    result.update(overrides)
    return result


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """A typed event envelope with stable identity and explicit field coverage."""

    event_id: str
    kind: EventKind
    source: SourceRef
    occurred_at: datetime
    recorded_at: datetime
    payload: EventPayload
    coverage: dict[str, CoverageStatus]
    session_id: str | None = None
    parent_event_id: str | None = None
    attributes: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        format_datetime(self.occurred_at)
        format_datetime(self.recorded_at)
        if self.payload.KIND is not self.kind:
            kind_name = self.kind.value if isinstance(self.kind, EventKind) else str(self.kind)
            raise ValidationError(
                f"{type(self.payload).__name__} cannot be used for {kind_name} events"
            )
        payload_fields = {field.name for field in fields(self.payload)}
        if set(self.coverage) != payload_fields:
            missing = sorted(payload_fields.difference(self.coverage))
            extra = sorted(set(self.coverage).difference(payload_fields))
            raise ValidationError(f"coverage must be complete (missing={missing}, extra={extra})")
        for field_name, status in self.coverage.items():
            value = getattr(self.payload, field_name)
            if value is None and status not in {
                CoverageStatus.UNAVAILABLE,
                CoverageStatus.REDACTED,
            }:
                raise ValidationError(f"{field_name} is absent but marked {status.value}")
            if value is not None and status in {
                CoverageStatus.UNAVAILABLE,
                CoverageStatus.REDACTED,
            }:
                raise ValidationError(f"{field_name} has a value but is marked {status.value}")

    @classmethod
    def create(
        cls,
        *,
        source: SourceRef,
        occurred_at: datetime,
        payload: EventPayload,
        coverage: dict[str, CoverageStatus] | None = None,
        recorded_at: datetime | None = None,
        session_id: str | None = None,
        parent_event_id: str | None = None,
        attributes: dict[str, JsonValue] | None = None,
    ) -> NormalizedEvent:
        return cls(
            event_id=stable_id("evt", source.adapter, payload.KIND.value, source.native_id),
            kind=payload.KIND,
            source=source,
            occurred_at=occurred_at,
            recorded_at=recorded_at or utc_now(),
            payload=payload,
            coverage=coverage or coverage_for(payload),
            session_id=session_id,
            parent_event_id=parent_event_id,
            attributes=attributes or {},
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "event_id": self.event_id,
            "kind": self.kind.value,
            "source": {
                "adapter": self.source.adapter,
                "native_id": self.source.native_id,
                "location": self.source.location,
            },
            "occurred_at": format_datetime(self.occurred_at),
            "recorded_at": format_datetime(self.recorded_at),
            "session_id": self.session_id,
            "parent_event_id": self.parent_event_id,
            "attributes": self.attributes or {},
            "payload": payload_to_dict(self.payload),
            "coverage": {name: status.value for name, status in self.coverage.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NormalizedEvent:
        if raw.get("schema_version") != 1:
            raise ValidationError(
                f"unsupported event schema version: {raw.get('schema_version')!r}"
            )
        kind = EventKind(raw["kind"])
        source_raw = raw["source"]
        payload = _payload_from_dict(kind, raw["payload"])
        coverage = {name: CoverageStatus(value) for name, value in raw["coverage"].items()}
        # Cost provenance was added additively to schema v1. Old immutable
        # events remain readable and declare the new fields unavailable.
        for payload_field in fields(payload):
            coverage.setdefault(
                payload_field.name,
                CoverageStatus.UNAVAILABLE
                if getattr(payload, payload_field.name) is None
                else CoverageStatus.RECOVERED,
            )
        return cls(
            event_id=raw["event_id"],
            kind=kind,
            source=SourceRef(
                adapter=source_raw["adapter"],
                native_id=source_raw["native_id"],
                location=source_raw.get("location"),
            ),
            occurred_at=parse_datetime(raw["occurred_at"]),
            recorded_at=parse_datetime(raw["recorded_at"]),
            session_id=raw.get("session_id"),
            parent_event_id=raw.get("parent_event_id"),
            attributes=raw.get("attributes") or {},
            payload=payload,
            coverage=coverage,
        )
