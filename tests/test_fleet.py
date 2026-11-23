import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from milton.cli import main
from milton.errors import MiltonError
from milton.fleet import (
    FleetConfig,
    FleetHost,
    collect_fleet,
    load_fleet_config,
    read_index,
    scan_script,
)
from milton.serve import fleet_summary, make_handler

FIXTURES = Path(__file__).parent / "fixtures"


def _plain(document: object) -> Any:
    return json.loads(json.dumps(document))


def _manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "hosts.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_manifest_defaults_and_host_overrides(tmp_path: Path) -> None:
    config = load_fleet_config(
        _manifest(
            tmp_path,
            """
[collect]
since = "7d"
milton = "uvx milton"
sources = ["git=~/Projects"]
adapters = ["claude-code"]

[[hosts]]
name = "alpha"

[[hosts]]
name = "beta"
ssh = "beta.example"
milton = "milton"
sources = ["codex=~/codex"]
adapters = ["codex", "git"]
""",
        )
    )
    alpha, beta = config.hosts
    assert config.since == "7d"
    assert alpha == FleetHost("alpha", "alpha", "uvx milton", ("git=~/Projects",), ("claude-code",))
    assert beta.ssh == "beta.example"
    assert beta.sources == ("git=~/Projects", "codex=~/codex")
    assert beta.adapters == ("codex", "git")


@pytest.mark.parametrize(
    "body",
    [
        "",
        '[[hosts]]\nname = "a"\n[[hosts]]\nname = "a"\n',
        '[[hosts]]\nname = "../x"\n',
        '[[hosts]]\nname = "a"\nsources = ["no-equals"]\n',
        '[collect]\ntimeout_seconds = 0\n[[hosts]]\nname = "a"\n',
    ],
)
def test_manifest_rejects_invalid(tmp_path: Path, body: str) -> None:
    with pytest.raises(MiltonError):
        load_fleet_config(_manifest(tmp_path, body))


def test_scan_script_runs_from_state_dir_with_metadata_policy() -> None:
    config = FleetConfig(hosts=(), since="30d", state_dir="~/state", timeout_seconds=60)
    host = FleetHost("h", "h", "milton", ("git=~/My Projects",), ("git",))
    script = scan_script(config, host)
    assert 'state="$HOME/state/' in script
    assert "cd \"$state\" && milton scan git --source 'git=~/My Projects'" in script
    assert "--content" not in script


def _local_config(tmp_path: Path) -> FleetConfig:
    milton = f"{sys.executable} -m milton"
    return FleetConfig(
        hosts=(
            FleetHost(
                "local-a",
                "local",
                milton,
                (f"claude-code={tmp_path / 'claude'}",),
                ("claude-code",),
            ),
        ),
        since="100000d",
        state_dir=str(tmp_path / "state"),
        timeout_seconds=120,
    )


def test_collect_local_host_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "claude" / "project").mkdir(parents=True)
    shutil.copy(FIXTURES / "claude_code" / "session-1.jsonl", tmp_path / "claude" / "project")
    out = tmp_path / "fleet"

    index = _plain(collect_fleet(_local_config(tmp_path), out))

    (entry,) = index["hosts"]
    assert entry["status"] == "ok", entry
    assert entry["last_success_at"] == entry["collected_at"]
    assert (out / "local-a" / "events.db").exists()
    assert not (out / "local-a" / "events.db.incoming").exists()
    snapshot = json.loads((out / "local-a" / "snapshot.json").read_text())
    assert snapshot["host"] == "local-a"
    assert snapshot["report"]["event_count"] > 0
    assert set(snapshot["outcomes"]) <= {
        "amounts_usd",
        "denominators",
        "outcome_coverage",
        "reason_counts",
    }
    summary = _plain(fleet_summary(out))
    assert summary["totals"]["event_count"] == snapshot["report"]["event_count"]


def test_failed_host_keeps_previous_snapshot(tmp_path: Path) -> None:
    (tmp_path / "claude").mkdir()
    out = tmp_path / "fleet"
    config = _local_config(tmp_path)
    first = _plain(collect_fleet(config, out))
    good_at = first["hosts"][0]["collected_at"]

    def unreachable(argv: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 255, "", "ssh: connect timed out")

    second = _plain(collect_fleet(config, out, runner=unreachable))
    (entry,) = second["hosts"]
    assert entry["status"] == "unreachable"
    assert entry["last_success_at"] == good_at
    assert "timed out" in str(entry["error"])
    assert (out / "local-a" / "snapshot.json").exists()
    assert _plain(read_index(out))["hosts"][0]["status"] == "unreachable"


def test_collect_rejects_unknown_host(tmp_path: Path) -> None:
    with pytest.raises(MiltonError, match="not in manifest"):
        collect_fleet(_local_config(tmp_path), tmp_path / "out", only=["nope"])


@pytest.fixture
def served(tmp_path: Path) -> Iterator[str]:
    (tmp_path / "claude" / "project").mkdir(parents=True)
    shutil.copy(FIXTURES / "claude_code" / "session-1.jsonl", tmp_path / "claude" / "project")
    out = tmp_path / "fleet"
    collect_fleet(_local_config(tmp_path), out)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(out))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_serve_routes(served: str) -> None:
    status, body = _get(f"{served}/health")
    assert status == 200 and json.loads(body)["status"] == "ok"
    status, body = _get(f"{served}/")
    assert status == 200 and "local-a" in body and "sum of host projections" in body
    status, body = _get(f"{served}/api/fleet.json")
    assert json.loads(body)["hosts"][0]["name"] == "local-a"
    status, body = _get(f"{served}/hosts/local-a")
    assert status == 200 and "Ingestion coverage" in body
    status, body = _get(f"{served}/api/hosts/local-a/snapshot.json")
    assert json.loads(body)["host"] == "local-a"
    assert _get(f"{served}/hosts/missing")[0] == 404
    assert _get(f"{served}/hosts/..%2Findex.json")[0] == 404


def test_cli_fleet_collect_reports_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest(
        tmp_path,
        f"""
[collect]
state_dir = "{tmp_path / "state"}"
milton = "false"

[[hosts]]
name = "broken"
ssh = "local"
""",
    )
    assert main(["fleet", "collect", "--hosts", str(manifest), "--out", str(tmp_path / "o")]) == 1
    assert "broken: error" in capsys.readouterr().out
