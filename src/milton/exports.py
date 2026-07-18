"""Versioned, dependency-free finding documents for external action owners."""

from __future__ import annotations

from milton.errors import ValidationError
from milton.findings import FindingKind, FindingLedger
from milton.model import JsonValue, format_datetime, stable_id

GEORGE_FINDING_CANDIDATE_SCHEMA = "milton.finding-candidate/v1"
CHIP_CANDIDATE_EXPORT_SCHEMA = "milton.chip-candidate-export/v1"


def build_george_finding_candidate(
    ledger: FindingLedger,
    finding_id: str,
    *,
    target_project: str = "george",
) -> dict[str, JsonValue]:
    """Build one immutable advisory document for George's intake boundary."""

    history = ledger.history(finding_id)
    if not history:
        raise ValidationError(f"finding does not exist: {finding_id}")
    finding = history[-1]
    coordinate = _target_coordinate(finding.manifest.scope, finding.details, finding_id)
    suggestion = _suggestion(finding.kind, finding.details)
    export_id = stable_id(
        "gfx",
        GEORGE_FINDING_CANDIDATE_SCHEMA,
        finding.finding_id,
        finding.revision_id,
        target_project,
        coordinate,
        suggestion,
    )
    return {
        "schema": GEORGE_FINDING_CANDIDATE_SCHEMA,
        "export_id": export_id,
        "export_coordinate": f"milton.finding-export={export_id}",
        "finding": {
            "finding_id": finding.finding_id,
            "revision_id": finding.revision_id,
            "kind": finding.kind.value,
            "grade": finding.grade.value,
            "summary": finding.summary,
            "details": finding.details,
            "recorded_at": format_datetime(finding.recorded_at),
        },
        "target": {
            "system": "george",
            "project": target_project,
            "coordinate": coordinate,
        },
        "suggestion": {
            "kind": suggestion,
            "authority": "george",
            "advisory_only": True,
        },
        "evidence": [item.to_dict() for item in finding.evidence],
        "coverage": {
            "value": finding.manifest.coverage,
            "gaps": list(finding.manifest.coverage_gaps),
        },
        "expiry": (
            format_datetime(finding.manifest.expires_at)
            if finding.manifest.expires_at is not None
            else None
        ),
        "generator": {
            "id": finding.manifest.generator,
            "source_snapshot": finding.manifest.source_snapshot,
            "scope": finding.manifest.scope,
            "generated_at": format_datetime(finding.manifest.generated_at),
        },
        "taint": {
            "classification": "derived-untrusted-data",
            "instruction_authority": "none",
            "content_policy": "structured-metadata",
        },
    }


def build_chip_candidate_export(
    ledger: FindingLedger,
    finding_id: str,
) -> dict[str, JsonValue]:
    """Project one exact Milton finding revision into Chip's public ledger contract."""

    history = ledger.history(finding_id)
    if not history:
        raise ValidationError(f"finding does not exist: {finding_id}")
    finding = history[-1]
    if finding.grade.value == "refuted":
        raise ValidationError("a refuted finding cannot be exported as a Chip candidate")

    occurrence_refs = _finding_refs(finding.details, "occurrence_refs", "session_ids")
    if not occurrence_refs:
        occurrence_refs = tuple(f"milton.event={item.event_id}" for item in finding.evidence)
    counterexample_refs = _finding_refs(
        finding.details,
        "counterexample_refs",
        "negative_fixture_refs",
    )
    fixture_refs = _finding_refs(
        finding.details,
        "fixture_refs",
        "exception_fixture_refs",
    )
    candidate_id = stable_id("chc", CHIP_CANDIDATE_EXPORT_SCHEMA, finding.finding_id)
    candidate: dict[str, JsonValue] = {
        "observedAt": format_datetime(finding.recorded_at),
        "shape": finding.summary,
        "occurrenceRefs": list(occurrence_refs),
        "counterexampleRefs": list(counterexample_refs),
        "fixtureRefs": list(fixture_refs),
        "count": len(occurrence_refs),
        "notedBy": f"milton:{finding.manifest.generator}",
        "candidateId": candidate_id,
        "sourceId": f"milton.finding={finding.finding_id}",
        "sourceRevision": f"milton.finding-revision={finding.revision_id}",
        "sourceLimits": {
            "coverage": finding.manifest.coverage,
            "coverageGaps": list(finding.manifest.coverage_gaps),
            "expiresAt": (
                format_datetime(finding.manifest.expires_at)
                if finding.manifest.expires_at is not None
                else None
            ),
            "generator": finding.manifest.generator,
            "sourceSnapshot": finding.manifest.source_snapshot,
            "scope": finding.manifest.scope,
        },
    }
    export_id = stable_id(
        "cpx",
        CHIP_CANDIDATE_EXPORT_SCHEMA,
        finding.revision_id,
        candidate_id,
    )
    return {
        "schema": CHIP_CANDIDATE_EXPORT_SCHEMA,
        "exportId": export_id,
        "candidate": candidate,
        "custody": {
            "canonicalSystem": "milton",
            "findingId": finding.finding_id,
            "revisionId": finding.revision_id,
            "chipOwns": "candidate-ledger-and-receipt",
            "miltonOwns": "finding-history",
        },
        "taint": {
            "classification": "derived-untrusted-data",
            "instructionAuthority": "none",
            "contentPolicy": "structured-metadata",
        },
    }


def _finding_refs(details: dict[str, JsonValue], *keys: str) -> tuple[str, ...]:
    refs: set[str] = set()
    for key in keys:
        values = details.get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValidationError(f"finding detail {key!r} must be a list of strings")
        for value in values:
            if not isinstance(value, str):
                raise ValidationError(f"finding detail {key!r} must be a list of strings")
            if value.strip():
                refs.add(value)
    return tuple(sorted(refs))


def _target_coordinate(
    scope: dict[str, JsonValue], details: dict[str, JsonValue], finding_id: str
) -> str:
    for source in (scope, details):
        coordinate = source.get("coordinate")
        if isinstance(coordinate, str) and coordinate.strip():
            return coordinate
    return f"milton.finding={finding_id}"


def _suggestion(kind: FindingKind, details: dict[str, JsonValue]) -> str:
    rule = details.get("rule")
    if kind is FindingKind.STALE_GATE or rule == "condition-resolved":
        return "review-stale-gate"
    if rule == "re-minted":
        return "review-re-mint"
    return "review-finding"
