import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.errors import ConfigurationError
from src.evolution_agent.memory import JsonFileAgentMemoryStore


class AgentMemoryStoreTests(unittest.TestCase):
    def test_json_memory_survives_reopen_and_supports_reviewable_crud(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.json"
            store = JsonFileAgentMemoryStore(path)
            created = store.create({
                "id": "memory-1",
                "app_id": "demo",
                "agent_id": "ui-designer",
                "agent_version": "1.0.0",
                "agent_revision": "abc123def456",
                "kind": "lesson",
                "content": "Keep the primary action visible on narrow screens.",
                "evidence": {"pr": 12},
                "revision": 1,
                "created_at": "2026-09-25T00:00:00Z",
            })
            self.assertEqual("memory-1", created["id"])

            reopened = JsonFileAgentMemoryStore(path)
            self.assertEqual(1, len(reopened.list(app_id="demo", agent_id="ui-designer")))
            updated = reopened.update("memory-1", "Keep primary actions visible and labeled.")
            self.assertEqual(2, updated["revision"])
            with self.assertRaises(ConfigurationError):
                reopened.update("memory-1", "   ")
            reopened.delete("memory-1")
            self.assertEqual([], reopened.list())


if __name__ == "__main__":
    unittest.main()
