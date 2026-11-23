"""Notional list-price valuation for usage that a source reports without an amount.

Subscription coding agents report tokens but no money. A notional amount
answers "what would this usage cost at public API list prices?". It is never a
charge and never enters selected (marginal) accounting. Notional copies are
built in memory: stored events are not changed. Each copy is marked
``kind=notional``, ``basis=computed``, and ``accuracy=estimated``, and carries
``pricing_version`` so every figure names the table that produced it.

The built-in table holds standard-tier, short-context list prices per million
tokens with a source for each row. Long-context surcharges, priority/fast
tiers, and batch discounts are not modeled, so for very long prompts the figure
is a lower bound. A model without a row is counted as unpriced rather than
guessed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from milton.errors import MiltonError
from milton.model import (
    CostAccuracy,
    CostBasis,
    CostKind,
    CostObservationRole,
    CostPayload,
    CoverageStatus,
    EventKind,
    JsonValue,
    NormalizedEvent,
)

PRICING_TABLE_VERSION = "2026-11-23"
NOTIONAL_PRICING_VERSION = f"milton-list-prices/{PRICING_TABLE_VERSION}"
_MILLION = Decimal(1_000_000)

_ANTHROPIC = (
    "https://platform.claude.com/docs/en/about-claude/pricing (cache write = 5-minute write)"
)
_OPENAI = "https://developers.openai.com/api/docs/pricing (cache write = 30-minute write)"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """List prices in USD per million tokens."""

    provider: str
    model: str
    input: Decimal
    cached_input: Decimal
    cache_write: Decimal
    output: Decimal
    # OpenAI reports cached tokens as a subset of input tokens; Anthropic
    # reports cache reads and writes separately from input.
    input_includes_cached: bool
    source: str


def _price(
    provider: str,
    model: str,
    input_: str,
    cached: str,
    write: str,
    output: str,
    source: str,
) -> ModelPrice:
    return ModelPrice(
        provider=provider,
        model=model,
        input=Decimal(input_),
        cached_input=Decimal(cached),
        cache_write=Decimal(write),
        output=Decimal(output),
        input_includes_cached=provider == "openai",
        source=source,
    )


BUILTIN_PRICES: tuple[ModelPrice, ...] = (
    _price("anthropic", "claude-fable-5-2", "8", "0.20", "10", "40", _ANTHROPIC),
    _price("anthropic", "claude-fable-5-1", "10", "0.25", "12.50", "50", _ANTHROPIC),
    _price("anthropic", "claude-fable-5", "10", "1", "12.50", "50", _ANTHROPIC),
    _price("anthropic", "claude-opus-5-5", "4", "0.20", "5", "20", _ANTHROPIC),
    _price("anthropic", "claude-opus-5", "5", "0.50", "6.25", "25", _ANTHROPIC),
    _price("anthropic", "claude-opus-4-8", "5", "0.50", "6.25", "25", _ANTHROPIC),
    _price("anthropic", "claude-opus-4-7", "5", "0.50", "6.25", "25", _ANTHROPIC),
    _price("anthropic", "claude-opus-4-6", "5", "0.50", "6.25", "25", _ANTHROPIC),
    _price("anthropic", "claude-sonnet-5-5", "2", "0.10", "2.50", "10", _ANTHROPIC),
    _price("anthropic", "claude-sonnet-5", "2", "0.20", "2.50", "10", _ANTHROPIC),
    # Haiku 5.5 doubles past 100K-token prompts; the short-prompt rate is used.
    _price("anthropic", "claude-haiku-5-5", "0.10", "0.01", "0.125", "0.50", _ANTHROPIC),
    _price("openai", "gpt-6.2-astra", "8", "0.40", "10", "40", _OPENAI),
    _price("openai", "gpt-6.2-sol", "2", "0.10", "2.50", "10", _OPENAI),
    _price("openai", "gpt-6.1-sol", "2", "0.10", "2.50", "10", _OPENAI),
)

_DATE_SUFFIX = re.compile(r"-\d{8}$")


def normalize_model(model: str) -> str:
    """Map source spellings (``anthropic/claude-opus-4.6``, dated ids) to table keys."""

    name = model.strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[1]
    name = _DATE_SUFFIX.sub("", name)
    if name.startswith("claude-"):
        name = name.replace(".", "-")
    return name


@dataclass(frozen=True, slots=True)
class PriceTable:
    prices: Mapping[str, ModelPrice]
    version: str = NOTIONAL_PRICING_VERSION

    @classmethod
    def builtin(cls) -> PriceTable:
        return cls({price.model: price for price in BUILTIN_PRICES})

    @classmethod
    def from_file(cls, path: Path) -> PriceTable:
        """Load an operator table: ``{"version": ..., "models": [{...}, ...]}``."""

        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            prices = {}
            for row in document["models"]:
                price = _price(
                    str(row["provider"]),
                    normalize_model(str(row["model"])),
                    str(row["input"]),
                    str(row["cached_input"]),
                    str(row["cache_write"]),
                    str(row["output"]),
                    str(row.get("source", path.name)),
                )
                prices[price.model] = price
            version = str(document["version"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise MiltonError(f"invalid price table {path}: {error}") from error
        return cls(prices, version=version)

    def lookup(self, model: str | None) -> ModelPrice | None:
        if not model:
            return None
        return self.prices.get(normalize_model(model))


def notional_amount(payload: CostPayload, table: PriceTable) -> Decimal | None:
    """List-price value of one observation's tokens, or None when not computable."""

    price = table.lookup(payload.model)
    tokens = (
        payload.input_tokens,
        payload.cached_input_tokens,
        payload.cache_write_tokens,
        payload.output_tokens,
    )
    if price is None or all(value is None for value in tokens):
        return None
    input_tokens = payload.input_tokens or 0
    cached = payload.cached_input_tokens or 0
    uncached = max(input_tokens - cached, 0) if price.input_includes_cached else input_tokens
    total = (
        uncached * price.input
        + cached * price.cached_input
        + (payload.cache_write_tokens or 0) * price.cache_write
        + (payload.output_tokens or 0) * price.output
    )
    return total / _MILLION


def _unpriced(event: NormalizedEvent) -> CostPayload | None:
    if event.kind is not EventKind.COST or not isinstance(event.payload, CostPayload):
        return None
    payload = event.payload
    if payload.amount_usd is not None or payload.observation_role is CostObservationRole.ROLLUP:
        return None
    return payload


def notional_event(event: NormalizedEvent, table: PriceTable) -> NormalizedEvent | None:
    """An in-memory notional copy of an unpriced cost event, if it can be valued."""

    payload = _unpriced(event)
    if payload is None:
        return None
    amount = notional_amount(payload, table)
    if amount is None:
        return None
    priced = replace(
        payload,
        amount_usd=amount,
        kind=CostKind.NOTIONAL,
        basis=CostBasis.COMPUTED,
        accuracy=CostAccuracy.ESTIMATED,
        pricing_version=table.version,
    )
    coverage = dict(event.coverage)
    coverage["amount_usd"] = CoverageStatus.INFERRED
    coverage["pricing_version"] = CoverageStatus.INFERRED
    return replace(event, payload=priced, coverage=coverage)


def with_notional(
    events: Iterable[NormalizedEvent], table: PriceTable | None = None
) -> tuple[NormalizedEvent, ...]:
    """Events with each valuable unpriced cost observation replaced by its notional copy."""

    table = table or PriceTable.builtin()
    return tuple(notional_event(event, table) or event for event in events)


@dataclass(slots=True)
class NotionalSummary:
    """What notional valuation covered, and what it could not value."""

    pricing_version: str
    unpriced_cost_events: int = 0
    valued_events: int = 0
    amount_usd: Decimal = Decimal(0)
    by_model: dict[str, list[Decimal]] = field(default_factory=dict)
    unvalued_models: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "pricing_version": self.pricing_version,
            "scope": "unpriced_cost_observations_at_list_price",
            "unpriced_cost_events": self.unpriced_cost_events,
            "valued_events": self.valued_events,
            "amount_usd": str(self.amount_usd),
            "by_model": {
                model: {"events": int(values[0]), "amount_usd": str(values[1])}
                for model, values in sorted(self.by_model.items())
            },
            "unvalued_models": dict(sorted(self.unvalued_models.items())),
        }


def build_notional_summary(
    events: Iterable[NormalizedEvent], table: PriceTable | None = None
) -> NotionalSummary:
    table = table or PriceTable.builtin()
    summary = NotionalSummary(pricing_version=table.version)
    for event in events:
        payload = _unpriced(event)
        if payload is None:
            continue
        summary.unpriced_cost_events += 1
        amount = notional_amount(payload, table)
        model = normalize_model(payload.model) if payload.model else "(no model)"
        if amount is None:
            summary.unvalued_models[model] = summary.unvalued_models.get(model, 0) + 1
            continue
        summary.valued_events += 1
        summary.amount_usd += amount
        entry = summary.by_model.setdefault(model, [Decimal(0), Decimal(0)])
        entry[0] += 1
        entry[1] += amount
    return summary
