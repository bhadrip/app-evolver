from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class AgentTeam:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def document(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def all(self) -> list[dict[str, Any]]:
        return self.document()["agents"]

    def enabled(self) -> list[dict[str, Any]]:
        return [agent for agent in self.all() if agent["enabled"]]

    def get(self, agent_id: str, require_enabled: bool = False) -> dict[str, Any]:
        agent = next((item for item in self.all() if item["id"] == agent_id), None)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_id}")
        if require_enabled and not agent["enabled"]:
            raise ValueError(f"{agent['name']} is disabled")
        return agent

    def update(
        self,
        agent_id: str,
        *,
        name: str,
        enabled: bool,
        model: str,
        instructions: str,
    ) -> None:
        document = self.document()
        agent = next((item for item in document["agents"] if item["id"] == agent_id), None)
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
        self._write(document)

    def move(self, agent_id: str, direction: str) -> None:
        document = self.document()
        agents = document["agents"]
        index = next((index for index, item in enumerate(agents) if item["id"] == agent_id), None)
        if index is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(agents):
            agents[index], agents[target] = agents[target], agents[index]
            self._write(document)

    def _write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix="agents-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as temporary:
                json.dump(document, temporary, indent=2)
                temporary.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
