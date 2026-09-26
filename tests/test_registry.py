import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.registry import AppRegistry


class RegistryTests(unittest.TestCase):
    def test_registers_app_from_its_own_contract(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "demo-app"
            app.mkdir()
            subprocess.run(["git", "init", "-q", app], check=True)
            (app / "evolution.json").write_text(json.dumps({
                "appId": "demo",
                "name": "Demo app",
                "productIntent": "Test registration.",
                "observationSource": {"kind": "fixture", "path": "observations.json"},
                "constitution": "constitution.json",
                "pullRequests": {"provider": "github", "baseBranch": "main", "draft": True},
                "mutablePaths": ["features.json"],
                "protectedPaths": ["evolution.json"],
                "validationCommands": []
            }))
            registry = AppRegistry()
            registered = registry.register(app)
            self.assertEqual("demo", registered["id"])
            self.assertEqual(str(app.resolve()), registry.get("demo")["path"])


if __name__ == "__main__":
    unittest.main()
