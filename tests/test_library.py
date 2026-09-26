import tempfile
import unittest
from pathlib import Path

from src.evolution_agent import AppEvolver, InMemoryStateStore


class FakeWorkspace:
    def prepare_pull_request(self, contract, observation, constitution):
        raise NotImplementedError


class LibraryTests(unittest.TestCase):
    def test_accepts_injected_in_memory_state_and_local_work_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = InMemoryStateStore()
            work_root = Path(temporary_directory) / "work"
            evolver = AppEvolver(state_store=store, work_root=work_root)
            self.assertIs(store, evolver.store)
            self.assertEqual([], evolver.registry.all())
            self.assertTrue(work_root.is_dir())

    def test_custom_workspace_does_not_create_a_local_work_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_root = Path(temporary_directory) / "unused"
            workspace = FakeWorkspace()
            evolver = AppEvolver(workspace=workspace, work_root=work_root)
            self.assertIs(workspace, evolver.workspace)
            self.assertFalse(work_root.exists())


if __name__ == "__main__":
    unittest.main()
