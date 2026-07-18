"""Stage-honest memory audit and bounded retention recommendations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from milton.errors import ValidationError
from milton.findings import (
    EvidenceRef,
    FindingGrade,
    FindingKind,
    FindingLedger,
    FindingManifest,
    FindingRevision,
)
from milton.model import (
    JsonValue,
    MemoryEvidencePayload,
    MemoryEvidenceState,
    MemoryItemKind,
    MemoryStage,
    NormalizedEvent,
    canonical_json,
    format_datetime,
    stable_id,
)

MEMORY_AUDIT_GENERATOR = "milton.memory-audit/v1"
AUDITED_STAGES = (
    MemoryStage.LOADED,
    MemoryStage.RETRIEVED,
    MemoryStage.REFERENCED,
    MemoryStage.APPLIED,
)


class MemoryStageStatus(StrEnum):
    OBSERVED = "observed"
    NOT_OBSERVED = "not_observed"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"


class MemoryDisposition(StrEnum):
    KEEP = "keep"
    PARK = "park"
    RETIRE = "retire"
    NONE = "none"


class MemoryAuditReason(StrEnum):
    APPLIED = "applied"
    ACCESSED = "accessed"
    COMPLETE_NON_USE = "complete-non-use"
    SUPERSEDED_NON_USE = "superseded-non-use"
    SIGNALS_UNKNOWN = "signals-unknown"
    TOO_RECENT = "too-recent"
    CONFLICTED = "conflicted"


@dataclass(frozen=True, slots=True)
class MemoryAuditConfig:
    cutoff: datetime
    non_use_after_days: int = 30
    expires_after_days: int = 30

    def __post_init__(self) -> None:
        format_datetime(self.cutoff)
        if self.non_use_after_days <= 0 or self.expires_after_days <= 0:
            raise ValidationError("memory audit day thresholds must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "cutoff_exclusive": format_datetime(self.cutoff),
            "non_use_after_days": self.non_use_after_days,
            "expires_after_days": self.expires_after_days,
        }


@dataclass(frozen=True, slots=True)
class MemoryAuditItem:
    system: str
    item_id: str
    item_kind: MemoryItemKind
    locator: str
    inventory_event_id: str
    inventoried_at: datetime
    stage_statuses: tuple[tuple[MemoryStage, MemoryStageStatus], ...]
    stage_event_ids: tuple[str, ...]
    disposition: MemoryDisposition
    reason: MemoryAuditReason
    superseded_by: str | None

    def status(self, stage: MemoryStage) -> MemoryStageStatus:
        return dict(self.stage_statuses)[stage]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "system": self.system,
            "item_id": self.item_id,
            "item_kind": self.item_kind.value,
            "locator": self.locator,
            "inventory_event_id": self.inventory_event_id,
            "inventoried_at": format_datetime(self.inventoried_at),
            "stages": {stage.value: status.value for stage, status in self.stage_statuses},
            "stage_event_ids": list(self.stage_event_ids),
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "superseded_by": self.superseded_by,
        }


@dataclass(frozen=True, slots=True)
class MemoryFindingCandidate:
    subject: str
    grade: FindingGrade
    summary: str
    details: dict[str, JsonValue]
    evidence: tuple[EvidenceRef, ...]
    manifest: FindingManifest

    @property
    def finding_id(self) -> str:
        return stable_id("fnd", FindingKind.MEMORY_HYGIENE.value, self.subject)

    def to_revision(self, *, recorded_at: datetime) -> FindingRevision:
        return FindingRevision.create(
            subject=self.subject,
            kind=FindingKind.MEMORY_HYGIENE,
            grade=self.grade,
            summary=self.summary,
            details=self.details,
            evidence=self.evidence,
            manifest=self.manifest,
            recorded_at=recorded_at,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "finding_id": self.finding_id,
            "subject": self.subject,
            "kind": FindingKind.MEMORY_HYGIENE.value,
            "grade": self.grade.value,
            "summary": self.summary,
            "details": self.details,
            "evidence": [item.to_dict() for item in self.evidence],
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MemoryAuditProjection:
    config: MemoryAuditConfig
    source_snapshot: str
    items: tuple[MemoryAuditItem, ...]
    candidates: tuple[MemoryFindingCandidate, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        systems = sorted({item.system for item in self.items})
        coverage: dict[str, JsonValue] = {}
        for system in systems:
            selected = tuple(item for item in self.items if item.system == system)
            coverage[system] = {
                "inventory": len(selected),
                "loaded_known": sum(
                    item.status(MemoryStage.LOADED) is not MemoryStageStatus.UNKNOWN
                    for item in selected
                ),
                "retrieved_known": sum(
                    item.status(MemoryStage.RETRIEVED) is not MemoryStageStatus.UNKNOWN
                    for item in selected
                ),
                "referenced_known": sum(
                    item.status(MemoryStage.REFERENCED) is not MemoryStageStatus.UNKNOWN
                    for item in selected
                ),
                "applied_known": sum(
                    item.status(MemoryStage.APPLIED) is not MemoryStageStatus.UNKNOWN
                    for item in selected
                ),
                "unknown_items": sum(
                    any(status is MemoryStageStatus.UNKNOWN for _, status in item.stage_statuses)
                    for item in selected
                ),
            }
        return {
            "schema_version": 1,
            "generator": MEMORY_AUDIT_GENERATOR,
            "config": self.config.to_dict(),
            "source_snapshot": self.source_snapshot,
            "counts": {
                "items": len(self.items),
                "keep": sum(item.disposition is MemoryDisposition.KEEP for item in self.items),
                "park": sum(item.disposition is MemoryDisposition.PARK for item in self.items),
                "retire": sum(item.disposition is MemoryDisposition.RETIRE for item in self.items),
                "unknown": sum(item.disposition is MemoryDisposition.NONE for item in self.items),
                "candidates": len(self.candidates),
            },
            "coverage": coverage,
            "items": [item.to_dict() for item in self.items],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def build_memory_audit(
    events: Iterable[NormalizedEvent], config: MemoryAuditConfig
) -> MemoryAuditProjection:
    selected = tuple(
        sorted(
            (
                event
                for event in events
                if isinstance(event.payload, MemoryEvidencePayload)
                and event.occurred_at < config.cutoff
            ),
            key=lambda event: (event.occurred_at, event.event_id),
        )
    )
    snapshot = stable_id(
        "snp",
        MEMORY_AUDIT_GENERATOR,
        canonical_json(config.to_dict()),
        *(event.event_id for event in selected),
    )
    grouped: dict[tuple[str, str], list[NormalizedEvent]] = {}
    for event in selected:
        payload = event.payload
        assert isinstance(payload, MemoryEvidencePayload)
        grouped.setdefault((payload.system, payload.item_id), []).append(event)

    items: list[MemoryAuditItem] = []
    candidates: list[MemoryFindingCandidate] = []
    for _, family in sorted(grouped.items()):
        inventory = tuple(
            event
            for event in family
            if isinstance(event.payload, MemoryEvidencePayload)
            and event.payload.stage is MemoryStage.INVENTORY
            and event.payload.state is MemoryEvidenceState.OBSERVED
        )
        if not inventory:
            continue
        inventory_event = inventory[-1]
        inventory_payload = inventory_event.payload
        assert isinstance(inventory_payload, MemoryEvidencePayload)
        stage_statuses = tuple((stage, _stage_status(family, stage)) for stage in AUDITED_STAGES)
        statuses = dict(stage_statuses)
        age_days = (config.cutoff - inventory_event.occurred_at).total_seconds() / 86400
        superseded_by = next(
            (
                event.payload.superseded_by
                for event in reversed(family)
                if isinstance(event.payload, MemoryEvidencePayload)
                and event.payload.superseded_by is not None
            ),
            None,
        )
        disposition, reason, grade = _recommend(statuses, age_days, superseded_by, config)
        item = MemoryAuditItem(
            system=inventory_payload.system,
            item_id=inventory_payload.item_id,
            item_kind=inventory_payload.item_kind,
            locator=inventory_payload.evidence_reference or "unknown",
            inventory_event_id=inventory_event.event_id,
            inventoried_at=inventory_event.occurred_at,
            stage_statuses=stage_statuses,
            stage_event_ids=tuple(sorted(event.event_id for event in family)),
            disposition=disposition,
            reason=reason,
            superseded_by=superseded_by,
        )
        items.append(item)
        if disposition is not MemoryDisposition.NONE and grade is not None:
            candidates.append(_candidate(item, family, config, snapshot, grade))
    return MemoryAuditProjection(
        config,
        snapshot,
        tuple(sorted(items, key=lambda item: (item.system, item.item_id))),
        tuple(sorted(candidates, key=lambda candidate: candidate.subject)),
    )


def append_memory_findings(
    ledger: FindingLedger, projection: MemoryAuditProjection, *, recorded_at: datetime
) -> tuple[int, int]:
    inserted = replayed = 0
    current = ledger.current()
    for candidate in projection.candidates:
        existing = current.get(candidate.finding_id)
        if existing is not None and _same_candidate(existing, candidate):
            replayed += 1
            continue
        revision = (
            candidate.to_revision(recorded_at=recorded_at)
            if existing is None
            else existing.revise(
                grade=candidate.grade,
                summary=candidate.summary,
                details=candidate.details,
                evidence=candidate.evidence,
                manifest=candidate.manifest,
                recorded_at=recorded_at,
            )
        )
        inserted += int(ledger.append(revision))
        current[revision.finding_id] = revision
    return inserted, replayed


def _stage_status(family: list[NormalizedEvent], stage: MemoryStage) -> MemoryStageStatus:
    events = [
        event
        for event in family
        if isinstance(event.payload, MemoryEvidencePayload) and event.payload.stage is stage
    ]
    if not events:
        return MemoryStageStatus.UNKNOWN
    latest_at = events[-1].occurred_at
    latest = [event for event in events if event.occurred_at == latest_at]
    states = {
        event.payload.state for event in latest if isinstance(event.payload, MemoryEvidencePayload)
    }
    if len(states) != 1:
        return MemoryStageStatus.CONFLICTED
    state = next(iter(states))
    return (
        MemoryStageStatus.OBSERVED
        if state is MemoryEvidenceState.OBSERVED
        else MemoryStageStatus.NOT_OBSERVED
    )


def _recommend(
    statuses: dict[MemoryStage, MemoryStageStatus],
    age_days: float,
    superseded_by: str | None,
    config: MemoryAuditConfig,
) -> tuple[MemoryDisposition, MemoryAuditReason, FindingGrade | None]:
    if any(status is MemoryStageStatus.CONFLICTED for status in statuses.values()):
        return MemoryDisposition.NONE, MemoryAuditReason.CONFLICTED, None
    if statuses[MemoryStage.APPLIED] is MemoryStageStatus.OBSERVED:
        return MemoryDisposition.KEEP, MemoryAuditReason.APPLIED, FindingGrade.CANDIDATE
    if any(
        statuses[stage] is MemoryStageStatus.OBSERVED
        for stage in (MemoryStage.LOADED, MemoryStage.RETRIEVED, MemoryStage.REFERENCED)
    ):
        return MemoryDisposition.KEEP, MemoryAuditReason.ACCESSED, FindingGrade.LEAD
    if age_days < config.non_use_after_days:
        return MemoryDisposition.NONE, MemoryAuditReason.TOO_RECENT, None
    if all(status is MemoryStageStatus.NOT_OBSERVED for status in statuses.values()):
        if superseded_by is not None:
            return (
                MemoryDisposition.RETIRE,
                MemoryAuditReason.SUPERSEDED_NON_USE,
                FindingGrade.CANDIDATE,
            )
        return MemoryDisposition.PARK, MemoryAuditReason.COMPLETE_NON_USE, FindingGrade.CANDIDATE
    return MemoryDisposition.NONE, MemoryAuditReason.SIGNALS_UNKNOWN, None


def _candidate(
    item: MemoryAuditItem,
    family: list[NormalizedEvent],
    config: MemoryAuditConfig,
    snapshot: str,
    grade: FindingGrade,
) -> MemoryFindingCandidate:
    known = sum(status is not MemoryStageStatus.UNKNOWN for _, status in item.stage_statuses)
    gaps = tuple(
        f"{stage.value} signal unavailable"
        for stage, status in item.stage_statuses
        if status is MemoryStageStatus.UNKNOWN
    )
    summary = {
        MemoryDisposition.KEEP: "Memory item has affirmative use evidence",
        MemoryDisposition.PARK: "Memory item has complete bounded non-use evidence",
        MemoryDisposition.RETIRE: "Superseded memory item has complete bounded non-use evidence",
        MemoryDisposition.NONE: "Memory item has insufficient disposition evidence",
    }[item.disposition]
    manifest = FindingManifest(
        source_snapshot=snapshot,
        generator=MEMORY_AUDIT_GENERATOR,
        scope={
            **config.to_dict(),
            "system": item.system,
            "item_kind": item.item_kind.value,
            "item_id": item.item_id,
            "disposition": item.disposition.value,
            "content_policy": "metadata-only",
        },
        coverage=known / len(AUDITED_STAGES),
        coverage_gaps=gaps,
        generated_at=config.cutoff,
        expires_at=config.cutoff + timedelta(days=config.expires_after_days),
    )
    return MemoryFindingCandidate(
        subject=f"{item.disposition.value}:{item.system}:{item.item_id}",
        grade=grade,
        summary=summary,
        details=item.to_dict(),
        evidence=tuple(EvidenceRef(event.event_id, "memory-stage-evidence") for event in family),
        manifest=manifest,
    )


def _same_candidate(existing: FindingRevision, candidate: MemoryFindingCandidate) -> bool:
    return (
        existing.kind is FindingKind.MEMORY_HYGIENE
        and existing.grade is candidate.grade
        and existing.summary == candidate.summary
        and existing.details == candidate.details
        and existing.evidence == candidate.evidence
        and existing.manifest.source_snapshot == candidate.manifest.source_snapshot
        and existing.manifest.scope == candidate.manifest.scope
        and existing.manifest.coverage == candidate.manifest.coverage
        and existing.manifest.coverage_gaps == candidate.manifest.coverage_gaps
    )
