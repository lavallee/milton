"""Versioned, evidence-only outcome snapshots for one served tuple."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from milton.errors import ValidationError
from milton.model import (
    CostPayload,
    JsonValue,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    format_datetime,
    stable_id,
    utc_now,
)
from milton.outcomes import AttributionState, OutcomeAttributionRecord
from milton.relations import TypedRef
from milton.store import MiltonStore

SCHEMA = "milton.outcome-tuple/v1"


class TupleEvidenceState(StrEnum):
    READY = "ready"
    SPARSE = "sparse"
    CONFOUNDED = "confounded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class OutcomeTuple:
    implementation: str
    profile: str
    served_model: str
    harness: str

    def __post_init__(self) -> None:
        for name in ("implementation", "profile", "served_model", "harness"):
            value = getattr(self, name)
            if not value.strip() or value != value.strip():
                raise ValidationError(f"tuple {name} must be non-empty without outer whitespace")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "implementation": self.implementation,
            "profile": self.profile,
            "served_model": self.served_model,
            "harness": self.harness,
        }


@dataclass(frozen=True, slots=True)
class TupleEvidenceSnapshot:
    snapshot_id: str
    generated_at: datetime
    since: datetime | None
    cutoff: datetime
    coordinate: OutcomeTuple
    state: TupleEvidenceState
    reasons: tuple[str, ...]
    minimum_observations: int
    observations: int
    attributed_observations: int
    ambiguous_observations: int
    unallocated_observations: int
    selected_usd: Decimal
    cost_by_kind: dict[str, Decimal]
    outcome_statuses: dict[str, int]
    evidence: tuple[dict[str, JsonValue], ...]
    coverage: dict[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": SCHEMA,
            "snapshot_id": self.snapshot_id,
            "generated_at": format_datetime(self.generated_at),
            "window": {
                "since": format_datetime(self.since) if self.since else None,
                "cutoff": format_datetime(self.cutoff),
                "cutoff_exclusive": True,
            },
            "tuple": self.coordinate.to_dict(),
            "sample": {
                "minimum_observations": self.minimum_observations,
                "observations": self.observations,
                "attributed": self.attributed_observations,
                "ambiguous": self.ambiguous_observations,
                "unallocated": self.unallocated_observations,
                "selected_usd": str(self.selected_usd),
                "cost_by_kind_usd": {
                    key: str(value) for key, value in sorted(self.cost_by_kind.items())
                },
                "outcome_statuses": dict(sorted(self.outcome_statuses.items())),
            },
            "uncertainty": {
                "state": self.state.value,
                "reasons": list(self.reasons),
                "policy_effect": "evidence_only",
            },
            "coverage": self.coverage,
            "evidence": list(self.evidence),
        }

    def to_text(self) -> str:
        return "\n".join(
            [
                "Milton tuple outcome evidence",
                "",
                f"Snapshot: {self.snapshot_id}",
                f"State: {self.state.value}",
                f"Tuple: {self.coordinate.implementation} / {self.coordinate.profile} / "
                f"{self.coordinate.served_model} / {self.coordinate.harness}",
                f"Window: {format_datetime(self.since) if self.since else 'beginning'} "
                f"to {format_datetime(self.cutoff)} (exclusive)",
                f"Sample: {self.observations} observation(s); "
                f"{self.attributed_observations} attributed; "
                f"{self.ambiguous_observations} ambiguous; "
                f"{self.unallocated_observations} unallocated",
                f"Selected observations: ${self.selected_usd}",
                "Policy effect: evidence only; no route is changed by this document",
                f"Reasons: {', '.join(self.reasons) if self.reasons else 'none'}",
            ]
        )


def build_tuple_evidence(
    store: MiltonStore,
    outcome_tuple: OutcomeTuple,
    *,
    cutoff: datetime,
    since: datetime | None = None,
    minimum_observations: int = 5,
    generated_at: datetime | None = None,
) -> TupleEvidenceSnapshot:
    """Build an exact Git-outcome snapshot without granting policy authority."""
    if minimum_observations < 1:
        raise ValidationError("minimum_observations must be positive")
    format_datetime(cutoff)
    if since is not None:
        format_datetime(since)
        if since >= cutoff:
            raise ValidationError("tuple evidence since must be earlier than cutoff")

    projection = store.outcome_attribution(
        since=format_datetime(since) if since else None,
        until=format_datetime(cutoff),
        outcome_types=("git.commit",),
    )
    events = {event.event_id: event for event in store.events()}
    relevant: list[OutcomeAttributionRecord] = []
    missing_fields = 0
    for record in projection.records:
        coordinates = _record_coordinates(store, events, record)
        if coordinates is None:
            missing_fields += 1
            continue
        profile, served_model, harness, implementations = coordinates
        if (
            profile == outcome_tuple.profile
            and served_model == outcome_tuple.served_model
            and harness == outcome_tuple.harness
            and outcome_tuple.implementation in implementations
        ):
            relevant.append(record)

    attributed = [
        record
        for record in relevant
        if record.state is AttributionState.ATTRIBUTED
        and record.outcome is not None
        and record.outcome.reference == TypedRef("git.commit", outcome_tuple.implementation)
    ]
    ambiguous = [record for record in relevant if record.state is AttributionState.AMBIGUOUS]
    unallocated = [record for record in relevant if record.state is AttributionState.UNALLOCATED]
    reasons: list[str] = []
    source_errors = sorted(
        name for name, summary in store.source_coverage().items() if summary.status == "error"
    )
    if source_errors:
        state = TupleEvidenceState.UNAVAILABLE
        reasons.append(f"source coverage error: {', '.join(source_errors)}")
    elif not relevant:
        state = TupleEvidenceState.UNAVAILABLE
        reasons.append("no exact observations for the requested tuple")
    elif ambiguous or unallocated:
        state = TupleEvidenceState.CONFOUNDED
        if ambiguous:
            reasons.append(f"{len(ambiguous)} observation(s) have competing outcomes")
        if unallocated:
            reasons.append(f"{len(unallocated)} observation(s) lack an eligible outcome path")
    elif len(attributed) < minimum_observations:
        state = TupleEvidenceState.SPARSE
        reasons.append(
            f"{len(attributed)} attributed observation(s) below floor {minimum_observations}"
        )
    else:
        state = TupleEvidenceState.READY

    cost_by_kind: dict[str, Decimal] = {}
    statuses: dict[str, int] = {}
    evidence: list[dict[str, JsonValue]] = []
    for record in relevant:
        cost_by_kind[record.economic_kind] = (
            cost_by_kind.get(record.economic_kind, Decimal(0)) + record.amount_usd
        )
        status = _target_status(record, outcome_tuple.implementation)
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        evidence.append(
            {
                "cost_event_id": record.cost_event_id,
                "state": record.state.value,
                "reason": record.reason.value,
                "amount_usd": str(record.amount_usd),
                "outcome_event_id": record.outcome.event_id if record.outcome else None,
                "relation_ids": list(record.path.relation_ids) if record.path else [],
                "relation_record_ids": (
                    list(record.path.relation_record_ids) if record.path else []
                ),
            }
        )

    evidence_ids = sorted(record.cost_event_id for record in relevant)
    snapshot_id = stable_id(
        "mts",
        SCHEMA,
        outcome_tuple.implementation,
        outcome_tuple.profile,
        outcome_tuple.served_model,
        outcome_tuple.harness,
        format_datetime(since) if since else "",
        format_datetime(cutoff),
        str(minimum_observations),
        *evidence_ids,
    )
    coverage: dict[str, JsonValue] = {
        "selected_observations_in_window": len(projection.records),
        "tuple_bound_observations": len(relevant),
        "records_missing_tuple_fields": missing_fields,
        "sources": {
            name: summary.to_dict() for name, summary in sorted(store.source_coverage().items())
        },
    }
    return TupleEvidenceSnapshot(
        snapshot_id=snapshot_id,
        generated_at=generated_at or utc_now(),
        since=since,
        cutoff=cutoff,
        coordinate=outcome_tuple,
        state=state,
        reasons=tuple(reasons),
        minimum_observations=minimum_observations,
        observations=len(relevant),
        attributed_observations=len(attributed),
        ambiguous_observations=len(ambiguous),
        unallocated_observations=len(unallocated),
        selected_usd=sum((record.amount_usd for record in relevant), Decimal(0)),
        cost_by_kind=cost_by_kind,
        outcome_statuses=statuses,
        evidence=tuple(evidence),
        coverage=coverage,
    )


def _record_coordinates(
    store: MiltonStore,
    events: dict[str, NormalizedEvent],
    record: OutcomeAttributionRecord,
) -> tuple[str, str, str, set[str]] | None:
    cost = events.get(record.cost_event_id)
    if cost is None or not isinstance(cost.payload, CostPayload):
        return None
    call = events.get(cost.parent_event_id or "")
    if call is None or not isinstance(call.payload, ModelCallPayload):
        return None
    profile = _text(call.attributes.get("workload_id")) or _text(call.attributes.get("prompt_id"))
    served_model = cost.payload.model or call.payload.model
    harness = _record_harness(store, events, call, record)
    implementations = {
        candidate.candidate.reference.value
        for candidate in record.candidates
        if candidate.candidate.outcome_type == "git.commit"
        and candidate.candidate.reference.namespace == "git.commit"
    }
    if record.outcome and record.outcome.outcome_type == "git.commit":
        implementations.add(record.outcome.reference.value)
    if not profile or not served_model or not harness or not implementations:
        return None
    return profile, served_model, harness, implementations


def _record_harness(
    store: MiltonStore,
    events: dict[str, NormalizedEvent],
    call: NormalizedEvent,
    record: OutcomeAttributionRecord,
) -> str | None:
    paths = [record.path] if record.path is not None else []
    paths.extend(candidate.path for candidate in record.candidates)
    for path in paths:
        for reference in path.references:
            if reference.namespace != "fab.attempt":
                continue
            attempt = store.event_for_ref(reference)
            if attempt is not None and (backend := _text(attempt.attributes.get("backend"))):
                return backend
    session = events.get(call.session_id or "")
    if session is not None and isinstance(session.payload, SessionPayload):
        return session.payload.harness
    if call.source.adapter == "somm" and call.attributes.get("origin") == "native":
        return "somm"
    return None


def _target_status(record: OutcomeAttributionRecord, implementation: str) -> str | None:
    if record.outcome is not None and record.outcome.reference == TypedRef(
        "git.commit", implementation
    ):
        return record.outcome.status
    for candidate in record.candidates:
        if candidate.candidate.reference == TypedRef("git.commit", implementation):
            return candidate.candidate.status
    return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
