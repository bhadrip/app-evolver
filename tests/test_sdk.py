import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.evolution_agent import AppEvolver


def create_app(root: Path) -> Path:
    app = root / "demo-app"
    app.mkdir()
    subprocess.run(["git", "init", "-q", app], check=True)
    (app / "evolution.json").write_text(json.dumps({
        "schemaVersion": 1,
        "appId": "demo",
        "name": "Demo app",
        "productIntent": "Demonstrate the public SDK.",
        "observationSource": {
            "kind": "fixture", "path": "observations.json",
            "requiredProvenance": ["appVersion", "appRevision"],
        },
        "constitution": "constitution.json",
        "pullRequests": {"provider": "github", "baseBranch": "main", "draft": True},
        "mutablePaths": ["features.json"],
        "protectedPaths": ["evolution.json"],
        "validationCommands": [],
        "capabilities": {
            "dark_mode": {
                "description": "Add a dark theme.",
                "signalKeywords": ["dark mode"],
                "successMetric": "dark theme activation",
                "risk": "low",
                "change": {
                    "kind": "json_set", "path": "features.json",
                    "key": "darkMode", "value": True,
                },
            }
        },
    }))
    (app / "constitution.json").write_text(json.dumps({
        "schemaVersion": 1,
        "purpose": "Keep the demo useful.",
        "nonNegotiables": ["Use pull requests."],
        "humanInTheLoop": {"observationSelection": "required"},
        "limits": {
            "maxChangedFiles": 2,
            "validationTimeoutSeconds": 30,
            "maxEvidenceSamples": 5,
        },
    }))
    (app / "features.json").write_text("{}\n")
    subprocess.run(["git", "add", "."], cwd=app, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-q", "-m", "initial app",
        ],
        cwd=app,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=app, text=True,
        stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    (app / "observations.json").write_text(json.dumps({
        "observations": [{
            "id": 1,
            "type": "feedback_submitted",
            "appVersion": "1.0.0",
            "appRevision": revision,
            "payload": {"message": "Please add dark mode"},
        }]
    }))
    subprocess.run(["git", "add", "observations.json"], cwd=app, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-q", "-m", "add observation fixture",
        ],
        cwd=app,
        check=True,
    )
    return app


class RecordingWorkspace:
    def __init__(self):
        self.change_plan = None

    def prepare_pull_request(
        self, contract, observation, constitution, *, change_plan, hypothesis
    ):
        self.change_plan = change_plan
        return {
            "id": "proposal-1",
            "app_id": contract.app_id,
            "observation_id": observation["id"],
            "hypothesis": hypothesis,
            "success_metric": contract.capability(observation["theme"])["successMetric"],
            "risk": "low",
            "branch": "evolution/proposal-1",
            "sandbox_path": "/tmp/proposal-1",
            "base_commit": "a" * 40,
            "proposed_commit": "b" * 40,
            "diff": "+ darkMode",
            "validation": "$ test\nOK",
            "evidence": observation["evidence"],
            "customer_app_versions": observation["evidence"]["appVersions"],
            "status": "checks_passed",
            "pr_number": None,
            "pr_url": None,
        }


class PublicSdkTests(unittest.TestCase):
    def test_public_workflow_without_adapter_internals(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = create_app(root)
            evolver = AppEvolver(work_root=root / "work")

            registered = evolver.register_app(app)
            governance = evolver.get_governance(registered["id"])
            result = evolver.sync_and_analyze(registered["id"])
            observations = evolver.list_observations(registered["id"])
            selected = evolver.select_observation(observations[0]["id"])

            self.assertEqual("demo", evolver.default_app_id())
            self.assertEqual("Demo app", governance["app"]["name"])
            self.assertEqual(1, result["inserted"])
            self.assertEqual([observations[0]["id"]], result["observation_ids"])
            self.assertEqual("selected", selected["status"])
            self.assertEqual("1.0.0", observations[0]["evidence"]["appVersions"][0]["version"])
            self.assertEqual("Signal Analyst", evolver.list_activity("demo")[0]["agent_name"])
            self.assertEqual(
                [
                    ["signal-analyst"],
                    ["product-manager", "ux-researcher"],
                    ["ui-designer"],
                    ["software-engineer"],
                    [
                        "accessibility-reviewer",
                        "evidence-reviewer",
                        "quality-reviewer",
                    ],
                ],
                evolver.get_agent_graph()["waves"],
            )

    def test_pr_proposal_carries_agent_plan_version_evidence_and_tests(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = create_app(root)
            workspace = RecordingWorkspace()
            evolver = AppEvolver(workspace=workspace, work_root=root / "unused")
            evolver.register_app(app)
            evolver.create_agent_memory(
                app_id="demo",
                agent_id="ui-designer",
                kind="lesson",
                content="Keep the primary action visible on narrow screens.",
            )
            evolver.sync_and_analyze("demo")
            observation = evolver.list_observations("demo")[0]
            evolver.select_observation(observation["id"])
            proposal = evolver.prepare_pull_request(observation["id"])

            self.assertEqual("features.json", workspace.change_plan["path"])
            self.assertEqual("1.0.0", proposal["customer_app_versions"][0]["version"])
            self.assertEqual("$ test\nOK", proposal["validation"])
            self.assertIn("dark theme activation", proposal["hypothesis"])
            self.assertIn(
                "Keep the primary action visible on narrow screens.",
                proposal["agent_evidence"]["ui-designer"]["appliedLessons"],
            )
            self.assertTrue(
                {
                    "Product Manager", "UX Researcher", "UI Designer",
                    "Software Engineer", "Quality Reviewer", "Evidence Reviewer",
                    "Accessibility Reviewer",
                }
                <= {item["agent_name"] for item in evolver.list_activity("demo")},
            )
            outcome_memories = evolver.record_pull_request_outcome(
                proposal["id"], outcome="rejected", feedback="Primary action was obscured."
            )
            self.assertEqual(len(proposal["agent_versions"]), len(outcome_memories))

            reopened = AppEvolver(work_root=root / "unused")
            reopened.register_app(app)
            self.assertGreaterEqual(len(reopened.list_agent_memory("demo")), 2)

    def test_cli_observe_uses_the_public_workflow(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = create_app(root)
            environment = dict(os.environ, APP_EVOLVER_WORK_DIR=str(root / "work"))
            result = subprocess.run(
                [
                    sys.executable, "-m", "src.evolution_agent.cli",
                    "--app-path", str(app), "--json", "observe",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(1, payload["run"]["inserted"])
            self.assertEqual("dark_mode", payload["observations"][0]["theme"])

    def test_cli_memory_survives_separate_processes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = create_app(root)
            environment = dict(os.environ, APP_EVOLVER_WORK_DIR=str(root / "work"))
            base = [
                sys.executable, "-m", "src.evolution_agent.cli",
                "--app-path", str(app), "--json",
            ]
            remembered = subprocess.run(
                base + [
                    "remember", "ui-designer",
                    "Keep the primary action visible on narrow screens.",
                ],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(0, remembered.returncode, remembered.stderr)
            listed = subprocess.run(
                base + ["memory"],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(0, listed.returncode, listed.stderr)
            memories = json.loads(listed.stdout)
            self.assertEqual("ui-designer", memories[0]["agent_id"])
            self.assertEqual("1.0.0", memories[0]["agent_version"])


if __name__ == "__main__":
    unittest.main()
