from __future__ import annotations

import argparse

from .dashboard import serve
from .engine import Engine


def print_state(engine: Engine) -> None:
    print("Observations")
    for item in engine.store.observations():
        print(f"  {item['id']:>3}  {item['status']:<10} score={item['score']:.0f}  {item['theme']}: {item['summary']}")
    print("Pull requests")
    for item in engine.store.pull_requests():
        print(f"  {item['id']}  {item['status']:<10} risk={item['risk']}  observation={item['observation_id']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observation-driven app evolution prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "sync", "triage", "list", "cycle", "serve"):
        subparsers.add_parser(name)
    for name in ("select", "prepare-pr"):
        command = subparsers.add_parser(name)
        command.add_argument("observation_id", type=int)
    command = subparsers.add_parser("open-pr")
    command.add_argument("pull_request_id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    engine = Engine()
    if args.command == "init":
        print(f"Initialized state at {engine.store.path}")
    elif args.command == "sync":
        print(f"Synced {engine.sync()} new signal(s).")
    elif args.command == "triage":
        print(f"Triaged {len(engine.triage())} actionable theme(s).")
    elif args.command == "list":
        print_state(engine)
    elif args.command == "select":
        engine.select(args.observation_id)
        print(f"Selected observation {args.observation_id}.")
    elif args.command == "prepare-pr":
        pull_request = engine.prepare_pull_request(args.observation_id)
        print(f"Prepared checked branch {pull_request['branch']} in {pull_request['sandbox_path']}")
        print(pull_request["diff"])
    elif args.command == "open-pr":
        print(engine.open_pull_request(args.pull_request_id))
    elif args.command == "cycle":
        print(engine.cycle())
    elif args.command == "serve":
        serve()


if __name__ == "__main__":
    main()
