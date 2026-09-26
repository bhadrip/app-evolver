# App Evolver

**App Evolver** is a small, auditable prototype of an observation-driven product
team. It turns observation signals into candidate improvements while enforcing
structure, direction, and safe boundaries. A configurable team of agents groups
signals, frames a hypothesis, prepares a bounded change in an isolated Git
worktree, validates it, and opens an ordinary pull request.

It deliberately uses a deterministic planner. That makes the first end-to-end
loop reproducible and proves the control plane before an LLM is allowed to write
code. Model-backed agents can later operate under the same sandbox, constitution,
validation, and pull-request controls.

## Quick start with mock observations

The first version deliberately reads synthetic, non-personal signals from
[`mock-data/observations.json`](mock-data/observations.json). No running app,
telemetry system, or model API is required to exercise the feedback workflow.

In the feedback-agent repository:

```bash
python3 -m src.evolution_agent.cli sync
python3 -m src.evolution_agent.cli triage
python3 -m src.evolution_agent.cli serve
```

Open <http://127.0.0.1:8100>. The control room has three views:

- **Control room** selects observations and prepares checked PR branches.
- **Agent team** enables agents and edits their names and instructions.
- **Activity** shows each agent's inputs, outputs, status, run ID, and duration.

When the app repository has a GitHub `origin`, App Evolver can push the checked
branch and open a draft PR. CI, review, merge, and revert remain normal repository
operations; App Evolver does not replace them.

To view the store, use another terminal:

```bash
cd ../pet-store-app
python3 -m src.pet_store.server
```

The same workflow is available from the CLI:

```bash
python3 -m src.evolution_agent.cli list
python3 -m src.evolution_agent.cli select 1
python3 -m src.evolution_agent.cli prepare-pr 1
python3 -m src.evolution_agent.cli open-pr <branch-id>
```

## Agent composition and human-in-the-loop

[`agents.json`](agents.json) defines the composite agent team. The same settings
are editable in the Agent team UI. The deterministic prototype persists agent
instructions but does not claim to execute them through a model yet.

[`constitution.json`](constitution.json) starts with observation selection set to
`required`. Set it to `automatic` to let `cycle` pick the highest-ranked candidate:

```json
"humanInTheLoop": {
  "observationSelection": "automatic"
}
```

```bash
python3 -m src.evolution_agent.cli cycle
```

The cycle stops at a checked branch. Opening, reviewing, and merging a PR always
uses the repository's existing Git and GitHub primitives.

## Onboarding an existing app

Add an `evolution.json` contract modeled on the pet store's contract, then add the
checkout to `agent-config.json`. Replace the fixture source with a live observation
adapter when the control loop is ready to consume real telemetry. The agent requires an existing Git repository
with a clean working tree before it creates a sandbox. The current deterministic
planner supports JSON feature-flag changes; later planners can share this adapter.

The Git worktree is an isolation mechanism for files and history, not a hardened
security boundary. For untrusted generated code, validation should run in an
ephemeral container or micro-VM with network disabled, resource limits, and a
read-only base image.
