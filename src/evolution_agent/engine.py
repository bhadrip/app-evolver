from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import AgentRequest, AgentTeam
from .contracts import AppContract
from .errors import (
    AgentExecutionError,
    ConfigurationError,
    DeliveryError,
    InvalidTransition,
    PolicyViolation,
)
from .models import (
    ActivityEntry,
    AgentDefinition,
    AgentGraphSnapshot,
    AgentGraphNode,
    AnalysisResult,
    AppInfo,
    GovernanceSnapshot,
    Observation,
    ObservationStatus,
    PullRequestProposal,
    SyncAndAnalyzeResult,
    SyncResult,
)
from .sandbox import ChangeWorkspace, LocalGitWorkspace
from .registry import AppRegistry
from .store import InMemoryStateStore, StateStore


RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"


class AppEvolver:
    """Embeddable orchestration library with dependency-injected runtime state."""

    def __init__(
        self,
        *,
        state_store: StateStore | None = None,
        registry: AppRegistry | None = None,
        agent_team: AgentTeam | None = None,
        workspace: ChangeWorkspace | None = None,
        work_root: Path | None = None,
        resource_root: Path = RESOURCE_ROOT,
    ):
        self.resource_root = resource_root.resolve()
        self.config = json.loads((self.resource_root / "service-config.json").read_text())
        configured_work_root = work_root or Path(
            os.environ.get("APP_EVOLVER_WORK_DIR", self.config["workDirectory"])
        )
        self.work_root = configured_work_root
        if not self.work_root.is_absolute():
            self.work_root = (Path.cwd() / self.work_root).resolve()
        self._platform_policy = json.loads(
            (self.resource_root / self.config["platformPolicy"]).read_text()
        )
        self._registry = registry or AppRegistry()
        self._state_store = state_store or InMemoryStateStore()
        if workspace is None:
            self.work_root.mkdir(parents=True, exist_ok=True)
            workspace = LocalGitWorkspace(self.work_root / self.config["sandboxDirectory"])
        self._workspace = workspace
        self._agent_team = agent_team or AgentTeam.from_path(
            self.resource_root / self.config["defaultAgentTeam"]
        )
        if os.environ.get("APP_EVOLVER_APP"):
            self._registry.register(Path(os.environ["APP_EVOLVER_APP"]))

    def register_app(self, app_root: Path) -> AppInfo:
        """Register a companion checkout for this App Evolver instance."""
        return self._registry.register(app_root)

    def list_apps(self) -> list[AppInfo]:
        return self._registry.all()

    def get_app(self, app_id: str) -> AppInfo:
        return self._registry.get(app_id)

    def default_app_id(self) -> str | None:
        return self._registry.default_app_id()

    def _contract(self, app_id: str) -> AppContract:
        app = self._registry.get(app_id)
        return AppContract.load(Path(app["path"]))

    def _constitution(self, app_id: str) -> dict[str, Any]:
        contract = self._contract(app_id)
        document = json.loads(contract.resolve_owned_path(contract.document["constitution"]).read_text())
        for key, ceiling in self._platform_policy["ceilings"].items():
            if int(document["limits"][key]) > int(ceiling):
                raise PolicyViolation(f"App constitution exceeds platform ceiling for {key}")
        return document

    def get_governance(self, app_id: str) -> GovernanceSnapshot:
        """Return all effective constraints that govern an app evolution run."""
        contract = self._contract(app_id)
        return {
            "app": self.get_app(app_id),
            "contract": copy.deepcopy(contract.document),
            "constitution": self._constitution(app_id),
            "platform_policy": copy.deepcopy(self._platform_policy),
        }

    def list_agents(self) -> list[AgentDefinition]:
        return self._agent_team.all()

    def get_agent_graph(self) -> AgentGraphSnapshot:
        """Return dependency nodes and parallel execution waves."""
        return self._agent_team.graph()

    def configure_agent_graph(self, nodes: list[AgentGraphNode]) -> AgentGraphSnapshot:
        """Replace the process-local dependency graph after validating it."""
        return self._agent_team.configure_graph(nodes)

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str,
        enabled: bool,
        model: str,
        instructions: str,
    ) -> AgentDefinition:
        self._agent_team.update(
            agent_id, name=name, enabled=enabled, model=model, instructions=instructions
        )
        return self._agent_team.get(agent_id)

    def sync_observations(self, app_id: str) -> SyncResult:
        """Read new signals from the app-owned observation source."""
        contract = self._contract(app_id)
        source = contract.document["observationSource"]
        since = self._state_store.latest_source_id(app_id)
        if source["kind"] != "fixture":
            raise PolicyViolation(f"Unsupported observation source in this prototype: {source['kind']}")
        fixture_path = contract.resolve_owned_path(source["path"])
        payload = json.loads(fixture_path.read_text())
        new_observations = [item for item in payload["observations"] if int(item["id"]) > since]
        for signal in new_observations:
            version = str(signal.get("appVersion", "")).strip()
            revision = str(signal.get("appRevision", "")).strip()
            if not version or not revision:
                raise ConfigurationError(
                    f"Observation {signal.get('id')} must include appVersion and appRevision"
                )
            exists = subprocess.run(
                ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
                cwd=contract.root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if exists.returncode != 0:
                raise ConfigurationError(
                    f"Observation {signal.get('id')} references appRevision not present in the app repository: {revision}"
                )
        inserted = self._state_store.add_signals(app_id, new_observations)
        return {
            "app_id": app_id,
            "inserted": inserted,
            "latest_source_id": self._state_store.latest_source_id(app_id),
        }

    def analyze_observations(self, app_id: str) -> AnalysisResult:
        """Convert collected signals into ranked, grounded opportunities."""
        agent = self._agent_team.get_agent("signal-analyst", require_enabled=True)
        started = time.perf_counter()
        signals = self._state_store.signals(app_id)
        run_id = uuid.uuid4().hex[:10]
        try:
            contract = self._contract(app_id)
            response = self._agent_team.run_composite({
                "signal-analyst": AgentRequest(
                    run_id=run_id,
                    app_id=app_id,
                    task="analyze_signals",
                    payload={
                        "signals": signals,
                        "capabilities": contract.capabilities,
                        "max_samples": int(
                            self._constitution(app_id)["limits"]["maxEvidenceSamples"]
                        ),
                    },
                )
            })["signal-analyst"]
            result = [
                self._state_store.upsert_observation(
                    app_id,
                    theme["theme"],
                    theme["summary"],
                    theme["evidence"],
                    float(theme["score"]),
                )
                for theme in response.payload["themes"]
            ]
            self._activity(
                agent.definition, app_id, run_id, "completed",
                f"{len(signals)} observation signals", response.summary, started,
            )
            return {"app_id": app_id, "observation_ids": result}
        except Exception as error:
            self._activity(
                agent.definition, app_id, run_id, "failed", f"{len(signals)} observation signals",
                str(error), started,
            )
            raise

    def sync_and_analyze(self, app_id: str) -> SyncAndAnalyzeResult:
        synced = self.sync_observations(app_id)
        analyzed = self.analyze_observations(app_id)
        return {
            "app_id": app_id,
            "inserted": synced["inserted"],
            "observation_ids": analyzed["observation_ids"],
        }

    def list_observations(
        self, app_id: str, *, status: ObservationStatus | None = None
    ) -> list[Observation]:
        observations = self._state_store.observations(app_id)
        if status is not None:
            observations = [item for item in observations if item["status"] == status]
        return observations

    def get_observation(self, observation_id: int) -> Observation:
        return self._state_store.observation(observation_id)

    def select_observation(self, observation_id: int) -> Observation:
        observation = self._state_store.observation(observation_id)
        if observation["status"] == "selected":
            return observation
        if observation["status"] != "candidate":
            raise InvalidTransition(
                f"Observation {observation_id} cannot be selected from status {observation['status']}"
            )
        self._state_store.set_observation_status(observation_id, "selected")
        return self._state_store.observation(observation_id)

    def prepare_pull_request(self, observation_id: int) -> PullRequestProposal:
        """Create and validate a bounded branch in the configured workspace."""
        observation = self._state_store.observation(observation_id)
        constitution = self._constitution(observation["app_id"])
        selection_policy = constitution["humanInTheLoop"]["observationSelection"]
        if selection_policy == "required" and observation["status"] != "selected":
            raise PolicyViolation("This constitution requires a human to select the observation first")
        if observation["status"] not in {"candidate", "selected"}:
            raise InvalidTransition(
                f"Observation {observation_id} cannot prepare a PR from status {observation['status']}"
            )

        run_id = uuid.uuid4().hex[:10]
        product_agent = self._agent_team.get_agent("product-manager", require_enabled=True)
        engineer = self._agent_team.get_agent("software-engineer", require_enabled=True)
        reviewer = self._agent_team.get_agent("quality-reviewer", require_enabled=True)
        evidence_reviewer = self._agent_team.get_agent(
            "evidence-reviewer", require_enabled=True
        )
        contract = self._contract(observation["app_id"])
        capability = contract.capability(observation["theme"])

        product_started = time.perf_counter()
        try:
            composite_responses = self._agent_team.run_composite({
                "product-manager": AgentRequest(
                    run_id=run_id,
                    app_id=observation["app_id"],
                    task="frame_hypothesis",
                    payload={"observation": observation, "capability": capability},
                ),
                "software-engineer": AgentRequest(
                    run_id=run_id,
                    app_id=observation["app_id"],
                    task="plan_grounded_change",
                    payload={"observation": observation, "capability": capability},
                ),
            })
        except AgentExecutionError as error:
            failed_agent = self._agent_team.get_agent(error.agent_id).definition
            self._activity(
                failed_agent, observation["app_id"], run_id, "failed",
                f"Selected observation {observation_id}", str(error), product_started,
            )
            raise
        product_response = composite_responses["product-manager"]
        engineer_response = composite_responses["software-engineer"]
        hypothesis = str(product_response.payload["hypothesis"])
        self._activity(
            product_agent.definition, observation["app_id"], run_id, "completed",
            f"{observation['evidence']['signalCount']} signals about {observation['theme']}",
            product_response.summary, product_started,
        )

        engineer_started = time.perf_counter()
        try:
            pull_request = self._workspace.prepare_pull_request(
                contract,
                observation,
                constitution,
                change_plan=dict(engineer_response.payload["change"]),
                hypothesis=hypothesis,
            )
        except Exception as error:
            self._activity(
                engineer.definition, observation["app_id"], run_id, "failed",
                f"Selected observation {observation_id}", str(error), engineer_started,
            )
            raise
        reviewer_started = time.perf_counter()
        try:
            review_responses = self._agent_team.run_composite({
                "quality-reviewer": AgentRequest(
                    run_id=run_id,
                    app_id=observation["app_id"],
                    task="review_validated_change",
                    payload={
                        "status": pull_request["status"],
                        "diff": pull_request["diff"],
                        "validation": pull_request["validation"],
                    },
                ),
                "evidence-reviewer": AgentRequest(
                    run_id=run_id,
                    app_id=observation["app_id"],
                    task="review_evidence",
                    payload={
                        "evidence": pull_request["evidence"],
                        "base_commit": pull_request["base_commit"],
                        "proposed_commit": pull_request["proposed_commit"],
                        "validation": pull_request["validation"],
                    },
                ),
            })
        except Exception as error:
            failed_id = (
                error.agent_id if isinstance(error, AgentExecutionError)
                else "quality-reviewer"
            )
            failed_agent = self._agent_team.get_agent(failed_id).definition
            self._activity(
                failed_agent, observation["app_id"], run_id, "failed",
                f"Diff on {pull_request['branch']}", str(error), reviewer_started,
            )
            raise
        reviewer_response = review_responses["quality-reviewer"]
        evidence_response = review_responses["evidence-reviewer"]
        pull_request["created_at"] = datetime.now(timezone.utc).isoformat()
        self._state_store.add_pull_request(pull_request)
        self._state_store.set_observation_status(observation_id, "pr_ready")
        self._activity(
            engineer.definition, observation["app_id"], run_id, "completed",
            f"Hypothesis and grounded capability {observation['theme']}",
            f"Committed {pull_request['proposed_commit'][:8]} on {pull_request['branch']}",
            engineer_started,
        )
        self._activity(
            reviewer.definition, observation["app_id"], run_id, "completed",
            f"Diff on {pull_request['branch']}",
            reviewer_response.summary,
            reviewer_started,
        )
        self._activity(
            evidence_reviewer.definition, observation["app_id"], run_id, "completed",
            f"Evidence for {pull_request['branch']}",
            evidence_response.summary,
            reviewer_started,
        )
        return pull_request

    def list_pull_requests(self, app_id: str) -> list[PullRequestProposal]:
        return self._state_store.pull_requests(app_id)

    def get_pull_request(self, pull_request_id: str) -> PullRequestProposal:
        return self._state_store.pull_request(pull_request_id)

    def can_open_pull_request(self, app_id: str) -> bool:
        contract = self._contract(app_id)
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=contract.root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        return remote.returncode == 0 and bool(remote.stdout.strip()) and shutil.which("gh") is not None

    def open_pull_request(self, pull_request_id: str) -> PullRequestProposal:
        """Push a checked branch and create its configured GitHub pull request."""
        pull_request = self._state_store.pull_request(pull_request_id)
        if pull_request["status"] != "checks_passed":
            raise InvalidTransition(f"Branch cannot open a PR from status: {pull_request['status']}")
        contract = self._contract(pull_request["app_id"])
        if not self.can_open_pull_request(pull_request["app_id"]):
            raise DeliveryError(
                "Configure the app repository's origin remote and GitHub CLI before opening a PR"
            )
        observation = self._state_store.observation(pull_request["observation_id"])
        capability = contract.capability(observation["theme"])
        body = (
            "## Evidence\n"
            + "\n".join(f"- {sample}" for sample in observation["evidence"].get("samples", []))
            + "\n\n## Customer app versions\n"
            + "\n".join(
                f"- `{item['version']}` at `{item['revision']}` ({item['signalCount']} signal(s))"
                for item in pull_request["customer_app_versions"]
            )
            + f"\n\n## Hypothesis\n{pull_request['hypothesis']}"
            + f"\n\n## Success metric\n{pull_request['success_metric']}"
            + f"\n\n## Code provenance\nBase `{pull_request['base_commit']}` → proposed `{pull_request['proposed_commit']}`"
            + "\n\n## Validation evidence\n```text\n"
            + pull_request["validation"][:10_000]
            + "\n```"
        )
        pushed = self._run(["git", "push", "-u", "origin", pull_request["branch"]], contract.root)
        if pushed.returncode != 0:
            raise DeliveryError(f"Could not push PR branch: {pushed.stdout.strip()}")
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
            raise DeliveryError(f"Could not open PR: {opened.stdout.strip()}")
        url = opened.stdout.strip().splitlines()[-1]
        viewed = self._run(["gh", "pr", "view", url, "--json", "number,url"], contract.root)
        metadata = json.loads(viewed.stdout) if viewed.returncode == 0 else {"number": 0, "url": url}
        self._state_store.set_pull_request_opened(
            pull_request_id, int(metadata["number"]), metadata["url"]
        )
        self._state_store.set_observation_status(pull_request["observation_id"], "pr_open")
        return self._state_store.pull_request(pull_request_id)

    def list_activity(self, app_id: str, *, limit: int = 100) -> list[ActivityEntry]:
        return self._state_store.activities(limit=limit, app_id=app_id)

    def run_cycle(self, app_id: str) -> str:
        """Run one automatic cycle, stopping when human selection is required."""
        self.sync_and_analyze(app_id)
        candidates = self.list_observations(app_id, status="candidate")
        if not candidates:
            return "No actionable candidate observations."
        if self._constitution(app_id)["humanInTheLoop"]["observationSelection"] == "required":
            return "Candidate observations are ready for human selection."
        observation = candidates[0]
        self.select_observation(observation["id"])
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
        self._state_store.add_activity(
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

    # Compatibility shims for the initial prototype. New integrations should use
    # the explicit public methods above.
    def sync(self, app_id: str) -> int:
        return self.sync_observations(app_id)["inserted"]

    def triage(self, app_id: str) -> list[int]:
        return self.analyze_observations(app_id)["observation_ids"]

    def select(self, observation_id: int) -> None:
        self.select_observation(observation_id)

    def cycle(self, app_id: str) -> str:
        return self.run_cycle(app_id)

    def pull_request_remote_ready(self, app_id: str) -> bool:
        return self.can_open_pull_request(app_id)


# Backwards-compatible name for the optional CLI and development UI adapter.
Engine = AppEvolver
