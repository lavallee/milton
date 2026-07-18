"""Run the bounded direct-versus-facet motif experiment against local Ollama."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL = "qwen2.5:7b"
MODEL_BLOB = "sha256-2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730"
MODEL_LICENSE = "Apache-2.0"
OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"
ALLOWED_MOTIFS = ("context-drift", "permission-loop", "retry-storm")
SEEDS = (17, 23)
OUTPUT_BUDGET = 1600
PARAMETERS_DIGEST = "sha256:940ab7b6431572e79a4af76e8118490ca9a90a4f0af5cf912d235c78db45ad81"

FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "motif_id": {"type": "string", "enum": list(ALLOWED_MOTIFS)},
                    "case_ids": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["motif_id", "case_ids", "summary"],
            },
        }
    },
    "required": ["findings"],
}


@dataclass(frozen=True)
class CallResult:
    document: dict[str, Any]
    prompt_tokens: int
    output_tokens: int
    duration_seconds: float


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases-v1.jsonl"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = read_cases(args.cases)
    heldout = [row for row in cases if row["partition"] == "heldout"]
    tuning = [row for row in cases if row["partition"] == "tuning"]
    runs = []
    for seed in SEEDS:
        runs.append(run_direct(tuning, heldout, seed))
        runs.append(run_facets(tuning, heldout, seed))
    report = summarize(cases, runs)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


def read_cases(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    ids = [str(row["case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("case ids must be unique")
    tuning_sessions = {row["session_id"] for row in rows if row["partition"] == "tuning"}
    heldout_sessions = {row["session_id"] for row in rows if row["partition"] == "heldout"}
    if tuning_sessions & heldout_sessions:
        raise ValueError("tuning and held-out sessions overlap")
    return rows


def run_direct(
    tuning: list[dict[str, Any]], heldout: list[dict[str, Any]], seed: int
) -> dict[str, Any]:
    prompt = (
        base_prompt(tuning, heldout)
        + """
Analyze the held-out cases directly. Return recurring findings only. Each
finding must cite at least three independent held-out case IDs. Do not emit a
finding for an isolated or clean case. Use only the allowed motif IDs.
"""
    )
    call = generate(prompt, FINDING_SCHEMA, seed=seed, budget=OUTPUT_BUDGET)
    return score("direct", seed, heldout, call.document, (call,))


def run_facets(
    tuning: list[dict[str, Any]], heldout: list[dict[str, Any]], seed: int
) -> dict[str, Any]:
    facets = deterministic_facets(heldout)
    cluster_prompt = f"""You are evaluating recurring operational failures.
Allowed motif IDs: {", ".join(ALLOWED_MOTIFS)}.
Cluster the supplied facets into findings. Each finding must cite at least
three independent case IDs. Do not emit isolated or clean cases. Return only
the schema-constrained document.

TUNING DEFINITIONS AND LABELED EXAMPLES:
{base_prompt(tuning, [])}

FACETS:
{json.dumps(facets, sort_keys=True)}
"""
    clusters = generate(cluster_prompt, FINDING_SCHEMA, seed=seed, budget=OUTPUT_BUDGET)
    return score("deterministic-facet-cluster", seed, heldout, clusters.document, (clusters,))


def deterministic_facets(cases: list[dict[str, Any]]) -> dict[str, Any]:
    facets = []
    for row in cases:
        signals = row["signals"]
        error = signals.get("error")
        if error in {"permission_denied", "sandbox_denied", "read_only"}:
            stage = "authorization"
        elif signals.get("scope_changes", 0) > 0:
            stage = "scope-control"
        elif error is not None:
            stage = "execution"
        else:
            stage = "completion"
        facets.append(
            {
                "case_id": row["case_id"],
                "failure_stage": stage,
                "attempts": signals.get("attempts"),
                "repeated_action": signals.get("repeated_action"),
                "error": error,
                "recovery": signals.get("recovery"),
                "outcome": signals.get("outcome"),
                "scope_changes": signals.get("scope_changes", 0),
            }
        )
    return {"facets": facets}


def base_prompt(tuning: list[dict[str, Any]], heldout: list[dict[str, Any]]) -> str:
    return f"""You are analyzing metadata-only agent execution receipts.
Allowed motif IDs: {", ".join(ALLOWED_MOTIFS)}.
Definitions:
- retry-storm: substantially identical failed action repeated without an effective change.
- permission-loop: a denied/read-only action repeated without changing permission or target.
- context-drift: work crosses or changes the requested scope and is later refuted, reverted, or abandoned.
Tuning examples are labeled demonstrations only. Never count them as held-out
evidence. Held-out expected labels are withheld. Return only the requested JSON.

TUNING:
{json.dumps(public_cases(tuning, include_label=True), sort_keys=True)}

HELDOUT:
{json.dumps(public_cases(heldout, include_label=False), sort_keys=True)}
"""


def public_cases(cases: list[dict[str, Any]], *, include_label: bool) -> list[dict[str, Any]]:
    fields = ("case_id", "session_id", "receipt_ids", "signals")
    output = [{name: row[name] for name in fields} for row in cases]
    if include_label:
        for source, target in zip(cases, output, strict=True):
            target["expected_motif"] = source["expected_motif"]
    return output


def generate(prompt: str, schema: dict[str, Any], *, seed: int, budget: int) -> CallResult:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0, "seed": seed, "num_predict": budget},
    }
    request = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = json.load(response)
    duration = time.monotonic() - started
    document = json.loads(raw["response"])
    return CallResult(
        document=document,
        prompt_tokens=int(raw.get("prompt_eval_count", 0)),
        output_tokens=int(raw.get("eval_count", 0)),
        duration_seconds=duration,
    )


def score(
    method: str,
    seed: int,
    cases: list[dict[str, Any]],
    document: dict[str, Any],
    calls: tuple[CallResult, ...],
) -> dict[str, Any]:
    known_ids = {row["case_id"] for row in cases}
    assignments: set[tuple[str, str]] = set()
    invalid_ids: list[str] = []
    for finding in document.get("findings", []):
        motif = str(finding["motif_id"])
        for case_id in finding["case_ids"]:
            if case_id not in known_ids:
                invalid_ids.append(str(case_id))
            else:
                assignments.add((str(case_id), motif))
    expected = {
        (str(row["case_id"]), str(row["expected_motif"]))
        for row in cases
        if row["expected_motif"] is not None
    }
    correct = assignments & expected
    false_positive = assignments - expected
    missed = expected - assignments
    recurring = {
        motif
        for motif in ALLOWED_MOTIFS
        if sum(assignment[1] == motif for assignment in assignments) >= 3
    }
    expected_motifs = {motif for _, motif in expected}
    return {
        "method": method,
        "seed": seed,
        "assignments": [list(item) for item in sorted(assignments)],
        "precision": len(correct) / len(assignments) if assignments else None,
        "recall": len(correct) / len(expected) if expected else None,
        "operator_value": len(recurring & expected_motifs) / len(expected_motifs),
        "counterexamples": {
            "false_positive": [list(item) for item in sorted(false_positive)],
            "missed": [list(item) for item in sorted(missed)],
            "invalid_case_ids": sorted(invalid_ids),
        },
        "usage": {
            "calls": len(calls),
            "prompt_tokens": sum(call.prompt_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "duration_seconds": round(sum(call.duration_seconds for call in calls), 3),
            "reported_cost_usd": None,
            "computed_cost_usd": None,
            "cost_basis": "local-included-unpriced",
        },
        "raw": document,
    }


def summarize(cases: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for method in ("direct", "deterministic-facet-cluster"):
        selected = [run for run in runs if run["method"] == method]
        assignment_sets = [{tuple(item) for item in run["assignments"]} for run in selected]
        union = assignment_sets[0] | assignment_sets[1]
        intersection = assignment_sets[0] & assignment_sets[1]
        methods[method] = {
            "precision_floor_passed": all(
                run["precision"] is not None and run["precision"] >= 0.9 for run in selected
            ),
            "precision": [run["precision"] for run in selected],
            "recall": [run["recall"] for run in selected],
            "operator_value": [run["operator_value"] for run in selected],
            "stability_jaccard": len(intersection) / len(union) if union else 1.0,
            "maintenance_units": 1 if method == "direct" else 2,
            "runs": selected,
        }
    eligible = [
        name
        for name, result in methods.items()
        if result["precision_floor_passed"]
        and result["stability_jaccard"] >= 0.8
        and min(result["operator_value"]) >= 2 / 3
    ]
    selected_method = max(
        eligible,
        key=lambda name: (
            min(methods[name]["operator_value"]),
            min(methods[name]["recall"]),
            methods[name]["stability_jaccard"],
            -methods[name]["maintenance_units"],
        ),
        default="none",
    )
    corpus_bytes = "\n".join(json.dumps(row, sort_keys=True) for row in cases).encode()
    return {
        "schema": "milton.failure-method-experiment/v1",
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "corpus": {
            "tuning_cases": sum(row["partition"] == "tuning" for row in cases),
            "heldout_cases": sum(row["partition"] == "heldout" for row in cases),
            "content_policy": "metadata-only",
            "independent_sessions": len({row["session_id"] for row in cases}),
        },
        "evaluation_tuple": {
            "generator": "milton.failure-motifs/v1",
            "model": MODEL,
            "model_blob": MODEL_BLOB,
            "model_license": MODEL_LICENSE,
            "parameters_digest": PARAMETERS_DIGEST,
            "harness": "ollama-api/v1",
            "seeds": list(SEEDS),
            "temperature": 0,
            "output_budget_per_method_per_seed": OUTPUT_BUDGET,
        },
        "methods": methods,
        "selection": {
            "method": selected_method,
            "rule": "floor precision/stability/operator value; rank operator value, recall, stability, then maintenance",
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
