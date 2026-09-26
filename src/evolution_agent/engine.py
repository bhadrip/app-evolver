from __future__ import annotations

import json
import os
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
from .registry import AppRegistry
from .store import StateStore
from .triage import triage


RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"


class Engine:
    def __init__(self, resource_root: Path = RESOURCE_ROOT):
        self.resource_root = resource_root.resolve()
        self.config = json.loads((self.resource_root / "service-config.json").read_text())
        configured_data_root = os.environ.get("APP_EVOLVER_DATA_DIR", self.config["dataDirectory"])
        self.data_root = Path(configured_data_root)
        if not self.data_root.is_absolute():
            self.data_root = (Path.cwd() / self.data_root).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.platform_policy = json.loads((self.resource_root / self.config["platformPolicy"]).read_text())
        self.registry = AppRegistry(self.data_root / self.config["appRegistry"])
        self.store = StateStore(self.data_root / self.config["stateDatabase"])
        self.sandbox = Sandbox(self.data_root / self.config["sandboxDirectory"])
        self.agents = AgentTeam(
            self.data_root / self.config["agentTeam"],
            self.resource_root / self.config["defaultAgentTeam"],
        )
        if os.environ.get("APP_EVOLVER_APP"):
            self.registry.register(Path(os.environ["APP_EVOLVER_APP"]))

    def register_app(self, app_root: Path) -> dict[str, Any]:
        return self.registry.register(app_root)

    def contract(self, app_id: str) -> AppContract:
        app = self.registry.get(app_id)
        return AppContract.load(Path(app["path"]))

    def constitution(self, app_id: str) -> dict[str, Any]:
        contract = self.contract(app_id)
        document = json.loads(contract.resolve_owned_path(contract.document["constitution"]).read_text())
        for key, ceiling in self.platform_policy["ceilings"].items():
            if int(document["limits"][key]) > int(ceiling):
                raise ValueError(f"App constitution exceeds platform ceiling for {key}")
        return document

    def sync(self, app_id: str) -> int:
        contract = self.contract(app_id)
        source = contract.document["observationSource"]
        since = self.store.latest_source_id(app_id)
        if source["kind"] != "fixture":
            raise ValueError(f"Unsupported observation source in this prototype: {source['kind']}")
        fixture_path = contract.resolve_owned_path(source["path"])
        payload = json.loads(fixture_path.read_text())
        new_observations = [item for item in payload["observations"] if int(item["id"]) > since]
        return self.store.add_signals(app_id, new_observations)

    def triage(self, app_id: str) -> list[int]:
        agent = self.agents.get("signal-analyst", require_enabled=True)
        started = time.perf_counter()
        signals = self.store.signals(app_id)
        run_id = uuid.uuid4().hex[:10]
        try:
            result = triage(
                self.store,
                self.contract(app_id),
                int(self.constitution(app_id)["limits"]["maxEvidenceSamples"]),
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
        constitution = self.constitution(observation["app_id"])
        selection_policy = constitution["humanInTheLoop"]["observationSelection"]
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
            pull_request = self.sandbox.prepare_pull_request(contract, observation, constitution)
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

    def pull_request_remote_ready(self, app_id: str) -> bool:
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
        pull_request_policy = contract.document["pullRequests"]
        command = [
            "gh", "pr", "create", "--head", pull_request["branch"],
            "--base", pull_request_policy["baseBranch"],
            "--title", f"Evolve: {capability['description']}", "--body", body,
        ]
        if pull_request_policy.get("draft", True):
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

    def cycle(self, app_id: str) -> str:
        self.sync(app_id)
        self.triage(app_id)
        candidates = [item for item in self.store.observations(app_id) if item["status"] == "candidate"]
        if not candidates:
            return "No actionable candidate observations."
        if self.constitution(app_id)["humanInTheLoop"]["observationSelection"] == "required":
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
