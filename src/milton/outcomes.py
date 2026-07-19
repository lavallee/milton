"""Conservative attribution of selected cost observations to typed outcomes."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from milton.accounting import AccountingProjection, build_accounting, select_cost_events
from milton.crosswalk import CrosswalkRecord
from milton.errors import ValidationError
from milton.model import (
    CostPayload,
    EventKind,
    JsonValue,
    NormalizedEvent,
    OutcomePayload,
)
from milton.relations import RelationKind, RelationRecord, TypedRef

OUTCOME_PRECEDENCE: tuple[str, ...] = (
    "git.commit",
    "george.entry",
    "fab.job",
    "fab.attempt",
)


class AttributionState(StrEnum):
    ATTRIBUTED = "attributed"
    AMBIGUOUS = "ambiguous"
    UNALLOCATED = "unallocated"


class AttributionReason(StrEnum):
    EXACT_DIRECTED_PATH = "exact-directed-path"
    COMPETING_OUTCOMES = "competing-outcomes"
    ASSOCIATION_ONLY = "association-only"
    NO_ROOT_REFERENCE = "no-root-reference"
    NO_OUTCOME_PATH = "no-outcome-path"


class PathStepKind(StrEnum):
    CROSSWALK = "crosswalk"
    RELATION = "relation"
    EVENT = "event"


@dataclass(frozen=True, slots=True)
class PathStep:
    kind: PathStepKind
    source: TypedRef
    target: TypedRef
    edge_id: str
    revision_id: str | None
    predicate: str | None
    direction: str
    evidence_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "edge_id": self.edge_id,
            "revision_id": self.revision_id,
            "predicate": self.predicate,
            "direction": self.direction,
            "evidence_event_ids": list(self.evidence_event_ids),
        }


@dataclass(frozen=True, slots=True)
class AttributionPath:
    references: tuple[TypedRef, ...]
    steps: tuple[PathStep, ...]
    event_ids: tuple[str, ...]
    link_ids: tuple[str, ...]
    link_record_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    relation_record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "references": [reference.to_dict() for reference in self.references],
            "steps": [step.to_dict() for step in self.steps],
            "event_ids": list(self.event_ids),
            "link_ids": list(self.link_ids),
            "link_record_ids": list(self.link_record_ids),
            "relation_ids": list(self.relation_ids),
            "relation_record_ids": list(self.relation_record_ids),
        }


@dataclass(frozen=True, slots=True)
class OutcomeCandidate:
    outcome_type: str
    reference: TypedRef
    event_id: str
    status: str
    occurred_at: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "outcome_type": self.outcome_type,
            "reference": self.reference.to_dict(),
            "event_id": self.event_id,
            "status": self.status,
            "occurred_at": self.occurred_at,
        }


@dataclass(frozen=True, slots=True)
class CandidatePath:
    candidate: OutcomeCandidate
    path: AttributionPath
    eligible: bool

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "candidate": self.candidate.to_dict(),
            "eligible": self.eligible,
            "path": self.path.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OutcomeAttributionRecord:
    cost_event_id: str
    source_adapter: str
    source_native_id: str
    amount_usd: Decimal
    economic_kind: str
    basis: str
    accuracy: str
    authority: str | None
    pricing_version: str | None
    accounting_key: str | None
    accounting_key_scope: str
    observation_role: str
    state: AttributionState
    reason: AttributionReason
    outcome: OutcomeCandidate | None
    path: AttributionPath | None
    candidates: tuple[CandidatePath, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "cost_event_id": self.cost_event_id,
            "source": {
                "adapter": self.source_adapter,
                "native_id": self.source_native_id,
            },
            "amount_usd": str(self.amount_usd),
            "economic_kind": self.economic_kind,
            "basis": self.basis,
            "accuracy": self.accuracy,
            "authority": self.authority,
            "pricing_version": self.pricing_version,
            "accounting_key": self.accounting_key,
            "accounting_key_scope": self.accounting_key_scope,
            "observation_role": self.observation_role,
            "state": self.state.value,
            "reason": self.reason.value,
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "path": self.path.to_dict() if self.path else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class OutcomeRollup:
    outcome_type: str
    reference: TypedRef
    status: str
    economic_kind: str
    amount_usd: Decimal
    observations: int

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "outcome_type": self.outcome_type,
            "reference": self.reference.to_dict(),
            "status": self.status,
            "economic_kind": self.economic_kind,
            "amount_usd": str(self.amount_usd),
            "observations": self.observations,
        }


@dataclass(frozen=True, slots=True)
class OutcomeAttributionProjection:
    accounting: AccountingProjection
    selected_total_usd: Decimal
    attributed_total_usd: Decimal
    ambiguous_total_usd: Decimal
    unallocated_total_usd: Decimal
    records: tuple[OutcomeAttributionRecord, ...]
    outcomes: tuple[OutcomeRollup, ...]
    outcome_types: tuple[str, ...]
    source_coverage: dict[str, JsonValue]

    def __post_init__(self) -> None:
        reconciled = (
            self.attributed_total_usd + self.ambiguous_total_usd + self.unallocated_total_usd
        )
        if self.selected_total_usd != reconciled:
            raise ValidationError("outcome attribution must conserve selected accounting amounts")
        if self.selected_total_usd != self.accounting.selected_total_usd:
            raise ValidationError("outcome attribution must use accounting's selected total")

    def to_dict(self) -> dict[str, JsonValue]:
        reasons: dict[str, int] = {}
        for record in self.records:
            reasons[record.reason.value] = reasons.get(record.reason.value, 0) + 1
        denominators: dict[str, JsonValue] = {}
        for outcome_type in self.outcome_types:
            matching = [item for item in self.outcomes if item.outcome_type == outcome_type]
            distinct = len({(item.reference.namespace, item.reference.value) for item in matching})
            amount = sum((item.amount_usd for item in matching), Decimal(0))
            denominators[outcome_type] = {
                "outcomes": distinct,
                "attributed_usd": str(amount),
                "cost_per_outcome_usd": str(amount / distinct) if distinct else None,
            }
        return {
            "schema_version": 1,
            "accounting_schema_version": 1,
            "outcome_precedence": list(OUTCOME_PRECEDENCE),
            "outcome_type_filter": list(self.outcome_types),
            "amounts_usd": {
                "selected_total": str(self.selected_total_usd),
                "attributed": str(self.attributed_total_usd),
                "ambiguous": str(self.ambiguous_total_usd),
                "unallocated": str(self.unallocated_total_usd),
            },
            "conservation": {
                "formula": "selected_total = attributed + ambiguous + unallocated",
                "satisfied": True,
            },
            "denominators": denominators,
            "reason_counts": dict(sorted(reasons.items())),
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "records": [record.to_dict() for record in self.records],
            "accounting": self.accounting.to_dict(),
            "source_coverage": self.source_coverage,
        }

    def to_text(self) -> str:
        lines = [
            "Milton cost per outcome",
            "",
            "Amounts are selected observations; they are not automatically actual provider spend.",
            f"Selected: ${self.selected_total_usd}",
            f"Attributed: ${self.attributed_total_usd}",
            f"Ambiguous: ${self.ambiguous_total_usd}",
            f"Unallocated: ${self.unallocated_total_usd}",
            "Conservation: satisfied",
            "",
            "Outcome amounts:",
        ]
        if not self.outcomes:
            lines.append("  none")
        for outcome in self.outcomes:
            lines.append(
                f"  {outcome.outcome_type} {outcome.reference.namespace}="
                f"{outcome.reference.value} [{outcome.status}/{outcome.economic_kind}]: "
                f"${outcome.amount_usd} from {outcome.observations} observation(s)"
            )
        gaps = [
            record for record in self.records if record.state is not AttributionState.ATTRIBUTED
        ]
        if gaps:
            lines.extend(["", "Coverage and abstentions:"])
            for record in gaps:
                lines.append(
                    f"  {record.cost_event_id}: {record.state.value}/{record.reason.value} "
                    f"(${record.amount_usd}; {record.source_adapter}; "
                    f"{record.basis}/{record.accuracy}/{record.economic_kind}; "
                    f"role={record.observation_role})"
                )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _Edge:
    target: TypedRef
    step: PathStep
    establishes_relation: bool


@dataclass(frozen=True, slots=True)
class _Walk:
    references: tuple[TypedRef, ...]
    steps: tuple[PathStep, ...]
    relation_used: bool


def build_outcome_attribution(
    events: Iterable[NormalizedEvent],
    crosswalks: Iterable[CrosswalkRecord],
    relations: Iterable[RelationRecord],
    *,
    cost_event_ids: Iterable[str] | None = None,
    outcome_types: Iterable[str] | None = None,
    source_coverage: dict[str, JsonValue] | None = None,
    max_depth: int = 8,
) -> OutcomeAttributionProjection:
    """Allocate each selected amount once or abstain with an explicit reason."""

    if max_depth < 1:
        raise ValidationError("outcome attribution max_depth must be positive")
    all_events = tuple(events)
    by_id = {event.event_id: event for event in all_events}
    selected_ids = set(cost_event_ids) if cost_event_ids is not None else None
    accounting_events = tuple(
        event for event in all_events if selected_ids is None or event.event_id in selected_ids
    )
    accounting = build_accounting(accounting_events)
    selected_costs = select_cost_events(accounting_events)
    allowed_types = tuple(outcome_types) if outcome_types is not None else OUTCOME_PRECEDENCE
    unknown_types = set(allowed_types).difference(OUTCOME_PRECEDENCE)
    if unknown_types:
        raise ValidationError(f"unsupported outcome types: {sorted(unknown_types)}")

    candidates = _outcome_candidates(all_events, set(allowed_types))
    graph = _build_graph(tuple(crosswalks), tuple(relations), all_events)
    records: list[OutcomeAttributionRecord] = []
    for cost in sorted(selected_costs, key=lambda item: (item.occurred_at, item.event_id)):
        roots, lineage_event_ids = _cost_roots(cost, by_id)
        records.append(
            _attribute_cost(
                cost,
                roots,
                lineage_event_ids,
                candidates,
                graph,
                max_depth=max_depth,
            )
        )

    attributed = sum(
        (record.amount_usd for record in records if record.state is AttributionState.ATTRIBUTED),
        Decimal(0),
    )
    ambiguous = sum(
        (record.amount_usd for record in records if record.state is AttributionState.AMBIGUOUS),
        Decimal(0),
    )
    unallocated = sum(
        (record.amount_usd for record in records if record.state is AttributionState.UNALLOCATED),
        Decimal(0),
    )
    return OutcomeAttributionProjection(
        accounting=accounting,
        selected_total_usd=accounting.selected_total_usd,
        attributed_total_usd=attributed,
        ambiguous_total_usd=ambiguous,
        unallocated_total_usd=unallocated,
        records=tuple(records),
        outcomes=_rollups(records),
        outcome_types=allowed_types,
        source_coverage=source_coverage or {},
    )


def _attribute_cost(
    cost: NormalizedEvent,
    roots: tuple[TypedRef, ...],
    lineage_event_ids: tuple[str, ...],
    candidates: tuple[OutcomeCandidate, ...],
    graph: dict[TypedRef, tuple[_Edge, ...]],
    *,
    max_depth: int,
) -> OutcomeAttributionRecord:
    payload = cost.payload
    if not isinstance(payload, CostPayload) or payload.amount_usd is None:  # defensive
        raise ValidationError("outcome attribution requires selected monetary events")
    if not roots:
        return _record(
            cost,
            AttributionState.UNALLOCATED,
            AttributionReason.NO_ROOT_REFERENCE,
        )

    walks = _walk_graph(roots, graph, max_depth=max_depth)
    candidate_paths: list[CandidatePath] = []
    for candidate in candidates:
        relation_walk = walks.get((candidate.reference, True))
        association_walk = walks.get((candidate.reference, False))
        walk = relation_walk or association_walk
        if walk is None:
            continue
        candidate_paths.append(
            CandidatePath(
                candidate=candidate,
                path=_attribution_path(
                    cost,
                    lineage_event_ids,
                    candidate,
                    walk,
                ),
                eligible=relation_walk is not None,
            )
        )
    candidate_paths.sort(
        key=lambda item: (
            OUTCOME_PRECEDENCE.index(item.candidate.outcome_type),
            item.candidate.reference,
            item.candidate.event_id,
        )
    )
    eligible = [item for item in candidate_paths if item.eligible]
    if not eligible:
        reason = (
            AttributionReason.ASSOCIATION_ONLY
            if candidate_paths
            else AttributionReason.NO_OUTCOME_PATH
        )
        return _record(
            cost,
            AttributionState.UNALLOCATED,
            reason,
            candidates=tuple(candidate_paths),
        )

    best_rank = min(OUTCOME_PRECEDENCE.index(item.candidate.outcome_type) for item in eligible)
    best = [
        item
        for item in eligible
        if OUTCOME_PRECEDENCE.index(item.candidate.outcome_type) == best_rank
    ]
    if len(best) != 1:
        return _record(
            cost,
            AttributionState.AMBIGUOUS,
            AttributionReason.COMPETING_OUTCOMES,
            candidates=tuple(candidate_paths),
        )
    winner = best[0]
    return _record(
        cost,
        AttributionState.ATTRIBUTED,
        AttributionReason.EXACT_DIRECTED_PATH,
        outcome=winner.candidate,
        path=winner.path,
        candidates=tuple(candidate_paths),
    )


def _record(
    cost: NormalizedEvent,
    state: AttributionState,
    reason: AttributionReason,
    *,
    outcome: OutcomeCandidate | None = None,
    path: AttributionPath | None = None,
    candidates: tuple[CandidatePath, ...] = (),
) -> OutcomeAttributionRecord:
    payload = cost.payload
    assert isinstance(payload, CostPayload)
    assert payload.amount_usd is not None
    return OutcomeAttributionRecord(
        cost_event_id=cost.event_id,
        source_adapter=cost.source.adapter,
        source_native_id=cost.source.native_id,
        amount_usd=payload.amount_usd,
        economic_kind=payload.kind.value,
        basis=payload.basis.value,
        accuracy=payload.accuracy.value,
        authority=payload.authority,
        pricing_version=payload.pricing_version,
        accounting_key=payload.accounting_key,
        accounting_key_scope=payload.accounting_key_scope.value,
        observation_role=payload.observation_role.value,
        state=state,
        reason=reason,
        outcome=outcome,
        path=path,
        candidates=candidates,
    )


def _outcome_candidates(
    events: tuple[NormalizedEvent, ...], allowed_types: set[str]
) -> tuple[OutcomeCandidate, ...]:
    current: dict[tuple[str, TypedRef], tuple[NormalizedEvent, OutcomeCandidate]] = {}
    for event in events:
        payload = event.payload
        if not isinstance(payload, OutcomePayload):
            continue
        resolved = _candidate_ref(event, payload)
        if resolved is None or resolved[0] not in allowed_types:
            continue
        outcome_type, reference = resolved
        candidate = OutcomeCandidate(
            outcome_type=outcome_type,
            reference=reference,
            event_id=event.event_id,
            status=payload.status.value,
            occurred_at=event.occurred_at.isoformat(),
        )
        key = (outcome_type, reference)
        previous = current.get(key)
        if previous is None or (event.occurred_at, event.event_id) > (
            previous[0].occurred_at,
            previous[0].event_id,
        ):
            current[key] = (event, candidate)
    return tuple(
        item[1]
        for item in sorted(
            current.values(),
            key=lambda item: (
                OUTCOME_PRECEDENCE.index(item[1].outcome_type),
                item[1].reference,
            ),
        )
    )


def _candidate_ref(event: NormalizedEvent, payload: OutcomePayload) -> tuple[str, TypedRef] | None:
    if payload.outcome_type == "git.commit" and payload.reference:
        return "git.commit", TypedRef("git.commit", payload.reference)
    if event.source.adapter == "george" and payload.outcome_type:
        return "george.entry", TypedRef("george.entry", event.source.native_id)
    if payload.outcome_type == "fab.job" and payload.reference:
        return "fab.job", TypedRef("fab.job", payload.reference)
    if payload.outcome_type == "fab.attempt":
        return "fab.attempt", TypedRef("fab.attempt", event.source.native_id)
    return None


def _build_graph(
    crosswalks: tuple[CrosswalkRecord, ...],
    relations: tuple[RelationRecord, ...],
    events: tuple[NormalizedEvent, ...],
) -> dict[TypedRef, tuple[_Edge, ...]]:
    graph: dict[TypedRef, list[_Edge]] = {}

    def add(source: TypedRef, edge: _Edge) -> None:
        graph.setdefault(source, []).append(edge)

    for link in crosswalks:
        left = TypedRef.from_identity(link.left)
        right = TypedRef.from_identity(link.right)
        add(
            left,
            _Edge(
                right,
                PathStep(
                    PathStepKind.CROSSWALK,
                    left,
                    right,
                    link.link_id,
                    link.record_id,
                    None,
                    "association",
                    link.evidence_event_ids,
                ),
                False,
            ),
        )
        add(
            right,
            _Edge(
                left,
                PathStep(
                    PathStepKind.CROSSWALK,
                    right,
                    left,
                    link.link_id,
                    link.record_id,
                    None,
                    "association",
                    link.evidence_event_ids,
                ),
                False,
            ),
        )
    for relation in relations:
        add(
            relation.subject,
            _Edge(
                relation.object,
                PathStep(
                    PathStepKind.RELATION,
                    relation.subject,
                    relation.object,
                    relation.relation_id,
                    relation.record_id,
                    relation.predicate.value,
                    "forward",
                    relation.evidence_event_ids,
                ),
                _relation_supports_attribution(relation),
            ),
        )
        add(
            relation.object,
            _Edge(
                relation.subject,
                PathStep(
                    PathStepKind.RELATION,
                    relation.object,
                    relation.subject,
                    relation.relation_id,
                    relation.record_id,
                    relation.predicate.value,
                    "reverse",
                    relation.evidence_event_ids,
                ),
                _relation_supports_attribution(relation),
            ),
        )
    for event in events:
        payload = event.payload
        if (
            isinstance(payload, OutcomePayload)
            and payload.outcome_type == "fab.attempt"
            and payload.reference
        ):
            job = TypedRef("fab.job", payload.reference)
            attempt = TypedRef("fab.attempt", event.source.native_id)
            add(
                job,
                _Edge(
                    attempt,
                    PathStep(
                        PathStepKind.EVENT,
                        job,
                        attempt,
                        event.event_id,
                        None,
                        "attempt_of",
                        "forward",
                        (event.event_id,),
                    ),
                    False,
                ),
            )
    return {
        reference: tuple(
            sorted(
                edges,
                key=lambda item: (
                    item.target,
                    item.step.kind.value,
                    item.step.edge_id,
                    item.step.direction,
                ),
            )
        )
        for reference, edges in graph.items()
    }


def _relation_supports_attribution(relation: RelationRecord) -> bool:
    pair = (relation.subject.namespace, relation.object.namespace)
    if relation.predicate is RelationKind.PRODUCED:
        return pair in {
            ("fab.job", "somm.call"),
            ("fab.job", "git.commit"),
            ("fab.job", "codex.session"),
            ("fab.job", "claude-code.session"),
            ("fab.job", "opencode.session"),
            ("fab.attempt", "somm.call"),
            ("fab.attempt", "git.commit"),
            ("fab.attempt", "codex.session"),
            ("fab.attempt", "claude-code.session"),
            ("fab.attempt", "opencode.session"),
        }
    if relation.predicate is RelationKind.VERIFIES:
        return pair in {
            ("george.entry", "fab.job"),
            ("george.entry", "git.commit"),
        }
    if relation.predicate is RelationKind.ATTEMPT_OF:
        return pair == ("fab.attempt", "fab.job")
    if relation.predicate is RelationKind.PART_OF:
        return pair in {
            ("somm.call", "fab.attempt"),
            ("fab.attempt", "fab.job"),
        }
    if relation.predicate is RelationKind.EVALUATES:
        # A synchronous Somm eval may explicitly stamp the Git implementation
        # being exercised even when no outer Fab attempt exists. The adapter
        # emits this edge only from the source-owned eval receipt.
        return pair == ("somm.call", "git.commit")
    return False


def _cost_roots(
    cost: NormalizedEvent, by_id: dict[str, NormalizedEvent]
) -> tuple[tuple[TypedRef, ...], tuple[str, ...]]:
    pending = deque(
        event_id for event_id in (cost.parent_event_id, cost.session_id) if event_id is not None
    )
    seen = {cost.event_id}
    lineage = {cost.event_id}
    roots: set[TypedRef] = set()
    while pending:
        event_id = pending.popleft()
        if event_id in seen:
            continue
        seen.add(event_id)
        event = by_id.get(event_id)
        if event is None:
            continue
        lineage.add(event.event_id)
        reference = _event_ref(event)
        if reference is not None:
            roots.add(reference)
        for parent_id in (event.parent_event_id, event.session_id):
            if parent_id is not None and parent_id not in seen:
                pending.append(parent_id)
    return tuple(sorted(roots)), tuple(sorted(lineage))


def _event_ref(event: NormalizedEvent) -> TypedRef | None:
    if event.kind is EventKind.SESSION:
        namespaces = {
            "claude-code": "claude-code.session",
            "codex": "codex.session",
            "fab": "fab.job",
            "hermes": "hermes.session",
            "opencode": "opencode.session",
            "somm": "somm.session",
        }
        namespace = namespaces.get(event.source.adapter)
        return TypedRef(namespace, event.source.native_id) if namespace else None
    if event.kind is EventKind.MODEL_CALL and event.source.adapter == "somm":
        return TypedRef("somm.call", event.source.native_id)
    return None


def _walk_graph(
    roots: tuple[TypedRef, ...],
    graph: dict[TypedRef, tuple[_Edge, ...]],
    *,
    max_depth: int,
) -> dict[tuple[TypedRef, bool], _Walk]:
    queue: deque[_Walk] = deque()
    walks: dict[tuple[TypedRef, bool], _Walk] = {}
    for root in roots:
        walk = _Walk((root,), (), False)
        queue.append(walk)
        walks[(root, False)] = walk
    while queue:
        walk = queue.popleft()
        if len(walk.steps) >= max_depth:
            continue
        source = walk.references[-1]
        for edge in graph.get(source, ()):
            relation_used = walk.relation_used or edge.establishes_relation
            key = (edge.target, relation_used)
            if key in walks:
                continue
            next_walk = _Walk(
                (*walk.references, edge.target),
                (*walk.steps, edge.step),
                relation_used,
            )
            walks[key] = next_walk
            queue.append(next_walk)
    return walks


def _attribution_path(
    cost: NormalizedEvent,
    lineage_event_ids: tuple[str, ...],
    candidate: OutcomeCandidate,
    walk: _Walk,
) -> AttributionPath:
    events = set(lineage_event_ids)
    events.add(cost.event_id)
    events.add(candidate.event_id)
    link_ids: set[str] = set()
    link_record_ids: set[str] = set()
    relation_ids: set[str] = set()
    relation_record_ids: set[str] = set()
    for step in walk.steps:
        events.update(step.evidence_event_ids)
        if step.kind is PathStepKind.CROSSWALK:
            link_ids.add(step.edge_id)
            if step.revision_id:
                link_record_ids.add(step.revision_id)
        elif step.kind is PathStepKind.RELATION:
            relation_ids.add(step.edge_id)
            if step.revision_id:
                relation_record_ids.add(step.revision_id)
    return AttributionPath(
        references=walk.references,
        steps=walk.steps,
        event_ids=tuple(sorted(events)),
        link_ids=tuple(sorted(link_ids)),
        link_record_ids=tuple(sorted(link_record_ids)),
        relation_ids=tuple(sorted(relation_ids)),
        relation_record_ids=tuple(sorted(relation_record_ids)),
    )


def _rollups(records: list[OutcomeAttributionRecord]) -> tuple[OutcomeRollup, ...]:
    grouped: dict[tuple[str, TypedRef, str, str], tuple[Decimal, int]] = {}
    for record in records:
        if record.state is not AttributionState.ATTRIBUTED or record.outcome is None:
            continue
        key = (
            record.outcome.outcome_type,
            record.outcome.reference,
            record.outcome.status,
            record.economic_kind,
        )
        amount, count = grouped.get(key, (Decimal(0), 0))
        grouped[key] = (amount + record.amount_usd, count + 1)
    return tuple(
        OutcomeRollup(outcome_type, reference, status, kind, amount, count)
        for (outcome_type, reference, status, kind), (amount, count) in sorted(
            grouped.items(),
            key=lambda item: (
                OUTCOME_PRECEDENCE.index(item[0][0]),
                item[0][1],
                item[0][2],
                item[0][3],
            ),
        )
    )
