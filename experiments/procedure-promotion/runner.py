"""Dependency-free local-model runner and deterministic decision grader."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

MODEL = "qwen2.5:7b"
MODEL_BLOB = "sha256:2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730"
HARNESS = "ollama-chat/v1;temperature=0;num_predict=1024;format=decision-schema-v1"
BASE_SYSTEM = (
    "You are a factory recovery controller. Return only a JSON decision that "
    "matches the supplied schema. Use only the stated authority and alternatives."
)
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["repeat_identical", "change_target", "change_policy", "escalate"],
        },
        "fingerprint": {"type": "string"},
        "change": {"type": "string"},
        "success_evidence": {"type": "string"},
    },
    "required": ["action", "fingerprint", "change", "success_evidence"],
    "additionalProperties": False,
}


def prompt_for(case: dict[str, Any]) -> str:
    return "Choose the next recovery class for this observed operation.\n" + json.dumps(
        {
            "operation": case["operation"],
            "error": case["error"],
            "operation_input_fingerprint": case["fingerprint"],
            "identical_failures": case["identical_failures"],
            "authorized_equivalent_target": case["authorized_equivalent_target"],
            "policy_change_authorized": case["policy_change_authorized"],
        },
        sort_keys=True,
    )


def system_for(skill_text: str | None) -> str:
    if not skill_text:
        return BASE_SYSTEM
    return f"{BASE_SYSTEM}\n\nThe bound procedure follows:\n{skill_text}"


def call_ollama(case: dict[str, Any], skill_text: str | None) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_for(skill_text)},
            {"role": "user", "content": prompt_for(case)},
        ],
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "options": {"temperature": 0, "num_predict": 1024},
    }
    request = urllib.request.Request(
        os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    message = result.get("message") if isinstance(result, dict) else None
    text = message.get("content", "") if isinstance(message, dict) else ""
    return {
        "text": text,
        "tokens_in": int(result.get("prompt_eval_count", 0)),
        "tokens_out": int(result.get("eval_count", 0)),
        "duration_ns": int(result.get("total_duration", 0)),
    }


def parse_decision(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S)
    if fenced:
        candidate = fenced.group(1)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def grade(case: dict[str, Any], text: str) -> tuple[float, dict[str, Any]]:
    parsed = parse_decision(text)
    action = parsed.get("action") if parsed else None
    fingerprint = parsed.get("fingerprint") if parsed else None
    change = parsed.get("change") if parsed else None
    success = parsed.get("success_evidence") if parsed else None
    components = {
        "valid_json": parsed is not None,
        "correct_action": action == case["expected_action"],
        "exact_fingerprint": fingerprint == case["fingerprint"],
        "specific_change": isinstance(change, str) and bool(change.strip()),
        "success_evidence": isinstance(success, str) and bool(success.strip()),
        "avoids_identical_retry": action != "repeat_identical",
    }
    score = (
        0.60 * float(components["correct_action"])
        + 0.10 * float(components["exact_fingerprint"])
        + 0.10 * float(components["specific_change"])
        + 0.10 * float(components["success_evidence"])
        + 0.10 * float(components["avoids_identical_retry"])
    )
    evidence = {
        "grader": "milton.repeated-permission-decision/v1",
        "expected_action": case["expected_action"],
        "observed_action": action,
        "components": components,
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    return score, evidence


def main() -> None:
    fixture_path = Path(os.environ["SPINDLE_EVAL_FIXTURE"])
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    case_id = os.environ["SPINDLE_EVAL_CASE_ID"]
    case = next(item for item in cases if item["id"] == case_id)
    skill_enabled = os.environ["SPINDLE_EVAL_SKILL_ENABLED"] == "1"
    skill_text = (
        Path(os.environ["SPINDLE_EVAL_SKILL_FILE"]).read_text(encoding="utf-8")
        if skill_enabled
        else None
    )
    response = call_ollama(case, skill_text)
    score, evidence = grade(case, response["text"])
    evidence.update(
        {
            "model": MODEL,
            "model_blob": MODEL_BLOB,
            "harness": HARNESS,
            "tokens_in": response["tokens_in"],
            "tokens_out": response["tokens_out"],
            "duration_ns": response["duration_ns"],
        }
    )
    document = {
        "score": score,
        "passed": score >= 0.8,
        "skill_invoked": skill_enabled,
        "evidence": evidence,
        "metrics": {"policy_adherence": score},
        "artifacts": [],
    }
    Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(
        json.dumps(document, sort_keys=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
