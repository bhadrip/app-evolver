# Feedback evolution agent

This repository is a small, auditable prototype of an observation-driven product
team. It reads sanitized signals from an app, groups them into candidate
observations, proposes a bounded change in an isolated Git worktree, validates the
change, and optionally waits for human decisions at two gates.

It deliberately uses a deterministic planner. That makes the first end-to-end
loop reproducible and proves the control plane before an LLM is allowed to write
code. A model-backed planner can later produce patches under the same sandbox,
constitution, validation, and approval controls.

## Quick start

In terminal 1:

```bash
cd ../pet-store-app
python3 -m src.pet_store.server
```

In terminal 2:

```bash
python3 -m src.evolution_agent.cli init
python3 -m src.evolution_agent.cli seed-demo
python3 -m src.evolution_agent.cli sync
python3 -m src.evolution_agent.cli triage
python3 -m src.evolution_agent.cli serve
```

Open <http://127.0.0.1:8100>. Select an observation, create a proposal, inspect
its evidence and diff, approve it, and apply it. Refresh the pet store to see the
new capability.

The same workflow is available from the CLI:

```bash
python3 -m src.evolution_agent.cli list
python3 -m src.evolution_agent.cli select 1
python3 -m src.evolution_agent.cli propose 1
python3 -m src.evolution_agent.cli approve <proposal-id>
python3 -m src.evolution_agent.cli apply <proposal-id>
```

## Human-in-the-loop modes

[`constitution.json`](constitution.json) starts with both gates set to
`required`. Change either gate to `automatic` to let `cycle` progress through it:

```json
"humanInTheLoop": {
  "observationSelection": "automatic",
  "changeApproval": "automatic"
}
```

```bash
python3 -m src.evolution_agent.cli cycle
```

Automatic approval only applies to risk levels explicitly listed in the
constitution. Manual commands remain available in either mode.

## Onboarding an existing app

Add an `evolution.json` contract modeled on the pet store's contract, then add the
checkout to `agent-config.json`. The agent requires an existing Git repository
with a clean working tree before it creates a sandbox. The current deterministic
planner supports JSON feature-flag changes; later planners can share this adapter.

The Git worktree is an isolation mechanism for files and history, not a hardened
security boundary. For untrusted generated code, validation should run in an
ephemeral container or micro-VM with network disabled, resource limits, and a
read-only base image.

