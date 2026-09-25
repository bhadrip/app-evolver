from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any

from .dashboard import serve
from .engine import Engine


DEMO_FEEDBACK = [
    "I want a wishlist so I can come back to toys later.",
    "Please add save for later; I am comparing a few cat products.",
    "A favorites list would be really helpful.",
    "Can you show whether an item is in stock before I add it?",
    "I need clearer availability information.",
]


def post_event(message: str, index: int) -> None:
    body = json.dumps(
        {
            "type": "feedback_submitted",
            "sessionId": f"demo-{index}",
            "payload": {"category": "idea", "message": message, "source": "demo-seed"},
        }
    ).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5):
        pass


def print_state(engine: Engine) -> None:
    print("Observations")
    for item in engine.store.observations():
        print(f"  {item['id']:>3}  {item['status']:<10} score={item['score']:.0f}  {item['theme']}: {item['summary']}")
    print("Proposals")
    for item in engine.store.proposals():
        print(f"  {item['id']}  {item['status']:<10} risk={item['risk']}  observation={item['observation_id']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observation-driven app evolution prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "seed-demo", "sync", "triage", "list", "cycle", "serve"):
        subparsers.add_parser(name)
    for name in ("select", "propose"):
        command = subparsers.add_parser(name)
        command.add_argument("observation_id", type=int)
    for name in ("approve", "reject", "apply"):
        command = subparsers.add_parser(name)
        command.add_argument("proposal_id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    engine = Engine()
    if args.command == "init":
        print(f"Initialized state at {engine.store.path}")
    elif args.command == "seed-demo":
        for index, message in enumerate(DEMO_FEEDBACK, start=1):
            post_event(message, index)
        print(f"Seeded {len(DEMO_FEEDBACK)} feedback signals.")
    elif args.command == "sync":
        print(f"Synced {engine.sync()} new signal(s).")
    elif args.command == "triage":
        print(f"Triaged {len(engine.triage())} actionable theme(s).")
    elif args.command == "list":
        print_state(engine)
    elif args.command == "select":
        engine.select(args.observation_id)
        print(f"Selected observation {args.observation_id}.")
    elif args.command == "propose":
        proposal = engine.propose(args.observation_id)
        print(f"Created validated proposal {proposal['id']} in {proposal['sandbox_path']}")
        print(proposal["diff"])
    elif args.command == "approve":
        engine.approve(args.proposal_id)
        print(f"Approved proposal {args.proposal_id}.")
    elif args.command == "reject":
        engine.reject(args.proposal_id)
        print(f"Rejected proposal {args.proposal_id}.")
    elif args.command == "apply":
        rollback = engine.apply(args.proposal_id)
        print(f"Applied proposal {args.proposal_id}. Rollback commit: {rollback}")
    elif args.command == "cycle":
        print(engine.cycle())
    elif args.command == "serve":
        serve()


if __name__ == "__main__":
    main()

