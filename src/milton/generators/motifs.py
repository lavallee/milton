"""Bounded failure-motif synthesis with deterministic hard gates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from milton.errors import ValidationError
from milton.evaluation import EvaluationDecision, FindingEvaluationResult
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
    NormalizedEvent,
    OutcomePayload,
    SessionPayload,
    ToolCallPayload,
    canonical_json,
    format_datetime,
    stable_id,
)
from milton.relations import TypedRef
from milton.store import MiltonStore

FAILURE_MOTIF_GENERATOR = "milton.failure-motifs/v1"
MOTIF_SYNTHESIS_SCHEMA = "milton.motif-synthesis/v1"


class MotifAssessmentState(StrEnum):
    ELIGIBLE = "eligible"
    ABSTAIN = "abstain"


class MotifAssessmentReason(StrEnum):
    EVIDENCE_FLOORS_MET = "evidence-floors-met"
    UNKNOWN_SESSION = "unknown-session"
    FACET_UNSUPPORTED = "facet-unsupported"
    INSUFFICIENT_RECURRENCE = "insufficient-recurrence"
    INSUFFICIENT_RECEIPTS = "insufficient-receipts"
    PRIVATE_SMALL_GROUP = "private-small-group"
    EVALUATION_OFFLINE = "evaluation-offline"


@dataclass(frozen=True, slots=True)
class MotifGeneratorConfig:
    since: datetime
    cutoff: datetime
    minimum_recurrence: int = 3
    minimum_receipts: int = 3
    minimum_aggregation: int = 3
    expires_after_days: int = 14

    def __post_init__(self) -> None:
        format_datetime(self.since)
        format_datetime(self.cutoff)
        if self.cutoff <= self.since:
            raise ValidationError("motif cutoff must follow since")
        for name in (
            "minimum_recurrence",
            "minimum_receipts",
            "minimum_aggregation",
            "expires_after_days",
        ):
            if getattr(self, name) <= 0:
                raise ValidationError(f"{name} must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "since": format_datetime(self.since),
            "cutoff_exclusive": format_datetime(self.cutoff),
            "minimum_recurrence": self.minimum_recurrence,
            "minimum_receipts": self.minimum_receipts,
            "minimum_aggregation": self.minimum_aggregation,
            "expires_after_days": self.expires_after_days,
        }


@dataclass(frozen=True, slots=True)
class FailureFacet:
    session_id: str
    session_native_id: str
    source_adapter: str
    event_ids: tuple[str, ...]
    receipt_event_ids: tuple[str, ...]
    tool_attempts: int
    failed_tool_attempts: int
    repeated_tool: str | None
    repeated_failed_tool: str | None
    repeated_failure_fingerprint: str | None
    error_categories: tuple[str, ...]
    outcome_statuses: tuple[str, ...]
    scope_changes: int

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "session_id": self.session_id,
            "session_native_id": self.session_native_id,
            "source_adapter": self.source_adapter,
            "event_ids": list(self.event_ids),
            "receipt_event_ids": list(self.receipt_event_ids),
            "tool_attempts": self.tool_attempts,
            "failed_tool_attempts": self.failed_tool_attempts,
            "repeated_tool": self.repeated_tool,
            "repeated_failed_tool": self.repeated_failed_tool,
            "repeated_failure_fingerprint": self.repeated_failure_fingerprint,
            "error_categories": list(self.error_categories),
            "outcome_statuses": list(self.outcome_statuses),
            "scope_changes": self.scope_changes,
        }


@dataclass(frozen=True, slots=True)
class MotifProposal:
    motif_id: str
    session_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if not self.motif_id.strip() or not self.summary.strip():
            raise ValidationError("motif proposal id and summary must not be empty")
        if len(self.summary) > 500:
            raise ValidationError("motif proposal summary exceeds 500 characters")
        if tuple(sorted(set(self.session_ids))) != self.session_ids:
            raise ValidationError("motif proposal sessions must be sorted and unique")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "motif_id": self.motif_id,
            "session_ids": list(self.session_ids),
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class MotifSynthesisReceipt:
    synthesis_id: str
    source_snapshot: str
    method: str
    model: str
    harness: str
    parameters_digest: str
    proposals: tuple[MotifProposal, ...]

    @classmethod
    def create(
        cls,
        *,
        source_snapshot: str,
        method: str,
        model: str,
        harness: str,
        parameters_digest: str,
        proposals: tuple[MotifProposal, ...],
    ) -> MotifSynthesisReceipt:
        synthesis_id = stable_id(
            "syn",
            MOTIF_SYNTHESIS_SCHEMA,
            source_snapshot,
            method,
            model,
            harness,
            parameters_digest,
            *(canonical_json(proposal.to_dict()) for proposal in proposals),
        )
        return cls(
            synthesis_id,
            source_snapshot,
            method,
            model,
            harness,
            parameters_digest,
            proposals,
        )

    def __post_init__(self) -> None:
        for name in (
            "synthesis_id",
            "source_snapshot",
            "method",
            "model",
            "harness",
            "parameters_digest",
        ):
            if not getattr(self, name).strip():
                raise ValidationError(f"motif synthesis {name} must not be empty")
        motif_ids = [proposal.motif_id for proposal in self.proposals]
        if len(motif_ids) != len(set(motif_ids)):
            raise ValidationError("motif synthesis proposal ids must be unique")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": MOTIF_SYNTHESIS_SCHEMA,
            "synthesis_id": self.synthesis_id,
            "source_snapshot": self.source_snapshot,
            "method": self.method,
            "model": self.model,
            "harness": self.harness,
            "parameters_digest": self.parameters_digest,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MotifSynthesisReceipt:
        if raw.get("schema") != MOTIF_SYNTHESIS_SCHEMA:
            raise ValidationError(f"unsupported motif synthesis schema: {raw.get('schema')!r}")
        return cls(
            synthesis_id=str(raw["synthesis_id"]),
            source_snapshot=str(raw["source_snapshot"]),
            method=str(raw["method"]),
            model=str(raw["model"]),
            harness=str(raw["harness"]),
            parameters_digest=str(raw["parameters_digest"]),
            proposals=tuple(
                MotifProposal(
                    motif_id=str(item["motif_id"]),
                    session_ids=tuple(str(value) for value in item["session_ids"]),
                    summary=str(item["summary"]),
                )
                for item in raw["proposals"]
            ),
        )


@dataclass(frozen=True, slots=True)
class MotifAssessment:
    motif_id: str
    state: MotifAssessmentState
    reason: MotifAssessmentReason
    independent_sessions: int
    corroborating_receipts: int
    aggregation_size: int
    session_ids: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "motif_id": self.motif_id,
            "state": self.state.value,
            "reason": self.reason.value,
            "independent_sessions": self.independent_sessions,
            "corroborating_receipts": self.corroborating_receipts,
            "aggregation_size": self.aggregation_size,
            "session_ids": list(self.session_ids),
            "evidence_event_ids": list(self.evidence_event_ids),
        }


@dataclass(frozen=True, slots=True)
class MotifFindingCandidate:
    subject: str
    grade: FindingGrade
    summary: str
    details: dict[str, JsonValue]
    evidence: tuple[EvidenceRef, ...]
    manifest: FindingManifest

    @property
    def finding_id(self) -> str:
        return stable_id("fnd", FindingKind.FAILURE_MOTIF.value, self.subject)

    def to_revision(self, *, recorded_at: datetime) -> FindingRevision:
        return FindingRevision.create(
            subject=self.subject,
            kind=FindingKind.FAILURE_MOTIF,
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
            "kind": FindingKind.FAILURE_MOTIF.value,
            "grade": self.grade.value,
            "summary": self.summary,
            "details": self.details,
            "evidence": [item.to_dict() for item in self.evidence],
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class MotifProjection:
    config: MotifGeneratorConfig
    source_snapshot: str
    facets: tuple[FailureFacet, ...]
    synthesis_id: str | None
    evaluation_result_id: str | None
    assessments: tuple[MotifAssessment, ...]
    candidates: tuple[MotifFindingCandidate, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "generator": FAILURE_MOTIF_GENERATOR,
            "config": self.config.to_dict(),
            "source_snapshot": self.source_snapshot,
            "synthesis_id": self.synthesis_id,
            "evaluation_result_id": self.evaluation_result_id,
            "counts": {
                "facets": len(self.facets),
                "assessments": len(self.assessments),
                "eligible": sum(
                    item.state is MotifAssessmentState.ELIGIBLE for item in self.assessments
                ),
                "abstained": sum(
                    item.state is MotifAssessmentState.ABSTAIN for item in self.assessments
                ),
                "candidates": len(self.candidates),
            },
            "facets": [facet.to_dict() for facet in self.facets],
            "assessments": [assessment.to_dict() for assessment in self.assessments],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def extract_failure_facets(
    events: Iterable[NormalizedEvent], config: MotifGeneratorConfig
) -> tuple[str, tuple[FailureFacet, ...]]:
    selected = tuple(
        sorted(
            (event for event in events if config.since <= event.occurred_at < config.cutoff),
            key=lambda event: (event.occurred_at, event.event_id),
        )
    )
    snapshot = stable_id(
        "snp",
        FAILURE_MOTIF_GENERATOR,
        canonical_json(config.to_dict()),
        *(event.event_id for event in selected),
    )
    session_events: dict[str, list[NormalizedEvent]] = {}
    session_roots: dict[str, NormalizedEvent] = {}
    for event in selected:
        session_id = (
            event.event_id if isinstance(event.payload, SessionPayload) else event.session_id
        )
        if session_id is None:
            continue
        session_events.setdefault(session_id, []).append(event)
        if isinstance(event.payload, SessionPayload):
            session_roots[session_id] = event

    facets: list[FailureFacet] = []
    for session_id, family in sorted(session_events.items()):
        root = session_roots.get(session_id)
        if root is None:
            continue
        tools = [
            (event, event.payload) for event in family if isinstance(event.payload, ToolCallPayload)
        ]
        outcomes = [
            (event, event.payload) for event in family if isinstance(event.payload, OutcomePayload)
        ]
        if not tools and not outcomes:
            continue
        tool_counts = Counter(
            payload.tool_name for _, payload in tools if payload.tool_name is not None
        )
        repeated_tool = next(
            (
                tool
                for tool, count in sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))
                if count >= 2
            ),
            None,
        )
        failed_tool_counts = Counter(
            payload.tool_name
            for _, payload in tools
            if payload.status.value == "failed" and payload.tool_name is not None
        )
        repeated_failed_tool = next(
            (
                tool
                for tool, count in sorted(
                    failed_tool_counts.items(), key=lambda item: (-item[1], item[0])
                )
                if count >= 2
            ),
            None,
        )
        failed_action_counts = Counter(
            fingerprint
            for event, payload in tools
            if payload.status.value == "failed"
            for fingerprint in (_failed_action_fingerprint(event, payload),)
            if fingerprint is not None
        )
        repeated_failure_fingerprint = next(
            (
                fingerprint
                for fingerprint, count in sorted(
                    failed_action_counts.items(), key=lambda item: (-item[1], item[0])
                )
                if count >= 2
            ),
            None,
        )
        error_categories = tuple(
            sorted(
                {
                    category
                    for _, payload in tools
                    if payload.error is not None
                    for category in (_bounded_error_category(payload.error),)
                }
            )
        )
        scope_changes = sum(_scope_change_count(event.attributes) for event in family)
        facets.append(
            FailureFacet(
                session_id=session_id,
                session_native_id=root.source.native_id,
                source_adapter=root.source.adapter,
                event_ids=tuple(sorted(event.event_id for event in family)),
                receipt_event_ids=tuple(
                    sorted(
                        {event.event_id for event, _ in outcomes}
                        | {
                            event.event_id
                            for event, payload in tools
                            if payload.status.value == "failed"
                        }
                    )
                ),
                tool_attempts=len(tools),
                failed_tool_attempts=sum(payload.status.value == "failed" for _, payload in tools),
                repeated_tool=repeated_tool,
                repeated_failed_tool=repeated_failed_tool,
                repeated_failure_fingerprint=repeated_failure_fingerprint,
                error_categories=error_categories,
                outcome_statuses=tuple(sorted({payload.status.value for _, payload in outcomes})),
                scope_changes=scope_changes,
            )
        )
    return snapshot, tuple(facets)


def build_motif_projection(
    events: Iterable[NormalizedEvent],
    config: MotifGeneratorConfig,
    *,
    synthesis: MotifSynthesisReceipt | None,
    evaluation: FindingEvaluationResult | None,
    corroborating_receipts: dict[str, tuple[str, ...]] | None = None,
) -> MotifProjection:
    snapshot, facets = extract_failure_facets(events, config)
    if synthesis is None:
        return MotifProjection(config, snapshot, facets, None, None, (), ())
    if synthesis.source_snapshot != snapshot:
        raise ValidationError("motif synthesis source snapshot does not match bounded scan")
    if evaluation is not None:
        expected = evaluation.evaluation_tuple
        if expected.generator != FAILURE_MOTIF_GENERATOR:
            raise ValidationError("motif evaluation belongs to a different generator")
        if (
            expected.model != synthesis.model
            or expected.harness != synthesis.harness
            or expected.parameters_digest != synthesis.parameters_digest
        ):
            raise ValidationError(
                "motif synthesis does not match evaluated model/harness/parameters"
            )
        if (
            config.minimum_recurrence < evaluation.floors.recurrence
            or config.minimum_aggregation < evaluation.floors.aggregation
        ):
            raise ValidationError(
                "motif scan cannot weaken its measured recurrence or aggregation floors"
            )

    by_session = {facet.session_id: facet for facet in facets}
    external_receipts = corroborating_receipts or {}
    assessments: list[MotifAssessment] = []
    candidates: list[MotifFindingCandidate] = []
    for proposal in synthesis.proposals:
        unknown = tuple(sorted(set(proposal.session_ids) - by_session.keys()))
        selected = tuple(
            by_session[session_id]
            for session_id in proposal.session_ids
            if session_id in by_session
        )
        receipts_by_session = {
            facet.session_id: tuple(
                sorted(
                    set(facet.receipt_event_ids) | set(external_receipts.get(facet.session_id, ()))
                )
            )
            for facet in selected
        }
        receipt_ids = tuple(
            sorted({receipt for receipts in receipts_by_session.values() for receipt in receipts})
        )
        receipt_sessions = sum(bool(receipts) for receipts in receipts_by_session.values())
        evidence_ids = tuple(
            sorted({event for facet in selected for event in facet.event_ids} | set(receipt_ids))
        )
        if unknown:
            state = MotifAssessmentState.ABSTAIN
            reason = MotifAssessmentReason.UNKNOWN_SESSION
        elif not all(_facet_supports(proposal.motif_id, facet) for facet in selected):
            state = MotifAssessmentState.ABSTAIN
            reason = MotifAssessmentReason.FACET_UNSUPPORTED
        elif len(selected) < config.minimum_recurrence:
            state = MotifAssessmentState.ABSTAIN
            reason = MotifAssessmentReason.INSUFFICIENT_RECURRENCE
        elif receipt_sessions < config.minimum_receipts:
            state = MotifAssessmentState.ABSTAIN
            reason = MotifAssessmentReason.INSUFFICIENT_RECEIPTS
        elif len(selected) < config.minimum_aggregation:
            state = MotifAssessmentState.ABSTAIN
            reason = MotifAssessmentReason.PRIVATE_SMALL_GROUP
        elif evaluation is not None and evaluation.decision is EvaluationDecision.OFFLINE:
            state = MotifAssessmentState.ABSTAIN
            reason = MotifAssessmentReason.EVALUATION_OFFLINE
        else:
            state = MotifAssessmentState.ELIGIBLE
            reason = MotifAssessmentReason.EVIDENCE_FLOORS_MET
        assessment = MotifAssessment(
            proposal.motif_id,
            state,
            reason,
            len(selected),
            receipt_sessions,
            len(selected),
            proposal.session_ids,
            evidence_ids,
        )
        assessments.append(assessment)
        if state is MotifAssessmentState.ELIGIBLE:
            grade = (
                FindingGrade.CANDIDATE
                if evaluation is not None and evaluation.decision is EvaluationDecision.SURFACE
                else FindingGrade.LEAD
            )
            candidates.append(
                _candidate(
                    proposal,
                    assessment,
                    config,
                    snapshot,
                    synthesis,
                    evaluation,
                    receipt_ids,
                    grade,
                )
            )
    return MotifProjection(
        config,
        snapshot,
        facets,
        synthesis.synthesis_id,
        evaluation.result_id if evaluation is not None else None,
        tuple(sorted(assessments, key=lambda item: item.motif_id)),
        tuple(sorted(candidates, key=lambda item: item.subject)),
    )


def find_corroborating_receipts(
    store: MiltonStore,
    facets: tuple[FailureFacet, ...],
    cutoff: datetime,
) -> dict[str, tuple[str, ...]]:
    """Find exact source-owned outcomes through current identity/work edges."""

    namespaces = {
        "claude-code": "claude-code.session",
        "codex": "codex.session",
        "fab": "fab.job",
        "hermes": "hermes.session",
        "opencode": "opencode.session",
    }
    result: dict[str, tuple[str, ...]] = {}
    for facet in facets:
        if facet.receipt_event_ids:
            continue
        namespace = namespaces.get(facet.source_adapter)
        if namespace is None:
            continue
        connected = store.connected_work_refs(TypedRef(namespace, facet.session_native_id))
        receipts: set[str] = set()
        for reference in connected:
            event = store.event_for_ref(reference)
            if event is None:
                continue
            receipts.update(
                item.event_id
                for item in store.event_family((event.event_id,))
                if isinstance(item.payload, OutcomePayload) and item.occurred_at < cutoff
            )
        if receipts:
            result[facet.session_id] = tuple(sorted(receipts))
    return result


def append_motif_findings(
    ledger: FindingLedger, projection: MotifProjection, *, recorded_at: datetime
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


def _candidate(
    proposal: MotifProposal,
    assessment: MotifAssessment,
    config: MotifGeneratorConfig,
    snapshot: str,
    synthesis: MotifSynthesisReceipt,
    evaluation: FindingEvaluationResult | None,
    receipt_ids: tuple[str, ...],
    grade: FindingGrade,
) -> MotifFindingCandidate:
    manifest = FindingManifest(
        source_snapshot=snapshot,
        generator=FAILURE_MOTIF_GENERATOR,
        scope={
            **config.to_dict(),
            "motif_id": proposal.motif_id,
            "method": synthesis.method,
            "model": synthesis.model,
            "harness": synthesis.harness,
            "parameters_digest": synthesis.parameters_digest,
            "synthesis_id": synthesis.synthesis_id,
            "evaluation_result_id": evaluation.result_id if evaluation else None,
            "content_policy": "metadata-only",
        },
        coverage=1.0,
        coverage_gaps=(),
        generated_at=config.cutoff,
        expires_at=config.cutoff + timedelta(days=config.expires_after_days),
    )
    return MotifFindingCandidate(
        subject=proposal.motif_id,
        grade=grade,
        summary=proposal.summary,
        details={
            "motif_id": proposal.motif_id,
            "independent_sessions": assessment.independent_sessions,
            "corroborating_receipts": assessment.corroborating_receipts,
            "aggregation_size": assessment.aggregation_size,
            "session_ids": list(proposal.session_ids),
            "receipt_event_ids": list(receipt_ids),
            "synthesis_id": synthesis.synthesis_id,
            "evaluation_result_id": evaluation.result_id if evaluation else None,
        },
        evidence=tuple(
            EvidenceRef(event_id, "session-or-outcome-receipt")
            for event_id in assessment.evidence_event_ids
        ),
        manifest=manifest,
    )


def _bounded_error_category(error: str) -> str:
    lowered = error.lower()
    if any(token in lowered for token in ("permission", "denied", "read_only", "read-only")):
        return "permission"
    if "rate" in lowered and "limit" in lowered:
        return "rate-limit"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    return "tool-failed"


def _scope_change_count(attributes: dict[str, JsonValue]) -> int:
    value = attributes.get("scope_changes", 0)
    return value if type(value) is int else 0


def _failed_action_fingerprint(event: NormalizedEvent, payload: ToolCallPayload) -> str | None:
    metadata = event.attributes.get("input_metadata")
    if not isinstance(metadata, dict):
        return None
    digest = metadata.get("sha256")
    if not isinstance(digest, str) or not digest:
        return None
    return stable_id("act", payload.tool_name or "unknown", digest)


def _facet_supports(motif_id: str, facet: FailureFacet) -> bool:
    if motif_id == "retry-storm":
        return facet.repeated_failure_fingerprint is not None
    if motif_id == "permission-loop":
        return facet.repeated_failed_tool is not None and "permission" in facet.error_categories
    if motif_id == "context-drift":
        terminal = {"failed", "reverted", "abandoned"}
        return facet.scope_changes > 0 and bool(terminal & set(facet.outcome_statuses))
    return False


def _same_candidate(existing: FindingRevision, candidate: MotifFindingCandidate) -> bool:
    return (
        existing.kind is FindingKind.FAILURE_MOTIF
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
