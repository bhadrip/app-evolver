from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .contracts import AppContract


class AppRegistry:
    """Process-local companion app registry for v0."""

    def __init__(self):
        self._apps: list[dict[str, Any]] = []

    def all(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._apps)

    def register(self, app_root: Path) -> dict[str, Any]:
        contract = AppContract.load(app_root)
        document = {"id": contract.app_id, "name": contract.document["name"], "path": str(contract.root)}
        existing = next((item for item in self._apps if item["id"] == contract.app_id), None)
        if existing:
            existing.update(document)
        else:
            self._apps.append(document)
        return copy.deepcopy(document)

    def get(self, app_id: str) -> dict[str, Any]:
        app = next((item for item in self._apps if item["id"] == app_id), None)
        if not app:
            raise ValueError(f"App is not registered: {app_id}")
        return copy.deepcopy(app)

    def default_app_id(self) -> str | None:
        return self._apps[0]["id"] if self._apps else None
