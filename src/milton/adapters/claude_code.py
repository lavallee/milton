"""Adapter for Claude Code project transcript JSONL."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

from milton.adapters.base import (
    AdapterRecord,
    ContentPolicy,
    ReadStats,
    SourceRead,
    project_from_cwd,
    protected_json,
    string_or_none,
    text_turn,
)
from milton.model import (
    CallStatus,
    CostKeyScope,
    CostPayload,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    SourceRef,
    ToolCallPayload,
    coverage_for,
    parse_datetime,
)


class ClaudeCodeAdapter:
    name = "claude-code"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.home() / ".claude" / "projects",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = [expanded] if expanded.is_file() else expanded.rglob("*.jsonl")
            for candidate in candidates:
                # Claude's workflow coordination journals share the JSONL suffix,
                # but are not model transcripts and do not carry session events.
                if candidate.name == "journal.jsonl":
                    continue
                resolved = candidate.resolve()
                if resolved not in seen and candidate.is_file():
                    seen.add(resolved)
                    yield candidate

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del until  # The ingest boundary filters records after adapter normalization.
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            session_native_id: str | None = None
            session_event_id: str | None = None
            seen_model_messages: set[str] = set()
            pending_tools: dict[str, tuple[datetime, str | None, object, int]] = {}
            try:
                handle = source.open(encoding="utf-8")
            except OSError as error:
                stats.warn("source-unreadable", str(error), source)
                return

            with handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    stats.source_records += 1
                    try:
                        raw = json.loads(line)
                        if not isinstance(raw, dict):
                            raise ValueError("record is not an object")
                    except (json.JSONDecodeError, TypeError, ValueError) as error:
                        stats.malformed_records += 1
                        stats.warn("malformed-jsonl", str(error), source, line_number)
                        continue

                    timestamp_value = raw.get("timestamp")
                    if timestamp_value is None and not isinstance(raw.get("message"), dict):
                        # File snapshots, prompt/title state, and mode changes are
                        # transcript metadata rather than timestamped interactions.
                        stats.skipped_records += 1
                        continue
                    try:
                        timestamp = parse_datetime(str(timestamp_value))
                    except (TypeError, ValueError) as error:
                        stats.malformed_records += 1
                        stats.warn("invalid-timestamp", str(error), source, line_number)
                        continue

                    parent_session_id = string_or_none(raw.get("sessionId"))
                    agent_id = string_or_none(raw.get("agentId"))
                    native_session = _session_identity(parent_session_id, agent_id)
                    if session_native_id is None and native_session:
                        session_native_id = native_session
                        cwd = string_or_none(raw.get("cwd"))
                        payload = SessionPayload(
                            project=project_from_cwd(cwd),
                            working_directory=cwd,
                            status=None,
                            harness="claude-code",
                        )
                        session_event = NormalizedEvent.create(
                            source=SourceRef(self.name, session_native_id, str(source)),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=payload,
                            attributes={
                                "version": string_or_none(raw.get("version")),
                                "git_branch": string_or_none(raw.get("gitBranch")),
                                "agent_id": agent_id,
                                "parent_session_id": parent_session_id if agent_id else None,
                                "sidechain": bool(raw.get("isSidechain", False)),
                                "entrypoint": string_or_none(raw.get("entrypoint")),
                            },
                        )
                        session_event_id = session_event.event_id
                        stats.emitted_records += 1
                        yield session_event

                    if native_session is not None and native_session != session_native_id:
                        stats.malformed_records += 1
                        stats.warn(
                            "mixed-session-source",
                            f"record belongs to {native_session!r}, expected {session_native_id!r}",
                            source,
                            line_number,
                        )
                        continue

                    if session_native_id is None or session_event_id is None:
                        stats.skipped_records += 1
                        continue

                    if since is not None and timestamp < since:
                        stats.skipped_records += 1
                        continue

                    record_type = raw.get("type")
                    message = raw.get("message")
                    if not isinstance(message, dict):
                        stats.skipped_records += 1
                        continue
                    content = message.get("content")

                    if record_type == "assistant":
                        message_id = (
                            string_or_none(message.get("id"))
                            or string_or_none(raw.get("requestId"))
                            or f"{session_native_id}:line:{line_number}"
                        )
                        if message_id not in seen_model_messages:
                            seen_model_messages.add(message_id)
                            model = string_or_none(message.get("model"))
                            stop_reason = string_or_none(message.get("stop_reason"))
                            request_id = string_or_none(raw.get("requestId"))
                            model_call = NormalizedEvent.create(
                                source=SourceRef(
                                    self.name,
                                    f"model:{session_native_id}:{message_id}",
                                    str(source),
                                ),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=ModelCallPayload(
                                    provider="anthropic",
                                    model=model,
                                    status=CallStatus.SUCCEEDED,
                                    finish_reason=stop_reason,
                                ),
                                session_id=session_event_id,
                                attributes={"request_id": request_id},
                            )
                            stats.emitted_records += 1
                            yield model_call
                            usage = message.get("usage")
                            if isinstance(usage, dict):
                                cost = CostPayload(
                                    amount_usd=None,
                                    input_tokens=_integer(usage.get("input_tokens")),
                                    output_tokens=_integer(usage.get("output_tokens")),
                                    cached_input_tokens=_integer(
                                        usage.get("cache_read_input_tokens")
                                    ),
                                    provider="anthropic",
                                    model=model,
                                    cache_write_tokens=_integer(
                                        usage.get("cache_creation_input_tokens")
                                    ),
                                    authority="claude-code",
                                    accounting_key=(
                                        f"anthropic.request={request_id}"
                                        if request_id
                                        else f"claude-code.message={session_native_id}:{message_id}"
                                    ),
                                    accounting_key_scope=(
                                        CostKeyScope.SHARED if request_id else CostKeyScope.SOURCE
                                    ),
                                )
                                cost_event = NormalizedEvent.create(
                                    source=SourceRef(
                                        self.name,
                                        f"usage:{session_native_id}:{message_id}",
                                        str(source),
                                    ),
                                    occurred_at=timestamp,
                                    recorded_at=timestamp,
                                    payload=cost,
                                    session_id=session_event_id,
                                    parent_event_id=model_call.event_id,
                                )
                                stats.emitted_records += 1
                                yield cost_event

                    text = _text_content(content)
                    if text:
                        role = string_or_none(message.get("role")) or string_or_none(record_type)
                        turn_payload, turn_coverage = text_turn(role, text, content_policy)
                        native = (
                            string_or_none(raw.get("uuid")) or f"{session_native_id}:{line_number}"
                        )
                        turn = NormalizedEvent.create(
                            source=SourceRef(self.name, f"message:{native}", str(source)),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=turn_payload,
                            coverage=turn_coverage,
                            session_id=session_event_id,
                            attributes={
                                "parent_uuid": string_or_none(raw.get("parentUuid")),
                                "agent_id": string_or_none(raw.get("agentId")),
                            },
                        )
                        stats.emitted_records += 1
                        yield turn

                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                call_id = string_or_none(block.get("id"))
                                if call_id:
                                    pending_tools[call_id] = (
                                        timestamp,
                                        string_or_none(block.get("name")),
                                        block.get("input"),
                                        line_number,
                                    )
                            elif block.get("type") == "tool_result":
                                call_id = string_or_none(block.get("tool_use_id"))
                                pending = pending_tools.pop(call_id, None) if call_id else None
                                if call_id and pending:
                                    started_at, tool_name, tool_input, start_line = pending
                                    is_error = bool(block.get("is_error", False))
                                    event = _tool_event(
                                        source,
                                        session_event_id,
                                        session_native_id,
                                        call_id,
                                        started_at,
                                        tool_name,
                                        tool_input,
                                        block.get("content"),
                                        is_error,
                                        content_policy,
                                        start_line,
                                    )
                                    stats.emitted_records += 1
                                    yield event
                                else:
                                    stats.malformed_records += 1
                                    stats.warn(
                                        "orphan-tool-output",
                                        f"no call found for tool result {call_id!r}",
                                        source,
                                        line_number,
                                    )

            stats.skipped_records += len(pending_tools)

        return SourceRead(records(), stats)


def _text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _session_identity(parent_session_id: str | None, agent_id: str | None) -> str | None:
    if parent_session_id is None:
        return None
    if agent_id is None:
        return parent_session_id
    return f"{parent_session_id}:agent:{agent_id}"


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def _tool_event(
    source: Path,
    session_event_id: str,
    session_native_id: str,
    call_id: str,
    timestamp: datetime,
    tool_name: str | None,
    tool_input: object,
    tool_output: object,
    is_error: bool,
    content_policy: ContentPolicy,
    source_line: int,
) -> NormalizedEvent:
    protected_input, input_status, input_meta = protected_json(tool_input, content_policy)
    protected_output, output_status, output_meta = protected_json(tool_output, content_policy)
    payload = ToolCallPayload(
        tool_name=tool_name,
        status=CallStatus.FAILED if is_error else CallStatus.SUCCEEDED,
        input=protected_input,
        output=protected_output,
        error=None,
    )
    coverage = coverage_for(payload, input=input_status, output=output_status)
    return NormalizedEvent.create(
        source=SourceRef("claude-code", f"tool:{session_native_id}:{call_id}", str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=payload,
        coverage=coverage,
        session_id=session_event_id,
        attributes={
            "call_id": call_id,
            "input_metadata": input_meta,
            "output_metadata": output_meta,
            "source_line": source_line,
        },
    )
