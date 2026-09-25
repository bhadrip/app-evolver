from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
            raise ValueError("Observation fixture must remain inside the Trellis repository")
        payload = json.loads(fixture_path.read_text())
        new_observations = [item for item in payload["observations"] if int(item["id"]) > since]
        return self.store.add_signals(app_id, new_observations)

    def triage(self, app_id: str = "pet-store") -> list[int]:
        return triage(
            self.store,
            self.contract(app_id),
            int(self.constitution["limits"]["maxEvidenceSamples"]),
        )

    def select(self, observation_id: int) -> None:
        self.store.set_observation_status(observation_id, "selected")

    def propose(self, observation_id: int) -> dict[str, Any]:
        observation = self.store.observation(observation_id)
        selection_policy = self.constitution["humanInTheLoop"]["observationSelection"]
        if selection_policy == "required" and observation["status"] != "selected":
            raise ValueError("This constitution requires a human to select the observation first")
        proposal = self.sandbox.propose(self.contract(observation["app_id"]), observation)
        proposal["created_at"] = datetime.now(timezone.utc).isoformat()
        self.store.add_proposal(proposal)
        self.store.set_observation_status(observation_id, "proposed")
        return proposal

    def approve(self, proposal_id: str) -> None:
        proposal = self.store.proposal(proposal_id)
        if proposal["status"] != "validated":
            raise ValueError(f"Proposal must be validated before approval; status is {proposal['status']}")
        self.store.set_proposal_status(proposal_id, "approved")

    def reject(self, proposal_id: str) -> None:
        proposal = self.store.proposal(proposal_id)
        self.store.set_proposal_status(proposal_id, "rejected")
        self.store.set_observation_status(proposal["observation_id"], "candidate")

    def apply(self, proposal_id: str) -> str:
        proposal = self.store.proposal(proposal_id)
        approval_policy = self.constitution["humanInTheLoop"]["changeApproval"]
        if approval_policy == "required" and proposal["status"] != "approved":
            raise ValueError("This constitution requires human approval before applying a change")
        if proposal["status"] not in {"validated", "approved"}:
            raise ValueError(f"Proposal cannot be applied from status: {proposal['status']}")
        contract = self.contract(proposal["app_id"])
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=contract.root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if status.stdout.strip():
            raise ValueError("App working tree changed since proposal; refusing to apply")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=contract.root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        ).stdout.strip()
        if head != proposal["base_commit"]:
            raise ValueError("App HEAD changed since proposal; rebase or generate a new proposal")
        merge = subprocess.run(
            ["git", "merge", "--ff-only", proposal["branch"]], cwd=contract.root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if merge.returncode != 0:
            raise ValueError(f"Could not apply proposal: {merge.stdout.strip()}")
        self.store.set_proposal_status(proposal_id, "applied")
        self.store.set_observation_status(proposal["observation_id"], "applied")
        return proposal["base_commit"]

    def cycle(self, app_id: str = "pet-store") -> str:
        self.sync(app_id)
        self.triage(app_id)
        candidates = [item for item in self.store.observations(app_id) if item["status"] == "candidate"]
        if not candidates:
            return "No actionable candidate observations."
        selection_policy = self.constitution["humanInTheLoop"]["observationSelection"]
        if selection_policy == "required":
            return "Candidate observations are ready for human selection."
        observation = candidates[0]
        self.select(observation["id"])
        proposal = self.propose(observation["id"])
        approval_policy = self.constitution["humanInTheLoop"]["changeApproval"]
        allowed_risks = self.constitution["automaticApprovalRiskLevels"]
        if approval_policy == "required" or proposal["risk"] not in allowed_risks:
            return f"Proposal {proposal['id']} is validated and waiting for human approval."
        self.approve(proposal["id"])
        rollback_commit = self.apply(proposal["id"])
        return f"Applied proposal {proposal['id']}; rollback commit is {rollback_commit}."
