"""Adapter for Somm's authoritative SQLite call ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from milton.adapters._sqlite import connect_readonly, table_columns
from milton.adapters.base import (
    AdapterRecord,
    ContentPolicy,
    ReadStats,
    SourceRead,
    string_or_none,
)
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.model import (
    CallStatus,
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    JsonValue,
    ModelCallPayload,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SessionPayload,
    SourceRef,
    format_datetime,
    parse_datetime,
    stable_id,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef

_REQUIRED_CALL_COLUMNS = {
    "id",
    "ts",
    "project",
    "provider",
    "model",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "outcome",
}


class SommAdapter:
    name = "somm"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.home() / ".somm" / "global.sqlite",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            if expanded.is_file():
                candidates = [expanded]
            elif (expanded / "global.sqlite").is_file():
                candidates = [expanded / "global.sqlite"]
            else:
                candidates = [
                    candidate
                    for candidate in expanded.glob("*.sqlite")
                    if "backup" not in candidate.name
                ]
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved not in seen:
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
        del content_policy  # Somm's calls table contains hashes, not transcript bodies.
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            try:
                connection = connect_readonly(source)
            except sqlite3.Error as error:
                stats.warn("source-unreadable", str(error), source)
                return
            with closing(connection):
                columns = table_columns(connection, "calls")
                missing = sorted(_REQUIRED_CALL_COLUMNS.difference(columns))
                if missing:
                    stats.warn(
                        "unsupported-schema",
                        f"calls table is missing columns: {missing}",
                        source,
                    )
                    return
                optional = {
                    name: name if name in columns else f"NULL AS {name}"
                    for name in (
                        "workload_id",
                        "prompt_id",
                        "latency_ms",
                        "error_kind",
                        "error_detail",
                        "prompt_hash",
                        "response_hash",
                        "correlation_id",
                        "ttft_ms",
                        "session_id",
                        "parent_call_id",
                        "cache_tokens_in",
                        "cache_tokens_out",
                        "cost_basis",
                        "cost_kind",
                        "cost_accuracy",
                        "cost_source",
                        "pricing_version",
                        "observation_role",
                        "source_call_id",
                        "eval_result_id",
                        "provider_request_id",
                        "billing_id",
                        "origin",
                        "budget_eligible",
                    )
                }
                selected = ", ".join(optional.values())
                query = f"""
                    SELECT id, ts, project, provider, model, tokens_in, tokens_out,
                           cost_usd, outcome, {selected}
                    FROM calls
                    WHERE (? IS NULL OR datetime(ts) >= datetime(?))
                      AND (? IS NULL OR datetime(ts) < datetime(?))
                    ORDER BY ts, id
                """  # noqa: S608 -- column names come from the fixed allowlist above
                since_text = format_datetime(since) if since else None
                until_text = format_datetime(until) if until else None
                seen_sessions: set[str] = set()
                try:
                    cursor = connection.execute(
                        query,
                        (since_text, since_text, until_text, until_text),
                    )
                    for row in cursor:
                        stats.source_records += 1
                        try:
                            timestamp = parse_datetime(str(row["ts"]))
                            call_id = str(row["id"])
                            project = str(row["project"])
                            provider = str(row["provider"])
                            model = str(row["model"])
                            session_native_id = string_or_none(row["session_id"])
                            session_event_id: str | None = None

                            if session_native_id:
                                session_event_id = stable_id(
                                    "evt", self.name, "session", session_native_id
                                )
                                if session_native_id not in seen_sessions:
                                    seen_sessions.add(session_native_id)
                                    session = NormalizedEvent.create(
                                        source=SourceRef(
                                            self.name,
                                            session_native_id,
                                            str(source),
                                        ),
                                        occurred_at=timestamp,
                                        recorded_at=timestamp,
                                        payload=SessionPayload(
                                            project=project,
                                            working_directory=None,
                                            status=None,
                                            harness="somm",
                                        ),
                                    )
                                    stats.emitted_records += 1
                                    yield session

                            outcome = str(row["outcome"])
                            succeeded = outcome.lower() in {"ok", "success", "succeeded"}
                            model_call = NormalizedEvent.create(
                                source=SourceRef(self.name, call_id, str(source)),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=ModelCallPayload(
                                    provider=provider,
                                    model=model,
                                    status=CallStatus.SUCCEEDED if succeeded else CallStatus.FAILED,
                                    finish_reason=outcome,
                                ),
                                session_id=session_event_id,
                                parent_event_id=_parent_event_id(row["parent_call_id"]),
                                attributes={
                                    "project": project,
                                    "workload_id": string_or_none(row["workload_id"]),
                                    "prompt_id": string_or_none(row["prompt_id"]),
                                    "latency_ms": _integer(row["latency_ms"]),
                                    "ttft_ms": _integer(row["ttft_ms"]),
                                    "error_kind": string_or_none(row["error_kind"]),
                                    "error_detail_sha256": _text_hash(row["error_detail"]),
                                    "prompt_hash": string_or_none(row["prompt_hash"]),
                                    "response_hash": string_or_none(row["response_hash"]),
                                    "correlation_id": string_or_none(row["correlation_id"]),
                                    "observation_role": string_or_none(row["observation_role"])
                                    or "production",
                                    "source_call_id": string_or_none(row["source_call_id"]),
                                    "eval_result_id": _integer(row["eval_result_id"]),
                                    "provider_request_id": string_or_none(
                                        row["provider_request_id"]
                                    ),
                                    "billing_id": string_or_none(row["billing_id"]),
                                    "origin": string_or_none(row["origin"]) or "native",
                                    "budget_eligible": _boolean(
                                        row["budget_eligible"], default=True
                                    ),
                                },
                            )
                            stats.emitted_records += 1
                            yield model_call

                            cost_basis = _cost_basis(row["cost_basis"])
                            cost_kind = _cost_kind(row["cost_kind"])
                            cost_accuracy = _cost_accuracy(row["cost_accuracy"])
                            cost_source = string_or_none(row["cost_source"])
                            local_unpriced = (
                                cost_basis is CostBasis.UNKNOWN
                                and cost_kind is CostKind.INCLUDED
                                and cost_source == "local-included-unpriced"
                            )
                            cost = NormalizedEvent.create(
                                source=SourceRef(self.name, f"cost:{call_id}", str(source)),
                                occurred_at=timestamp,
                                recorded_at=timestamp,
                                payload=CostPayload(
                                    amount_usd=(
                                        None if local_unpriced else Decimal(str(row["cost_usd"]))
                                    ),
                                    input_tokens=_integer(row["tokens_in"]),
                                    output_tokens=_integer(row["tokens_out"]),
                                    cached_input_tokens=_integer(row["cache_tokens_in"]),
                                    provider=provider,
                                    model=model,
                                    cache_write_tokens=_integer(row["cache_tokens_out"]),
                                    basis=cost_basis,
                                    kind=cost_kind,
                                    accuracy=cost_accuracy,
                                    authority="somm",
                                    pricing_version=string_or_none(row["pricing_version"])
                                    or cost_source,
                                    accounting_key=_accounting_key(
                                        provider,
                                        string_or_none(row["provider_request_id"]),
                                        call_id,
                                    ),
                                    accounting_key_scope=(
                                        CostKeyScope.SHARED
                                        if string_or_none(row["provider_request_id"])
                                        else CostKeyScope.SOURCE
                                    ),
                                    observation_role=_observation_role(row["observation_role"]),
                                ),
                                session_id=session_event_id,
                                parent_event_id=model_call.event_id,
                                attributes={
                                    "project": project,
                                    "cost_source": string_or_none(row["cost_source"]),
                                    "provider_request_id": string_or_none(
                                        row["provider_request_id"]
                                    ),
                                    "billing_id": string_or_none(row["billing_id"]),
                                    "origin": string_or_none(row["origin"]) or "native",
                                    "budget_eligible": _boolean(
                                        row["budget_eligible"], default=True
                                    ),
                                },
                            )
                            stats.emitted_records += 1
                            yield cost

                            eval_result_id = _integer(row["eval_result_id"])
                            if eval_result_id is not None:
                                stats.emitted_records += 1
                                yield RelationRecord.create(
                                    subject=TypedRef("somm.call", call_id),
                                    predicate=RelationKind.PART_OF,
                                    object=TypedRef(
                                        "somm.eval-result", f"eval-result:{eval_result_id}"
                                    ),
                                    confidence=1,
                                    method=RelationMethod.SOURCE_RECEIPT,
                                    evidence_event_ids=(model_call.event_id,),
                                    recorded_at=timestamp,
                                    note="Somm call row carries its eval_result_id",
                                )

                            for crosswalk in _crosswalks(
                                call_id=call_id,
                                session_id=session_native_id,
                                correlation_id=string_or_none(row["correlation_id"]),
                                event_id=model_call.event_id,
                                timestamp=timestamp,
                            ):
                                stats.emitted_records += 1
                                yield crosswalk
                            workload_id = string_or_none(row["workload_id"])
                            if workload_id:
                                stats.emitted_records += 1
                                yield CrosswalkRecord.create(
                                    left=ExternalIdentity("somm.call", call_id),
                                    right=ExternalIdentity("somm.workload", workload_id),
                                    confidence=1,
                                    method=JoinMethod.EXPLICIT,
                                    evidence_event_ids=(model_call.event_id,),
                                    recorded_at=timestamp,
                                )
                            correlation_id = string_or_none(row["correlation_id"])
                            if (
                                project == "fab"
                                and correlation_id
                                and not _fab_attempt_correlation(correlation_id)
                            ):
                                stats.emitted_records += 1
                                yield RelationRecord.create(
                                    subject=TypedRef("fab.job", correlation_id),
                                    predicate=RelationKind.PRODUCED,
                                    object=TypedRef("somm.call", call_id),
                                    confidence=1,
                                    method=RelationMethod.SOURCE_RECEIPT,
                                    evidence_event_ids=(model_call.event_id,),
                                    recorded_at=timestamp,
                                    note="Legacy Somm call recorded Fab's job id as correlation",
                                )
                        except (KeyError, TypeError, ValueError) as error:
                            stats.malformed_records += 1
                            stats.warn("malformed-call", str(error), source)
                except sqlite3.Error as error:
                    stats.warn("query-failed", str(error), source)

                yield from _read_evidence_tables(
                    connection,
                    source=source,
                    stats=stats,
                    since=since,
                    until=until,
                )

        return SourceRead(records(), stats)


def _crosswalks(
    *,
    call_id: str,
    session_id: str | None,
    correlation_id: str | None,
    event_id: str,
    timestamp: datetime,
) -> Iterator[CrosswalkRecord]:
    left = ExternalIdentity("somm.call", call_id)
    if session_id:
        yield CrosswalkRecord.create(
            left=left,
            right=ExternalIdentity("somm.session", session_id),
            confidence=1,
            method=JoinMethod.EXPLICIT,
            evidence_event_ids=(event_id,),
            recorded_at=timestamp,
        )
    if correlation_id:
        yield CrosswalkRecord.create(
            left=left,
            right=ExternalIdentity("correlation", correlation_id),
            confidence=1,
            method=JoinMethod.EXPLICIT,
            evidence_event_ids=(event_id,),
            recorded_at=timestamp,
        )


_EVIDENCE_TABLES = (
    "eval_results",
    "eval_receipts",
    "campaigns",
    "campaign_events",
    "decisions",
    "recommendations",
    "call_updates",
)


def _read_evidence_tables(
    connection: sqlite3.Connection,
    *,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    missing_tables = [name for name in _EVIDENCE_TABLES if not table_columns(connection, name)]
    if missing_tables:
        stats.warn(
            "optional-tables-missing",
            f"legacy Somm source lacks evidence tables: {missing_tables}",
            source,
        )

    readers = (
        ("eval_results", _read_eval_results),
        ("eval_receipts", _read_eval_receipts),
        ("campaigns", _read_campaigns),
        ("campaign_events", _read_campaign_events),
        ("decisions", _read_decisions),
        ("recommendations", _read_recommendations),
        ("call_updates", _read_call_updates),
    )
    for table, reader in readers:
        try:
            yield from reader(connection, source, stats, since, until)
        except (KeyError, TypeError, ValueError, sqlite3.Error) as error:
            stats.malformed_records += 1
            stats.warn("optional-table-read-failed", f"{table}: {error}", source)


def _read_eval_results(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "call_id", "gold_model", "ts"}
    if not _supports_table(connection, "eval_results", required, source, stats):
        return
    for row in connection.execute(
        "SELECT id, call_id, gold_model, gold_response_hash, structural_score, "
        "embedding_score, judge_score, grading_started_at, ts "
        "FROM eval_results ORDER BY ts, id"
    ):
        stats.source_records += 1
        timestamp = _somm_timestamp(row["ts"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"eval-result:{row['id']}"
        score_present = any(
            row[name] is not None for name in ("structural_score", "embedding_score", "judge_score")
        )
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type="somm.eval-result",
                status=OutcomeStatus.SUCCEEDED if score_present else OutcomeStatus.UNKNOWN,
                reference=str(row["call_id"]),
            ),
            parent_event_id=stable_id("evt", "somm", "model-call", str(row["call_id"])),
            attributes={
                "gold_model": string_or_none(row["gold_model"]),
                "gold_response_hash": string_or_none(row["gold_response_hash"]),
                "structural_score": _number(row["structural_score"]),
                "embedding_score": _number(row["embedding_score"]),
                "judge_score": _number(row["judge_score"]),
                "grading_started_at": string_or_none(row["grading_started_at"]),
            },
        )
        stats.emitted_records += 1
        yield event
        stats.emitted_records += 1
        yield RelationRecord.create(
            subject=TypedRef("somm.eval-result", native_id),
            predicate=RelationKind.EVALUATES,
            object=TypedRef("somm.call", str(row["call_id"])),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
            note="Somm eval_result names its source call",
        )


def _read_eval_receipts(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "receipt_type", "payload_json", "created_at"}
    if not _supports_table(connection, "eval_receipts", required, source, stats):
        return
    rows = connection.execute(
        "SELECT id, eval_result_id, run_id, receipt_type, call_id, dataset_id, "
        "dataset_item_id, source_call_id, candidate_a_call_id, candidate_b_call_id, "
        "winner, score, threshold, payload_json, created_at "
        "FROM eval_receipts ORDER BY created_at, id"
    )
    for row in rows:
        stats.source_records += 1
        timestamp = _somm_timestamp(row["created_at"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"eval-receipt:{row['id']}"
        receipt_type = str(row["receipt_type"])
        procedure = (
            _procedure_outcome_payload(row["payload_json"])
            if receipt_type == "procedure_outcome"
            else None
        )
        implementation = _eval_receipt_implementation(row["payload_json"])
        eval_result_id = _integer(row["eval_result_id"])
        parent_event_id = (
            stable_id("evt", "somm", "outcome", f"eval-result:{eval_result_id}")
            if eval_result_id is not None
            else None
        )
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type=f"somm.eval-receipt.{receipt_type}",
                status=OutcomeStatus.SUCCEEDED,
                reference=string_or_none(row["call_id"]) or string_or_none(row["source_call_id"]),
            ),
            parent_event_id=parent_event_id,
            attributes={
                "eval_result_id": eval_result_id,
                "run_id": string_or_none(row["run_id"]),
                "dataset_id": string_or_none(row["dataset_id"]),
                "dataset_item_id": string_or_none(row["dataset_item_id"]),
                "winner": string_or_none(row["winner"]),
                "score": _number(row["score"]),
                "threshold": _number(row["threshold"]),
                "implementation": implementation,
                **(procedure or {}),
                **_protected_text_attributes("payload", row["payload_json"]),
            },
        )
        stats.emitted_records += 1
        yield event
        receipt_ref = TypedRef("somm.eval-receipt", native_id)
        if eval_result_id is not None:
            stats.emitted_records += 1
            yield RelationRecord.create(
                subject=receipt_ref,
                predicate=RelationKind.PART_OF,
                object=TypedRef("somm.eval-result", f"eval-result:{eval_result_id}"),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
                note="Somm eval receipt carries its eval_result_id",
            )
        call_ids = sorted(
            value
            for value in {
                string_or_none(row["call_id"]),
                string_or_none(row["source_call_id"]),
                string_or_none(row["candidate_a_call_id"]),
                string_or_none(row["candidate_b_call_id"]),
            }
            if value
        )
        for call_id in call_ids:
            stats.emitted_records += 1
            yield RelationRecord.create(
                subject=receipt_ref,
                predicate=RelationKind.EVALUATES,
                object=TypedRef("somm.call", call_id),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
                note="Somm eval receipt explicitly names this call",
            )
        if implementation:
            for call_id in call_ids:
                stats.emitted_records += 1
                yield RelationRecord.create(
                    subject=TypedRef("somm.call", call_id),
                    predicate=RelationKind.EVALUATES,
                    object=TypedRef("git.commit", implementation),
                    confidence=1,
                    method=RelationMethod.SOURCE_RECEIPT,
                    evidence_event_ids=(event.event_id,),
                    recorded_at=timestamp,
                    note="Somm eval receipt binds this call to the evaluated implementation",
                )
        run_id = string_or_none(row["run_id"])
        if run_id:
            stats.emitted_records += 1
            yield CrosswalkRecord.create(
                left=ExternalIdentity("somm.eval-receipt", native_id),
                right=ExternalIdentity("somm.eval-run", run_id),
                confidence=1,
                method=JoinMethod.EXPLICIT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
            )
        if procedure is not None:
            origin = procedure["procedure_origin"]
            post = procedure["post_promotion"]
            assert isinstance(origin, dict) and isinstance(post, dict)
            promotion_id = origin["spindle_promotion_receipt_id"]
            fab_job_id = post["fab_job_id"]
            assert isinstance(promotion_id, str) and isinstance(fab_job_id, str)
            stats.emitted_records += 1
            yield RelationRecord.create(
                subject=receipt_ref,
                predicate=RelationKind.EVALUATES,
                object=TypedRef("spindle.promotion-receipt", promotion_id),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
                note="Somm procedure outcome evaluates the exact Spindle promotion",
            )
            stats.emitted_records += 1
            yield RelationRecord.create(
                subject=receipt_ref,
                predicate=RelationKind.VERIFIES,
                object=TypedRef("fab.job", fab_job_id),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
                note="Somm procedure outcome names the exact Fab execution",
            )


def _procedure_outcome_payload(value: object) -> dict[str, JsonValue] | None:
    if not isinstance(value, str):
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("schema") != "somm.procedure-outcome/v1":
        return None
    origin = raw.get("origin")
    evaluation_tuple = raw.get("evaluation_tuple")
    baseline_tuple = raw.get("baseline_tuple")
    baseline = raw.get("baseline")
    post = raw.get("post_promotion")
    if not all(
        isinstance(item, dict)
        for item in (origin, evaluation_tuple, baseline_tuple, baseline, post)
    ):
        return None
    assert isinstance(origin, dict)
    assert isinstance(evaluation_tuple, dict)
    assert isinstance(baseline_tuple, dict)
    assert isinstance(baseline, dict)
    assert isinstance(post, dict)
    origin_fields = (
        "milton_finding_id",
        "milton_revision_id",
        "chip_candidate_id",
        "chip_receipt_id",
        "spindle_evaluation_receipt_id",
        "spindle_promotion_receipt_id",
    )
    tuple_fields = ("implementation", "profile", "model", "harness")
    if any(not isinstance(origin.get(field), str) or not origin[field] for field in origin_fields):
        return None
    for value_tuple in (evaluation_tuple, baseline_tuple):
        if any(
            not isinstance(value_tuple.get(field), str) or not value_tuple[field]
            for field in tuple_fields
        ):
            return None
    if any(
        not isinstance(post.get(field), str) or not post[field]
        for field in ("fab_receipt_id", "fab_job_id", "somm_call_id")
    ):
        return None
    baseline_score = _number(baseline.get("score"))
    post_score = _number(post.get("score"))
    baseline_receipt_ref = string_or_none(baseline.get("receipt_ref"))
    baseline_call_id = string_or_none(baseline.get("somm_call_id"))
    metric = string_or_none(raw.get("metric"))
    direction = string_or_none(raw.get("direction"))
    if (
        baseline_score is None
        or post_score is None
        or not baseline_receipt_ref
        or not baseline_call_id
        or not metric
        or direction not in {"higher", "lower"}
    ):
        return None
    return {
        "procedure_origin": cast(JsonValue, {field: origin[field] for field in origin_fields}),
        "evaluation_tuple": cast(
            JsonValue, {field: evaluation_tuple[field] for field in tuple_fields}
        ),
        "baseline_tuple": cast(JsonValue, {field: baseline_tuple[field] for field in tuple_fields}),
        "metric": metric,
        "direction": direction,
        "baseline_score": baseline_score,
        "post_score": post_score,
        "baseline_receipt_ref": baseline_receipt_ref,
        "baseline_call_id": baseline_call_id,
        "post_promotion": cast(
            JsonValue,
            {
                "fab_receipt_id": post["fab_receipt_id"],
                "fab_job_id": post["fab_job_id"],
                "somm_call_id": post["somm_call_id"],
            },
        ),
    }


def _eval_receipt_implementation(value: object) -> str | None:
    """Read an operator-declared implementation coordinate from a receipt."""
    if not isinstance(value, str):
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return string_or_none(raw.get("implementation"))


def _read_campaigns(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "project", "workload_id", "status", "created_at"}
    if not _supports_table(connection, "campaigns", required, source, stats):
        return
    rows = connection.execute(
        "SELECT id, project, workload_id, dataset_id, name, metric, direction, "
        "threshold, token_budget, max_rounds, plateau_window, min_delta, status, "
        "best_score, total_tokens, total_cost_usd, metadata_json, created_at, "
        "updated_at, completed_at FROM campaigns ORDER BY created_at, id"
    )
    for row in rows:
        stats.source_records += 1
        timestamp = _somm_timestamp(row["completed_at"] or row["updated_at"] or row["created_at"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"campaign:{row['id']}"
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type="somm.campaign",
                status=_outcome_status(row["status"]),
                reference=str(row["workload_id"]),
            ),
            attributes={
                "project": str(row["project"]),
                "name": str(row["name"]),
                "dataset_id": string_or_none(row["dataset_id"]),
                "metric": str(row["metric"]),
                "direction": str(row["direction"]),
                "threshold": _number(row["threshold"]),
                "token_budget": _integer(row["token_budget"]),
                "max_rounds": _integer(row["max_rounds"]),
                "plateau_window": _integer(row["plateau_window"]),
                "min_delta": _number(row["min_delta"]),
                "best_score": _number(row["best_score"]),
                "total_tokens": _integer(row["total_tokens"]),
                **_protected_text_attributes("metadata", row["metadata_json"]),
            },
        )
        stats.emitted_records += 1
        yield event
        cost = NormalizedEvent.create(
            source=SourceRef("somm", f"campaign-rollup:{row['id']}", str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=CostPayload(
                amount_usd=Decimal(str(row["total_cost_usd"])),
                input_tokens=None,
                output_tokens=None,
                cached_input_tokens=None,
                provider=None,
                model=None,
                basis=CostBasis.COMPUTED,
                kind=CostKind.UNKNOWN,
                accuracy=CostAccuracy.UNKNOWN,
                authority="somm",
                accounting_key=f"somm.campaign={row['id']}",
                accounting_key_scope=CostKeyScope.SOURCE,
                observation_role=CostObservationRole.ROLLUP,
            ),
            parent_event_id=event.event_id,
            attributes={"rollup_of": native_id},
        )
        stats.emitted_records += 1
        yield cost


def _read_campaign_events(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "campaign_id", "event_type", "action", "created_at"}
    if not _supports_table(connection, "campaign_events", required, source, stats):
        return
    rows = connection.execute(
        "SELECT id, campaign_id, sequence, run_id, event_type, action, metric_score, "
        "threshold, tokens_in, tokens_out, total_tokens, cost_usd, payload_json, "
        "created_at FROM campaign_events ORDER BY created_at, campaign_id, sequence"
    )
    for row in rows:
        stats.source_records += 1
        timestamp = _somm_timestamp(row["created_at"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"campaign-event:{row['id']}"
        campaign_native_id = f"campaign:{row['campaign_id']}"
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type=f"somm.campaign-event.{row['event_type']}",
                status=_campaign_action_status(row["action"]),
                reference=str(row["campaign_id"]),
            ),
            parent_event_id=stable_id("evt", "somm", "outcome", campaign_native_id),
            attributes={
                "sequence": _integer(row["sequence"]),
                "run_id": string_or_none(row["run_id"]),
                "action": str(row["action"]),
                "metric_score": _number(row["metric_score"]),
                "threshold": _number(row["threshold"]),
                "tokens_in": _integer(row["tokens_in"]),
                "tokens_out": _integer(row["tokens_out"]),
                "total_tokens": _integer(row["total_tokens"]),
                "cost_usd_rollup": _number(row["cost_usd"]),
                **_protected_text_attributes("payload", row["payload_json"]),
            },
        )
        stats.emitted_records += 1
        yield event
        stats.emitted_records += 1
        yield RelationRecord.create(
            subject=TypedRef("somm.campaign-event", native_id),
            predicate=RelationKind.PART_OF,
            object=TypedRef("somm.campaign", campaign_native_id),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
            note="Somm campaign event names its campaign",
        )
        run_id = string_or_none(row["run_id"])
        if run_id:
            stats.emitted_records += 1
            yield CrosswalkRecord.create(
                left=ExternalIdentity("somm.campaign-event", native_id),
                right=ExternalIdentity("somm.eval-run", run_id),
                confidence=1,
                method=JoinMethod.EXPLICIT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
            )


def _read_decisions(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "ts", "project", "question_hash", "candidates_json"}
    if not _supports_table(connection, "decisions", required, source, stats):
        return
    rows = connection.execute(
        "SELECT id, ts, project, workload_id, workload_name, question_hash, "
        "constraints_json, candidates_json, chosen_provider, chosen_model, rationale, "
        "agent, superseded_by, outcome_note FROM decisions ORDER BY ts, id"
    )
    for row in rows:
        stats.source_records += 1
        timestamp = _somm_timestamp(row["ts"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"decision:{row['id']}"
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type="somm.decision",
                status=OutcomeStatus.SUCCEEDED,
                reference=string_or_none(row["workload_id"]),
            ),
            attributes={
                "project": str(row["project"]),
                "workload_name": string_or_none(row["workload_name"]),
                "question_hash": str(row["question_hash"]),
                "chosen_provider": string_or_none(row["chosen_provider"]),
                "chosen_model": string_or_none(row["chosen_model"]),
                "agent": string_or_none(row["agent"]),
                "superseded_by": string_or_none(row["superseded_by"]),
                **_protected_text_attributes("constraints", row["constraints_json"]),
                **_protected_text_attributes("candidates", row["candidates_json"]),
                **_protected_text_attributes("rationale", row["rationale"]),
                **_protected_text_attributes("outcome_note", row["outcome_note"]),
            },
        )
        stats.emitted_records += 1
        yield event
        workload_id = string_or_none(row["workload_id"])
        if workload_id:
            stats.emitted_records += 1
            yield RelationRecord.create(
                subject=TypedRef("somm.decision", native_id),
                predicate=RelationKind.ACTS_ON,
                object=TypedRef("somm.workload", workload_id),
                confidence=1,
                method=RelationMethod.SOURCE_RECEIPT,
                evidence_event_ids=(event.event_id,),
                recorded_at=timestamp,
                note="Somm decision names its workload",
            )


def _read_recommendations(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "workload_id", "action", "created_at"}
    if not _supports_table(connection, "recommendations", required, source, stats):
        return
    rows = connection.execute(
        "SELECT id, workload_id, action, evidence_json, expected_impact, confidence, "
        "created_at, dismissed_at, applied_at FROM recommendations ORDER BY created_at, id"
    )
    for row in rows:
        stats.source_records += 1
        timestamp = _somm_timestamp(row["applied_at"] or row["dismissed_at"] or row["created_at"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"recommendation:{row['id']}"
        status = (
            OutcomeStatus.SUCCEEDED
            if row["applied_at"]
            else OutcomeStatus.ABANDONED
            if row["dismissed_at"]
            else OutcomeStatus.UNKNOWN
        )
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type=f"somm.recommendation.{row['action']}",
                status=status,
                reference=str(row["workload_id"]),
            ),
            attributes={
                "confidence": _number(row["confidence"]),
                "created_at": str(row["created_at"]),
                "dismissed_at": string_or_none(row["dismissed_at"]),
                "applied_at": string_or_none(row["applied_at"]),
                **_protected_text_attributes("evidence", row["evidence_json"]),
                **_protected_text_attributes("expected_impact", row["expected_impact"]),
            },
        )
        stats.emitted_records += 1
        yield event
        stats.emitted_records += 1
        yield RelationRecord.create(
            subject=TypedRef("somm.recommendation", native_id),
            predicate=RelationKind.ACTS_ON,
            object=TypedRef("somm.workload", str(row["workload_id"])),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
            note="Somm recommendation names its workload",
        )


def _read_call_updates(
    connection: sqlite3.Connection,
    source: Path,
    stats: ReadStats,
    since: datetime | None,
    until: datetime | None,
) -> Iterator[AdapterRecord]:
    required = {"id", "call_id", "field", "value", "ts"}
    if not _supports_table(connection, "call_updates", required, source, stats):
        return
    rows = connection.execute(
        "SELECT id, call_id, field, value, ts FROM call_updates ORDER BY ts, id"
    )
    for row in rows:
        stats.source_records += 1
        timestamp = _somm_timestamp(row["ts"])
        if not _in_window(timestamp, since, until):
            stats.skipped_records += 1
            continue
        native_id = f"call-update:{row['id']}"
        field = str(row["field"])
        value = str(row["value"])
        event = NormalizedEvent.create(
            source=SourceRef("somm", native_id, str(source)),
            occurred_at=timestamp,
            recorded_at=timestamp,
            payload=OutcomePayload(
                outcome_type=f"somm.call-update.{field}",
                status=_outcome_status(value) if field == "outcome" else OutcomeStatus.UNKNOWN,
                reference=str(row["call_id"]),
            ),
            parent_event_id=stable_id("evt", "somm", "model-call", str(row["call_id"])),
            attributes={"field": field, "value": value},
        )
        stats.emitted_records += 1
        yield event
        stats.emitted_records += 1
        yield RelationRecord.create(
            subject=TypedRef("somm.call-update", native_id),
            predicate=RelationKind.ACTS_ON,
            object=TypedRef("somm.call", str(row["call_id"])),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
            note="Somm late update names its call",
        )


def _supports_table(
    connection: sqlite3.Connection,
    table: str,
    required: set[str],
    source: Path,
    stats: ReadStats,
) -> bool:
    columns = table_columns(connection, table)
    if not columns:
        return False
    missing = sorted(required.difference(columns))
    if missing:
        stats.warn(
            "unsupported-optional-schema",
            f"{table} is missing columns: {missing}",
            source,
        )
        return False
    return True


def _somm_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    text = str(value).strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _in_window(timestamp: datetime, since: datetime | None, until: datetime | None) -> bool:
    return (since is None or timestamp >= since) and (until is None or timestamp < until)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _boolean(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _protected_text_attributes(prefix: str, value: object) -> dict[str, JsonValue]:
    if value is None:
        return {f"{prefix}_sha256": None, f"{prefix}_chars": None}
    text = str(value)
    return {
        f"{prefix}_sha256": hashlib.sha256(text.encode()).hexdigest(),
        f"{prefix}_chars": len(text),
    }


def _outcome_status(value: object) -> OutcomeStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"ok", "success", "succeeded", "completed", "passed", "acted"}:
        return OutcomeStatus.SUCCEEDED
    if normalized in {
        "error",
        "failed",
        "bad_json",
        "empty",
        "off_task",
        "timeout",
        "rate_limit",
        "upstream_error",
        "exhausted",
    }:
        return OutcomeStatus.FAILED
    if normalized in {"reverted", "revert", "refuted"}:
        return OutcomeStatus.REVERTED
    if normalized in {"abandoned", "dismissed", "stopped", "plateau", "budget_exhausted"}:
        return OutcomeStatus.ABANDONED
    return OutcomeStatus.UNKNOWN


def _campaign_action_status(value: object) -> OutcomeStatus:
    normalized = str(value or "").strip().lower()
    if normalized == "keep":
        return OutcomeStatus.SUCCEEDED
    if normalized == "revert":
        return OutcomeStatus.REVERTED
    if normalized == "stop":
        return OutcomeStatus.ABANDONED
    return OutcomeStatus.UNKNOWN


def _observation_role(value: object) -> CostObservationRole:
    if value is None:
        return CostObservationRole.PRODUCTION
    try:
        return CostObservationRole(str(value))
    except ValueError:
        return CostObservationRole.UNKNOWN


def _accounting_key(provider: str, provider_request_id: str | None, call_id: str) -> str:
    if provider_request_id:
        return f"provider.request={provider}:{provider_request_id}"
    return f"somm.call={call_id}"


def _fab_attempt_correlation(value: str) -> bool:
    job_id, marker, attempt_index = value.rpartition(":attempt:")
    return bool(job_id and marker and attempt_index.isdigit())


def _cost_basis(value: object) -> CostBasis:
    try:
        return CostBasis(str(value)) if value is not None else CostBasis.COMPUTED
    except ValueError:
        return CostBasis.UNKNOWN


def _cost_kind(value: object) -> CostKind:
    try:
        return CostKind(str(value)) if value is not None else CostKind.UNKNOWN
    except ValueError:
        return CostKind.UNKNOWN


def _cost_accuracy(value: object) -> CostAccuracy:
    try:
        return CostAccuracy(str(value)) if value is not None else CostAccuracy.ESTIMATED
    except ValueError:
        return CostAccuracy.UNKNOWN


def _parent_event_id(value: object) -> str | None:
    parent = string_or_none(value)
    return stable_id("evt", "somm", "model-call", parent) if parent else None


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
