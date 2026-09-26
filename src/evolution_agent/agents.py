from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class AgentTeam:
    """Process-local composite-agent configuration for v0."""

    def __init__(self, document: dict[str, Any]):
        self._document = copy.deepcopy(document)

    @classmethod
    def from_path(cls, path: Path) -> "AgentTeam":
        return cls(json.loads(path.read_text()))

    def document(self) -> dict[str, Any]:
        return copy.deepcopy(self._document)

    def all(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._document["agents"])

    def enabled(self) -> list[dict[str, Any]]:
        return [agent for agent in self.all() if agent["enabled"]]

    def get(self, agent_id: str, require_enabled: bool = False) -> dict[str, Any]:
        agent = next((item for item in self._document["agents"] if item["id"] == agent_id), None)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_id}")
        if require_enabled and not agent["enabled"]:
            raise ValueError(f"{agent['name']} is disabled")
        return copy.deepcopy(agent)

    def update(
        self,
        agent_id: str,
        *,
        name: str,
        enabled: bool,
        model: str,
        instructions: str,
    ) -> None:
        agent = next((item for item in self._document["agents"] if item["id"] == agent_id), None)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_id}")
        clean_name = name.strip()[:80]
        clean_model = model.strip()[:80]
        clean_instructions = instructions.strip()[:2_000]
        if not clean_name or not clean_model or not clean_instructions:
            raise ValueError("Name, model, and instructions are required")
        agent.update(
            name=clean_name,
            enabled=enabled,
            model=clean_model,
            instructions=clean_instructions,
        )
