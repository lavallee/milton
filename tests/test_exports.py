from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from milton.adapters import ContentPolicy
from milton.adapters.chip import ChipAdapter
from milton.adapters.george import GeorgeAdapter
from milton.cli import main
from milton.exports import build_chip_candidate_export, build_george_finding_candidate
from milton.findings import (
    EvidenceRef,
    FindingDisposition,
    FindingGrade,
    FindingKind,
    FindingLedger,
    FindingManifest,
    FindingRevision,
    build_finding_activity,
)
from milton.ingest import Ingestor
from milton.model import JsonValue
from milton.relations import TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def _finding(ledger: FindingLedger) -> FindingRevision:
    finding = FindingRevision.create(
        subject="condition-resolved:target=work-1",
        kind=FindingKind.STALE_GATE,
        grade=FindingGrade.LEAD,
        summary="Gate condition has an exact later resolution receipt",
        details={"rule": "condition-resolved", "coordinate": "target=work-1"},
        evidence=(
            EvidenceRef("evt_mint", "gate-mint"),
            EvidenceRef("evt_decision", "resolution"),
        ),
        manifest=FindingManifest(
            source_snapshot="snp_1",
            generator="milton.george-gates/v1",
            scope={"coordinate": "target=work-1", "cutoff_exclusive": "2026-07-18T00:00:00Z"},
            coverage=0.9,
            coverage_gaps=("consultation receipts unavailable",),
            generated_at=NOW,
            expires_at=NOW + timedelta(days=7),
        ),
        recorded_at=NOW,
    )
    assert ledger.append(finding)
    return finding


def _chip_finding(ledger: FindingLedger) -> FindingRevision:
    finding = FindingRevision.create(
        subject="procedure:retry-with-policy-change",
        kind=FindingKind.PROCEDURE_CANDIDATE,
        grade=FindingGrade.CANDIDATE,
        summary="When a permission retry recurs, change policy or target before retrying",
        details={
            "occurrence_refs": ["session:one", "session:two"],
            "counterexample_refs": ["fixture:negative:clean-retry"],
            "fixture_refs": [
                "fixture:exception:policy-unavailable",
                "fixture:positive:permission-loop",
            ],
        },
        evidence=(
            EvidenceRef("evt_occurrence_one", "recurrence"),
            EvidenceRef("evt_occurrence_two", "recurrence"),
        ),
        manifest=FindingManifest(
            source_snapshot="snp_procedure_1",
            generator="milton.procedure-candidates/v1",
            scope={"content_policy": "metadata-only", "minimum_recurrence": 2},
            coverage=0.75,
            coverage_gaps=("one harness unavailable",),
            generated_at=NOW,
            expires_at=NOW + timedelta(days=14),
        ),
        recorded_at=NOW,
    )
    assert ledger.append(finding)
    return finding


def test_george_candidate_export_is_immutable_advisory_and_complete(tmp_path: Path) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = _finding(ledger)

    first = build_george_finding_candidate(ledger, finding.finding_id)
    replay = build_george_finding_candidate(ledger, finding.finding_id)
    first_finding = cast(dict[str, JsonValue], first["finding"])
    coverage = cast(dict[str, JsonValue], first["coverage"])
    generator = cast(dict[str, JsonValue], first["generator"])
    taint = cast(dict[str, JsonValue], first["taint"])
    evidence = cast(list[dict[str, JsonValue]], first["evidence"])

    assert replay == first
    assert first["schema"] == "milton.finding-candidate/v1"
    assert first_finding["revision_id"] == finding.revision_id
    assert first["target"] == {
        "system": "george",
        "project": "george",
        "coordinate": "target=work-1",
    }
    assert first["suggestion"] == {
        "kind": "review-stale-gate",
        "authority": "george",
        "advisory_only": True,
    }
    assert coverage["value"] == 0.9
    assert first["expiry"] == "2026-07-24T12:00:00Z"
    assert generator["id"] == "milton.george-gates/v1"
    assert taint["instruction_authority"] == "none"
    assert [item["event_id"] for item in evidence] == [
        "evt_mint",
        "evt_decision",
    ]


def test_george_candidate_is_available_from_public_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = _finding(ledger)
    assert (
        main(
            [
                "findings",
                "export",
                finding.finding_id,
                "--findings",
                str(ledger.path),
                "--contract",
                "george",
            ]
        )
        == 0
    )
    document = json.loads(capsys.readouterr().out)
    assert document["schema"] == "milton.finding-candidate/v1"
    assert document["finding"]["revision_id"] == finding.revision_id


def test_george_disposition_round_trip_derives_refutation_without_dependency(
    tmp_path: Path,
) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = _finding(ledger)
    candidate = build_george_finding_candidate(ledger, finding.finding_id)
    candidate_finding = candidate["finding"]
    candidate_target = candidate["target"]
    assert isinstance(candidate_finding, dict)
    assert isinstance(candidate_target, dict)
    receipt_id = "01KTESTGEORGERECEIPT000001"
    source = tmp_path / "george.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": receipt_id,
                "host": "dash",
                "session": "milton-finding-disposition",
                "kind": "decision",
                "content": "Refuted external finding after bounded review",
                "project": "george",
                "refs": ["intake-entry-1"],
                "tags": ["milton:finding-disposition"],
                "ts": "2026-07-17T12:01:00Z",
                "context": {
                    "milton_finding_disposition": {
                        "schema": "george.finding-disposition/v1",
                        "receipt_id": receipt_id,
                        "finding_id": candidate_finding["finding_id"],
                        "revision_id": candidate_finding["revision_id"],
                        "intake_entry_id": "intake-entry-1",
                        "actor": "operator",
                        "disposition": "refuted",
                        "subject_coordinate": candidate_target["coordinate"],
                        "decided_at": "2026-07-17T12:01:00Z",
                        "reason": "already reconciled before candidate export",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with MiltonStore(tmp_path / "events.db") as store:
        result = Ingestor(store).run(
            [GeorgeAdapter()],
            roots={"george": [source]},
            content_policy=ContentPolicy.METADATA,
            until=datetime(2026, 7, 18, tzinfo=UTC),
        )
        assert result.failed is False
        relation = store.outgoing_relations(
            TypedRef("milton.finding-revision", finding.revision_id)
        )[0]
        assert relation.predicate.value == "refutes"
        assert relation.object.value == receipt_id
        activity = build_finding_activity(store, ledger, finding.finding_id)

    assert activity.disposition is FindingDisposition.REFUTED
    assert activity.refuted is True
    assert activity.acted_on is False


def test_chip_candidate_export_preserves_refs_limits_and_cli_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = _chip_finding(ledger)

    document = build_chip_candidate_export(ledger, finding.finding_id)
    replay = build_chip_candidate_export(ledger, finding.finding_id)
    candidate = document["candidate"]
    assert isinstance(candidate, dict)
    assert replay == document
    assert candidate["sourceRevision"] == f"milton.finding-revision={finding.revision_id}"
    assert candidate["occurrenceRefs"] == ["session:one", "session:two"]
    assert candidate["counterexampleRefs"] == ["fixture:negative:clean-retry"]
    assert candidate["fixtureRefs"] == [
        "fixture:exception:policy-unavailable",
        "fixture:positive:permission-loop",
    ]
    assert candidate["sourceLimits"] == {
        "coverage": 0.75,
        "coverageGaps": ["one harness unavailable"],
        "expiresAt": "2026-07-31T12:00:00Z",
        "generator": "milton.procedure-candidates/v1",
        "sourceSnapshot": "snp_procedure_1",
        "scope": {"content_policy": "metadata-only", "minimum_recurrence": 2},
    }

    assert (
        main(
            [
                "findings",
                "export",
                finding.finding_id,
                "--findings",
                str(ledger.path),
                "--target",
                "chip",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == document


def test_milton_export_chip_ingest_and_public_receipt_round_trip(tmp_path: Path) -> None:
    """Exercise both repos while Milton reads only Chip's public receipt ledger."""

    chip_root = Path(__file__).resolve().parents[2] / "chip"
    if not (chip_root / "src" / "chip" / "candidates.py").is_file():
        pytest.skip("sibling Chip checkout is not present")

    ledger = FindingLedger(tmp_path / "findings.jsonl")
    finding = _chip_finding(ledger)
    export_path = tmp_path / "candidate-export.json"
    export_path.write_text(
        json.dumps(build_chip_candidate_export(ledger, finding.finding_id)),
        encoding="utf-8",
    )
    candidates_path = tmp_path / "chip-private" / "candidates.jsonl"
    receipts_path = tmp_path / "chip-public" / "candidate-receipts.jsonl"
    script = """
import json
import sys
from chip.candidates import commission_candidate

document = json.load(open(sys.argv[1], encoding="utf-8"))
receipt = commission_candidate(sys.argv[2], document["candidate"], receipts_path=sys.argv[3])
print(json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(chip_root / "src"), environment.get("PYTHONPATH")))
    )
    command = [
        sys.executable,
        "-c",
        script,
        str(export_path),
        str(candidates_path),
        str(receipts_path),
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True, env=environment)
    second = subprocess.run(command, check=True, capture_output=True, text=True, env=environment)
    assert second.stdout == first.stdout
    assert len(candidates_path.read_text(encoding="utf-8").splitlines()) == 1
    assert len(receipts_path.read_text(encoding="utf-8").splitlines()) == 1

    with MiltonStore(tmp_path / "events.db") as store:
        result = Ingestor(store).run(
            [ChipAdapter()],
            roots={"chip": [receipts_path]},
            content_policy=ContentPolicy.METADATA,
        )
        assert not result.failed
        assert result.adapters[0].events_inserted == 1
        assert result.adapters[0].relations_inserted == 2
        relations = store.outgoing_relations(
            TypedRef("milton.finding-revision", finding.revision_id)
        )
        assert len(relations) == 1
        assert relations[0].predicate.value == "produced"
        assert relations[0].object.namespace == "chip.candidate"
        receipt = json.loads(first.stdout)
        assert (
            store.event_for_ref(TypedRef("chip.candidate-receipt", receipt["receiptId"]))
            is not None
        )
