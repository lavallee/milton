from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from milton.adapters import ChipAdapter, ContentPolicy, FabAdapter, SommAdapter, SpindleAdapter
from milton.cli import main
from milton.exports import build_chip_candidate_export
from milton.findings import (
    EvidenceRef,
    FindingDisposition,
    FindingGrade,
    FindingKind,
    FindingLedger,
    FindingManifest,
    FindingRevision,
    build_finding_activity,
)
from milton.ingest import Ingestor
from milton.promotion import (
    ProcedureCalibrationLedger,
    ProcedureOutcomeState,
    build_procedure_calibration,
    classify_procedure_outcome,
)
from milton.store import MiltonStore

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
PROJECTS = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("direction", "baseline", "post", "expected"),
    [
        ("higher", 0.5, 0.8, ProcedureOutcomeState.IMPROVEMENT),
        ("higher", 0.5, 0.2, ProcedureOutcomeState.REGRESSION),
        ("lower", 10.0, 8.0, ProcedureOutcomeState.IMPROVEMENT),
        ("lower", 10.0, 12.0, ProcedureOutcomeState.REGRESSION),
        ("higher", 0.5, 0.5, ProcedureOutcomeState.INCONCLUSIVE),
        (None, 0.5, 0.8, ProcedureOutcomeState.INCONCLUSIVE),
    ],
)
def test_procedure_outcome_classification(
    direction: str | None,
    baseline: float,
    post: float,
    expected: ProcedureOutcomeState,
) -> None:
    assert classify_procedure_outcome(direction, baseline, post) is expected


def _finding(ledger: FindingLedger) -> FindingRevision:
    finding = FindingRevision.create(
        subject="procedure:retry-with-policy-change",
        kind=FindingKind.PROCEDURE_CANDIDATE,
        grade=FindingGrade.CANDIDATE,
        summary="Change policy or target before retrying an identical permission failure",
        details={
            "occurrence_refs": ["session:one", "session:two", "session:three"],
            "counterexample_refs": ["fixture:negative:clean-retry"],
            "fixture_refs": ["fixture:exception:policy-unavailable"],
        },
        evidence=(EvidenceRef("evt-procedure", "recurrence"),),
        manifest=FindingManifest(
            source_snapshot="procedure-source-v1",
            generator="milton.procedure-candidates/v1",
            scope={"content_policy": "metadata-only"},
            coverage=1,
            coverage_gaps=(),
            generated_at=NOW,
            expires_at=NOW + timedelta(days=30),
        ),
        recorded_at=NOW,
    )
    assert ledger.append(finding)
    return finding


def _environment(*source_paths: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (*(str(path) for path in source_paths), environment.get("PYTHONPATH")))
    )
    return environment


def _run(script: str, args: list[Path], environment: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", script, *(str(path) for path in args)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return cast(dict[str, Any], json.loads(result.stdout))


def test_real_chip_spindle_fab_somm_promotion_changes_milton_calibration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chip_root = PROJECTS / "chip"
    spindle_root = PROJECTS / "spindle"
    fab_root = PROJECTS / "fab"
    somm_root = PROJECTS / "somm"
    required = (
        chip_root / "src" / "chip" / "candidates.py",
        spindle_root / "src" / "spindle" / "evaluation.py",
        fab_root / "src" / "fab" / "receipts.py",
        somm_root / "packages" / "somm" / "src" / "somm" / "procedure_outcomes.py",
    )
    if not all(path.is_file() for path in required):
        pytest.skip("sibling factory repositories are not present")

    findings = FindingLedger(tmp_path / "findings.jsonl")
    finding = _finding(findings)
    export_path = tmp_path / "chip-export.json"
    export_path.write_text(
        json.dumps(build_chip_candidate_export(findings, finding.finding_id)),
        encoding="utf-8",
    )
    chip_ledger = tmp_path / "chip-private" / "candidates.jsonl"
    chip_receipts = tmp_path / "public" / "chip" / "candidate-receipts.jsonl"
    chip = _run(
        """
import json, sys
from chip.candidates import commission_candidate
document = json.load(open(sys.argv[1], encoding="utf-8"))
receipt = commission_candidate(sys.argv[2], document["candidate"], receipts_path=sys.argv[3])
print(json.dumps(receipt.to_dict()))
""",
        [export_path, chip_ledger, chip_receipts],
        _environment(chip_root / "src"),
    )
    candidate = json.loads(export_path.read_text(encoding="utf-8"))["candidate"]

    spindle_work = tmp_path / "spindle-work"
    spindle_work.mkdir()
    skill = spindle_work / "SKILL.md"
    skill.write_text(
        "# Permission retry\n\nChange policy or target before an identical retry.\n",
        encoding="utf-8",
    )
    runner = spindle_work / "runner.py"
    runner.write_text(
        """
import json, os
from pathlib import Path
fixture = json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text())
arm = os.environ["SPINDLE_EVAL_ARM"]
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(json.dumps({
    "score": fixture[arm], "passed": fixture[arm] >= 0.5,
    "skill_invoked": arm == "variant",
    "evidence": {"grader": "exact-fixture", "case": os.environ["SPINDLE_EVAL_CASE_ID"]},
    "metrics": {"successful_resolution": int(arm == "variant")}, "artifacts": []}))
""",
        encoding="utf-8",
    )
    fixture = spindle_work / "held.json"
    fixture.write_text(json.dumps({"baseline": 0.5, "variant": 0.8}), encoding="utf-8")
    manifest = spindle_work / "eval.toml"
    manifest.write_text(
        f'''schema_version = 1
id = "permission-retry-pilot"
skill = "permission-retry"
skill_path = "SKILL.md"
runner = ["{sys.executable}", "runner.py"]
seed = 17
min_held_out_cases = 1
min_improvement = 0.1
receipt_dir = "receipts"

[dimensions]
profile = "factory-procedure@1"
model = "fixture-model@1"
harness = "spindle-fixture/v1"
baseline_implementation = "raw-agent@1"

[[cases]]
id = "held-permission-loop"
split = "held_out"
fixture = "held.json"
tags = ["permission", "held-out"]

[origin]
schema = "spindle.procedure-origin/v1"
milton_finding_id = "{finding.finding_id}"
milton_revision_id = "{finding.revision_id}"
chip_candidate_id = "{candidate["candidateId"]}"
chip_receipt_id = "{chip["receiptId"]}"
''',
        encoding="utf-8",
    )
    spindle_eval = tmp_path / "public" / "spindle" / "evaluation-receipt.json"
    spindle_promotion = tmp_path / "public" / "spindle" / "promotion-receipt.json"
    spindle_state = tmp_path / "spindle-state"
    spindle = _run(
        """
import json, os, sys
from spindle.binding import record_evaluated_binding
from spindle.composition import ComposedSkill, Composition
from spindle.evaluation import load_manifest, record_promotion, run_evaluation
os.environ["SPINDLE_HOME"] = sys.argv[4]
manifest = load_manifest(sys.argv[1])
_, evaluation = run_evaluation(manifest, split="held_out", receipt_path=sys.argv[2])
composition = Composition(surface="repo:procedure-pilot", autonomy_mode="deterministic",
    skills=[ComposedSkill(manifest.skill, str(manifest.skill_path), "milton-candidate")])
binding = record_evaluated_binding(composition, doctrine_coordinate="procedure-doctrine@1",
    channel_versions={"milton-candidate": "1"}, evaluation_receipt=evaluation)
promotion = record_promotion(evaluation, binding, sys.argv[3])
print(json.dumps({"evaluation": evaluation, "promotion": promotion}))
""",
        [manifest, spindle_eval, spindle_promotion, spindle_state],
        _environment(spindle_root / "src"),
    )
    evaluation = spindle["evaluation"]
    promotion = spindle["promotion"]

    origin = {
        **promotion["origin"],
        "spindle_evaluation_receipt_id": evaluation["receipt_id"],
        "spindle_promotion_receipt_id": promotion["receipt_id"],
        "evaluation_tuple": promotion["evaluation_tuple"],
        "baseline_tuple": promotion["baseline_tuple"],
    }
    fab_state = tmp_path / "fab-state"
    fab_job_path = fab_state / "jobs" / "procedure-job-1"
    origin_path = tmp_path / "origin.json"
    origin_path.write_text(json.dumps(origin), encoding="utf-8")
    fab = _run(
        """
import json, sys
from pathlib import Path
from types import SimpleNamespace
from fab.receipts import write_job_outcome, write_job_submitted
origin = json.load(open(sys.argv[1], encoding="utf-8"))
spec = SimpleNamespace(id="procedure-job-1", backend="somm", cwd="/redacted",
    intent="procedure-outcome", submitter="milton-pilot", origin=origin)
path = Path(sys.argv[2])
write_job_submitted(path, spec=spec)
receipt = write_job_outcome(path, spec=spec, status="succeeded", reason=None,
    attempt_idx=0, semantic=True, reason_tags=["procedure-pilot"])
print(json.dumps(receipt))
""",
        [origin_path, fab_job_path],
        _environment(fab_root / "src"),
    )

    somm_db = tmp_path / "somm.sqlite"
    somm_input = tmp_path / "somm-input.json"
    somm_input.write_text(
        json.dumps(
            {
                "origin": {
                    key: value
                    for key, value in origin.items()
                    if key not in {"evaluation_tuple", "baseline_tuple", "schema"}
                },
                "evaluation_tuple": promotion["evaluation_tuple"],
                "baseline_tuple": promotion["baseline_tuple"],
                "fab_receipt_id": fab["receipt_id"],
            }
        ),
        encoding="utf-8",
    )
    somm = _run(
        """
import json, sys
from datetime import UTC, datetime
from somm.procedure_outcomes import record_procedure_outcome
from somm_core import Call, Outcome
from somm_core.repository import Repository
data = json.load(open(sys.argv[1], encoding="utf-8"))
repo = Repository(sys.argv[2])
repo.write_call(Call(id="procedure-call-baseline", ts=datetime.now(UTC), project="procedure-pilot",
    workload_id=None, prompt_id=None, provider="fixture", model="fixture-model@1",
    tokens_in=10, tokens_out=5, latency_ms=1, cost_usd=0, outcome=Outcome.OK,
    error_kind=None, prompt_hash="prompt-base", response_hash="response-base"))
repo.write_call(Call(id="procedure-call-1", ts=datetime.now(UTC), project="procedure-pilot",
    workload_id=None, prompt_id=None, provider="fixture", model="fixture-model@1",
    tokens_in=10, tokens_out=5, latency_ms=1, cost_usd=0, outcome=Outcome.OK,
    error_kind=None, prompt_hash="prompt", response_hash="response"))
receipt = record_procedure_outcome(repo, origin=data["origin"],
    evaluation_tuple=data["evaluation_tuple"], baseline_tuple=data["baseline_tuple"],
    metric="successful-resolution", direction="higher", baseline_score=0.5, post_score=0.8,
    baseline_receipt_ref="spindle.evaluation=" + data["origin"]["spindle_evaluation_receipt_id"],
    baseline_call_id="procedure-call-baseline",
    fab_receipt_id=data["fab_receipt_id"], fab_job_id="procedure-job-1",
    post_call_id="procedure-call-1")
print(json.dumps({"receipt_id": receipt.id, "payload": receipt.payload}))
""",
        [somm_input, somm_db],
        _environment(
            somm_root / "packages" / "somm" / "src",
            somm_root / "packages" / "somm-core" / "src",
        ),
    )

    store_path = tmp_path / "events.db"
    with MiltonStore(store_path) as store:
        summary = Ingestor(store).run(
            [ChipAdapter(), SpindleAdapter(), FabAdapter(), SommAdapter()],
            roots={
                "chip": [chip_receipts],
                "spindle": [spindle_eval, spindle_promotion],
                "fab": [fab_state],
                "somm": [somm_db],
            },
            content_policy=ContentPolicy.METADATA,
        )
        assert not summary.failed
        calibration = build_procedure_calibration(
            store,
            spindle_promotion_receipt_id=promotion["receipt_id"],
        )
        activity = build_finding_activity(store, findings, finding.finding_id)

    assert calibration.state is ProcedureOutcomeState.IMPROVEMENT
    assert calibration.baseline_score == 0.5
    assert calibration.post_score == 0.8
    assert calibration.fab_receipt_id == fab["receipt_id"]
    assert calibration.somm_receipt_id == f"eval-receipt:{somm['receipt_id']}"
    assert calibration.evaluation_tuple == promotion["evaluation_tuple"]
    assert calibration.baseline_tuple == promotion["baseline_tuple"]
    assert activity.disposition is FindingDisposition.PROMOTED

    calibration_path = tmp_path / "procedure-calibration.jsonl"
    assert ProcedureCalibrationLedger(calibration_path).append(calibration)
    assert not ProcedureCalibrationLedger(calibration_path).append(calibration)
    assert (
        main(
            [
                "findings",
                "calibrate-promotion",
                promotion["receipt_id"],
                "--store",
                str(store_path),
                "--calibration",
                str(calibration_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    cli_output = json.loads(capsys.readouterr().out)
    assert cli_output["state"] == "improvement"
    assert cli_output["calibration_appended"] is False
    assert len(ProcedureCalibrationLedger(calibration_path).load()) == 1
