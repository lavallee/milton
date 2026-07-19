"""Strict optional reader for ``barnowl.research-outcome/v1`` JSONL."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never, cast

from milton.adapters.base import AdapterRecord, ContentPolicy, ReadStats, SourceRead
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.model import JsonValue, NormalizedEvent, OutcomePayload, OutcomeStatus, SourceRef
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef

SCHEMA_VERSION = "barnowl.research-outcome/v1"
OUTCOME_TYPE = "barnowl.research-outcome"

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_FORBIDDEN_PRIVATE_KEYS = {
    "body",
    "completion",
    "completionbody",
    "completiontext",
    "content",
    "evidence",
    "evidencebody",
    "evidencetext",
    "prompt",
    "promptbody",
    "prompttext",
    "questiontext",
    "response",
    "responsebody",
    "responsetext",
    "rostertext",
    "snippet",
    "snippettext",
    "systemprompt",
    "systempromptbody",
    "text",
}
_FORBIDDEN_TELEMETRY_MARKERS = ("token", "latency", "cost")
_REQUIRED_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "occurred_at",
    "workload",
    "attempt",
    "correlation",
    "somm_calls",
    "treatment_manifest",
    "prompt_coordinate",
    "domain_object",
    "outcome",
    "authority",
}
_OPTIONAL_EVENT_FIELDS = {"supersedes_event_id"}


class _LineValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _CallCoordinate:
    vote_index: int
    call_id: str | None
    served_provider: str | None
    served_model: str | None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "vote_index": self.vote_index,
            "call_id": self.call_id,
            "served_provider": self.served_provider,
            "served_model": self.served_model,
        }


@dataclass(frozen=True, slots=True)
class _ValidatedEvent:
    event_id: str
    occurred_at: datetime
    workload: str
    attempt_namespace: str
    attempt_id: str
    correlation_namespace: str
    correlation_id: str
    somm_calls: tuple[_CallCoordinate, ...]
    treatment_namespace: str
    manifest_sha256: str
    prompt_namespace: str
    prompt_id: str
    prompt_sha256: str
    domain_namespace: str
    object_type: str
    object_id: str
    outcome_kind: str
    judgment: str | None
    error_kind: str | None
    authority_namespace: str
    authority_id: str
    supersedes_event_id: str | None

    def attributes(self) -> dict[str, JsonValue]:
        attributes: dict[str, JsonValue] = {
            "workload": self.workload,
            "attempt": {
                "namespace": self.attempt_namespace,
                "attempt_id": self.attempt_id,
            },
            "correlation": {
                "namespace": self.correlation_namespace,
                "correlation_id": self.correlation_id,
            },
            "somm_calls": [call.to_dict() for call in self.somm_calls],
            "treatment_manifest": {
                "namespace": self.treatment_namespace,
                "manifest_sha256": self.manifest_sha256,
            },
            "prompt_coordinate": {
                "namespace": self.prompt_namespace,
                "prompt_id": self.prompt_id,
                "prompt_sha256": self.prompt_sha256,
            },
            "domain_object": {
                "namespace": self.domain_namespace,
                "object_type": self.object_type,
                "object_id": self.object_id,
            },
            "outcome": (
                {"kind": self.outcome_kind, "judgment": self.judgment}
                if self.judgment is not None
                else {"kind": self.outcome_kind, "error_kind": self.error_kind}
            ),
            "authority": {
                "namespace": self.authority_namespace,
                "authority_id": self.authority_id,
            },
        }
        if self.supersedes_event_id is not None:
            attributes["supersedes_event_id"] = self.supersedes_event_id
        return attributes


class BarnowlResearchOutcomeAdapter:
    """Read only an explicitly supplied Barnowl research-outcome JSONL path."""

    name = "barnowl-research-outcome"

    def default_roots(self) -> tuple[Path, ...]:
        return ()

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        candidates: dict[Path, Path] = {}
        for root in roots:
            expanded = root.expanduser()
            if expanded.is_file():
                discovered = [expanded] if expanded.suffix == ".jsonl" else []
            elif expanded.is_dir():
                discovered = list(expanded.rglob("*.jsonl"))
            else:
                discovered = []
            for candidate in discovered:
                if candidate.is_file():
                    candidates.setdefault(candidate.resolve(), candidate)
        for resolved in sorted(candidates, key=str):
            yield candidates[resolved]

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del content_policy, until
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            try:
                handle = source.open("rb")
            except OSError as error:
                stats.warn("source-unreadable", str(error), source)
                return

            with handle:
                for line_number, encoded_line in enumerate(handle, 1):
                    if not encoded_line.strip():
                        continue
                    stats.source_records += 1
                    try:
                        line = encoded_line.decode("utf-8")
                        raw = json.loads(
                            line,
                            object_pairs_hook=_unique_object,
                            parse_constant=_reject_json_constant,
                        )
                        event = _validate_event(raw)
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        stats.malformed_records += 1
                        stats.warn("malformed-jsonl", str(error), source, line_number)
                        continue
                    except _LineValidationError as error:
                        stats.malformed_records += 1
                        stats.warn(error.code, str(error), source, line_number)
                        continue

                    if since is not None and event.occurred_at < since:
                        stats.skipped_records += 1
                        continue

                    for record in _normalize_event(event, source):
                        stats.emitted_records += 1
                        yield record

        return SourceRead(records(), stats)


def _reject_json_constant(value: str) -> Never:
    raise _LineValidationError("malformed-jsonl", f"non-standard JSON constant {value!r}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _LineValidationError("duplicate-field", f"object repeats field {key!r}")
        result[key] = value
    return result


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _reject_forbidden_fields(value: object, coordinate: str = "event") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalized_key(key)
            if any(marker in normalized for marker in _FORBIDDEN_TELEMETRY_MARKERS):
                raise _LineValidationError(
                    "forbidden-field", f"{coordinate}.{key} is forbidden telemetry"
                )
            if normalized in _FORBIDDEN_PRIVATE_KEYS:
                raise _LineValidationError(
                    "forbidden-field", f"{coordinate}.{key} is forbidden private content"
                )
            _reject_forbidden_fields(nested, f"{coordinate}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_fields(nested, f"{coordinate}[{index}]")


def _require_fields(
    value: object,
    required: set[str],
    coordinate: str,
    *,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _LineValidationError("invalid-structure", f"{coordinate} must be an object")
    result = cast(dict[str, Any], value)
    optional = optional or set()
    fields = set(result)
    missing = sorted(required - fields)
    unknown = sorted(fields - required - optional)
    if missing:
        raise _LineValidationError("missing-field", f"{coordinate} is missing {missing}")
    if unknown:
        raise _LineValidationError("unknown-field", f"{coordinate} has unknown fields {unknown}")
    return result


def _require_string(value: object, coordinate: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise _LineValidationError(
            "invalid-coordinate", f"{coordinate} must be a nonblank canonical string"
        )
    return value


def _require_nullable_string(value: object, coordinate: str) -> str | None:
    return None if value is None else _require_string(value, coordinate)


def _require_uuid(value: object, coordinate: str) -> str:
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != value:
        raise _LineValidationError("invalid-coordinate", f"{coordinate} must be a canonical UUID")
    return value


def _require_digest(value: object, coordinate: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise _LineValidationError(
            "invalid-coordinate", f"{coordinate} must be a lowercase SHA-256 digest"
        )
    return value


def _parse_occurred_at(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise _LineValidationError(
            "invalid-coordinate",
            "event.occurred_at must be a canonical ISO-8601 UTC timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise _LineValidationError(
            "invalid-coordinate", "event.occurred_at must be a valid ISO-8601 UTC timestamp"
        ) from error
    if parsed.utcoffset() != timedelta(0) or parsed.tzinfo is None:
        raise _LineValidationError(
            "invalid-coordinate", "event.occurred_at must be a UTC timestamp"
        )
    return parsed.astimezone(UTC)


def _named_coordinate(value: object, coordinate: str, id_field: str) -> tuple[str, str]:
    result = _require_fields(value, {"namespace", id_field}, coordinate)
    return (
        _require_string(result["namespace"], f"{coordinate}.namespace"),
        _require_string(result[id_field], f"{coordinate}.{id_field}"),
    )


def _validate_calls(value: object) -> tuple[_CallCoordinate, ...]:
    if not isinstance(value, list):
        raise _LineValidationError("invalid-structure", "event.somm_calls must be a list")
    call_ids: set[str] = set()
    vote_indexes: set[int] = set()
    calls: list[_CallCoordinate] = []
    for index, raw_call in enumerate(value):
        coordinate = f"event.somm_calls[{index}]"
        call = _require_fields(
            raw_call,
            {"vote_index", "call_id", "served_provider", "served_model"},
            coordinate,
        )
        vote_index = call["vote_index"]
        if (
            not isinstance(vote_index, int)
            or isinstance(vote_index, bool)
            or vote_index < 1
            or vote_index in vote_indexes
        ):
            raise _LineValidationError(
                "invalid-call-coordinate",
                f"{coordinate}.vote_index is invalid or duplicate",
            )
        vote_indexes.add(vote_index)
        call_id = _require_nullable_string(call["call_id"], f"{coordinate}.call_id")
        served_provider = _require_nullable_string(
            call["served_provider"], f"{coordinate}.served_provider"
        )
        served_model = _require_nullable_string(call["served_model"], f"{coordinate}.served_model")
        if call_id is None and served_provider is None and served_model is None:
            raise _LineValidationError(
                "invalid-call-coordinate", f"{coordinate} has no non-null call coordinate"
            )
        if call_id is not None:
            if call_id in call_ids:
                raise _LineValidationError(
                    "duplicate-call-id", f"event repeats Somm call ID {call_id}"
                )
            call_ids.add(call_id)
        calls.append(_CallCoordinate(vote_index, call_id, served_provider, served_model))
    return tuple(calls)


def _validate_event(value: object) -> _ValidatedEvent:
    _reject_forbidden_fields(value)
    event = _require_fields(
        value,
        _REQUIRED_EVENT_FIELDS,
        "event",
        optional=_OPTIONAL_EVENT_FIELDS,
    )
    if event["schema_version"] != SCHEMA_VERSION:
        raise _LineValidationError(
            "unsupported-schema", f"schema_version must equal {SCHEMA_VERSION}"
        )
    event_id = _require_uuid(event["event_id"], "event.event_id")
    occurred_at = _parse_occurred_at(event["occurred_at"])
    workload = _require_string(event["workload"], "event.workload")
    attempt_namespace, attempt_id = _named_coordinate(
        event["attempt"], "event.attempt", "attempt_id"
    )
    correlation_namespace, correlation_id = _named_coordinate(
        event["correlation"], "event.correlation", "correlation_id"
    )
    calls = _validate_calls(event["somm_calls"])

    treatment = _require_fields(
        event["treatment_manifest"],
        {"namespace", "manifest_sha256"},
        "event.treatment_manifest",
    )
    treatment_namespace = _require_string(
        treatment["namespace"], "event.treatment_manifest.namespace"
    )
    manifest_sha256 = _require_digest(
        treatment["manifest_sha256"], "event.treatment_manifest.manifest_sha256"
    )

    prompt = _require_fields(
        event["prompt_coordinate"],
        {"namespace", "prompt_id", "prompt_sha256"},
        "event.prompt_coordinate",
    )
    prompt_namespace = _require_string(prompt["namespace"], "event.prompt_coordinate.namespace")
    prompt_id = _require_string(prompt["prompt_id"], "event.prompt_coordinate.prompt_id")
    prompt_sha256 = _require_digest(
        prompt["prompt_sha256"], "event.prompt_coordinate.prompt_sha256"
    )

    domain = _require_fields(
        event["domain_object"],
        {"namespace", "object_type", "object_id"},
        "event.domain_object",
    )
    domain_namespace = _require_string(domain["namespace"], "event.domain_object.namespace")
    object_type = _require_string(domain["object_type"], "event.domain_object.object_type")
    object_id = _require_string(domain["object_id"], "event.domain_object.object_id")

    outcome = _require_fields(
        event["outcome"], {"kind"}, "event.outcome", optional={"judgment", "error_kind"}
    )
    outcome_kind = outcome["kind"]
    if outcome_kind == "judged":
        outcome = _require_fields(outcome, {"kind", "judgment"}, "event.outcome")
        judgment = _require_string(outcome["judgment"], "event.outcome.judgment")
        error_kind = None
    elif outcome_kind == "error":
        outcome = _require_fields(outcome, {"kind", "error_kind"}, "event.outcome")
        judgment = None
        error_kind = _require_string(outcome["error_kind"], "event.outcome.error_kind")
    else:
        raise _LineValidationError("invalid-outcome", "event.outcome.kind must be judged or error")

    authority_namespace, authority_id = _named_coordinate(
        event["authority"], "event.authority", "authority_id"
    )
    supersedes_event_id = None
    if "supersedes_event_id" in event:
        supersedes_event_id = _require_uuid(
            event["supersedes_event_id"], "event.supersedes_event_id"
        )
        if supersedes_event_id == event_id:
            raise _LineValidationError("invalid-coordinate", "an event cannot supersede itself")

    return _ValidatedEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        workload=workload,
        attempt_namespace=attempt_namespace,
        attempt_id=attempt_id,
        correlation_namespace=correlation_namespace,
        correlation_id=correlation_id,
        somm_calls=calls,
        treatment_namespace=treatment_namespace,
        manifest_sha256=manifest_sha256,
        prompt_namespace=prompt_namespace,
        prompt_id=prompt_id,
        prompt_sha256=prompt_sha256,
        domain_namespace=domain_namespace,
        object_type=object_type,
        object_id=object_id,
        outcome_kind=outcome_kind,
        judgment=judgment,
        error_kind=error_kind,
        authority_namespace=authority_namespace,
        authority_id=authority_id,
        supersedes_event_id=supersedes_event_id,
    )


def _normalize_event(event: _ValidatedEvent, source: Path) -> Iterator[AdapterRecord]:
    outcome = NormalizedEvent.create(
        source=SourceRef("barnowl-research-outcome", event.event_id, str(source)),
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
        payload=OutcomePayload(
            outcome_type=OUTCOME_TYPE,
            status=(
                OutcomeStatus.SUCCEEDED if event.outcome_kind == "judged" else OutcomeStatus.FAILED
            ),
            reference=event.event_id,
        ),
        attributes=event.attributes(),
    )
    yield outcome

    outcome_ref = TypedRef(OUTCOME_TYPE, event.event_id)
    for call in event.somm_calls:
        if call.call_id is None:
            continue
        yield RelationRecord.create(
            subject=TypedRef("somm.call", call.call_id),
            predicate=RelationKind.PRODUCED,
            object=outcome_ref,
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(outcome.event_id,),
            recorded_at=event.occurred_at,
            note="Barnowl research-outcome receipt names the exact Somm call",
        )

    attempt_ref = TypedRef(event.attempt_namespace, event.attempt_id)
    if outcome_ref != attempt_ref:
        yield RelationRecord.create(
            subject=outcome_ref,
            predicate=RelationKind.PART_OF,
            object=attempt_ref,
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(outcome.event_id,),
            recorded_at=event.occurred_at,
            note="Barnowl research-outcome receipt names its exact attempt",
        )

    correlation = ExternalIdentity(event.correlation_namespace, event.correlation_id)
    outcome_identity = ExternalIdentity(OUTCOME_TYPE, event.event_id)
    if correlation != outcome_identity:
        yield CrosswalkRecord.create(
            left=outcome_identity,
            right=correlation,
            confidence=1,
            method=JoinMethod.EXPLICIT,
            evidence_event_ids=(outcome.event_id,),
            recorded_at=event.occurred_at,
            note="Barnowl research-outcome receipt carries this correlation coordinate",
        )

    domain_ref = TypedRef(event.domain_namespace, event.object_id)
    if outcome_ref != domain_ref:
        yield RelationRecord.create(
            subject=outcome_ref,
            predicate=RelationKind.EVALUATES,
            object=domain_ref,
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(outcome.event_id,),
            recorded_at=event.occurred_at,
            note="Barnowl research-outcome receipt names the exact evaluated domain object",
        )
