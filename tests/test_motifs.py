from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from milton.cli import main
from milton.errors import ValidationError
from milton.evaluation import (
    EvaluationFloors,
    EvaluationPartition,
    EvaluationTuple,
    FindingEvaluationCase,
    FindingEvaluationResult,
    FindingPrediction,
    evaluate_findings,
)
from milton.findings import FindingGrade, FindingLedger
from milton.generators.motifs import (
    FAILURE_MOTIF_GENERATOR,
    MotifAssessmentReason,
    MotifGeneratorConfig,
    MotifProposal,
    MotifSynthesisReceipt,
    append_motif_findings,
    build_motif_projection,
    extract_failure_facets,
)
from milton.model import (
    CallStatus,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SessionPayload,
    SourceRef,
    ToolCallPayload,
)
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
PARAMETERS = "parameters-v1"


def session_family(index: int, *, receipt: bool = True) -> tuple[NormalizedEvent, ...]:
    root = NormalizedEvent.create(
        source=SourceRef("codex", f"session-{index}"),
        occurred_at=NOW + timedelta(minutes=index),
        recorded_at=NOW + timedelta(minutes=index),
        payload=SessionPayload("project", "/redacted", "failed", "codex"),
    )
    tools = tuple(
        NormalizedEvent.create(
            source=SourceRef("codex", f"session-{index}:tool-{attempt}"),
            occurred_at=root.occurred_at + timedelta(seconds=attempt),
            recorded_at=root.recorded_at + timedelta(seconds=attempt),
            session_id=root.event_id,
            attributes={"input_metadata": {"sha256": f"same-input-{index}"}},
            payload=ToolCallPayload("shell", CallStatus.FAILED, None, None, "permission denied"),
        )
        for attempt in range(3)
    )
    outcome = (
        (
            NormalizedEvent.create(
                source=SourceRef("fab", f"receipt-{index}"),
                occurred_at=root.occurred_at + timedelta(seconds=10),
                recorded_at=root.recorded_at + timedelta(seconds=10),
                session_id=root.event_id,
                payload=OutcomePayload("fab.attempt", OutcomeStatus.FAILED, f"attempt-{index}"),
            ),
        )
        if receipt
        else ()
    )
    return (root, *tools, *outcome)


def config() -> MotifGeneratorConfig:
    return MotifGeneratorConfig(NOW, NOW + timedelta(hours=1))


def surface_evaluation() -> FindingEvaluationResult:
    cases = (
        FindingEvaluationCase(
            "held-positive",
            EvaluationPartition.HELDOUT,
            True,
            None,
            "reviewed recurring motif",
            ("fixture=positive",),
            ("fixture-event-positive",),
        ),
        FindingEvaluationCase(
            "held-negative",
            EvaluationPartition.HELDOUT,
            False,
            None,
            "reviewed clean session",
            ("fixture=negative",),
            ("fixture-event-negative",),
        ),
    )
    return evaluate_findings(
        cases,
        (
            FindingPrediction(
                "held-positive", True, None, ("session-1", "session-2", "session-3"), 3
            ),
            FindingPrediction("held-negative", False, None, (), 0),
        ),
        evaluation_tuple=EvaluationTuple(
            FAILURE_MOTIF_GENERATOR,
            "qwen2.5:7b",
            "ollama-api/v1",
            PARAMETERS,
            "frozen-corpus-v1",
        ),
        floors=EvaluationFloors(recurrence=3, aggregation=3),
    )


def synthesis(
    events: tuple[NormalizedEvent, ...], session_ids: tuple[str, ...]
) -> MotifSynthesisReceipt:
    snapshot, _ = extract_failure_facets(events, config())
    return MotifSynthesisReceipt.create(
        source_snapshot=snapshot,
        method="direct",
        model="qwen2.5:7b",
        harness="ollama-api/v1",
        parameters_digest=PARAMETERS,
        proposals=(
            MotifProposal(
                "permission-loop",
                tuple(sorted(session_ids)),
                "Permission-denied actions recur without a changed target or policy",
            ),
        ),
    )


def test_motif_projection_requires_independent_sessions_receipts_and_privacy() -> None:
    families = tuple(session_family(index) for index in range(3))
    events = tuple(event for family in families for event in family)
    session_ids = tuple(family[0].event_id for family in families)
    projection = build_motif_projection(
        events,
        config(),
        synthesis=synthesis(events, session_ids),
        evaluation=surface_evaluation(),
    )

    assert len(projection.facets) == 3
    assert all(facet.error_categories == ("permission",) for facet in projection.facets)
    assert all(facet.repeated_tool == "shell" for facet in projection.facets)
    assert all(facet.repeated_failed_tool == "shell" for facet in projection.facets)
    assert all(facet.repeated_failure_fingerprint is not None for facet in projection.facets)
    assert all(facet.failed_tool_attempts == 3 for facet in projection.facets)
    assert projection.assessments[0].reason is MotifAssessmentReason.EVIDENCE_FLOORS_MET
    assert projection.assessments[0].corroborating_receipts == 3
    assert len(projection.candidates) == 1
    assert projection.candidates[0].grade is FindingGrade.CANDIDATE
    assert projection.candidates[0].manifest.expires_at == NOW + timedelta(hours=1, days=14)
    assert projection.candidates[0].manifest.scope["content_policy"] == "metadata-only"

    small = build_motif_projection(
        events,
        config(),
        synthesis=synthesis(events, session_ids[:2]),
        evaluation=surface_evaluation(),
    )
    assert not small.candidates
    assert small.assessments[0].reason is MotifAssessmentReason.INSUFFICIENT_RECURRENCE

    privacy_config = MotifGeneratorConfig(
        NOW,
        NOW + timedelta(hours=1),
        minimum_recurrence=2,
        minimum_receipts=2,
        minimum_aggregation=3,
    )
    privacy_snapshot, _ = extract_failure_facets(events, privacy_config)
    privacy_synthesis = MotifSynthesisReceipt.create(
        source_snapshot=privacy_snapshot,
        method="direct",
        model="qwen2.5:7b",
        harness="ollama-api/v1",
        parameters_digest=PARAMETERS,
        proposals=synthesis(events, session_ids[:2]).proposals,
    )
    private = build_motif_projection(
        events,
        privacy_config,
        synthesis=privacy_synthesis,
        evaluation=None,
    )
    assert not private.candidates
    assert private.assessments[0].reason is MotifAssessmentReason.PRIVATE_SMALL_GROUP


def test_failed_tool_receipts_corroborate_and_synthesis_cannot_self_corroborate() -> None:
    families = (session_family(0), session_family(1), session_family(2, receipt=False))
    events = tuple(event for family in families for event in family)
    session_ids = tuple(family[0].event_id for family in families)
    projection = build_motif_projection(
        events,
        config(),
        synthesis=synthesis(events, session_ids),
        evaluation=surface_evaluation(),
    )
    assert len(projection.candidates) == 1
    assert projection.assessments[0].corroborating_receipts == 3

    externally_corroborated = build_motif_projection(
        events,
        config(),
        synthesis=synthesis(events, session_ids),
        evaluation=surface_evaluation(),
        corroborating_receipts={session_ids[2]: ("external-fab-outcome-receipt",)},
    )
    assert externally_corroborated.assessments[0].corroborating_receipts == 3
    assert len(externally_corroborated.candidates) == 1

    complete_events = tuple(event for index in range(3) for event in session_family(index + 10))
    complete_ids = tuple(
        event.event_id for event in complete_events if isinstance(event.payload, SessionPayload)
    )
    lead = build_motif_projection(
        complete_events,
        config(),
        synthesis=synthesis(complete_events, complete_ids),
        evaluation=None,
    )
    assert lead.candidates[0].grade is FindingGrade.LEAD
    assert all(candidate.grade is not FindingGrade.CORROBORATED for candidate in lead.candidates)


def test_evaluated_tuple_and_floors_cannot_be_weakened() -> None:
    events = tuple(event for index in range(3) for event in session_family(index))
    session_ids = tuple(
        event.event_id for event in events if isinstance(event.payload, SessionPayload)
    )
    receipt = synthesis(events, session_ids)
    weak_config = MotifGeneratorConfig(
        NOW,
        NOW + timedelta(hours=1),
        minimum_recurrence=2,
        minimum_aggregation=2,
    )
    weak_snapshot, _ = extract_failure_facets(events, weak_config)
    weak_receipt = MotifSynthesisReceipt.create(
        source_snapshot=weak_snapshot,
        method=receipt.method,
        model=receipt.model,
        harness=receipt.harness,
        parameters_digest=receipt.parameters_digest,
        proposals=receipt.proposals,
    )
    with pytest.raises(ValidationError, match="cannot weaken"):
        build_motif_projection(
            events,
            weak_config,
            synthesis=weak_receipt,
            evaluation=surface_evaluation(),
        )

    mismatched = MotifSynthesisReceipt.create(
        source_snapshot=receipt.source_snapshot,
        method="direct",
        model="different-model",
        harness="ollama-api/v1",
        parameters_digest=PARAMETERS,
        proposals=receipt.proposals,
    )
    with pytest.raises(ValidationError, match="does not match evaluated"):
        build_motif_projection(
            events,
            config(),
            synthesis=mismatched,
            evaluation=surface_evaluation(),
        )


def test_motif_append_is_idempotent(tmp_path: Path) -> None:
    events = tuple(event for index in range(3) for event in session_family(index))
    session_ids = tuple(
        event.event_id for event in events if isinstance(event.payload, SessionPayload)
    )
    projection = build_motif_projection(
        events,
        config(),
        synthesis=synthesis(events, session_ids),
        evaluation=surface_evaluation(),
    )
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    assert append_motif_findings(ledger, projection, recorded_at=NOW) == (1, 0)
    assert append_motif_findings(ledger, projection, recorded_at=NOW + timedelta(seconds=1)) == (
        0,
        1,
    )
    assert len(ledger.current()) == 1


def test_motif_cli_consumes_exact_synthesis_and_measured_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tuple(event for index in range(3) for event in session_family(index))
    session_ids = tuple(
        event.event_id for event in events if isinstance(event.payload, SessionPayload)
    )
    store_path = tmp_path / "events.db"
    findings_path = tmp_path / "findings.jsonl"
    synthesis_path = tmp_path / "synthesis.json"
    evaluation_path = tmp_path / "evaluation.json"
    with MiltonStore(store_path) as store:
        store.append_events(events)
    synthesis_path.write_text(
        json.dumps(synthesis(events, session_ids).to_dict()), encoding="utf-8"
    )
    evaluation_path.write_text(json.dumps(surface_evaluation().to_dict()), encoding="utf-8")
    args = [
        "findings",
        "generate",
        "--generator",
        "failure-motifs",
        "--store",
        str(store_path),
        "--findings",
        str(findings_path),
        "--since",
        "2026-07-17T12:00:00Z",
        "--until",
        "2026-07-17T13:00:00Z",
        "--synthesis",
        str(synthesis_path),
        "--evaluation-result",
        str(evaluation_path),
        "--recorded-at",
        "2026-07-17T13:00:01Z",
        "--format",
        "json",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["projection"]["counts"]["candidates"] == 1
    assert result["emission"] == {
        "inserted": 1,
        "maximum_grade": "candidate",
        "replayed": 0,
    }
    assert main(args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["emission"]["inserted"] == 0
    assert replay["emission"]["replayed"] == 1
