"""Public data contracts returned by :class:`AppEvolver`."""

from typing import Any, Literal, TypedDict


ObservationStatus = Literal["candidate", "selected", "pr_ready", "pr_open"]
PullRequestStatus = Literal["checks_passed", "opened"]
RunStatus = Literal["completed", "failed"]


class AppInfo(TypedDict):
    id: str
    name: str
    path: str


class AppVersionEvidence(TypedDict):
    version: str
    revision: str
    signalCount: int


class ObservationEvidence(TypedDict):
    signalCount: int
    sourceEventIds: list[int]
    samples: list[str]
    appVersions: list[AppVersionEvidence]


class Observation(TypedDict):
    id: int
    app_id: str
    theme: str
    summary: str
    evidence: ObservationEvidence
    score: float
    status: ObservationStatus
    updated_at: str


class PullRequestProposal(TypedDict):
    id: str
    app_id: str
    observation_id: int
    hypothesis: str
    success_metric: str
    risk: str
    branch: str
    sandbox_path: str
    base_commit: str
    proposed_commit: str
    diff: str
    validation: str
    evidence: ObservationEvidence
    customer_app_versions: list[AppVersionEvidence]
    status: PullRequestStatus
    pr_number: int | None
    pr_url: str | None
    created_at: str


class AgentDefinition(TypedDict):
    id: str
    kind: str
    name: str
    stage: str
    enabled: bool
    model: str
    instructions: str
    access: str


class AgentGraphNode(TypedDict):
    agentId: str
    dependsOn: list[str]


class AgentGraphSnapshot(TypedDict):
    nodes: list[AgentGraphNode]
    waves: list[list[str]]


class ActivityEntry(TypedDict):
    id: int
    run_id: str
    app_id: str
    agent_id: str
    agent_name: str
    stage: str
    status: RunStatus
    input_summary: str
    output_summary: str
    duration_ms: int
    created_at: str


class SyncResult(TypedDict):
    app_id: str
    inserted: int
    latest_source_id: int


class AnalysisResult(TypedDict):
    app_id: str
    observation_ids: list[int]


class SyncAndAnalyzeResult(TypedDict):
    app_id: str
    inserted: int
    observation_ids: list[int]


class GovernanceSnapshot(TypedDict):
    app: AppInfo
    contract: dict[str, Any]
    constitution: dict[str, Any]
    platform_policy: dict[str, Any]
