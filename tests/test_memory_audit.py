from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from milton.adapters import DecisionMemoryAdapter, NativeMemoryAdapter
from milton.adapters.base import ContentPolicy
from milton.findings import FindingLedger, build_finding_activity
from milton.generators.memory import (
    MemoryAuditConfig,
    MemoryDisposition,
    MemoryStageStatus,
    append_memory_findings,
    build_memory_audit,
)
from milton.ingest import Ingestor
from milton.model import (
    MemoryEvidencePayload,
    MemoryStage,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def write_access(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def access(
    item: str,
    stage: str,
    *,
    state: str = "observed",
    superseded_by: str | None = None,
) -> dict[str, object]:
    return {
        "schema": "milton.memory-access/v1",
        "item": item,
        "stage": stage,
        "state": state,
        "evidence_reference": f"host-receipt:{item}:{stage}",
        "superseded_by": superseded_by,
        "occurred_at": "2026-07-16T12:00:00Z",
    }


def fixture_roots(tmp_path: Path) -> tuple[Path, Path]:
    native = tmp_path / "native"
    decision = tmp_path / "decision"
    skill = native / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    native.mkdir(exist_ok=True)
    (native / "AGENTS.md").write_text("old rule", encoding="utf-8")
    skill.write_text("useful skill", encoding="utf-8")
    old = (NOW - timedelta(days=90)).timestamp()
    os.utime(native / "AGENTS.md", (old, old))
    os.utime(skill, (old, old))
    native_rows = [
        access("AGENTS.md", stage, state="not_observed", superseded_by="skills/demo/SKILL.md")
        for stage in ("loaded", "retrieved", "referenced", "applied")
    ]
    native_rows.extend(
        access("skills/demo/SKILL.md", stage)
        for stage in ("loaded", "retrieved", "referenced", "applied")
    )
    write_access(native / ".milton-memory-access.jsonl", native_rows)

    decisions = decision / "decisions"
    decisions.mkdir(parents=True)
    adr = decisions / "0001-boundary.md"
    adr.write_text("accepted boundary", encoding="utf-8")
    os.utime(adr, (old, old))
    write_access(
        decision / ".milton-memory-access.jsonl",
        [
            access("decisions/0001-boundary.md", "retrieved"),
            access("decisions/0001-boundary.md", "referenced"),
        ],
    )
    return native, decision


def test_two_read_only_memory_adapters_preserve_stage_honesty(tmp_path: Path) -> None:
    native, decision = fixture_roots(tmp_path)
    before = {
        path: path.read_bytes()
        for path in (
            native / "AGENTS.md",
            native / "skills" / "demo" / "SKILL.md",
            decision / "decisions" / "0001-boundary.md",
        )
    }
    with MiltonStore(tmp_path / "events.db") as store:
        summary = Ingestor(store).run(
            [NativeMemoryAdapter(), DecisionMemoryAdapter()],
            roots={"native-memory": (native,), "decision-memory": (decision,)},
            content_policy=ContentPolicy.METADATA,
        )
        events = tuple(store.events())

    assert not summary.failed
    memory_events = tuple(
        event for event in events if isinstance(event.payload, MemoryEvidencePayload)
    )
    assert len(memory_events) == 13
    assert all(event.attributes.get("content_coverage") != "recovered" for event in memory_events)
    assert all(path.read_bytes() == content for path, content in before.items())

    projection = build_memory_audit(events, MemoryAuditConfig(NOW))
    assert projection.to_dict()["coverage"] == {
        "decision-memory": {
            "applied_known": 0,
            "inventory": 1,
            "loaded_known": 0,
            "referenced_known": 1,
            "retrieved_known": 1,
            "unknown_items": 1,
        },
        "factory-native": {
            "applied_known": 2,
            "inventory": 2,
            "loaded_known": 2,
            "referenced_known": 2,
            "retrieved_known": 2,
            "unknown_items": 0,
        },
    }
    dispositions = {item.locator: item.disposition for item in projection.items}
    assert dispositions == {
        "AGENTS.md": MemoryDisposition.RETIRE,
        "decisions/0001-boundary.md": MemoryDisposition.KEEP,
        "skills/demo/SKILL.md": MemoryDisposition.KEEP,
    }
    decision_item = next(item for item in projection.items if item.item_kind.value == "decision")
    assert decision_item.status(MemoryStage.RETRIEVED) is MemoryStageStatus.OBSERVED
    assert decision_item.status(MemoryStage.APPLIED) is MemoryStageStatus.UNKNOWN
    assert {candidate.grade.value for candidate in projection.candidates} == {
        "lead",
        "candidate",
    }


def test_reviewed_memory_recommendation_links_to_simulated_action_receipt(
    tmp_path: Path,
) -> None:
    native, decision = fixture_roots(tmp_path)
    store_path = tmp_path / "events.db"
    ledger = FindingLedger(tmp_path / "findings.jsonl")
    with MiltonStore(store_path) as store:
        Ingestor(store).run(
            [NativeMemoryAdapter(), DecisionMemoryAdapter()],
            roots={"native-memory": (native,), "decision-memory": (decision,)},
        )
        projection = build_memory_audit(tuple(store.events()), MemoryAuditConfig(NOW))
        assert append_memory_findings(ledger, projection, recorded_at=NOW) == (3, 0)
        assert append_memory_findings(
            ledger, projection, recorded_at=NOW + timedelta(seconds=1)
        ) == (0, 3)
        retire = next(
            revision
            for revision in ledger.current().values()
            if revision.details["disposition"] == "retire"
        )
        receipt = NormalizedEvent.create(
            source=SourceRef("memory-sim", "park-or-retire-reviewed"),
            occurred_at=NOW + timedelta(minutes=1),
            recorded_at=NOW + timedelta(minutes=1),
            payload=OutcomePayload(
                "memory.action", OutcomeStatus.SUCCEEDED, str(retire.details["item_id"])
            ),
        )
        store.append_event(receipt)
        store.append_relation(
            RelationRecord.create(
                subject=TypedRef("milton.finding-revision", retire.revision_id),
                predicate=RelationKind.ACTS_ON,
                object=TypedRef("milton.event", receipt.event_id),
                confidence=1,
                method=RelationMethod.HUMAN,
                evidence_event_ids=(receipt.event_id,),
                recorded_at=receipt.recorded_at,
                note="simulated review only; source memory was not changed",
            )
        )
        activity = build_finding_activity(store, ledger, retire.finding_id)

    assert activity.acted_on
    assert activity.ever_acted_on
    assert (native / "AGENTS.md").read_text(encoding="utf-8") == "old rule"
