"""Canonical cost projection with explicit, auditable precedence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from milton.model import (
    CostAccuracy,
    CostBasis,
    CostKeyScope,
    CostKind,
    CostObservationRole,
    CostPayload,
    EventKind,
    JsonValue,
    NormalizedEvent,
)

# Accuracy is compared before derivation: a settled computed amount is stronger
# than an upstream estimate. Within one accuracy tier, a source-reported amount
# wins over one recomputed from tokens and a price table.
ACCOUNTING_PRECEDENCE: tuple[tuple[CostBasis, CostAccuracy], ...] = (
    (CostBasis.REPORTED, CostAccuracy.ACTUAL),
    (CostBasis.COMPUTED, CostAccuracy.ACTUAL),
    (CostBasis.UNKNOWN, CostAccuracy.ACTUAL),
    (CostBasis.REPORTED, CostAccuracy.ESTIMATED),
    (CostBasis.COMPUTED, CostAccuracy.ESTIMATED),
    (CostBasis.UNKNOWN, CostAccuracy.ESTIMATED),
    (CostBasis.REPORTED, CostAccuracy.UNKNOWN),
    (CostBasis.COMPUTED, CostAccuracy.UNKNOWN),
    (CostBasis.UNKNOWN, CostAccuracy.UNKNOWN),
)

# This only breaks ties after basis and accuracy. Somm wins equal-quality ties
# for mediated calls because it owns that per-call ledger; lexical ordering is
# the deterministic fallback for adapters not listed here.
AUTHORITY_PRECEDENCE: tuple[str, ...] = (
    "provider",
    "somm",
    "hermes",
    "opencode",
    "claude-code",
    "codex",
)


@dataclass(frozen=True, slots=True)
class AccountingDecision:
    accounting_key: str
    key_scope: CostKeyScope
    kind: CostKind
    selected_event_id: str
    selected_adapter: str
    selected_basis: CostBasis
    selected_accuracy: CostAccuracy
    selected_amount_usd: Decimal
    suppressed_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "accounting_key": self.accounting_key,
            "key_scope": self.key_scope.value,
            "kind": self.kind.value,
            "selected": {
                "event_id": self.selected_event_id,
                "adapter": self.selected_adapter,
                "basis": self.selected_basis.value,
                "accuracy": self.selected_accuracy.value,
                "amount_usd": str(self.selected_amount_usd),
            },
            "suppressed_event_ids": list(self.suppressed_event_ids),
        }


@dataclass(frozen=True, slots=True)
class AccountingProjection:
    cost_events: int
    amount_observations: int
    selected_observations: int
    suppressed_observations: int
    amount_unavailable: int
    rollup_events: int
    raw_observed_usd: Decimal
    selected_total_usd: Decimal
    suppressed_usd: Decimal
    selected_by_kind: dict[CostKind, Decimal]
    selected_by_basis: dict[CostBasis, Decimal]
    shared_key_observations: int
    source_key_observations: int
    unknown_key_observations: int
    decisions: tuple[AccountingDecision, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "precedence": [
                f"{basis.value}.{accuracy.value}" for basis, accuracy in ACCOUNTING_PRECEDENCE
            ],
            "authority_tiebreak": list(AUTHORITY_PRECEDENCE),
            "observations": {
                "cost_events": self.cost_events,
                "with_amount": self.amount_observations,
                "amount_unavailable": self.amount_unavailable,
                "excluded_rollups": self.rollup_events,
                "selected": self.selected_observations,
                "suppressed_exact_duplicates": self.suppressed_observations,
            },
            "amounts_usd": {
                "raw_observed": str(self.raw_observed_usd),
                "selected_observations": str(self.selected_total_usd),
                "suppressed_exact_duplicates": str(self.suppressed_usd),
                "by_kind": {
                    kind.value: str(self.selected_by_kind.get(kind, Decimal(0)))
                    for kind in CostKind
                },
                "by_basis": {
                    basis.value: str(self.selected_by_basis.get(basis, Decimal(0)))
                    for basis in CostBasis
                },
            },
            "key_coverage": {
                "shared": self.shared_key_observations,
                "source_local": self.source_key_observations,
                "unknown_or_missing": self.unknown_key_observations,
            },
            "duplicate_decisions": [decision.to_dict() for decision in self.decisions],
        }

    def to_text(self) -> str:
        by_kind = {kind: self.selected_by_kind.get(kind, Decimal(0)) for kind in CostKind}
        lines = [
            "Milton accounting",
            "",
            f"Marginal cost: ${by_kind[CostKind.MARGINAL]}",
            f"Notional cost: ${by_kind[CostKind.NOTIONAL]}",
            f"Included cost: ${by_kind[CostKind.INCLUDED]}",
            f"Unclassified cost: ${by_kind[CostKind.UNKNOWN]}",
            f"Raw observed amounts: ${self.raw_observed_usd}",
            f"Selected observation total: ${self.selected_total_usd}",
            "",
            f"Cost events: {self.cost_events}; amounts present: {self.amount_observations}",
            f"Rollup events excluded from monetary selection: {self.rollup_events}",
            f"Exact duplicate observations suppressed: {self.suppressed_observations} "
            f"(${self.suppressed_usd})",
            "Accounting keys: "
            f"{self.shared_key_observations} shared, "
            f"{self.source_key_observations} source-local, "
            f"{self.unknown_key_observations} missing/unknown",
            "Precedence: "
            + " > ".join(
                f"{basis.value}.{accuracy.value}" for basis, accuracy in ACCOUNTING_PRECEDENCE
            ),
        ]
        if self.source_key_observations or self.unknown_key_observations:
            lines.extend(
                [
                    "",
                    "Caution: source-local and missing keys cannot prove cross-source "
                    "equivalence, so Milton does not deduplicate them by timestamp or token count.",
                ]
            )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _AccountingSelection:
    cost_events: int
    amount_unavailable: int
    rollup_events: int
    observations: tuple[NormalizedEvent, ...]
    selected: tuple[NormalizedEvent, ...]
    decisions: tuple[AccountingDecision, ...]
    shared: int
    source_local: int
    unknown: int


def select_cost_events(events: Iterable[NormalizedEvent]) -> tuple[NormalizedEvent, ...]:
    """Return the exact monetary observations selected by accounting precedence."""

    return _select_accounting(events).selected


def build_accounting(events: Iterable[NormalizedEvent]) -> AccountingProjection:
    selection = _select_accounting(events)
    observations = selection.observations
    selected = selection.selected
    raw = sum((_amount(event) for event in observations), Decimal(0))
    projected = sum((_amount(event) for event in selected), Decimal(0))
    by_kind = _sum_by_kind(selected)
    by_basis = _sum_by_basis(selected)
    return AccountingProjection(
        cost_events=selection.cost_events,
        amount_observations=len(observations),
        selected_observations=len(selected),
        suppressed_observations=len(observations) - len(selected),
        amount_unavailable=selection.amount_unavailable,
        rollup_events=selection.rollup_events,
        raw_observed_usd=raw,
        selected_total_usd=projected,
        suppressed_usd=raw - projected,
        selected_by_kind=by_kind,
        selected_by_basis=by_basis,
        shared_key_observations=selection.shared,
        source_key_observations=selection.source_local,
        unknown_key_observations=selection.unknown,
        decisions=selection.decisions,
    )


def _select_accounting(events: Iterable[NormalizedEvent]) -> _AccountingSelection:
    cost_events = 0
    amount_unavailable = 0
    rollup_events = 0
    observations: list[NormalizedEvent] = []
    for event in events:
        if event.kind is not EventKind.COST or not isinstance(event.payload, CostPayload):
            continue
        cost_events += 1
        if event.payload.observation_role is CostObservationRole.ROLLUP:
            rollup_events += 1
            continue
        if event.payload.amount_usd is None:
            amount_unavailable += 1
            continue
        observations.append(event)

    groups: dict[tuple[str, CostKind], list[NormalizedEvent]] = {}
    shared = source_local = unknown = 0
    for event in observations:
        payload = _cost_payload(event)
        group_key: str
        if payload.accounting_key and payload.accounting_key_scope is CostKeyScope.SHARED:
            shared += 1
            group_key = f"shared\0{payload.accounting_key}"
        elif payload.accounting_key and payload.accounting_key_scope is CostKeyScope.SOURCE:
            source_local += 1
            group_key = f"source\0{event.source.adapter}\0{payload.accounting_key}"
        else:
            unknown += 1
            group_key = f"event\0{event.event_id}"
        groups.setdefault((group_key, payload.kind), []).append(event)

    selected: list[NormalizedEvent] = []
    decisions: list[AccountingDecision] = []
    for (_, kind), group in sorted(groups.items()):
        ordered = sorted(group, key=_precedence_key)
        winner = ordered[0]
        selected.append(winner)
        if len(ordered) > 1:
            payload = _cost_payload(winner)
            assert payload.amount_usd is not None
            decisions.append(
                AccountingDecision(
                    accounting_key=payload.accounting_key or winner.event_id,
                    key_scope=payload.accounting_key_scope,
                    kind=kind,
                    selected_event_id=winner.event_id,
                    selected_adapter=winner.source.adapter,
                    selected_basis=payload.basis,
                    selected_accuracy=payload.accuracy,
                    selected_amount_usd=payload.amount_usd,
                    suppressed_event_ids=tuple(event.event_id for event in ordered[1:]),
                )
            )

    return _AccountingSelection(
        cost_events=cost_events,
        amount_unavailable=amount_unavailable,
        rollup_events=rollup_events,
        observations=tuple(observations),
        selected=tuple(selected),
        decisions=tuple(decisions),
        shared=shared,
        source_local=source_local,
        unknown=unknown,
    )


def _precedence_key(event: NormalizedEvent) -> tuple[int, int, str, str]:
    payload = _cost_payload(event)
    try:
        provenance_rank = ACCOUNTING_PRECEDENCE.index((payload.basis, payload.accuracy))
    except ValueError:  # pragma: no cover - enums make this defensive
        provenance_rank = len(ACCOUNTING_PRECEDENCE)
    authority = payload.authority or event.source.adapter
    try:
        authority_rank = AUTHORITY_PRECEDENCE.index(authority)
    except ValueError:
        authority_rank = len(AUTHORITY_PRECEDENCE)
    return (provenance_rank, authority_rank, authority, event.event_id)


def _cost_payload(event: NormalizedEvent) -> CostPayload:
    payload = event.payload
    if not isinstance(payload, CostPayload):  # pragma: no cover - caller filters
        raise TypeError("accounting projection requires cost events")
    return payload


def _amount(event: NormalizedEvent) -> Decimal:
    amount = _cost_payload(event).amount_usd
    return amount if amount is not None else Decimal(0)


def _sum_by_kind(events: Iterable[NormalizedEvent]) -> dict[CostKind, Decimal]:
    result: dict[CostKind, Decimal] = {}
    for event in events:
        payload = _cost_payload(event)
        result[payload.kind] = result.get(payload.kind, Decimal(0)) + _amount(event)
    return result


def _sum_by_basis(events: Iterable[NormalizedEvent]) -> dict[CostBasis, Decimal]:
    result: dict[CostBasis, Decimal] = {}
    for event in events:
        payload = _cost_payload(event)
        result[payload.basis] = result.get(payload.basis, Decimal(0)) + _amount(event)
    return result
