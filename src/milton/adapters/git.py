"""Adapter for commit outcomes across local Git repositories."""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

from milton.adapters.base import AdapterRecord, ContentPolicy, ReadStats, SourceRead
from milton.crosswalk import CrosswalkRecord, ExternalIdentity, JoinMethod
from milton.model import (
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
    OutcomeStatus,
    SourceRef,
    format_datetime,
    parse_datetime,
)


class GitAdapter:
    name = "git"

    def default_roots(self) -> tuple[Path, ...]:
        explicit = os.environ.get("MILTON_PROJECTS_ROOT") or os.environ.get("GEORGE_PROJECTS_ROOT")
        if explicit:
            return (Path(explicit),)
        sibling_root = Path.cwd().parent
        if (sibling_root / "Central").is_dir():
            return (sibling_root,)
        return (Path.cwd(),)

    def discover(self, roots: Sequence[Path]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in roots:
            expanded = root.expanduser()
            if _is_repo(expanded):
                candidates = [expanded]
            elif expanded.is_dir():
                candidates = [marker.parent for marker in expanded.rglob(".git")]
            else:
                candidates = []
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved not in seen and _is_repo(candidate):
                    seen.add(resolved)
                    yield candidate

    def fingerprint(self, source: Path) -> str:
        result = _git(source, "show-ref", "--head", "--dereference")
        if result.returncode not in {0, 1} or result.stderr.strip():
            raise RuntimeError(result.stderr.strip() or "git show-ref failed")
        return hashlib.sha256(result.stdout.encode()).hexdigest()

    def read(
        self,
        source: Path,
        *,
        content_policy: ContentPolicy = ContentPolicy.METADATA,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SourceRead:
        del until  # The ingest boundary filters exact normalized timestamps.
        stats = ReadStats()

        def records() -> Iterator[AdapterRecord]:
            args = [
                "log",
                "--all",
                "--format=%H%x00%aI%x00%P%x00%an%x00%ae%x00%D%x00%s%x00%b%x1e",
            ]
            if since is not None:
                args.append(f"--since={format_datetime(since)}")
            result = _git(source, *args)
            if result.returncode != 0:
                stats.warn("git-log-failed", result.stderr.strip() or "git log failed", source)
                return

            repo_identity = str(source.resolve())
            for raw_record in result.stdout.split("\x1e"):
                record = raw_record.strip("\n")
                if not record:
                    continue
                stats.source_records += 1
                fields = record.split("\x00")
                if len(fields) != 8:
                    stats.malformed_records += 1
                    stats.warn(
                        "malformed-git-record",
                        f"expected 8 fields, found {len(fields)}",
                        source,
                    )
                    continue
                sha, timestamp_text, parents, author_name, author_email, refs, subject, body = (
                    fields
                )
                try:
                    timestamp = parse_datetime(timestamp_text)
                except ValueError as error:
                    stats.malformed_records += 1
                    stats.warn("invalid-git-timestamp", str(error), source)
                    continue

                native_id = f"{repo_identity}#{sha}"
                content_attributes = _commit_content(
                    author_name, author_email, subject, body, content_policy
                )
                event = NormalizedEvent.create(
                    source=SourceRef(self.name, native_id, repo_identity),
                    occurred_at=timestamp,
                    recorded_at=timestamp,
                    payload=OutcomePayload(
                        outcome_type="git.commit",
                        status=OutcomeStatus.SUCCEEDED,
                        reference=sha,
                    ),
                    attributes={
                        "project": source.name,
                        "repository": repo_identity,
                        "parents": cast(JsonValue, parents.split() if parents else []),
                        "refs": refs,
                        **content_attributes,
                    },
                )
                stats.emitted_records += 1
                yield event
                crosswalk = CrosswalkRecord.create(
                    left=ExternalIdentity("git.commit-instance", native_id),
                    right=ExternalIdentity("git.commit", sha),
                    confidence=1,
                    method=JoinMethod.EXACT,
                    evidence_event_ids=(event.event_id,),
                    recorded_at=timestamp,
                )
                stats.emitted_records += 1
                yield crosswalk

        return SourceRead(records(), stats)


def _is_repo(path: Path) -> bool:
    if not path.is_dir() or not (path / ".git").exists():
        return False
    result = _git(path, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git(source: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(source), *args],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )


def _commit_content(
    author_name: str,
    author_email: str,
    subject: str,
    body: str,
    policy: ContentPolicy,
) -> dict[str, JsonValue]:
    message = subject if not body else f"{subject}\n\n{body.rstrip()}"
    result: dict[str, JsonValue] = {
        "author_name_sha256": hashlib.sha256(author_name.encode()).hexdigest(),
        "author_email_sha256": hashlib.sha256(author_email.encode()).hexdigest(),
        "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
        "message_chars": len(message),
        "content_coverage": "recovered" if policy is ContentPolicy.FULL else "redacted",
    }
    if policy is ContentPolicy.FULL:
        result.update(
            {"author_name": author_name, "author_email": author_email, "message": message}
        )
    return result
