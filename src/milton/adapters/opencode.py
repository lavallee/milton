"""Adapter for OpenCode's SQLite session/message/part store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from milton.adapters._sqlite import connect_readonly, table_columns
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
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostPayload,
    CoverageStatus,
    JsonValue,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    SourceRef,
    ToolCallPayload,
    coverage_for,
    stable_id,
)


class OpenCodeAdapter:
    name = "opencode"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.home() / ".local" / "share" / "opencode" / "opencode.db",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = [expanded] if expanded.is_file() else [expanded / "opencode.db"]
            for candidate in candidates:
                if candidate.is_file() and candidate.resolve() not in seen:
                    seen.add(candidate.resolve())
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
            try:
                connection = connect_readonly(source)
            except sqlite3.Error as error:
                stats.warn("source-unreadable", str(error), source)
                return
            with closing(connection):
                required = {
                    "session": {"id", "project_id", "directory", "time_created"},
                    "message": {"id", "session_id", "time_created", "data"},
                    "part": {"id", "message_id", "session_id", "time_created", "data"},
                }
                missing = {
                    table: sorted(columns.difference(table_columns(connection, table)))
                    for table, columns in required.items()
                }
                missing = {table: columns for table, columns in missing.items() if columns}
                if missing:
                    stats.warn("unsupported-schema", f"missing columns: {missing}", source)
                    return

                since_ms = int(since.timestamp() * 1000) if since else None
                query = """
                    SELECT
                        s.id AS session_native_id, s.project_id, s.parent_id,
                        s.directory, s.version, s.time_created AS session_created,
                        s.time_archived, s.agent, s.title,
                        pjt.name AS project_name, pjt.worktree,
                        m.id AS message_id, m.time_created AS message_created, m.data AS message_data,
                        p.id AS part_id, p.time_created AS part_created, p.data AS part_data
                    FROM session s
                    LEFT JOIN project pjt ON pjt.id = s.project_id
                    LEFT JOIN message m ON m.session_id = s.id
                    LEFT JOIN part p ON p.message_id = m.id
                    WHERE (? IS NULL OR s.time_created >= ?)
                    ORDER BY s.time_created, s.id, m.time_created, m.id, p.time_created, p.id
                """
                seen_sessions: set[str] = set()
                seen_messages: set[str] = set()
                try:
                    for row in connection.execute(query, (since_ms, since_ms)):
                        session_native_id = str(row["session_native_id"])
                        session_event_id = stable_id("evt", self.name, "session", session_native_id)
                        session_timestamp = _millisecond_time(row["session_created"])
                        if session_native_id not in seen_sessions:
                            seen_sessions.add(session_native_id)
                            directory = string_or_none(row["directory"])
                            project_name = string_or_none(row["project_name"])
                            session = NormalizedEvent.create(
                                source=SourceRef(self.name, session_native_id, str(source)),
                                occurred_at=session_timestamp,
                                recorded_at=session_timestamp,
                                payload=SessionPayload(
                                    project=project_name or project_from_cwd(directory),
                                    working_directory=directory,
                                    status="archived" if row["time_archived"] else None,
                                    harness="opencode",
                                ),
                                attributes={
                                    "project_id": str(row["project_id"]),
                                    "parent_session_id": string_or_none(row["parent_id"]),
                                    "version": string_or_none(row["version"]),
                                    "agent": string_or_none(row["agent"]),
                                    "worktree": string_or_none(row["worktree"]),
                                    "title_sha256": _text_hash(row["title"]),
                                    "title_chars": _text_length(row["title"]),
                                },
                            )
                            stats.emitted_records += 1
                            yield session
                            parent = string_or_none(row["parent_id"])
                            if parent:
                                crosswalk = CrosswalkRecord.create(
                                    left=ExternalIdentity("opencode.session", session_native_id),
                                    right=ExternalIdentity("opencode.session", parent),
                                    confidence=1,
                                    method=JoinMethod.EXPLICIT,
                                    evidence_event_ids=(session.event_id,),
                                    recorded_at=session_timestamp,
                                    note="parent session",
                                )
                                stats.emitted_records += 1
                                yield crosswalk

                        if row["message_id"] is None:
                            continue
                        message_id = str(row["message_id"])
                        try:
                            message_data = json.loads(str(row["message_data"]))
                        except (json.JSONDecodeError, TypeError, ValueError) as error:
                            stats.malformed_records += 1
                            stats.warn("malformed-message", str(error), source)
                            continue
                        if not isinstance(message_data, dict):
                            stats.malformed_records += 1
                            stats.warn("malformed-message", "message data is not an object", source)
                            continue
                        role = string_or_none(message_data.get("role"))
                        message_timestamp = _millisecond_time(row["message_created"])
                        if message_id not in seen_messages:
                            seen_messages.add(message_id)
                            if role == "assistant":
                                model_call, cost_event = _model_records(
                                    source,
                                    session_native_id,
                                    session_event_id,
                                    message_id,
                                    message_timestamp,
                                    message_data,
                                )
                                stats.emitted_records += 1
                                yield model_call
                                stats.emitted_records += 1
                                yield cost_event

                        if row["part_id"] is None:
                            continue
                        stats.source_records += 1
                        try:
                            part_data = json.loads(str(row["part_data"]))
                        except (json.JSONDecodeError, TypeError, ValueError) as error:
                            stats.malformed_records += 1
                            stats.warn("malformed-part", str(error), source)
                            continue
                        if not isinstance(part_data, dict):
                            stats.malformed_records += 1
                            continue
                        part_id = str(row["part_id"])
                        timestamp = _millisecond_time(row["part_created"])
                        part_type = part_data.get("type")
                        if part_type == "text" and isinstance(part_data.get("text"), str):
                            turn_payload, turn_coverage = text_turn(
                                role, part_data["text"], content_policy
                            )
                            turn = NormalizedEvent.create(
                                source=SourceRef(
                                    self.name,
                                    f"part:{session_native_id}:{part_id}",
                                    str(source),
                                ),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=turn_payload,
                                coverage=turn_coverage,
                                session_id=session_event_id,
                                attributes={"message_id": message_id},
                            )
                            stats.emitted_records += 1
                            yield turn
                        elif part_type == "tool":
                            event = _tool_record(
                                source,
                                session_native_id,
                                session_event_id,
                                part_id,
                                timestamp,
                                message_id,
                                part_data,
                                content_policy,
                            )
                            stats.emitted_records += 1
                            yield event
                        else:
                            stats.skipped_records += 1
                except (sqlite3.Error, TypeError, ValueError) as error:
                    stats.warn("query-failed", str(error), source)

        return SourceRead(records(), stats)


def _model_records(
    source: Path,
    session_native_id: str,
    session_event_id: str,
    message_id: str,
    timestamp: datetime,
    data: dict[str, object],
) -> tuple[NormalizedEvent, NormalizedEvent]:
    provider = string_or_none(data.get("providerID"))
    model = string_or_none(data.get("modelID"))
    nested_model = data.get("model")
    if isinstance(nested_model, dict):
        provider = provider or string_or_none(nested_model.get("providerID"))
        model = model or string_or_none(nested_model.get("modelID"))
    error = data.get("error")
    model_call = NormalizedEvent.create(
        source=SourceRef("opencode", f"model:{session_native_id}:{message_id}", str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=ModelCallPayload(
            provider=provider,
            model=model,
            status=CallStatus.FAILED if error else CallStatus.SUCCEEDED,
            finish_reason=string_or_none(data.get("finish")),
        ),
        session_id=session_event_id,
        attributes={"error_sha256": _json_hash(error)},
    )
    tokens = data.get("tokens")
    token_data = tokens if isinstance(tokens, dict) else {}
    cache = token_data.get("cache")
    cache_data = cache if isinstance(cache, dict) else {}
    amount = data.get("cost")
    cost_payload = CostPayload(
        amount_usd=Decimal(str(amount)) if isinstance(amount, int | float) else None,
        input_tokens=_integer(token_data.get("input")),
        output_tokens=_integer(token_data.get("output")),
        cached_input_tokens=_integer(cache_data.get("read")),
        provider=provider,
        model=model,
        cache_write_tokens=_integer(cache_data.get("write")),
        reasoning_tokens=_integer(token_data.get("reasoning")),
        basis=CostBasis.REPORTED,
        kind=CostKind.UNKNOWN,
        accuracy=CostAccuracy.UNKNOWN,
        authority="opencode",
        accounting_key=f"opencode.message={session_native_id}:{message_id}",
        accounting_key_scope=CostKeyScope.SOURCE,
    )
    cost = NormalizedEvent.create(
        source=SourceRef("opencode", f"cost:{session_native_id}:{message_id}", str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=cost_payload,
        session_id=session_event_id,
        parent_event_id=model_call.event_id,
    )
    return model_call, cost


def _tool_record(
    source: Path,
    session_native_id: str,
    session_event_id: str,
    part_id: str,
    timestamp: datetime,
    message_id: str,
    data: dict[str, object],
    content_policy: ContentPolicy,
) -> NormalizedEvent:
    state = data.get("state")
    state_data = state if isinstance(state, dict) else {}
    input_value, input_status, input_meta = _protected_field(state_data, "input", content_policy)
    output_value, output_status, output_meta = _protected_field(
        state_data, "output", content_policy
    )
    error = state_data.get("error")
    status_name = string_or_none(state_data.get("status"))
    status = {
        "completed": CallStatus.SUCCEEDED,
        "error": CallStatus.FAILED,
        "running": CallStatus.STARTED,
        "pending": CallStatus.STARTED,
    }.get(status_name or "", CallStatus.UNKNOWN)
    payload = ToolCallPayload(
        tool_name=string_or_none(data.get("tool")),
        status=status,
        input=input_value,
        output=output_value,
        error=None,
    )
    coverage = coverage_for(payload, input=input_status, output=output_status)
    if error is not None:
        coverage["error"] = CoverageStatus.REDACTED
    call_id = string_or_none(data.get("callID")) or part_id
    return NormalizedEvent.create(
        source=SourceRef("opencode", f"tool:{session_native_id}:{call_id}", str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=payload,
        coverage=coverage,
        session_id=session_event_id,
        attributes={
            "message_id": message_id,
            "part_id": part_id,
            "call_id": call_id,
            "input_metadata": input_meta,
            "output_metadata": output_meta,
            "error_sha256": _json_hash(error),
        },
    )


def _protected_field(
    data: dict[str, object], key: str, policy: ContentPolicy
) -> tuple[JsonValue, CoverageStatus, dict[str, JsonValue] | None]:
    if key not in data:
        return None, CoverageStatus.UNAVAILABLE, None
    return protected_json(data[key], policy)


def _millisecond_time(value: object) -> datetime:
    return datetime.fromtimestamp(float(str(value)) / 1000, UTC)


def _integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _json_hash(value: object) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _text_hash(value: object) -> str | None:
    text = string_or_none(value)
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def _text_length(value: object) -> int | None:
    text = string_or_none(value)
    return len(text) if text else None
