"""Shared contracts and privacy helpers for source adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from milton.crosswalk import CrosswalkRecord
from milton.model import CoverageStatus, JsonValue, NormalizedEvent, TurnPayload, coverage_for
from milton.relations import RelationRecord

type AdapterRecord = NormalizedEvent | CrosswalkRecord | RelationRecord


class ContentPolicy(StrEnum):
    """Whether sensitive transcript bodies may enter Milton's local store."""

    METADATA = "metadata"
    FULL = "full"


class DiagnosticLevel(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AdapterDiagnostic:
    level: DiagnosticLevel
    code: str
    message: str
    source: str
    line: int | None = None


@dataclass(slots=True)
class ReadStats:
    source_records: int = 0
    emitted_records: int = 0
    skipped_records: int = 0
    malformed_records: int = 0
    diagnostics: list[AdapterDiagnostic] = field(default_factory=list)

    def warn(self, code: str, message: str, source: Path, line: int | None = None) -> None:
        self.diagnostics.append(
            AdapterDiagnostic(DiagnosticLevel.WARNING, code, message, str(source), line)
        )


@dataclass(frozen=True, slots=True)
class SourceRead:
    records: Iterator[AdapterRecord]
    stats: ReadStats


class SourceAdapter(Protocol):
    name: str

    def default_roots(self) -> tuple[Path, ...]: ...

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]: ...

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead: ...


def text_turn(
    role: str | None, text: str, policy: ContentPolicy
) -> tuple[TurnPayload, dict[str, CoverageStatus]]:
    """Normalize text without retaining it under the metadata-only default."""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload = TurnPayload(
        role=role,
        content=text if policy is ContentPolicy.FULL else None,
        content_sha256=digest,
        content_chars=len(text),
    )
    overrides = {
        "content_sha256": CoverageStatus.INFERRED,
        "content_chars": CoverageStatus.INFERRED,
    }
    if policy is ContentPolicy.METADATA:
        overrides["content"] = CoverageStatus.REDACTED
    return payload, coverage_for(payload, **overrides)


def protected_json(
    value: object,
    policy: ContentPolicy,
) -> tuple[JsonValue, CoverageStatus, dict[str, JsonValue]]:
    """Return a raw JSON value only when opted in, plus metadata either way."""

    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    metadata: dict[str, JsonValue] = {
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "chars": len(encoded),
    }
    if policy is ContentPolicy.FULL:
        return value, CoverageStatus.RECOVERED, metadata  # type: ignore[return-value]
    return None, CoverageStatus.REDACTED, metadata


def project_from_cwd(cwd: object) -> str | None:
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    return Path(cwd).name or None


def string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
