"""Dependency-free command line surface for Milton's deterministic core."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from milton.activity import build_activity
from milton.adapters import BUILTIN_ADAPTERS, ContentPolicy, built_in_adapters
from milton.barnowl_effectiveness import DEFAULT_JOIN_COVERAGE_THRESHOLD
from milton.crosswalk import ExternalIdentity
from milton.errors import MiltonError
from milton.evaluation import FindingEvaluationResult
from milton.exports import build_chip_candidate_export, build_george_finding_candidate
from milton.findings import (
    EvidenceRef,
    FindingActivityProjection,
    FindingDisposition,
    FindingGrade,
    FindingKind,
    FindingLedger,
    FindingManifest,
    FindingRevision,
    build_finding_activity,
    build_finding_export,
)
from milton.generators import (
    GateDetectorConfig,
    GateDetectorProjection,
    GateSourceState,
    MemoryAuditConfig,
    MotifGeneratorConfig,
    MotifSynthesisReceipt,
    append_gate_findings,
    append_memory_findings,
    append_motif_findings,
    build_memory_audit,
    build_motif_projection,
    detect_george_gates,
    evaluate_gate_cases,
    extract_failure_facets,
    find_corroborating_receipts,
    read_gate_cases,
)
from milton.ingest import Ingestor
from milton.model import JsonValue, canonical_json, format_datetime, utc_now
from milton.outcomes import OUTCOME_PRECEDENCE
from milton.promotion import ProcedureCalibrationLedger, build_procedure_calibration
from milton.relations import (
    RelationDirection,
    RelationKind,
    RelationMethod,
    RelationRecord,
    RelationState,
    TypedRef,
)
from milton.store import MiltonStore
from milton.tuple_evidence import OutcomeTuple, build_tuple_evidence
from milton.version import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="milton", description="Understand what your agents did")
    parser.add_argument("--version", action="version", version=f"milton {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="initialize a local Milton data directory")
    init.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    init.add_argument("--findings", type=Path, default=Path(".milton/findings.jsonl"))

    report = subparsers.add_parser("report", help="summarize normalized events and coverage")
    report.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    report.add_argument("--since", help="report events at/after ISO timestamp or duration")
    report.add_argument("--format", choices=("text", "json"), default="text")

    accounting = subparsers.add_parser(
        "accounting", help="project costs with explicit provenance and deduplication precedence"
    )
    accounting.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    accounting.add_argument("--since", help="project events at/after ISO timestamp or duration")
    accounting.add_argument("--format", choices=("text", "json"), default="text")

    cost = subparsers.add_parser("cost", help="reconcile selected costs to typed outcomes")
    cost.add_argument("--per-outcome", action="store_true", required=True)
    cost.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    cost.add_argument("--since", help="select cost events at/after ISO timestamp or duration")
    cost.add_argument("--until", help="exclusive ISO8601 end for selected cost events")
    cost.add_argument("--outcome-type", action="append", choices=OUTCOME_PRECEDENCE, default=[])
    cost.add_argument("--format", choices=("text", "json"), default="text")

    effectiveness = subparsers.add_parser(
        "effectiveness", help="project privacy-safe effectiveness from exact outcome receipts"
    )
    effectiveness_commands = effectiveness.add_subparsers(
        dest="effectiveness_command", required=True
    )
    barnowl_effectiveness = effectiveness_commands.add_parser(
        "barnowl", help="project Barnowl raw yields and standardized semantic follow-up"
    )
    barnowl_effectiveness.add_argument("--store", type=Path, required=True)
    barnowl_effectiveness.add_argument("--since", help="inclusive ISO8601 event time")
    barnowl_effectiveness.add_argument("--until", help="exclusive ISO8601 event cutoff")
    barnowl_effectiveness.add_argument(
        "--join-coverage-threshold",
        default=str(DEFAULT_JOIN_COVERAGE_THRESHOLD),
        help="minimum exact receipt-call join rate in [0,1] (default: 0.95)",
    )
    barnowl_effectiveness.add_argument("--format", choices=("text", "json"), default="text")

    evidence = subparsers.add_parser(
        "evidence", help="export bounded evidence documents for downstream consumers"
    )
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    tuple_export = evidence_commands.add_parser(
        "export-tuple", help="export evidence for one implementation/profile/model/harness tuple"
    )
    tuple_export.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    tuple_export.add_argument("--implementation", required=True)
    tuple_export.add_argument("--profile", required=True)
    tuple_export.add_argument("--served-model", required=True)
    tuple_export.add_argument("--harness", required=True)
    tuple_export.add_argument("--since", help="inclusive ISO8601 start")
    tuple_export.add_argument("--cutoff", required=True, help="exclusive ISO8601 cutoff")
    tuple_export.add_argument("--minimum-observations", type=int, default=5)
    tuple_export.add_argument("--format", choices=("text", "json"), default="json")

    memory = subparsers.add_parser("memory", help="audit memory inventory and use evidence")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_audit = memory_commands.add_parser(
        "audit", help="project keep/park/retire evidence without mutating sources"
    )
    memory_audit.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    memory_audit.add_argument("--findings", type=Path, default=Path(".milton/findings.jsonl"))
    memory_audit.add_argument("--cutoff", help="exclusive ISO8601 cutoff")
    memory_audit.add_argument("--non-use-after-days", type=int, default=30)
    memory_audit.add_argument("--expires-after-days", type=int, default=30)
    memory_audit.add_argument("--append", action="store_true")
    memory_audit.add_argument("--recorded-at")
    memory_audit.add_argument("--format", choices=("text", "json"), default="text")

    activity = subparsers.add_parser(
        "activity", help="project activity connected to one native identity"
    )
    activity.add_argument("identity", help="identity as NAMESPACE=VALUE, e.g. fab.job=JOB_ID")
    activity.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    activity.add_argument("--max-depth", type=int, default=4)
    activity.add_argument("--format", choices=("text", "json"), default="text")

    relations = subparsers.add_parser(
        "relations", help="inspect typed directed relations without merging identity links"
    )
    relation_commands = relations.add_subparsers(dest="relations_command", required=True)
    relation_show = relation_commands.add_parser("show", help="traverse relations from one ref")
    relation_show.add_argument("reference", help="reference as NAMESPACE=VALUE")
    relation_show.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    relation_show.add_argument(
        "--direction", choices=tuple(RelationDirection), default=RelationDirection.BOTH
    )
    relation_show.add_argument(
        "--predicate", action="append", choices=tuple(RelationKind), default=[]
    )
    relation_show.add_argument("--max-depth", type=int, default=4)
    relation_show.add_argument("--format", choices=("text", "json"), default="text")

    findings = subparsers.add_parser(
        "findings", help="review the append-only finding and action-receipt lifecycle"
    )
    finding_commands = findings.add_subparsers(dest="findings_command", required=True)

    finding_list = finding_commands.add_parser("list", help="list current finding revisions")
    _add_finding_paths(finding_list)
    finding_list.add_argument("--kind", choices=tuple(FindingKind))
    finding_list.add_argument("--grade", choices=tuple(FindingGrade))
    finding_list.add_argument("--acted-on", action="store_true")
    finding_list.add_argument("--disposition", choices=tuple(FindingDisposition))
    finding_list.add_argument("--format", choices=("text", "json"), default="text")

    finding_show = finding_commands.add_parser("show", help="show evidence and action receipts")
    finding_show.add_argument("finding_id")
    _add_finding_paths(finding_show)
    finding_show.add_argument("--format", choices=("text", "json"), default="text")

    finding_generate = finding_commands.add_parser(
        "generate", help="detect findings without contacting or mutating source systems"
    )
    _add_finding_paths(finding_generate)
    finding_generate.add_argument(
        "--generator", choices=("george-gates", "failure-motifs"), required=True
    )
    finding_generate.add_argument("--since", required=True)
    finding_generate.add_argument("--until", help="exclusive reproducibility cutoff")
    finding_generate.add_argument(
        "--source-state",
        choices=("auto", *tuple(GateSourceState)),
        default="auto",
        help="override adapter-run freshness only for an audited fixture",
    )
    finding_generate.add_argument("--remint-threshold", type=int, default=3)
    finding_generate.add_argument("--remint-window-days", type=int, default=7)
    finding_generate.add_argument("--old-after-days", type=int, default=7)
    finding_generate.add_argument("--evaluation-cases", type=Path)
    finding_generate.add_argument("--synthesis", type=Path)
    finding_generate.add_argument("--evaluation-result", type=Path)
    finding_generate.add_argument("--promotion-floor", type=float, default=0.9)
    finding_generate.add_argument("--narrow-floor", type=float, default=0.8)
    finding_generate.add_argument("--recurrence-floor", type=int, default=1)
    finding_generate.add_argument("--aggregation-floor", type=int, default=1)
    finding_generate.add_argument("--minimum-recurrence", type=int, default=3)
    finding_generate.add_argument("--minimum-receipts", type=int, default=3)
    finding_generate.add_argument("--minimum-aggregation", type=int, default=3)
    finding_generate.add_argument("--expires-after-days", type=int, default=14)
    finding_generate.add_argument("--recorded-at")
    finding_generate.add_argument("--dry-run", action="store_true")
    finding_generate.add_argument("--format", choices=("text", "json"), default="text")

    finding_evaluate = finding_commands.add_parser(
        "evaluate", help="score a labeled held-out finding corpus"
    )
    finding_evaluate.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    finding_evaluate.add_argument("--cases", type=Path, required=True)
    finding_evaluate.add_argument("--promotion-floor", type=float, default=0.9)
    finding_evaluate.add_argument("--narrow-floor", type=float, default=0.8)
    finding_evaluate.add_argument("--recurrence-floor", type=int, default=1)
    finding_evaluate.add_argument("--aggregation-floor", type=int, default=1)
    finding_evaluate.add_argument("--format", choices=("text", "json"), default="text")

    finding_calibrate = finding_commands.add_parser(
        "calibrate-promotion",
        help="compare one Spindle promotion with exact Fab/Somm outcome receipts",
    )
    finding_calibrate.add_argument("spindle_promotion_receipt_id")
    finding_calibrate.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    finding_calibrate.add_argument(
        "--calibration",
        type=Path,
        default=Path(".milton/procedure-calibration.jsonl"),
    )
    finding_calibrate.add_argument("--format", choices=("text", "json"), default="text")

    finding_create = finding_commands.add_parser("create", help="append a finding")
    finding_create.add_argument("subject", help="stable generator-defined subject")
    finding_create.add_argument("--findings", type=Path, default=Path(".milton/findings.jsonl"))
    finding_create.add_argument("--kind", choices=tuple(FindingKind), required=True)
    finding_create.add_argument("--grade", choices=tuple(FindingGrade), required=True)
    finding_create.add_argument("--summary", required=True)
    finding_create.add_argument("--details", default="{}", metavar="JSON_OBJECT")
    finding_create.add_argument(
        "--evidence", action="append", required=True, metavar="EVENT_ID=ROLE"
    )
    finding_create.add_argument("--source-snapshot", required=True)
    finding_create.add_argument("--generator", required=True)
    finding_create.add_argument("--scope", default="{}", metavar="JSON_OBJECT")
    finding_create.add_argument("--coverage", type=float, required=True)
    finding_create.add_argument("--coverage-gap", action="append", default=[])
    finding_create.add_argument("--generated-at")
    finding_create.add_argument("--expires-at")
    finding_create.add_argument("--recorded-at")
    finding_create.add_argument("--format", choices=("text", "json"), default="text")

    finding_revise = finding_commands.add_parser("revise", help="append a graded revision")
    finding_revise.add_argument("finding_id")
    finding_revise.add_argument("--findings", type=Path, default=Path(".milton/findings.jsonl"))
    finding_revise.add_argument(
        "--grade",
        choices=(FindingGrade.LEAD, FindingGrade.CANDIDATE, FindingGrade.CORROBORATED),
        required=True,
    )
    finding_revise.add_argument("--summary")
    finding_revise.add_argument("--details", metavar="JSON_OBJECT")
    finding_revise.add_argument("--evidence", action="append", metavar="EVENT_ID=ROLE")
    finding_revise.add_argument("--recorded-at")
    finding_revise.add_argument("--format", choices=("text", "json"), default="text")

    finding_refute = finding_commands.add_parser("refute", help="append a refuted revision")
    finding_refute.add_argument("finding_id")
    finding_refute.add_argument("--findings", type=Path, default=Path(".milton/findings.jsonl"))
    finding_refute.add_argument("--summary", required=True, help="explicit refutation reason")
    finding_refute.add_argument("--details", metavar="JSON_OBJECT")
    finding_refute.add_argument("--recorded-at")
    finding_refute.add_argument("--format", choices=("text", "json"), default="text")

    finding_relate = finding_commands.add_parser(
        "relate", help="link an exact finding revision to an ingested receipt"
    )
    finding_relate.add_argument("finding_id")
    _add_finding_paths(finding_relate)
    action = finding_relate.add_mutually_exclusive_group(required=True)
    action.add_argument("--acts-on", metavar="NAMESPACE=VALUE")
    action.add_argument("--refutes", metavar="NAMESPACE=VALUE")
    action.add_argument("--evaluates", metavar="NAMESPACE=VALUE")
    action.add_argument("--promotes", metavar="NAMESPACE=VALUE")
    finding_relate.add_argument("--revision", help="exact revision id; defaults to current")
    finding_relate.add_argument(
        "--method", choices=tuple(RelationMethod), default=RelationMethod.HUMAN
    )
    finding_relate.add_argument("--confidence", type=float, default=1.0)
    finding_relate.add_argument("--evidence-event-id", action="append", default=[])
    finding_relate.add_argument("--note")
    finding_relate.add_argument("--recorded-at")
    finding_relate.add_argument("--format", choices=("text", "json"), default="text")

    finding_unrelate = finding_commands.add_parser(
        "unrelate", help="append an explicit refutation of an action relation"
    )
    finding_unrelate.add_argument("relation_id")
    finding_unrelate.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    finding_unrelate.add_argument("--note", required=True)
    finding_unrelate.add_argument("--evidence-event-id", action="append", default=[])
    finding_unrelate.add_argument("--recorded-at")
    finding_unrelate.add_argument("--format", choices=("text", "json"), default="text")

    finding_export = finding_commands.add_parser(
        "export", help="emit deterministic finding and receipt custody JSON"
    )
    finding_export.add_argument("finding_id")
    _add_finding_paths(finding_export)
    finding_export.add_argument("--contract", choices=("custody", "george"), default="custody")
    finding_export.add_argument(
        "--target",
        choices=("custody", "george", "chip"),
        help="export target; supersedes the legacy --contract selector",
    )
    finding_export.add_argument("--target-project", default="george")
    finding_export.add_argument("--format", choices=("json",), default="json")

    ingest = subparsers.add_parser("ingest", help="ingest local agent and infrastructure exhaust")
    _add_ingest_arguments(ingest)
    scan = subparsers.add_parser("scan", help="ingest sources and report in one pass")
    _add_ingest_arguments(scan)
    return parser


def _add_ingest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "adapters",
        nargs="*",
        choices=sorted(BUILTIN_ADAPTERS),
        help="adapter names (default: all built-ins)",
    )
    parser.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="ADAPTER=PATH",
        help="override/add a discovery root; repeatable",
    )
    parser.add_argument(
        "--content",
        choices=tuple(ContentPolicy),
        default=ContentPolicy.METADATA,
        help="metadata hashes by default; raw transcript bodies require 'full'",
    )
    parser.add_argument("--force", action="store_true", help="rescan unchanged sources")
    parser.add_argument(
        "--since",
        help="only emit records at/after an ISO timestamp or duration such as 7d or 24h",
    )
    parser.add_argument("--until", help="exclusive ISO8601 end of the ingestion window")
    parser.add_argument("--format", choices=("text", "json"), default="text")


def _add_finding_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store", type=Path, default=Path(".milton/events.db"))
    parser.add_argument("--findings", type=Path, default=Path(".milton/findings.jsonl"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            with MiltonStore(args.store):
                pass
            FindingLedger(args.findings).initialize()
            print(f"Initialized event store: {args.store}")
            print(f"Initialized findings ledger: {args.findings}")
            return 0

        if args.command == "report":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                print("Run `milton init` first, then ingest an adapter.", file=sys.stderr)
                return 2
            since = _parse_since(args.since)
            with MiltonStore(args.store) as store:
                report = store.report(since=format_datetime(since) if since else None)
            print(canonical_json(report.to_dict()) if args.format == "json" else report.to_text())
            return 0

        if args.command == "accounting":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                print("Run `milton init` first, then ingest an adapter.", file=sys.stderr)
                return 2
            since = _parse_since(args.since)
            with MiltonStore(args.store) as store:
                accounting_projection = store.accounting(
                    since=format_datetime(since) if since else None
                )
            print(
                canonical_json(accounting_projection.to_dict())
                if args.format == "json"
                else accounting_projection.to_text()
            )
            return 0

        if args.command == "cost":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                print("Run `milton init` first, then ingest an adapter.", file=sys.stderr)
                return 2
            since = _parse_since(args.since)
            until = _parse_timestamp(args.until, "--until")
            if since is not None and until is not None and since >= until:
                raise MiltonError("--since must be earlier than --until")
            with MiltonStore(args.store) as store:
                outcome_projection = store.outcome_attribution(
                    since=format_datetime(since) if since else None,
                    until=format_datetime(until) if until else None,
                    outcome_types=tuple(args.outcome_type) or None,
                )
            print(
                canonical_json(outcome_projection.to_dict())
                if args.format == "json"
                else outcome_projection.to_text()
            )
            return 0

        if args.command == "effectiveness" and args.effectiveness_command == "barnowl":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                return 2
            since = _parse_timestamp(args.since, "--since")
            until = _parse_timestamp(args.until, "--until")
            if since is not None and until is not None and since >= until:
                raise MiltonError("--since must be earlier than --until")
            threshold = _parse_unit_decimal(
                args.join_coverage_threshold, "--join-coverage-threshold"
            )
            with MiltonStore(args.store, read_only=True) as store:
                effectiveness_projection = store.barnowl_effectiveness(
                    since=since,
                    until=until,
                    join_coverage_threshold=threshold,
                )
            print(
                canonical_json(effectiveness_projection.to_dict())
                if args.format == "json"
                else effectiveness_projection.to_text()
            )
            return 0

        if args.command == "activity":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                return 2
            identity = _parse_identity(args.identity)
            with MiltonStore(args.store) as store:
                snapshot = build_activity(store, identity, max_depth=args.max_depth)
            print(
                canonical_json(snapshot.to_dict()) if args.format == "json" else snapshot.to_text()
            )
            return 0

        if args.command == "evidence" and args.evidence_command == "export-tuple":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                return 2
            since = _parse_timestamp(args.since, "--since")
            cutoff = _parse_timestamp(args.cutoff, "--cutoff")
            assert cutoff is not None  # argparse requires it
            with MiltonStore(args.store) as store:
                tuple_snapshot = build_tuple_evidence(
                    store,
                    OutcomeTuple(
                        args.implementation,
                        args.profile,
                        args.served_model,
                        args.harness,
                    ),
                    since=since,
                    cutoff=cutoff,
                    minimum_observations=args.minimum_observations,
                )
            print(
                canonical_json(tuple_snapshot.to_dict())
                if args.format == "json"
                else tuple_snapshot.to_text()
            )
            return 0

        if args.command == "relations" and args.relations_command == "show":
            if not args.store.exists():
                print(f"milton: event store does not exist: {args.store}", file=sys.stderr)
                return 2
            reference = _parse_ref(args.reference)
            direction = RelationDirection(args.direction)
            predicates = tuple(RelationKind(item) for item in args.predicate)
            with MiltonStore(args.store) as store:
                references, records = store.traverse_relations(
                    reference,
                    direction=direction,
                    max_depth=args.max_depth,
                    predicates=predicates or None,
                )
            if args.format == "json":
                relation_document: dict[str, JsonValue] = {
                    "schema_version": 1,
                    "root": reference.to_dict(),
                    "direction": direction.value,
                    "max_depth": args.max_depth,
                    "references": [item.to_dict() for item in references],
                    "relations": [item.to_dict() for item in records],
                }
                print(canonical_json(relation_document))
            else:
                print(_relations_text(reference, direction, args.max_depth, records))
            return 0

        if args.command == "findings":
            return _run_findings(args)

        if args.command == "memory":
            return _run_memory(args)

        if args.command in {"ingest", "scan"}:
            roots = _parse_sources(args.source)
            since = _parse_since(args.since)
            until = _parse_timestamp(args.until, "--until")
            if since is not None and until is not None and since >= until:
                raise MiltonError("--since must be earlier than --until")
            with MiltonStore(args.store) as store:
                summary = Ingestor(store).run(
                    built_in_adapters(args.adapters),
                    roots=roots,
                    content_policy=ContentPolicy(args.content),
                    since=since,
                    until=until,
                    force=bool(args.force),
                )
                scan_report = (
                    store.report(
                        since=format_datetime(since) if since else None,
                        until=format_datetime(until) if until else None,
                    )
                    if args.command == "scan"
                    else None
                )
            if args.format == "json":
                document = (
                    {"ingestion": summary.to_dict(), "report": scan_report.to_dict()}
                    if scan_report is not None
                    else summary.to_dict()
                )
                print(canonical_json(cast(JsonValue, document)))
            else:
                print(
                    f"{summary.to_text()}\n\n{scan_report.to_text()}"
                    if scan_report is not None
                    else summary.to_text()
                )
            return 1 if summary.failed else 0
    except MiltonError as error:
        print(f"milton: {error}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


def _parse_sources(values: Sequence[str]) -> dict[str, list[Path]]:
    roots: dict[str, list[Path]] = {}
    for value in values:
        adapter, separator, path = value.partition("=")
        if not separator or adapter not in BUILTIN_ADAPTERS or not path:
            expected = ", ".join(sorted(BUILTIN_ADAPTERS))
            raise MiltonError(f"invalid --source {value!r}; expected ADAPTER=PATH ({expected})")
        roots.setdefault(adapter, []).append(Path(path))
    return roots


def _run_memory(args: argparse.Namespace) -> int:
    if args.memory_command != "audit":
        raise MiltonError(f"unknown memory command: {args.memory_command}")
    _require_store(args.store)
    cutoff = _parse_timestamp(args.cutoff, "--cutoff") or utc_now()
    config = MemoryAuditConfig(
        cutoff,
        non_use_after_days=args.non_use_after_days,
        expires_after_days=args.expires_after_days,
    )
    with MiltonStore(args.store) as store:
        projection = build_memory_audit(tuple(store.events()), config)
    inserted = replayed = 0
    if args.append:
        if not projection.candidates:
            raise MiltonError("memory audit produced no evidence-supported recommendation")
        inserted, replayed = append_memory_findings(
            FindingLedger(args.findings),
            projection,
            recorded_at=_parse_timestamp(args.recorded_at, "--recorded-at") or utc_now(),
        )
    document: dict[str, JsonValue] = {
        "schema_version": 1,
        "mode": "append" if args.append else "dry-run",
        "projection": projection.to_dict(),
        "emission": {"inserted": inserted, "replayed": replayed},
    }
    print(canonical_json(document) if args.format == "json" else _memory_audit_text(document))
    return 0


def _memory_audit_text(document: dict[str, JsonValue]) -> str:
    projection = document["projection"]
    assert isinstance(projection, dict)
    counts = projection["counts"]
    assert isinstance(counts, dict)
    coverage = projection["coverage"]
    assert isinstance(coverage, dict)
    lines = [
        "Milton memory audit",
        "",
        f"Items: {counts['items']}",
        f"Recommendations: keep={counts['keep']}, park={counts['park']}, retire={counts['retire']}",
        f"Unknown disposition: {counts['unknown']}",
    ]
    for system, raw in sorted(coverage.items()):
        assert isinstance(raw, dict)
        lines.append(
            f"  {system}: inventory={raw['inventory']}, unknown-items={raw['unknown_items']}"
        )
    return "\n".join(lines)


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    duration = re.fullmatch(r"([1-9][0-9]*)([dhm])", value)
    if duration:
        amount = int(duration.group(1))
        unit = duration.group(2)
        delta = {
            "d": timedelta(days=amount),
            "h": timedelta(hours=amount),
            "m": timedelta(minutes=amount),
        }[unit]
        return datetime.now(UTC) - delta
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MiltonError(f"invalid --since {value!r}; use ISO8601, 7d, 24h, or 30m") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MiltonError("--since timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _parse_identity(value: str) -> ExternalIdentity:
    namespace, separator, native_id = value.partition("=")
    if not separator or not namespace.strip() or not native_id.strip():
        raise MiltonError("identity must be NAMESPACE=VALUE, for example fab.job=JOB_ID")
    return ExternalIdentity(namespace, native_id)


def _parse_ref(value: str) -> TypedRef:
    identity = _parse_identity(value)
    return TypedRef.from_identity(identity)


def _relations_text(
    root: TypedRef,
    direction: RelationDirection,
    max_depth: int,
    records: tuple[RelationRecord, ...],
) -> str:
    lines = [
        "Milton relations",
        "",
        f"Root: {root.namespace}={root.value}",
        f"Traversal: {direction.value}; maximum depth {max_depth}",
        f"Current asserted relations: {len(records)}",
    ]
    for record in records:
        evidence = ",".join(record.evidence_event_ids) or "none"
        lines.append(
            f"  {record.subject.namespace}={record.subject.value} "
            f"--{record.predicate.value}/{record.method.value}--> "
            f"{record.object.namespace}={record.object.value} "
            f"(confidence={record.confidence:g}; evidence={evidence})"
        )
    return "\n".join(lines)


def _run_findings(args: argparse.Namespace) -> int:
    command = str(args.findings_command)
    if command == "generate":
        return _run_finding_generation(args)
    if command == "evaluate":
        _require_store(args.store)
        cases = read_gate_cases(args.cases)
        with MiltonStore(args.store) as store:
            evaluation = evaluate_gate_cases(
                cases,
                store,
                promotion_floor=args.promotion_floor,
                narrow_floor=args.narrow_floor,
                recurrence_floor=args.recurrence_floor,
                aggregation_floor=args.aggregation_floor,
            )
        print(
            canonical_json(evaluation.to_dict())
            if args.format == "json"
            else _gate_evaluation_text(evaluation.to_dict())
        )
        return 0
    if command == "calibrate-promotion":
        _require_store(args.store)
        with MiltonStore(args.store) as store:
            calibration = build_procedure_calibration(
                store,
                spindle_promotion_receipt_id=args.spindle_promotion_receipt_id,
            )
        appended = ProcedureCalibrationLedger(args.calibration).append(calibration)
        document = {**calibration.to_dict(), "calibration_appended": appended}
        if args.format == "json":
            print(canonical_json(cast(JsonValue, document)))
        else:
            print(
                f"Procedure promotion {calibration.spindle_promotion_receipt_id}\n\n"
                f"Outcome: {calibration.state.value}\n"
                f"Metric: {calibration.metric or 'unknown'}\n"
                f"Baseline: {calibration.baseline_score}\n"
                f"Post-promotion: {calibration.post_score}\n"
                f"Calibration appended: {'yes' if appended else 'no (replay)'}"
            )
        return 0
    if command == "create":
        recorded_at = _parse_timestamp(args.recorded_at, "--recorded-at") or utc_now()
        generated_at = _parse_timestamp(args.generated_at, "--generated-at") or recorded_at
        record = FindingRevision.create(
            subject=args.subject,
            kind=FindingKind(args.kind),
            grade=FindingGrade(args.grade),
            summary=args.summary,
            details=_parse_json_object(args.details, "--details"),
            evidence=_parse_evidence(args.evidence),
            manifest=FindingManifest(
                source_snapshot=args.source_snapshot,
                generator=args.generator,
                scope=_parse_json_object(args.scope, "--scope"),
                coverage=args.coverage,
                coverage_gaps=tuple(args.coverage_gap),
                generated_at=generated_at,
                expires_at=_parse_timestamp(args.expires_at, "--expires-at"),
            ),
            recorded_at=recorded_at,
        )
        FindingLedger(args.findings).append(record)
        _print_finding_revision(record, args.format)
        return 0

    if command == "unrelate":
        _require_store(args.store)
        with MiltonStore(args.store) as store:
            history = tuple(store.relation_history(args.relation_id))
            if not history:
                raise MiltonError(f"relation does not exist: {args.relation_id}")
            current_relation = history[-1]
            if current_relation.predicate not in {
                RelationKind.ACTS_ON,
                RelationKind.REFUTES,
                RelationKind.EVALUATES,
                RelationKind.PROMOTES,
            }:
                raise MiltonError("findings unrelate only accepts finding-action relations")
            if current_relation.state is RelationState.REFUTED:
                raise MiltonError(f"relation is already refuted: {args.relation_id}")
            relation_evidence = _validated_evidence_ids(store, args.evidence_event_id)
            refuted = current_relation.refute(
                note=args.note,
                evidence_event_ids=relation_evidence,
                recorded_at=_parse_timestamp(args.recorded_at, "--recorded-at"),
            )
            store.append_relation(refuted)
        _print_relation(refuted, args.format)
        return 0

    ledger = FindingLedger(args.findings)
    if command in {"revise", "refute"}:
        current = _current_finding(ledger, args.finding_id)
        revision_recorded_at = _parse_timestamp(args.recorded_at, "--recorded-at")
        details = (
            _parse_json_object(args.details, "--details") if args.details is not None else None
        )
        evidence = _parse_evidence(args.evidence) if getattr(args, "evidence", None) else None
        grade = FindingGrade.REFUTED if command == "refute" else FindingGrade(args.grade)
        revised = current.revise(
            grade=grade,
            summary=args.summary,
            details=details,
            evidence=evidence,
            recorded_at=revision_recorded_at,
        )
        ledger.append(revised)
        _print_finding_revision(revised, args.format)
        return 0

    if command == "relate":
        _require_store(args.store)
        revisions = ledger.history(args.finding_id)
        if not revisions:
            raise MiltonError(f"finding does not exist: {args.finding_id}")
        selected_revision: FindingRevision | None = revisions[-1]
        if args.revision is not None:
            selected_revision = next(
                (item for item in revisions if item.revision_id == args.revision),
                None,
            )
            if selected_revision is None:
                raise MiltonError(
                    f"revision {args.revision} does not belong to finding {args.finding_id}"
                )
        assert selected_revision is not None
        predicate, receipt_value = _finding_relation_args(args)
        receipt_ref = _parse_ref(receipt_value)
        with MiltonStore(args.store) as store:
            receipt_event = store.event_for_ref(receipt_ref)
            if receipt_event is None:
                raise MiltonError(
                    "receipt reference is not present in the store; ingest it before relating"
                )
            extra_evidence = _validated_evidence_ids(store, args.evidence_event_id)
            relation_evidence = tuple(sorted(set((receipt_event.event_id, *extra_evidence))))
            relation = RelationRecord.create(
                subject=TypedRef("milton.finding-revision", selected_revision.revision_id),
                predicate=predicate,
                object=receipt_ref,
                confidence=args.confidence,
                method=RelationMethod(args.method),
                evidence_event_ids=relation_evidence,
                recorded_at=_parse_timestamp(args.recorded_at, "--recorded-at"),
                note=args.note,
            )
            store.append_relation(relation)
        _print_relation(relation, args.format)
        return 0

    if command == "export":
        target = args.target or args.contract
        if target == "chip":
            document = build_chip_candidate_export(ledger, args.finding_id)
        elif target == "george":
            document = build_george_finding_candidate(
                ledger, args.finding_id, target_project=args.target_project
            )
        else:
            _require_store(args.store)
            with MiltonStore(args.store) as store:
                document = build_finding_export(store, ledger, args.finding_id)
        print(canonical_json(document))
        return 0

    if command in {"list", "show"}:
        return _run_finding_read(args, ledger)
    raise MiltonError(f"unknown findings command: {command}")


def _run_finding_generation(args: argparse.Namespace) -> int:
    if args.generator == "failure-motifs":
        return _run_motif_generation(args)
    _require_store(args.store)
    since = _parse_since(args.since)
    assert since is not None  # parser requires --since
    cutoff = _parse_timestamp(args.until, "--until") or utc_now()
    if since >= cutoff:
        raise MiltonError("--since must be earlier than --until")
    with MiltonStore(args.store) as store:
        source_state = (
            _gate_source_state(store, cutoff)
            if args.source_state == "auto"
            else GateSourceState(args.source_state)
        )
        config = GateDetectorConfig(
            since=since,
            cutoff=cutoff,
            source_state=source_state,
            remint_threshold=args.remint_threshold,
            remint_window_days=args.remint_window_days,
            old_after_days=args.old_after_days,
        )
        projection = detect_george_gates(
            store.events(since=format_datetime(since), until=format_datetime(cutoff)),
            config,
        )
        evaluation = (
            evaluate_gate_cases(
                read_gate_cases(args.evaluation_cases),
                store,
                promotion_floor=args.promotion_floor,
                narrow_floor=args.narrow_floor,
                recurrence_floor=args.recurrence_floor,
                aggregation_floor=args.aggregation_floor,
            )
            if args.evaluation_cases is not None
            else None
        )

    surface_rules = set(evaluation.surface_rules) if evaluation is not None else set()
    eligible_candidates = tuple(
        candidate for candidate in projection.candidates if candidate.rule in surface_rules
    )
    eligible_projection = GateDetectorProjection(
        projection.config,
        projection.source_snapshot,
        projection.assessments,
        eligible_candidates,
    )
    inserted = replayed = 0
    if not args.dry_run:
        if evaluation is None:
            raise MiltonError("appending generated findings requires --evaluation-cases")
        if not eligible_candidates:
            raise MiltonError("no detected finding belongs to a rule approved for surfacing")
        recorded_at = _parse_timestamp(args.recorded_at, "--recorded-at") or utc_now()
        inserted, replayed = append_gate_findings(
            FindingLedger(args.findings),
            eligible_projection,
            recorded_at=recorded_at,
        )

    emission_document: dict[str, JsonValue] = {
        "surface_rules": cast(JsonValue, sorted(rule.value for rule in surface_rules)),
        "max_generator_grade": FindingGrade.LEAD.value,
        "candidates": cast(JsonValue, [candidate.to_dict() for candidate in eligible_candidates]),
        "inserted": inserted,
        "replayed": replayed,
    }
    document: dict[str, JsonValue] = {
        "schema_version": 1,
        "mode": "dry-run" if args.dry_run else "append",
        "projection": projection.to_dict(),
        "evaluation": evaluation.to_dict() if evaluation is not None else None,
        "emission": emission_document,
    }
    print(canonical_json(document) if args.format == "json" else _gate_generation_text(document))
    return 0


def _run_motif_generation(args: argparse.Namespace) -> int:
    _require_store(args.store)
    since = _parse_since(args.since)
    assert since is not None
    cutoff = _parse_timestamp(args.until, "--until") or utc_now()
    if since >= cutoff:
        raise MiltonError("--since must be earlier than --until")
    config = MotifGeneratorConfig(
        since,
        cutoff,
        minimum_recurrence=args.minimum_recurrence,
        minimum_receipts=args.minimum_receipts,
        minimum_aggregation=args.minimum_aggregation,
        expires_after_days=args.expires_after_days,
    )
    synthesis = (
        MotifSynthesisReceipt.from_dict(_read_json_file(args.synthesis, "--synthesis"))
        if args.synthesis is not None
        else None
    )
    evaluation = (
        FindingEvaluationResult.from_dict(
            _read_json_file(args.evaluation_result, "--evaluation-result")
        )
        if args.evaluation_result is not None
        else None
    )
    with MiltonStore(args.store) as store:
        events = tuple(store.events(since=format_datetime(since), until=format_datetime(cutoff)))
        _, facets = extract_failure_facets(events, config)
        proposed_sessions = (
            {session_id for proposal in synthesis.proposals for session_id in proposal.session_ids}
            if synthesis is not None
            else set()
        )
        corroborating_receipts = find_corroborating_receipts(
            store,
            tuple(facet for facet in facets if facet.session_id in proposed_sessions),
            cutoff,
        )
    projection = build_motif_projection(
        events,
        config,
        synthesis=synthesis,
        evaluation=evaluation,
        corroborating_receipts=corroborating_receipts,
    )
    inserted = replayed = 0
    if not args.dry_run:
        if synthesis is None or evaluation is None:
            raise MiltonError(
                "appending failure motifs requires --synthesis and --evaluation-result"
            )
        if not projection.candidates:
            raise MiltonError("no failure motif meets evaluation and evidence floors")
        inserted, replayed = append_motif_findings(
            FindingLedger(args.findings),
            projection,
            recorded_at=_parse_timestamp(args.recorded_at, "--recorded-at") or utc_now(),
        )
    document: dict[str, JsonValue] = {
        "schema_version": 1,
        "mode": "dry-run" if args.dry_run else "append",
        "projection": projection.to_dict(),
        "emission": {
            "maximum_grade": FindingGrade.CANDIDATE.value,
            "inserted": inserted,
            "replayed": replayed,
        },
    }
    print(canonical_json(document) if args.format == "json" else canonical_json(document))
    return 0


def _read_json_file(path: Path, option: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MiltonError(f"cannot read {option} document {path}: {error}") from error
    if not isinstance(raw, dict):
        raise MiltonError(f"{option} document must be a JSON object")
    return raw


def _run_finding_read(args: argparse.Namespace, ledger: FindingLedger) -> int:
    command = str(args.findings_command)
    if command == "show":
        current = _current_finding(ledger, args.finding_id)
        history = ledger.history(current.finding_id)
        if args.store.exists():
            with MiltonStore(args.store) as store:
                show_projection = build_finding_activity(store, ledger, current.finding_id)
            if args.format == "json":
                print(canonical_json(show_projection.to_dict()))
            else:
                print(show_projection.to_text())
            return 0
        document: dict[str, JsonValue] = {
            "schema_version": 1,
            "finding": current.to_dict(),
            "finding_history": [item.to_dict() for item in history],
            "activity": None,
        }
        print(canonical_json(document) if args.format == "json" else _finding_text(current, None))
        return 0

    if (args.acted_on or args.disposition is not None) and not args.store.exists():
        raise MiltonError("action filters require an existing event store")
    optional_store: MiltonStore | None = MiltonStore(args.store) if args.store.exists() else None
    try:
        selected: list[tuple[FindingRevision, FindingActivityProjection | None]] = []
        for finding in sorted(ledger.current().values(), key=lambda item: item.finding_id):
            if args.kind is not None and finding.kind is not FindingKind(args.kind):
                continue
            if args.grade is not None and finding.grade is not FindingGrade(args.grade):
                continue
            list_projection = (
                build_finding_activity(optional_store, ledger, finding.finding_id)
                if optional_store is not None
                else None
            )
            if args.acted_on and (list_projection is None or not list_projection.acted_on):
                continue
            if args.disposition is not None and (
                list_projection is None
                or list_projection.disposition is not FindingDisposition(args.disposition)
            ):
                continue
            selected.append((finding, list_projection))
    finally:
        if optional_store is not None:
            optional_store.close()

    if args.format == "json":
        rows: list[JsonValue] = []
        for finding, row_projection in selected:
            activity = row_projection.to_dict() if row_projection is not None else None
            rows.append({"finding": finding.to_dict(), "activity": activity})
        print(canonical_json({"schema_version": 1, "findings": rows}))
    else:
        lines = ["Milton findings", "", f"Current findings: {len(selected)}"]
        for finding, row_projection in selected:
            disposition = (
                row_projection.disposition.value if row_projection is not None else "unknown"
            )
            lines.append(
                f"  {finding.finding_id} [{finding.kind.value}/{finding.grade.value}; "
                f"{disposition}] {finding.summary}"
            )
        print("\n".join(lines))
    return 0


def _current_finding(ledger: FindingLedger, finding_id: str) -> FindingRevision:
    current = ledger.current().get(finding_id)
    if current is None:
        raise MiltonError(f"finding does not exist: {finding_id}")
    return current


def _parse_json_object(value: str, option: str) -> dict[str, JsonValue]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise MiltonError(f"{option} must be valid JSON: {error.msg}") from error
    if not isinstance(parsed, dict):
        raise MiltonError(f"{option} must be a JSON object")
    return cast(dict[str, JsonValue], parsed)


def _parse_evidence(values: Sequence[str]) -> tuple[EvidenceRef, ...]:
    evidence: list[EvidenceRef] = []
    for value in values:
        event_id, separator, role = value.partition("=")
        if not separator or not event_id.strip() or not role.strip():
            raise MiltonError("evidence must be EVENT_ID=ROLE")
        evidence.append(EvidenceRef(event_id, role))
    return tuple(evidence)


def _parse_timestamp(value: str | None, option: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MiltonError(f"{option} must be an ISO8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MiltonError(f"{option} must include a timezone")
    return parsed.astimezone(UTC)


def _parse_unit_decimal(value: str, option: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise MiltonError(f"{option} must be a decimal between 0 and 1") from error
    if not parsed.is_finite() or not Decimal(0) <= parsed <= Decimal(1):
        raise MiltonError(f"{option} must be between 0 and 1")
    return parsed


def _finding_relation_args(args: argparse.Namespace) -> tuple[RelationKind, str]:
    for attribute, predicate in (
        ("acts_on", RelationKind.ACTS_ON),
        ("refutes", RelationKind.REFUTES),
        ("evaluates", RelationKind.EVALUATES),
        ("promotes", RelationKind.PROMOTES),
    ):
        value = getattr(args, attribute)
        if value is not None:
            return predicate, str(value)
    raise MiltonError("one finding action relation is required")


def _validated_evidence_ids(store: MiltonStore, event_ids: Sequence[str]) -> tuple[str, ...]:
    for event_id in event_ids:
        if store.get_event(event_id) is None:
            raise MiltonError(f"evidence event does not exist: {event_id}")
    return tuple(sorted(set(event_ids)))


def _require_store(path: Path) -> None:
    if not path.exists():
        raise MiltonError(f"event store does not exist: {path}")


def _gate_source_state(store: MiltonStore, cutoff: datetime) -> GateSourceState:
    coverage = store.source_coverage().get("george")
    if coverage is None:
        return GateSourceState.UNKNOWN
    if coverage.status != "ok":
        return GateSourceState.STALE
    if coverage.until_at is not None and coverage.until_at >= cutoff:
        return GateSourceState.FRESH
    if coverage.until_at is None and coverage.last_ingested_at >= cutoff:
        return GateSourceState.FRESH
    return GateSourceState.STALE


def _gate_generation_text(document: dict[str, JsonValue]) -> str:
    projection = document.get("projection")
    counts = projection.get("counts") if isinstance(projection, dict) else {}
    emission = document.get("emission")
    emitted = emission.get("candidates") if isinstance(emission, dict) else []
    return "\n".join(
        [
            "Milton George gate findings",
            "",
            f"Mode: {document.get('mode')}",
            f"Detected: {counts.get('detected', 0) if isinstance(counts, dict) else 0}",
            f"Abstained: {counts.get('abstained', 0) if isinstance(counts, dict) else 0}",
            f"Eligible finding leads: {len(emitted) if isinstance(emitted, list) else 0}",
            "Source systems contacted or mutated: no",
        ]
    )


def _gate_evaluation_text(document: dict[str, JsonValue]) -> str:
    lines = [
        "Milton George gate evaluation",
        "",
        f"Corpus: {document.get('corpus_snapshot')}",
    ]
    rules = document.get("rules")
    if isinstance(rules, list):
        for row in rules:
            if not isinstance(row, dict):
                continue
            precision = row.get("precision")
            rendered = f"{precision:.3f}" if isinstance(precision, int | float) else "unavailable"
            coverage = row.get("coverage")
            rendered_coverage = f"{coverage:.3f}" if isinstance(coverage, int | float) else "0"
            lines.append(
                f"  {row.get('rule')}: precision={rendered}; "
                f"coverage={rendered_coverage}; decision={row.get('decision')}"
            )
    return "\n".join(lines)


def _print_finding_revision(record: FindingRevision, format_name: str) -> None:
    if format_name == "json":
        print(canonical_json(record.to_dict()))
    else:
        print(_finding_text(record, None))


def _finding_text(record: FindingRevision, disposition: str | None) -> str:
    lines = [
        f"Finding {record.finding_id}",
        "",
        f"Revision: {record.revision_id}",
        f"Kind: {record.kind.value}",
        f"Grade: {record.grade.value}",
        f"Disposition: {disposition or 'not projected'}",
        f"Summary: {record.summary}",
        f"Evidence: {len(record.evidence)}",
        f"Generator: {record.manifest.generator}",
        f"Coverage: {record.manifest.coverage:g}",
    ]
    return "\n".join(lines)


def _print_relation(record: RelationRecord, format_name: str) -> None:
    if format_name == "json":
        print(canonical_json(record.to_dict()))
    else:
        print(
            f"{record.relation_id}: {record.subject.namespace}={record.subject.value} "
            f"--{record.predicate.value}/{record.state.value}--> "
            f"{record.object.namespace}={record.object.value}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
