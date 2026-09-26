from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .contracts import AppContract


class Sandbox:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _run(command: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "GIT_AUTHOR_NAME": "Evolution Agent",
            "GIT_AUTHOR_EMAIL": "evolution-agent@localhost",
            "GIT_COMMITTER_NAME": "Evolution Agent",
            "GIT_COMMITTER_EMAIL": "evolution-agent@localhost",
        }
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )

    def prepare_pull_request(
        self, contract: AppContract, observation: dict[str, Any], constitution: dict[str, Any]
    ) -> dict[str, Any]:
        status = self._run(["git", "status", "--porcelain"], contract.root)
        if status.returncode != 0 or status.stdout.strip():
            raise ValueError("App working tree must be clean before preparing a PR branch")

        capability = contract.capability(observation["theme"])
        change = capability["change"]
        if change.get("kind") != "json_set":
            raise ValueError(f"Unsupported grounded change operation: {change.get('kind')}")

        pull_request_id = uuid.uuid4().hex[:10]
        branch = f"evolution/{pull_request_id}"
        sandbox_path = self.root / contract.app_id / pull_request_id
        sandbox_path.parent.mkdir(parents=True, exist_ok=True)
        base = self._run(["git", "rev-parse", "HEAD"], contract.root)
        if base.returncode != 0:
            raise ValueError(f"Cannot resolve app HEAD: {base.stdout.strip()}")
        base_commit = base.stdout.strip()
        created = self._run(
            ["git", "worktree", "add", "-b", branch, str(sandbox_path), base_commit], contract.root
        )
        if created.returncode != 0:
            raise ValueError(f"Cannot create sandbox worktree: {created.stdout.strip()}")

        target = (sandbox_path / change["path"]).resolve()
        if sandbox_path not in target.parents:
            raise ValueError("Grounded change escaped the sandbox")
        document = json.loads(target.read_text())
        document[change["key"]] = change["value"]
        target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

        changed = self._run(["git", "diff", "--name-only"], sandbox_path)
        changed_paths = [line for line in changed.stdout.splitlines() if line]
        contract.validate_changed_paths(
            changed_paths, int(constitution["limits"]["maxChangedFiles"])
        )

        validation_output: list[str] = []
        timeout = int(constitution["limits"]["validationTimeoutSeconds"])
        for command in contract.document["validationCommands"]:
            result = self._run([str(part) for part in command], sandbox_path, timeout=timeout)
            validation_output.append(f"$ {' '.join(command)}\n{result.stdout.strip()}")
            if result.returncode != 0:
                raise ValueError("Validation failed:\n" + "\n\n".join(validation_output))

        diff = self._run(["git", "diff", "--no-ext-diff", "--"], sandbox_path).stdout
        self._run(["git", "add", "--", *changed_paths], sandbox_path)
        committed = self._run(
            ["git", "commit", "-m", f"evolve: {capability['description']}"], sandbox_path
        )
        if committed.returncode != 0:
            raise ValueError(f"Could not commit PR branch: {committed.stdout.strip()}")
        proposed_commit = self._run(["git", "rev-parse", "HEAD"], sandbox_path).stdout.strip()
        return {
            "id": pull_request_id,
            "app_id": contract.app_id,
            "observation_id": observation["id"],
            "hypothesis": (
                f"If we {capability['description'].lower()} then the observation's affected customers "
                f"will use it, improving {capability['successMetric']}."
            ),
            "success_metric": capability["successMetric"],
            "risk": capability["risk"],
            "branch": branch,
            "sandbox_path": str(sandbox_path),
            "base_commit": base_commit,
            "proposed_commit": proposed_commit,
            "diff": diff,
            "validation": "\n\n".join(validation_output),
            "status": "checks_passed",
            "pr_number": None,
            "pr_url": None,
        }
