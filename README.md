# App Evolver

App Evolver is a pure Python library for observation-driven application
evolution. Applications embed and configure it; App Evolver does not require a
server, database, LangGraph, or hosted control plane.

The library composes agents that group observations, frame a hypothesis, prepare
a bounded change, validate it in an isolated workspace, and open an ordinary
pull request. It does not replace Git, CI, branch protection, review, merge, or
revert.

## Library shape

```python
from pathlib import Path

from app_evolver import AppEvolver, InMemoryStateStore

evolver = AppEvolver(
    state_store=InMemoryStateStore(),
    work_root=Path(".app-evolver-work"),
)
app = evolver.register_app(Path("/absolute/path/to/my-app"))

evolver.sync(app["id"])
evolver.triage(app["id"])
```

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
    "path": "evolution/observations.json"
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

## In-memory v0

The following state is process-local and disappears when the process exits:

- registered companion apps;
- observations and activity traces;
- agent configuration changes;
- in-progress PR metadata.

The local work directory is different: it contains temporary Git worktrees and
other files required to run and validate an application. Configure it with
`work_root` or `APP_EVOLVER_WORK_DIR`.

## Optional development control room

The repository includes a thin CLI and browser UI over the same public library.
They are development adapters, not required runtime services.

```bash
uv run app-evolver --app-path /absolute/path/to/my-app serve
```

Open <http://127.0.0.1:8100>.

- **Control room:** select observations and prepare checked PR branches.
- **Agent team:** configure the process-local composite agent team.
- **Governance:** visualize platform policy and the selected app's constitution,
  evolution surfaces, checks, and PR configuration.
- **Activity:** inspect each agent's inputs, outputs, status, duration, and run ID.

The local Git worktree is an execution workspace, not a hardened security
boundary. A future workspace adapter can execute the same library workflow in an
ephemeral container or remote validation sandbox. Delivery remains an ordinary
pull request.
