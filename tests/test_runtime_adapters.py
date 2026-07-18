import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path

from milton.adapters import ContentPolicy, FabAdapter, GeorgeAdapter, GitAdapter
from milton.adapters.base import AdapterRecord
from milton.crosswalk import CrosswalkRecord
from milton.ingest import Ingestor
from milton.model import (
    CoverageStatus,
    GateConsultation,
    GateEvidenceKind,
    GateEvidencePayload,
    GateStatus,
    NormalizedEvent,
    OutcomePayload,
    SessionPayload,
)
from milton.relations import RelationKind, RelationRecord
from milton.store import MiltonStore


def normalized(records: Iterable[AdapterRecord]) -> list[NormalizedEvent]:
    return [record for record in records if isinstance(record, NormalizedEvent)]


def gate_payload(event: NormalizedEvent) -> GateEvidencePayload:
    assert isinstance(event.payload, GateEvidencePayload)
    return event.payload


def test_fab_adapter_reads_lifecycle_outcomes_and_work_item_join(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [
        {
            "event": "submitted",
            "job_id": "fab-job-1",
            "ts": "2026-07-17T14:00:00Z",
            "backend": "codex",
            "intent": "harness",
            "submitter": "fab-bridge-george",
            "tags": {
                "work_item_id": "george-entry-1",
                "work_project": "widgets",
                "repair_of": "fab-parent-1",
            },
            "launch": {"model": "private-model"},
        },
        {
            "event": "attempt_finished",
            "job_id": "fab-job-1",
            "attempt_idx": 0,
            "outcome": "succeeded",
            "exit_code": 0,
            "detail": "private detail",
            "ts": "2026-07-17T14:01:00Z",
        },
        {
            "event": "status_changed",
            "job_id": "fab-job-1",
            "to": "succeeded",
            "ts": "2026-07-17T14:01:01Z",
        },
    ]
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\nbroken\n")

    read = FabAdapter().read(ledger)
    records = list(read.records)
    events = normalized(records)
    session = next(event for event in events if isinstance(event.payload, SessionPayload))
    outcomes = [event for event in events if isinstance(event.payload, OutcomePayload)]

    assert isinstance(session.payload, SessionPayload)
    assert session.payload.project == "widgets"
    assert session.payload.harness == "codex"
    assert session.attributes["tags"] is None
    assert len(outcomes) == 2
    assert all(
        isinstance(event.payload, OutcomePayload) and event.payload.status.value == "succeeded"
        for event in outcomes
    )
    joins = [record for record in records if isinstance(record, CrosswalkRecord)]
    assert len(joins) == 2
    assert {identity.namespace for join in joins for identity in (join.left, join.right)} >= {
        "fab.job",
        "correlation",
    }
    assert any(join.left.namespace == join.right.namespace == "fab.job" for join in joins)
    assert read.stats.malformed_records == 1

    full_session = next(
        event
        for event in normalized(
            FabAdapter().read(ledger, content_policy=ContentPolicy.FULL).records
        )
        if isinstance(event.payload, SessionPayload)
    )
    assert full_session.attributes["launch"] == {"model": "private-model"}


def test_fab_adapter_joins_job_to_native_harness_session(tmp_path: Path) -> None:
    state = tmp_path / "fab"
    job = state / "jobs" / "fab-job-1"
    attempt = job / "attempts" / "0"
    attempt.mkdir(parents=True)
    (state / "ledger.jsonl").touch()
    (job / "spec.json").write_text(
        json.dumps(
            {
                "id": "fab-job-1",
                "backend": "codex",
                "created_at": "2026-07-17T14:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    stdout = attempt / "stdout"
    stdout.write_text(
        '{"type":"thread.started","thread_id":"codex-thread-1"}\n',
        encoding="utf-8",
    )

    adapter = FabAdapter()
    assert list(adapter.discover([state])) == [state / "ledger.jsonl", stdout]
    joins = [
        record for record in adapter.read(stdout).records if isinstance(record, CrosswalkRecord)
    ]
    assert len(joins) == 1
    assert {joins[0].left.namespace, joins[0].right.namespace} == {
        "fab.job",
        "codex.session",
    }


def test_george_adapter_reads_work_ledger_and_explicit_joins(tmp_path: Path) -> None:
    inbox = tmp_path / "2026-07.jsonl"
    row = {
        "id": "george-entry-1",
        "host": "lisbon",
        "session": "fab-bridge",
        "kind": "done",
        "content": "private result",
        "project": "widgets",
        "context": {
            "fab_job_id": "fab-job-1",
            "git_sha": "abc123",
            "secret": "private context",
        },
        "refs": ["george-todo-1"],
        "tags": ["fab-bridge"],
        "ts": "2026-07-17T14:02:00Z",
    }
    inbox.write_text(json.dumps(row) + "\n", encoding="utf-8")

    records = list(GeorgeAdapter().read(inbox).records)
    event = normalized(records)[0]
    assert isinstance(event.payload, OutcomePayload)
    assert event.payload.outcome_type == "george.done"
    assert event.payload.status.value == "succeeded"
    assert event.payload.reference == "george-todo-1"
    assert event.attributes["context"] is None
    assert "content" not in event.attributes
    joins = [record for record in records if isinstance(record, CrosswalkRecord)]
    assert {identity.namespace for join in joins for identity in (join.left, join.right)} == {
        "fab.job",
        "george.entry",
        "git.commit",
    }
    relations = [record for record in records if isinstance(record, RelationRecord)]
    assert [relation.predicate for relation in relations] == [
        RelationKind.VERIFIES,
        RelationKind.PRODUCED,
    ]
    assert [relation.subject.namespace for relation in relations] == [
        "george.entry",
        "fab.job",
    ]
    assert [relation.object.namespace for relation in relations] == [
        "fab.job",
        "git.commit",
    ]

    full_event = normalized(GeorgeAdapter().read(inbox, content_policy=ContentPolicy.FULL).records)[
        0
    ]
    assert full_event.attributes["content"] == "private result"
    assert full_event.attributes["context"] == row["context"]


def test_george_gate_evidence_keeps_coordinate_mints_and_unknown_reads_distinct(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "2026-07.jsonl"
    rows = [
        {
            "id": "gate-mint-1",
            "host": "dash",
            "session": "groundskeeper",
            "kind": "observation",
            "content": "first private gate",
            "project": "widgets",
            "tags": ["needs:human"],
            "edges": [{"type": "relates_to", "target": "work-1"}],
            "ts": "2026-07-10T10:00:00Z",
        },
        {
            "id": "gate-mint-2",
            "host": "dash",
            "session": "groundskeeper",
            "kind": "observation",
            "content": "second private gate",
            "project": "widgets",
            "tags": ["needs:human"],
            "edges": [{"type": "relates_to", "target": "work-1"}],
            "ts": "2026-07-11T10:00:00Z",
        },
        {
            "id": "gate-consult-1",
            "host": "dash",
            "session": "review",
            "kind": "observation",
            "content": "consulted private gate",
            "project": "widgets",
            "refs": ["work-1"],
            "context": {"gate_consultation": {"consulted": True, "mint_id": "gate-mint-1"}},
            "ts": "2026-07-12T10:00:00Z",
        },
        {
            "id": "gate-decision-1",
            "host": "dash",
            "session": "human",
            "kind": "decision",
            "content": "resolved private gate",
            "project": "widgets",
            "refs": ["work-1"],
            "tags": ["resolved-by-human"],
            "ts": "2026-07-13T10:00:00Z",
        },
        {
            "id": "gate-mint-unkeyed",
            "host": "dash",
            "session": "groundskeeper",
            "kind": "observation",
            "content": "private gate without a coordinate",
            "project": "widgets",
            "tags": ["needs:human"],
            "ts": "2026-07-14T10:00:00Z",
        },
    ]
    inbox.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    with MiltonStore(tmp_path / "events.db") as store:
        summary = Ingestor(store).run((GeorgeAdapter(),), roots={"george": (inbox,)}).adapters[0]
        gate_events = [
            event for event in store.events() if isinstance(event.payload, GateEvidencePayload)
        ]
        relations = store.current_relations()
        crosswalks = store.current_crosswalks()

    assert summary.events_inserted == 10
    assert summary.relations_inserted == 4
    assert len(gate_events) == 5
    mints = [
        event for event in gate_events if gate_payload(event).evidence_kind is GateEvidenceKind.MINT
    ]
    keyed = [event for event in mints if gate_payload(event).coordinate == "target=work-1"]
    assert {gate_payload(event).mint_id for event in keyed} == {
        "gate-mint-1",
        "gate-mint-2",
    }
    assert len({gate_payload(event).coordinate for event in keyed}) == 1

    unkeyed = next(event for event in mints if gate_payload(event).mint_id == "gate-mint-unkeyed")
    assert gate_payload(unkeyed).coordinate is None
    assert gate_payload(unkeyed).consultation is None
    assert unkeyed.coverage["coordinate"] is CoverageStatus.UNAVAILABLE
    assert unkeyed.coverage["consultation"] is CoverageStatus.UNAVAILABLE

    consulted = next(
        event
        for event in gate_events
        if gate_payload(event).evidence_kind is GateEvidenceKind.CONSULT
    )
    assert gate_payload(consulted).consultation is GateConsultation.CONSULTED
    assert consulted.coverage["consultation"] is CoverageStatus.RECOVERED
    decision = next(
        event
        for event in gate_events
        if gate_payload(event).evidence_kind is GateEvidenceKind.DECISION
    )
    assert gate_payload(decision).status is GateStatus.RESOLVED

    assert {relation.predicate for relation in relations} == {
        RelationKind.PART_OF,
        RelationKind.EVALUATES,
    }
    assert all(relation.object.namespace == "george.gate" for relation in relations)
    assert (
        len(
            [
                link
                for link in crosswalks
                if {link.left.namespace, link.right.namespace}
                & {"george.gate-mint", "george.gate-event"}
            ]
        )
        == 5
    )


def test_git_adapter_reads_all_refs_with_private_content_default(tmp_path: Path) -> None:
    repo = tmp_path / "widgets"
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_text("gitdir: /missing/worktree\n", encoding="utf-8")
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Private Author")
    _git(repo, "config", "user.email", "private@example.test")
    tracked = repo / "artifact.txt"
    tracked.write_text("first\n", encoding="utf-8")
    _git(repo, "add", "artifact.txt")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-07-17T14:03:00+00:00",
        "GIT_COMMITTER_DATE": "2026-07-17T14:03:00+00:00",
    }
    _git(repo, "commit", "-q", "-m", "private commit", env=env)

    adapter = GitAdapter()
    assert list(adapter.discover([tmp_path])) == [repo]
    before = adapter.fingerprint(repo)
    records = list(adapter.read(repo).records)
    event = normalized(records)[0]
    assert isinstance(event.payload, OutcomePayload)
    assert event.payload.outcome_type == "git.commit"
    assert "message" not in event.attributes
    assert "author_email" not in event.attributes
    assert len([record for record in records if isinstance(record, CrosswalkRecord)]) == 1

    full_event = normalized(adapter.read(repo, content_policy=ContentPolicy.FULL).records)[0]
    assert full_event.attributes["message"] == "private commit"
    assert full_event.attributes["author_email"] == "private@example.test"

    tracked.write_text("second\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "second commit", env=env)
    assert adapter.fingerprint(repo) != before


def _git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
