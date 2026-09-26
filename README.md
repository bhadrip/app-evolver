# App Evolver

App Evolver is a reusable companion service for applications that improve from
observed customer behavior. It is intentionally application-agnostic: like a
database server, one service can be configured at runtime to work with multiple
independent applications.

A configurable agent team groups observations, frames a hypothesis, implements a
bounded change in a disposable Git worktree, runs the companion repository's
checks, and opens an ordinary pull request. App Evolver does not replace Git, CI,
branch protection, review, merge, or revert.

## Ownership boundary

App Evolver owns only generic orchestration:

- the agent runtime and control-room UI;
- runtime app registration and state;
- worktree isolation and contract enforcement;
- activity traces and PR creation;
- platform-wide safety ceilings.

Every companion application owns its own:

- product constitution and intent;
- observation source;
- mutable and protected paths;
- grounded capabilities and success metrics;
- validation commands;
- Git provider, base branch, and draft-PR policy.

None of those app-specific values are checked into this repository.

## Run

```bash
python3 -m src.evolution_agent.cli register /absolute/path/to/your-app
python3 -m src.evolution_agent.cli serve
```

Open <http://127.0.0.1:8100>. Apps can also be registered from the UI.

For a separate runtime volume:

```bash
APP_EVOLVER_DATA_DIR=/var/lib/app-evolver \
  python3 -m src.evolution_agent.cli serve
```

For a single companion checkout, registration can happen at startup:

```bash
APP_EVOLVER_APP=/workspace/my-app \
  python3 -m src.evolution_agent.cli serve
```

Runtime state—including the app registry, SQLite state, customized agent team,
and sandboxes—lives under `APP_EVOLVER_DATA_DIR`. It is excluded from Git.

## Companion application contract

The registered Git repository must contain `evolution.json`. The contract points
to other app-owned resources using paths relative to that repository:

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

The evolution contract is protected: agents may read it but cannot expand their
own authority. Contract changes require an ordinary human-reviewed PR.

## Control room

- **Control room:** select observations and prepare checked PR branches.
- **Agent team:** configure the reusable composite agent runtime.
- **Governance:** visualize platform policy and the selected app's constitution,
  evolution surfaces, checks, and PR configuration.
- **Activity:** inspect each agent's inputs, outputs, status, duration, and run ID.

## CLI

```bash
python3 -m src.evolution_agent.cli apps
python3 -m src.evolution_agent.cli sync --app my-app
python3 -m src.evolution_agent.cli triage --app my-app
python3 -m src.evolution_agent.cli list --app my-app
python3 -m src.evolution_agent.cli select 1
python3 -m src.evolution_agent.cli prepare-pr 1
python3 -m src.evolution_agent.cli open-pr <branch-id>
```

The current implementation uses deterministic adapters so the control plane is
reproducible before model-backed agents are introduced. A Git worktree isolates
files and history but is not a hardened security boundary; untrusted generated
code should be validated in an ephemeral container or micro-VM with network and
resource restrictions.
