from __future__ import annotations

import argparse
from pathlib import Path

from .dashboard import serve
from .engine import Engine


def print_state(engine: Engine, app_id: str) -> None:
    print("Observations")
    for item in engine.store.observations(app_id):
        print(f"  {item['id']:>3}  {item['status']:<10} score={item['score']:.0f}  {item['theme']}: {item['summary']}")
    print("Pull requests")
    for item in engine.store.pull_requests(app_id):
        print(f"  {item['id']}  {item['status']:<10} risk={item['risk']}  observation={item['observation_id']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observation-driven app evolution prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    subparsers.add_parser("apps")
    subparsers.add_parser("serve")
    register = subparsers.add_parser("register")
    register.add_argument("path", type=Path)
    for name in ("sync", "triage", "list", "cycle"):
        command = subparsers.add_parser(name)
        command.add_argument("--app")
    for name in ("select", "prepare-pr"):
        command = subparsers.add_parser(name)
        command.add_argument("observation_id", type=int)
    command = subparsers.add_parser("open-pr")
    command.add_argument("pull_request_id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    engine = Engine()
    app_id = getattr(args, "app", None) or engine.registry.default_app_id()
    if args.command == "init":
        print(f"Initialized state at {engine.store.path}")
    elif args.command == "register":
        app = engine.register_app(args.path)
        print(f"Registered {app['name']} ({app['id']}) from {app['path']}")
    elif args.command == "apps":
        for app in engine.registry.all():
            print(f"{app['id']}\t{app['name']}\t{app['path']}")
    elif args.command in {"sync", "triage", "list", "cycle"} and not app_id:
        raise SystemExit("No companion app is registered. Run: app-evolver register /path/to/app")
    elif args.command == "sync":
        print(f"Synced {engine.sync(app_id)} new signal(s).")
    elif args.command == "triage":
        print(f"Triaged {len(engine.triage(app_id))} actionable theme(s).")
    elif args.command == "list":
        print_state(engine, app_id)
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
        print(engine.cycle(app_id))
    elif args.command == "serve":
        serve()


if __name__ == "__main__":
    main()
