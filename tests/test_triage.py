import json
import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.contracts import AppContract
from src.evolution_agent.store import StateStore
from src.evolution_agent.triage import triage


class TriageTests(unittest.TestCase):
    def test_groups_feedback_using_grounded_capability_keywords(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / ".git").mkdir()
            (root / "evolution.json").write_text(json.dumps({
                "appId": "demo",
                "observationEndpoint": "http://example.invalid",
                "mutablePaths": ["features.json"],
                "protectedPaths": [],
                "validationCommands": [],
                "capabilities": {
                    "wishlist": {
                        "description": "Add a wishlist.",
                        "signalKeywords": ["wishlist", "save for later"]
                    }
                }
            }))
            contract = AppContract.load(root)
            store = StateStore(root / "state.db")
            store.add_signals("demo", [
                {"id": 1, "type": "feedback_submitted", "payload": {"message": "Need a wishlist"}},
                {"id": 2, "type": "page_viewed", "payload": {}},
            ])
            result = triage(store, contract, max_samples=5)
            self.assertEqual(1, len(result))
            observation = store.observation(result[0])
            self.assertEqual("wishlist", observation["theme"])
            self.assertEqual(1, observation["evidence"]["signalCount"])


if __name__ == "__main__":
    unittest.main()

