"""Deterministic stale, re-minted, and unconsulted George gate rules."""

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
    GateConsultation,
    GateEvidenceKind,
    GateEvidencePayload,
    GateStatus,
    JsonValue,
    NormalizedEvent,
    format_datetime,
    stable_id,
)

GEORGE_GATE_GENERATOR = "milton.george-gates/v1"


class GateRule(StrEnum):
    CONDITION_RESOLVED = "condition-resolved"
    REMINTED = "re-minted"
    OLD_UNCONSULTED = "old-unconsulted"


class GateAssessmentState(StrEnum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    ABSTAIN = "abstain"


class GateAssessmentReason(StrEnum):
    RESOLUTION_RECEIPT = "resolution-receipt"
    REMINT_THRESHOLD = "re-mint-threshold"
    EXPLICIT_NOT_CONSULTED = "explicit-not-consulted"
    NO_RESOLUTION = "no-resolution"
    BELOW_THRESHOLD = "below-threshold"
    TOO_YOUNG = "too-young"
    CONSULTED = "consulted"
    ALREADY_RESOLVED = "already-resolved"
    COORDINATE_UNAVAILABLE = "coordinate-unavailable"
    COORDINATE_AMBIGUOUS = "coordinate-ambiguous"
    CONSULTATION_UNKNOWN = "consultation-unknown"
    STALE_SOURCE = "stale-source"


class GateSourceState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GateDetectorConfig:
    since: datetime
    cutoff: datetime
    source_state: GateSourceState
    remint_threshold: int = 3
    remint_window_days: int = 7
    old_after_days: int = 7
    expires_after_days: int = 7

    def __post_init__(self) -> None:
        format_datetime(self.since)
        format_datetime(self.cutoff)
        if self.cutoff <= self.since:
            raise ValidationError("gate detector cutoff must follow since")
        for name in (
            "remint_threshold",
            "remint_window_days",
            "old_after_days",
            "expires_after_days",
        ):
            if getattr(self, name) <= 0:
                raise ValidationError(f"{name} must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "since": format_datetime(self.since),
            "cutoff_exclusive": format_datetime(self.cutoff),
            "source_state": self.source_state.value,
            "remint_threshold": self.remint_threshold,
            "remint_window_days": self.remint_window_days,
            "old_after_days": self.old_after_days,
            "expires_after_days": self.expires_after_days,
        }


@dataclass(frozen=True, slots=True)
class GateAssessment:
    rule: GateRule
    state: GateAssessmentState
    reason: GateAssessmentReason
    coordinate: str | None
    mint_ids: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]
    details: dict[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "rule": self.rule.value,
            "state": self.state.value,
            "reason": self.reason.value,
            "coordinate": self.coordinate,
            "mint_ids": list(self.mint_ids),
            "evidence_event_ids": list(self.evidence_event_ids),
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class GateFindingCandidate:
    rule: GateRule
    subject: str
    kind: FindingKind
    grade: FindingGrade
    summary: str
    details: dict[str, JsonValue]
    evidence: tuple[EvidenceRef, ...]
    manifest: FindingManifest

    @property
    def finding_id(self) -> str:
        return stable_id("fnd", self.kind.value, self.subject)

    def to_revision(self, *, recorded_at: datetime) -> FindingRevision:
        return FindingRevision.create(
            subject=self.subject,
            kind=self.kind,
            grade=self.grade,
            summary=self.summary,
            details=self.details,
            evidence=self.evidence,
            manifest=self.manifest,
            recorded_at=recorded_at,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "rule": self.rule.value,
            "subject": self.subject,
            "finding_id": self.finding_id,
            "kind": self.kind.value,
            "grade": self.grade.value,
            "summary": self.summary,
            "details": self.details,
            "evidence": [item.to_dict() for item in self.evidence],
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class GateDetectorProjection:
    config: GateDetectorConfig
    source_snapshot: str
    assessments: tuple[GateAssessment, ...]
    candidates: tuple[GateFindingCandidate, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "generator": GEORGE_GATE_GENERATOR,
            "config": self.config.to_dict(),
            "source_snapshot": self.source_snapshot,
            "counts": {
                "assessments": len(self.assessments),
                "detected": sum(
                    item.state is GateAssessmentState.DETECTED for item in self.assessments
                ),
                "not_detected": sum(
                    item.state is GateAssessmentState.NOT_DETECTED for item in self.assessments
                ),
                "abstained": sum(
                    item.state is GateAssessmentState.ABSTAIN for item in self.assessments
                ),
                "candidates": len(self.candidates),
            },
            "assessments": [item.to_dict() for item in self.assessments],
            "candidates": [item.to_dict() for item in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class _GateEvidence:
    event: NormalizedEvent
    payload: GateEvidencePayload


def detect_george_gates(
    events: Iterable[NormalizedEvent], config: GateDetectorConfig
) -> GateDetectorProjection:
    evidence = tuple(
        sorted(
            (
                _GateEvidence(event, event.payload)
                for event in events
                if isinstance(event.payload, GateEvidencePayload)
                and config.since <= event.occurred_at < config.cutoff
            ),
            key=lambda item: (item.event.occurred_at, item.event.event_id),
        )
    )
    snapshot = stable_id(
        "snp",
        GEORGE_GATE_GENERATOR,
        format_datetime(config.since),
        format_datetime(config.cutoff),
        config.source_state.value,
        str(config.remint_threshold),
        str(config.remint_window_days),
        str(config.old_after_days),
        *(item.event.event_id for item in evidence),
    )
    mints = tuple(item for item in evidence if item.payload.evidence_kind is GateEvidenceKind.MINT)
    coordinate_by_mint_id = {
        item.payload.mint_id: item.payload.coordinate
        for item in mints
        if item.payload.mint_id is not None and item.payload.coordinate is not None
    }
    keyed: dict[str, list[_GateEvidence]] = {}
    unkeyed: list[_GateEvidence] = []
    for mint in mints:
        if mint.payload.coordinate is None:
            unkeyed.append(mint)
        else:
            keyed.setdefault(mint.payload.coordinate, []).append(mint)

    assessments: list[GateAssessment] = []
    candidates: list[GateFindingCandidate] = []
    coverage = sum(len(items) for items in keyed.values()) / max(len(mints), 1)
    for mint in sorted(unkeyed, key=lambda item: item.event.event_id):
        reason = (
            GateAssessmentReason.COORDINATE_AMBIGUOUS
            if mint.event.attributes.get("coordinate_ambiguous") is True
            else GateAssessmentReason.COORDINATE_UNAVAILABLE
        )
        for rule in GateRule:
            assessments.append(
                _assessment(rule, GateAssessmentState.ABSTAIN, reason, None, (mint,), ())
            )

    for coordinate, group in sorted(keyed.items()):
        ordered_mints = tuple(
            sorted(group, key=lambda item: (item.event.occurred_at, item.event.event_id))
        )
        related = tuple(
            item
            for item in evidence
            if _canonical_evidence_coordinate(item, coordinate_by_mint_id) == coordinate
        )
        if config.source_state is not GateSourceState.FRESH:
            for rule in GateRule:
                assessments.append(
                    _assessment(
                        rule,
                        GateAssessmentState.ABSTAIN,
                        GateAssessmentReason.STALE_SOURCE,
                        coordinate,
                        ordered_mints,
                        (),
                    )
                )
            continue

        resolved = tuple(
            item
            for item in related
            if item.payload.evidence_kind
            in {GateEvidenceKind.DECISION, GateEvidenceKind.DISPOSITION}
            and item.payload.status
            in {GateStatus.RESOLVED, GateStatus.RETIRED, GateStatus.REFUTED, GateStatus.ACTED}
        )
        resolved_assessment = _assessment(
            GateRule.CONDITION_RESOLVED,
            GateAssessmentState.DETECTED if resolved else GateAssessmentState.NOT_DETECTED,
            GateAssessmentReason.RESOLUTION_RECEIPT
            if resolved
            else GateAssessmentReason.NO_RESOLUTION,
            coordinate,
            ordered_mints,
            resolved,
        )
        assessments.append(resolved_assessment)
        if resolved:
            candidates.append(_candidate(resolved_assessment, config, snapshot, coverage))

        remint_window = _densest_window(ordered_mints, config.remint_window_days)
        reminted = len(remint_window) >= config.remint_threshold
        remint_assessment = _assessment(
            GateRule.REMINTED,
            GateAssessmentState.DETECTED if reminted else GateAssessmentState.NOT_DETECTED,
            GateAssessmentReason.REMINT_THRESHOLD
            if reminted
            else GateAssessmentReason.BELOW_THRESHOLD,
            coordinate,
            remint_window,
            (),
            extra={
                "threshold": config.remint_threshold,
                "window_days": config.remint_window_days,
            },
        )
        assessments.append(remint_assessment)
        if reminted:
            candidates.append(_candidate(remint_assessment, config, snapshot, coverage))

        consultation = tuple(
            item for item in related if item.payload.evidence_kind is GateEvidenceKind.CONSULT
        )
        first_mint = ordered_mints[0].event.occurred_at
        age_days = (config.cutoff - first_mint).total_seconds() / 86400
        if resolved:
            old_state = GateAssessmentState.NOT_DETECTED
            old_reason = GateAssessmentReason.ALREADY_RESOLVED
        elif age_days < config.old_after_days:
            old_state = GateAssessmentState.NOT_DETECTED
            old_reason = GateAssessmentReason.TOO_YOUNG
        elif any(item.payload.consultation is GateConsultation.CONSULTED for item in consultation):
            old_state = GateAssessmentState.NOT_DETECTED
            old_reason = GateAssessmentReason.CONSULTED
        elif any(
            item.payload.consultation is GateConsultation.NOT_CONSULTED for item in consultation
        ):
            old_state = GateAssessmentState.DETECTED
            old_reason = GateAssessmentReason.EXPLICIT_NOT_CONSULTED
        else:
            old_state = GateAssessmentState.ABSTAIN
            old_reason = GateAssessmentReason.CONSULTATION_UNKNOWN
        old_assessment = _assessment(
            GateRule.OLD_UNCONSULTED,
            old_state,
            old_reason,
            coordinate,
            ordered_mints,
            consultation,
            extra={"age_days": round(age_days, 6), "old_after_days": config.old_after_days},
        )
        assessments.append(old_assessment)
        if old_state is GateAssessmentState.DETECTED:
            candidates.append(_candidate(old_assessment, config, snapshot, coverage))

    assessments.sort(key=lambda item: (item.coordinate or "", item.rule.value, item.reason.value))
    candidates.sort(key=lambda item: (item.subject, item.kind.value))
    return GateDetectorProjection(config, snapshot, tuple(assessments), tuple(candidates))


def append_gate_findings(
    ledger: FindingLedger,
    projection: GateDetectorProjection,
    *,
    recorded_at: datetime,
) -> tuple[int, int]:
    """Append new/changed leads and replay identical candidates without duplicates."""

    inserted = 0
    replayed = 0
    current = ledger.current()
    for candidate in projection.candidates:
        existing = current.get(candidate.finding_id)
        if existing is not None and _same_candidate(existing, candidate):
            replayed += 1
            continue
        if existing is None:
            revision = candidate.to_revision(recorded_at=recorded_at)
        else:
            revision = existing.revise(
                grade=FindingGrade.LEAD,
                summary=candidate.summary,
                details=candidate.details,
                evidence=candidate.evidence,
                manifest=candidate.manifest,
                recorded_at=recorded_at,
            )
        inserted += int(ledger.append(revision))
        current[revision.finding_id] = revision
    return inserted, replayed


def _same_candidate(existing: FindingRevision, candidate: GateFindingCandidate) -> bool:
    return (
        existing.kind is candidate.kind
        and existing.grade is candidate.grade
        and existing.summary == candidate.summary
        and existing.details == candidate.details
        and existing.evidence == candidate.evidence
        and existing.manifest.source_snapshot == candidate.manifest.source_snapshot
        and existing.manifest.generator == candidate.manifest.generator
        and existing.manifest.scope == candidate.manifest.scope
        and existing.manifest.coverage == candidate.manifest.coverage
        and existing.manifest.coverage_gaps == candidate.manifest.coverage_gaps
    )


def _assessment(
    rule: GateRule,
    state: GateAssessmentState,
    reason: GateAssessmentReason,
    coordinate: str | None,
    mints: tuple[_GateEvidence, ...],
    supporting: tuple[_GateEvidence, ...],
    *,
    extra: dict[str, JsonValue] | None = None,
) -> GateAssessment:
    mint_ids = tuple(
        sorted(item.payload.mint_id for item in mints if item.payload.mint_id is not None)
    )
    event_ids = tuple(sorted({item.event.event_id for item in (*mints, *supporting)}))
    details: dict[str, JsonValue] = {
        "mint_count": len(mints),
        "supporting_event_count": len(supporting),
    }
    details.update(extra or {})
    return GateAssessment(rule, state, reason, coordinate, mint_ids, event_ids, details)


def _candidate(
    assessment: GateAssessment,
    config: GateDetectorConfig,
    snapshot: str,
    coverage: float,
) -> GateFindingCandidate:
    assert assessment.coordinate is not None
    kind = {
        GateRule.CONDITION_RESOLVED: FindingKind.STALE_GATE,
        GateRule.REMINTED: FindingKind.FAILURE_MOTIF,
        GateRule.OLD_UNCONSULTED: FindingKind.MEMORY_HYGIENE,
    }[assessment.rule]
    summary = {
        GateRule.CONDITION_RESOLVED: "George gate coordinate has a later resolution receipt",
        GateRule.REMINTED: "George gate coordinate was repeatedly re-minted",
        GateRule.OLD_UNCONSULTED: "Old George gate has explicit non-consultation evidence",
    }[assessment.rule]
    roles = {
        GateRule.CONDITION_RESOLVED: "gate-mint-or-resolution",
        GateRule.REMINTED: "gate-mint",
        GateRule.OLD_UNCONSULTED: "gate-mint-or-consultation",
    }
    evidence = tuple(
        EvidenceRef(event_id, roles[assessment.rule]) for event_id in assessment.evidence_event_ids
    )
    gaps = ("some gate mints lack canonical coordinates",) if coverage < 1 else ()
    manifest = FindingManifest(
        source_snapshot=snapshot,
        generator=GEORGE_GATE_GENERATOR,
        scope={
            "rule": assessment.rule.value,
            "coordinate": assessment.coordinate,
            **config.to_dict(),
        },
        coverage=coverage,
        coverage_gaps=gaps,
        generated_at=config.cutoff,
        expires_at=config.cutoff + timedelta(days=config.expires_after_days),
    )
    return GateFindingCandidate(
        rule=assessment.rule,
        subject=f"{assessment.rule.value}:{assessment.coordinate}",
        kind=kind,
        grade=FindingGrade.LEAD,
        summary=summary,
        details={
            "rule": assessment.rule.value,
            "reason": assessment.reason.value,
            "coordinate": assessment.coordinate,
            "mint_ids": list(assessment.mint_ids),
            **assessment.details,
        },
        evidence=evidence,
        manifest=manifest,
    )


def _densest_window(
    mints: tuple[_GateEvidence, ...], window_days: int
) -> tuple[_GateEvidence, ...]:
    if not mints:
        return ()
    width = timedelta(days=window_days)
    best = mints[:1]
    start = 0
    for end, item in enumerate(mints):
        while item.event.occurred_at - mints[start].event.occurred_at > width:
            start += 1
        candidate = mints[start : end + 1]
        if len(candidate) > len(best):
            best = candidate
    return best


def _canonical_evidence_coordinate(
    evidence: _GateEvidence, coordinate_by_mint_id: dict[str, str]
) -> str | None:
    coordinate = evidence.payload.coordinate
    if evidence.payload.evidence_kind is GateEvidenceKind.MINT or coordinate is None:
        return coordinate
    prefix = "target="
    if coordinate.startswith(prefix):
        return coordinate_by_mint_id.get(coordinate[len(prefix) :], coordinate)
    return coordinate
