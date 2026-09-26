# App Evolver

App Evolver is a pure Python library for observation-driven application
evolution. Applications embed and configure it; App Evolver does not require a
server, database, LangGraph, or hosted control plane.

The library composes agents that group observations, frame a hypothesis, prepare
a bounded change, validate it in an isolated workspace, and open an ordinary
pull request. It does not replace Git, CI, branch protection, review, merge, or
revert.

## Python SDK

```python
from pathlib import Path

from app_evolver import AppEvolver, InMemoryStateStore

evolver = AppEvolver(
    state_store=InMemoryStateStore(),
    work_root=Path(".app-evolver-work"),
)
app = evolver.register_app(Path("/absolute/path/to/my-app"))

run = evolver.sync_and_analyze(app["id"])
observations = evolver.list_observations(app["id"])

# Explicit human selection when required by the app constitution.
selected = evolver.select_observation(observations[0]["id"])
proposal = evolver.prepare_pull_request(selected["id"])
```

`AppEvolver` is the stable façade used by the CLI and development UI:

| Concern | Public SDK methods |
| --- | --- |
| Applications | `register_app`, `list_apps`, `get_app`, `default_app_id` |
| Governance | `get_governance` |
| Agent composition | `list_agents`, `get_agent_graph`, `configure_agent_graph`, `update_agent` |
| Continual memory | `create_agent_memory`, `list_agent_memory`, `update_agent_memory`, `delete_agent_memory`, `record_pull_request_outcome` |
| Observations | `sync_observations`, `analyze_observations`, `sync_and_analyze`, `list_observations`, `get_observation`, `select_observation` |
| Pull requests | `prepare_pull_request`, `list_pull_requests`, `get_pull_request`, `can_open_pull_request`, `open_pull_request` |
| Observability | `list_activity` |
| Automation | `run_cycle` |

Public return values have exported `TypedDict` contracts such as `AppInfo`,
`Observation`, `PullRequestProposal`, and `GovernanceSnapshot`. Expected failures
use exported domain errors rooted at `AppEvolverError`, including
`PolicyViolation`, `InvalidTransition`, `ValidationFailed`, and `DeliveryError`.

## Composable agents

Every agent implements the transport-neutral `Agent` protocol:

```python
class Agent(Protocol):
    @property
    def definition(self) -> AgentDefinition: ...

    def run(self, request: AgentRequest) -> AgentResponse: ...
```

`SignalAnalystAgent`, `ProductManagerAgent`, `UXResearcherAgent`,
`UIDesignerAgent`, `SoftwareEngineerAgent`, `QualityReviewerAgent`,
`EvidenceReviewerAgent`, and `AccessibilityReviewerAgent` are concrete
`BaseAgent` subtypes. An `AgentTeam` resolves the `kind` in each agent definition
through a type registry, so applications can add another subtype without
changing orchestration code. Requests and responses use normalized, serializable
envelopes. A future MCP or A2A adapter can therefore implement `Agent` and
translate those envelopes at the boundary; App Evolver does not prematurely
choose either transport for its core API.

The agent-team document is a dependency graph. App Evolver topologically divides
it into execution waves: agents in the same wave run in parallel; a later wave
runs only after all of its dependencies complete. Normalized upstream payloads
are supplied to downstream agents as `dependency_outputs`. The SDK exposes this
resolved shape through `get_agent_graph()`, and the development UI renders the
same graph.

## Continual memory and agent lineage

Each agent definition has an explicit version. Changing its model or instructions
requires a new version, and activity traces, PR proposals, and memories record the
exact version that participated. The default graph runs product and UX work in
parallel, feeds both into UI design and engineering, then runs quality, evidence,
and accessibility review in parallel before a proposal becomes PR-ready.

Agent memory is a separate injectable boundary. `JsonFileAgentMemoryStore` is the
durable local default; `InMemoryAgentMemoryStore` is available for tests, and a
future server can inject a Postgres implementation of `AgentMemoryStore`. Memory
supports reviewed CRUD operations for lessons, failures, decisions, and outcomes.
Runtime failures are recorded automatically, and hosts can call
`record_pull_request_outcome` after merge, rejection, revert, or failure. Relevant
history is supplied to later invocations, while agents remain unable to rewrite
their constitution, implementation, or memory without going through the public
reviewable APIs.

State and execution environments are separate concerns:

- `StateStore` holds signals, observations, activity traces, and in-progress PR
  metadata. v0 provides `InMemoryStateStore`.
- The local workspace owns disposable Git worktrees and validation processes.
  It is filesystem-backed because Git and app execution require real files.
- Companion repositories remain the source of truth for product configuration.
- Pull requests and the Git provider remain the durable record of code changes.

A future optional package can implement the `StateStore` protocol with Postgres,
similar to the way other libraries offer optional durable checkpointers. The core
library will not depend on that adapter.

## Companion application ownership

Each application repository owns its own:

- product constitution and intent;
- observation source;
- mutable and protected paths;
- grounded capabilities and success metrics;
- validation and preview commands;
- pull-request policy.

The repository must contain an `evolution.json` contract:

```json
{
  "schemaVersion": 1,
  "appId": "my-app",
  "name": "My App",
  "productIntent": "The outcome this product exists to create.",
  "observationSource": {
    "kind": "fixture",
    "path": "evolution/observations.json",
    "requiredProvenance": ["appVersion", "appRevision"]
  },
  "constitution": "evolution/constitution.json",
  "pullRequests": {
    "provider": "github",
    "baseBranch": "main",
    "draft": true
  },
  "mutablePaths": ["config/features.json"],
  "protectedPaths": ["src/auth/", "evolution.json"],
  "validationCommands": [
    ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
  ],
  "capabilities": {}
}
```

The contract is protected: agents may read it but cannot expand their own
authority. Contract changes require an ordinary human-reviewed PR.

Every interaction signal must identify both the customer-facing `appVersion`
and its exact Git `appRevision`. App Evolver verifies that revision exists in the
registered app repository, preserves version counts in observation evidence, and
includes them in the PR proposal together with the base commit, proposed commit,
diff, and repository validation output. This keeps changes grounded in both the
code customers actually used and the tests run against the proposed code.

## In-memory v0

The following state is process-local and disappears when the process exits:

- registered companion apps;
- observations and activity traces;
- agent configuration changes;
- in-progress PR metadata.

Agent memory is the deliberate exception: by default it is written to
`.app-evolver-work/agent-memory.json` and survives process restarts. This follows
the continual-harness idea of durable, inspectable learning without turning
opaque model context into the source of truth.

The local work directory is different: it contains temporary Git worktrees and
other files required to run and validate an application. Configure it with
`work_root` or `APP_EVOLVER_WORK_DIR`.

## CLI

The `app-evolver` CLI calls only the public Python SDK. Commands that require
state are atomic because v0 state does not survive between CLI processes.

```bash
# Inspect the effective app contract, constitution, and platform policy.
uv run app-evolver --app-path /absolute/path/to/my-app --json inspect

# Collect mock signals and print ranked themes.
uv run app-evolver --app-path /absolute/path/to/my-app observe

# Inspect serial and parallel agent execution waves.
uv run app-evolver graph

# Record and inspect a reviewed lesson that survives CLI processes.
uv run app-evolver --app-path /absolute/path/to/my-app remember ui-designer \
  "Keep the primary action visible on narrow screens."
uv run app-evolver --app-path /absolute/path/to/my-app memory

# Human-select a theme and prepare its validated PR branch in one invocation.
uv run app-evolver --app-path /absolute/path/to/my-app propose delivery_tracking

# Start the long-lived development UI with in-memory state.
uv run app-evolver --app-path /absolute/path/to/my-app serve
```

Use global `--json` for machine-readable output. `propose --open` opens the
checked branch as a GitHub pull request when the companion checkout and GitHub
CLI are configured.

## Optional development control room

The repository includes a thin browser UI over the same public SDK. It has no
direct access to the state store, registry, agent team, or workspace adapter.
It is a development adapter, not a required runtime service.

```bash
uv run app-evolver --app-path /absolute/path/to/my-app serve
```

Open <http://127.0.0.1:8100>.

- **Control room:** select observations and prepare checked PR branches.
- **Agent team:** configure the process-local composite agent team.
- **Governance:** visualize platform policy and the selected app's constitution,
  evolution surfaces, checks, and PR configuration.
- **Activity:** inspect each agent's inputs, outputs, status, duration, and run ID.
- **Memory:** inspect and curate durable lessons by app, agent, and agent version.

The local Git worktree is an execution workspace, not a hardened security
boundary. A future workspace adapter can execute the same library workflow in an
ephemeral container or remote validation sandbox. Delivery remains an ordinary
pull request.
