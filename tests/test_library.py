import tempfile
import unittest
from pathlib import Path

from src.evolution_agent import AppEvolver, InMemoryAgentMemoryStore, InMemoryStateStore


class FakeWorkspace:
    def prepare_pull_request(
        self, contract, observation, constitution, *, change_plan, hypothesis
    ):
        raise NotImplementedError


class LibraryTests(unittest.TestCase):
    def test_accepts_injected_in_memory_state_and_local_work_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = InMemoryStateStore()
            store.add_activity({
                "run_id": "run-1", "app_id": "demo", "agent_id": "analyst",
                "agent_name": "Analyst", "stage": "Observe", "status": "completed",
                "input_summary": "input", "output_summary": "output", "duration_ms": 1,
                "created_at": "2026-09-25T00:00:00Z",
            })
            work_root = Path(temporary_directory) / "work"
            evolver = AppEvolver(state_store=store, work_root=work_root)
            self.assertEqual("run-1", evolver.list_activity("demo")[0]["run_id"])
            self.assertEqual([], evolver.list_apps())
            self.assertTrue(work_root.is_dir())

    def test_custom_workspace_does_not_create_a_local_work_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_root = Path(temporary_directory) / "unused"
            workspace = FakeWorkspace()
            evolver = AppEvolver(
                workspace=workspace,
                memory_store=InMemoryAgentMemoryStore(),
                work_root=work_root,
            )
            self.assertFalse(work_root.exists())


if __name__ == "__main__":
    unittest.main()
