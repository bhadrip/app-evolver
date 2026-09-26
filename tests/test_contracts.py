import json
import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.contracts import AppContract


class ContractTests(unittest.TestCase):
    def contract(self, root: Path) -> AppContract:
        (root / ".git").mkdir()
        (root / "evolution.json").write_text(json.dumps({
            "appId": "demo",
            "name": "Demo",
            "productIntent": "Demonstrate contracts.",
            "observationSource": {"kind": "fixture", "path": "observations.json"},
            "constitution": "constitution.json",
            "pullRequests": {"provider": "github", "baseBranch": "main", "draft": True},
            "mutablePaths": ["config/features.json"],
            "protectedPaths": ["src/"],
            "validationCommands": []
        }))
        return AppContract.load(root)

    def test_accepts_allowlisted_change(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.contract(Path(temporary_directory)).validate_changed_paths(["config/features.json"], 2)

    def test_rejects_protected_change(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "protected"):
                self.contract(Path(temporary_directory)).validate_changed_paths(["src/auth.py"], 2)

    def test_rejects_change_outside_surface(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "outside"):
                self.contract(Path(temporary_directory)).validate_changed_paths(["README.md"], 2)


if __name__ == "__main__":
    unittest.main()
