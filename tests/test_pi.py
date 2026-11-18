from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from milton.adapters import ContentPolicy, FabAdapter, PiAdapter, SourceAdapter
from milton.ingest import Ingestor
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostPayload,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    parse_datetime,
)
from milton.store import MiltonStore

T = "2026-09-21T12:00:00Z"


def write_session(path: Path, sid: str, rows: list[dict[str, object]], **header: object) -> Path:
    first = {"type": "session", "id": sid, "version": 3, "cwd": "/work/project", **header}
    path.write_text("\n".join(json.dumps({"timestamp": T, **r}) for r in [first, *rows]))
    return path


def assistant(entry: str, reason: str, **usage: object) -> dict[str, object]:
    return {
        "type": "message",
        "id": entry,
        "message": {
            "role": "assistant",
            "provider": "example",
            "model": "requested",
            "responseModel": "actual",
            "responseId": "private-response",
            "content": "private-body",
            "errorMessage": "private-error",
            "stopReason": reason,
            "usage": usage,
        },
    }


def test_pi_usage_and_privacy(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = [
        assistant(
            "a",
            "toolUse",
            input=20,
            output=10,
            reasoning=4,
            cacheRead=5,
            cacheWrite=2,
            cost={"total": 0.123, "totalFromProvider": True},
        ),
        assistant("b", "aborted", cost={"total": 0}),
        assistant("c", "error", cost={"total": 0, "totalFromProvider": True}),
        assistant("d", "deferred", cost={"total": 17}),
        {"id": "e", "type": "usage", "kind": "cache_warm", "usage": {"cost": {"total": 0.05}}},
        {"id": "f", "type": "branch_summary", "summary": "private-summary", "usage": {"input": 2}},
        {"id": "g", "type": "compaction", "usage": {"output": 3}},
    ]
    path = write_session(tmp_path / "pi.jsonl", "sid", rows)
    adapter = PiAdapter()
    assert adapter.default_roots() == ()
    assert list(adapter.discover([tmp_path, path])) == [path]
    read = adapter.read(path, content_policy=ContentPolicy.FULL)
    events = [r for r in read.records if isinstance(r, NormalizedEvent)]
    assert "private-" not in repr(events)
    assert read.stats.malformed_records == 0
    calls = [r.payload for r in events if isinstance(r.payload, ModelCallPayload)]
    assert [c.status for c in calls] == [
        CallStatus.SUCCEEDED,
        CallStatus.CANCELLED,
        CallStatus.FAILED,
    ]
    assert all(c.model == "actual" for c in calls)
    costs = [r.payload for r in events if isinstance(r.payload, CostPayload)]
    assert [(c.amount_usd, c.basis) for c in costs] == [
        (Decimal("0.123"), CostBasis.REPORTED),
        (None, CostBasis.UNKNOWN),
        (Decimal(0), CostBasis.REPORTED),
        (Decimal("0.05"), CostBasis.COMPUTED),
        (None, CostBasis.UNKNOWN),
        (None, CostBasis.UNKNOWN),
    ]
    c = costs[0]
    assert (
        c.input_tokens,
        c.output_tokens,
        c.reasoning_tokens,
        c.cached_input_tokens,
        c.cache_write_tokens,
    ) == (20, 10, 4, 5, 2)
    assert c.accuracy == CostAccuracy.ACTUAL and costs[3].accuracy == CostAccuracy.ESTIMATED
    assert c.accounting_key == "pi.entry=sid:a"
    assert costs[5].model is None
    assert len(list(adapter.read(path, until=parse_datetime(T)).records)) == 1


def test_pi_fork_and_malformed(tmp_path: Path) -> None:
    adapter = PiAdapter()
    row = assistant("a", "stop", input=3)
    fork = adapter.read(
        write_session(tmp_path / "fork.jsonl", "child", [row], parentSession="/private-parent")
    )
    assert len(list(fork.records)) == 1
    assert [d.code for d in fork.stats.diagnostics] == ["pi-fork-history"]
    bad = adapter.read(write_session(tmp_path / "old.jsonl", "legacy", [row], version=2))
    assert not list(bad.records)
    assert [d.code for d in bad.stats.diagnostics] == ["unsupported-pi-session"]
    invalid = adapter.read(
        write_session(
            tmp_path / "bad.jsonl",
            "sid",
            [
                assistant("badcost", "stop", input=-1),
                assistant("", "stop"),
                row,
                {"type": "session", "id": "another", "version": 3},
                assistant("after", "stop"),
            ],
        )
    )
    events = [r for r in invalid.records if isinstance(r, NormalizedEvent)]
    assert [r.source.native_id for r in events] == [
        "sid",
        "model:sid:badcost",
        "model:sid:a",
        "usage:sid:a",
    ]
    assert invalid.stats.malformed_records == 2
    assert invalid.stats.diagnostics[-1].code == "unexpected-pi-header"


def test_pi_exact_fab_attribution_and_replay(tmp_path: Path) -> None:
    fab = tmp_path / "fab"
    receipts = fab / "jobs" / "j" / "receipts"
    receipts.mkdir(parents=True)
    job = {"namespace": "fab.job", "value": "j"}
    attempt = {"namespace": "fab.attempt", "value": "j:attempt:0"}
    for kind, relations in [
        ("attempt_started", [{"subject": attempt, "predicate": "attempt_of", "object": job}]),
        (
            "attempt_finished",
            [
                {"subject": attempt, "predicate": "attempt_of", "object": job},
                {
                    "subject": attempt,
                    "predicate": "produced",
                    "object": {"namespace": "pi.session", "value": "linked"},
                },
            ],
        ),
        ("job_outcome", []),
    ]:
        (receipts / f"{kind}.json").write_text(
            json.dumps(
                {
                    "schema": "fab.execution-receipt/v1",
                    "receipt_id": kind,
                    "kind": kind,
                    "occurred_at": T,
                    "job_id": "j",
                    "attempt_id": "j:attempt:0",
                    "attempt_idx": 0,
                    "backend": "pi",
                    "relations": relations,
                    "outcome": {"status": "succeeded"},
                }
            )
        )
    pi = tmp_path / "pi"
    pi.mkdir()
    for sid in ("linked", "unrelated"):
        write_session(pi / f"{sid}.jsonl", sid, [assistant("same", "stop", cost={"total": 0.25})])
    with MiltonStore(tmp_path / "events.db") as store:
        adapters: list[SourceAdapter] = [FabAdapter(), PiAdapter()]
        roots = {"fab": [fab], "pi": [pi]}
        result = Ingestor(store).run(adapters, roots=roots)
        assert not result.failed, result.to_text()
        assert (
            len(
                [
                    e
                    for e in store.events()
                    if isinstance(e.payload, SessionPayload) and e.source.adapter == "pi"
                ]
            )
            == 2
        )
        projection = store.outcome_attribution(outcome_types=["fab.job"])
        assert projection.selected_total_usd == Decimal("0.50")
        assert projection.attributed_total_usd == Decimal("0.25")
        repeat = Ingestor(store).run(adapters, roots=roots, force=True)
        assert not repeat.failed and all(s.events_inserted == 0 for s in repeat.adapters)
