"""Stable identity-scoped activity projection for downstream consumers."""

from __future__ import annotations

from dataclasses import dataclass

from milton.crosswalk import CrosswalkRecord, ExternalIdentity
from milton.model import EventKind, JsonValue, NormalizedEvent, OutcomePayload, stable_id
from milton.relations import RelationRecord, TypedRef
from milton.report import MiltonReport, build_report
from milton.store import MiltonStore


@dataclass(frozen=True, slots=True)
class OutcomeSummary:
    outcome_type: str | None
    status: str
    count: int

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "outcome_type": self.outcome_type,
            "status": self.status,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    root: ExternalIdentity
    related_identities: tuple[ExternalIdentity, ...]
    links: tuple[CrosswalkRecord, ...]
    relations: tuple[RelationRecord, ...]
    report: MiltonReport
    outcomes: tuple[OutcomeSummary, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 2,
            "root": {"namespace": self.root.namespace, "value": self.root.value},
            "related_identities": [
                {"namespace": item.namespace, "value": item.value}
                for item in self.related_identities
            ],
            "links": [
                {
                    "left": {
                        "namespace": link.left.namespace,
                        "value": link.left.value,
                    },
                    "right": {
                        "namespace": link.right.namespace,
                        "value": link.right.value,
                    },
                    "method": link.method.value,
                    "confidence": link.confidence,
                    "evidence_event_ids": list(link.evidence_event_ids),
                    "note": link.note,
                }
                for link in self.links
            ],
            "relations": [relation.to_dict() for relation in self.relations],
            "report": self.report.to_dict(),
            "outcomes": [item.to_dict() for item in self.outcomes],
        }

    def to_text(self) -> str:
        lines = [
            "Milton activity",
            "",
            f"Identity: {self.root.namespace}={self.root.value}",
            f"Related identities: {len(self.related_identities) - 1}",
            f"Events: {self.report.event_count}",
            f"Cost: ${self.report.total_cost_usd}",
        ]
        if self.outcomes:
            lines.extend(
                [
                    "",
                    "Outcomes:",
                    *[
                        f"  {item.outcome_type or 'unknown'} / {item.status}: {item.count}"
                        for item in self.outcomes
                    ],
                ]
            )
        if self.links:
            lines.extend(
                [
                    "",
                    "Trace links:",
                    *[
                        f"  {link.left.namespace}={link.left.value} "
                        f"--{link.method.value}--> "
                        f"{link.right.namespace}={link.right.value}"
                        for link in self.links
                    ],
                ]
            )
        if self.relations:
            lines.extend(
                [
                    "",
                    "Directed relations:",
                    *[
                        f"  {relation.subject.namespace}={relation.subject.value} "
                        f"--{relation.predicate.value}/{relation.method.value}--> "
                        f"{relation.object.namespace}={relation.object.value}"
                        for relation in self.relations
                    ],
                ]
            )
        return "\n".join(lines)


def build_activity(
    store: MiltonStore,
    root: ExternalIdentity,
    *,
    max_depth: int = 4,
) -> ActivitySnapshot:
    references = store.connected_work_refs(TypedRef.from_identity(root), max_depth=max_depth)
    identities = tuple(reference.to_identity() for reference in references)
    identity_set = set(identities)
    reference_set = set(references)
    seed_ids: set[str] = set()
    for identity in identities:
        reference = TypedRef.from_identity(identity)
        event = store.event_for_ref(reference)
        if event is not None:
            seed_ids.add(event.event_id)
            continue
        adapter = store.adapter_for_ref(reference)
        if adapter is not None and identity.namespace.endswith(".session"):
            # A windowed ingest may capture children of a session/job whose
            # creation predates the window. Stable parent identity still lets
            # the consumer recover those descendants without inventing a row.
            seed_ids.add(stable_id("evt", adapter, EventKind.SESSION.value, identity.value))
        elif identity.namespace == "fab.job":
            seed_ids.add(stable_id("evt", "fab", EventKind.SESSION.value, identity.value))

    events = store.event_family(seed_ids)
    return ActivitySnapshot(
        root=root,
        related_identities=identities,
        links=tuple(
            link
            for link in store.current_crosswalks(identities)
            if link.left in identity_set and link.right in identity_set
        ),
        relations=tuple(
            relation
            for relation in store.current_relations(references)
            if relation.subject in reference_set and relation.object in reference_set
        ),
        report=build_report(events),
        outcomes=_outcome_summaries(events),
    )


def _outcome_summaries(events: tuple[NormalizedEvent, ...]) -> tuple[OutcomeSummary, ...]:
    counts: dict[tuple[str | None, str], int] = {}
    for event in events:
        if not isinstance(event.payload, OutcomePayload):
            continue
        key = (event.payload.outcome_type, event.payload.status.value)
        counts[key] = counts.get(key, 0) + 1
    return tuple(
        OutcomeSummary(outcome_type, status, count)
        for (outcome_type, status), count in sorted(
            counts.items(), key=lambda item: (item[0][0] or "", item[0][1])
        )
    )
