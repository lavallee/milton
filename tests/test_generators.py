from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from milton.errors import ValidationError
from milton.findings import FindingGrade, FindingKind, FindingLedger
from milton.generators import (
    GateAssessment,
    GateAssessmentReason,
    GateAssessmentState,
    GateCaseLabel,
    GateCasePartition,
    GateDetectorConfig,
    GateDetectorProjection,
    GateEvaluationCase,
    GateRule,
    GateSourceState,
    GateSurfaceDecision,
    append_gate_findings,
    detect_george_gates,
    evaluate_gate_cases,
)
from milton.model import (
    GateConsultation,
    GateEvidenceKind,
    GateEvidencePayload,
    GateStatus,
    NormalizedEvent,
    SourceRef,
)
from milton.store import MiltonStore

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def gate_event(
    native_id: str,
    *,
    kind: GateEvidenceKind = GateEvidenceKind.MINT,
    coordinate: str | None = "target=work-1",
    offset_days: int = 0,
    status: GateStatus = GateStatus.OPEN,
    consultation: GateConsultation | None = None,
    ambiguous: bool = False,
) -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("george", native_id),
        occurred_at=NOW + timedelta(days=offset_days),
        recorded_at=NOW + timedelta(days=offset_days),
        payload=GateEvidencePayload(
            evidence_kind=kind,
            coordinate=coordinate,
            mint_id=native_id if kind is GateEvidenceKind.MINT else None,
            status=status,
            consultation=consultation,
            disposition=status.value if kind is not GateEvidenceKind.MINT else None,
        ),
        attributes={"coordinate_ambiguous": ambiguous},
    )


def config(
    *,
    source_state: GateSourceState = GateSourceState.FRESH,
    cutoff_days: int = 12,
) -> GateDetectorConfig:
    return GateDetectorConfig(
        since=NOW,
        cutoff=NOW + timedelta(days=cutoff_days),
        source_state=source_state,
        remint_threshold=3,
        remint_window_days=7,
        old_after_days=7,
    )


def assessment_for(projection: GateDetectorProjection, rule: GateRule) -> GateAssessment:
    return next(item for item in projection.assessments if item.rule is rule)


def test_resolved_rule_has_positive_negative_ambiguous_and_stale_source_cases() -> None:
    mint = gate_event("mint-1")
    resolution = gate_event(
        "decision-1",
        kind=GateEvidenceKind.DECISION,
        offset_days=2,
        status=GateStatus.RESOLVED,
    )
    positive = assessment_for(
        detect_george_gates((mint, resolution), config()), GateRule.CONDITION_RESOLVED
    )
    negative = assessment_for(detect_george_gates((mint,), config()), GateRule.CONDITION_RESOLVED)
    ambiguous = assessment_for(
        detect_george_gates(
            (gate_event("mint-ambiguous", coordinate=None, ambiguous=True),), config()
        ),
        GateRule.CONDITION_RESOLVED,
    )
    stale = assessment_for(
        detect_george_gates((mint, resolution), config(source_state=GateSourceState.STALE)),
        GateRule.CONDITION_RESOLVED,
    )

    assert (positive.state, positive.reason) == (
        GateAssessmentState.DETECTED,
        GateAssessmentReason.RESOLUTION_RECEIPT,
    )
    assert (negative.state, negative.reason) == (
        GateAssessmentState.NOT_DETECTED,
        GateAssessmentReason.NO_RESOLUTION,
    )
    assert (ambiguous.state, ambiguous.reason) == (
        GateAssessmentState.ABSTAIN,
        GateAssessmentReason.COORDINATE_AMBIGUOUS,
    )
    assert (stale.state, stale.reason) == (
        GateAssessmentState.ABSTAIN,
        GateAssessmentReason.STALE_SOURCE,
    )

    mint_target_resolution = gate_event(
        "decision-by-mint",
        kind=GateEvidenceKind.DECISION,
        coordinate="target=mint-1",
        offset_days=3,
        status=GateStatus.RESOLVED,
    )
    resolved_through_mint = assessment_for(
        detect_george_gates((mint, mint_target_resolution), config()),
        GateRule.CONDITION_RESOLVED,
    )
    assert resolved_through_mint.reason is GateAssessmentReason.RESOLUTION_RECEIPT


def test_remint_rule_has_positive_negative_ambiguous_and_stale_source_cases() -> None:
    mints = tuple(gate_event(f"mint-{index}", offset_days=index) for index in range(3))
    positive_projection = detect_george_gates(mints, config())
    positive = assessment_for(positive_projection, GateRule.REMINTED)
    negative = assessment_for(detect_george_gates(mints[:2], config()), GateRule.REMINTED)
    ambiguous = assessment_for(
        detect_george_gates((gate_event("mint-x", coordinate=None),), config()),
        GateRule.REMINTED,
    )
    stale = assessment_for(
        detect_george_gates(mints, config(source_state=GateSourceState.UNKNOWN)),
        GateRule.REMINTED,
    )

    assert (positive.state, positive.reason, positive.details["mint_count"]) == (
        GateAssessmentState.DETECTED,
        GateAssessmentReason.REMINT_THRESHOLD,
        3,
    )
    assert positive_projection.candidates[0].grade is FindingGrade.LEAD
    assert positive_projection.candidates[0].kind is FindingKind.FAILURE_MOTIF
    assert (negative.state, negative.reason) == (
        GateAssessmentState.NOT_DETECTED,
        GateAssessmentReason.BELOW_THRESHOLD,
    )
    assert ambiguous.state is GateAssessmentState.ABSTAIN
    assert stale.reason is GateAssessmentReason.STALE_SOURCE


def test_old_unconsulted_rule_requires_explicit_read_evidence() -> None:
    mint = gate_event("mint-1")
    not_consulted = gate_event(
        "consult-1",
        kind=GateEvidenceKind.CONSULT,
        offset_days=8,
        consultation=GateConsultation.NOT_CONSULTED,
    )
    consulted = gate_event(
        "consult-2",
        kind=GateEvidenceKind.CONSULT,
        offset_days=8,
        consultation=GateConsultation.CONSULTED,
    )
    positive = assessment_for(
        detect_george_gates((mint, not_consulted), config()), GateRule.OLD_UNCONSULTED
    )
    negative = assessment_for(
        detect_george_gates((mint, consulted), config()), GateRule.OLD_UNCONSULTED
    )
    unknown = assessment_for(detect_george_gates((mint,), config()), GateRule.OLD_UNCONSULTED)
    ambiguous = assessment_for(
        detect_george_gates((gate_event("mint-x", coordinate=None),), config()),
        GateRule.OLD_UNCONSULTED,
    )
    stale = assessment_for(
        detect_george_gates((mint, not_consulted), config(source_state=GateSourceState.STALE)),
        GateRule.OLD_UNCONSULTED,
    )

    assert (positive.state, positive.reason) == (
        GateAssessmentState.DETECTED,
        GateAssessmentReason.EXPLICIT_NOT_CONSULTED,
    )
    assert (negative.state, negative.reason) == (
        GateAssessmentState.NOT_DETECTED,
        GateAssessmentReason.CONSULTED,
    )
    assert (unknown.state, unknown.reason) == (
        GateAssessmentState.ABSTAIN,
        GateAssessmentReason.CONSULTATION_UNKNOWN,
    )
    assert ambiguous.state is GateAssessmentState.ABSTAIN
    assert stale.reason is GateAssessmentReason.STALE_SOURCE


def test_generation_is_dry_until_append_and_replays_without_duplicate_findings(
    tmp_path: Path,
) -> None:
    events = tuple(gate_event(f"mint-{index}", offset_days=index) for index in range(3))
    projection = detect_george_gates(events, config())
    reversed_projection = detect_george_gates(reversed(events), config())
    ledger = FindingLedger(tmp_path / "findings.jsonl")

    assert not ledger.path.exists()
    assert reversed_projection.to_dict() == projection.to_dict()
    assert all(candidate.grade is FindingGrade.LEAD for candidate in projection.candidates)
    assert len(projection.candidates) == 1

    inserted, replayed = append_gate_findings(
        ledger, projection, recorded_at=NOW + timedelta(days=12)
    )
    inserted_again, replayed_again = append_gate_findings(
        ledger, projection, recorded_at=NOW + timedelta(days=13)
    )

    assert (inserted, replayed) == (1, 0)
    assert (inserted_again, replayed_again) == (0, 1)
    assert len(tuple(ledger.records())) == 1


def test_evaluation_below_precision_floor_stays_offline_and_rejects_partition_leakage(
    tmp_path: Path,
) -> None:
    families = {
        coordinate: tuple(
            gate_event(
                f"{coordinate}-mint-{index}",
                coordinate=f"target={coordinate}",
                offset_days=index,
            )
            for index in range(3)
        )
        for coordinate in ("supported", "unsupported", "duplicate")
    }
    with MiltonStore(tmp_path / "events.db") as store:
        for events in families.values():
            store.append_events(events)
        cases = tuple(
            GateEvaluationCase(
                case_id=f"case-{coordinate}",
                partition=GateCasePartition.HELDOUT,
                rule=GateRule.REMINTED,
                label=label,
                rationale=f"reviewed {coordinate} case",
                source_coordinates=(f"george.gate=target={coordinate}",),
                event_ids=tuple(sorted(event.event_id for event in families[coordinate])),
                config=config(),
            )
            for coordinate, label in (
                ("supported", GateCaseLabel.SUPPORTED),
                ("unsupported", GateCaseLabel.UNSUPPORTED),
                ("duplicate", GateCaseLabel.DUPLICATE),
            )
        )
        evaluation = evaluate_gate_cases(cases, store)

        remint = next(item for item in evaluation.rules if item.rule is GateRule.REMINTED)
        assert remint.precision == pytest.approx(1 / 3)
        assert remint.decision is GateSurfaceDecision.OFFLINE
        assert GateRule.REMINTED not in evaluation.surface_rules

        overlapping = (
            GateEvaluationCase(
                case_id="tuning",
                partition=GateCasePartition.TUNING,
                rule=GateRule.REMINTED,
                label=GateCaseLabel.SUPPORTED,
                rationale="tuning case",
                source_coordinates=("george.gate=shared",),
                event_ids=tuple(sorted(event.event_id for event in families["supported"])),
                config=config(),
            ),
            GateEvaluationCase(
                case_id="heldout",
                partition=GateCasePartition.HELDOUT,
                rule=GateRule.REMINTED,
                label=GateCaseLabel.SUPPORTED,
                rationale="held-out case",
                source_coordinates=("george.gate=shared",),
                event_ids=tuple(sorted(event.event_id for event in families["supported"])),
                config=config(),
            ),
        )
        with pytest.raises(ValidationError, match="overlap"):
            evaluate_gate_cases(overlapping, store)

        event_leakage = (
            GateEvaluationCase(
                case_id="tuning-events",
                partition=GateCasePartition.TUNING,
                rule=GateRule.REMINTED,
                label=GateCaseLabel.SUPPORTED,
                rationale="tuning case",
                source_coordinates=("george.gate=tuning-only",),
                event_ids=tuple(sorted(event.event_id for event in families["supported"])),
                config=config(),
            ),
            GateEvaluationCase(
                case_id="heldout-events",
                partition=GateCasePartition.HELDOUT,
                rule=GateRule.REMINTED,
                label=GateCaseLabel.SUPPORTED,
                rationale="held-out case",
                source_coordinates=("george.gate=heldout-only",),
                event_ids=tuple(sorted(event.event_id for event in families["supported"])),
                config=config(),
            ),
        )
        with pytest.raises(ValidationError, match="event ids overlap"):
            evaluate_gate_cases(event_leakage, store)
