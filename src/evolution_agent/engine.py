from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import AgentTeam
from .contracts import AppContract
from .sandbox import Sandbox
from .store import StateStore
from .triage import triage


ROOT = Path(__file__).resolve().parents[2]


class Engine:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()
        self.config = json.loads((self.root / "agent-config.json").read_text())
        self.constitution = json.loads((self.root / "constitution.json").read_text())
        self.store = StateStore(self.root / self.config["stateDatabase"])
        self.sandbox = Sandbox(self.root / self.config["sandboxRoot"], self.constitution)
        self.agents = AgentTeam(self.root / self.config["agentTeam"])

    def contract(self, app_id: str = "pet-store") -> AppContract:
        app = next((item for item in self.config["apps"] if item["id"] == app_id), None)
        if not app:
            raise ValueError(f"Unknown app: {app_id}")
        return AppContract.load(self.root / app["path"])

    def sync(self, app_id: str = "pet-store") -> int:
        source = self.config["observationSource"]
        since = self.store.latest_source_id(app_id)
        if source["kind"] != "fixture":
            raise ValueError(f"Unsupported observation source in this prototype: {source['kind']}")
        fixture_path = (self.root / source["path"]).resolve()
        if self.root not in fixture_path.parents:
            raise ValueError("Observation fixture must remain inside the App Evolver repository")
        payload = json.loads(fixture_path.read_text())
        new_observations = [item for item in payload["observations"] if int(item["id"]) > since]
        return self.store.add_signals(app_id, new_observations)

    def triage(self, app_id: str = "pet-store") -> list[int]:
        agent = self.agents.get("signal-analyst", require_enabled=True)
        started = time.perf_counter()
        signals = self.store.signals(app_id)
        run_id = uuid.uuid4().hex[:10]
        try:
            result = triage(
                self.store,
                self.contract(app_id),
                int(self.constitution["limits"]["maxEvidenceSamples"]),
            )
            self._activity(
                agent, app_id, run_id, "completed", f"{len(signals)} observation signals",
                f"Produced {len(result)} ranked opportunity themes", started,
            )
            return result
        except Exception as error:
            self._activity(
                agent, app_id, run_id, "failed", f"{len(signals)} observation signals",
                str(error), started,
            )
            raise

    def select(self, observation_id: int) -> None:
        self.store.set_observation_status(observation_id, "selected")

    def prepare_pull_request(self, observation_id: int) -> dict[str, Any]:
        observation = self.store.observation(observation_id)
        selection_policy = self.constitution["humanInTheLoop"]["observationSelection"]
        if selection_policy == "required" and observation["status"] != "selected":
            raise ValueError("This constitution requires a human to select the observation first")

        run_id = uuid.uuid4().hex[:10]
        product_agent = self.agents.get("product-manager", require_enabled=True)
        engineer = self.agents.get("software-engineer", require_enabled=True)
        reviewer = self.agents.get("quality-reviewer", require_enabled=True)
        contract = self.contract(observation["app_id"])
        capability = contract.capability(observation["theme"])

        product_started = time.perf_counter()
        hypothesis = (
            f"If we {capability['description'].lower()} then customers expressing this need "
            f"will use it, improving {capability['successMetric']}."
        )
        self._activity(
            product_agent, observation["app_id"], run_id, "completed",
            f"{observation['evidence']['signalCount']} signals about {observation['theme']}",
            f"Hypothesis: {hypothesis}", product_started,
        )

        engineer_started = time.perf_counter()
        try:
            pull_request = self.sandbox.prepare_pull_request(contract, observation)
        except Exception as error:
            self._activity(
                engineer, observation["app_id"], run_id, "failed",
                f"Selected observation {observation_id}", str(error), engineer_started,
            )
            raise
        pull_request["created_at"] = datetime.now(timezone.utc).isoformat()
        self.store.add_pull_request(pull_request)
        self.store.set_observation_status(observation_id, "pr_ready")
        self._activity(
            engineer, observation["app_id"], run_id, "completed",
            f"Hypothesis and grounded capability {observation['theme']}",
            f"Committed {pull_request['proposed_commit'][:8]} on {pull_request['branch']}",
            engineer_started,
        )
        self._activity(
            reviewer, observation["app_id"], run_id, "completed",
            f"Diff on {pull_request['branch']}",
            "All repository checks passed; branch is ready to open as a PR",
            engineer_started,
        )
        return pull_request

    def pull_request_remote_ready(self, app_id: str = "pet-store") -> bool:
        contract = self.contract(app_id)
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=contract.root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        return remote.returncode == 0 and bool(remote.stdout.strip()) and shutil.which("gh") is not None

    def open_pull_request(self, pull_request_id: str) -> str:
        pull_request = self.store.pull_request(pull_request_id)
        if pull_request["status"] != "checks_passed":
            raise ValueError(f"Branch cannot open a PR from status: {pull_request['status']}")
        contract = self.contract(pull_request["app_id"])
        if not self.pull_request_remote_ready(pull_request["app_id"]):
            raise ValueError("Configure the app repository's origin remote and GitHub CLI before opening a PR")
        observation = self.store.observation(pull_request["observation_id"])
        capability = contract.capability(observation["theme"])
        body = (
            "## Evidence\n"
            + "\n".join(f"- {sample}" for sample in observation["evidence"].get("samples", []))
            + f"\n\n## Hypothesis\n{pull_request['hypothesis']}"
            + f"\n\n## Success metric\n{pull_request['success_metric']}"
            + "\n\n## Validation\nAll repository validation commands passed in the App Evolver worktree."
        )
        pushed = self._run(["git", "push", "-u", "origin", pull_request["branch"]], contract.root)
        if pushed.returncode != 0:
            raise ValueError(f"Could not push PR branch: {pushed.stdout.strip()}")
        command = [
            "gh", "pr", "create", "--head", pull_request["branch"],
            "--base", self.config["pullRequests"]["baseBranch"],
            "--title", f"Evolve: {capability['description']}", "--body", body,
        ]
        if self.config["pullRequests"].get("draft", True):
            command.append("--draft")
        opened = self._run(command, contract.root)
        if opened.returncode != 0:
            raise ValueError(f"Could not open PR: {opened.stdout.strip()}")
        url = opened.stdout.strip().splitlines()[-1]
        viewed = self._run(["gh", "pr", "view", url, "--json", "number,url"], contract.root)
        metadata = json.loads(viewed.stdout) if viewed.returncode == 0 else {"number": 0, "url": url}
        self.store.set_pull_request_opened(pull_request_id, int(metadata["number"]), metadata["url"])
        self.store.set_observation_status(pull_request["observation_id"], "pr_open")
        return metadata["url"]

    def cycle(self, app_id: str = "pet-store") -> str:
        self.sync(app_id)
        self.triage(app_id)
        candidates = [item for item in self.store.observations(app_id) if item["status"] == "candidate"]
        if not candidates:
            return "No actionable candidate observations."
        if self.constitution["humanInTheLoop"]["observationSelection"] == "required":
            return "Candidate observations are ready for human selection."
        observation = candidates[0]
        self.select(observation["id"])
        pull_request = self.prepare_pull_request(observation["id"])
        return f"Branch {pull_request['branch']} passed checks and is ready to open as a PR."

    def _activity(
        self,
        agent: dict[str, Any],
        app_id: str,
        run_id: str,
        status: str,
        input_summary: str,
        output_summary: str,
        started: float,
    ) -> None:
        self.store.add_activity(
            {
                "run_id": run_id,
                "app_id": app_id,
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "stage": agent["stage"],
                "status": status,
                "input_summary": input_summary[:1_000],
                "output_summary": output_summary[:2_000],
                "duration_ms": max(1, int((time.perf_counter() - started) * 1_000)),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command, cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
