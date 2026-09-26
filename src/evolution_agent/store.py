from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_id TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(app_id, source_id)
                );
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_id TEXT NOT NULL,
                    theme TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    score REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    updated_at TEXT NOT NULL,
                    UNIQUE(app_id, theme)
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    observation_id INTEGER NOT NULL,
                    hypothesis TEXT NOT NULL,
                    success_metric TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    sandbox_path TEXT NOT NULL,
                    base_commit TEXT NOT NULL,
                    proposed_commit TEXT NOT NULL,
                    diff TEXT NOT NULL,
                    validation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(observation_id) REFERENCES observations(id)
                );
                CREATE TABLE IF NOT EXISTS pull_requests (
                    id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    observation_id INTEGER NOT NULL,
                    hypothesis TEXT NOT NULL,
                    success_metric TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    sandbox_path TEXT NOT NULL,
                    base_commit TEXT NOT NULL,
                    proposed_commit TEXT NOT NULL,
                    diff TEXT NOT NULL,
                    validation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pr_number INTEGER,
                    pr_url TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(observation_id) REFERENCES observations(id)
                );
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_summary TEXT NOT NULL,
                    output_summary TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO pull_requests(
                    id, app_id, observation_id, hypothesis, success_metric, risk,
                    branch, sandbox_path, base_commit, proposed_commit, diff,
                    validation, status, pr_number, pr_url, created_at
                )
                SELECT
                    id, app_id, observation_id, hypothesis, success_metric, risk,
                    branch, sandbox_path, base_commit, proposed_commit, diff,
                    validation,
                    CASE status
                        WHEN 'applied' THEN 'merged'
                        WHEN 'rejected' THEN 'closed'
                        ELSE 'checks_passed'
                    END,
                    NULL, NULL, created_at
                FROM proposals
                """
            )
            connection.execute(
                "UPDATE observations SET status = 'pr_ready' WHERE status = 'proposed'"
            )

    def add_signals(self, app_id: str, signals: list[dict[str, Any]]) -> int:
        inserted = 0
        with self.connect() as connection:
            for signal in signals:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO signals(app_id, source_id, event_type, payload, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        app_id,
                        int(signal["id"]),
                        signal["type"],
                        json.dumps(signal.get("payload", {}), sort_keys=True),
                        signal.get("createdAt", now()),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def latest_source_id(self, app_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(source_id), 0) AS value FROM signals WHERE app_id = ?", (app_id,)
            ).fetchone()
        return int(row["value"])

    def signals(self, app_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM signals WHERE app_id = ? ORDER BY source_id", (app_id,)
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def upsert_observation(
        self, app_id: str, theme: str, summary: str, evidence: dict[str, Any], score: float
    ) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO observations(app_id, theme, summary, evidence, score, status, updated_at)
                VALUES (?, ?, ?, ?, ?, 'candidate', ?)
                ON CONFLICT(app_id, theme) DO UPDATE SET
                    summary = excluded.summary,
                    evidence = excluded.evidence,
                    score = excluded.score,
                    updated_at = excluded.updated_at
                """,
                (app_id, theme, summary, json.dumps(evidence, sort_keys=True), score, now()),
            )
            row = connection.execute(
                "SELECT id FROM observations WHERE app_id = ? AND theme = ?", (app_id, theme)
            ).fetchone()
        return int(row["id"])

    def observations(self, app_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM observations"
        parameters: tuple[Any, ...] = ()
        if app_id:
            query += " WHERE app_id = ?"
            parameters = (app_id,)
        query += " ORDER BY score DESC, id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows]

    def observation(self, observation_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM observations WHERE id = ?", (observation_id,)).fetchone()
        if not row:
            raise ValueError(f"Observation {observation_id} does not exist")
        return {**dict(row), "evidence": json.loads(row["evidence"])}

    def set_observation_status(self, observation_id: int, status: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE observations SET status = ?, updated_at = ? WHERE id = ?",
                (status, now(), observation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Observation {observation_id} does not exist")

    def add_pull_request(self, pull_request: dict[str, Any]) -> None:
        fields = (
            "id", "app_id", "observation_id", "hypothesis", "success_metric", "risk",
            "branch", "sandbox_path", "base_commit", "proposed_commit", "diff",
            "validation", "status", "pr_number", "pr_url", "created_at",
        )
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO pull_requests({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                tuple(pull_request.get(field) for field in fields),
            )

    def pull_requests(self, app_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM pull_requests"
        parameters: tuple[Any, ...] = ()
        if app_id:
            query += " WHERE app_id = ?"
            parameters = (app_id,)
        query += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def pull_request(self, pull_request_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM pull_requests WHERE id = ?", (pull_request_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"PR branch {pull_request_id} does not exist")
        return dict(row)

    def set_pull_request_opened(self, pull_request_id: str, number: int, url: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE pull_requests SET status = 'opened', pr_number = ?, pr_url = ? WHERE id = ?",
                (number, url, pull_request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"PR branch {pull_request_id} does not exist")

    def add_activity(self, activity: dict[str, Any]) -> None:
        fields = (
            "run_id", "app_id", "agent_id", "agent_name", "stage", "status",
            "input_summary", "output_summary", "duration_ms", "created_at",
        )
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO activity({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                tuple(activity[field] for field in fields),
            )

    def activities(self, limit: int = 100, app_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM activity"
        parameters: tuple[Any, ...]
        if app_id:
            query += " WHERE app_id = ?"
            parameters = (app_id, limit)
        else:
            parameters = (limit,)
        query += " ORDER BY id DESC LIMIT ?"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]
