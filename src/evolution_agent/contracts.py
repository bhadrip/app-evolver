from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, NotFoundError, PolicyViolation


@dataclass(frozen=True)
class AppContract:
    root: Path
    document: dict[str, Any]

    @classmethod
    def load(cls, root: Path) -> "AppContract":
        root = root.resolve()
        contract_path = root / "evolution.json"
        if not (root / ".git").exists():
            raise ConfigurationError(f"App is not a Git repository: {root}")
        if not contract_path.is_file():
            raise ConfigurationError(f"Missing evolution contract: {contract_path}")
        document = json.loads(contract_path.read_text())
        required = {
            "appId", "name", "productIntent", "observationSource", "constitution",
            "pullRequests", "mutablePaths", "protectedPaths", "validationCommands",
        }
        missing = sorted(required - document.keys())
        if missing:
            raise ConfigurationError(f"Evolution contract is missing: {', '.join(missing)}")
        return cls(root=root, document=document)

    @property
    def app_id(self) -> str:
        return self.document["appId"]

    @property
    def capabilities(self) -> dict[str, Any]:
        return self.document.get("capabilities", {})

    def capability(self, theme: str) -> dict[str, Any]:
        if theme not in self.capabilities:
            raise NotFoundError(f"No grounded evolution capability exists for theme: {theme}")
        return self.capabilities[theme]

    def resolve_owned_path(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if self.root not in path.parents:
            raise PolicyViolation(f"App-owned path escapes repository: {relative_path}")
        return path

    def validate_changed_paths(self, changed_paths: list[str], max_files: int) -> None:
        if not changed_paths:
            raise PolicyViolation("Planner produced no change")
        if len(changed_paths) > max_files:
            raise PolicyViolation(
                f"Change has {len(changed_paths)} files; constitution permits {max_files}"
            )
        mutable = tuple(self.document["mutablePaths"])
        protected = tuple(self.document["protectedPaths"])
        for path in changed_paths:
            if any(path == item or path.startswith(item.rstrip("/") + "/") for item in protected):
                raise PolicyViolation(f"Planner touched protected path: {path}")
            if not any(path == item or path.startswith(item.rstrip("/") + "/") for item in mutable):
                raise PolicyViolation(f"Planner touched path outside the evolution surface: {path}")
