import json
import tempfile
import unittest
from pathlib import Path

from src.evolution_agent.agents import Agent, AgentRequest, AgentTeam, BaseAgent


class DependencyEchoAgent(BaseAgent):
    task = "echo"

    def execute(self, payload):
        dependencies = sorted(payload.get("dependency_outputs", {}))
        return {"dependencies": dependencies}, f"Saw {len(dependencies)} dependencies"


class AgentTeamTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "agents.json"
        self.path.write_text(json.dumps({
            "schemaVersion": 1,
            "workflow": {"nodes": [{"agentId": "analyst", "dependsOn": []}]},
            "agents": [{
                "id": "analyst",
                "kind": "signal_analyst",
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

    def test_builtin_agent_implements_normalized_protocol(self):
        agent = self.team.get_agent("analyst", require_enabled=True)
        self.assertIsInstance(agent, Agent)
        response = agent.run(AgentRequest(
            run_id="run-1",
            app_id="demo",
            task="analyze_signals",
            payload={
                "signals": [{
                    "source_id": 1,
                    "event_type": "feedback_submitted",
                    "payload": {"message": "Please add dark mode"},
                }],
                "capabilities": {
                    "dark_mode": {
                        "description": "Add a dark theme.",
                        "signalKeywords": ["dark mode"],
                    }
                },
                "max_samples": 5,
            },
        ))
        self.assertEqual("analyst", response.agent_id)
        self.assertEqual("dark_mode", response.payload["themes"][0]["theme"])

    def test_composite_groups_parallel_agents_then_runs_dependents_in_series(self):
        definition = self.team.get("analyst")
        definitions = []
        for agent_id in ("research-a", "research-b", "synthesis"):
            item = dict(definition)
            item["id"] = agent_id
            item["kind"] = "dependency_echo"
            definitions.append(item)
        team = AgentTeam({
            "schemaVersion": 1,
            "workflow": {"nodes": [
                {"agentId": "research-a", "dependsOn": []},
                {"agentId": "research-b", "dependsOn": []},
                {"agentId": "synthesis", "dependsOn": ["research-a", "research-b"]},
            ]},
            "agents": definitions,
        }, agent_types={"dependency_echo": DependencyEchoAgent})
        self.assertEqual(
            [["research-a", "research-b"], ["synthesis"]],
            team.execution_waves(),
        )
        request = lambda agent_id: AgentRequest(
            run_id="run-1", app_id="demo", task="echo", payload={},
        )
        responses = team.run_composite({
            agent_id: request(agent_id)
            for agent_id in ("research-a", "research-b", "synthesis")
        })
        self.assertEqual({"research-a", "research-b", "synthesis"}, set(responses))
        self.assertEqual(
            ["research-a", "research-b"], responses["synthesis"].payload["dependencies"]
        )

    def test_rejects_a_cyclic_runtime_graph_without_replacing_the_valid_graph(self):
        original = self.team.graph()
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.team.configure_graph([{"agentId": "analyst", "dependsOn": ["analyst"]}])
        self.assertEqual(original, self.team.graph())


if __name__ == "__main__":
    unittest.main()
