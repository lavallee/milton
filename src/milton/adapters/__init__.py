"""Built-in source adapters."""

from milton.adapters.barnowl_research_outcome import BarnowlResearchOutcomeAdapter
from milton.adapters.base import ContentPolicy, SourceAdapter
from milton.adapters.chip import ChipAdapter
from milton.adapters.claude_code import ClaudeCodeAdapter
from milton.adapters.codex import CodexAdapter
from milton.adapters.fab import FabAdapter
from milton.adapters.george import GeorgeAdapter
from milton.adapters.git import GitAdapter
from milton.adapters.hermes import HermesAdapter
from milton.adapters.memory_files import DecisionMemoryAdapter, NativeMemoryAdapter
from milton.adapters.opencode import OpenCodeAdapter
from milton.adapters.somm import SommAdapter
from milton.adapters.spindle import SpindleAdapter

BUILTIN_ADAPTERS: dict[
    str,
    type[ClaudeCodeAdapter]
    | type[BarnowlResearchOutcomeAdapter]
    | type[ChipAdapter]
    | type[CodexAdapter]
    | type[FabAdapter]
    | type[GeorgeAdapter]
    | type[GitAdapter]
    | type[HermesAdapter]
    | type[NativeMemoryAdapter]
    | type[DecisionMemoryAdapter]
    | type[OpenCodeAdapter]
    | type[SommAdapter]
    | type[SpindleAdapter],
] = {
    "barnowl-research-outcome": BarnowlResearchOutcomeAdapter,
    "claude-code": ClaudeCodeAdapter,
    "chip": ChipAdapter,
    "codex": CodexAdapter,
    "fab": FabAdapter,
    "george": GeorgeAdapter,
    "git": GitAdapter,
    "hermes": HermesAdapter,
    "native-memory": NativeMemoryAdapter,
    "decision-memory": DecisionMemoryAdapter,
    "opencode": OpenCodeAdapter,
    "somm": SommAdapter,
    "spindle": SpindleAdapter,
}


def built_in_adapters(names: list[str] | None = None) -> list[SourceAdapter]:
    selected = names or sorted(BUILTIN_ADAPTERS)
    return [BUILTIN_ADAPTERS[name]() for name in selected]


__all__ = [
    "BUILTIN_ADAPTERS",
    "BarnowlResearchOutcomeAdapter",
    "ClaudeCodeAdapter",
    "ChipAdapter",
    "CodexAdapter",
    "ContentPolicy",
    "FabAdapter",
    "GeorgeAdapter",
    "GitAdapter",
    "HermesAdapter",
    "NativeMemoryAdapter",
    "DecisionMemoryAdapter",
    "OpenCodeAdapter",
    "SommAdapter",
    "SpindleAdapter",
    "SourceAdapter",
    "built_in_adapters",
]
