"""Metadata reader for explicitly supplied Pi v3 native session files."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from milton.adapters.base import (
    AdapterRecord,
    ContentPolicy,
    ReadStats,
    SourceRead,
    project_from_cwd,
    string_or_none,
)
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostObservationRole,
    CostPayload,
    ModelCallPayload,
    NormalizedEvent,
    SessionPayload,
    SourceRef,
    parse_datetime,
)

_FINISHED = {
    "stop": CallStatus.SUCCEEDED,
    "toolUse": CallStatus.SUCCEEDED,
    "length": CallStatus.SUCCEEDED,
    "aborted": CallStatus.CANCELLED,
    "error": CallStatus.FAILED,
}


class PiAdapter:
    name = "pi"

    def default_roots(self) -> tuple[Path, ...]:
        return ()

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        files: set[Path] = set()
        for root in roots:
            root = root.expanduser()
            candidates = [root] if root.is_file() else root.rglob("*.jsonl")
            files.update(p.resolve() for p in candidates if p.suffix == ".jsonl" and p.is_file())
        yield from sorted(files)

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del content_policy  # This adapter never emits message or tool bodies.
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            session: NormalizedEvent | None = None
            with source.open("rb") as handle:
                for number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    stats.source_records += 1
                    try:
                        raw = json.loads(line, parse_float=Decimal)
                        if not isinstance(raw, dict):
                            raise ValueError
                        timestamp = parse_datetime(raw["timestamp"])
                    except (ValueError, TypeError, AttributeError, KeyError):
                        stats.malformed_records += 1
                        stats.warn(
                            "malformed-pi-record", "Expected a dated JSON object", source, number
                        )
                        if session is None:
                            return
                        continue

                    if session is None:
                        sid = string_or_none(raw.get("id"))
                        if (
                            raw.get("type") != "session"
                            or type(raw.get("version")) is not int
                            or raw.get("version") != 3
                            or not sid
                            or not sid.strip()
                            or ":" in sid
                        ):
                            stats.warn(
                                "unsupported-pi-session",
                                "Expected a Pi v3 session header and ID",
                                source,
                                number,
                            )
                            return
                        cwd = string_or_none(raw.get("cwd"))
                        session = NormalizedEvent.create(
                            source=SourceRef(self.name, sid, str(source)),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=SessionPayload(project_from_cwd(cwd), cwd, None, self.name),
                        )
                        stats.emitted_records += 1
                        yield session
                        if "parentSession" in raw and raw["parentSession"] is not None:
                            stats.warn(
                                "pi-fork-history",
                                "Fork may contain copied history; only its session is emitted",
                                source,
                                number,
                            )
                            return
                        continue

                    if raw.get("type") == "session":
                        stats.warn(
                            "unexpected-pi-header",
                            "Stopped at a second session header",
                            source,
                            number,
                        )
                        return
                    if (since is not None and timestamp < since) or (
                        until is not None and timestamp >= until
                    ):
                        stats.skipped_records += 1
                        continue
                    emitted = False
                    try:
                        for event in _entry(raw, session, timestamp, source, number):
                            stats.emitted_records += 1
                            emitted = True
                            yield event
                    except ValueError as error:
                        stats.malformed_records += 1
                        stats.warn("invalid-pi-entry", str(error), source, number)
                        continue
                    if not emitted:
                        stats.skipped_records += 1

        return SourceRead(records(), stats)


def _entry(
    raw: dict[str, object], session: NormalizedEvent, timestamp: datetime, source: Path, number: int
) -> Iterator[NormalizedEvent]:
    kind = raw.get("type")
    if kind == "message":
        message = raw.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return
        fields = message
    elif kind in ("usage", "compaction", "branch_summary") and isinstance(raw.get("usage"), dict):
        fields = raw
    else:
        return
    entry_id = string_or_none(raw.get("id"))
    if not entry_id or not entry_id.strip():
        raise ValueError("Missing native entry ID")
    coordinate = f"{session.source.native_id}:{entry_id}"
    location = f"{source}#{number}"
    provider = string_or_none(fields.get("provider"))
    model = string_or_none(fields.get("responseModel")) or string_or_none(fields.get("model"))
    call = None
    if kind == "message":
        reason = string_or_none(fields.get("stopReason"))
        if reason in ("pending", "deferred"):
            return
        call = NormalizedEvent.create(
            source=SourceRef("pi", f"model:{coordinate}", location),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=ModelCallPayload(
                provider, model, _FINISHED.get(reason or "", CallStatus.UNKNOWN), reason
            ),
            session_id=session.event_id,
        )
        yield call

    usage = fields.get("usage")
    if not isinstance(usage, dict):
        return

    def tokens(key: str) -> int | None:
        value = usage.get(key)
        if value is None:
            return None
        if type(value) is not int or value < 0:
            raise ValueError(f"Invalid Pi token count for {key}")
        return value

    cost = usage.get("cost")
    total = cost.get("total") if isinstance(cost, dict) else None
    amount = (
        Decimal(total)
        if isinstance(total, (int, Decimal)) and not isinstance(total, bool)
        else None
    )
    if total is not None and amount is None:
        raise ValueError("Invalid Pi cost total")
    reported = isinstance(cost, dict) and cost.get("totalFromProvider") is True
    if amount is not None and (not amount.is_finite() or amount < 0):
        raise ValueError("Invalid Pi cost total")
    if amount == 0 and not reported:
        amount = None  # Catalog zero alone cannot establish a free call.
    payload = CostPayload(
        amount_usd=amount,
        input_tokens=tokens("input"),
        output_tokens=tokens("output"),
        cached_input_tokens=tokens("cacheRead"),
        cache_write_tokens=tokens("cacheWrite"),
        reasoning_tokens=tokens("reasoning"),
        provider=provider,
        model=model,
        authority="pi",
        basis=(CostBasis.REPORTED if reported else CostBasis.COMPUTED)
        if amount is not None
        else CostBasis.UNKNOWN,
        accuracy=(CostAccuracy.ACTUAL if reported else CostAccuracy.ESTIMATED)
        if amount is not None
        else CostAccuracy.UNKNOWN,
        accounting_key=f"pi.entry={coordinate}",
        accounting_key_scope=CostKeyScope.SOURCE,
        observation_role=CostObservationRole.PRODUCTION,
    )
    yield NormalizedEvent.create(
        source=SourceRef("pi", f"usage:{coordinate}", location),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=payload,
        session_id=session.event_id,
        parent_event_id=call.event_id if call else None,
        attributes={"entry_type": str(kind)},
    )
