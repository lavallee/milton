from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from milton.errors import LedgerCorruptionError, ValidationError
from milton.findings import (
    EvidenceRef,
    FindingDisposition,
    FindingGrade,
    FindingKind,
    FindingLedger,
    FindingManifest,
    FindingRevision,
    ReceiptFreshness,
    ReceiptValidity,
    build_finding_activity,
)
from milton.model import NormalizedEvent, OutcomePayload, OutcomeStatus, SourceRef, format_datetime
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def manifest() -> FindingManifest:
    return FindingManifest(
        source_snapshot="sha256:snapshot",
        generator="milton.test/1",
        scope={"project": "milton"},
        coverage=0.8,
        coverage_gaps=("missing gateway ledger",),
        generated_at=NOW,
    )


def lead() -> FindingRevision:
    return FindingRevision.create(
        subject="retry-storm/tool-x",
        kind=FindingKind.FAILURE_MOTIF,
        grade=FindingGrade.LEAD,
        summary="Tool X is repeatedly retried",
        details={"occurrences": 3},
        evidence=(EvidenceRef("evt_1", "first occurrence"),),
        manifest=manifest(),
        recorded_at=NOW,
    )


def test_ledger_retains_the_grading_history(tmp_path: Path) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    initial = lead()
    candidate = initial.revise(
        grade=FindingGrade.CANDIDATE,
        evidence=(
            EvidenceRef("evt_1", "first occurrence"),
            EvidenceRef("evt_2", "independent occurrence"),
        ),
        recorded_at=NOW + timedelta(seconds=1),
    )
    refuted = candidate.revise(
        grade=FindingGrade.REFUTED,
        summary="Retries came from the test fixture",
        recorded_at=NOW + timedelta(seconds=2),
    )

    assert ledger.append(initial)
    assert not ledger.append(initial)
    assert ledger.append(candidate)
    assert ledger.append(refuted)

    assert list(ledger.records()) == [initial, candidate, refuted]
    assert ledger.current()[initial.finding_id] == refuted


def test_ledger_rejects_stale_or_backward_revisions(tmp_path: Path) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    initial = lead()
    candidate = initial.revise(
        grade=FindingGrade.CANDIDATE,
        recorded_at=NOW + timedelta(seconds=1),
    )
    ledger.append(initial)
    ledger.append(candidate)

    stale = initial.revise(
        grade=FindingGrade.CORROBORATED,
        recorded_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValidationError, match="must supersede current"):
        ledger.append(stale)

    backward = candidate.revise(
        grade=FindingGrade.LEAD,
        recorded_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(ValidationError, match="cannot move backward"):
        ledger.append(backward)

    backward_time = candidate.revise(
        grade=FindingGrade.CORROBORATED,
        recorded_at=NOW - timedelta(seconds=1),
    )
    with pytest.raises(ValidationError, match="forward in time"):
        ledger.append(backward_time)


def test_malformed_ledger_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "findings.jsonl"
    path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(LedgerCorruptionError, match="line 1"):
        list(FindingLedger(path).records())


def _george_receipt(native_id: str = "disposition-1") -> NormalizedEvent:
    return NormalizedEvent.create(
        source=SourceRef("george", native_id),
        occurred_at=NOW + timedelta(seconds=1),
        recorded_at=NOW + timedelta(seconds=1),
        payload=OutcomePayload("george.finding-disposition", OutcomeStatus.SUCCEEDED, None),
    )


def _record_george_coverage(store: MiltonStore, *, status: str = "ok") -> None:
    store.record_adapter_run(
        adapter="george",
        status=status,
        content_policy="metadata",
        since_at=None,
        sources_discovered=1,
        sources_read=int(status == "ok"),
        sources_unchanged=0,
        sources_outside_window=0,
        sources_failed=int(status == "error"),
        source_records=1,
        malformed_records=0,
        events_inserted=1,
        crosswalks_inserted=0,
        ingested_at=format_datetime(NOW + timedelta(seconds=1)),
    )


def _action_relation(
    finding: FindingRevision,
    receipt: NormalizedEvent,
    *,
    predicate: RelationKind = RelationKind.ACTS_ON,
) -> RelationRecord:
    return RelationRecord.create(
        subject=TypedRef("milton.finding-revision", finding.revision_id),
        predicate=predicate,
        object=TypedRef("george.disposition", receipt.source.native_id),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=(receipt.event_id,),
        recorded_at=NOW + timedelta(seconds=2),
    )


def test_finding_without_a_valid_receipt_is_not_acted_on(tmp_path: Path) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = lead()
    ledger.append(finding)
    missing = _george_receipt("missing")

    with MiltonStore(tmp_path / "events.db") as store:
        _record_george_coverage(store)
        store.append_relation(_action_relation(finding, missing))
        projection = build_finding_activity(store, ledger, finding.finding_id)

    assert projection.disposition is FindingDisposition.NONE
    assert not projection.acted_on
    assert not projection.ever_acted_on
    assert projection.freshness is ReceiptFreshness.INVALID
    assert projection.receipts[0].validity is ReceiptValidity.INVALID


def test_valid_receipt_derives_action_and_coverage_loss_only_qualifies_freshness(
    tmp_path: Path,
) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = lead()
    ledger.append(finding)
    receipt = _george_receipt()

    with MiltonStore(tmp_path / "events.db") as store:
        store.append_event(receipt)
        _record_george_coverage(store)
        store.append_relation(_action_relation(finding, receipt))

        projection = build_finding_activity(store, ledger, finding.finding_id)
        assert projection.disposition is FindingDisposition.ACTED_ON
        assert projection.acted_on
        assert projection.ever_acted_on
        assert projection.freshness is ReceiptFreshness.CURRENT
        assert projection.to_dict()["state"] == {
            "acted_on": True,
            "refuted": False,
            "evaluated": False,
            "promoted": False,
        }

        _record_george_coverage(store, status="error")
        unavailable = build_finding_activity(store, ledger, finding.finding_id)

    assert unavailable.disposition is FindingDisposition.ACTED_ON
    assert unavailable.ever_acted_on
    assert unavailable.freshness is ReceiptFreshness.UNKNOWN
    assert unavailable.receipts[0].validity is ReceiptValidity.VALID


def test_relation_refutation_changes_current_state_but_retains_revision_history(
    tmp_path: Path,
) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = lead()
    ledger.append(finding)
    receipt = _george_receipt()
    action = _action_relation(finding, receipt)

    with MiltonStore(tmp_path / "events.db") as store:
        store.append_event(receipt)
        _record_george_coverage(store)
        store.append_relation(action)
        store.append_relation(
            action.refute(
                note="George linked the wrong disposition",
                recorded_at=NOW + timedelta(seconds=3),
            )
        )
        projection = build_finding_activity(store, ledger, finding.finding_id)

    assert projection.disposition is FindingDisposition.NONE
    assert not projection.ever_acted_on
    assert not projection.acted_on
    assert len(projection.receipts) == 1
    assert not projection.receipts[0].active
    assert projection.receipts[0].relation.state.value == "refuted"


def test_action_targets_exact_revision_and_refutation_is_separate_from_acted_on(
    tmp_path: Path,
) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = lead()
    ledger.append(finding)
    receipt = _george_receipt()

    with MiltonStore(tmp_path / "events.db") as store:
        store.append_event(receipt)
        _record_george_coverage(store)
        store.append_relation(_action_relation(finding, receipt, predicate=RelationKind.REFUTES))
        refuted_projection = build_finding_activity(store, ledger, finding.finding_id)

        assert refuted_projection.disposition is FindingDisposition.REFUTED
        assert refuted_projection.refuted
        assert not refuted_projection.acted_on
        assert not refuted_projection.ever_acted_on

    revised = finding.revise(
        grade=FindingGrade.CANDIDATE,
        recorded_at=NOW + timedelta(seconds=4),
    )
    ledger.append(revised)
    with MiltonStore(tmp_path / "events.db") as store:
        revised_projection = build_finding_activity(store, ledger, finding.finding_id)

    assert revised_projection.disposition is FindingDisposition.NONE
    assert not revised_projection.refuted
    assert len(revised_projection.receipts) == 1
    assert not revised_projection.receipts[0].current_finding_revision
