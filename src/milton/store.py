"""SQLite index for normalized events and identity joins."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from collections import deque
from collections.abc import Iterable, Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from milton.accounting import AccountingProjection, build_accounting
from milton.barnowl_effectiveness import (
    DEFAULT_JOIN_COVERAGE_THRESHOLD,
    BarnowlEffectivenessProjection,
    build_barnowl_effectiveness,
)
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinState
from milton.errors import RecordConflictError, ValidationError
from milton.model import (
    EventKind,
    JsonValue,
    NormalizedEvent,
    canonical_json,
    format_datetime,
    parse_datetime,
)
from milton.outcomes import OutcomeAttributionProjection, build_outcome_attribution
from milton.relations import (
    RelationDirection,
    RelationKind,
    RelationRecord,
    RelationState,
    TypedRef,
)
from milton.report import MiltonReport, SourceCoverageSummary, build_report

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    adapter TEXT NOT NULL,
    native_id TEXT NOT NULL,
    source_location TEXT,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    session_id TEXT,
    parent_event_id TEXT,
    document_json TEXT NOT NULL,
    UNIQUE (adapter, kind, native_id)
);

CREATE INDEX IF NOT EXISTS events_occurred_at_idx ON events (occurred_at);
CREATE INDEX IF NOT EXISTS events_session_id_idx ON events (session_id);
CREATE INDEX IF NOT EXISTS events_parent_event_id_idx ON events (parent_event_id);

CREATE TABLE IF NOT EXISTS crosswalk_records (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    link_id TEXT NOT NULL,
    left_namespace TEXT NOT NULL,
    left_value TEXT NOT NULL,
    right_namespace TEXT NOT NULL,
    right_value TEXT NOT NULL,
    state TEXT NOT NULL,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    supersedes TEXT,
    document_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS crosswalk_link_id_idx ON crosswalk_records (link_id, sequence);
CREATE INDEX IF NOT EXISTS crosswalk_left_idx
    ON crosswalk_records (left_namespace, left_value);
CREATE INDEX IF NOT EXISTS crosswalk_right_idx
    ON crosswalk_records (right_namespace, right_value);

CREATE TABLE IF NOT EXISTS relation_records (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    relation_id TEXT NOT NULL,
    subject_namespace TEXT NOT NULL,
    subject_value TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_namespace TEXT NOT NULL,
    object_value TEXT NOT NULL,
    state TEXT NOT NULL,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    supersedes TEXT,
    document_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS relation_id_idx ON relation_records (relation_id, sequence);
CREATE INDEX IF NOT EXISTS relation_subject_idx
    ON relation_records (subject_namespace, subject_value, predicate);
CREATE INDEX IF NOT EXISTS relation_object_idx
    ON relation_records (object_namespace, object_value, predicate);

CREATE TABLE IF NOT EXISTS adapter_sources (
    adapter TEXT NOT NULL,
    source TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    records_seen INTEGER NOT NULL,
    records_emitted INTEGER NOT NULL,
    diagnostics_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (adapter, source)
);

CREATE TABLE IF NOT EXISTS adapter_runs (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter TEXT NOT NULL,
    status TEXT NOT NULL,
    content_policy TEXT NOT NULL,
    since_at TEXT,
    until_at TEXT,
    sources_discovered INTEGER NOT NULL,
    sources_read INTEGER NOT NULL,
    sources_unchanged INTEGER NOT NULL,
    sources_outside_window INTEGER NOT NULL,
    sources_failed INTEGER NOT NULL,
    source_records INTEGER NOT NULL,
    malformed_records INTEGER NOT NULL,
    events_inserted INTEGER NOT NULL,
    crosswalks_inserted INTEGER NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS adapter_runs_latest_idx
    ON adapter_runs (adapter, sequence DESC);
"""

_REFERENCE_EVENT_MAP: dict[str, tuple[str, EventKind]] = {
    "claude-code.session": ("claude-code", EventKind.SESSION),
    "codex.session": ("codex", EventKind.SESSION),
    "chip.candidate-receipt": ("chip", EventKind.OUTCOME),
    "fab.job": ("fab", EventKind.SESSION),
    "fab.attempt": ("fab", EventKind.OUTCOME),
    "fab.verifier": ("fab", EventKind.OUTCOME),
    "george.entry": ("george", EventKind.OUTCOME),
    "george.disposition": ("george", EventKind.OUTCOME),
    "george.gate-event": ("george", EventKind.GATE_EVIDENCE),
    "george.gate-mint": ("george", EventKind.GATE_EVIDENCE),
    "git.commit-instance": ("git", EventKind.OUTCOME),
    "hermes.session": ("hermes", EventKind.SESSION),
    "opencode.session": ("opencode", EventKind.SESSION),
    "somm.call": ("somm", EventKind.MODEL_CALL),
    "somm.call-update": ("somm", EventKind.OUTCOME),
    "somm.campaign": ("somm", EventKind.OUTCOME),
    "somm.campaign-event": ("somm", EventKind.OUTCOME),
    "somm.decision": ("somm", EventKind.OUTCOME),
    "somm.eval-receipt": ("somm", EventKind.OUTCOME),
    "somm.eval-result": ("somm", EventKind.OUTCOME),
    "spindle.evaluation-receipt": ("spindle", EventKind.OUTCOME),
    "spindle.promotion-receipt": ("spindle", EventKind.OUTCOME),
    "somm.recommendation": ("somm", EventKind.OUTCOME),
    "somm.session": ("somm", EventKind.SESSION),
}


class MiltonStore:
    """Transactional local index; adapters can ingest independently and idempotently."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self._read_snapshot: tempfile.TemporaryDirectory[str] | None = None
        if read_only:
            self._connection = self._open_read_snapshot()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if read_only:
            self._connection.execute("PRAGMA query_only = ON")
            self._validate_schema()
        else:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._initialize()

    def _open_read_snapshot(self) -> sqlite3.Connection:
        """Copy the SQLite state so reads never create source WAL/SHM sidecars."""

        snapshot = tempfile.TemporaryDirectory(prefix="milton-readonly-")
        self._read_snapshot = snapshot
        snapshot_path = Path(snapshot.name) / "events.db"
        try:
            shutil.copyfile(self.path, snapshot_path)
            for suffix in ("-wal", "-shm", "-journal"):
                source_sidecar = Path(f"{self.path}{suffix}")
                if source_sidecar.is_file():
                    shutil.copyfile(source_sidecar, Path(f"{snapshot_path}{suffix}"))
            return sqlite3.connect(snapshot_path)
        except Exception:
            snapshot.cleanup()
            self._read_snapshot = None
            raise

    def _validate_schema(self) -> None:
        try:
            rows = self._connection.execute("SELECT version FROM schema_meta").fetchall()
        except sqlite3.DatabaseError as error:
            raise ValidationError("event store is not an initialized Milton database") from error
        if len(rows) != 1 or rows[0]["version"] != self.SCHEMA_VERSION:
            versions = [row["version"] for row in rows]
            raise ValidationError(f"unsupported store schema versions: {versions}")

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(_SCHEMA)
            rows = self._connection.execute("SELECT version FROM schema_meta").fetchall()
            if not rows:
                self._connection.execute(
                    "INSERT INTO schema_meta (version) VALUES (?)", (self.SCHEMA_VERSION,)
                )
            elif len(rows) != 1 or rows[0]["version"] != self.SCHEMA_VERSION:
                versions = [row["version"] for row in rows]
                raise ValidationError(f"unsupported store schema versions: {versions}")
            adapter_run_columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(adapter_runs)")
            }
            if "until_at" not in adapter_run_columns:
                self._connection.execute("ALTER TABLE adapter_runs ADD COLUMN until_at TEXT")

    def close(self) -> None:
        try:
            self._connection.close()
        finally:
            if self._read_snapshot is not None:
                self._read_snapshot.cleanup()
                self._read_snapshot = None

    def __enter__(self) -> MiltonStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append_event(self, event: NormalizedEvent) -> bool:
        """Append an event, returning false for an exact idempotent replay."""

        document = canonical_json(event.to_dict())
        with self._connection:
            existing = self._connection.execute(
                "SELECT document_json FROM events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if existing is not None:
                if existing["document_json"] == document:
                    return False
                raise RecordConflictError(f"event {event.event_id} has conflicting content")
            try:
                self._connection.execute(
                    """
                    INSERT INTO events (
                        event_id, kind, adapter, native_id, source_location,
                        occurred_at, recorded_at, session_id, parent_event_id, document_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.kind.value,
                        event.source.adapter,
                        event.source.native_id,
                        event.source.location,
                        format_datetime(event.occurred_at),
                        format_datetime(event.recorded_at),
                        event.session_id,
                        event.parent_event_id,
                        document,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise RecordConflictError(
                    f"native identity {event.source.adapter}/{event.kind.value}/"
                    f"{event.source.native_id} already has different content"
                ) from error
        return True

    def append_events(self, events: Iterable[NormalizedEvent]) -> tuple[int, int]:
        inserted = 0
        replayed = 0
        for event in events:
            if self.append_event(event):
                inserted += 1
            else:
                replayed += 1
        return inserted, replayed

    def events(
        self,
        *,
        adapter: str | None = None,
        session_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> Iterator[NormalizedEvent]:
        clauses: list[str] = []
        parameters: list[str] = []
        if adapter is not None:
            clauses.append("adapter = ?")
            parameters.append(adapter)
        if session_id is not None:
            clauses.append("session_id = ?")
            parameters.append(session_id)
        if since is not None:
            clauses.append("occurred_at >= ?")
            parameters.append(since)
        if until is not None:
            clauses.append("occurred_at < ?")
            parameters.append(until)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = self._connection.execute(
            f"SELECT document_json FROM events{where} ORDER BY occurred_at, event_id",  # noqa: S608
            parameters,
        )
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                raise ValidationError("stored event must be a JSON object")
            yield NormalizedEvent.from_dict(raw)

    def get_event(self, event_id: str) -> NormalizedEvent | None:
        row = self._connection.execute(
            "SELECT document_json FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        raw: dict[str, Any] = json.loads(row["document_json"])
        return NormalizedEvent.from_dict(raw)

    def event_by_native(
        self,
        *,
        adapter: str,
        kind: str,
        native_id: str,
    ) -> NormalizedEvent | None:
        row = self._connection.execute(
            """
            SELECT document_json FROM events
            WHERE adapter = ? AND kind = ? AND native_id = ?
            """,
            (adapter, kind, native_id),
        ).fetchone()
        if row is None:
            return None
        raw: dict[str, Any] = json.loads(row["document_json"])
        return NormalizedEvent.from_dict(raw)

    def event_for_ref(self, reference: TypedRef) -> NormalizedEvent | None:
        """Resolve a typed reference to an exact normalized receipt event."""

        if reference.namespace == "milton.event":
            return self.get_event(reference.value)
        mapping = _REFERENCE_EVENT_MAP.get(reference.namespace)
        if mapping is None:
            return None
        adapter, kind = mapping
        return self.event_by_native(
            adapter=adapter,
            kind=kind.value,
            native_id=reference.value,
        )

    @staticmethod
    def adapter_for_ref(reference: TypedRef) -> str | None:
        if reference.namespace == "milton.event":
            return None
        mapping = _REFERENCE_EVENT_MAP.get(reference.namespace)
        return mapping[0] if mapping is not None else None

    def event_family(self, seed_event_ids: Iterable[str]) -> tuple[NormalizedEvent, ...]:
        """Return seed events plus their session/parent ancestry and descendants."""

        pending = deque(seed_event_ids)
        queued = set(pending)
        events: dict[str, NormalizedEvent] = {}
        while pending:
            event_id = pending.popleft()
            event = self.get_event(event_id)
            if event is not None and event.event_id not in events:
                events[event.event_id] = event
                for parent_id in (event.session_id, event.parent_event_id):
                    if parent_id and parent_id not in queued:
                        queued.add(parent_id)
                        pending.append(parent_id)

            cursor = self._connection.execute(
                """
                SELECT document_json FROM events
                WHERE session_id = ? OR parent_event_id = ?
                """,
                (event_id, event_id),
            )
            for row in cursor:
                raw: dict[str, Any] = json.loads(row["document_json"])
                child = NormalizedEvent.from_dict(raw)
                if child.event_id not in queued:
                    queued.add(child.event_id)
                    pending.append(child.event_id)
        return tuple(sorted(events.values(), key=lambda item: (item.occurred_at, item.event_id)))

    def report(self, *, since: str | None = None, until: str | None = None) -> MiltonReport:
        return build_report(
            self.events(since=since, until=until),
            source_coverage=self.source_coverage(),
        )

    def accounting(
        self, *, since: str | None = None, until: str | None = None
    ) -> AccountingProjection:
        return build_accounting(self.events(since=since, until=until))

    def outcome_attribution(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        outcome_types: Iterable[str] | None = None,
    ) -> OutcomeAttributionProjection:
        """Reconcile accounting-selected costs to current exact outcome paths."""

        window_events = tuple(self.events(since=since, until=until))
        cost_event_ids = {event.event_id for event in window_events if event.kind is EventKind.COST}
        coverage: dict[str, JsonValue] = {
            name: summary.to_dict() for name, summary in sorted(self.source_coverage().items())
        }
        return build_outcome_attribution(
            tuple(self.events()),
            self.current_crosswalks(),
            self.current_relations(),
            cost_event_ids=cost_event_ids,
            outcome_types=outcome_types,
            source_coverage=coverage,
        )

    def barnowl_effectiveness(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        join_coverage_threshold: Decimal = DEFAULT_JOIN_COVERAGE_THRESHOLD,
    ) -> BarnowlEffectivenessProjection:
        """Project aggregate Barnowl effectiveness without scanning or mutating sources."""

        return build_barnowl_effectiveness(
            self.events(),
            self.crosswalk_records(),
            self.relation_records(),
            since=since,
            until=until,
            join_coverage_threshold=join_coverage_threshold,
        )

    def source_coverage(self) -> dict[str, SourceCoverageSummary]:
        cursor = self._connection.execute(
            """
            WITH latest AS (
                SELECT adapter, MAX(sequence) AS sequence
                FROM adapter_runs
                GROUP BY adapter
            )
            SELECT runs.*
            FROM adapter_runs runs
            JOIN latest ON latest.sequence = runs.sequence
            ORDER BY runs.adapter
            """
        )
        return {
            str(row["adapter"]): SourceCoverageSummary(
                status=str(row["status"]),
                last_ingested_at=parse_datetime(str(row["ingested_at"])),
                sources_discovered=int(row["sources_discovered"]),
                sources_read=int(row["sources_read"]),
                sources_unchanged=int(row["sources_unchanged"]),
                sources_outside_window=int(row["sources_outside_window"]),
                sources_failed=int(row["sources_failed"]),
                source_records=int(row["source_records"]),
                malformed_records=int(row["malformed_records"]),
                since_at=(
                    parse_datetime(str(row["since_at"])) if row["since_at"] is not None else None
                ),
                until_at=(
                    parse_datetime(str(row["until_at"])) if row["until_at"] is not None else None
                ),
            )
            for row in cursor
        }

    def record_adapter_run(
        self,
        *,
        adapter: str,
        status: str,
        content_policy: str,
        since_at: str | None,
        sources_discovered: int,
        sources_read: int,
        sources_unchanged: int,
        sources_outside_window: int,
        sources_failed: int,
        source_records: int,
        malformed_records: int,
        events_inserted: int,
        crosswalks_inserted: int,
        ingested_at: str,
        until_at: str | None = None,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO adapter_runs (
                    adapter, status, content_policy, since_at, until_at,
                    sources_discovered, sources_read, sources_unchanged,
                    sources_outside_window, sources_failed, source_records,
                    malformed_records, events_inserted, crosswalks_inserted,
                    ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    adapter,
                    status,
                    content_policy,
                    since_at,
                    until_at,
                    sources_discovered,
                    sources_read,
                    sources_unchanged,
                    sources_outside_window,
                    sources_failed,
                    source_records,
                    malformed_records,
                    events_inserted,
                    crosswalks_inserted,
                    ingested_at,
                ),
            )

    def source_fingerprint(self, adapter: str, source: str) -> str | None:
        row = self._connection.execute(
            """
            SELECT fingerprint FROM adapter_sources
            WHERE adapter = ? AND source = ? AND status = 'ok'
            """,
            (adapter, source),
        ).fetchone()
        return str(row["fingerprint"]) if row is not None else None

    def record_source(
        self,
        *,
        adapter: str,
        source: str,
        fingerprint: str,
        status: str,
        records_seen: int,
        records_emitted: int,
        diagnostics: list[dict[str, Any]],
        ingested_at: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO adapter_sources (
                    adapter, source, fingerprint, status, records_seen,
                    records_emitted, diagnostics_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(adapter, source) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    status = excluded.status,
                    records_seen = excluded.records_seen,
                    records_emitted = excluded.records_emitted,
                    diagnostics_json = excluded.diagnostics_json,
                    ingested_at = excluded.ingested_at
                """,
                (
                    adapter,
                    source,
                    fingerprint,
                    status,
                    records_seen,
                    records_emitted,
                    json.dumps(diagnostics, separators=(",", ":"), sort_keys=True),
                    ingested_at,
                ),
            )

    def append_crosswalk(self, record: CrosswalkRecord) -> bool:
        """Append one join revision, enforcing a linear and inspectable history."""

        document = canonical_json(record.to_dict())
        with self._connection:
            existing = self._connection.execute(
                "SELECT document_json FROM crosswalk_records WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
            if existing is not None:
                if existing["document_json"] == document:
                    return False
                raise RecordConflictError(
                    f"crosswalk record {record.record_id} has conflicting content"
                )

            current = self._connection.execute(
                """
                SELECT record_id FROM crosswalk_records
                WHERE link_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (record.link_id,),
            ).fetchone()
            if current is None and record.supersedes is not None:
                raise ValidationError("the first crosswalk record cannot supersede another record")
            if current is not None and record.supersedes != current["record_id"]:
                raise ValidationError(
                    f"crosswalk revision must supersede current record {current['record_id']}"
                )

            self._connection.execute(
                """
                INSERT INTO crosswalk_records (
                    record_id, link_id, left_namespace, left_value,
                    right_namespace, right_value, state, confidence,
                    method, recorded_at, supersedes, document_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.link_id,
                    record.left.namespace,
                    record.left.value,
                    record.right.namespace,
                    record.right.value,
                    record.state.value,
                    record.confidence,
                    record.method.value,
                    format_datetime(record.recorded_at),
                    record.supersedes,
                    document,
                ),
            )
        return True

    def crosswalk_history(self, link_id: str) -> Iterator[CrosswalkRecord]:
        cursor = self._connection.execute(
            """
            SELECT document_json FROM crosswalk_records
            WHERE link_id = ? ORDER BY sequence
            """,
            (link_id,),
        )
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                raise ValidationError("stored crosswalk record must be a JSON object")
            yield CrosswalkRecord.from_dict(raw)

    def crosswalk_records(self) -> tuple[CrosswalkRecord, ...]:
        """Return immutable crosswalk revisions in append order."""

        cursor = self._connection.execute(
            "SELECT document_json FROM crosswalk_records ORDER BY sequence"
        )
        records: list[CrosswalkRecord] = []
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                raise ValidationError("stored crosswalk record must be a JSON object")
            records.append(CrosswalkRecord.from_dict(raw))
        return tuple(records)

    def append_relation(self, record: RelationRecord) -> bool:
        """Append relation evidence, allowing corroboration before terminal refutation."""

        document = canonical_json(record.to_dict())
        with self._connection:
            existing = self._connection.execute(
                "SELECT document_json FROM relation_records WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
            if existing is not None:
                if existing["document_json"] == document:
                    return False
                raise RecordConflictError(
                    f"relation record {record.record_id} has conflicting content"
                )

            current_row = self._connection.execute(
                """
                SELECT document_json FROM relation_records
                WHERE relation_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (record.relation_id,),
            ).fetchone()
            if current_row is None:
                if record.state is not RelationState.ASSERTED or record.supersedes is not None:
                    raise ValidationError("the first relation revision must be an assertion")
            else:
                raw = json.loads(current_row["document_json"])
                if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                    raise ValidationError("stored relation record must be a JSON object")
                current = RelationRecord.from_dict(raw)
                if current.state is RelationState.REFUTED:
                    raise ValidationError("a refuted relation has a closed history")
                if record.state is RelationState.ASSERTED:
                    prior_rows = self._connection.execute(
                        """
                        SELECT document_json FROM relation_records
                        WHERE relation_id = ? AND state = ?
                        """,
                        (record.relation_id, RelationState.ASSERTED.value),
                    )
                    prior_evidence: set[str] = set()
                    for prior_row in prior_rows:
                        prior_raw = json.loads(prior_row["document_json"])
                        if not isinstance(prior_raw, dict):  # pragma: no cover
                            raise ValidationError("stored relation record must be a JSON object")
                        prior_evidence.update(
                            RelationRecord.from_dict(prior_raw).evidence_event_ids
                        )
                    if not set(record.evidence_event_ids) - prior_evidence:
                        raise ValidationError(
                            "a corroborating relation assertion requires new evidence"
                        )
                else:
                    if record.supersedes != current.record_id:
                        raise ValidationError(
                            f"relation revision must supersede current record {current.record_id}"
                        )
                    latest_assertion_at = max(
                        item.recorded_at
                        for item in self.relation_history(record.relation_id)
                        if item.state is RelationState.ASSERTED
                    )
                    if record.recorded_at <= latest_assertion_at:
                        raise ValidationError("relation revisions must move forward in time")

            self._connection.execute(
                """
                INSERT INTO relation_records (
                    record_id, relation_id, subject_namespace, subject_value,
                    predicate, object_namespace, object_value, state, confidence,
                    method, recorded_at, supersedes, document_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.relation_id,
                    record.subject.namespace,
                    record.subject.value,
                    record.predicate.value,
                    record.object.namespace,
                    record.object.value,
                    record.state.value,
                    record.confidence,
                    record.method.value,
                    format_datetime(record.recorded_at),
                    record.supersedes,
                    document,
                ),
            )
        return True

    def relation_history(self, relation_id: str) -> Iterator[RelationRecord]:
        cursor = self._connection.execute(
            """
            SELECT document_json FROM relation_records
            WHERE relation_id = ? ORDER BY sequence
            """,
            (relation_id,),
        )
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                raise ValidationError("stored relation record must be a JSON object")
            yield RelationRecord.from_dict(raw)

    def relation_records(
        self,
        *,
        subject: TypedRef | None = None,
        object: TypedRef | None = None,
        predicates: Iterable[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        """Return immutable relation revisions, including explicit refutations."""

        selected_predicates = set(predicates) if predicates is not None else None
        cursor = self._connection.execute(
            "SELECT document_json FROM relation_records ORDER BY sequence"
        )
        records: list[RelationRecord] = []
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                raise ValidationError("stored relation record must be a JSON object")
            record = RelationRecord.from_dict(raw)
            if subject is not None and record.subject != subject:
                continue
            if object is not None and record.object != object:
                continue
            if selected_predicates is not None and record.predicate not in selected_predicates:
                continue
            records.append(record)
        return tuple(records)

    def current_relations(
        self,
        references: Iterable[TypedRef] | None = None,
        *,
        predicates: Iterable[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        """Return current asserted relations, optionally touching selected refs."""

        selected = set(references) if references is not None else None
        selected_predicates = set(predicates) if predicates is not None else None
        cursor = self._connection.execute(
            """
            WITH latest AS (
                SELECT relation_id, MAX(sequence) AS sequence
                FROM relation_records
                GROUP BY relation_id
            )
            SELECT r.document_json
            FROM relation_records r
            JOIN latest ON latest.sequence = r.sequence
            WHERE r.state = ?
            ORDER BY r.subject_namespace, r.subject_value, r.predicate,
                     r.object_namespace, r.object_value
            """,
            (RelationState.ASSERTED.value,),
        )
        records: list[RelationRecord] = []
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                raise ValidationError("stored relation record must be a JSON object")
            record = RelationRecord.from_dict(raw)
            if (
                selected is not None
                and record.subject not in selected
                and record.object not in selected
            ):
                continue
            if selected_predicates is not None and record.predicate not in selected_predicates:
                continue
            records.append(record)
        return tuple(records)

    def outgoing_relations(
        self,
        subject: TypedRef,
        *,
        predicates: Iterable[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        return tuple(
            record
            for record in self.current_relations((subject,), predicates=predicates)
            if record.subject == subject
        )

    def incoming_relations(
        self,
        object: TypedRef,
        *,
        predicates: Iterable[RelationKind] | None = None,
    ) -> tuple[RelationRecord, ...]:
        return tuple(
            record
            for record in self.current_relations((object,), predicates=predicates)
            if record.object == object
        )

    def traverse_relations(
        self,
        root: TypedRef,
        *,
        direction: RelationDirection = RelationDirection.BOTH,
        max_depth: int = 4,
        predicates: Iterable[RelationKind] | None = None,
    ) -> tuple[tuple[TypedRef, ...], tuple[RelationRecord, ...]]:
        """Traverse current relations while preserving edge direction in output."""

        if max_depth < 0:
            raise ValidationError("max_depth must not be negative")
        predicate_filter = tuple(predicates) if predicates is not None else None
        seen = {root}
        frontier = {root}
        traversed: dict[str, RelationRecord] = {}
        for _ in range(max_depth):
            next_frontier: set[TypedRef] = set()
            for reference in sorted(frontier):
                records: list[RelationRecord] = []
                if direction in (RelationDirection.OUTGOING, RelationDirection.BOTH):
                    records.extend(self.outgoing_relations(reference, predicates=predicate_filter))
                if direction in (RelationDirection.INCOMING, RelationDirection.BOTH):
                    records.extend(self.incoming_relations(reference, predicates=predicate_filter))
                for record in records:
                    traversed[record.relation_id] = record
                    neighbor = record.object if record.subject == reference else record.subject
                    if neighbor not in seen:
                        seen.add(neighbor)
                        next_frontier.add(neighbor)
            if not next_frontier:
                break
            frontier = next_frontier
        traversal_records = tuple(traversed.values())
        return tuple(sorted(seen)), traversal_records

    def connected_work_refs(
        self,
        root: TypedRef,
        *,
        max_depth: int = 4,
    ) -> tuple[TypedRef, ...]:
        """Traverse identity associations and relations as distinct graph edges."""

        if max_depth < 0:
            raise ValidationError("max_depth must not be negative")
        seen = {root}
        frontier = {root}
        for _ in range(max_depth):
            next_frontier: set[TypedRef] = set()
            for reference in sorted(frontier):
                identity = reference.to_identity()
                neighbors = {
                    TypedRef.from_identity(item) for item in self._crosswalk_neighbors(identity)
                }
                neighbors.update(record.object for record in self.outgoing_relations(reference))
                neighbors.update(record.subject for record in self.incoming_relations(reference))
                for neighbor in neighbors:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        next_frontier.add(neighbor)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(sorted(seen))

    def connected_identities(
        self,
        root: ExternalIdentity,
        *,
        max_depth: int = 4,
    ) -> tuple[ExternalIdentity, ...]:
        """Traverse currently asserted crosswalk links from one native identity."""

        if max_depth < 0:
            raise ValidationError("max_depth must not be negative")
        seen = {root}
        frontier = {root}
        for _ in range(max_depth):
            next_frontier: set[ExternalIdentity] = set()
            for identity in frontier:
                for neighbor in self._crosswalk_neighbors(identity):
                    if neighbor not in seen:
                        seen.add(neighbor)
                        next_frontier.add(neighbor)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(sorted(seen))

    def current_crosswalks(
        self, identities: Iterable[ExternalIdentity] | None = None
    ) -> tuple[CrosswalkRecord, ...]:
        """Return current asserted links, optionally touching an identity set."""

        selected = set(identities) if identities is not None else None
        cursor = self._connection.execute(
            """
            WITH latest AS (
                SELECT link_id, MAX(sequence) AS sequence
                FROM crosswalk_records
                GROUP BY link_id
            )
            SELECT r.document_json
            FROM crosswalk_records r
            JOIN latest ON latest.sequence = r.sequence
            WHERE r.state = ?
            ORDER BY r.left_namespace, r.left_value, r.right_namespace, r.right_value
            """,
            (JoinState.ASSERTED.value,),
        )
        records: list[CrosswalkRecord] = []
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                continue
            record = CrosswalkRecord.from_dict(raw)
            if selected is None or record.left in selected or record.right in selected:
                records.append(record)
        return tuple(records)

    def _crosswalk_neighbors(self, identity: ExternalIdentity) -> Iterator[ExternalIdentity]:
        cursor = self._connection.execute(
            """
            WITH latest AS (
                SELECT link_id, MAX(sequence) AS sequence
                FROM crosswalk_records
                GROUP BY link_id
            )
            SELECT r.document_json
            FROM crosswalk_records r
            JOIN latest ON latest.sequence = r.sequence
            WHERE r.state = ? AND (
                (r.left_namespace = ? AND r.left_value = ?) OR
                (r.right_namespace = ? AND r.right_value = ?)
            )
            """,
            (
                JoinState.ASSERTED.value,
                identity.namespace,
                identity.value,
                identity.namespace,
                identity.value,
            ),
        )
        for row in cursor:
            raw = json.loads(row["document_json"])
            if not isinstance(raw, dict):  # pragma: no cover - protected by append path
                continue
            record = CrosswalkRecord.from_dict(raw)
            yield record.right if record.left == identity else record.left
