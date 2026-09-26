from __future__ import annotations

import copy
from pathlib import Path
from .contracts import AppContract
from .errors import NotFoundError
from .models import AppInfo


class AppRegistry:
    """Process-local companion app registry for v0."""

    def __init__(self):
        self._apps: list[AppInfo] = []

    def all(self) -> list[AppInfo]:
        return copy.deepcopy(self._apps)

    def register(self, app_root: Path) -> AppInfo:
        contract = AppContract.load(app_root)
        document = {"id": contract.app_id, "name": contract.document["name"], "path": str(contract.root)}
        existing = next((item for item in self._apps if item["id"] == contract.app_id), None)
        if existing:
            existing.update(document)
        else:
            self._apps.append(document)
        return copy.deepcopy(document)

    def get(self, app_id: str) -> AppInfo:
        app = next((item for item in self._apps if item["id"] == app_id), None)
        if not app:
            raise NotFoundError(f"App is not registered: {app_id}")
        return copy.deepcopy(app)

    def default_app_id(self) -> str | None:
        return self._apps[0]["id"] if self._apps else None
