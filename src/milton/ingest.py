"""Incremental, fail-open orchestration across heterogeneous adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

from milton.adapters.base import ContentPolicy, SourceAdapter
from milton.crosswalk import CrosswalkRecord
from milton.model import JsonValue, NormalizedEvent, canonical_json, format_datetime, utc_now
from milton.relations import RelationRecord
from milton.store import MiltonStore


@dataclass(slots=True)
class AdapterIngestSummary:
    adapter: str
    sources_discovered: int = 0
    sources_read: int = 0
    sources_unchanged: int = 0
    sources_outside_window: int = 0
    records_outside_window: int = 0
    sources_failed: int = 0
    source_records: int = 0
    malformed_records: int = 0
    events_inserted: int = 0
    crosswalks_inserted: int = 0
    relations_inserted: int = 0
    replayed: int = 0
    diagnostics: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IngestSummary:
    adapters: tuple[AdapterIngestSummary, ...]

    @property
    def failed(self) -> bool:
        return any(item.sources_failed for item in self.adapters)

    def to_dict(self) -> dict[str, object]:
        return {"adapters": [item.to_dict() for item in self.adapters]}

    def to_text(self) -> str:
        lines = ["Milton ingestion"]
        for item in self.adapters:
            lines.extend(
                [
                    "",
                    f"{item.adapter}: {item.events_inserted} events, "
                    f"{item.crosswalks_inserted} joins, "
                    f"{item.relations_inserted} relations",
                    f"  sources: {item.sources_read} read, "
                    f"{item.sources_unchanged} unchanged, "
                    f"{item.sources_outside_window} outside window, "
                    f"{item.sources_failed} failed",
                    f"  records: {item.source_records} read, "
                    f"{item.malformed_records} malformed, {item.replayed} replayed",
                    f"  window: {item.records_outside_window} records at/after exclusive end",
                ]
            )
            for diagnostic in item.diagnostics[:10]:
                location = diagnostic.get("source", "")
                if diagnostic.get("line"):
                    location = f"{location}:{diagnostic['line']}"
                lines.append(
                    f"  {diagnostic.get('level', 'warning')}: "
                    f"{diagnostic.get('code', 'adapter')}: "
                    f"{diagnostic.get('message', '')} [{location}]"
                )
            remaining = len(item.diagnostics) - 10
            if remaining > 0:
                lines.append(f"  ... {remaining} more diagnostics")
        return "\n".join(lines)


class Ingestor:
    def __init__(self, store: MiltonStore) -> None:
        self.store = store

    def run(
        self,
        adapters: Sequence[SourceAdapter],
        *,
        roots: Mapping[str, Sequence[Path]] | None = None,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
        force: bool = False,
    ) -> IngestSummary:
        root_overrides = roots or {}
        summaries: list[AdapterIngestSummary] = []
        for adapter in adapters:
            summary = AdapterIngestSummary(adapter.name)
            summaries.append(summary)
            adapter_roots = tuple(root_overrides.get(adapter.name, adapter.default_roots()))
            for source in adapter.discover(adapter_roots):
                summary.sources_discovered += 1
                if since is not None and _file_predates(source, since):
                    summary.sources_outside_window += 1
                    continue
                source_key = str(source.resolve())
                try:
                    adapter_fingerprint = getattr(adapter, "fingerprint", None)
                    source_state = (
                        adapter_fingerprint(source)
                        if callable(adapter_fingerprint)
                        else source_fingerprint(source)
                    )
                except Exception as error:
                    summary.sources_failed += 1
                    summary.diagnostics.append(
                        {
                            "level": "error",
                            "code": "source-fingerprint-failed",
                            "message": str(error),
                            "source": str(source),
                            "line": None,
                        }
                    )
                    continue
                fingerprint = canonical_json(
                    cast(
                        JsonValue,
                        {
                            "source": source_state,
                            "content_policy": content_policy.value,
                            "since": format_datetime(since) if since else None,
                            "until": format_datetime(until) if until else None,
                        },
                    )
                )
                if (
                    not force
                    and self.store.source_fingerprint(adapter.name, source_key) == fingerprint
                ):
                    summary.sources_unchanged += 1
                    continue

                read = adapter.read(
                    source,
                    content_policy=content_policy,
                    since=since,
                    until=until,
                )
                source_failed = False
                try:
                    for record in read.records:
                        record_time = (
                            record.occurred_at
                            if isinstance(record, NormalizedEvent)
                            else record.recorded_at
                        )
                        if until is not None and record_time >= until:
                            summary.records_outside_window += 1
                            continue
                        if isinstance(record, NormalizedEvent):
                            inserted = self.store.append_event(record)
                            summary.events_inserted += int(inserted)
                        elif isinstance(record, CrosswalkRecord):
                            inserted = self.store.append_crosswalk(record)
                            summary.crosswalks_inserted += int(inserted)
                        elif isinstance(record, RelationRecord):
                            inserted = self.store.append_relation(record)
                            summary.relations_inserted += int(inserted)
                        else:  # pragma: no cover - protocol boundary defense
                            raise TypeError(f"unsupported adapter record: {type(record)!r}")
                        summary.replayed += int(not inserted)
                except Exception as error:
                    source_failed = True
                    summary.sources_failed += 1
                    summary.diagnostics.append(
                        {
                            "level": "error",
                            "code": "source-failed",
                            "message": str(error),
                            "source": source_key,
                            "line": None,
                        }
                    )
                else:
                    summary.sources_read += 1

                diagnostics = [asdict(item) for item in read.stats.diagnostics]
                summary.diagnostics.extend(diagnostics)
                summary.source_records += read.stats.source_records
                summary.malformed_records += read.stats.malformed_records
                self.store.record_source(
                    adapter=adapter.name,
                    source=source_key,
                    fingerprint=fingerprint,
                    status="error" if source_failed else "ok",
                    records_seen=read.stats.source_records,
                    records_emitted=read.stats.emitted_records,
                    diagnostics=diagnostics,
                    ingested_at=format_datetime(utc_now()),
                )
            self.store.record_adapter_run(
                adapter=adapter.name,
                status=(
                    "error"
                    if summary.sources_failed
                    else ("empty" if summary.sources_discovered == 0 else "ok")
                ),
                content_policy=content_policy.value,
                since_at=format_datetime(since) if since else None,
                until_at=format_datetime(until) if until else None,
                sources_discovered=summary.sources_discovered,
                sources_read=summary.sources_read,
                sources_unchanged=summary.sources_unchanged,
                sources_outside_window=summary.sources_outside_window,
                sources_failed=summary.sources_failed,
                source_records=summary.source_records,
                malformed_records=summary.malformed_records,
                events_inserted=summary.events_inserted,
                crosswalks_inserted=summary.crosswalks_inserted,
                ingested_at=format_datetime(utc_now()),
            )
        return IngestSummary(tuple(summaries))


def source_fingerprint(path: Path) -> str:
    """Fingerprint a file/dir plus an SQLite WAL when present."""

    parts: list[dict[str, int | str]] = []
    for candidate in (path, Path(f"{path}-wal")):
        try:
            stat = candidate.stat()
        except OSError:
            continue
        parts.append(
            {
                "name": candidate.name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return canonical_json(cast(JsonValue, parts))


def _file_predates(path: Path, since: datetime) -> bool:
    if path.suffix.lower() not in {".jsonl", ".ndjson"}:
        return False
    try:
        return path.stat().st_mtime < since.timestamp()
    except OSError:
        return False
