import json
import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.agents import AgentTeam


class AgentTeamTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "agents.json"
        self.path.write_text(json.dumps({
            "schemaVersion": 1,
            "agents": [{
                "id": "analyst",
                "name": "Analyst",
                "stage": "Observe",
                "enabled": True,
                "model": "deterministic",
                "access": "read-only",
                "instructions": "Group signals."
            }]
        }))
        self.team = AgentTeam(json.loads(self.path.read_text()))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_updates_agent_configuration(self):
        self.team.update(
            "analyst",
            name="Customer Signal Analyst",
            enabled=False,
            model="deterministic",
            instructions="Retain evidence when grouping signals.",
        )
        agent = self.team.get("analyst")
        self.assertEqual("Customer Signal Analyst", agent["name"])
        self.assertFalse(agent["enabled"])
        self.assertEqual([], self.team.enabled())

    def test_require_enabled_rejects_disabled_agent(self):
        self.team.update(
            "analyst", name="Analyst", enabled=False,
            model="deterministic", instructions="Group signals.",
        )
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.team.get("analyst", require_enabled=True)


if __name__ == "__main__":
    unittest.main()
