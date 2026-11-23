"""Collect per-host Milton stores and render deterministic fleet snapshots.

Each host scans its own exhaust with its own Milton, under the default
metadata content policy, so raw transcript bodies never leave the host. The
collector copies back only the normalized store, then computes one snapshot
per host with the collector's projections. Hosts are never merged into one
store: each keeps its own coverage declaration, and fleet totals are labeled
as sums of host projections.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast

from milton.errors import MiltonError
from milton.model import JsonValue, format_datetime, utc_now
from milton.pricing import PriceTable, build_notional_summary
from milton.store import MiltonStore

SNAPSHOT_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
LOCAL = "local"
FLEET_NAME = "_fleet"
_REMOTE_PATH = "$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
_STDERR_TAIL = 2000


@dataclass(frozen=True, slots=True)
class FleetHost:
    name: str
    ssh: str
    milton: str
    sources: tuple[str, ...] = ()
    adapters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FleetConfig:
    hosts: tuple[FleetHost, ...]
    since: str
    state_dir: str
    timeout_seconds: int


Runner = Callable[[Sequence[str], int], "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)


def load_fleet_config(path: Path) -> FleetConfig:
    """Read a hosts manifest. See docs/fleet.md for the format."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise MiltonError(f"cannot read hosts manifest {path}: {error}") from error
    collect = document.get("collect", {})
    if not isinstance(collect, dict):
        raise MiltonError("[collect] must be a table")
    default_milton = str(collect.get("milton", "milton"))
    default_sources = _strings(collect.get("sources", []), "collect.sources")
    default_adapters = _strings(collect.get("adapters", []), "collect.adapters")
    since = str(collect.get("since", "30d"))
    state_dir = str(collect.get("state_dir", "~/.local/state/milton/fleet"))
    timeout = collect.get("timeout_seconds", 1800)
    if not isinstance(timeout, int) or timeout <= 0:
        raise MiltonError("collect.timeout_seconds must be a positive integer")
    raw_hosts = document.get("hosts", [])
    if not isinstance(raw_hosts, list) or not raw_hosts:
        raise MiltonError("hosts manifest must declare at least one [[hosts]] entry")
    hosts: list[FleetHost] = []
    seen: set[str] = set()
    for entry in raw_hosts:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise MiltonError("each [[hosts]] entry needs a string name")
        name = entry["name"]
        if not name or "/" in name or name.startswith((".", "_")) or name in seen:
            raise MiltonError(f"invalid or duplicate host name: {name!r}")
        seen.add(name)
        hosts.append(
            FleetHost(
                name=name,
                ssh=str(entry.get("ssh", name)),
                milton=str(entry.get("milton", default_milton)),
                sources=default_sources
                + _strings(entry.get("sources", []), f"hosts.{name}.sources"),
                adapters=_strings(
                    entry.get("adapters", list(default_adapters)), f"hosts.{name}.adapters"
                ),
            )
        )
    return FleetConfig(
        hosts=tuple(hosts), since=since, state_dir=state_dir, timeout_seconds=timeout
    )


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MiltonError(f"{label} must be a list of strings")
    for item in value:
        if label.endswith("sources") and "=" not in item:
            raise MiltonError(f"{label} entries must be ADAPTER=PATH, got {item!r}")
    return tuple(value)


def remote_state_dir(config: FleetConfig, host: FleetHost) -> str:
    """A per-command store directory, so a Milton change builds a fresh store."""

    tag = hashlib.sha256(host.milton.encode("utf-8")).hexdigest()[:12]
    return f"{config.state_dir.rstrip('/')}/{tag}"


def scan_script(config: FleetConfig, host: FleetHost) -> str:
    state = remote_state_dir(config, host)
    state_expr = state.replace("~", "$HOME", 1) if state.startswith("~") else state
    extra = "".join(f" {shlex.quote(adapter)}" for adapter in host.adapters) + "".join(
        f" --source {shlex.quote(source)}" for source in host.sources
    )
    # Run from the state directory: the memory and git adapters default to
    # the working directory, and an SSH session would otherwise start in $HOME.
    return (
        f'export PATH="{_REMOTE_PATH}"; '
        f'state="{state_expr}"; mkdir -p "$state" && cd "$state" && '
        f'{host.milton} scan{extra} --store "$state/events.db" '
        f"--since {shlex.quote(config.since)} --format json "
        '> "$state/scan.json"; code=$?; '
        'printf "%s\\n" "$state"; exit $code'
    )


def _scan_argv(config: FleetConfig, host: FleetHost) -> list[str]:
    script = scan_script(config, host)
    if host.ssh == LOCAL:
        return ["sh", "-c", script]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host.ssh, script]


def _copy_argv(host: FleetHost, remote_file: str, destination: Path) -> list[str]:
    if host.ssh == LOCAL:
        return ["cp", remote_file, str(destination)]
    return ["rsync", "-a", "--inplace", f"{host.ssh}:{remote_file}", str(destination)]


def collect_host(
    config: FleetConfig,
    host: FleetHost,
    out_dir: Path,
    *,
    runner: Runner = _run,
    snapshot_since: datetime | None = None,
) -> dict[str, JsonValue]:
    """Scan one host and refresh its local copy and snapshot.

    A failed host keeps its previous store and snapshot so the dashboard can
    show the last good projection beside the current error.
    """

    started = utc_now()
    record: dict[str, JsonValue] = {
        "name": host.name,
        "ssh": host.ssh,
        "milton": host.milton,
        "started_at": format_datetime(started),
    }
    host_dir = out_dir / host.name
    host_dir.mkdir(parents=True, exist_ok=True)
    try:
        scan = runner(_scan_argv(config, host), config.timeout_seconds)
    except (subprocess.TimeoutExpired, OSError) as error:
        return {**record, "status": "unreachable", "error": str(error)[-_STDERR_TAIL:]}
    state_lines = [line for line in scan.stdout.splitlines() if line.strip()]
    record["scan_exit"] = scan.returncode
    if scan.returncode not in (0, 1) or not state_lines:
        status = "unreachable" if scan.returncode == 255 else "error"
        detail = (scan.stderr or scan.stdout or "scan produced no state directory").strip()
        return {**record, "status": status, "error": detail[-_STDERR_TAIL:]}
    state = state_lines[-1]
    staging = host_dir / "events.db.incoming"
    for suffix in ("", "-wal"):
        target = Path(f"{staging}{suffix}")
        target.unlink(missing_ok=True)
        copy = runner(_copy_argv(host, f"{state}/events.db{suffix}", target), 600)
        if copy.returncode != 0 and suffix == "":
            detail = (copy.stderr or "copy failed").strip()
            return {**record, "status": "error", "error": detail[-_STDERR_TAIL:]}
    since = snapshot_since or _duration_start(config.since)
    try:
        snapshot = build_snapshot(staging, since=since)
    except MiltonError as error:
        return {**record, "status": "error", "error": f"snapshot: {error}"}
    for suffix in ("", "-wal"):
        source = Path(f"{staging}{suffix}")
        destination = host_dir / f"events.db{suffix}"
        if source.exists():
            os.replace(source, destination)
        else:
            destination.unlink(missing_ok=True)
    (host_dir / "events.db-shm").unlink(missing_ok=True)
    snapshot["host"] = host.name
    _write_json(host_dir / "snapshot.json", snapshot)
    return {
        **record,
        "status": "ok" if scan.returncode == 0 else "partial",
        "error": scan.stderr.strip()[-_STDERR_TAIL:] or None,
        "collected_at": format_datetime(utc_now()),
    }


def collect_fleet(
    config: FleetConfig,
    out_dir: Path,
    *,
    only: Sequence[str] = (),
    runner: Runner = _run,
    workers: int = 4,
) -> dict[str, JsonValue]:
    unknown = set(only).difference(host.name for host in config.hosts)
    if unknown:
        raise MiltonError(f"hosts not in manifest: {', '.join(sorted(unknown))}")
    selected = [host for host in config.hosts if not only or host.name in only]
    out_dir.mkdir(parents=True, exist_ok=True)
    since = _duration_start(config.since)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(
            pool.map(
                lambda host: collect_host(
                    config, host, out_dir, runner=runner, snapshot_since=since
                ),
                selected,
            )
        )
    previous = read_index(out_dir)
    previous_hosts = {
        str(item["name"]): item
        for item in cast(list[dict[str, JsonValue]], previous.get("hosts", []))
    }
    merged: dict[str, dict[str, JsonValue]] = {}
    for host in config.hosts:
        if host.name in previous_hosts:
            merged[host.name] = previous_hosts[host.name]
    for result in results:
        name = str(result["name"])
        last_success = result.get("collected_at") or previous_hosts.get(name, {}).get(
            "last_success_at"
        )
        merged[name] = {**result, "last_success_at": last_success}
    index: dict[str, JsonValue] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": format_datetime(utc_now()),
        "window": {"since": config.since},
        "content_policy": "metadata",
        "hosts": [merged[host.name] for host in config.hosts if host.name in merged],
    }
    collected = [
        str(item["name"])
        for item in index_hosts(index)
        if (out_dir / str(item["name"]) / "events.db").exists()
    ]
    fleet: dict[str, JsonValue] = {"hosts": cast(JsonValue, collected)}
    try:
        merge_fleet(out_dir, collected, since=since)
        fleet.update(status="ok", generated_at=format_datetime(utc_now()))
    except (MiltonError, OSError, sqlite3.Error) as error:
        fleet.update(status="error", error=str(error)[-_STDERR_TAIL:])
    index["fleet"] = fleet
    _write_json(out_dir / "index.json", index)
    return index


_OUTCOME_KEYS = ("amounts_usd", "denominators", "outcome_coverage", "reason_counts")


def _outcome_summary(document: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: document[key] for key in _OUTCOME_KEYS if key in document}


def build_snapshot(
    store_path: Path, *, since: datetime | None, prices: PriceTable | None = None
) -> dict[str, JsonValue]:
    """Precompute the projections the dashboard renders for one store.

    ``outcomes`` attributes selected (priced) observations only. ``notional``
    values the unpriced usage in the window at list price, and
    ``notional_outcomes`` attributes priced plus notional amounts together.
    """

    if not store_path.exists():
        raise MiltonError(f"event store does not exist: {store_path}")
    table = prices or PriceTable.builtin()
    since_text = format_datetime(since) if since else None
    with MiltonStore(store_path, read_only=True) as store:
        report = store.report(since=since_text)
        outcomes = store.outcome_attribution(since=since_text).to_dict()
        notional = build_notional_summary(store.events(since=since_text), table)
        notional_outcomes = store.outcome_attribution(since=since_text, notional=table).to_dict()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": format_datetime(utc_now()),
        "window": {"since": since_text},
        "report": report.to_dict(),
        "outcomes": _outcome_summary(outcomes),
        "notional": notional.to_dict(),
        "notional_outcomes": _outcome_summary(notional_outcomes),
    }


def merge_fleet(
    out_dir: Path,
    hosts: Sequence[str],
    *,
    since: datetime | None,
    prices: PriceTable | None = None,
) -> dict[str, JsonValue]:
    """Rebuild the derived fleet store from host stores and snapshot it.

    Host stores stay authoritative; the merged store is rebuilt from them on
    every run and exists only so joins can cross hosts (for example an outcome
    recorded on one machine and the session that produced it on another).
    Exact replays are deduplicated by the store's identity rules. A record
    whose identity conflicts across hosts is skipped and counted, never
    overwritten.
    """

    fleet_dir = out_dir / FLEET_NAME
    fleet_dir.mkdir(parents=True, exist_ok=True)
    staging = fleet_dir / "events.db.incoming"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{staging}{suffix}").unlink(missing_ok=True)
    merge: dict[str, JsonValue] = {}
    with MiltonStore(staging) as merged:
        for host in hosts:
            source = out_dir / host / "events.db"
            if not source.exists():
                continue
            counts = {"events": 0, "duplicates": 0, "conflicts": 0, "links": 0}
            with MiltonStore(source, read_only=True) as store:
                with merged.write_batch():
                    for event in store.events():
                        try:
                            inserted = merged.append_event(event)
                        except MiltonError:
                            counts["conflicts"] += 1
                            continue
                        counts["events" if inserted else "duplicates"] += 1
                appends: list[Callable[[], bool]] = [
                    partial(merged.append_crosswalk, crosswalk)
                    for crosswalk in store.crosswalk_records()
                ]
                appends += [
                    partial(merged.append_relation, relation)
                    for relation in store.relation_records()
                ]
                for append in appends:
                    try:
                        counts["links"] += int(append())
                    except MiltonError:
                        counts["conflicts"] += 1
            merge[host] = cast(JsonValue, counts)
    snapshot = build_snapshot(staging, since=since, prices=prices)
    for suffix in ("", "-wal"):
        source_path = Path(f"{staging}{suffix}")
        destination = fleet_dir / f"events.db{suffix}"
        if source_path.exists():
            os.replace(source_path, destination)
        else:
            destination.unlink(missing_ok=True)
    Path(f"{staging}-shm").unlink(missing_ok=True)
    (fleet_dir / "events.db-shm").unlink(missing_ok=True)
    snapshot["host"] = FLEET_NAME
    snapshot["merge"] = merge
    _write_json(fleet_dir / "snapshot.json", snapshot)
    return snapshot


def index_hosts(index: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    hosts = index.get("hosts", [])
    return [item for item in hosts if isinstance(item, dict)] if isinstance(hosts, list) else []


def read_index(out_dir: Path) -> dict[str, JsonValue]:
    path = out_dir / "index.json"
    if not path.exists():
        return {}
    try:
        return cast(dict[str, JsonValue], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def read_snapshot(out_dir: Path, host: str) -> dict[str, JsonValue] | None:
    path = out_dir / host / "snapshot.json"
    if "/" in host or host.startswith(".") or not path.exists():
        return None
    try:
        return cast(dict[str, JsonValue], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def _duration_start(value: str) -> datetime | None:
    # Local import keeps cli -> fleet one-directional at import time.
    from milton.cli import _parse_since

    return _parse_since(value)


def _write_json(path: Path, document: dict[str, JsonValue]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def require_tools(config: FleetConfig) -> None:
    if any(host.ssh != LOCAL for host in config.hosts):
        for tool in ("ssh", "rsync"):
            if shutil.which(tool) is None:
                raise MiltonError(f"remote collection needs `{tool}` on PATH")
