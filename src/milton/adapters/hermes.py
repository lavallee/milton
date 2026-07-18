"""Adapter for Hermes Agent's session and message SQLite store."""

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
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    SourceRef,
    ToolCallPayload,
    coverage_for,
)

_REQUIRED_SESSION_COLUMNS = {
    "id",
    "source",
    "model",
    "started_at",
    "ended_at",
    "input_tokens",
    "output_tokens",
}
_REQUIRED_MESSAGE_COLUMNS = {"id", "session_id", "role", "content", "timestamp"}


class HermesAdapter:
    name = "hermes"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.home() / ".hermes" / "state.db",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = [expanded] if expanded.is_file() else [expanded / "state.db"]
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
                missing_sessions = _REQUIRED_SESSION_COLUMNS.difference(
                    table_columns(connection, "sessions")
                )
                missing_messages = _REQUIRED_MESSAGE_COLUMNS.difference(
                    table_columns(connection, "messages")
                )
                if missing_sessions or missing_messages:
                    stats.warn(
                        "unsupported-schema",
                        f"missing session columns {sorted(missing_sessions)}; "
                        f"message columns {sorted(missing_messages)}",
                        source,
                    )
                    return

                since_epoch = since.timestamp() if since else None
                query = """
                    SELECT
                        s.id AS session_native_id, s.source AS session_source,
                        s.model, s.parent_session_id, s.started_at, s.ended_at,
                        s.end_reason, s.input_tokens, s.output_tokens,
                        s.cache_read_tokens, s.cache_write_tokens, s.reasoning_tokens,
                        s.billing_provider, s.billing_mode, s.estimated_cost_usd,
                        s.actual_cost_usd, s.cost_status, s.cost_source,
                        s.pricing_version, s.title,
                        m.id AS message_id, m.role, m.content, m.tool_call_id,
                        m.tool_calls, m.tool_name, m.timestamp AS message_timestamp,
                        m.token_count, m.finish_reason
                    FROM sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    WHERE (? IS NULL OR s.started_at >= ?)
                    ORDER BY s.started_at, s.id, m.timestamp, m.id
                """
                seen_sessions: set[str] = set()
                pending_tools: dict[tuple[str, str], tuple[datetime, str | None, object, int]] = {}
                try:
                    cursor = connection.execute(query, (since_epoch, since_epoch))
                    for row in cursor:
                        session_native_id = str(row["session_native_id"])
                        started_at = _unix_time(row["started_at"])
                        session_event_id = _session_event_id(session_native_id)
                        if session_native_id not in seen_sessions:
                            seen_sessions.add(session_native_id)
                            session = NormalizedEvent.create(
                                source=SourceRef(self.name, session_native_id, str(source)),
                                occurred_at=started_at,
                                recorded_at=started_at,
                                payload=SessionPayload(
                                    project=None,
                                    working_directory=None,
                                    status=string_or_none(row["end_reason"])
                                    if row["ended_at"] is not None
                                    else "running",
                                    harness="hermes",
                                ),
                                attributes={
                                    "source": string_or_none(row["session_source"]),
                                    "parent_session_id": string_or_none(row["parent_session_id"]),
                                    "ended_at": _optional_unix_iso(row["ended_at"]),
                                    "title_sha256": _text_hash(row["title"]),
                                    "title_chars": _text_length(row["title"]),
                                    "billing_mode": string_or_none(row["billing_mode"]),
                                },
                            )
                            stats.emitted_records += 1
                            yield session

                            cost_event = _session_cost(row, source, session_event_id, started_at)
                            stats.emitted_records += 1
                            yield cost_event

                            parent_session_id = string_or_none(row["parent_session_id"])
                            if parent_session_id:
                                crosswalk = CrosswalkRecord.create(
                                    left=ExternalIdentity("hermes.session", session_native_id),
                                    right=ExternalIdentity("hermes.session", parent_session_id),
                                    confidence=1,
                                    method=JoinMethod.EXPLICIT,
                                    evidence_event_ids=(session.event_id,),
                                    recorded_at=started_at,
                                    note="parent session",
                                )
                                stats.emitted_records += 1
                                yield crosswalk

                        if row["message_id"] is None:
                            continue
                        stats.source_records += 1
                        message_id = str(row["message_id"])
                        timestamp = _unix_time(row["message_timestamp"])
                        role = str(row["role"])
                        content = string_or_none(row["content"])

                        if content and role in {"user", "assistant", "system"}:
                            payload, coverage = text_turn(role, content, content_policy)
                            turn = NormalizedEvent.create(
                                source=SourceRef(
                                    self.name,
                                    f"message:{session_native_id}:{message_id}",
                                    str(source),
                                ),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=payload,
                                coverage=coverage,
                                session_id=session_event_id,
                            )
                            stats.emitted_records += 1
                            yield turn

                        if role == "assistant":
                            model_call = NormalizedEvent.create(
                                source=SourceRef(
                                    self.name,
                                    f"model:{session_native_id}:{message_id}",
                                    str(source),
                                ),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=ModelCallPayload(
                                    provider=string_or_none(row["billing_provider"]),
                                    model=string_or_none(row["model"]),
                                    status=CallStatus.SUCCEEDED,
                                    finish_reason=string_or_none(row["finish_reason"]),
                                ),
                                session_id=session_event_id,
                                attributes={"token_count": _integer(row["token_count"])},
                            )
                            stats.emitted_records += 1
                            yield model_call
                            for call_id, tool_name, tool_input in _tool_calls(row["tool_calls"]):
                                pending_tools[(session_native_id, call_id)] = (
                                    timestamp,
                                    tool_name,
                                    tool_input,
                                    int(row["message_id"]),
                                )

                        if role == "tool":
                            tool_result_id = string_or_none(row["tool_call_id"])
                            pending = (
                                pending_tools.pop((session_native_id, tool_result_id), None)
                                if tool_result_id
                                else None
                            )
                            if tool_result_id and pending:
                                call_at, tool_name, tool_input, call_message_id = pending
                                event = _tool_event(
                                    source=source,
                                    session_native_id=session_native_id,
                                    session_event_id=session_event_id,
                                    call_id=tool_result_id,
                                    timestamp=call_at,
                                    tool_name=tool_name or string_or_none(row["tool_name"]),
                                    tool_input=tool_input,
                                    tool_output=content,
                                    content_policy=content_policy,
                                    call_message_id=call_message_id,
                                )
                                stats.emitted_records += 1
                                yield event
                            else:
                                stats.malformed_records += 1
                                stats.warn(
                                    "orphan-tool-output",
                                    f"no call found for tool result {tool_result_id!r}",
                                    source,
                                )
                except (sqlite3.Error, TypeError, ValueError) as error:
                    stats.warn("query-failed", str(error), source)

                stats.skipped_records += len(pending_tools)

        return SourceRead(records(), stats)


def _session_event_id(session_id: str) -> str:
    from milton.model import stable_id

    return stable_id("evt", "hermes", "session", session_id)


def _session_cost(
    row: sqlite3.Row,
    source: Path,
    session_event_id: str,
    timestamp: datetime,
) -> NormalizedEvent:
    actual = row["actual_cost_usd"]
    estimated = row["estimated_cost_usd"]
    amount = actual if actual is not None else estimated
    payload = CostPayload(
        amount_usd=Decimal(str(amount)) if amount is not None else None,
        input_tokens=_integer(row["input_tokens"]),
        output_tokens=_integer(row["output_tokens"]),
        cached_input_tokens=_integer(row["cache_read_tokens"]),
        provider=string_or_none(row["billing_provider"]),
        model=string_or_none(row["model"]),
        cache_write_tokens=_integer(row["cache_write_tokens"]),
        reasoning_tokens=_integer(row["reasoning_tokens"]),
        basis=CostBasis.REPORTED if actual is not None else CostBasis.COMPUTED,
        kind=_cost_kind(row["billing_mode"]),
        accuracy=CostAccuracy.ACTUAL if actual is not None else CostAccuracy.ESTIMATED,
        authority="hermes",
        pricing_version=string_or_none(row["pricing_version"])
        or string_or_none(row["cost_source"]),
        accounting_key=f"hermes.session={row['session_native_id']}",
        accounting_key_scope=CostKeyScope.SOURCE,
    )
    coverage = coverage_for(payload)
    if actual is None and estimated is not None:
        coverage["amount_usd"] = CoverageStatus.INFERRED
    return NormalizedEvent.create(
        source=SourceRef("hermes", f"cost:{row['session_native_id']}", str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=payload,
        coverage=coverage,
        session_id=session_event_id,
        attributes={
            "cost_status": string_or_none(row["cost_status"]),
            "cost_source": string_or_none(row["cost_source"]),
            "pricing_version": string_or_none(row["pricing_version"]),
            "basis": "actual"
            if actual is not None
            else "estimated"
            if estimated is not None
            else None,
        },
    )


def _cost_kind(value: object) -> CostKind:
    mode = (string_or_none(value) or "").lower()
    if "included" in mode:
        return CostKind.INCLUDED
    if any(marker in mode for marker in ("subscription", "metered", "notional")):
        return CostKind.NOTIONAL
    if mode in {"payg", "actual"}:
        return CostKind.MARGINAL
    return CostKind.UNKNOWN


def _tool_calls(raw: object) -> Iterator[tuple[str, str | None, object]]:
    if not isinstance(raw, str) or not raw:
        return
    try:
        calls = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict):
            continue
        call_id = string_or_none(call.get("id")) or string_or_none(call.get("call_id"))
        function = call.get("function")
        if not call_id or not isinstance(function, dict):
            continue
        arguments: object = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                pass
        yield call_id, string_or_none(function.get("name")), arguments


def _tool_event(
    *,
    source: Path,
    session_native_id: str,
    session_event_id: str,
    call_id: str,
    timestamp: datetime,
    tool_name: str | None,
    tool_input: object,
    tool_output: object,
    content_policy: ContentPolicy,
    call_message_id: int,
) -> NormalizedEvent:
    protected_input, input_status, input_meta = protected_json(tool_input, content_policy)
    protected_output, output_status, output_meta = protected_json(tool_output, content_policy)
    payload = ToolCallPayload(
        tool_name=tool_name,
        status=CallStatus.SUCCEEDED,
        input=protected_input,
        output=protected_output,
        error=None,
    )
    return NormalizedEvent.create(
        source=SourceRef("hermes", f"tool:{session_native_id}:{call_id}", str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=payload,
        coverage=coverage_for(payload, input=input_status, output=output_status),
        session_id=session_event_id,
        attributes={
            "call_id": call_id,
            "call_message_id": call_message_id,
            "input_metadata": input_meta,
            "output_metadata": output_meta,
        },
    )


def _unix_time(value: object) -> datetime:
    return datetime.fromtimestamp(float(str(value)), UTC)


def _optional_unix_iso(value: object) -> str | None:
    return _unix_time(value).isoformat() if value is not None else None


def _integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _text_hash(value: object) -> str | None:
    text = string_or_none(value)
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def _text_length(value: object) -> int | None:
    text = string_or_none(value)
    return len(text) if text else None
