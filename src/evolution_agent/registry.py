from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .contracts import AppContract


class AppRegistry:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"schemaVersion": 1, "apps": []})

    def all(self) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text())["apps"]

    def register(self, app_root: Path) -> dict[str, Any]:
        contract = AppContract.load(app_root)
        document = {"id": contract.app_id, "name": contract.document["name"], "path": str(contract.root)}
        registry = {"schemaVersion": 1, "apps": self.all()}
        existing = next((item for item in registry["apps"] if item["id"] == contract.app_id), None)
        if existing:
            existing.update(document)
        else:
            registry["apps"].append(document)
        self._write(registry)
        return document

    def get(self, app_id: str) -> dict[str, Any]:
        app = next((item for item in self.all() if item["id"] == app_id), None)
        if not app:
            raise ValueError(f"App is not registered: {app_id}")
        return app

    def default_app_id(self) -> str | None:
        apps = self.all()
        return apps[0]["id"] if apps else None

    def _write(self, document: dict[str, Any]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix="apps-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as temporary:
                json.dump(document, temporary, indent=2)
                temporary.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
