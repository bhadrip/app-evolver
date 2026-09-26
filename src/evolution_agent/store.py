from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Protocol

from .errors import InvalidTransition, NotFoundError


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore(Protocol):
    """Persistence boundary implemented in memory for v0 and by Postgres later."""

    def add_signals(self, app_id: str, signals: list[dict[str, Any]]) -> int: ...
    def latest_source_id(self, app_id: str) -> int: ...
    def signals(self, app_id: str) -> list[dict[str, Any]]: ...
    def upsert_observation(
        self, app_id: str, theme: str, summary: str, evidence: dict[str, Any], score: float
    ) -> int: ...
    def observations(self, app_id: str | None = None) -> list[dict[str, Any]]: ...
    def observation(self, observation_id: int) -> dict[str, Any]: ...
    def set_observation_status(self, observation_id: int, status: str) -> None: ...
    def add_pull_request(self, pull_request: dict[str, Any]) -> None: ...
    def pull_requests(self, app_id: str | None = None) -> list[dict[str, Any]]: ...
    def pull_request(self, pull_request_id: str) -> dict[str, Any]: ...
    def set_pull_request_opened(self, pull_request_id: str, number: int, url: str) -> None: ...
    def add_activity(self, activity: dict[str, Any]) -> None: ...
    def activities(self, limit: int = 100, app_id: str | None = None) -> list[dict[str, Any]]: ...


class InMemoryStateStore:
    def __init__(self):
        self._signals: list[dict[str, Any]] = []
        self._observations: list[dict[str, Any]] = []
        self._pull_requests: list[dict[str, Any]] = []
        self._activity: list[dict[str, Any]] = []
        self._next_signal_id = 1
        self._next_observation_id = 1
        self._next_activity_id = 1

    def add_signals(self, app_id: str, signals: list[dict[str, Any]]) -> int:
        inserted = 0
        known = {(item["app_id"], item["source_id"]) for item in self._signals}
        for signal in signals:
            source_id = int(signal["id"])
            if (app_id, source_id) in known:
                continue
            self._signals.append(
                {
                    "id": self._next_signal_id,
                    "app_id": app_id,
                    "source_id": source_id,
                    "event_type": signal["type"],
                    "app_version": signal.get("appVersion", "unknown"),
                    "app_revision": signal.get("appRevision", "unknown"),
                    "payload": copy.deepcopy(signal.get("payload", {})),
                    "created_at": signal.get("createdAt", now()),
                }
            )
            self._next_signal_id += 1
            inserted += 1
            known.add((app_id, source_id))
        return inserted

    def latest_source_id(self, app_id: str) -> int:
        return max((item["source_id"] for item in self._signals if item["app_id"] == app_id), default=0)

    def signals(self, app_id: str) -> list[dict[str, Any]]:
        values = [item for item in self._signals if item["app_id"] == app_id]
        return copy.deepcopy(sorted(values, key=lambda item: item["source_id"]))

    def upsert_observation(
        self, app_id: str, theme: str, summary: str, evidence: dict[str, Any], score: float
    ) -> int:
        existing = next(
            (item for item in self._observations if item["app_id"] == app_id and item["theme"] == theme),
            None,
        )
        if existing:
            existing.update(summary=summary, evidence=copy.deepcopy(evidence), score=score, updated_at=now())
            return int(existing["id"])
        observation_id = self._next_observation_id
        self._next_observation_id += 1
        self._observations.append(
            {
                "id": observation_id,
                "app_id": app_id,
                "theme": theme,
                "summary": summary,
                "evidence": copy.deepcopy(evidence),
                "score": score,
                "status": "candidate",
                "updated_at": now(),
            }
        )
        return observation_id

    def observations(self, app_id: str | None = None) -> list[dict[str, Any]]:
        values = self._observations if app_id is None else [
            item for item in self._observations if item["app_id"] == app_id
        ]
        return copy.deepcopy(sorted(values, key=lambda item: (-item["score"], item["id"])))

    def observation(self, observation_id: int) -> dict[str, Any]:
        value = next((item for item in self._observations if item["id"] == observation_id), None)
        if not value:
            raise NotFoundError(f"Observation {observation_id} does not exist")
        return copy.deepcopy(value)

    def set_observation_status(self, observation_id: int, status: str) -> None:
        value = next((item for item in self._observations if item["id"] == observation_id), None)
        if not value:
            raise NotFoundError(f"Observation {observation_id} does not exist")
        value.update(status=status, updated_at=now())

    def add_pull_request(self, pull_request: dict[str, Any]) -> None:
        if any(item["id"] == pull_request["id"] for item in self._pull_requests):
            raise InvalidTransition(f"PR branch {pull_request['id']} already exists")
        self._pull_requests.append(copy.deepcopy(pull_request))

    def pull_requests(self, app_id: str | None = None) -> list[dict[str, Any]]:
        values = self._pull_requests if app_id is None else [
            item for item in self._pull_requests if item["app_id"] == app_id
        ]
        return copy.deepcopy(list(reversed(values)))

    def pull_request(self, pull_request_id: str) -> dict[str, Any]:
        value = next((item for item in self._pull_requests if item["id"] == pull_request_id), None)
        if not value:
            raise NotFoundError(f"PR branch {pull_request_id} does not exist")
        return copy.deepcopy(value)

    def set_pull_request_opened(self, pull_request_id: str, number: int, url: str) -> None:
        value = next((item for item in self._pull_requests if item["id"] == pull_request_id), None)
        if not value:
            raise NotFoundError(f"PR branch {pull_request_id} does not exist")
        value.update(status="opened", pr_number=number, pr_url=url)

    def add_activity(self, activity: dict[str, Any]) -> None:
        value = copy.deepcopy(activity)
        value["id"] = self._next_activity_id
        self._next_activity_id += 1
        self._activity.append(value)

    def activities(self, limit: int = 100, app_id: str | None = None) -> list[dict[str, Any]]:
        values = self._activity if app_id is None else [
            item for item in self._activity if item["app_id"] == app_id
        ]
        return copy.deepcopy(list(reversed(values))[:limit])
