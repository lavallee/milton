from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from milton.activity import build_activity
from milton.adapters import FabAdapter, SommAdapter
from milton.crosswalk import ExternalIdentity
from milton.ingest import Ingestor
from milton.model import CostObservationRole, CostPayload
from milton.outcomes import AttributionState
from milton.relations import TypedRef
from milton.store import MiltonStore

SCHEMA = "fab.execution-receipt/v1"
JOB = "job-1"
ATTEMPT = "job-1:attempt:0"
CALL = "call-1"
ENTRY = "Q024"
SHA = "a" * 40


def _write_receipt(root: Path, name: str, body: dict[str, object]) -> None:
    path = root / "jobs" / JOB / "receipts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA, **body}, indent=2, sort_keys=True))


def _fab_fixture(root: Path) -> None:
    origin = {
        "source": "george",
        "entry_namespace": "george.entry",
        "entry_id": ENTRY,
        "commission_revision": "7",
        "commission_fingerprint": "sha256:commission",
    }
    _write_receipt(
        root,
        "job-submitted.json",
        {
            "receipt_id": "receipt-job",
            "kind": "job_submitted",
            "occurred_at": "2026-07-17T10:00:00Z",
            "job_id": JOB,
            "backend": "somm",
            "cwd": "/work/project",
            "intent": "harness",
            "submitter": "fab-bridge-george",
            "origin": origin,
            "relations": [
                {
                    "subject": {"namespace": "george.entry", "value": ENTRY},
                    "predicate": "verifies",
                    "object": {"namespace": "fab.job", "value": JOB},
                }
            ],
        },
    )
    _write_receipt(
        root,
        "attempt-0-started.json",
        {
            "receipt_id": "receipt-start",
            "kind": "attempt_started",
            "occurred_at": "2026-07-17T10:01:00Z",
            "job_id": JOB,
            "attempt_id": ATTEMPT,
            "attempt_idx": 0,
            "backend": "somm",
            "origin": origin,
            "correlation_id": ATTEMPT,
            "relations": [
                {
                    "subject": {"namespace": "fab.attempt", "value": ATTEMPT},
                    "predicate": "attempt_of",
                    "object": {"namespace": "fab.job", "value": JOB},
                }
            ],
            "accounting": {
                "observation_role": "rollup",
                "child_accounting_keys": [],
                "counting": False,
            },
        },
    )
    _write_receipt(
        root,
        "attempt-0-finished.json",
        {
            "receipt_id": "receipt-finish",
            "kind": "attempt_finished",
            "occurred_at": "2026-07-17T10:02:00Z",
            "job_id": JOB,
            "attempt_id": ATTEMPT,
            "attempt_idx": 0,
            "backend": "somm",
            "origin": origin,
            "correlation_id": ATTEMPT,
            "native_coordinates": [{"namespace": "somm.call", "value": CALL}],
            "outcome": {"status": "succeeded", "exit_code": 0, "reason": "done"},
            "relations": [
                {
                    "subject": {"namespace": "fab.attempt", "value": ATTEMPT},
                    "predicate": "attempt_of",
                    "object": {"namespace": "fab.job", "value": JOB},
                },
                {
                    "subject": {"namespace": "fab.attempt", "value": ATTEMPT},
                    "predicate": "produced",
                    "object": {"namespace": "somm.call", "value": CALL},
                },
            ],
            "accounting": {
                "observation_role": "rollup",
                "child_accounting_keys": [f"somm.call={CALL}"],
                "counting": False,
            },
        },
    )
    _write_receipt(
        root,
        "job-outcome.json",
        {
            "receipt_id": "receipt-outcome",
            "kind": "job_outcome",
            "occurred_at": "2026-07-17T10:03:00Z",
            "job_id": JOB,
            "attempt_id": ATTEMPT,
            "attempt_idx": 0,
            "origin": origin,
            "outcome": {"status": "succeeded", "reason": "stop", "reason_tags": []},
            "relations": [],
        },
    )
    _write_receipt(
        root,
        "delivery-outcome.json",
        {
            "receipt_id": "receipt-delivery",
            "kind": "delivery_outcome",
            "occurred_at": "2026-07-17T10:04:00Z",
            "job_id": JOB,
            "attempt_id": ATTEMPT,
            "attempt_idx": 0,
            "origin": origin,
            "outcome": {"status": "done", "reason": "done", "reason_tags": []},
            "relations": [],
        },
    )
    _write_receipt(
        root,
        "attempt-0-verifier.json",
        {
            "receipt_id": "receipt-verifier",
            "kind": "verifier",
            "occurred_at": "2026-07-17T10:05:00Z",
            "job_id": JOB,
            "attempt_id": ATTEMPT,
            "attempt_idx": 0,
            "origin": origin,
            "review_id": "review-1",
            "review": {"review_id": "review-1", "recommendation": "pass"},
            "relations": [
                {
                    "subject": {"namespace": "fab.verifier", "value": "review-1"},
                    "predicate": "verifies",
                    "object": {"namespace": "fab.attempt", "value": ATTEMPT},
                }
            ],
        },
    )
    _write_receipt(
        root,
        "attempt-0-artifact.json",
        {
            "receipt_id": "receipt-artifact",
            "kind": "artifact",
            "occurred_at": "2026-07-17T10:06:00Z",
            "job_id": JOB,
            "attempt_id": ATTEMPT,
            "attempt_idx": 0,
            "origin": origin,
            "artifact": {
                "type": "git_commit",
                "coordinate": {"namespace": "git.commit", "value": SHA},
                "attributes": {},
            },
            "relations": [
                {
                    "subject": {"namespace": "fab.attempt", "value": ATTEMPT},
                    "predicate": "produced",
                    "object": {"namespace": "git.commit", "value": SHA},
                }
            ],
        },
    )


def _somm_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE calls (
            id TEXT PRIMARY KEY, ts TEXT, project TEXT, provider TEXT, model TEXT,
            tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, outcome TEXT,
            correlation_id TEXT, cost_basis TEXT, cost_kind TEXT,
            cost_accuracy TEXT, cost_source TEXT, pricing_version TEXT,
            observation_role TEXT, provider_request_id TEXT, origin TEXT,
            budget_eligible INTEGER
        );
        """
    )
    connection.execute(
        "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            CALL,
            "2026-07-17T10:01:30Z",
            "fab",
            "provider",
            "model",
            10,
            2,
            0.25,
            "ok",
            ATTEMPT,
            "computed",
            "marginal",
            "estimated",
            "pricing",
            "pricing-v1",
            "production",
            None,
            "native",
            1,
        ),
    )
    connection.commit()
    connection.close()


def test_fab_receipts_trace_exactly_and_rollups_do_not_count(tmp_path: Path) -> None:
    fab_root = tmp_path / "fab"
    somm_path = tmp_path / "calls.sqlite"
    _fab_fixture(fab_root)
    _somm_fixture(somm_path)

    with MiltonStore(tmp_path / "milton.sqlite") as store:
        first = Ingestor(store).run(
            [FabAdapter(), SommAdapter()],
            roots={"fab": [fab_root], "somm": [somm_path]},
        )
        assert not first.failed, first.to_text()

        costs = [
            event.payload for event in store.events() if isinstance(event.payload, CostPayload)
        ]
        assert len(costs) == 3
        assert sum(
            payload.amount_usd or Decimal(0)
            for payload in costs
            if payload.observation_role is CostObservationRole.PRODUCTION
        ) == Decimal("0.25")
        assert (
            sum(1 for payload in costs if payload.observation_role is CostObservationRole.ROLLUP)
            == 2
        )
        assert store.accounting().selected_total_usd == Decimal("0.25")

        activity = build_activity(store, ExternalIdentity("george.entry", ENTRY), max_depth=8)
        identities = set(activity.related_identities)
        assert ExternalIdentity("fab.job", JOB) in identities
        assert ExternalIdentity("fab.attempt", ATTEMPT) in identities
        assert ExternalIdentity("somm.call", CALL) in identities
        assert ExternalIdentity("fab.verifier", "review-1") in identities
        assert ExternalIdentity("git.commit", SHA) in identities
        assert activity.report.total_cost_usd == Decimal("0.25")

        projection = store.outcome_attribution(outcome_types=["fab.job"])
        assert projection.selected_total_usd == Decimal("0.25")
        assert projection.attributed_total_usd == Decimal("0.25")
        assert projection.records[0].state is AttributionState.ATTRIBUTED
        assert projection.records[0].outcome is not None
        assert projection.records[0].outcome.reference == TypedRef("fab.job", JOB)

        second = Ingestor(store).run(
            [FabAdapter(), SommAdapter()],
            roots={"fab": [fab_root], "somm": [somm_path]},
        )
        assert all(summary.sources_unchanged for summary in second.adapters)
