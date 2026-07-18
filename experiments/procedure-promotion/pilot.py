"""Replay-safe orchestration for the A-4.6 local procedure-promotion pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = ROOT / "reports" / "evidence" / "procedure-promotion-2026-07-17"
STATE = ROOT / ".milton" / "procedure-promotion"
MODEL_ID = "qwen2.5:7b@sha256:2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730"
PROFILE = "factory-recovery-controller@1"
HARNESS = "ollama-chat/v1;temperature=0;num_predict=1024;format=decision-schema-v1"
BASELINE_IMPLEMENTATION = "raw-factory-recovery-controller@1"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") != encoded:
        raise RuntimeError(f"refusing to replace conflicting artifact: {path}")
    path.write_text(encoded, encoding="utf-8")


def _write_tuning_json(path: Path, value: object) -> None:
    """Write the current development result; held-out/public custody stays immutable."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare() -> dict[str, Any]:
    from chip.candidates import commission_candidate

    from milton.exports import build_chip_candidate_export
    from milton.findings import (
        EvidenceRef,
        FindingGrade,
        FindingKind,
        FindingLedger,
        FindingManifest,
        FindingRevision,
    )

    source = _read_json(HERE / "source-evidence.json")
    recorded_at = datetime(2026, 7, 17, 20, 0, tzinfo=UTC)
    evidence_ids = [ref.split("=", 1)[1] for ref in source["occurrence_refs"]]
    finding = FindingRevision.create(
        subject="procedure:repeated-permission-failure-recovery-v1",
        kind=FindingKind.PROCEDURE_CANDIDATE,
        grade=FindingGrade.CANDIDATE,
        summary=(
            "After two identical permission failures, choose an authorized target change, "
            "then an authorized policy change, otherwise escalate; never repeat unchanged."
        ),
        details={
            "source_finding_id": source["source_finding_id"],
            "source_synthesis_receipt_id": source["source_synthesis_receipt_id"],
            "source_evaluation_result_id": source["source_evaluation_result_id"],
            "procedure_ref": "experiments/procedure-promotion/SKILL.md",
            "occurrence_refs": source["occurrence_refs"],
            "counterexample_refs": source["counterexample_refs"],
            "fixture_refs": source["fixture_refs"],
            "source_limits": source["limits"],
        },
        evidence=tuple(
            [EvidenceRef(event_id, "source-occurrence") for event_id in evidence_ids]
            + [EvidenceRef(source["source_synthesis_receipt_id"], "source-synthesis")]
        ),
        manifest=FindingManifest(
            source_snapshot=source["source_snapshot"],
            generator="milton.procedure-candidates/v1",
            scope={
                "source_finding_id": source["source_finding_id"],
                "procedure": "repeated-permission-failure-recovery-v1",
                "population_sessions": source["limits"]["source_population_sessions"],
                "evaluated_sessions": source["limits"]["bounded_evaluation_sessions"],
            },
            coverage=(
                source["limits"]["bounded_evaluation_sessions"]
                / source["limits"]["source_population_sessions"]
            ),
            coverage_gaps=(
                "source motif does not establish procedure efficacy",
                "local policy-adherence evaluation is not production task success",
                "one later operational comparison cannot establish general effect",
            ),
            generated_at=recorded_at,
            expires_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        recorded_at=recorded_at,
    )
    finding_ledger = RESULTS / "milton-findings.jsonl"
    FindingLedger(finding_ledger).append(finding)
    export = build_chip_candidate_export(FindingLedger(finding_ledger), finding.finding_id)
    _write_json(RESULTS / "chip-candidate-export.json", export)
    chip_receipt = commission_candidate(
        RESULTS / "chip-candidates.jsonl",
        export["candidate"],
        receipts_path=RESULTS / "chip-candidate-receipts.jsonl",
    )
    receipt = chip_receipt.to_dict()
    _write_json(RESULTS / "chip-candidate-receipt.json", receipt)

    manifest = _manifest_text(finding, export["candidate"], receipt)
    manifest_path = RESULTS / "evaluation.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.is_file() and manifest_path.read_text(encoding="utf-8") != manifest:
        raise RuntimeError(f"refusing to replace conflicting artifact: {manifest_path}")
    manifest_path.write_text(manifest, encoding="utf-8")
    summary = {
        "schema": "milton.procedure-pilot-preparation/v1",
        "finding_id": finding.finding_id,
        "finding_revision_id": finding.revision_id,
        "chip_candidate_id": export["candidate"]["candidateId"],
        "chip_receipt_id": receipt["receiptId"],
        "manifest": str(manifest_path.relative_to(ROOT)),
        "replay_safe": True,
    }
    _write_json(RESULTS / "preparation.json", summary)
    return summary


def _manifest_text(finding: Any, candidate: Any, receipt: Any) -> str:
    development = _read_json(HERE / "fixtures" / "development.json")
    heldout = _read_json(HERE / "fixtures" / "heldout.json")
    cases: list[str] = []
    for split, rows, fixture in (
        ("development", development, HERE / "fixtures" / "development.json"),
        ("held_out", heldout, HERE / "fixtures" / "heldout.json"),
    ):
        for row in rows:
            cases.append(
                "\n".join(
                    (
                        "[[cases]]",
                        f'id = "{row["id"]}"',
                        f'split = "{split}"',
                        f'fixture = "{fixture}"',
                        'tags = ["permission-failure", "local-model"]',
                    )
                )
            )
    return (
        "\n".join(
            (
                "schema_version = 1",
                'id = "repeated-permission-recovery-v1"',
                'skill = "repeated-permission-failure-recovery"',
                f'skill_path = "{HERE / "SKILL.md"}"',
                f'runner = ["{sys.executable}", "{HERE / "runner.py"}"]',
                "timeout_seconds = 240",
                "seed = 17",
                "min_held_out_cases = 4",
                "min_improvement = 0.10",
                f'receipt_dir = "{RESULTS}"',
                "",
                "[dimensions]",
                f'profile = "{PROFILE}"',
                f'model = "{MODEL_ID}"',
                f'harness = "{HARNESS}"',
                f'baseline_implementation = "{BASELINE_IMPLEMENTATION}"',
                "",
                "[origin]",
                'schema = "spindle.procedure-origin/v1"',
                f'milton_finding_id = "{finding.finding_id}"',
                f'milton_revision_id = "{finding.revision_id}"',
                f'chip_candidate_id = "{candidate["candidateId"]}"',
                f'chip_receipt_id = "{receipt["receiptId"]}"',
                "",
                *cases,
                "",
            )
        )
        + "\n"
    )


def development() -> dict[str, Any]:
    from spindle.evaluation import load_manifest, run_evaluation

    manifest = load_manifest(RESULTS / "evaluation.toml")
    _, receipt = run_evaluation(
        manifest,
        split="development",
        receipt_path=RESULTS / "spindle-development-receipt.json",
    )
    summary = _evaluation_summary(receipt)
    _write_tuning_json(RESULTS / "development-summary.json", summary)
    return summary


def heldout() -> dict[str, Any]:
    existing_summary = RESULTS / "pilot-summary.json"
    if existing_summary.is_file():
        return _read_json(existing_summary)

    from fab.receipts import (
        attempt_id,
        write_attempt_finished,
        write_attempt_started,
        write_job_outcome,
        write_job_submitted,
    )
    from runner import RESPONSE_SCHEMA, grade, prompt_for, system_for
    from somm import llm
    from somm.procedure_outcomes import record_procedure_outcome
    from somm_core.repository import Repository
    from spindle.binding import record_evaluated_binding
    from spindle.composition import ComposedSkill, Composition
    from spindle.evaluation import load_manifest, record_promotion, run_evaluation

    from milton.adapters import (
        ChipAdapter,
        ContentPolicy,
        FabAdapter,
        SommAdapter,
        SpindleAdapter,
    )
    from milton.findings import FindingLedger, build_finding_activity
    from milton.ingest import Ingestor
    from milton.promotion import ProcedureCalibrationLedger, build_procedure_calibration
    from milton.store import MiltonStore

    manifest = load_manifest(RESULTS / "evaluation.toml")
    evaluation_path = RESULTS / "spindle-evaluation-receipt.json"
    promotion_path = RESULTS / "spindle-promotion-receipt.json"
    if evaluation_path.is_file():
        from spindle.evaluation import load_receipt

        evaluation = load_receipt(evaluation_path)
    else:
        _, evaluation = run_evaluation(
            manifest,
            split="held_out",
            receipt_path=evaluation_path,
        )
    evaluation_summary = _evaluation_summary(evaluation)
    _write_json(RESULTS / "heldout-summary.json", evaluation_summary)
    if not evaluation["promotion"]["eligible"]:
        summary = {
            "schema": "milton.procedure-promotion-pilot/v1",
            "status": "not-promoted",
            "evaluation": evaluation_summary,
            "reason": "Spindle held-out promotion floor was not met",
        }
        _write_json(existing_summary, summary)
        return summary

    if promotion_path.is_file():
        promotion = _read_json(promotion_path)
        binding_coordinate = promotion["binding"]["coordinate"]
    else:
        os.environ["SPINDLE_HOME"] = str(STATE / "spindle")
        composition = Composition(
            surface="repo:milton-procedure-pilot",
            autonomy_mode="deterministic",
            skills=[
                ComposedSkill(
                    manifest.skill,
                    "permission-recovery",
                    "repo",
                    source="milton-chip-candidate",
                    source_dir=str(manifest.skill_path.parent),
                )
            ],
        )
        binding = record_evaluated_binding(
            composition,
            doctrine_coordinate="factory-recovery-doctrine@1",
            channel_versions={"milton-chip-candidate": "1"},
            evaluation_receipt=evaluation,
        )
        promotion = record_promotion(evaluation, binding, promotion_path)
        binding_coordinate = binding.coordinate

    origin = {
        **promotion["origin"],
        "spindle_evaluation_receipt_id": evaluation["receipt_id"],
        "spindle_promotion_receipt_id": promotion["receipt_id"],
    }
    fab_origin = {
        **origin,
        "evaluation_tuple": promotion["evaluation_tuple"],
        "baseline_tuple": promotion["baseline_tuple"],
    }
    job_id = "milton-procedure-pilot-2026-07-17"
    job_path = STATE / "fab" / "jobs" / job_id
    spec = SimpleNamespace(
        id=job_id,
        backend="somm",
        cwd="/redacted/milton",
        intent="measure-bound-permission-recovery-procedure",
        submitter="milton-procedure-pilot",
        origin=fab_origin,
    )
    write_job_submitted(job_path, spec=spec)

    operational = _read_json(HERE / "fixtures" / "operational.json")
    skill_text = manifest.skill_path.read_text(encoding="utf-8")
    client = llm(project="milton-procedure-pilot", mode="observe")
    try:
        baseline_result = client.generate(
            prompt_for(operational),
            system=system_for(None),
            workload="procedure-operational-baseline",
            max_tokens=256,
            temperature=0,
            model="qwen2.5:7b",
            provider="ollama",
            no_fallback=True,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "permission_recovery_decision",
                    "schema": RESPONSE_SCHEMA,
                },
            },
            correlation_id="milton-procedure-pilot:baseline",
        )
        write_attempt_started(
            job_path,
            spec=spec,
            attempt_idx=0,
            backend="somm",
            launch={
                "backend": "somm",
                "model": MODEL_ID,
                "project": "milton-procedure-pilot",
                "workload": "procedure-operational-promoted",
                "max_tokens": 256,
            },
        )
        promoted_result = client.generate(
            prompt_for(operational),
            system=system_for(skill_text),
            workload="procedure-operational-promoted",
            max_tokens=256,
            temperature=0,
            model="qwen2.5:7b",
            provider="ollama",
            no_fallback=True,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "permission_recovery_decision",
                    "schema": RESPONSE_SCHEMA,
                },
            },
            correlation_id=attempt_id(job_id, 0),
        )
    finally:
        client.close()

    baseline_score, baseline_evidence = grade(operational, baseline_result.text)
    promoted_score, promoted_evidence = grade(operational, promoted_result.text)
    attempt_path = job_path / "attempts" / "0"
    attempt_path.mkdir(parents=True, exist_ok=True)
    _write_json(attempt_path / "native-receipt.json", {"call_id": promoted_result.call_id})
    write_attempt_finished(
        job_path,
        spec=spec,
        attempt_idx=0,
        backend="somm",
        outcome="succeeded",
        exit_code=0,
        detail=None,
    )
    fab_outcome = write_job_outcome(
        job_path,
        spec=spec,
        status="succeeded",
        reason=None,
        attempt_idx=0,
        semantic=True,
        reason_tags=["procedure-pilot", "model-graded"],
    )

    repo = Repository(client.config.db_path)
    baseline_call = repo.get_call(baseline_result.call_id)
    promoted_call = repo.get_call(promoted_result.call_id)
    if baseline_call is None or promoted_call is None:
        raise RuntimeError("Somm did not persist both operational calls")
    somm_receipt = record_procedure_outcome(
        repo,
        origin=origin,
        evaluation_tuple=promotion["evaluation_tuple"],
        baseline_tuple=promotion["baseline_tuple"],
        metric="repeated-permission-policy-adherence",
        direction="higher",
        baseline_score=baseline_score,
        post_score=promoted_score,
        baseline_receipt_ref=f"somm.call={baseline_result.call_id}",
        baseline_call_id=baseline_result.call_id,
        fab_receipt_id=fab_outcome["receipt_id"],
        fab_job_id=job_id,
        post_call_id=promoted_result.call_id,
    )
    _write_json(
        RESULTS / "somm-procedure-outcome-receipt.json",
        {
            "id": somm_receipt.id,
            "receipt_type": somm_receipt.receipt_type,
            "run_id": somm_receipt.run_id,
            "call_id": somm_receipt.call_id,
            "source_call_id": somm_receipt.source_call_id,
            "score": somm_receipt.score,
            "threshold": somm_receipt.threshold,
            "payload": somm_receipt.payload,
        },
    )
    _write_json(
        RESULTS / "operational-call-summary.json",
        {
            "schema": "milton.procedure-operational-comparison/v1",
            "case_id": operational["id"],
            "baseline": _call_summary(
                baseline_result, baseline_call, baseline_score, baseline_evidence
            ),
            "promoted": _call_summary(
                promoted_result, promoted_call, promoted_score, promoted_evidence
            ),
            "reported_cost": {
                "state": "unavailable",
                "reason": "Ollama emitted no provider invoice or reported dollar amount",
            },
            "computed_cost": {
                "state": "unavailable",
                "reason": "no local electricity, hardware, or opportunity-cost rate is configured",
            },
            "economic_kind": "included",
            "producer_sentinel_usd": 0.0,
            "producer_sentinel_interpretation": "compatibility field; not an economic zero",
        },
    )

    with MiltonStore(STATE / "milton-events.db") as store:
        ingest = Ingestor(store).run(
            [ChipAdapter(), SpindleAdapter(), FabAdapter(), SommAdapter()],
            roots={
                "chip": [RESULTS / "chip-candidate-receipts.jsonl"],
                "spindle": [
                    RESULTS / "spindle-evaluation-receipt.json",
                    RESULTS / "spindle-promotion-receipt.json",
                ],
                "fab": [STATE / "fab"],
                "somm": [client.config.db_path],
            },
            content_policy=ContentPolicy.METADATA,
        )
        if ingest.failed:
            raise RuntimeError(f"Milton ingest failed: {ingest.failed}")
        calibration = build_procedure_calibration(
            store,
            spindle_promotion_receipt_id=promotion["receipt_id"],
        )
        activity = build_finding_activity(
            store,
            FindingLedger(RESULTS / "milton-findings.jsonl"),
            origin["milton_finding_id"],
        )
    ProcedureCalibrationLedger(RESULTS / "milton-procedure-calibration.jsonl").append(calibration)
    summary = {
        "schema": "milton.procedure-promotion-pilot/v1",
        "status": "calibrated",
        "finding_id": origin["milton_finding_id"],
        "finding_revision_id": origin["milton_revision_id"],
        "chip_candidate_id": origin["chip_candidate_id"],
        "chip_receipt_id": origin["chip_receipt_id"],
        "spindle_evaluation_receipt_id": evaluation["receipt_id"],
        "spindle_promotion_receipt_id": promotion["receipt_id"],
        "spindle_binding_coordinate": binding_coordinate,
        "evaluation": evaluation_summary,
        "fab_job_id": job_id,
        "fab_receipt_id": fab_outcome["receipt_id"],
        "somm_receipt_id": somm_receipt.id,
        "baseline_call_id": baseline_result.call_id,
        "promoted_call_id": promoted_result.call_id,
        "calibration": calibration.to_dict(),
        "finding_disposition": activity.disposition.value,
        "limitations": [
            "held-out score measures adherence to a narrow recovery policy",
            "one synthetic operational case cannot establish general production efficacy",
            "local model cost is classified as included/unpriced rather than zero-cost",
        ],
    }
    _write_json(existing_summary, summary)
    return summary


def _evaluation_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    runs = receipt["runs"]
    return {
        "receipt_id": receipt["receipt_id"],
        "split_requested": receipt["split_requested"],
        "evaluation_tuple": receipt["evaluation_tuple"],
        "baseline_tuple": receipt["baseline_tuple"],
        "summary": receipt["summaries"][receipt["split_requested"]],
        "promotion": receipt["promotion"],
        "calls": [
            {
                "case_id": run["case_id"],
                "arm": run["arm"],
                "status": run["status"],
                "score": run.get("result", {}).get("score"),
                "evidence": run.get("result", {}).get("evidence"),
            }
            for run in runs
        ],
    }


def _call_summary(result: Any, call: Any, score: float, evidence: dict[str, Any]) -> dict[str, Any]:
    amount = None if call.cost_source == "local-included-unpriced" else call.cost_usd
    return {
        "call_id": result.call_id,
        "provider": result.provider,
        "model": result.model,
        "outcome": result.outcome.value,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
        "cost_observation": {
            "amount_usd": amount,
            "basis": call.cost_basis,
            "kind": call.cost_kind,
            "accuracy": call.cost_accuracy,
            "source": call.cost_source,
            "pricing_version": call.pricing_version,
        },
        "score": score,
        "evidence": evidence,
        "response_sha256": hashlib.sha256(result.text.encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prepare", "development", "heldout"), required=True)
    args = parser.parse_args()
    if args.phase == "prepare":
        result = prepare()
    elif args.phase == "development":
        result = development()
    else:
        result = heldout()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
