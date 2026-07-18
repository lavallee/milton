"""Deterministic projections over normalized events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from milton.accounting import AccountingProjection, build_accounting, select_cost_events
from milton.model import (
    CostPayload,
    CoverageStatus,
    EventKind,
    JsonValue,
    NormalizedEvent,
    format_datetime,
)


@dataclass(slots=True)
class AdapterSummary:
    events: int = 0
    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    coverage: dict[str, int] = field(default_factory=dict)
    gaps: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "events": self.events,
            "cost_usd": str(self.cost_usd),
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "cached_input": self.cached_input_tokens,
                "cache_write": self.cache_write_tokens,
                "reasoning": self.reasoning_tokens,
            },
            "coverage": dict(sorted(self.coverage.items())),
            "gaps": dict(sorted(self.gaps.items())),
        }


@dataclass(frozen=True, slots=True)
class SourceCoverageSummary:
    status: str
    last_ingested_at: datetime
    sources_discovered: int
    sources_read: int
    sources_unchanged: int
    sources_outside_window: int
    sources_failed: int
    source_records: int
    malformed_records: int
    since_at: datetime | None = None
    until_at: datetime | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "status": self.status,
            "last_ingested_at": format_datetime(self.last_ingested_at),
            "sources": {
                "discovered": self.sources_discovered,
                "read": self.sources_read,
                "unchanged": self.sources_unchanged,
                "outside_window": self.sources_outside_window,
                "failed": self.sources_failed,
            },
            "source_records": self.source_records,
            "malformed_records": self.malformed_records,
            "window": {
                "since": format_datetime(self.since_at) if self.since_at else None,
                "until_exclusive": format_datetime(self.until_at) if self.until_at else None,
            },
        }


@dataclass(frozen=True, slots=True)
class MiltonReport:
    event_count: int
    first_event_at: datetime | None
    last_event_at: datetime | None
    by_kind: dict[str, int]
    adapters: dict[str, AdapterSummary]
    accounting: AccountingProjection
    source_coverage: dict[str, SourceCoverageSummary] = field(default_factory=dict)

    @property
    def total_cost_usd(self) -> Decimal:
        return self.accounting.selected_total_usd

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "event_count": self.event_count,
            "period": {
                "start": format_datetime(self.first_event_at) if self.first_event_at else None,
                "end": format_datetime(self.last_event_at) if self.last_event_at else None,
            },
            "cost_usd": str(self.total_cost_usd),
            "accounting": self.accounting.to_dict(),
            "by_kind": dict(sorted(self.by_kind.items())),
            "adapters": {
                name: summary.to_dict() for name, summary in sorted(self.adapters.items())
            },
            "source_coverage": {
                name: summary.to_dict() for name, summary in sorted(self.source_coverage.items())
            },
        }

    def to_text(self) -> str:
        if self.event_count == 0:
            lines = ["Milton report", "", "No normalized events."]
            if not self.source_coverage:
                lines[-1] += " Coverage: no adapters have been ingested."
            else:
                lines.extend(_source_coverage_lines(self.source_coverage))
            return "\n".join(lines)

        assert self.first_event_at is not None
        assert self.last_event_at is not None
        period = f"{format_datetime(self.first_event_at)} to {format_datetime(self.last_event_at)}"
        lines = [
            "Milton report",
            "",
            f"Period: {period}",
            f"Events: {self.event_count}",
            f"Selected cost observations: ${self.total_cost_usd}",
            "",
            "Sources:",
        ]
        for name, summary in sorted(self.adapters.items()):
            lines.append(f"  {name}: {summary.events} events, ${summary.cost_usd}")
            if summary.gaps:
                gaps = ", ".join(
                    f"{field} ({count})" for field, count in sorted(summary.gaps.items())
                )
                lines.append(f"    coverage gaps: {gaps}")
            else:
                lines.append("    coverage gaps: none declared")
        if self.source_coverage:
            lines.extend(_source_coverage_lines(self.source_coverage))
        return "\n".join(lines)


def build_report(
    events: Iterable[NormalizedEvent],
    *,
    source_coverage: dict[str, SourceCoverageSummary] | None = None,
) -> MiltonReport:
    count = 0
    first: datetime | None = None
    last: datetime | None = None
    by_kind: dict[str, int] = {}
    adapters: dict[str, AdapterSummary] = {}
    cost_events: list[NormalizedEvent] = []

    for event in events:
        count += 1
        first = event.occurred_at if first is None else min(first, event.occurred_at)
        last = event.occurred_at if last is None else max(last, event.occurred_at)
        by_kind[event.kind.value] = by_kind.get(event.kind.value, 0) + 1
        adapter = adapters.setdefault(event.source.adapter, AdapterSummary())
        adapter.events += 1

        for field_name, status in event.coverage.items():
            adapter.coverage[status.value] = adapter.coverage.get(status.value, 0) + 1
            if status in {CoverageStatus.UNAVAILABLE, CoverageStatus.REDACTED}:
                gap = f"{event.kind.value}.{field_name}:{status.value}"
                adapter.gaps[gap] = adapter.gaps.get(gap, 0) + 1

        if event.kind is EventKind.COST:
            payload = event.payload
            if not isinstance(payload, CostPayload):  # defended by NormalizedEvent validation
                continue
            cost_events.append(event)

    accounting = build_accounting(cost_events)
    for event in select_cost_events(cost_events):
        payload = event.payload
        assert isinstance(payload, CostPayload)
        adapter = adapters[event.source.adapter]
        adapter.cost_usd += payload.amount_usd or Decimal(0)
        adapter.input_tokens += payload.input_tokens or 0
        adapter.output_tokens += payload.output_tokens or 0
        adapter.cached_input_tokens += payload.cached_input_tokens or 0
        adapter.cache_write_tokens += payload.cache_write_tokens or 0
        adapter.reasoning_tokens += payload.reasoning_tokens or 0

    return MiltonReport(
        event_count=count,
        first_event_at=first,
        last_event_at=last,
        by_kind=by_kind,
        adapters=adapters,
        accounting=accounting,
        source_coverage=source_coverage or {},
    )


def _source_coverage_lines(
    coverage_by_adapter: dict[str, SourceCoverageSummary],
) -> list[str]:
    lines = ["", "Ingestion coverage:"]
    for name, coverage in sorted(coverage_by_adapter.items()):
        lines.append(
            f"  {name}: {coverage.status}; {coverage.sources_read} read, "
            f"{coverage.sources_unchanged} unchanged, {coverage.sources_failed} failed"
        )
        if coverage.since_at is not None or coverage.until_at is not None:
            lines.append(
                "    window: "
                f"{format_datetime(coverage.since_at) if coverage.since_at else 'unbounded'} "
                "to "
                f"{format_datetime(coverage.until_at) if coverage.until_at else 'unbounded'} "
                "(exclusive)"
            )
    return lines
