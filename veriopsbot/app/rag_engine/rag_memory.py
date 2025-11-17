"""Lightweight in-memory state for tenant conversations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class MemoryTurn:
    role: str
    content: str


@dataclass
class MemoryState:
    """Conversation memory shared across RAG pipeline components."""

    tenant_id: int | None = None
    turns: List[MemoryTurn] = field(default_factory=list)
    max_turns: int = 20

    def remember(self, role: str, content: str) -> None:
        """Append a turn and trim history so prompts stay bounded."""
        self.turns.append(MemoryTurn(role=role, content=content))
        if len(self.turns) > self.max_turns:
            # Keep only the most recent turns to bound memory usage.
            self.turns = self.turns[-self.max_turns :]

    def as_dict(self) -> Dict[str, List[Dict[str, str]]]:
        """Serialize the memory for debugging or persistence."""
        return {
            "tenant_id": self.tenant_id,
            "turns": [turn.__dict__ for turn in self.turns],
        }

    def transcript(self) -> str:
        """Return a plain-text transcript useful for prompts."""
        return "\n".join(f"{turn.role}: {turn.content}" for turn in self.turns)
