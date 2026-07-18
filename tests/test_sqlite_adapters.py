import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from milton.activity import build_activity
from milton.adapters import ContentPolicy, FabAdapter, HermesAdapter, OpenCodeAdapter, SommAdapter
from milton.adapters.base import AdapterRecord
from milton.crosswalk import CrosswalkRecord, ExternalIdentity
from milton.ingest import Ingestor
from milton.model import (
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    CoverageStatus,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    ToolCallPayload,
    TurnPayload,
)
from milton.outcomes import AttributionState
from milton.relations import RelationKind, RelationRecord
from milton.store import MiltonStore


def normalized(records: Iterable[AdapterRecord]) -> list[NormalizedEvent]:
    return [record for record in records if isinstance(record, NormalizedEvent)]


def test_somm_adapter_reads_authoritative_calls_and_joins(tmp_path: Path) -> None:
    path = tmp_path / "global.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE calls (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, project TEXT NOT NULL,
            workload_id TEXT, prompt_id TEXT, provider TEXT NOT NULL, model TEXT NOT NULL,
            tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, latency_ms INTEGER,
            cost_usd REAL NOT NULL, outcome TEXT NOT NULL, error_kind TEXT,
            prompt_hash TEXT, response_hash TEXT, error_detail TEXT, correlation_id TEXT,
            ttft_ms INTEGER, session_id TEXT, parent_call_id TEXT,
            cache_tokens_in INTEGER, cache_tokens_out INTEGER
        );
        """
    )
    rows = [
        (
            "call-1",
            "2026-07-17T14:00:00+00:00",
            "fab",
            "workload",
            "prompt",
            "provider",
            "model",
            100,
            20,
            500,
            0.25,
            "ok",
            None,
            "prompt-hash",
            "response-hash",
            None,
            "fab-job-1",
            100,
            "session-1",
            None,
            50,
            0,
        ),
        (
            "call-2",
            "2026-07-17T14:01:00+00:00",
            "fab",
            "workload",
            "prompt",
            "provider",
            "model",
            50,
            10,
            250,
            0.10,
            "error",
            "rate_limit",
            "prompt-hash-2",
            "response-hash-2",
            "private detail",
            "fab-job-1",
            50,
            "session-1",
            "call-1",
            20,
            0,
        ),
    ]
    connection.executemany(
        "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    connection.commit()
    connection.close()

    read = SommAdapter().read(path)
    records = list(read.records)
    events = normalized(records)

    assert len([event for event in events if isinstance(event.payload, SessionPayload)]) == 1
    assert len([event for event in events if isinstance(event.payload, ModelCallPayload)]) == 2
    costs = [payload for event in events if isinstance((payload := event.payload), CostPayload)]
    assert [cost.amount_usd for cost in costs] == [Decimal("0.25"), Decimal("0.1")]
    assert all(cost.basis is CostBasis.COMPUTED for cost in costs)
    assert all(cost.accuracy is CostAccuracy.ESTIMATED for cost in costs)
    assert all(cost.accounting_key_scope is CostKeyScope.SOURCE for cost in costs)
    assert len([record for record in records if isinstance(record, CrosswalkRecord)]) == 6
    failed = [
        payload
        for event in events
        if isinstance((payload := event.payload), ModelCallPayload)
        and payload.status.value == "failed"
    ]
    assert len(failed) == 1


def test_somm_adapter_keeps_local_unpriced_amount_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "local.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE calls (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, project TEXT NOT NULL,
            provider TEXT NOT NULL, model TEXT NOT NULL,
            tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
            cost_usd REAL NOT NULL, outcome TEXT NOT NULL,
            cost_basis TEXT, cost_kind TEXT, cost_accuracy TEXT,
            cost_source TEXT, pricing_version TEXT
        );
        INSERT INTO calls VALUES (
            'local-1', '2026-07-17T14:00:00+00:00', 'factory',
            'ollama', 'qwen2.5:7b', 100, 20, 0.0, 'ok',
            'unknown', 'included', 'unknown', 'local-included-unpriced', NULL
        );
        """
    )
    connection.commit()
    connection.close()

    events = normalized(SommAdapter().read(path).records)
    costs = [payload for event in events if isinstance((payload := event.payload), CostPayload)]
    assert len(costs) == 1
    assert costs[0].amount_usd is None
    assert costs[0].basis is CostBasis.UNKNOWN
    assert costs[0].kind is CostKind.INCLUDED
    assert costs[0].accuracy is CostAccuracy.UNKNOWN
    assert costs[0].pricing_version == "local-included-unpriced"


def test_somm_v22_evidence_flows_without_duplicate_cost_filters(tmp_path: Path) -> None:
    path = tmp_path / "somm-v22.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE calls (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, project TEXT NOT NULL,
            workload_id TEXT, prompt_id TEXT, provider TEXT NOT NULL, model TEXT NOT NULL,
            tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, latency_ms INTEGER,
            cost_usd REAL NOT NULL, outcome TEXT NOT NULL, error_kind TEXT,
            prompt_hash TEXT NOT NULL, response_hash TEXT NOT NULL, error_detail TEXT,
            correlation_id TEXT, ttft_ms INTEGER, session_id TEXT, parent_call_id TEXT,
            cache_tokens_in INTEGER, cache_tokens_out INTEGER, cost_basis TEXT,
            cost_kind TEXT, cost_accuracy TEXT, cost_source TEXT, pricing_version TEXT,
            observation_role TEXT, source_call_id TEXT, eval_result_id INTEGER,
            provider_request_id TEXT, billing_id TEXT, origin TEXT,
            budget_eligible INTEGER
        );
        INSERT INTO calls VALUES
          ('prod', '2026-07-17T14:00:00+00:00', 'factory', 'wl-1', NULL,
           'provider', 'prod-m', 100, 20, 100, 0.10, 'ok', NULL, 'p1', 'r1',
           NULL, NULL, 20, 'session-1', NULL, 0, 0, 'computed', 'marginal',
           'estimated', 'somm:model_intel', 'test@2026-07-17', 'production',
           NULL, NULL, 'req-prod', 'bill-prod', 'native', 1),
          ('gold', '2026-07-17T14:01:00+00:00', 'factory', 'wl-1', NULL,
           'provider', 'gold-m', 15, 8, 10, 0.02, 'ok', NULL, 'p2', 'r2',
           NULL, NULL, 2, 'session-1', 'prod', 0, 0, 'computed', 'marginal',
           'estimated', 'somm:model_intel', 'test@2026-07-17', 'shadow_gold',
           'prod', 1, 'req-gold', NULL, 'native', 1),
          ('judge', '2026-07-17T14:02:00+00:00', 'factory', 'wl-1', NULL,
           'provider', 'judge-m', 12, 6, 10, 0.03, 'ok', NULL, 'p3', 'r3',
           NULL, NULL, 2, 'session-1', 'prod', 0, 0, 'reported', 'marginal',
           'actual', 'provider:response', NULL, 'shadow_judge', 'prod', 1,
           'req-judge', 'bill-judge', 'native', 1);

        CREATE TABLE eval_results (
            id INTEGER PRIMARY KEY, call_id TEXT NOT NULL, gold_model TEXT NOT NULL,
            gold_response_hash TEXT, structural_score REAL, embedding_score REAL,
            judge_score REAL, judge_reason TEXT, grading_started_at TEXT, ts TEXT NOT NULL
        );
        INSERT INTO eval_results VALUES
          (1, 'prod', 'gold-m', 'gold-hash', 0.8, 0.7, 1.0, '{}', NULL,
           '2026-07-17 14:03:00');

        CREATE TABLE eval_receipts (
            id TEXT PRIMARY KEY, eval_result_id INTEGER, run_id TEXT, receipt_type TEXT,
            call_id TEXT, dataset_id TEXT, dataset_item_id TEXT, source_call_id TEXT,
            candidate_a_call_id TEXT, candidate_b_call_id TEXT, winner TEXT,
            score REAL, threshold REAL, payload_json TEXT, created_at TEXT
        );
        INSERT INTO eval_receipts VALUES
          ('receipt-1', 1, 'run-1', 'shadow_eval', 'prod', NULL, NULL, 'prod',
           NULL, NULL, NULL, 1.0, 0.8, '{"evidence":"kept private"}',
           '2026-07-17 14:03:01');

        CREATE TABLE campaigns (
            id TEXT PRIMARY KEY, project TEXT, workload_id TEXT, dataset_id TEXT,
            name TEXT, metric TEXT, direction TEXT, threshold REAL, token_budget INTEGER,
            max_rounds INTEGER, plateau_window INTEGER, min_delta REAL, status TEXT,
            best_score REAL, total_tokens INTEGER, total_cost_usd REAL,
            metadata_json TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT
        );
        INSERT INTO campaigns VALUES
          ('campaign-1', 'factory', 'wl-1', NULL, 'campaign', 'score', 'gte', 0.8,
           1000, 3, 2, 0.01, 'completed', 1.0, 161, 0.15, '{}',
           '2026-07-17 14:00:00', '2026-07-17 14:04:00', '2026-07-17 14:04:00');

        CREATE TABLE campaign_events (
            id TEXT PRIMARY KEY, campaign_id TEXT, sequence INTEGER, run_id TEXT,
            event_type TEXT, action TEXT, metric_score REAL, threshold REAL,
            tokens_in INTEGER, tokens_out INTEGER, total_tokens INTEGER, cost_usd REAL,
            payload_json TEXT, created_at TEXT
        );
        INSERT INTO campaign_events VALUES
          ('campaign-event-1', 'campaign-1', 1, 'run-1', 'round_completed', 'keep',
           1.0, 0.8, 127, 34, 161, 0.15, '{}', '2026-07-17 14:03:02');

        CREATE TABLE decisions (
            id TEXT PRIMARY KEY, ts TEXT, project TEXT, workload_id TEXT,
            workload_name TEXT, question TEXT, question_hash TEXT, constraints_json TEXT,
            candidates_json TEXT, chosen_provider TEXT, chosen_model TEXT,
            rationale TEXT, agent TEXT, superseded_by TEXT, outcome_note TEXT
        );
        INSERT INTO decisions VALUES
          ('decision-1', '2026-07-17T14:05:00+00:00', 'factory', 'wl-1', 'work',
           'private question', 'question-hash', '{}', '[]', 'provider', 'prod-m',
           'private rationale', 'human', NULL, 'worked');

        CREATE TABLE recommendations (
            id INTEGER PRIMARY KEY, workload_id TEXT, action TEXT, evidence_json TEXT,
            expected_impact TEXT, confidence REAL, created_at TEXT,
            dismissed_at TEXT, applied_at TEXT
        );
        INSERT INTO recommendations VALUES
          (1, 'wl-1', 'switch_model', '{}', 'less cost', 0.9,
           '2026-07-17 14:05:00', NULL, '2026-07-17 14:06:00');

        CREATE TABLE call_updates (
            id INTEGER PRIMARY KEY, call_id TEXT, field TEXT, value TEXT, ts TEXT
        );
        INSERT INTO call_updates VALUES
          (1, 'prod', 'outcome', 'off_task', '2026-07-17 14:07:00');
        """
    )
    connection.commit()
    connection.close()

    read = SommAdapter().read(path)
    records = list(read.records)
    events = normalized(records)
    calls = [event for event in events if isinstance(event.payload, ModelCallPayload)]
    costs = [event.payload for event in events if isinstance(event.payload, CostPayload)]

    assert len(calls) == 3
    assert {event.attributes["observation_role"] for event in calls} == {
        "production",
        "shadow_gold",
        "shadow_judge",
    }
    assert len(costs) == 4
    assert [payload.observation_role for payload in costs].count(CostObservationRole.ROLLUP) == 1
    billable_events = [
        event
        for event in events
        if isinstance(event.payload, CostPayload)
        and event.payload.observation_role is not CostObservationRole.ROLLUP
    ]
    assert len(billable_events) == 3
    assert all(
        isinstance(event.payload, CostPayload)
        and event.payload.accounting_key_scope is CostKeyScope.SHARED
        for event in billable_events
    )
    assert {event.attributes["provider_request_id"] for event in billable_events} == {
        "req-prod",
        "req-gold",
        "req-judge",
    }
    assert not [
        diagnostic
        for diagnostic in read.stats.diagnostics
        if diagnostic.code == "optional-tables-missing"
    ]

    store_path = tmp_path / "milton.sqlite"
    with MiltonStore(store_path) as store:
        summary = Ingestor(store).run((SommAdapter(),), roots={"somm": (path,)})
        assert summary.adapters[0].sources_failed == 0
        snapshot = build_activity(store, ExternalIdentity("somm.call", "prod"))

    assert snapshot.report.accounting.cost_events == 4
    assert snapshot.report.accounting.rollup_events == 1
    assert snapshot.report.accounting.selected_observations == 3
    assert snapshot.report.total_cost_usd == Decimal("0.15")
    assert snapshot.report.adapters["somm"].cost_usd == Decimal("0.15")
    namespaces = {identity.namespace for identity in snapshot.related_identities}
    assert {
        "somm.eval-result",
        "somm.eval-receipt",
        "somm.campaign",
        "somm.campaign-event",
        "somm.decision",
        "somm.recommendation",
        "somm.call-update",
    }.issubset(namespaces)
    outcome_types = {outcome.outcome_type for outcome in snapshot.outcomes}
    assert "somm.eval-result" in outcome_types
    assert "somm.call-update.outcome" in outcome_types


def test_fab_job_to_direct_somm_call_trace_closes_on_correlation(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "event": "submitted",
                    "job_id": "fab-job-1",
                    "ts": "2026-07-17T14:00:00Z",
                    "backend": "somm",
                    "intent": "llm",
                    "tags": {},
                    "launch": {},
                },
                {
                    "event": "status_changed",
                    "job_id": "fab-job-1",
                    "to": "succeeded",
                    "ts": "2026-07-17T14:00:02Z",
                },
            )
        )
        + "\n"
    )
    database = tmp_path / "somm.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE calls (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, project TEXT NOT NULL,
            provider TEXT NOT NULL, model TEXT NOT NULL,
            tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL,
            cost_usd REAL NOT NULL, outcome TEXT NOT NULL, correlation_id TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "call-1",
            "2026-07-17T14:00:01+00:00",
            "fab",
            "ollama",
            "model",
            10,
            2,
            0.0,
            "ok",
            "fab-job-1",
        ),
    )
    connection.commit()
    connection.close()

    records = [*FabAdapter().read(ledger).records, *SommAdapter().read(database).records]
    relations = [record for record in records if isinstance(record, RelationRecord)]
    assert len(relations) == 1
    assert relations[0].predicate is RelationKind.PRODUCED
    with MiltonStore(tmp_path / "milton.sqlite") as store:
        summary = Ingestor(store).run(
            (FabAdapter(), SommAdapter()),
            roots={"fab": (ledger,), "somm": (database,)},
        )
        snapshot = build_activity(store, ExternalIdentity("fab.job", "fab-job-1"))
        outcome_projection = store.outcome_attribution()

    assert {identity.namespace for identity in snapshot.related_identities} == {
        "correlation",
        "fab.job",
        "somm.call",
    }
    assert snapshot.report.adapters["somm"].cost_usd == Decimal("0.0")
    assert snapshot.relations == tuple(relations)
    assert summary.adapters[1].relations_inserted == 1
    assert outcome_projection.records[0].state is AttributionState.ATTRIBUTED


def test_hermes_adapter_uses_session_cost_and_pairs_tools(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT,
            parent_session_id TEXT, started_at REAL NOT NULL, ended_at REAL,
            end_reason TEXT, input_tokens INTEGER, output_tokens INTEGER,
            cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
            billing_provider TEXT, billing_mode TEXT, estimated_cost_usd REAL,
            actual_cost_usd REAL, cost_status TEXT, cost_source TEXT,
            pricing_version TEXT, title TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,
            timestamp REAL NOT NULL, token_count INTEGER, finish_reason TEXT
        );
        """
    )
    start = datetime(2026, 7, 17, 14, tzinfo=UTC).timestamp()
    connection.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "session-1",
            "cli",
            "hermes-model",
            None,
            start,
            start + 10,
            "complete",
            100,
            20,
            30,
            5,
            4,
            "provider",
            "estimated",
            0.12,
            None,
            "estimated",
            "pricing-table",
            "v1",
            "private title",
        ),
    )
    tool_calls = json.dumps(
        [
            {
                "id": "tool-1",
                "type": "function",
                "function": {"name": "shell", "arguments": '{"cmd":"private"}'},
            }
        ]
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "session-1", "user", "private request", None, None, None, start + 1, 5, None),
            (
                2,
                "session-1",
                "assistant",
                "private response",
                None,
                tool_calls,
                None,
                start + 2,
                20,
                "tool_calls",
            ),
            (3, "session-1", "tool", "private output", "tool-1", None, "shell", start + 3, 3, None),
        ],
    )
    connection.commit()
    connection.close()

    read = HermesAdapter().read(path)
    events = normalized(read.records)
    costs = [event for event in events if isinstance(event.payload, CostPayload)]
    tools = [payload for event in events if isinstance((payload := event.payload), ToolCallPayload)]
    turns = [payload for event in events if isinstance((payload := event.payload), TurnPayload)]

    assert len(costs) == 1
    assert isinstance(costs[0].payload, CostPayload)
    assert costs[0].payload.amount_usd == Decimal("0.12")
    assert costs[0].payload.basis is CostBasis.COMPUTED
    assert costs[0].payload.accuracy is CostAccuracy.ESTIMATED
    assert costs[0].coverage["amount_usd"] is CoverageStatus.INFERRED
    assert len(tools) == 1
    assert tools[0].input is None
    assert tools[0].output is None
    assert all(turn.content is None for turn in turns)


def test_opencode_adapter_reads_message_usage_and_typed_parts(tmp_path: Path) -> None:
    path = tmp_path / "opencode.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, worktree TEXT);
        CREATE TABLE session (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT,
            directory TEXT NOT NULL, version TEXT, time_created INTEGER NOT NULL,
            time_archived INTEGER, agent TEXT, title TEXT
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL, data TEXT NOT NULL
        );
        """
    )
    timestamp = 1_768_651_200_000
    connection.execute("INSERT INTO project VALUES ('project-1','widgets','/work/widgets')")
    connection.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "session-1",
            "project-1",
            None,
            "/work/widgets",
            "1.0",
            timestamp,
            None,
            "build",
            "private title",
        ),
    )
    message_data = json.dumps(
        {
            "role": "assistant",
            "providerID": "provider",
            "modelID": "model",
            "finish": "stop",
            "cost": 0.5,
            "tokens": {
                "input": 100,
                "output": 20,
                "reasoning": 5,
                "cache": {"read": 30, "write": 4},
            },
        }
    )
    connection.execute(
        "INSERT INTO message VALUES (?,?,?,?)",
        ("message-1", "session-1", timestamp + 1000, message_data),
    )
    connection.executemany(
        "INSERT INTO part VALUES (?,?,?,?,?)",
        [
            (
                "part-text",
                "message-1",
                "session-1",
                timestamp + 2000,
                json.dumps({"type": "text", "text": "private response"}),
            ),
            (
                "part-tool",
                "message-1",
                "session-1",
                timestamp + 3000,
                json.dumps(
                    {
                        "type": "tool",
                        "callID": "tool-1",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "private"},
                            "output": "private output",
                        },
                    }
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()

    events = normalized(OpenCodeAdapter().read(path).records)
    costs = [payload for event in events if isinstance((payload := event.payload), CostPayload)]
    assert costs[0].basis is CostBasis.REPORTED
    assert costs[0].accounting_key_scope is CostKeyScope.SOURCE
    tools = [payload for event in events if isinstance((payload := event.payload), ToolCallPayload)]
    turns = [payload for event in events if isinstance((payload := event.payload), TurnPayload)]
    assert costs[0].amount_usd == Decimal("0.5")
    assert costs[0].reasoning_tokens == 5
    assert len(tools) == 1 and tools[0].input is None and tools[0].output is None
    assert len(turns) == 1 and turns[0].content is None

    full_events = normalized(
        OpenCodeAdapter().read(path, content_policy=ContentPolicy.FULL).records
    )
    full_tool = next(
        payload for event in full_events if isinstance((payload := event.payload), ToolCallPayload)
    )
    assert full_tool.input == {"command": "private"}
