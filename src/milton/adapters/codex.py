"""Adapter for Codex rollout JSONL under ``~/.codex/sessions``."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

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
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.model import (
    CallStatus,
    CostKeyScope,
    CostPayload,
    ModelCallPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SessionPayload,
    SourceRef,
    ToolCallPayload,
    coverage_for,
    parse_datetime,
)


class CodexAdapter:
    name = "codex"

    def __init__(self) -> None:
        self._parent_turn_cache: dict[
            tuple[Path, str], tuple[tuple[datetime, str], ...] | None
        ] = {}

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.home() / ".codex" / "sessions",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = [expanded] if expanded.is_file() else expanded.rglob("rollout-*.jsonl")
            for candidate in candidates:
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
            skipping_inherited_history = False
            parent_turn_ids: frozenset[str] | None = None
            provider: str | None = None
            model: str | None = None
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
                        timestamp = parse_datetime(str(raw["timestamp"]))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                        stats.malformed_records += 1
                        stats.warn("malformed-jsonl", str(error), source, line_number)
                        continue

                    envelope_type = raw.get("type")
                    payload = raw.get("payload")
                    if not isinstance(payload, dict):
                        stats.skipped_records += 1
                        continue
                    payload_type = payload.get("type")

                    if envelope_type == "session_meta":
                        # Forked rollout files may embed their parent's complete
                        # session_meta as the second row. The first row owns this
                        # file; later metadata is ancestry context, not another
                        # session to emit under the same source stream.
                        if session_native_id is not None:
                            skipping_inherited_history = True
                            stats.skipped_records += 1
                            continue
                        session_native_id = string_or_none(payload.get("id")) or string_or_none(
                            payload.get("session_id")
                        )
                        if session_native_id is None:
                            stats.malformed_records += 1
                            stats.warn(
                                "missing-session-id",
                                "session_meta has no id or session_id",
                                source,
                                line_number,
                            )
                            continue
                        provider = string_or_none(payload.get("model_provider"))
                        cwd = string_or_none(payload.get("cwd"))
                        session_payload = SessionPayload(
                            project=project_from_cwd(cwd),
                            working_directory=cwd,
                            status=None,
                            harness="codex",
                        )
                        event = NormalizedEvent.create(
                            source=SourceRef(self.name, session_native_id, str(source)),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=session_payload,
                            attributes={
                                "cli_version": string_or_none(payload.get("cli_version")),
                                "originator": string_or_none(payload.get("originator")),
                                "source": string_or_none(payload.get("source")),
                                "thread_source": string_or_none(payload.get("thread_source")),
                                "git": _safe_git(payload.get("git")),
                            },
                        )
                        session_event_id = event.event_id
                        stats.emitted_records += 1
                        yield event
                        parent_id = string_or_none(
                            payload.get("parent_thread_id")
                        ) or string_or_none(payload.get("forked_from_id"))
                        if parent_id and parent_id != session_native_id:
                            parent_turn_ids = self._parent_turn_ids(
                                source,
                                parent_id,
                                before=timestamp,
                            )
                            # Newer compacted forks can omit the repeated
                            # parent session_meta and begin replaying inherited
                            # rows immediately after the child's metadata.
                            skipping_inherited_history = True
                            stats.emitted_records += 1
                            yield CrosswalkRecord.create(
                                left=ExternalIdentity("codex.session", session_native_id),
                                right=ExternalIdentity("codex.session", parent_id),
                                confidence=1,
                                method=JoinMethod.EXPLICIT,
                                evidence_event_ids=(event.event_id,),
                                recorded_at=timestamp,
                                note="Codex fork parent",
                            )
                        continue

                    # Forked files replay the parent's history with timestamps
                    # rewritten to the fork instant. A parent can have many
                    # task_started markers, so the child's stream begins at the
                    # first turn ID that did not exist in the parent at fork
                    # time. If the parent rollout is unavailable, retain the
                    # conservative legacy fallback of the next marker.
                    if skipping_inherited_history:
                        if envelope_type == "event_msg" and payload_type == "task_started":
                            turn_id = string_or_none(payload.get("turn_id"))
                            if parent_turn_ids is None or (
                                turn_id is not None and turn_id not in parent_turn_ids
                            ):
                                skipping_inherited_history = False
                        stats.skipped_records += 1
                        continue

                    if envelope_type == "turn_context":
                        model = string_or_none(payload.get("model")) or model
                        stats.skipped_records += 1
                        continue

                    if since is not None and timestamp < since:
                        stats.skipped_records += 1
                        continue

                    if session_native_id is None or session_event_id is None:
                        stats.skipped_records += 1
                        continue

                    if envelope_type == "response_item" and payload_type == "message":
                        role = string_or_none(payload.get("role"))
                        text = _content_text(payload.get("content"))
                        native = (
                            string_or_none(payload.get("id"))
                            or f"{session_native_id}:line:{line_number}"
                        )
                        if text:
                            turn_payload, turn_coverage = text_turn(role, text, content_policy)
                            turn = NormalizedEvent.create(
                                source=SourceRef(self.name, f"message:{native}", str(source)),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=turn_payload,
                                coverage=turn_coverage,
                                session_id=session_event_id,
                                attributes={"phase": string_or_none(payload.get("phase"))},
                            )
                            stats.emitted_records += 1
                            yield turn
                        if role == "assistant":
                            model_call = NormalizedEvent.create(
                                source=SourceRef(self.name, f"model:{native}", str(source)),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=ModelCallPayload(
                                    provider=provider,
                                    model=model,
                                    status=CallStatus.SUCCEEDED,
                                    finish_reason=None,
                                ),
                                session_id=session_event_id,
                            )
                            stats.emitted_records += 1
                            yield model_call
                        continue

                    if envelope_type == "response_item" and payload_type in {
                        "custom_tool_call",
                        "function_call",
                    }:
                        call_id = string_or_none(payload.get("call_id")) or string_or_none(
                            payload.get("id")
                        )
                        if call_id:
                            pending_tools[call_id] = (
                                timestamp,
                                string_or_none(payload.get("name")),
                                payload.get("input"),
                                line_number,
                            )
                        else:
                            stats.malformed_records += 1
                            stats.warn(
                                "missing-tool-id", "tool call has no id", source, line_number
                            )
                        continue

                    if envelope_type == "response_item" and payload_type in {
                        "custom_tool_call_output",
                        "function_call_output",
                    }:
                        call_id = string_or_none(payload.get("call_id"))
                        pending = pending_tools.pop(call_id, None) if call_id else None
                        if call_id and pending:
                            started_at, tool_name, tool_input, start_line = pending
                            event = _tool_event(
                                source,
                                session_event_id,
                                session_native_id,
                                call_id,
                                started_at,
                                tool_name,
                                tool_input,
                                payload.get("output"),
                                CallStatus.SUCCEEDED,
                                content_policy,
                                start_line,
                            )
                            stats.emitted_records += 1
                            yield event
                        else:
                            stats.malformed_records += 1
                            stats.warn(
                                "orphan-tool-output",
                                f"no call found for tool output {call_id!r}",
                                source,
                                line_number,
                            )
                        continue

                    if envelope_type == "event_msg" and payload_type == "token_count":
                        info = payload.get("info")
                        usage = info.get("last_token_usage") if isinstance(info, dict) else None
                        if isinstance(usage, dict):
                            cost_payload = CostPayload(
                                amount_usd=None,
                                input_tokens=_integer(usage.get("input_tokens")),
                                output_tokens=_integer(usage.get("output_tokens")),
                                cached_input_tokens=_integer(usage.get("cached_input_tokens")),
                                provider=provider,
                                model=model,
                                reasoning_tokens=_integer(usage.get("reasoning_output_tokens")),
                                authority="codex",
                                accounting_key=f"codex.usage={session_native_id}:{line_number}",
                                accounting_key_scope=CostKeyScope.SOURCE,
                            )
                            event = NormalizedEvent.create(
                                source=SourceRef(
                                    self.name,
                                    f"usage:{session_native_id}:{line_number}",
                                    str(source),
                                ),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=cost_payload,
                                session_id=session_event_id,
                            )
                            stats.emitted_records += 1
                            yield event
                        else:
                            stats.skipped_records += 1
                        continue

                    if envelope_type == "event_msg" and payload_type == "task_complete":
                        turn_id = string_or_none(payload.get("turn_id")) or str(line_number)
                        outcome = NormalizedEvent.create(
                            source=SourceRef(
                                self.name, f"task:{session_native_id}:{turn_id}", str(source)
                            ),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=OutcomePayload("task", OutcomeStatus.SUCCEEDED, turn_id),
                            session_id=session_event_id,
                            attributes={
                                "duration_ms": _integer(payload.get("duration_ms")),
                                "time_to_first_token_ms": _integer(
                                    payload.get("time_to_first_token_ms")
                                ),
                            },
                        )
                        stats.emitted_records += 1
                        yield outcome
                        continue

                    stats.skipped_records += 1

            # An actively growing transcript can end mid-call. Persist only
            # completed pairs so a later append cannot mutate a stable event.
            stats.skipped_records += len(pending_tools)

        return SourceRead(records(), stats)

    def _parent_turn_ids(
        self,
        source: Path,
        parent_id: str,
        *,
        before: datetime,
    ) -> frozenset[str] | None:
        sessions_root = next(
            (ancestor for ancestor in source.parents if ancestor.name == "sessions"),
            source.parent,
        )
        cache_key = (sessions_root, parent_id)
        cached = self._parent_turn_cache.get(cache_key)
        if cache_key not in self._parent_turn_cache:
            parent_source = next(
                sessions_root.rglob(f"rollout-*{parent_id}.jsonl"),
                None,
            )
            if parent_source is None or parent_source == source:
                cached = None
            else:
                turns: list[tuple[datetime, str]] = []
                try:
                    with parent_source.open(encoding="utf-8") as handle:
                        for line in handle:
                            if not line.strip():
                                continue
                            try:
                                raw = json.loads(line)
                                payload = raw.get("payload")
                                if (
                                    raw.get("type") != "event_msg"
                                    or not isinstance(payload, dict)
                                    or payload.get("type") != "task_started"
                                ):
                                    continue
                                occurred_at = parse_datetime(str(raw["timestamp"]))
                                turn_id = string_or_none(payload.get("turn_id"))
                            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                                continue
                            if turn_id is not None:
                                turns.append((occurred_at, turn_id))
                except OSError:
                    cached = None
                else:
                    cached = tuple(turns)
            self._parent_turn_cache[cache_key] = cached

        if cached is None:
            return None
        return frozenset(turn_id for occurred_at, turn_id in cached if occurred_at <= before)


def _content_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"}:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def _safe_git(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = ("branch", "commit_hash", "repository_url")
    return {key: value[key] for key in allowed if isinstance(value.get(key), str)}


def _tool_event(
    source: Path,
    session_event_id: str,
    session_native_id: str,
    call_id: str,
    timestamp: datetime,
    tool_name: str | None,
    tool_input: object,
    tool_output: object,
    status: CallStatus,
    content_policy: ContentPolicy,
    source_line: int,
) -> NormalizedEvent:
    protected_input, input_status, input_meta = protected_json(tool_input, content_policy)
    protected_output, output_status, output_meta = protected_json(tool_output, content_policy)
    payload = ToolCallPayload(
        tool_name=tool_name,
        status=status,
        input=protected_input,
        output=protected_output,
        error=None,
    )
    coverage = coverage_for(
        payload,
        input=input_status,
        output=output_status,
    )
    return NormalizedEvent.create(
        source=SourceRef("codex", f"tool:{session_native_id}:{call_id}", str(source)),
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
