"""Composable agent protocol and built-in deterministic implementations."""

from __future__ import annotations

import copy
import hashlib
import json
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .errors import AgentExecutionError, ConfigurationError, NotFoundError, ValidationFailed
from .models import AgentDefinition, AgentGraphNode, AgentGraphSnapshot
from .triage import group_signals


@dataclass(frozen=True)
class AgentRequest:
    """Transport-neutral input envelope suitable for local, MCP, or A2A adapters."""

    run_id: str
    app_id: str
    task: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class AgentResponse:
    """Normalized agent output consumed by App Evolver orchestration."""

    agent_id: str
    summary: str
    payload: Mapping[str, Any]


@runtime_checkable
class Agent(Protocol):
    """Contract every local or remote App Evolver agent must implement."""

    @property
    def definition(self) -> AgentDefinition: ...

    def run(self, request: AgentRequest) -> AgentResponse: ...


AgentFactory = Callable[[AgentDefinition], Agent]


class BaseAgent(ABC):
    """Convenience base type for built-in and user-defined in-process agents."""

    task: str

    def __init__(self, definition: AgentDefinition):
        self._definition = copy.deepcopy(definition)

    @property
    def definition(self) -> AgentDefinition:
        return copy.deepcopy(self._definition)

    def run(self, request: AgentRequest) -> AgentResponse:
        if request.task != self.task:
            raise ConfigurationError(
                f"Agent {self._definition['id']} handles {self.task}, not {request.task}"
            )
        payload, summary = self.execute(copy.deepcopy(dict(request.payload)))
        return AgentResponse(
            agent_id=self._definition["id"], summary=summary, payload=copy.deepcopy(payload)
        )

    @abstractmethod
    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Execute one role-specific task using a serializable payload."""


class SignalAnalystAgent(BaseAgent):
    task = "analyze_signals"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        themes = group_signals(
            payload["signals"], payload["capabilities"], int(payload["max_samples"])
        )
        return {"themes": themes}, f"Produced {len(themes)} ranked opportunity themes"


class ProductManagerAgent(BaseAgent):
    task = "frame_hypothesis"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        capability = payload["capability"]
        hypothesis = (
            f"If we {capability['description'].lower()} then customers expressing this need "
            f"will use it, improving {capability['successMetric']}."
        )
        return {"hypothesis": hypothesis}, f"Hypothesis: {hypothesis}"


class UXResearcherAgent(BaseAgent):
    task = "research_user_experience"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        observation = payload["observation"]
        memories = payload.get("memories", [])
        findings = {
            "userNeed": observation["summary"],
            "evidenceSamples": copy.deepcopy(observation["evidence"].get("samples", [])),
            "priorLessons": [item["content"] for item in memories if item["kind"] == "lesson"],
            "risk": payload["capability"].get("risk", "unknown"),
        }
        return findings, f"Grounded UX direction in {observation['evidence']['signalCount']} signals"


class UIDesignerAgent(BaseAgent):
    task = "design_interface"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        dependencies = payload.get("dependency_outputs", {})
        prior_lessons = [
            item["content"] for item in payload.get("memories", [])
            if item["kind"] in {"lesson", "failure"}
        ]
        user_need = dependencies.get("ux-researcher", {}).get(
            "userNeed", payload["capability"]["description"]
        )
        design = {
            "direction": f"Expose {payload['capability']['description'].lower()} with clear state and feedback.",
            "userNeed": user_need,
            "acceptanceCriteria": [
                "The capability is discoverable without blocking the primary task.",
                "State changes have visible confirmation and reversible affordances.",
                "Keyboard, focus, labels, and contrast remain testable.",
            ],
            "appliedLessons": prior_lessons,
        }
        return design, "Produced UI direction and testable acceptance criteria"


class SoftwareEngineerAgent(BaseAgent):
    task = "plan_grounded_change"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        capability = payload["capability"]
        plan = copy.deepcopy(capability["change"])
        return {
            "change": plan,
            "design": copy.deepcopy(
                payload.get("dependency_outputs", {}).get("ui-designer", {})
            ),
        }, f"Planned {plan['kind']} change in {plan['path']}"


class QualityReviewerAgent(BaseAgent):
    task = "review_validated_change"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if payload["status"] != "checks_passed":
            raise ValidationFailed(f"Reviewer rejected workspace status: {payload['status']}")
        return {"approved": True}, "All repository checks passed; branch is ready for a PR"


class EvidenceReviewerAgent(BaseAgent):
    task = "review_evidence"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        evidence = payload["evidence"]
        if not evidence.get("samples") or not evidence.get("appVersions"):
            raise ValidationFailed("PR evidence must include samples and customer app versions")
        return {"approved": True}, "Evidence includes customer signals and app-version provenance"


class AccessibilityReviewerAgent(BaseAgent):
    task = "review_accessibility"

    def execute(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        design = payload.get("design", {})
        criteria = design.get("acceptanceCriteria", [])
        if not criteria:
            raise ValidationFailed("Accessibility review requires UI acceptance criteria")
        return {
            "approved": True,
            "criteriaReviewed": copy.deepcopy(criteria),
        }, "Accessibility acceptance criteria are present for implementation review"


BUILT_IN_AGENT_TYPES: dict[str, AgentFactory] = {
    "signal_analyst": SignalAnalystAgent,
    "product_manager": ProductManagerAgent,
    "ux_researcher": UXResearcherAgent,
    "ui_designer": UIDesignerAgent,
    "software_engineer": SoftwareEngineerAgent,
    "quality_reviewer": QualityReviewerAgent,
    "evidence_reviewer": EvidenceReviewerAgent,
    "accessibility_reviewer": AccessibilityReviewerAgent,
}


class AgentTeam:
    """Composable process-local agent registry for v0."""

    def __init__(
        self,
        document: dict[str, Any],
        agent_types: Mapping[str, AgentFactory] | None = None,
    ):
        self._document = copy.deepcopy(document)
        self._agent_types = dict(BUILT_IN_AGENT_TYPES)
        if agent_types:
            self._agent_types.update(agent_types)
        self._instances: dict[str, Agent] = {}
        self._rebuild()

    @classmethod
    def from_path(
        cls,
        path: Path,
        agent_types: Mapping[str, AgentFactory] | None = None,
    ) -> "AgentTeam":
        return cls(json.loads(path.read_text()), agent_types=agent_types)

    def document(self) -> dict[str, Any]:
        return copy.deepcopy(self._document)

    def all(self) -> list[AgentDefinition]:
        return [self._materialize(definition) for definition in self._document["agents"]]

    def enabled(self) -> list[AgentDefinition]:
        return [agent for agent in self.all() if agent["enabled"]]

    def graph(self) -> AgentGraphSnapshot:
        nodes = copy.deepcopy(self._document.get("workflow", {}).get("nodes", []))
        return {"nodes": nodes, "waves": self.execution_waves()}

    def configure_graph(self, nodes: list[AgentGraphNode]) -> AgentGraphSnapshot:
        previous = copy.deepcopy(self._document.get("workflow"))
        self._document["workflow"] = {"nodes": copy.deepcopy(nodes)}
        try:
            self.execution_waves()
        except Exception:
            if previous is None:
                self._document.pop("workflow", None)
            else:
                self._document["workflow"] = previous
            raise
        return self.graph()

    def execution_waves(self, agent_ids: set[str] | None = None) -> list[list[str]]:
        """Topologically group agents; members of one wave may run in parallel."""
        known = {definition["id"] for definition in self._document["agents"]}
        nodes = self._document.get("workflow", {}).get("nodes", [])
        if not nodes:
            nodes = [{"agentId": definition["id"], "dependsOn": []} for definition in self.all()]
        selected = known if agent_ids is None else set(agent_ids)
        unknown = selected - known
        if unknown:
            raise ConfigurationError(f"Workflow references unknown agents: {', '.join(sorted(unknown))}")
        dependencies: dict[str, set[str]] = {}
        for node in nodes:
            agent_id = node["agentId"]
            if agent_id not in known:
                raise ConfigurationError(f"Workflow node references unknown agent: {agent_id}")
            unknown_dependencies = set(node.get("dependsOn", [])) - known
            if unknown_dependencies:
                raise ConfigurationError(
                    f"Workflow node {agent_id} has unknown dependencies: "
                    + ", ".join(sorted(unknown_dependencies))
                )
            if agent_id in selected:
                dependencies[agent_id] = set(node.get("dependsOn", [])) & selected
        missing_nodes = selected - dependencies.keys()
        if missing_nodes:
            raise ConfigurationError(
                f"Workflow has no nodes for agents: {', '.join(sorted(missing_nodes))}"
            )
        waves: list[list[str]] = []
        completed: set[str] = set()
        while len(completed) < len(selected):
            wave = sorted(
                agent_id for agent_id, required in dependencies.items()
                if agent_id not in completed and required <= completed
            )
            if not wave:
                raise ConfigurationError("Agent workflow contains a dependency cycle")
            waves.append(wave)
            completed.update(wave)
        return waves

    def run_composite(
        self, requests: Mapping[str, AgentRequest]
    ) -> dict[str, AgentResponse]:
        """Execute independent agents in parallel and dependency waves in series."""
        responses: dict[str, AgentResponse] = {}
        configured_dependencies = {
            node["agentId"]: list(node.get("dependsOn", []))
            for node in self._document.get("workflow", {}).get("nodes", [])
        }
        for wave in self.execution_waves(set(requests)):
            with ThreadPoolExecutor(max_workers=max(1, len(wave))) as executor:
                futures = {}
                for agent_id in wave:
                    request = requests[agent_id]
                    payload = copy.deepcopy(dict(request.payload))
                    payload["dependency_outputs"] = {
                        dependency: copy.deepcopy(dict(responses[dependency].payload))
                        for dependency in configured_dependencies.get(agent_id, [])
                        if dependency in responses
                    }
                    enriched = AgentRequest(
                        run_id=request.run_id,
                        app_id=request.app_id,
                        task=request.task,
                        payload=payload,
                    )
                    futures[agent_id] = executor.submit(
                        self.get_agent(agent_id, require_enabled=True).run, enriched
                    )
                for agent_id, future in futures.items():
                    try:
                        responses[agent_id] = future.result()
                    except Exception as error:
                        raise AgentExecutionError(agent_id, error) from error
        return responses

    def get_definition(self, agent_id: str, require_enabled: bool = False) -> AgentDefinition:
        definition = next(
            (item for item in self._document["agents"] if item["id"] == agent_id), None
        )
        if not definition:
            raise NotFoundError(f"Unknown agent: {agent_id}")
        if require_enabled and not definition["enabled"]:
            raise ConfigurationError(f"{definition['name']} is disabled")
        return self._materialize(definition)

    def get_agent(self, agent_id: str, require_enabled: bool = False) -> Agent:
        self.get_definition(agent_id, require_enabled=require_enabled)
        return self._instances[agent_id]

    # Compatibility alias for the initial configuration-only API.
    def get(self, agent_id: str, require_enabled: bool = False) -> AgentDefinition:
        return self.get_definition(agent_id, require_enabled=require_enabled)

    def update(
        self,
        agent_id: str,
        *,
        name: str,
        enabled: bool,
        model: str,
        instructions: str,
        version: str | None = None,
    ) -> None:
        agent = next((item for item in self._document["agents"] if item["id"] == agent_id), None)
        if not agent:
            raise NotFoundError(f"Unknown agent: {agent_id}")
        clean_name = name.strip()[:80]
        clean_model = model.strip()[:80]
        clean_instructions = instructions.strip()[:2_000]
        clean_version = (version or agent["version"]).strip()[:40]
        if not clean_name or not clean_model or not clean_instructions or not clean_version:
            raise ConfigurationError("Name, version, model, and instructions are required")
        behavior_changed = (
            clean_model != agent["model"] or clean_instructions != agent["instructions"]
        )
        if behavior_changed and clean_version == agent["version"]:
            raise ConfigurationError(
                "Changing an agent's model or instructions requires a new version"
            )
        agent.update(
            name=clean_name,
            enabled=enabled,
            model=clean_model,
            instructions=clean_instructions,
            version=clean_version,
        )
        self._instances[agent_id] = self._instantiate(agent)

    def _rebuild(self) -> None:
        self._instances = {
            definition["id"]: self._instantiate(definition)
            for definition in self._document["agents"]
        }
        self.execution_waves()

    def _instantiate(self, definition: AgentDefinition) -> Agent:
        kind = definition.get("kind")
        agent_type = self._agent_types.get(str(kind))
        if not agent_type:
            raise ConfigurationError(
                f"Agent {definition['id']} references unknown agent kind: {kind}"
            )
        instance = agent_type(self._materialize(definition))
        if not isinstance(instance, Agent):
            raise ConfigurationError(f"Agent kind {kind} does not implement the Agent protocol")
        return instance

    @staticmethod
    def _materialize(definition: AgentDefinition) -> AgentDefinition:
        value = copy.deepcopy(definition)
        source = copy.deepcopy(value)
        source.pop("revision", None)
        value["revision"] = hashlib.sha256(
            json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        return value
