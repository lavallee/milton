import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from milton.cli import main
from milton.findings import FindingLedger, FindingRevision
from milton.generators import GateDetectorConfig, GateSourceState
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostPayload,
    GateEvidenceKind,
    GateEvidencePayload,
    GateStatus,
    ModelCallPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore


def test_init_and_empty_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store_path = tmp_path / "data" / "events.db"
    findings_path = tmp_path / "data" / "findings.jsonl"

    assert main(["init", "--store", str(store_path), "--findings", str(findings_path)]) == 0
    assert store_path.exists()
    assert findings_path.exists()
    capsys.readouterr()

    assert main(["report", "--store", str(store_path)]) == 0
    output = capsys.readouterr().out
    assert "No normalized events" in output
    assert "Coverage: no adapters" in output


def test_json_report_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    with MiltonStore(store_path) as store:
        store.append_event(
            NormalizedEvent.create(
                source=SourceRef("test", "cost-1"),
                occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
                recorded_at=datetime(2026, 7, 17, tzinfo=UTC),
                payload=CostPayload(Decimal("1.25"), 10, 2, 0, "p", "m"),
            )
        )

    assert main(["report", "--store", str(store_path), "--format", "json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["cost_usd"] == "1.25"
    assert output["adapters"]["test"]["events"] == 1
    assert output["accounting"]["amounts_usd"]["raw_observed"] == "1.25"


def test_accounting_command_exposes_cost_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    with MiltonStore(store_path) as store:
        store.append_event(
            NormalizedEvent.create(
                source=SourceRef("somm", "cost-1"),
                occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
                recorded_at=datetime(2026, 7, 17, tzinfo=UTC),
                payload=CostPayload(
                    Decimal("1.25"),
                    10,
                    2,
                    0,
                    "p",
                    "m",
                    basis=CostBasis.COMPUTED,
                    kind=CostKind.MARGINAL,
                    accuracy=CostAccuracy.ESTIMATED,
                    authority="somm",
                    accounting_key="somm.call=one",
                    accounting_key_scope=CostKeyScope.SOURCE,
                ),
            )
        )

    assert main(["accounting", "--store", str(store_path), "--format", "json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["amounts_usd"]["by_basis"]["computed"] == "1.25"
    assert output["amounts_usd"]["by_kind"]["marginal"] == "1.25"


def test_cost_per_outcome_reconciles_to_accounting_with_paths_and_filters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    timestamp = datetime(2026, 7, 17, 14, tzinfo=UTC)
    call = NormalizedEvent.create(
        source=SourceRef("somm", "call-1"),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=ModelCallPayload("provider", "model", CallStatus.SUCCEEDED, "stop"),
    )
    cost_event = NormalizedEvent.create(
        source=SourceRef("somm", "cost:call-1"),
        occurred_at=timestamp,
        recorded_at=timestamp,
        parent_event_id=call.event_id,
        payload=CostPayload(
            Decimal("1.25"),
            10,
            2,
            0,
            "provider",
            "model",
            basis=CostBasis.COMPUTED,
            kind=CostKind.MARGINAL,
            accuracy=CostAccuracy.ESTIMATED,
            authority="somm",
            accounting_key="somm.call=call-1",
            accounting_key_scope=CostKeyScope.SOURCE,
        ),
    )
    outcome = NormalizedEvent.create(
        source=SourceRef("fab", "terminal:job-1"),
        occurred_at=timestamp.replace(minute=1),
        recorded_at=timestamp.replace(minute=1),
        payload=OutcomePayload("fab.job", OutcomeStatus.SUCCEEDED, "job-1"),
    )
    relation = RelationRecord.create(
        subject=TypedRef("fab.job", "job-1"),
        predicate=RelationKind.PRODUCED,
        object=TypedRef("somm.call", "call-1"),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=(call.event_id,),
        recorded_at=timestamp,
    )
    with MiltonStore(store_path) as store:
        store.append_events((call, cost_event, outcome))
        store.append_relation(relation)
        accounting_total = store.accounting(
            since="2026-07-17T14:00:00Z", until="2026-07-17T15:00:00Z"
        ).selected_total_usd

    args = [
        "cost",
        "--per-outcome",
        "--store",
        str(store_path),
        "--since",
        "2026-07-17T14:00:00Z",
        "--until",
        "2026-07-17T15:00:00Z",
        "--outcome-type",
        "fab.job",
        "--format",
        "json",
    ]
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert Decimal(output["amounts_usd"]["selected_total"]) == accounting_total
    assert output["amounts_usd"] == {
        "selected_total": "1.25",
        "attributed": "1.25",
        "ambiguous": "0",
        "unallocated": "0",
    }
    assert output["denominators"]["fab.job"]["outcomes"] == 1
    assert output["records"][0]["path"]["relation_ids"] == [relation.relation_id]
    assert output["records"][0]["source"] == {
        "adapter": "somm",
        "native_id": "cost:call-1",
    }
    assert output["records"][0]["authority"] == "somm"
    assert output["records"][0]["accounting_key"] == "somm.call=call-1"
    assert output["records"][0]["accounting_key_scope"] == "source"
    assert output["records"][0]["observation_role"] == "unknown"

    text_args = [*args[:-2]]
    assert main(text_args) == 0
    text_output = capsys.readouterr().out
    assert "not automatically actual provider spend" in text_output


def test_report_explains_a_missing_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--store", str(tmp_path / "missing.db")]) == 2
    assert "Run `milton init` first" in capsys.readouterr().err


def test_activity_json_is_a_stable_consumer_surface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    with MiltonStore(store_path) as store:
        store.append_event(
            NormalizedEvent.create(
                source=SourceRef("george", "entry-1"),
                occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
                recorded_at=datetime(2026, 7, 17, tzinfo=UTC),
                payload=OutcomePayload("george.done", OutcomeStatus.SUCCEEDED, None),
            )
        )

    assert (
        main(
            [
                "activity",
                "george.entry=entry-1",
                "--store",
                str(store_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == 2
    assert output["root"] == {"namespace": "george.entry", "value": "entry-1"}
    assert output["report"]["event_count"] == 1
    assert output["relations"] == []


def test_relations_command_explains_george_fab_somm_direction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    george = TypedRef("george.entry", "entry-1")
    fab = TypedRef("fab.job", "job-1")
    somm = TypedRef("somm.call", "call-1")
    with MiltonStore(store_path) as store:
        store.append_relation(
            RelationRecord.create(
                subject=george,
                predicate=RelationKind.PRODUCED,
                object=fab,
                confidence=1,
                method=RelationMethod.EXPLICIT,
                evidence_event_ids=("evt_george",),
                recorded_at=datetime(2026, 7, 17, tzinfo=UTC),
            )
        )
        store.append_relation(
            RelationRecord.create(
                subject=fab,
                predicate=RelationKind.PRODUCED,
                object=somm,
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=("evt_fab",),
                recorded_at=datetime(2026, 7, 17, tzinfo=UTC),
            )
        )

    assert (
        main(
            [
                "relations",
                "show",
                "george.entry=entry-1",
                "--store",
                str(store_path),
                "--direction",
                "outgoing",
                "--max-depth",
                "2",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert [item["subject"]["namespace"] for item in output["relations"]] == [
        "george.entry",
        "fab.job",
    ]
    assert [item["object"]["namespace"] for item in output["relations"]] == [
        "fab.job",
        "somm.call",
    ]


def test_gate_generation_evaluation_append_list_and_show_are_one_public_flow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    findings_path = tmp_path / "findings.jsonl"
    cases_path = tmp_path / "cases.jsonl"
    start = datetime(2026, 7, 1, tzinfo=UTC)
    mints = tuple(
        NormalizedEvent.create(
            source=SourceRef("george", f"mint-{index}"),
            occurred_at=start + timedelta(days=index),
            recorded_at=start + timedelta(days=index),
            payload=GateEvidencePayload(
                GateEvidenceKind.MINT,
                "target=work-1",
                f"mint-{index}",
                GateStatus.OPEN,
            ),
        )
        for index in range(3)
    )
    with MiltonStore(store_path) as store:
        store.append_events(mints)

    detector_config = GateDetectorConfig(
        since=start,
        cutoff=start + timedelta(days=12),
        source_state=GateSourceState.FRESH,
    )
    evaluation_case = {
        "case_id": "heldout-remint-positive",
        "partition": "heldout",
        "rule": "re-minted",
        "label": "supported",
        "rationale": "three distinct source mints share one exact coordinate",
        "source_coordinates": ["george.gate=target=work-1"],
        "event_ids": sorted(event.event_id for event in mints),
        "config": detector_config.to_dict(),
    }
    cases_path.write_text(json.dumps(evaluation_case) + "\n", encoding="utf-8")

    assert (
        main(
            [
                "findings",
                "evaluate",
                "--store",
                str(store_path),
                "--cases",
                str(cases_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    evaluation = json.loads(capsys.readouterr().out)
    remint_evaluation = next(row for row in evaluation["rules"] if row["rule"] == "re-minted")
    assert remint_evaluation["precision"] == 1.0
    assert remint_evaluation["decision"] == "surface"

    generate_args = [
        "findings",
        "generate",
        "--generator",
        "george-gates",
        "--store",
        str(store_path),
        "--findings",
        str(findings_path),
        "--since",
        "2026-07-01T00:00:00Z",
        "--until",
        "2026-07-13T00:00:00Z",
        "--source-state",
        "fresh",
        "--evaluation-cases",
        str(cases_path),
        "--format",
        "json",
    ]
    assert main([*generate_args, "--dry-run"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["emission"]["max_generator_grade"] == "lead"
    assert len(dry_run["emission"]["candidates"]) == 1
    assert not findings_path.exists()

    assert main([*generate_args, "--recorded-at", "2026-07-13T00:00:01Z"]) == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["emission"]["candidates"] == dry_run["emission"]["candidates"]
    assert appended["emission"]["inserted"] == 1
    finding_id = appended["emission"]["candidates"][0]["finding_id"]

    assert main([*generate_args, "--recorded-at", "2026-07-13T00:00:02Z"]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["emission"]["inserted"] == 0
    assert replay["emission"]["replayed"] == 1

    assert (
        main(
            [
                "findings",
                "list",
                "--store",
                str(store_path),
                "--findings",
                str(findings_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert [row["finding"]["finding_id"] for row in listed["findings"]] == [finding_id]

    assert (
        main(
            [
                "findings",
                "show",
                finding_id,
                "--store",
                str(store_path),
                "--findings",
                str(findings_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["finding"]["grade"] == "lead"


def test_gate_generation_auto_source_state_uses_typed_adapter_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    source = tmp_path / "2026-07.jsonl"
    rows = [
        {
            "id": f"gate-{index}",
            "host": "dash",
            "session": "groundskeeper",
            "kind": "observation",
            "content": "private",
            "project": "widgets",
            "tags": ["needs:human"],
            "edges": [{"type": "relates_to", "target": "work-1"}],
            "ts": f"2026-07-0{index + 1}T00:00:00Z",
        }
        for index in range(3)
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert (
        main(
            [
                "ingest",
                "george",
                "--source",
                f"george={source}",
                "--store",
                str(store_path),
                "--since",
                "2026-07-01T00:00:00Z",
                "--until",
                "2026-07-10T00:00:00Z",
                "--format",
                "json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "findings",
                "generate",
                "--generator",
                "george-gates",
                "--store",
                str(store_path),
                "--since",
                "2026-07-01T00:00:00Z",
                "--until",
                "2026-07-10T00:00:00Z",
                "--dry-run",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["projection"]["config"]["source_state"] == "fresh"
    assert output["projection"]["counts"]["detected"] == 1


def test_finding_cli_creates_relates_refutes_exports_and_rereads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "events.db"
    findings_path = tmp_path / "findings.jsonl"
    receipt = NormalizedEvent.create(
        source=SourceRef("george", "disposition-1"),
        occurred_at=datetime(2026, 7, 17, 12, 0, 1, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 17, 12, 0, 1, tzinfo=UTC),
        payload=OutcomePayload("george.finding-disposition", OutcomeStatus.SUCCEEDED, "gate-1"),
    )
    with MiltonStore(store_path) as store:
        store.append_event(receipt)

    assert (
        main(
            [
                "findings",
                "create",
                "george.gate=gate-1",
                "--findings",
                str(findings_path),
                "--kind",
                "drift",
                "--grade",
                "lead",
                "--summary",
                "Gate condition appears resolved",
                "--details",
                '{"gate_id":"gate-1"}',
                "--evidence",
                "evt_gate=gate snapshot",
                "--source-snapshot",
                "sha256:gate-snapshot",
                "--generator",
                "milton.gates/stale-v1",
                "--scope",
                '{"project":"george"}',
                "--coverage",
                "0.9",
                "--coverage-gap",
                "one archived queue unavailable",
                "--generated-at",
                "2026-07-17T12:00:00Z",
                "--recorded-at",
                "2026-07-17T12:00:00Z",
                "--format",
                "json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    finding_id = created["finding_id"]
    revision_id = created["revision_id"]

    assert (
        main(
            [
                "findings",
                "relate",
                finding_id,
                "--findings",
                str(findings_path),
                "--store",
                str(store_path),
                "--acts-on",
                "george.disposition=disposition-1",
                "--revision",
                revision_id,
                "--recorded-at",
                "2026-07-17T12:00:02Z",
                "--format",
                "json",
            ]
        )
        == 0
    )
    related = json.loads(capsys.readouterr().out)
    relation_id = related["relation_id"]
    assert related["evidence_event_ids"] == [receipt.event_id]

    assert (
        main(
            [
                "findings",
                "show",
                finding_id,
                "--findings",
                str(findings_path),
                "--store",
                str(store_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["disposition"] == "acted_on"
    assert shown["state"]["acted_on"] is True
    assert shown["receipts"][0]["receipt_event_id"] == receipt.event_id

    assert (
        main(
            [
                "findings",
                "list",
                "--findings",
                str(findings_path),
                "--store",
                str(store_path),
                "--acted-on",
                "--format",
                "json",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert len(listed["findings"]) == 1

    assert (
        main(
            [
                "findings",
                "refute",
                finding_id,
                "--findings",
                str(findings_path),
                "--summary",
                "The gate is still consulted by release automation",
                "--recorded-at",
                "2026-07-17T12:00:03Z",
                "--format",
                "json",
            ]
        )
        == 0
    )
    refuted = json.loads(capsys.readouterr().out)
    assert refuted["grade"] == "refuted"
    assert refuted["supersedes"] == revision_id

    export_args = [
        "findings",
        "export",
        finding_id,
        "--findings",
        str(findings_path),
        "--store",
        str(store_path),
    ]
    assert main(export_args) == 0
    first_export_text = capsys.readouterr().out
    assert main(export_args) == 0
    assert capsys.readouterr().out == first_export_text
    exported = json.loads(first_export_text)
    assert len(exported["finding_history"]) == 2
    assert len(exported["relation_history"]) == 1
    assert [
        FindingRevision.from_dict(item).grade.value for item in exported["finding_history"]
    ] == ["lead", "refuted"]
    assert len(FindingLedger(findings_path).history(finding_id)) == 2

    assert (
        main(
            [
                "findings",
                "unrelate",
                relation_id,
                "--store",
                str(store_path),
                "--note",
                "Receipt was attached to the wrong finding",
                "--recorded-at",
                "2026-07-17T12:00:04Z",
                "--format",
                "json",
            ]
        )
        == 0
    )
    unrelated = json.loads(capsys.readouterr().out)
    assert unrelated["state"] == "refuted"


def test_scan_ingests_and_reports_in_one_machine_readable_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = (
        Path(__file__).parent / "fixtures" / "codex" / "rollout-2026-07-17T10-00-00-session-1.jsonl"
    )
    store_path = tmp_path / "events.db"
    assert (
        main(
            [
                "scan",
                "codex",
                "--source",
                f"codex={fixture}",
                "--store",
                str(store_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["ingestion"]["adapters"][0]["adapter"] == "codex"
    assert output["report"]["event_count"] == 7
    assert output["report"]["source_coverage"]["codex"]["status"] == "ok"


def test_scan_until_is_an_exclusive_record_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = (
        Path(__file__).parent / "fixtures" / "codex" / "rollout-2026-07-17T10-00-00-session-1.jsonl"
    )
    store_path = tmp_path / "events.db"
    assert (
        main(
            [
                "scan",
                "codex",
                "--source",
                f"codex={fixture}",
                "--store",
                str(store_path),
                "--until",
                "2026-07-17T14:00:04Z",
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["report"]["period"]["end"] < "2026-07-17T14:00:04Z"
    assert output["ingestion"]["adapters"][0]["records_outside_window"] > 0
    assert output["report"]["source_coverage"]["codex"]["window"] == {
        "since": None,
        "until_exclusive": "2026-07-17T14:00:04Z",
    }
