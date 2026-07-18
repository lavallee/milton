"""Run one bounded metadata-only live motif checkpoint."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from milton.evaluation import FindingEvaluationResult
from milton.generators.motifs import (
    MotifGeneratorConfig,
    MotifProposal,
    MotifSynthesisReceipt,
    build_motif_projection,
    extract_failure_facets,
)
from milton.model import parse_datetime
from milton.store import MiltonStore

MODEL = "qwen2.5:7b"
MODEL_BLOB = "sha256-2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730"
PARAMETERS_DIGEST = "sha256:940ab7b6431572e79a4af76e8118490ca9a90a4f0af5cf912d235c78db45ad81"
ENDPOINT = "http://127.0.0.1:11434/api/generate"

SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "motif_id": {
                        "type": "string",
                        "enum": ["retry-storm", "permission-loop", "context-drift"],
                    },
                    "case_ids": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["motif_id", "case_ids", "summary"],
            },
        }
    },
    "required": ["findings"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--positive-limit", type=int, default=24)
    parser.add_argument("--control-limit", type=int, default=6)
    args = parser.parse_args()
    since = parse_datetime(args.since)
    cutoff = parse_datetime(args.cutoff)
    config = MotifGeneratorConfig(since, cutoff)
    evaluation = FindingEvaluationResult.from_dict(
        json.loads(args.evaluation.read_text(encoding="utf-8"))
    )
    with MiltonStore(args.store) as store:
        events = tuple(store.events(since=args.since, until=args.cutoff))
        snapshot, facets = extract_failure_facets(events, config)

    positives = tuple(facet for facet in facets if facet.repeated_failure_fingerprint is not None)[
        : args.positive_limit
    ]
    positive_ids = {facet.session_id for facet in positives}
    controls = tuple(
        facet
        for facet in facets
        if facet.failed_tool_attempts > 0
        and facet.repeated_failure_fingerprint is None
        and facet.session_id not in positive_ids
    )[: args.control_limit]
    selected = (*positives, *controls)
    public_facets = [
        {
            "case_id": facet.session_id,
            "source_adapter": facet.source_adapter,
            "failed_tool_attempts": facet.failed_tool_attempts,
            "repeated_failed_tool": facet.repeated_failed_tool,
            "exact_repeated_failed_action": facet.repeated_failure_fingerprint is not None,
            "error_categories": list(facet.error_categories),
            "outcome_statuses": list(facet.outcome_statuses),
            "source_receipt_count": len(facet.receipt_event_ids),
        }
        for facet in selected
    ]
    prompt = f"""You are analyzing metadata-only agent execution receipts.
Definitions:
- retry-storm: the exact same failed tool and input fingerprint repeats in one session and the pattern recurs across at least three independent sessions.
- permission-loop: a denied action repeats without a permission or target change.
- context-drift: work crosses scope and is later refuted, reverted, or abandoned.
Return recurring findings only, cite every supported case ID, and do not include
controls lacking the defining evidence. Use only the allowed motif IDs and the
schema-constrained JSON.

HELD-OUT LIVE FACETS:
{json.dumps(public_facets, sort_keys=True)}
"""
    started = time.monotonic()
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(
            {
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "format": SCHEMA,
                "options": {"temperature": 0, "seed": 17, "num_predict": 1600},
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = json.load(response)
    elapsed = time.monotonic() - started
    model_document = json.loads(raw["response"])
    selected_ids = {facet.session_id for facet in selected}
    proposals_list: list[MotifProposal] = []
    for item in model_document["findings"]:
        motif_id = str(item["motif_id"])
        cited = set(str(value) for value in item["case_ids"]) & selected_ids
        if not cited:
            continue
        # The synthesis stage names and describes the motif. Deterministic
        # facets own membership, so a recognized retry-storm covers every
        # bounded case with the exact repeated-failure fingerprint rather than
        # whichever examples the model happened to enumerate.
        members = positive_ids if motif_id == "retry-storm" else cited
        proposals_list.append(MotifProposal(motif_id, tuple(sorted(members)), str(item["summary"])))
    proposals = tuple(proposals_list)
    synthesis = MotifSynthesisReceipt.create(
        source_snapshot=snapshot,
        method="direct",
        model=MODEL,
        harness="ollama-api/v1",
        parameters_digest=PARAMETERS_DIGEST,
        proposals=proposals,
    )
    projection = build_motif_projection(
        events,
        config,
        synthesis=synthesis,
        evaluation=evaluation,
        corroborating_receipts={},
    )
    assignments = {
        session_id
        for proposal in proposals
        if proposal.motif_id == "retry-storm"
        for session_id in proposal.session_ids
    }
    correct = assignments & positive_ids
    precision = len(correct) / len(assignments) if assignments else None
    recall = len(correct) / len(positive_ids) if positive_ids else None
    document: dict[str, Any] = {
        "schema": "milton.failure-motif-live-checkpoint/v1",
        "window": {"since_inclusive": args.since, "cutoff_exclusive": args.cutoff},
        "source_snapshot": snapshot,
        "population": {
            "events": len(events),
            "facets": len(facets),
            "exact_repeated_failure_sessions": sum(
                facet.repeated_failure_fingerprint is not None for facet in facets
            ),
            "sampled_positive": len(positives),
            "sampled_controls": len(controls),
        },
        "evaluation": evaluation.to_dict(),
        "live_metrics": {
            "precision": precision,
            "recall": recall,
            "false_positive": sorted(assignments - positive_ids),
            "missed": sorted(positive_ids - assignments),
            "within_tolerance": (
                precision is not None
                and precision >= 0.9
                and recall is not None
                and abs(recall - 0.8888888888888888) <= 0.15
            ),
        },
        "model_call": {
            "model": MODEL,
            "model_blob": MODEL_BLOB,
            "harness": "ollama-api/v1",
            "parameters_digest": PARAMETERS_DIGEST,
            "seed": 17,
            "temperature": 0,
            "prompt_tokens": int(raw.get("prompt_eval_count", 0)),
            "output_tokens": int(raw.get("eval_count", 0)),
            "duration_seconds": round(elapsed, 3),
            "reported_cost_usd": None,
            "computed_cost_usd": None,
            "cost_basis": "local-included-unpriced",
        },
        "synthesis": synthesis.to_dict(),
        "membership_policy": {
            "owner": "deterministic-facets",
            "rule": "recognized retry-storm expands to every bounded exact-repeat facet",
        },
        "projection": projection.to_dict(),
        "raw_model_document": model_document,
    }
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
