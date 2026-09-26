import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.store import StateStore


class ActivityStoreTests(unittest.TestCase):
    def test_records_observable_agent_behavior(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = StateStore(Path(temporary_directory) / "state.db")
            store.add_activity({
                "run_id": "run-1",
                "app_id": "demo",
                "agent_id": "analyst",
                "agent_name": "Signal Analyst",
                "stage": "Observe",
                "status": "completed",
                "input_summary": "7 signals",
                "output_summary": "2 themes",
                "duration_ms": 12,
                "created_at": "2026-09-25T00:00:00Z",
            })
            activity = store.activities()
            self.assertEqual("run-1", activity[0]["run_id"])
            self.assertEqual("2 themes", activity[0]["output_summary"])
            self.assertEqual(12, activity[0]["duration_ms"])


if __name__ == "__main__":
    unittest.main()

