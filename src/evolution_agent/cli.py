"""Command-line adapter over the public App Evolver SDK."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .dashboard import serve
from .engine import AppEvolver
from .errors import AppEvolverError, NotFoundError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="App Evolver SDK command-line adapter")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    parser.add_argument(
        "--app-path", action="append", type=Path, default=[],
        help="register a companion checkout for this process; may be repeated",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("apps", help="list apps registered for this invocation")
    subparsers.add_parser("agents", help="show the configured composite agent team")
    subparsers.add_parser("graph", help="show serial and parallel agent execution waves")
    subparsers.add_parser("serve", help="run the optional development control room")
    for name, help_text in (
        ("inspect", "show the effective contract and governance policy"),
        ("observe", "sync signals and produce ranked observations"),
        ("cycle", "run one automatic evolution cycle"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--app")
    propose = subparsers.add_parser(
        "propose", help="select a theme and prepare its validated PR branch atomically"
    )
    propose.add_argument("theme", help="theme returned by the observe command")
    propose.add_argument("--app")
    propose.add_argument("--open", action="store_true", help="also open the GitHub pull request")
    return parser


def _emit(payload: Any, *, as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif human is not None:
        print(human)


def _resolve_app(evolver: AppEvolver, requested: str | None) -> str:
    app_id = requested or evolver.default_app_id()
    if not app_id:
        raise NotFoundError("No companion app is registered. Pass --app-path /path/to/app")
    evolver.get_app(app_id)
    return app_id


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    evolver = AppEvolver()
    try:
        for app_path in args.app_path:
            evolver.register_app(app_path)

        if args.command == "apps":
            apps = evolver.list_apps()
            _emit(
                apps,
                as_json=args.json,
                human="\n".join(f"{app['id']}\t{app['name']}\t{app['path']}" for app in apps),
            )
        elif args.command == "agents":
            agents = evolver.list_agents()
            _emit(
                agents,
                as_json=args.json,
                human="\n".join(
                    f"{agent['id']}\t{'enabled' if agent['enabled'] else 'disabled'}\t{agent['name']}"
                    for agent in agents
                ),
            )
        elif args.command == "graph":
            graph = evolver.get_agent_graph()
            _emit(
                graph,
                as_json=args.json,
                human="\n".join(
                    f"wave {index}: {' | '.join(wave)}"
                    for index, wave in enumerate(graph["waves"], start=1)
                ),
            )
        elif args.command == "serve":
            serve(evolver=evolver)
        elif args.command == "inspect":
            governance = evolver.get_governance(_resolve_app(evolver, args.app))
            _emit(governance, as_json=True)
        elif args.command == "observe":
            app_id = _resolve_app(evolver, args.app)
            result = evolver.sync_and_analyze(app_id)
            observations = evolver.list_observations(app_id)
            payload = {"run": result, "observations": observations}
            rows = [
                f"{item['theme']}\tscore={item['score']:.0f}\t{item['status']}\t{item['summary']}"
                for item in observations
            ]
            _emit(payload, as_json=args.json, human="\n".join(rows))
        elif args.command == "propose":
            app_id = _resolve_app(evolver, args.app)
            evolver.sync_and_analyze(app_id)
            observation = next(
                (item for item in evolver.list_observations(app_id) if item["theme"] == args.theme),
                None,
            )
            if not observation:
                raise NotFoundError(f"No observation matched theme: {args.theme}")
            evolver.select_observation(observation["id"])
            pull_request = evolver.prepare_pull_request(observation["id"])
            if args.open:
                pull_request = evolver.open_pull_request(pull_request["id"])
            _emit(
                pull_request,
                as_json=args.json,
                human=(
                    f"Opened {pull_request['pr_url']}" if pull_request["pr_url"]
                    else f"Prepared {pull_request['branch']} in {pull_request['sandbox_path']}"
                ),
            )
        elif args.command == "cycle":
            app_id = _resolve_app(evolver, args.app)
            outcome = evolver.run_cycle(app_id)
            _emit({"app_id": app_id, "outcome": outcome}, as_json=args.json, human=outcome)
    except (AppEvolverError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        if args.json:
            print(json.dumps({"error": type(error).__name__, "message": str(error)}))
        else:
            print(f"app-evolver: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
