"""Injectable durable memory for versioned agents."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Protocol

from .errors import ConfigurationError, NotFoundError
from .models import AgentMemory


class AgentMemoryStore(Protocol):
    """CRUD boundary for in-memory, file, Postgres, or remote memory adapters."""

    def create(self, memory: AgentMemory) -> AgentMemory: ...
    def get(self, memory_id: str) -> AgentMemory: ...
    def list(
        self,
        *,
        app_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentMemory]: ...
    def update(self, memory_id: str, content: str) -> AgentMemory: ...
    def delete(self, memory_id: str) -> None: ...


class InMemoryAgentMemoryStore:
    def __init__(self, memories: list[AgentMemory] | None = None):
        self._memories = copy.deepcopy(memories or [])
        self._lock = threading.RLock()

    def create(self, memory: AgentMemory) -> AgentMemory:
        with self._lock:
            self._memories.append(copy.deepcopy(memory))
            self._changed()
            return copy.deepcopy(memory)

    def get(self, memory_id: str) -> AgentMemory:
        with self._lock:
            memory = next((item for item in self._memories if item["id"] == memory_id), None)
            if not memory:
                raise NotFoundError(f"Agent memory does not exist: {memory_id}")
            return copy.deepcopy(memory)

    def list(
        self,
        *,
        app_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentMemory]:
        with self._lock:
            values = self._memories
            if app_id is not None:
                values = [item for item in values if item["app_id"] == app_id]
            if agent_id is not None:
                values = [item for item in values if item["agent_id"] == agent_id]
            return copy.deepcopy(list(reversed(values))[:limit])

    def update(self, memory_id: str, content: str) -> AgentMemory:
        with self._lock:
            memory = next((item for item in self._memories if item["id"] == memory_id), None)
            if not memory:
                raise NotFoundError(f"Agent memory does not exist: {memory_id}")
            clean_content = content.strip()[:4_000]
            if not clean_content:
                raise ConfigurationError("Agent memory content is required")
            memory["content"] = clean_content
            memory["revision"] += 1
            self._changed()
            return copy.deepcopy(memory)

    def delete(self, memory_id: str) -> None:
        with self._lock:
            before = len(self._memories)
            self._memories = [item for item in self._memories if item["id"] != memory_id]
            if len(self._memories) == before:
                raise NotFoundError(f"Agent memory does not exist: {memory_id}")
            self._changed()

    def _changed(self) -> None:
        pass


class JsonFileAgentMemoryStore(InMemoryAgentMemoryStore):
    """Small durable v0 adapter; production hosts can inject Postgres instead."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        memories: list[AgentMemory] = []
        if self.path.exists():
            document = json.loads(self.path.read_text())
            memories = document.get("memories", [])
        super().__init__(memories)

    def _changed(self) -> None:
        document = {"schemaVersion": 1, "memories": self._memories}
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="agent-memory-", suffix=".json", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w") as temporary:
                json.dump(document, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
