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
                """
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

    def add_proposal(self, proposal: dict[str, Any]) -> None:
        fields = (
            "id", "app_id", "observation_id", "hypothesis", "success_metric", "risk",
            "branch", "sandbox_path", "base_commit", "proposed_commit", "diff",
            "validation", "status", "created_at",
        )
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO proposals({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                tuple(proposal[field] for field in fields),
            )

    def proposals(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        if not row:
            raise ValueError(f"Proposal {proposal_id} does not exist")
        return dict(row)

    def set_proposal_status(self, proposal_id: str, status: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id)
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Proposal {proposal_id} does not exist")

