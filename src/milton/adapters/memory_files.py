"""Read-only adapters for native rule/skill files and decision memories."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milton.adapters.base import AdapterRecord, ContentPolicy, ReadStats, SourceRead
from milton.model import (
    MemoryEvidencePayload,
    MemoryEvidenceState,
    MemoryItemKind,
    MemoryStage,
    NormalizedEvent,
    SourceRef,
    parse_datetime,
    stable_id,
)

ACCESS_SCHEMA = "milton.memory-access/v1"
ACCESS_LOG = ".milton-memory-access.jsonl"
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


class NativeMemoryAdapter:
    name = "native-memory"
    system = "factory-native"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.cwd(),)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        yield from _roots(roots)

    def fingerprint(self, source: Path) -> str:
        return _fingerprint(source, self._inventory)

    def _inventory(self, root: Path) -> tuple[tuple[Path, MemoryItemKind], ...]:
        rows: list[tuple[Path, MemoryItemKind]] = []
        for path in _walk_files(root):
            kind = _native_kind(path)
            if kind is not None:
                rows.append((path, kind))
        return tuple(sorted(rows))

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del content_policy
        return _read_memory_root(
            self.name,
            self.system,
            source,
            self._inventory(source),
            since,
            until,
        )


class DecisionMemoryAdapter:
    name = "decision-memory"
    system = "decision-memory"

    def default_roots(self) -> tuple[Path, ...]:
        return (Path.cwd(),)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        yield from _roots(roots)

    def fingerprint(self, source: Path) -> str:
        return _fingerprint(source, self._inventory)

    def _inventory(self, root: Path) -> tuple[tuple[Path, MemoryItemKind], ...]:
        rows = [
            (path, MemoryItemKind.DECISION)
            for path in _walk_files(root)
            if "decisions" in path.parts
            and path.suffix.lower() == ".md"
            and path.name != "README.md"
        ]
        return tuple(sorted(rows))

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del content_policy
        return _read_memory_root(
            self.name,
            self.system,
            source,
            self._inventory(source),
            since,
            until,
        )


def _read_memory_root(
    adapter: str,
    system: str,
    root: Path,
    inventory: tuple[tuple[Path, MemoryItemKind], ...],
    since: datetime | None,
    until: datetime | None,
) -> SourceRead:
    stats = ReadStats()

    def records() -> Iterator[AdapterRecord]:
        item_by_locator: dict[str, tuple[str, MemoryItemKind, Path]] = {}
        for path, kind in inventory:
            stats.source_records += 1
            occurred_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if until is not None and occurred_at >= until:
                stats.skipped_records += 1
                continue
            locator = path.relative_to(root).as_posix()
            item_id = stable_id("mem", system, str(path.resolve()))
            item_by_locator[locator] = (item_id, kind, path)
            content = path.read_bytes()
            event = NormalizedEvent.create(
                source=SourceRef(adapter, f"{item_id}:inventory", str(path)),
                occurred_at=occurred_at,
                recorded_at=occurred_at,
                payload=MemoryEvidencePayload(
                    system,
                    item_id,
                    kind,
                    MemoryStage.INVENTORY,
                    MemoryEvidenceState.OBSERVED,
                    evidence_reference=locator,
                ),
                attributes={
                    "locator": locator,
                    "content_sha256": hashlib.sha256(content).hexdigest(),
                    "content_chars": len(content),
                    "content_coverage": "redacted",
                },
            )
            stats.emitted_records += 1
            yield event

        for access_log in _access_logs(root):
            try:
                lines = access_log.read_text(encoding="utf-8").splitlines()
            except OSError as error:
                stats.warn("memory-access-read-failed", str(error), access_log)
                continue
            for line_number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                stats.source_records += 1
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict) or raw.get("schema") != ACCESS_SCHEMA:
                        raise ValueError("unsupported memory access row")
                    locator = str(raw["item"])
                    item = item_by_locator.get(locator)
                    if item is None:
                        raise ValueError(f"memory item is not inventoried: {locator}")
                    item_id, kind, path = item
                    occurred_at = parse_datetime(str(raw["occurred_at"]))
                    if since is not None and occurred_at < since:
                        stats.skipped_records += 1
                        continue
                    if until is not None and occurred_at >= until:
                        stats.skipped_records += 1
                        continue
                    stage = MemoryStage(str(raw["stage"]))
                    state = MemoryEvidenceState(str(raw.get("state", "observed")))
                    evidence_reference = _optional_string(raw, "evidence_reference")
                    superseded_by = _optional_string(raw, "superseded_by")
                    native_id = stable_id(
                        "mse",
                        item_id,
                        stage.value,
                        state.value,
                        evidence_reference or "",
                        superseded_by or "",
                        str(raw["occurred_at"]),
                    )
                    event = NormalizedEvent.create(
                        source=SourceRef(adapter, native_id, str(access_log)),
                        occurred_at=occurred_at,
                        recorded_at=occurred_at,
                        payload=MemoryEvidencePayload(
                            system,
                            item_id,
                            kind,
                            stage,
                            state,
                            evidence_reference=evidence_reference,
                            superseded_by=superseded_by,
                        ),
                        attributes={
                            "locator": locator,
                            "source_item": str(path),
                            "access_log": str(access_log),
                        },
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    stats.malformed_records += 1
                    stats.warn("invalid-memory-access", str(error), access_log, line_number)
                    continue
                stats.emitted_records += 1
                yield event

    return SourceRead(records(), stats)


def _roots(roots: Sequence[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for root in roots:
        expanded = root.expanduser()
        candidate = (
            expanded if expanded.is_dir() else expanded.parent if expanded.is_file() else None
        )
        if candidate is None:
            continue
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            yield resolved


def _walk_files(root: Path) -> Iterator[Path]:
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in IGNORED_DIRECTORIES)
        directory_path = Path(directory)
        for name in sorted(files):
            yield directory_path / name


def _native_kind(path: Path) -> MemoryItemKind | None:
    if path.name == "SKILL.md":
        return MemoryItemKind.SKILL
    if "rules" in path.parts and path.suffix.lower() in {".md", ".txt"}:
        return MemoryItemKind.RULE
    if path.name in {"AGENTS.md", "CLAUDE.md", "MEMORY.md", "memory_summary.md"}:
        return MemoryItemKind.FILE
    return None


def _access_logs(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in _walk_files(root) if path.name == ACCESS_LOG))


def _fingerprint(
    root: Path,
    inventory_reader: Any,
) -> str:
    paths = [path for path, _ in inventory_reader(root)]
    paths.extend(_access_logs(root))
    rows = []
    for path in sorted(set(paths)):
        stat = path.stat()
        rows.append(f"{path.relative_to(root)}\0{stat.st_size}\0{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _optional_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value
