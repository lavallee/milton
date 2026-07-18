"""Adapter for Fab's append-only job lifecycle ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from milton.adapters.base import (
    AdapterRecord,
    ContentPolicy,
    ReadStats,
    SourceRead,
    project_from_cwd,
    protected_json,
    string_or_none,
)
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.model import (
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SessionPayload,
    SourceRef,
    parse_datetime,
    stable_id,
)
from milton.relations import (
    RelationKind,
    RelationMethod,
    RelationRecord,
    TypedRef,
)

_TERMINAL_STATUSES = {"succeeded", "failed", "escalated", "cancelled"}
_RECEIPT_SCHEMA = "fab.execution-receipt/v1"


class FabAdapter:
    name = "fab"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.home() / ".local" / "share" / "fab",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            if expanded.is_file():
                candidates = [expanded]
            else:
                candidates = [expanded / "ledger.jsonl"]
                jobs = expanded / "jobs"
                if jobs.is_dir():
                    candidates.extend(jobs.glob("*/receipts/*.json"))
                    candidates.extend(
                        stdout
                        for stdout in jobs.glob("*/attempts/*/stdout")
                        if _supported_receipt(stdout) and not _has_exact_attempt_receipt(stdout)
                    )
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
        if source.parent.name == "receipts" and source.suffix == ".json":
            return _read_execution_receipt(
                source,
                content_policy=content_policy,
                since=since,
            )
        if source.name == "stdout":
            return _read_attempt_receipt(source, since=since)
        stats = ReadStats()
        receipt_coverage = _receipt_coverage(source.parent)

        def records() -> Iterator[AdapterRecord]:
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
                        timestamp = parse_datetime(str(raw["ts"]))
                        event_type = str(raw["event"])
                        job_id = str(raw["job_id"])
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                        stats.malformed_records += 1
                        stats.warn("malformed-ledger-record", str(error), source, line_number)
                        continue

                    if since is not None and timestamp < since:
                        stats.skipped_records += 1
                        continue

                    if event_type == "submitted":
                        if (job_id, "job_submitted") in receipt_coverage:
                            stats.skipped_records += 1
                            continue
                        tags = cast(
                            dict[str, object],
                            raw.get("tags") if isinstance(raw.get("tags"), dict) else {},
                        )
                        launch = cast(
                            dict[str, object],
                            raw.get("launch") if isinstance(raw.get("launch"), dict) else {},
                        )
                        backend = string_or_none(raw.get("backend"))
                        cwd = string_or_none(raw.get("cwd"))
                        project = _selected_string(tags, "work_project", "project")
                        protected_tags, tags_status, tags_metadata = protected_json(
                            tags, content_policy
                        )
                        protected_launch, launch_status, launch_metadata = protected_json(
                            launch, content_policy
                        )
                        session = NormalizedEvent.create(
                            source=SourceRef(self.name, job_id, str(source)),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=SessionPayload(
                                project=project or project_from_cwd(cwd),
                                working_directory=cwd,
                                status="submitted",
                                harness=backend,
                            ),
                            attributes={
                                "intent": string_or_none(raw.get("intent")),
                                "submitter": string_or_none(raw.get("submitter")),
                                "work_item_id": string_or_none(tags.get("work_item_id")),
                                "george_todo": string_or_none(tags.get("george_todo")),
                                "repair_of": string_or_none(tags.get("repair_of")),
                                "tags": protected_tags,
                                "tags_coverage": tags_status.value,
                                "tags_metadata": tags_metadata,
                                "launch": protected_launch,
                                "launch_coverage": launch_status.value,
                                "launch_metadata": launch_metadata,
                            },
                        )
                        stats.emitted_records += 1
                        yield session
                        for crosswalk in _submitted_crosswalks(
                            job_id, tags, session.event_id, timestamp
                        ):
                            stats.emitted_records += 1
                            yield crosswalk
                        continue

                    if event_type in {"attempt_finished", "attempt_finished_post_cancel"}:
                        attempt_index = _integer(raw.get("attempt_idx"))
                        if (
                            attempt_index is not None
                            and (job_id, f"attempt_finished:{attempt_index}") in receipt_coverage
                        ):
                            stats.skipped_records += 1
                            continue
                        outcome = string_or_none(raw.get("outcome"))
                        event = NormalizedEvent.create(
                            source=SourceRef(
                                self.name,
                                f"attempt:{job_id}:{raw.get('attempt_idx')}:{event_type}",
                                str(source),
                            ),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=OutcomePayload(
                                outcome_type="fab.attempt",
                                status=_attempt_status(outcome),
                                reference=job_id,
                            ),
                            session_id=_session_event_id(job_id),
                            attributes={
                                "attempt_index": _integer(raw.get("attempt_idx")),
                                "exit_code": _integer(raw.get("exit_code")),
                                "native_outcome": outcome,
                                "detail": _protected_text(raw.get("detail"), content_policy),
                            },
                        )
                        stats.emitted_records += 1
                        yield event
                        continue

                    terminal_status = string_or_none(raw.get("to"))
                    if event_type == "status_changed" and terminal_status in _TERMINAL_STATUSES:
                        if (job_id, "job_outcome") in receipt_coverage:
                            stats.skipped_records += 1
                            continue
                        event = NormalizedEvent.create(
                            source=SourceRef(
                                self.name,
                                f"terminal:{job_id}:{line_number}",
                                str(source),
                            ),
                            occurred_at=timestamp,
                            recorded_at=timestamp,
                            payload=OutcomePayload(
                                outcome_type="fab.job",
                                status=_terminal_status(terminal_status),
                                reference=job_id,
                            ),
                            session_id=_session_event_id(job_id),
                            attributes={"native_status": terminal_status},
                        )
                        stats.emitted_records += 1
                        yield event
                        continue

                    stats.skipped_records += 1

        return SourceRead(records(), stats)


def _session_event_id(job_id: str) -> str:
    return stable_id("evt", "fab", "session", job_id)


def _submitted_crosswalks(
    job_id: str,
    tags: dict[str, object],
    event_id: str,
    timestamp: datetime,
) -> Iterator[CrosswalkRecord]:
    left = ExternalIdentity("fab.job", job_id)
    # Fab passes the job id as the correlation id to its direct Somm backend
    # and to the shared harness request. Keeping that alias even before a
    # downstream record exists lets a later Somm ingest close the trace.
    identities: set[ExternalIdentity] = {ExternalIdentity("correlation", job_id)}
    for key in ("correlation_id", "session_id"):
        value = string_or_none(tags.get(key))
        if value:
            identities.add(ExternalIdentity("correlation", value))
    repair_of = string_or_none(tags.get("repair_of"))
    if repair_of and repair_of != job_id:
        identities.add(ExternalIdentity("fab.job", repair_of))

    for right in sorted(identities):
        yield CrosswalkRecord.create(
            left=left,
            right=right,
            confidence=1,
            method=JoinMethod.EXPLICIT,
            evidence_event_ids=(event_id,),
            recorded_at=timestamp,
        )


def _attempt_status(outcome: str | None) -> OutcomeStatus:
    if outcome == "succeeded":
        return OutcomeStatus.SUCCEEDED
    if outcome in {"errored", "stuck", "out_of_turns", "agent_blocked"}:
        return OutcomeStatus.FAILED
    return OutcomeStatus.UNKNOWN


def _terminal_status(status: str) -> OutcomeStatus:
    if status == "succeeded":
        return OutcomeStatus.SUCCEEDED
    if status == "cancelled":
        return OutcomeStatus.ABANDONED
    return OutcomeStatus.FAILED


def _selected_string(values: dict[str, object], *names: str) -> str | None:
    return next((value for name in names if (value := string_or_none(values.get(name)))), None)


def _integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _protected_text(value: object, policy: ContentPolicy) -> JsonValue:
    if value is None:
        return None
    protected, _, metadata = protected_json(value, policy)
    return protected if policy is ContentPolicy.FULL else metadata


def _receipt_coverage(root: Path) -> set[tuple[str, str]]:
    coverage: set[tuple[str, str]] = set()
    jobs = root / "jobs"
    if not jobs.is_dir():
        return coverage
    for path in jobs.glob("*/receipts/*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or raw.get("schema") != _RECEIPT_SCHEMA:
            continue
        job_id = string_or_none(raw.get("job_id"))
        kind = string_or_none(raw.get("kind"))
        if job_id is None or kind is None:
            continue
        if kind == "attempt_finished":
            attempt_index = _integer(raw.get("attempt_idx"))
            if attempt_index is not None:
                coverage.add((job_id, f"attempt_finished:{attempt_index}"))
        else:
            coverage.add((job_id, kind))
    return coverage


def _has_exact_attempt_receipt(stdout: Path) -> bool:
    try:
        attempt_index = int(stdout.parent.name)
    except ValueError:
        return False
    receipts = stdout.parents[2] / "receipts"
    return (receipts / f"attempt-{attempt_index}-finished.json").is_file()


def _read_execution_receipt(
    source: Path,
    *,
    content_policy: ContentPolicy,
    since: datetime | None,
) -> SourceRead:
    stats = ReadStats()

    def records() -> Iterator[AdapterRecord]:
        stats.source_records += 1
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("receipt is not an object")
            if raw.get("schema") != _RECEIPT_SCHEMA:
                raise ValueError("unsupported Fab receipt schema")
            receipt = cast(dict[str, object], raw)
            receipt_id = str(receipt["receipt_id"])
            kind = str(receipt["kind"])
            job_id = str(receipt["job_id"])
            timestamp = parse_datetime(str(receipt["occurred_at"]))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            stats.malformed_records += 1
            stats.warn("malformed-execution-receipt", str(error), source)
            return
        if since is not None and timestamp < since:
            stats.skipped_records += 1
            return

        origin = cast(
            dict[str, object],
            receipt.get("origin") if isinstance(receipt.get("origin"), dict) else {},
        )
        attributes: dict[str, JsonValue] = {
            "receipt_id": receipt_id,
            "receipt_kind": kind,
            "attempt_id": string_or_none(receipt.get("attempt_id")),
            "attempt_index": _integer(receipt.get("attempt_idx")),
            "backend": string_or_none(receipt.get("backend")),
            "origin_source": string_or_none(origin.get("source")),
            "origin_entry_id": string_or_none(origin.get("entry_id")),
            "origin_entry_namespace": string_or_none(origin.get("entry_namespace")),
            "commission_revision": string_or_none(origin.get("commission_revision")),
            "commission_fingerprint": string_or_none(origin.get("commission_fingerprint")),
            "thread_id": string_or_none(origin.get("thread_id")),
            "intake_id": string_or_none(origin.get("intake_id")),
            "milton_finding_id": string_or_none(origin.get("milton_finding_id")),
            "milton_revision_id": string_or_none(origin.get("milton_revision_id")),
            "chip_candidate_id": string_or_none(origin.get("chip_candidate_id")),
            "chip_receipt_id": string_or_none(origin.get("chip_receipt_id")),
            "spindle_evaluation_receipt_id": string_or_none(
                origin.get("spindle_evaluation_receipt_id")
            ),
            "spindle_promotion_receipt_id": string_or_none(
                origin.get("spindle_promotion_receipt_id")
            ),
            "evaluation_tuple": _origin_tuple(origin.get("evaluation_tuple")),
            "baseline_tuple": _origin_tuple(origin.get("baseline_tuple")),
        }
        event: NormalizedEvent | None = None
        if kind == "job_submitted":
            event = NormalizedEvent.create(
                source=SourceRef("fab", job_id, str(source)),
                occurred_at=timestamp,
                recorded_at=timestamp,
                payload=SessionPayload(
                    project=None,
                    working_directory=string_or_none(receipt.get("cwd")),
                    status="submitted",
                    harness=string_or_none(receipt.get("backend")),
                ),
                attributes={
                    **attributes,
                    "intent": string_or_none(receipt.get("intent")),
                    "submitter": string_or_none(receipt.get("submitter")),
                },
            )
        elif kind == "attempt_finished":
            attempt_coordinate = string_or_none(receipt.get("attempt_id"))
            outcome = cast(
                dict[str, object],
                receipt.get("outcome") if isinstance(receipt.get("outcome"), dict) else {},
            )
            if attempt_coordinate:
                event = NormalizedEvent.create(
                    source=SourceRef("fab", attempt_coordinate, str(source)),
                    occurred_at=timestamp,
                    recorded_at=timestamp,
                    payload=OutcomePayload(
                        outcome_type="fab.attempt",
                        status=_receipt_outcome_status(outcome.get("status")),
                        reference=job_id,
                    ),
                    session_id=_session_event_id(job_id),
                    attributes={
                        **attributes,
                        "exit_code": _integer(outcome.get("exit_code")),
                        "reason": _protected_text(outcome.get("reason"), content_policy),
                    },
                )
        elif kind in {"job_outcome", "delivery_outcome"}:
            outcome = cast(
                dict[str, object],
                receipt.get("outcome") if isinstance(receipt.get("outcome"), dict) else {},
            )
            event = NormalizedEvent.create(
                source=SourceRef("fab", f"{kind}:{job_id}", str(source)),
                occurred_at=timestamp,
                recorded_at=timestamp,
                payload=OutcomePayload(
                    outcome_type="fab.job",
                    status=_receipt_outcome_status(outcome.get("status")),
                    reference=job_id,
                ),
                session_id=_session_event_id(job_id),
                attributes={
                    **attributes,
                    "semantic": kind == "delivery_outcome",
                    "reason": _protected_text(outcome.get("reason"), content_policy),
                    "reason_tags": _string_list(outcome.get("reason_tags")),
                },
            )
        elif kind == "verifier":
            review = cast(
                dict[str, object],
                receipt.get("review") if isinstance(receipt.get("review"), dict) else {},
            )
            review_id = string_or_none(receipt.get("review_id")) or receipt_id
            protected_review, review_status, review_metadata = protected_json(
                review, content_policy
            )
            event = NormalizedEvent.create(
                source=SourceRef("fab", review_id, str(source)),
                occurred_at=timestamp,
                recorded_at=timestamp,
                payload=OutcomePayload(
                    outcome_type="fab.verifier",
                    status=_receipt_outcome_status(review.get("recommendation")),
                    reference=review_id,
                ),
                session_id=_session_event_id(job_id),
                attributes={
                    **attributes,
                    "review": protected_review,
                    "review_coverage": review_status.value,
                    "review_metadata": review_metadata,
                },
            )
        elif kind == "artifact":
            artifact = cast(
                dict[str, object],
                receipt.get("artifact") if isinstance(receipt.get("artifact"), dict) else {},
            )
            coordinate = cast(
                dict[str, object],
                artifact.get("coordinate") if isinstance(artifact.get("coordinate"), dict) else {},
            )
            namespace = string_or_none(coordinate.get("namespace"))
            value = string_or_none(coordinate.get("value"))
            if namespace and value:
                event = NormalizedEvent.create(
                    source=SourceRef("fab", receipt_id, str(source)),
                    occurred_at=timestamp,
                    recorded_at=timestamp,
                    payload=OutcomePayload(
                        outcome_type=(
                            "git.commit" if namespace == "git.commit" else "fab.artifact"
                        ),
                        status=OutcomeStatus.SUCCEEDED,
                        reference=value,
                    ),
                    session_id=_session_event_id(job_id),
                    attributes={
                        **attributes,
                        "artifact_type": string_or_none(artifact.get("type")),
                        "artifact_namespace": namespace,
                    },
                )

        evidence_id = event.event_id if event is not None else receipt_id
        if event is not None:
            stats.emitted_records += 1
            yield event

        attempt_coordinate = string_or_none(receipt.get("attempt_id"))
        correlation_id = string_or_none(receipt.get("correlation_id"))
        if kind == "attempt_started" and attempt_coordinate and correlation_id:
            stats.emitted_records += 1
            yield CrosswalkRecord.create(
                left=ExternalIdentity("fab.attempt", attempt_coordinate),
                right=ExternalIdentity("correlation", correlation_id),
                confidence=1,
                method=JoinMethod.EXPLICIT,
                evidence_event_ids=(evidence_id,),
                recorded_at=timestamp,
                note="Fab receipt publishes the exact attempt correlation coordinate",
            )

        for relation in _receipt_relations(receipt, evidence_id, timestamp, kind=kind):
            stats.emitted_records += 1
            yield relation

        accounting = cast(
            dict[str, object],
            receipt.get("accounting") if isinstance(receipt.get("accounting"), dict) else {},
        )
        if accounting:
            amount = _decimal_or_none(accounting.get("amount_usd"))
            rollup = NormalizedEvent.create(
                source=SourceRef("fab", f"cost:{receipt_id}", str(source)),
                occurred_at=timestamp,
                recorded_at=timestamp,
                payload=CostPayload(
                    amount_usd=amount,
                    input_tokens=None,
                    output_tokens=None,
                    cached_input_tokens=None,
                    provider=None,
                    model=None,
                    basis=CostBasis.UNKNOWN,
                    kind=CostKind.UNKNOWN,
                    accuracy=CostAccuracy.UNKNOWN,
                    authority="fab",
                    accounting_key=f"fab.receipt={receipt_id}",
                    accounting_key_scope=CostKeyScope.SOURCE,
                    observation_role=CostObservationRole.ROLLUP,
                ),
                session_id=_session_event_id(job_id),
                parent_event_id=(event.event_id if event is not None else None),
                attributes={
                    **attributes,
                    "child_accounting_keys": _string_list(accounting.get("child_accounting_keys")),
                    "counting": bool(accounting.get("counting", False)),
                },
            )
            stats.emitted_records += 1
            yield rollup

    return SourceRead(records(), stats)


def _receipt_relations(
    receipt: dict[str, object],
    evidence_id: str,
    timestamp: datetime,
    *,
    kind: str,
) -> Iterator[RelationRecord]:
    raw_relations = receipt.get("relations")
    if not isinstance(raw_relations, list):
        return
    for raw in raw_relations:
        if not isinstance(raw, dict):
            continue
        subject = raw.get("subject")
        object_ref = raw.get("object")
        if not isinstance(subject, dict) or not isinstance(object_ref, dict):
            continue
        # The started receipt is the canonical attempt→job assertion. Later
        # receipts repeat it for self-containment, but do not create a second
        # relation revision in Milton.
        if raw.get("predicate") == "attempt_of" and kind != "attempt_started":
            continue
        try:
            yield RelationRecord.create(
                subject=TypedRef.from_dict(subject),
                predicate=RelationKind(str(raw["predicate"])),
                object=TypedRef.from_dict(object_ref),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=(evidence_id,),
                recorded_at=timestamp,
                note="Fab producer receipt",
            )
        except (KeyError, TypeError, ValueError):
            continue


def _receipt_outcome_status(value: object) -> OutcomeStatus:
    status = str(value or "").lower()
    if status in {"done", "ok", "pass", "passed", "succeeded", "success"}:
        return OutcomeStatus.SUCCEEDED
    if status in {"cancelled", "parked"}:
        return OutcomeStatus.ABANDONED
    if status in {
        "errored",
        "escalated",
        "fail",
        "failed",
        "needs_review",
        "uncertain",
    }:
        return OutcomeStatus.FAILED
    return OutcomeStatus.UNKNOWN


def _origin_tuple(value: object) -> JsonValue:
    if not isinstance(value, dict):
        return None
    fields = ("implementation", "profile", "model", "harness")
    if any(not isinstance(value.get(field), str) or not value[field] for field in fields):
        return None
    return {field: str(value[field]) for field in fields}


def _string_list(value: object) -> list[JsonValue]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None


def _supported_receipt(stdout: Path) -> bool:
    spec = _receipt_spec(stdout)
    return string_or_none(spec.get("backend")) in {"claude-cli", "codex", "opencode"}


def _receipt_spec(stdout: Path) -> dict[str, object]:
    try:
        raw = json.loads((stdout.parents[2] / "spec.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast(dict[str, object], raw) if isinstance(raw, dict) else {}


def _read_attempt_receipt(source: Path, *, since: datetime | None) -> SourceRead:
    stats = ReadStats()

    def records() -> Iterator[AdapterRecord]:
        spec = _receipt_spec(source)
        job_id = string_or_none(spec.get("id")) or source.parents[2].name
        backend = string_or_none(spec.get("backend"))
        created_at_value = string_or_none(spec.get("created_at"))
        try:
            recorded_at = (
                parse_datetime(created_at_value)
                if created_at_value
                else datetime.fromtimestamp(source.stat().st_mtime, UTC)
            )
            modified_at = datetime.fromtimestamp(source.stat().st_mtime, UTC)
        except (OSError, ValueError) as error:
            stats.warn("receipt-unreadable", str(error), source)
            return
        if since is not None and modified_at < since:
            stats.skipped_records += 1
            return
        if backend not in {"claude-cli", "codex", "opencode"}:
            stats.skipped_records += 1
            return

        session_id: str | None = None
        try:
            handle = source.open(encoding="utf-8", errors="replace")
        except OSError as error:
            stats.warn("receipt-unreadable", str(error), source)
            return
        with handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                stats.source_records += 1
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    stats.malformed_records += 1
                    stats.warn("malformed-receipt-record", "invalid JSON", source, line_number)
                    continue
                if not isinstance(raw, dict):
                    continue
                session_id = _receipt_session_id(backend, raw)
                if session_id:
                    break

        if session_id is None:
            stats.warn("session-id-unavailable", f"no {backend} session id found", source)
            return
        namespace = {
            "claude-cli": "claude-code.session",
            "codex": "codex.session",
            "opencode": "opencode.session",
        }[backend]
        crosswalk = CrosswalkRecord.create(
            left=ExternalIdentity("fab.job", job_id),
            right=ExternalIdentity(namespace, session_id),
            confidence=1,
            method=JoinMethod.EXPLICIT,
            evidence_event_ids=(_session_event_id(job_id),),
            recorded_at=recorded_at,
            note=f"Fab {backend} attempt transcript",
        )
        stats.emitted_records += 1
        yield crosswalk

    return SourceRead(records(), stats)


def _receipt_session_id(backend: str, raw: dict[str, object]) -> str | None:
    if backend == "codex":
        if raw.get("type") == "thread.started":
            return string_or_none(raw.get("thread_id"))
        return None
    if backend == "claude-cli":
        return string_or_none(raw.get("session_id")) or string_or_none(raw.get("conversation_id"))
    direct = string_or_none(raw.get("sessionID")) or string_or_none(raw.get("session_id"))
    part = raw.get("part")
    if direct or not isinstance(part, dict):
        return direct
    return string_or_none(part.get("sessionID")) or string_or_none(part.get("session_id"))
