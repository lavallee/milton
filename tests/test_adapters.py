import json
from pathlib import Path

from milton.adapters import ClaudeCodeAdapter, CodexAdapter, ContentPolicy
from milton.crosswalk import CrosswalkRecord
from milton.model import (
    CostPayload,
    CoverageStatus,
    EventKind,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    ToolCallPayload,
    TurnPayload,
)
from milton.store import MiltonStore

FIXTURES = Path(__file__).parent / "fixtures"


def test_codex_adapter_normalizes_real_rollout_shapes_without_content() -> None:
    source = FIXTURES / "codex" / "rollout-2026-07-17T10-00-00-session-1.jsonl"
    read = CodexAdapter().read(source)
    events = [record for record in read.records if isinstance(record, NormalizedEvent)]

    assert [event.kind for event in events].count(EventKind.SESSION) == 1
    assert [event.kind for event in events].count(EventKind.TURN) == 2
    assert [event.kind for event in events].count(EventKind.MODEL_CALL) == 1
    assert [event.kind for event in events].count(EventKind.TOOL_CALL) == 1
    assert [event.kind for event in events].count(EventKind.COST) == 1
    assert [event.kind for event in events].count(EventKind.OUTCOME) == 1
    assert read.stats.malformed_records == 1
    assert read.stats.skipped_records == 1

    turn_events = [event for event in events if isinstance(event.payload, TurnPayload)]
    turns = [
        payload for event in turn_events if isinstance((payload := event.payload), TurnPayload)
    ]
    assert all(payload.content is None for payload in turns)
    assert all(event.coverage["content"] is CoverageStatus.REDACTED for event in turn_events)
    assert all(payload.content_sha256 for payload in turns)

    tool = next(event for event in events if isinstance(event.payload, ToolCallPayload))
    assert isinstance(tool.payload, ToolCallPayload)
    assert tool.payload.input is None
    assert tool.payload.output is None
    assert tool.coverage["input"] is CoverageStatus.REDACTED
    assert tool.attributes is not None
    assert tool.attributes["input_metadata"] != tool.attributes["output_metadata"]

    cost = next(payload for event in events if isinstance((payload := event.payload), CostPayload))
    assert cost.input_tokens == 100
    assert cost.reasoning_tokens == 5
    assert cost.amount_usd is None


def test_codex_full_content_is_explicit_opt_in() -> None:
    source = FIXTURES / "codex" / "rollout-2026-07-17T10-00-00-session-1.jsonl"
    events = [
        record
        for record in CodexAdapter().read(source, content_policy=ContentPolicy.FULL).records
        if isinstance(record, NormalizedEvent)
    ]

    turns = [payload for event in events if isinstance((payload := event.payload), TurnPayload)]
    assert [turn.content for turn in turns] == ["private user request", "private assistant reply"]
    tool = next(
        payload for event in events if isinstance((payload := event.payload), ToolCallPayload)
    )
    assert tool.input == '{"cmd":"private command"}'
    assert tool.output == "private output"


def test_codex_fork_keeps_child_identity_and_links_embedded_parent(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    day = sessions_root / "2026" / "07" / "17"
    day.mkdir(parents=True)
    parent_source = day / "rollout-2026-07-17T09-00-00-parent.jsonl"
    parent_rows = [
        {
            "timestamp": "2026-07-17T09:00:00Z",
            "type": "session_meta",
            "payload": {"id": "parent", "cwd": "/work/widgets"},
        },
        {
            "timestamp": "2026-07-17T09:15:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "parent-turn"},
        },
    ]
    parent_source.write_text("\n".join(json.dumps(row) for row in parent_rows) + "\n")

    source = day / "rollout-2026-07-17T10-00-00-child.jsonl"
    rows = [
        {
            "timestamp": "2026-07-17T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "child",
                "session_id": "parent",
                "parent_thread_id": "parent",
                "cwd": "/work/widgets",
            },
        },
        {
            "timestamp": "2026-07-17T09:00:00Z",
            "type": "session_meta",
            "payload": {"id": "parent", "cwd": "/work/widgets"},
        },
        {
            "timestamp": "2026-07-17T09:30:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "parent-message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "parent history"}],
            },
        },
        {
            "timestamp": "2026-07-17T10:00:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "parent-turn"},
        },
        {
            "timestamp": "2026-07-17T10:00:01Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "child-turn"},
        },
        {
            "timestamp": "2026-07-17T10:01:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "child-message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "child work"}],
            },
        },
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    records = list(CodexAdapter().read(source).records)
    events = [record for record in records if isinstance(record, NormalizedEvent)]
    joins = [record for record in records if isinstance(record, CrosswalkRecord)]

    assert [event.source.native_id for event in events] == [
        "child",
        "message:child-message",
        "model:child-message",
    ]
    assert len(joins) == 1
    assert {joins[0].left.value, joins[0].right.value} == {"child", "parent"}

    compacted_source = day / "rollout-2026-07-17T10-00-01-child.jsonl"
    compacted_rows = [rows[0], *rows[2:]]
    compacted_source.write_text("\n".join(json.dumps(row) for row in compacted_rows) + "\n")
    compacted_events = [
        record
        for record in CodexAdapter().read(compacted_source).records
        if isinstance(record, NormalizedEvent)
    ]
    assert [event.source.native_id for event in compacted_events] == [
        "child",
        "message:child-message",
        "model:child-message",
    ]


def test_claude_adapter_deduplicates_streamed_message_usage() -> None:
    source = FIXTURES / "claude_code" / "session-1.jsonl"
    read = ClaudeCodeAdapter().read(source)
    events = [record for record in read.records if isinstance(record, NormalizedEvent)]

    model_calls = [
        payload for event in events if isinstance((payload := event.payload), ModelCallPayload)
    ]
    costs = [payload for event in events if isinstance((payload := event.payload), CostPayload)]
    tools = [payload for event in events if isinstance((payload := event.payload), ToolCallPayload)]
    turns = [payload for event in events if isinstance((payload := event.payload), TurnPayload)]

    assert len(model_calls) == 1
    assert len(costs) == 1
    assert len(tools) == 1
    assert len(turns) == 2
    assert costs[0].cached_input_tokens == 30
    assert costs[0].cache_write_tokens == 40
    assert read.stats.malformed_records == 1
    assert all(turn.content is None for turn in turns)
    assert tools[0].input is None
    assert tools[0].output is None


def test_adapter_discovery_accepts_a_file_or_tree() -> None:
    codex = CodexAdapter()
    source = FIXTURES / "codex" / "rollout-2026-07-17T10-00-00-session-1.jsonl"
    assert list(codex.discover([source])) == [source]
    assert list(codex.discover([FIXTURES / "codex"])) == [source]


def test_claude_discovery_excludes_workflow_journals(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    journal = tmp_path / "journal.jsonl"
    transcript.touch()
    journal.touch()

    assert list(ClaudeCodeAdapter().discover([tmp_path])) == [transcript]


def test_claude_subagents_have_distinct_session_identities(tmp_path: Path) -> None:
    sources: list[Path] = []
    for agent_id in ("agent-a", "agent-b"):
        source = tmp_path / f"{agent_id}.jsonl"
        source.write_text(
            '{"type":"user","uuid":"'
            + agent_id
            + '","sessionId":"parent-session","agentId":"'
            + agent_id
            + '","timestamp":"2026-07-17T14:00:00Z",'
            '"isSidechain":true,"message":{"role":"user","content":"hello"}}\n',
            encoding="utf-8",
        )
        sources.append(source)

    sessions: list[NormalizedEvent] = []
    for source in sources:
        sessions.extend(
            event
            for event in ClaudeCodeAdapter().read(source).records
            if isinstance(event, NormalizedEvent) and isinstance(event.payload, SessionPayload)
        )

    assert len({event.event_id for event in sessions}) == 2
    assert {event.source.native_id for event in sessions} == {
        "parent-session:agent:agent-a",
        "parent-session:agent:agent-b",
    }
    assert all(event.attributes["parent_session_id"] == "parent-session" for event in sessions)


def test_codex_active_tool_is_deferred_until_output_is_immutable(tmp_path: Path) -> None:
    source = tmp_path / "rollout-active.jsonl"
    session = {
        "timestamp": "2026-07-17T14:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": "active-session",
            "cwd": "/work/widgets",
            "model_provider": "openai",
        },
    }
    call = {
        "timestamp": "2026-07-17T14:00:01Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": "call-1",
            "name": "exec",
            "input": '{"cmd":"private"}',
        },
    }
    source.write_text(
        "\n".join(json.dumps(row) for row in (session, call)) + "\n",
        encoding="utf-8",
    )
    first_events = [
        record
        for record in CodexAdapter().read(source).records
        if isinstance(record, NormalizedEvent)
    ]
    assert not any(isinstance(event.payload, ToolCallPayload) for event in first_events)

    output = {
        "timestamp": "2026-07-17T14:00:02Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": "call-1",
            "output": "private result",
        },
    }
    source.write_text(
        source.read_text(encoding="utf-8") + json.dumps(output) + "\n",
        encoding="utf-8",
    )
    second_events = [
        record
        for record in CodexAdapter().read(source).records
        if isinstance(record, NormalizedEvent)
    ]
    assert (
        len([event for event in second_events if isinstance(event.payload, ToolCallPayload)]) == 1
    )

    with MiltonStore(tmp_path / "events.db") as store:
        inserted, replayed = store.append_events(first_events)
        assert (inserted, replayed) == (1, 0)
        inserted, replayed = store.append_events(second_events)
        assert (inserted, replayed) == (1, 1)
