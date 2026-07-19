"""Privacy-safe Barnowl effectiveness projection over exact Milton attribution."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from milton.crosswalk import CrosswalkRecord, JoinState
from milton.errors import ValidationError
from milton.model import (
    EventKind,
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
    format_datetime,
)
from milton.outcomes import (
    AttributionState,
    OutcomeAttributionProjection,
    OutcomeAttributionRecord,
    build_outcome_attribution,
)
from milton.relations import RelationRecord, RelationState

SCHEMA_VERSION = "milton.barnowl-effectiveness/v1"
BARNOWL_OUTCOME_TYPE = "barnowl.research-outcome"
DEFAULT_JOIN_COVERAGE_THRESHOLD = Decimal("0.95")
STANDARDIZED_JUDGMENTS = frozenset({"ADMITTED", "REJECTED", "CORROBORATED"})

_CLAIMABILITY_REASON_ORDER = (
    "below_join_threshold",
    "ambiguous_or_invalid_followup",
    "no_standardized_admissions",
    "insufficient_later_followup",
)
_RAW_YIELD_BUCKETS = ("ADMITTED", "REJECTED", "CORROBORATED", "error", "unmapped")
_GAP_NAMES = (
    "outside_window",
    "missing_target",
    "cross_domain",
    "fork",
    "cycle",
    "non_increasing_timestamp",
)


@dataclass(frozen=True, slots=True)
class _Receipt:
    event: NormalizedEvent
    coordinate: str
    workload: str
    attempt: tuple[str, str]
    call_ids: tuple[str | None, ...]
    treatment: tuple[str, str]
    authority_namespace: str
    domain: tuple[str, str, str]
    outcome_kind: str
    judgment: str | None
    error_kind: str | None
    predecessor: str | None

    @property
    def raw_bucket(self) -> str:
        if self.outcome_kind == "error":
            return "error"
        if self.judgment in STANDARDIZED_JUDGMENTS:
            assert self.judgment is not None
            return self.judgment
        return "unmapped"

    @property
    def sort_key(self) -> tuple[datetime, str]:
        return (self.event.occurred_at, self.coordinate)


@dataclass(frozen=True, slots=True)
class _Chain:
    receipts: tuple[_Receipt, ...]
    attributed_observations: int
    attributed_cost_usd: Decimal

    @property
    def contains_admitted(self) -> bool:
        return any(receipt.raw_bucket == "ADMITTED" for receipt in self.receipts)

    @property
    def terminal_bucket(self) -> str:
        return self.receipts[-1].raw_bucket

    @property
    def later_corroborated(self) -> bool:
        return self.contains_admitted and self.terminal_bucket == "CORROBORATED"

    @property
    def treatment(self) -> tuple[str, str] | None:
        treatments = {receipt.treatment for receipt in self.receipts}
        return next(iter(treatments)) if len(treatments) == 1 else None


@dataclass(frozen=True, slots=True)
class BarnowlEffectivenessProjection:
    """A deterministic aggregate document that never exposes private coordinates."""

    document: dict[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]:
        return self.document

    def to_text(self) -> str:
        document = cast(dict[str, Any], self.document)
        window = cast(dict[str, Any], document["window"])
        claimability = cast(dict[str, Any], document["semantic_effectiveness"])
        receipt_coverage = cast(dict[str, Any], document["receipt_coordinate_coverage"])
        allocation = cast(dict[str, Any], document["selected_window_allocation"])
        allocation_observations = cast(dict[str, Any], allocation["observations"])
        allocation_amounts = cast(dict[str, Any], allocation["amounts_usd"])
        reason_counts = cast(dict[str, Any], allocation["reason_counts"])
        funnel = cast(dict[str, Any], document["semantic_funnel"])
        gap_counts = cast(dict[str, Any], funnel["gap_counts"])
        raw_dimensions = cast(list[dict[str, Any]], document["raw_outcome_dimensions"])
        workload_groups = cast(list[dict[str, Any]], document["workload_groups"])
        treatment_groups = cast(list[dict[str, Any]], document["treatment_groups"])

        status = str(claimability["status"])
        reasons = ", ".join(cast(list[str], claimability["reasons"]))
        lines = [
            "Milton Barnowl effectiveness",
            "",
            "Amounts are selected observations; they are not automatically actual provider spend.",
            f"Window: since={window['since_inclusive'] or 'unbounded'}, "
            f"until={window['until_exclusive'] or 'unbounded'} (exclusive)",
            f"Join threshold: {document['join_coverage_threshold']} "
            f"({_percentage_from_rate(Decimal(str(document['join_coverage_threshold'])))}%)",
            (
                "Semantic effectiveness: eligible"
                if status == "eligible"
                else f"Semantic effectiveness: not claimable ({reasons})"
            ),
            "",
            "Receipt coordinate coverage:",
            f"  Total call slots: {receipt_coverage['total_call_slots']}",
            f"  Null call IDs: {receipt_coverage['null_call_ids']}",
            f"  Non-null call ID occurrences: {receipt_coverage['non_null_call_id_occurrences']}",
            f"  Distinct call IDs: {receipt_coverage['distinct_call_ids']}",
            "  Duplicate call IDs across receipts: "
            f"{receipt_coverage['duplicate_call_ids_across_receipts']}",
            "  Exact selected cost observations joined: "
            f"{receipt_coverage['exact_selected_cost_observations_joined']}",
            "  Receipt call ID occurrences exactly joined: "
            f"{receipt_coverage['receipt_call_id_occurrences_exactly_joined']}",
            "  Receipt call ID occurrences without selected cost: "
            f"{receipt_coverage['receipt_call_id_occurrences_without_selected_cost']}",
            "  Distinct receipt call IDs without selected cost: "
            f"{receipt_coverage['distinct_receipt_call_ids_without_selected_cost']}",
            f"  Exact join percentage: {_render_rate(receipt_coverage['exact_join_percentage'])}",
            "",
            "Selected-window allocation:",
            f"  Selected: {allocation_observations['selected']} observation(s), "
            f"${allocation_amounts['selected']}",
            f"  Attributed: {allocation_observations['attributed']['count']} observation(s), "
            f"{_render_rate(allocation_observations['attributed']['percentage'])}; "
            f"${allocation_amounts['attributed']['amount']}, "
            f"{_render_rate(allocation_amounts['attributed']['percentage'])} of cost",
            f"  Ambiguous: {allocation_observations['ambiguous']['count']} observation(s), "
            f"{_render_rate(allocation_observations['ambiguous']['percentage'])}; "
            f"${allocation_amounts['ambiguous']['amount']}, "
            f"{_render_rate(allocation_amounts['ambiguous']['percentage'])} of cost",
            f"  Unallocated: {allocation_observations['unallocated']['count']} observation(s), "
            f"{_render_rate(allocation_observations['unallocated']['percentage'])}; "
            f"${allocation_amounts['unallocated']['amount']}, "
            f"{_render_rate(allocation_amounts['unallocated']['percentage'])} of cost",
            "  Reason counts: "
            + (", ".join(f"{name}={count}" for name, count in reason_counts.items()) or "none"),
            "  Conservation: satisfied",
            "",
            "Raw outcome dimensions:",
        ]
        if not raw_dimensions:
            lines.append("  none")
        for row in raw_dimensions:
            outcome = cast(dict[str, Any], row["outcome"])
            label = outcome["judgment"] or outcome["error_kind"]
            lines.append(
                f"  workload={row['workload']} | "
                f"treatment={row['treatment_namespace']}@{row['manifest_sha256']} | "
                f"authority={row['authority_namespace']} | "
                f"domain={row['domain_namespace']}/{row['domain_object_type']} | "
                f"outcome={outcome['kind']}:{label} | "
                f"outcomes={row['receipt_outcomes']}, attributed=${row['attributed_cost_usd']}, "
                f"raw-yield={_render_rate(row['raw_yield_percentage'])}"
            )
        lines.extend(
            [
                "",
                "Semantic funnel:",
                f"  Valid domain chains: {funnel['valid_domain_chains']}",
                f"  Chains containing ADMITTED: {funnel['chains_containing_admitted']}",
                f"  Later-corroborated chains: {funnel['later_corroborated_chains']}",
                f"  Terminal REJECTED: {funnel['terminal_rejected_chains']}",
                f"  Terminal error: {funnel['terminal_error_chains']}",
                f"  Terminal unmapped: {funnel['terminal_unmapped_chains']}",
                f"  Awaiting later follow-up: {funnel['admitted_awaiting_followup_chains']}",
                "  Gaps: " + ", ".join(f"{name}={gap_counts[name]}" for name in _GAP_NAMES),
                "",
                "Workload groups:",
            ]
        )
        if not workload_groups:
            lines.append("  none")
        for row in workload_groups:
            yields = cast(dict[str, dict[str, Any]], row["raw_yields"])
            rendered_yields = ", ".join(
                f"{bucket}={values['outcomes']} ({_render_rate(values['percentage'])})"
                for bucket, values in yields.items()
                if values["outcomes"]
            )
            lines.append(
                f"  {row['workload']}: outcomes={row['receipt_outcomes']}, "
                f"attempts={row['distinct_attempts']}, calls={row['distinct_call_ids']}, "
                f"attributed=${row['attributed_cost_usd']}; yields={rendered_yields or 'none'}"
            )
        lines.extend(["", "Treatment groups:"])
        if not treatment_groups:
            lines.append("  none")
        for row in treatment_groups:
            yields = cast(dict[str, dict[str, Any]], row["raw_yields"])
            rendered_yields = ", ".join(
                f"{bucket}={values['outcomes']} ({_render_rate(values['percentage'])})"
                for bucket, values in yields.items()
                if values["outcomes"]
            )
            lines.append(
                f"  {row['treatment_namespace']}@{row['manifest_sha256']}: "
                f"outcomes={row['receipt_outcomes']}, attempts={row['distinct_attempts']}, "
                f"calls={row['distinct_call_ids']}, attributed=${row['attributed_cost_usd']}; "
                f"yields={rendered_yields or 'none'}"
            )
        return "\n".join(lines)


def build_barnowl_effectiveness(
    events: Iterable[NormalizedEvent],
    crosswalk_records: Iterable[CrosswalkRecord],
    relation_records: Iterable[RelationRecord],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    join_coverage_threshold: Decimal = DEFAULT_JOIN_COVERAGE_THRESHOLD,
) -> BarnowlEffectivenessProjection:
    """Build the offline projection without changing attribution or monetary selection."""

    _validate_inputs(since, until, join_coverage_threshold)
    all_events = tuple(events)
    all_receipts = tuple(
        sorted(
            (_parse_receipt(event) for event in all_events if _is_barnowl_outcome(event)),
            key=lambda receipt: receipt.sort_key,
        )
    )
    cutoff_receipts = tuple(
        receipt for receipt in all_receipts if until is None or receipt.event.occurred_at < until
    )
    selected_receipts = tuple(
        receipt
        for receipt in cutoff_receipts
        if _in_window(receipt.event.occurred_at, since=since, until=until)
    )
    selected_receipt_coordinates = {receipt.coordinate for receipt in selected_receipts}
    selected_cost_event_ids = {
        event.event_id
        for event in all_events
        if event.kind is EventKind.COST and _in_window(event.occurred_at, since=since, until=until)
    }

    attribution_events = tuple(
        event
        for event in all_events
        if (until is None or event.occurred_at < until)
        and (
            not _is_barnowl_outcome(event)
            or _barnowl_coordinate(event) in selected_receipt_coordinates
        )
    )
    crosswalks = _current_crosswalks_as_of(tuple(crosswalk_records), until)
    relations = _current_relations_as_of(tuple(relation_records), until)
    attribution = build_outcome_attribution(
        attribution_events,
        crosswalks,
        relations,
        cost_event_ids=selected_cost_event_ids,
        outcome_types=(BARNOWL_OUTCOME_TYPE,),
    )

    events_by_id = {event.event_id: event for event in attribution_events}
    records_by_receipt = _attributed_records_by_receipt(attribution.records)
    receipt_coverage = _receipt_coordinate_coverage(
        selected_receipts,
        attribution.records,
        events_by_id,
    )
    allocation = _selected_window_allocation(attribution)
    raw_dimensions = _raw_outcome_dimensions(
        selected_receipts,
        records_by_receipt,
        denominator=len(selected_receipts),
    )
    workload_groups = _aggregate_receipt_groups(
        selected_receipts,
        records_by_receipt,
        key=lambda receipt: (receipt.workload,),
        labels=("workload",),
    )
    treatment_groups = _aggregate_receipt_groups(
        selected_receipts,
        records_by_receipt,
        key=lambda receipt: receipt.treatment,
        labels=("treatment_namespace", "manifest_sha256"),
    )
    chains, gap_counts, invalid_receipts, invalid_components = _build_current_chains(
        selected_receipts,
        cutoff_receipts,
        records_by_receipt,
    )
    semantic_funnel = _semantic_funnel(
        chains,
        gap_counts,
        invalid_receipts,
        invalid_components,
        records_by_receipt,
    )
    exact_join_rate = _ratio(
        receipt_coverage["receipt_call_id_occurrences_exactly_joined"],
        receipt_coverage["non_null_call_id_occurrences"],
    )
    claimability = _claimability(
        exact_join_rate=exact_join_rate,
        threshold=join_coverage_threshold,
        attribution=attribution,
        gap_counts=gap_counts,
        chains=chains,
    )

    document: dict[str, JsonValue] = {
        "schema_version": SCHEMA_VERSION,
        "cutoff": format_datetime(until) if until is not None else None,
        "window": {
            "since_inclusive": format_datetime(since) if since is not None else None,
            "until_exclusive": format_datetime(until) if until is not None else None,
        },
        "join_coverage_threshold": _decimal_string(join_coverage_threshold),
        "semantic_effectiveness": claimability,
        "source_coverage": _source_coverage(selected_receipts, attribution, cutoff_receipts),
        "receipt_coordinate_coverage": cast(dict[str, JsonValue], receipt_coverage),
        "selected_window_allocation": cast(dict[str, JsonValue], allocation),
        "raw_outcome_dimensions": cast(list[JsonValue], raw_dimensions),
        "semantic_funnel": cast(dict[str, JsonValue], semantic_funnel),
        "workload_groups": cast(list[JsonValue], workload_groups),
        "treatment_groups": cast(list[JsonValue], treatment_groups),
    }
    return BarnowlEffectivenessProjection(document)


def _validate_inputs(
    since: datetime | None,
    until: datetime | None,
    threshold: Decimal,
) -> None:
    for name, value in (("since", since), ("until", until)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValidationError(f"Barnowl effectiveness {name} must include a timezone")
    if since is not None and until is not None and since >= until:
        raise ValidationError("Barnowl effectiveness since must be earlier than until")
    if not threshold.is_finite() or not Decimal(0) <= threshold <= Decimal(1):
        raise ValidationError("Barnowl effectiveness join threshold must be between 0 and 1")


def _is_barnowl_outcome(event: NormalizedEvent) -> bool:
    return (
        event.kind is EventKind.OUTCOME
        and isinstance(event.payload, OutcomePayload)
        and event.payload.outcome_type == BARNOWL_OUTCOME_TYPE
    )


def _barnowl_coordinate(event: NormalizedEvent) -> str:
    payload = event.payload
    if not isinstance(payload, OutcomePayload) or payload.reference is None:
        raise ValidationError("Barnowl outcome event must carry an exact reference")
    return payload.reference


def _parse_receipt(event: NormalizedEvent) -> _Receipt:
    coordinate = _barnowl_coordinate(event)
    attributes = event.attributes
    attempt = _mapping(attributes.get("attempt"), "attempt")
    treatment = _mapping(attributes.get("treatment_manifest"), "treatment_manifest")
    authority = _mapping(attributes.get("authority"), "authority")
    domain = _mapping(attributes.get("domain_object"), "domain_object")
    outcome = _mapping(attributes.get("outcome"), "outcome")
    raw_calls = attributes.get("somm_calls")
    if not isinstance(raw_calls, list):
        raise ValidationError("Barnowl outcome somm_calls must be a list")
    call_ids: list[str | None] = []
    for raw_call in raw_calls:
        call = _mapping(raw_call, "somm_calls item")
        call_id = call.get("call_id")
        if call_id is not None and not isinstance(call_id, str):
            raise ValidationError("Barnowl outcome call_id must be a string or null")
        call_ids.append(call_id)
    outcome_kind = _string(outcome, "kind", "outcome")
    judgment = outcome.get("judgment")
    error_kind = outcome.get("error_kind")
    if judgment is not None and not isinstance(judgment, str):
        raise ValidationError("Barnowl outcome judgment must be a string")
    if error_kind is not None and not isinstance(error_kind, str):
        raise ValidationError("Barnowl outcome error_kind must be a string")
    predecessor = attributes.get("supersedes_event_id")
    if predecessor is not None and not isinstance(predecessor, str):
        raise ValidationError("Barnowl supersedes_event_id must be a string")
    workload = attributes.get("workload")
    if not isinstance(workload, str):
        raise ValidationError("Barnowl outcome workload must be a string")
    return _Receipt(
        event=event,
        coordinate=coordinate,
        workload=workload,
        attempt=(
            _string(attempt, "namespace", "attempt"),
            _string(attempt, "attempt_id", "attempt"),
        ),
        call_ids=tuple(call_ids),
        treatment=(
            _string(treatment, "namespace", "treatment_manifest"),
            _string(treatment, "manifest_sha256", "treatment_manifest"),
        ),
        authority_namespace=_string(authority, "namespace", "authority"),
        domain=(
            _string(domain, "namespace", "domain_object"),
            _string(domain, "object_type", "domain_object"),
            _string(domain, "object_id", "domain_object"),
        ),
        outcome_kind=outcome_kind,
        judgment=judgment,
        error_kind=error_kind,
        predecessor=predecessor,
    )


def _mapping(value: object, coordinate: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValidationError(f"Barnowl outcome {coordinate} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValidationError(f"Barnowl outcome {coordinate} keys must be strings")
    return cast(dict[str, JsonValue], value)


def _string(mapping: dict[str, JsonValue], key: str, coordinate: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"Barnowl outcome {coordinate}.{key} must be a string")
    return value


def _in_window(value: datetime, *, since: datetime | None, until: datetime | None) -> bool:
    return (since is None or value >= since) and (until is None or value < until)


def _current_crosswalks_as_of(
    records: Sequence[CrosswalkRecord], cutoff: datetime | None
) -> tuple[CrosswalkRecord, ...]:
    current: dict[str, CrosswalkRecord] = {}
    for record in records:
        if cutoff is None or record.recorded_at < cutoff:
            current[record.link_id] = record
    return tuple(
        sorted(
            (record for record in current.values() if record.state is JoinState.ASSERTED),
            key=lambda record: (record.left, record.right, record.record_id),
        )
    )


def _current_relations_as_of(
    records: Sequence[RelationRecord], cutoff: datetime | None
) -> tuple[RelationRecord, ...]:
    current: dict[str, RelationRecord] = {}
    for record in records:
        if cutoff is None or record.recorded_at < cutoff:
            current[record.relation_id] = record
    return tuple(
        sorted(
            (record for record in current.values() if record.state is RelationState.ASSERTED),
            key=lambda record: (
                record.subject,
                record.predicate.value,
                record.object,
                record.record_id,
            ),
        )
    )


def _attributed_records_by_receipt(
    records: Sequence[OutcomeAttributionRecord],
) -> dict[str, tuple[OutcomeAttributionRecord, ...]]:
    grouped: dict[str, list[OutcomeAttributionRecord]] = defaultdict(list)
    for record in records:
        if (
            record.state is AttributionState.ATTRIBUTED
            and record.outcome is not None
            and record.outcome.outcome_type == BARNOWL_OUTCOME_TYPE
        ):
            grouped[record.outcome.reference.value].append(record)
    return {
        coordinate: tuple(sorted(items, key=lambda record: record.cost_event_id))
        for coordinate, items in grouped.items()
    }


def _receipt_coordinate_coverage(
    receipts: Sequence[_Receipt],
    records: Sequence[OutcomeAttributionRecord],
    events_by_id: dict[str, NormalizedEvent],
) -> dict[str, Any]:
    occurrences = [
        (receipt.coordinate, call_id)
        for receipt in receipts
        for call_id in receipt.call_ids
        if call_id is not None
    ]
    call_receipts: dict[str, set[str]] = defaultdict(set)
    for receipt_coordinate, call_id in occurrences:
        call_receipts[call_id].add(receipt_coordinate)

    selected_records_by_call: dict[str, list[OutcomeAttributionRecord]] = defaultdict(list)
    for record in records:
        cost_event = events_by_id.get(record.cost_event_id)
        if (
            cost_event is None
            or cost_event.source.adapter != "somm"
            or cost_event.parent_event_id is None
        ):
            continue
        call_event = events_by_id.get(cost_event.parent_event_id)
        if (
            call_event is None
            or call_event.kind is not EventKind.MODEL_CALL
            or call_event.source.adapter != "somm"
        ):
            continue
        selected_records_by_call[call_event.source.native_id].append(record)

    joined_occurrences = 0
    missing_occurrences = 0
    missing_distinct: set[str] = set()
    for receipt_coordinate, call_id in occurrences:
        matching = selected_records_by_call.get(call_id, ())
        if not matching:
            missing_occurrences += 1
            missing_distinct.add(call_id)
        if any(
            record.state is AttributionState.ATTRIBUTED
            and record.outcome is not None
            and record.outcome.reference.value == receipt_coordinate
            for record in matching
        ):
            joined_occurrences += 1

    exact_joined_records = sum(
        1
        for record in records
        if record.state is AttributionState.ATTRIBUTED
        and record.outcome is not None
        and record.outcome.outcome_type == BARNOWL_OUTCOME_TYPE
    )
    non_null = len(occurrences)
    return {
        "total_call_slots": sum(len(receipt.call_ids) for receipt in receipts),
        "null_call_ids": sum(
            call_id is None for receipt in receipts for call_id in receipt.call_ids
        ),
        "non_null_call_id_occurrences": non_null,
        "distinct_call_ids": len(call_receipts),
        "duplicate_call_ids_across_receipts": sum(
            len(receipt_coordinates) > 1 for receipt_coordinates in call_receipts.values()
        ),
        "duplicate_call_id_occurrences": sum(
            len(receipt_coordinates)
            for receipt_coordinates in call_receipts.values()
            if len(receipt_coordinates) > 1
        ),
        "exact_selected_cost_observations_joined": exact_joined_records,
        "receipt_call_id_occurrences_exactly_joined": joined_occurrences,
        "receipt_call_id_occurrences_without_selected_cost": missing_occurrences,
        "distinct_receipt_call_ids_without_selected_cost": len(missing_distinct),
        "exact_join_percentage": _percentage(joined_occurrences, non_null),
    }


def _selected_window_allocation(
    attribution: OutcomeAttributionProjection,
) -> dict[str, Any]:
    counts = Counter(record.state.value for record in attribution.records)
    reason_counts = Counter(record.reason.value for record in attribution.records)
    selected_count = len(attribution.records)
    state_amounts = {
        AttributionState.ATTRIBUTED: attribution.attributed_total_usd,
        AttributionState.AMBIGUOUS: attribution.ambiguous_total_usd,
        AttributionState.UNALLOCATED: attribution.unallocated_total_usd,
    }
    observations: dict[str, Any] = {"selected": selected_count}
    amounts: dict[str, Any] = {"selected": str(attribution.selected_total_usd)}
    for state in AttributionState:
        count = counts[state.value]
        amount = state_amounts[state]
        observations[state.value] = {
            "count": count,
            "percentage": _percentage(count, selected_count),
        }
        amounts[state.value] = {
            "amount": str(amount),
            "percentage": _decimal_percentage(amount, attribution.selected_total_usd),
        }
    return {
        "observations": observations,
        "amounts_usd": amounts,
        "reason_counts": dict(sorted(reason_counts.items())),
        "conservation": {
            "formula": "selected = attributed + ambiguous + unallocated",
            "satisfied": True,
        },
    }


def _raw_outcome_dimensions(
    receipts: Sequence[_Receipt],
    records_by_receipt: dict[str, tuple[OutcomeAttributionRecord, ...]],
    *,
    denominator: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[_Receipt]] = defaultdict(list)
    for receipt in receipts:
        grouped[
            (
                receipt.workload,
                *receipt.treatment,
                receipt.authority_namespace,
                receipt.domain[0],
                receipt.domain[1],
                receipt.outcome_kind,
                receipt.judgment or "",
                receipt.error_kind or "",
            )
        ].append(receipt)
    rows: list[dict[str, Any]] = []
    for key, members in sorted(grouped.items()):
        metrics = _receipt_metrics(members, records_by_receipt)
        rows.append(
            {
                "workload": key[0],
                "treatment_namespace": key[1],
                "manifest_sha256": key[2],
                "authority_namespace": key[3],
                "domain_namespace": key[4],
                "domain_object_type": key[5],
                "outcome": {
                    "kind": key[6],
                    "judgment": key[7] or None,
                    "error_kind": key[8] or None,
                },
                **metrics,
                "raw_yield_percentage": _percentage(len(members), denominator),
            }
        )
    return rows


def _aggregate_receipt_groups(
    receipts: Sequence[_Receipt],
    records_by_receipt: dict[str, tuple[OutcomeAttributionRecord, ...]],
    *,
    key: Any,
    labels: tuple[str, ...],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[_Receipt]] = defaultdict(list)
    for receipt in receipts:
        grouped[cast(tuple[str, ...], key(receipt))].append(receipt)
    rows: list[dict[str, Any]] = []
    for coordinate, members in sorted(grouped.items()):
        row: dict[str, Any] = dict(zip(labels, coordinate, strict=True))
        row.update(_receipt_metrics(members, records_by_receipt))
        yields = Counter(receipt.raw_bucket for receipt in members)
        row["raw_yields"] = {
            bucket: {
                "outcomes": yields[bucket],
                "percentage": _percentage(yields[bucket], len(members)),
            }
            for bucket in _RAW_YIELD_BUCKETS
        }
        rows.append(row)
    return rows


def _receipt_metrics(
    receipts: Sequence[_Receipt],
    records_by_receipt: dict[str, tuple[OutcomeAttributionRecord, ...]],
) -> dict[str, Any]:
    records = [
        record for receipt in receipts for record in records_by_receipt.get(receipt.coordinate, ())
    ]
    amount = sum((record.amount_usd for record in records), Decimal(0))
    outcomes_with_cost = sum(
        bool(records_by_receipt.get(receipt.coordinate)) for receipt in receipts
    )
    distinct_call_ids = {
        call_id for receipt in receipts for call_id in receipt.call_ids if call_id is not None
    }
    return {
        "receipt_outcomes": len(receipts),
        "distinct_attempts": len({receipt.attempt for receipt in receipts}),
        "call_slots": sum(len(receipt.call_ids) for receipt in receipts),
        "non_null_call_id_occurrences": sum(
            call_id is not None for receipt in receipts for call_id in receipt.call_ids
        ),
        "distinct_call_ids": len(distinct_call_ids),
        "attributed_observations": len(records),
        "attributed_cost_usd": str(amount),
        "outcomes_with_attributed_cost": outcomes_with_cost,
        "outcomes_with_attributed_cost_percentage": _percentage(outcomes_with_cost, len(receipts)),
        "cost_per_outcome_usd": str(amount / len(receipts)) if receipts else None,
    }


def _build_current_chains(
    selected: Sequence[_Receipt],
    all_receipts: Sequence[_Receipt],
    records_by_receipt: dict[str, tuple[OutcomeAttributionRecord, ...]],
) -> tuple[tuple[_Chain, ...], dict[str, int], set[str], int]:
    selected_by_coordinate = {receipt.coordinate: receipt for receipt in selected}
    all_coordinates = {receipt.coordinate for receipt in all_receipts}
    predecessor_by_successor: dict[str, str] = {}
    successors_by_predecessor: dict[str, set[str]] = defaultdict(set)
    adjacency: dict[str, set[str]] = defaultdict(set)
    invalid: set[str] = set()
    gaps = {name: 0 for name in _GAP_NAMES}

    for successor in selected:
        predecessor_coordinate = successor.predecessor
        if predecessor_coordinate is None:
            continue
        predecessor = selected_by_coordinate.get(predecessor_coordinate)
        if predecessor is None:
            gap = (
                "outside_window" if predecessor_coordinate in all_coordinates else "missing_target"
            )
            gaps[gap] += 1
            invalid.add(successor.coordinate)
            continue
        predecessor_by_successor[successor.coordinate] = predecessor.coordinate
        successors_by_predecessor[predecessor.coordinate].add(successor.coordinate)
        adjacency[predecessor.coordinate].add(successor.coordinate)
        adjacency[successor.coordinate].add(predecessor.coordinate)
        if predecessor.domain != successor.domain:
            gaps["cross_domain"] += 1
            invalid.update((predecessor.coordinate, successor.coordinate))
        if predecessor.event.occurred_at >= successor.event.occurred_at:
            gaps["non_increasing_timestamp"] += 1
            invalid.update((predecessor.coordinate, successor.coordinate))

    for predecessor_coordinate, successors in successors_by_predecessor.items():
        if len(successors) > 1:
            gaps["fork"] += 1
            invalid.add(predecessor_coordinate)
            invalid.update(successors)

    cycles = _cycles(predecessor_by_successor)
    gaps["cycle"] = len(cycles)
    for cycle in cycles:
        invalid.update(cycle)

    pending = list(invalid)
    while pending:
        pending_coordinate = pending.pop()
        for neighbor in adjacency.get(pending_coordinate, ()):
            if neighbor not in invalid:
                invalid.add(neighbor)
                pending.append(neighbor)

    invalid_components = _component_count(invalid, adjacency)
    valid = set(selected_by_coordinate).difference(invalid)
    valid_successor: dict[str, str] = {}
    valid_predecessors: set[str] = set()
    for successor_coordinate, predecessor_coordinate in predecessor_by_successor.items():
        if successor_coordinate in valid and predecessor_coordinate in valid:
            valid_successor[predecessor_coordinate] = successor_coordinate
            valid_predecessors.add(successor_coordinate)
    roots = sorted(
        valid.difference(valid_predecessors),
        key=lambda coordinate: selected_by_coordinate[coordinate].sort_key,
    )
    chains: list[_Chain] = []
    visited: set[str] = set()
    for root in roots:
        members: list[_Receipt] = []
        chain_coordinate: str | None = root
        while chain_coordinate is not None and chain_coordinate not in visited:
            visited.add(chain_coordinate)
            members.append(selected_by_coordinate[chain_coordinate])
            chain_coordinate = valid_successor.get(chain_coordinate)
        records = [
            record
            for receipt in members
            for record in records_by_receipt.get(receipt.coordinate, ())
        ]
        chains.append(
            _Chain(
                receipts=tuple(members),
                attributed_observations=len(records),
                attributed_cost_usd=sum((record.amount_usd for record in records), Decimal(0)),
            )
        )
    if visited != valid:  # pragma: no cover - cycles are excluded above
        raise ValidationError("Barnowl current-chain projection did not terminate")
    return tuple(chains), gaps, invalid, invalid_components


def _cycles(predecessor_by_successor: dict[str, str]) -> tuple[frozenset[str], ...]:
    cycles: set[frozenset[str]] = set()
    complete: set[str] = set()
    for start in sorted(predecessor_by_successor):
        if start in complete:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        coordinate: str | None = start
        while coordinate is not None and coordinate not in complete:
            if coordinate in positions:
                cycles.add(frozenset(path[positions[coordinate] :]))
                break
            positions[coordinate] = len(path)
            path.append(coordinate)
            coordinate = predecessor_by_successor.get(coordinate)
        complete.update(path)
    return tuple(sorted(cycles, key=lambda cycle: tuple(sorted(cycle))))


def _component_count(coordinates: set[str], adjacency: dict[str, set[str]]) -> int:
    unseen = set(coordinates)
    count = 0
    while unseen:
        count += 1
        pending = [unseen.pop()]
        while pending:
            coordinate = pending.pop()
            for neighbor in adjacency.get(coordinate, ()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    pending.append(neighbor)
    return count


def _semantic_funnel(
    chains: Sequence[_Chain],
    gap_counts: dict[str, int],
    invalid_receipts: set[str],
    invalid_components: int,
    records_by_receipt: dict[str, tuple[OutcomeAttributionRecord, ...]],
) -> dict[str, Any]:
    admitted = [chain for chain in chains if chain.contains_admitted]
    later = [chain for chain in admitted if chain.later_corroborated]
    admitted_cost = sum((chain.attributed_cost_usd for chain in admitted), Decimal(0))
    later_cost = sum((chain.attributed_cost_usd for chain in later), Decimal(0))
    invalid_records = [
        record
        for coordinate in invalid_receipts
        for record in records_by_receipt.get(coordinate, ())
    ]
    terminals = Counter(chain.terminal_bucket for chain in chains)
    admitted_waiting = sum(
        chain.contains_admitted and chain.terminal_bucket == "ADMITTED" for chain in chains
    )
    semantic_treatments: dict[tuple[str, str, str], list[_Chain]] = defaultdict(list)
    for chain in chains:
        treatment = chain.treatment
        coordinate = (
            ("single", treatment[0], treatment[1]) if treatment is not None else ("mixed", "", "")
        )
        semantic_treatments[coordinate].append(chain)
    treatment_rows: list[dict[str, Any]] = []
    for coordinate, members in sorted(semantic_treatments.items()):
        member_admitted = [chain for chain in members if chain.contains_admitted]
        member_later = [chain for chain in member_admitted if chain.later_corroborated]
        amount = sum((chain.attributed_cost_usd for chain in members), Decimal(0))
        admitted_amount = sum((chain.attributed_cost_usd for chain in member_admitted), Decimal(0))
        later_amount = sum((chain.attributed_cost_usd for chain in member_later), Decimal(0))
        treatment_rows.append(
            {
                "bucket": coordinate[0],
                "treatment_namespace": coordinate[1] or None,
                "manifest_sha256": coordinate[2] or None,
                "domain_chains": len(members),
                "attributed_observations": sum(chain.attributed_observations for chain in members),
                "attributed_cost_usd": str(amount),
                "chains_containing_admitted": len(member_admitted),
                "later_corroborated_chains": len(member_later),
                "cost_per_admitted_result_usd": (
                    str(admitted_amount / len(member_admitted)) if member_admitted else None
                ),
                "cost_per_later_corroborated_result_usd": (
                    str(later_amount / len(member_later)) if member_later else None
                ),
            }
        )
    return {
        "standardized_judgments": sorted(STANDARDIZED_JUDGMENTS),
        "valid_domain_chains": len(chains),
        "excluded_invalid_chains": invalid_components,
        "excluded_invalid_receipt_outcomes": len(invalid_receipts),
        "excluded_invalid_attributed_observations": len(invalid_records),
        "excluded_invalid_attributed_cost_usd": str(
            sum((record.amount_usd for record in invalid_records), Decimal(0))
        ),
        "chains_containing_admitted": len(admitted),
        "chains_containing_admitted_percentage": _percentage(len(admitted), len(chains)),
        "admitted_chain_cost_usd": str(admitted_cost),
        "cost_per_admitted_result_usd": (str(admitted_cost / len(admitted)) if admitted else None),
        "later_corroborated_chains": len(later),
        "later_corroborated_percentage_of_admitted": _percentage(len(later), len(admitted)),
        "later_corroborated_chain_cost_usd": str(later_cost),
        "cost_per_later_corroborated_result_usd": (str(later_cost / len(later)) if later else None),
        "terminal_rejected_chains": terminals["REJECTED"],
        "terminal_rejected_percentage": _percentage(terminals["REJECTED"], len(chains)),
        "terminal_error_chains": terminals["error"],
        "terminal_error_percentage": _percentage(terminals["error"], len(chains)),
        "terminal_unmapped_chains": terminals["unmapped"],
        "terminal_unmapped_percentage": _percentage(terminals["unmapped"], len(chains)),
        "terminal_corroborated_without_admission_chains": sum(
            chain.terminal_bucket == "CORROBORATED" and not chain.contains_admitted
            for chain in chains
        ),
        "admitted_awaiting_followup_chains": admitted_waiting,
        "gap_counts": gap_counts,
        "treatment_groups": treatment_rows,
    }


def _claimability(
    *,
    exact_join_rate: Decimal | None,
    threshold: Decimal,
    attribution: OutcomeAttributionProjection,
    gap_counts: dict[str, int],
    chains: Sequence[_Chain],
) -> dict[str, JsonValue]:
    reasons: set[str] = set()
    if exact_join_rate is None or exact_join_rate < threshold:
        reasons.add("below_join_threshold")
    if (
        attribution.ambiguous_total_usd != 0
        or any(record.state is AttributionState.AMBIGUOUS for record in attribution.records)
        or any(gap_counts.values())
        or any(chain.terminal_bucket == "unmapped" for chain in chains)
    ):
        reasons.add("ambiguous_or_invalid_followup")
    admitted = [chain for chain in chains if chain.contains_admitted]
    if not admitted:
        reasons.add("no_standardized_admissions")
    if any(chain.terminal_bucket == "ADMITTED" for chain in admitted):
        reasons.add("insufficient_later_followup")
    ordered = [reason for reason in _CLAIMABILITY_REASON_ORDER if reason in reasons]
    if not ordered:
        ordered = ["eligible"]
    return {
        "status": "eligible" if ordered == ["eligible"] else "not_claimable",
        "reasons": cast(list[JsonValue], ordered),
    }


def _source_coverage(
    selected_receipts: Sequence[_Receipt],
    attribution: OutcomeAttributionProjection,
    cutoff_receipts: Sequence[_Receipt],
) -> dict[str, JsonValue]:
    cost_adapters = Counter(record.source_adapter for record in attribution.records)
    return {
        "barnowl_research_outcome": {
            "selected_receipt_outcomes": len(selected_receipts),
            "before_since_receipt_outcomes": len(cutoff_receipts) - len(selected_receipts),
        },
        "selected_cost_observations": {
            "total": len(attribution.records),
            "by_adapter": dict(sorted(cost_adapters.items())),
        },
    }


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    return Decimal(numerator) / Decimal(denominator) if denominator else None


def _percentage(numerator: int, denominator: int) -> str | None:
    rate = _ratio(numerator, denominator)
    return _percentage_from_rate(rate) if rate is not None else None


def _decimal_percentage(numerator: Decimal, denominator: Decimal) -> str | None:
    return _percentage_from_rate(numerator / denominator) if denominator != 0 else None


def _percentage_from_rate(rate: Decimal) -> str:
    return _decimal_string(rate * Decimal(100))


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _render_rate(value: object) -> str:
    return "null" if value is None else f"{value}%"
