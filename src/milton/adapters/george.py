"""Adapter for George's append-only cross-project inbox."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

from milton.adapters.base import (
    AdapterRecord,
    ContentPolicy,
    ReadStats,
    SourceRead,
    protected_json,
    string_or_none,
)
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.model import (
    GateConsultation,
    GateEvidenceKind,
    GateEvidencePayload,
    GateStatus,
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
    parse_datetime,
)
from milton.relations import RelationKind, RelationMethod, RelationRecord, TypedRef


class GeorgeAdapter:
    name = "george"

    def default_roots(self) -> tuple[Path, ...]:
        explicit = os.environ.get("MILTON_GEORGE_INBOX")
        if explicit:
            return (Path(explicit),)
        central = os.environ.get("GEORGE_CENTRAL_DIR")
        if central:
            return (Path(central) / ".george" / "inbox",)
        sibling = Path.cwd().parent / "Central" / ".george" / "inbox"
        if sibling.is_dir():
            return (sibling,)
        return (Path.home() / "Projects" / "Central" / ".george" / "inbox",)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            candidates = [expanded] if expanded.is_file() else expanded.rglob("*.jsonl")
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
                        entry_id = str(raw["id"])
                        entry_kind = str(raw["kind"])
                        content = str(raw["content"])
                        timestamp = parse_datetime(str(raw["ts"]))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                        stats.malformed_records += 1
                        stats.warn("malformed-inbox-record", str(error), source, line_number)
                        continue

                    if since is not None and timestamp < since:
                        stats.skipped_records += 1
                        continue

                    context = cast(
                        dict[str, object],
                        raw.get("context") if isinstance(raw.get("context"), dict) else {},
                    )
                    context_value, context_status, context_metadata = protected_json(
                        context, content_policy
                    )
                    content_attributes: dict[str, JsonValue] = {
                        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "content_chars": len(content),
                        "content_coverage": (
                            "recovered" if content_policy is ContentPolicy.FULL else "redacted"
                        ),
                    }
                    if content_policy is ContentPolicy.FULL:
                        content_attributes["content"] = content

                    refs = _strings(raw.get("refs"))
                    event = NormalizedEvent.create(
                        source=SourceRef(self.name, entry_id, str(source)),
                        occurred_at=timestamp,
                        recorded_at=timestamp,
                        payload=OutcomePayload(
                            outcome_type=f"george.{entry_kind}",
                            status=_entry_status(entry_kind),
                            reference=refs[0] if refs else None,
                        ),
                        attributes={
                            "host": string_or_none(raw.get("host")),
                            "session_native_id": string_or_none(raw.get("session")),
                            "harness": string_or_none(raw.get("harness")),
                            "project": string_or_none(raw.get("project")),
                            "concept": string_or_none(raw.get("concept")),
                            "run_id": string_or_none(raw.get("run_id")),
                            "fab_job_id": string_or_none(context.get("fab_job_id")),
                            "git_sha": _selected_string(context, "git_sha", "sha", "commit"),
                            "tags": cast(JsonValue, _strings(raw.get("tags"))),
                            "refs": cast(JsonValue, refs),
                            "edges": _safe_edges(raw.get("edges")),
                            "context": context_value,
                            "context_coverage": context_status.value,
                            "context_metadata": context_metadata,
                            **content_attributes,
                        },
                    )
                    stats.emitted_records += 1
                    yield event

                    for crosswalk in _entry_crosswalks(raw, context, event, timestamp):
                        stats.emitted_records += 1
                        yield crosswalk
                    for relation in _entry_relations(context, event, timestamp):
                        stats.emitted_records += 1
                        yield relation
                    for gate_record in _gate_evidence_records(
                        raw, context, event, timestamp, source
                    ):
                        stats.emitted_records += 1
                        yield gate_record
                    for disposition_record in _finding_disposition_records(
                        context, event, timestamp
                    ):
                        stats.emitted_records += 1
                        yield disposition_record

        return SourceRead(records(), stats)


def _entry_status(kind: str) -> OutcomeStatus:
    if kind == "done":
        return OutcomeStatus.SUCCEEDED
    if kind == "blocker":
        return OutcomeStatus.FAILED
    if kind == "obviated":
        return OutcomeStatus.REVERTED
    return OutcomeStatus.UNKNOWN


def _entry_crosswalks(
    raw: dict[str, object],
    context: dict[str, object],
    event: NormalizedEvent,
    timestamp: datetime,
) -> Iterator[CrosswalkRecord]:
    left = ExternalIdentity("george.entry", event.source.native_id)
    identities: set[ExternalIdentity] = set()
    fab_job_id = string_or_none(context.get("fab_job_id"))
    if fab_job_id:
        identities.add(ExternalIdentity("fab.job", fab_job_id))
    git_sha = _selected_string(context, "git_sha", "sha", "commit")
    if git_sha:
        identities.add(ExternalIdentity("git.commit", git_sha))
    run_id = string_or_none(raw.get("run_id"))
    if run_id:
        identities.add(ExternalIdentity("george.run", run_id))

    session_id = string_or_none(context.get("session_id"))
    harness = string_or_none(raw.get("harness"))
    if session_id and harness in {"codex", "claude"}:
        namespace = "codex.session" if harness == "codex" else "claude-code.session"
        identities.add(ExternalIdentity(namespace, session_id))

    for right in sorted(identities):
        yield CrosswalkRecord.create(
            left=left,
            right=right,
            confidence=1,
            method=JoinMethod.EXPLICIT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
        )


def _entry_relations(
    context: dict[str, object],
    event: NormalizedEvent,
    timestamp: datetime,
) -> Iterator[RelationRecord]:
    george = TypedRef("george.entry", event.source.native_id)
    fab_job_id = string_or_none(context.get("fab_job_id"))
    git_sha = _selected_string(context, "git_sha", "sha", "commit")
    if fab_job_id:
        yield RelationRecord.create(
            subject=george,
            predicate=RelationKind.VERIFIES,
            object=TypedRef("fab.job", fab_job_id),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
            note="George entry explicitly records the Fab job receipt",
        )
    if git_sha:
        subject = TypedRef("fab.job", fab_job_id) if fab_job_id else george
        yield RelationRecord.create(
            subject=subject,
            predicate=RelationKind.PRODUCED,
            object=TypedRef("git.commit", git_sha),
            confidence=1,
            method=RelationMethod.SOURCE_RECEIPT,
            evidence_event_ids=(event.event_id,),
            recorded_at=timestamp,
            note="George entry explicitly records the produced commit coordinate",
        )


def _gate_evidence_records(
    raw: dict[str, object],
    context: dict[str, object],
    entry_event: NormalizedEvent,
    timestamp: datetime,
    source: Path,
) -> Iterator[AdapterRecord]:
    classification = _gate_classification(raw, context)
    if classification is None:
        return
    evidence_kind, status, consultation, disposition, mint_id = classification
    coordinate, coordinate_method, coordinate_ambiguous = _gate_coordinate(raw, context)
    payload = GateEvidencePayload(
        evidence_kind=evidence_kind,
        coordinate=coordinate,
        mint_id=mint_id,
        status=status,
        consultation=consultation,
        disposition=disposition,
    )
    gate_event = NormalizedEvent.create(
        source=SourceRef("george", entry_event.source.native_id, str(source)),
        occurred_at=timestamp,
        recorded_at=timestamp,
        payload=payload,
        parent_event_id=entry_event.event_id,
        attributes={
            "project": string_or_none(raw.get("project")),
            "concept": string_or_none(raw.get("concept")),
            "coordinate_method": coordinate_method,
            "coordinate_ambiguous": coordinate_ambiguous,
        },
    )
    yield gate_event

    gate_namespace = (
        "george.gate-mint" if evidence_kind is GateEvidenceKind.MINT else "george.gate-event"
    )
    gate_ref = ExternalIdentity(gate_namespace, entry_event.source.native_id)
    yield CrosswalkRecord.create(
        left=ExternalIdentity("george.entry", entry_event.source.native_id),
        right=gate_ref,
        confidence=1,
        method=JoinMethod.EXPLICIT,
        evidence_event_ids=(entry_event.event_id, gate_event.event_id),
        recorded_at=timestamp,
        note="one George source row exposes both entry and gate-evidence views",
    )

    if coordinate is None:
        return
    predicate = {
        GateEvidenceKind.MINT: RelationKind.PART_OF,
        GateEvidenceKind.CONSULT: RelationKind.EVALUATES,
        GateEvidenceKind.DECISION: RelationKind.EVALUATES,
        GateEvidenceKind.DISPOSITION: RelationKind.ACTS_ON,
    }[evidence_kind]
    yield RelationRecord.create(
        subject=TypedRef(gate_namespace, entry_event.source.native_id),
        predicate=predicate,
        object=TypedRef("george.gate", coordinate),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=(gate_event.event_id,),
        recorded_at=timestamp,
        note=f"George {evidence_kind.value} carries an exact gate coordinate",
    )


def _finding_disposition_records(
    context: dict[str, object],
    entry_event: NormalizedEvent,
    timestamp: datetime,
) -> Iterator[AdapterRecord]:
    raw = context.get("milton_finding_disposition")
    if not isinstance(raw, dict) or raw.get("schema") != "george.finding-disposition/v1":
        return
    receipt_id = string_or_none(raw.get("receipt_id"))
    finding_id = string_or_none(raw.get("finding_id"))
    revision_id = string_or_none(raw.get("revision_id"))
    disposition = string_or_none(raw.get("disposition"))
    if (
        receipt_id != entry_event.source.native_id
        or finding_id is None
        or revision_id is None
        or disposition not in {"accepted", "refuted", "deferred", "acted"}
    ):
        return

    receipt_ref = ExternalIdentity("george.disposition", receipt_id)
    yield CrosswalkRecord.create(
        left=ExternalIdentity("george.entry", entry_event.source.native_id),
        right=receipt_ref,
        confidence=1,
        method=JoinMethod.EXPLICIT,
        evidence_event_ids=(entry_event.event_id,),
        recorded_at=timestamp,
        note="George entry is the canonical finding-disposition receipt",
    )
    predicate = {
        "accepted": RelationKind.EVALUATES,
        "deferred": RelationKind.EVALUATES,
        "refuted": RelationKind.REFUTES,
        "acted": RelationKind.ACTS_ON,
    }[disposition]
    yield RelationRecord.create(
        subject=TypedRef("milton.finding-revision", revision_id),
        predicate=predicate,
        object=TypedRef("george.disposition", receipt_id),
        confidence=1,
        method=RelationMethod.SOURCE_RECEIPT,
        evidence_event_ids=(entry_event.event_id,),
        recorded_at=timestamp,
        note=(f"George {disposition} Milton finding {finding_id} at exact revision {revision_id}"),
    )


def _gate_classification(
    raw: dict[str, object], context: dict[str, object]
) -> (
    tuple[
        GateEvidenceKind,
        GateStatus,
        GateConsultation | None,
        str | None,
        str | None,
    ]
    | None
):
    entry_id = str(raw["id"])
    tags = set(_strings(raw.get("tags")))
    if "needs:human" in tags or bool(context.get("gate")):
        return GateEvidenceKind.MINT, GateStatus.OPEN, None, None, entry_id

    consultation_raw = context.get("gate_consultation")
    if isinstance(consultation_raw, dict):
        explicit = consultation_raw.get("consulted")
        consultation = (
            GateConsultation.CONSULTED
            if explicit is True
            else GateConsultation.NOT_CONSULTED
            if explicit is False
            else None
        )
        mint_id = string_or_none(consultation_raw.get("mint_id"))
        return GateEvidenceKind.CONSULT, GateStatus.OPEN, consultation, None, mint_id

    kind = string_or_none(raw.get("kind"))
    refs = _strings(raw.get("refs"))
    if (
        kind == "decision"
        and refs
        and (
            "resolved-by-human" in tags
            or "gate-decision" in tags
            or isinstance(context.get("gate_decision"), dict)
        )
    ):
        decision = context.get("decision")
        resolved = "resolved-by-human" in tags or (
            isinstance(decision, dict) and decision.get("status") == "resolved"
        )
        return (
            GateEvidenceKind.DECISION,
            GateStatus.RESOLVED if resolved else GateStatus.OPEN,
            None,
            "resolved" if resolved else "open",
            None,
        )
    if (
        kind in {"done", "obviated"}
        and refs
        and ("gate-disposition" in tags or isinstance(context.get("gate_disposition"), dict))
    ):
        return (
            GateEvidenceKind.DISPOSITION,
            GateStatus.RESOLVED if kind == "done" else GateStatus.RETIRED,
            None,
            kind,
            None,
        )
    return None


def _gate_coordinate(
    raw: dict[str, object], context: dict[str, object]
) -> tuple[str | None, str, bool]:
    explicit = context.get("triage_coordinate") or context.get("work_coordinate")
    if isinstance(explicit, str) and explicit.strip():
        return f"context={explicit.strip()}", "explicit-context", False
    if isinstance(explicit, dict):
        repository = _canonical_repository(explicit.get("repository") or explicit.get("repo"))
        ref = string_or_none(explicit.get("ref")) or string_or_none(explicit.get("branch"))
        policy = _canonical_policy(explicit.get("policy") or explicit.get("rule"))
        target = (string_or_none(explicit.get("target")) or "").lower()
        if repository and ref and policy and target:
            return (
                f"repository={repository}|ref={ref}|policy={policy}|target={target}",
                "explicit-structured",
                False,
            )

    decision = context.get("decision")
    if isinstance(decision, dict):
        decision_coordinate = string_or_none(decision.get("coordinate"))
        if decision_coordinate:
            return f"context={decision_coordinate}", "decision-context", False

    targets: set[str] = set()
    for edge in _safe_edges(raw.get("edges")):
        if not isinstance(edge, dict):  # protected by _safe_edges; narrows JsonValue
            continue
        edge_type = string_or_none(edge.get("type"))
        edge_target = string_or_none(edge.get("target"))
        if edge_type in {"blocks", "relates_to", "depends_on", "supersedes"} and edge_target:
            targets.add(edge_target)
    targets.update(_strings(raw.get("refs")))
    if len(targets) == 1:
        return f"target={next(iter(targets))}", "exact-target", False
    return None, "ambiguous-target" if targets else "unavailable", len(targets) > 1


def _canonical_repository(value: object) -> str:
    raw = (string_or_none(value) or "").lower().removesuffix(".git").rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return raw if raw.count("/") == 1 and all(raw.split("/")) else ""


def _canonical_policy(value: object) -> str:
    raw = " ".join((string_or_none(value) or "").lower().replace("_", " ").split())
    return raw.replace(" ", "-")


def _selected_string(values: dict[str, object], *names: str) -> str | None:
    return next((value for name in names if (value := string_or_none(values.get(name)))), None)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _safe_edges(value: object) -> list[JsonValue]:
    if not isinstance(value, list):
        return []
    edges: list[JsonValue] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        edge_type = string_or_none(item.get("type"))
        target = string_or_none(item.get("target"))
        if edge_type and target:
            edges.append({"type": edge_type, "target": target})
    return edges
