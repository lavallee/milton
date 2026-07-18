"""Verify the built wheel against a synthetic cross-layer fixture corpus."""

from __future__ import annotations

import argparse
import difflib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast


def _run(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        rendered = " ".join(command)
        raise RuntimeError(
            f"release smoke command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _run_json(command: list[str]) -> dict[str, Any]:
    raw = json.loads(_run(command))
    if not isinstance(raw, dict):
        raise RuntimeError(f"expected JSON object from {' '.join(command)}")
    return cast(dict[str, Any], raw)


def _manifest(
    scan: dict[str, Any],
    accounting: dict[str, Any],
    attribution: dict[str, Any],
    evaluation: dict[str, Any],
    first_generation: dict[str, Any],
    replay_generation: dict[str, Any],
    findings: dict[str, Any],
) -> dict[str, Any]:
    adapters = scan["ingestion"]["adapters"]
    records = attribution["records"]
    finding_rows = findings["findings"]
    return {
        "schema": "milton.release-smoke/v1",
        "ingestion": {
            row["adapter"]: {
                "events": row["events_inserted"],
                "relations": row["relations_inserted"],
                "sources_failed": row["sources_failed"],
            }
            for row in adapters
        },
        "accounting": {
            "amounts_usd": accounting["amounts_usd"],
            "key_coverage": accounting["key_coverage"],
            "observations": accounting["observations"],
        },
        "attribution": {
            "amounts_usd": attribution["amounts_usd"],
            "conservation": attribution["conservation"],
            "denominators": attribution["denominators"],
            "records": [
                {
                    "accounting_key": row["accounting_key"],
                    "accounting_key_scope": row["accounting_key_scope"],
                    "accuracy": row["accuracy"],
                    "amount_usd": row["amount_usd"],
                    "basis": row["basis"],
                    "economic_kind": row["economic_kind"],
                    "outcome": {
                        "outcome_type": row["outcome"]["outcome_type"],
                        "reference": row["outcome"]["reference"],
                        "status": row["outcome"]["status"],
                    },
                    "path": [
                        {
                            "direction": step["direction"],
                            "predicate": step["predicate"],
                            "source": step["source"],
                            "target": step["target"],
                        }
                        for step in row["path"]["steps"]
                    ],
                    "reason": row["reason"],
                    "state": row["state"],
                }
                for row in records
            ],
        },
        "findings": {
            "surface_rules": evaluation["surface_rules"],
            "first_emission": {
                "candidates": len(first_generation["emission"]["candidates"]),
                "inserted": first_generation["emission"]["inserted"],
                "replayed": first_generation["emission"]["replayed"],
            },
            "replay_emission": {
                "candidates": len(replay_generation["emission"]["candidates"]),
                "inserted": replay_generation["emission"]["inserted"],
                "replayed": replay_generation["emission"]["replayed"],
            },
            "current": [
                {
                    "finding_id": row["finding"]["finding_id"],
                    "grade": row["finding"]["grade"],
                    "kind": row["finding"]["kind"],
                    "subject": (
                        f"{row['finding']['details']['rule']}:"
                        f"{row['finding']['details']['coordinate']}"
                    ),
                    "generator": row["finding"]["manifest"]["generator"],
                }
                for row in finding_rows
            ],
        },
    }


def run_smoke(wheel: Path) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    fixtures = repository / "tests" / "fixtures" / "release-smoke"
    with tempfile.TemporaryDirectory(prefix="milton-release-smoke-") as temporary:
        work = Path(temporary)
        environment = work / "venv"
        _run([sys.executable, "-m", "venv", str(environment)])
        python = environment / "bin" / "python"
        cli = environment / "bin" / "milton"
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheel.resolve()),
            ]
        )

        somm_store = work / "somm.sqlite"
        with sqlite3.connect(somm_store) as connection:
            connection.executescript((fixtures / "somm.sql").read_text(encoding="utf-8"))

        store = work / "events.db"
        ledger = work / "findings.jsonl"
        _run([str(cli), "init", "--store", str(store), "--findings", str(ledger)])
        scan = _run_json(
            [
                str(cli),
                "scan",
                "fab",
                "somm",
                "george",
                "--store",
                str(store),
                "--source",
                f"fab={fixtures / 'fab'}",
                "--source",
                f"somm={somm_store}",
                "--source",
                f"george={fixtures / 'george.jsonl'}",
                "--since",
                "2026-07-01T00:00:00Z",
                "--until",
                "2026-07-15T00:00:00Z",
                "--format",
                "json",
            ]
        )
        accounting = _run_json(
            [
                str(cli),
                "accounting",
                "--store",
                str(store),
                "--since",
                "2026-07-01T00:00:00Z",
                "--format",
                "json",
            ]
        )
        attribution = _run_json(
            [
                str(cli),
                "cost",
                "--per-outcome",
                "--store",
                str(store),
                "--since",
                "2026-07-01T00:00:00Z",
                "--until",
                "2026-07-15T00:00:00Z",
                "--outcome-type",
                "fab.job",
                "--format",
                "json",
            ]
        )
        cases = fixtures / "gate-cases.jsonl"
        evaluation = _run_json(
            [
                str(cli),
                "findings",
                "evaluate",
                "--store",
                str(store),
                "--cases",
                str(cases),
                "--format",
                "json",
            ]
        )
        generate = [
            str(cli),
            "findings",
            "generate",
            "--generator",
            "george-gates",
            "--store",
            str(store),
            "--findings",
            str(ledger),
            "--since",
            "2026-07-01T00:00:00Z",
            "--until",
            "2026-07-15T00:00:00Z",
            "--source-state",
            "fresh",
            "--evaluation-cases",
            str(cases),
            "--recorded-at",
            "2026-07-15T00:00:01Z",
            "--format",
            "json",
        ]
        first_generation = _run_json(generate)
        replay_generation = _run_json(generate)
        findings = _run_json(
            [
                str(cli),
                "findings",
                "list",
                "--store",
                str(store),
                "--findings",
                str(ledger),
                "--format",
                "json",
            ]
        )
        return _manifest(
            scan,
            accounting,
            attribution,
            evaluation,
            first_generation,
            replay_generation,
            findings,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="print the compact manifest without comparing it to the checked-in expectation",
    )
    args = parser.parse_args()
    manifest = run_smoke(args.wheel)
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.print_only:
        print(rendered, end="")
        return 0

    expected_path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "release-smoke"
        / "expected-manifest.json"
    )
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    if manifest != expected:
        expected_rendered = json.dumps(expected, indent=2, sort_keys=True) + "\n"
        diff = "".join(
            difflib.unified_diff(
                expected_rendered.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile="expected-manifest.json",
                tofile="actual-manifest.json",
            )
        )
        print(diff, file=sys.stderr)
        return 1
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
