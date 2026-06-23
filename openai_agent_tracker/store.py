import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai_agent_tracker.models import AgentRun, HandoffRecord, LLMCall, ToolCall


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrackerStore:
    def record_run_start(self, run: AgentRun) -> None: ...
    def record_run_end(self, run_id: str) -> None: ...
    def record_run_error(self, run_id: str, error: str) -> None: ...
    def record_llm_call(self, call: LLMCall) -> None: ...
    def record_tool_call(self, call: ToolCall) -> None: ...
    def record_handoff(self, h: HandoffRecord) -> None: ...
    def get_runs(self, limit: int = 50, offset: int = 0, agent: str | None = None) -> list[AgentRun]: ...
    def get_run(self, run_id: str) -> AgentRun | None: ...
    def get_llm_calls(self, run_id: str) -> list[LLMCall]: ...
    def get_tool_calls(self, run_id: str) -> list[ToolCall]: ...
    def get_handoffs(self, run_id: str) -> list[HandoffRecord]: ...
    def get_agents(self) -> list[dict[str, Any]]: ...
    def get_stats(self) -> dict[str, Any]: ...
    def get_total_runs(self, agent: str | None = None) -> int: ...
    def get_recent_costs(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def get_recent_latencies(self, limit: int = 100) -> list[dict[str, Any]]: ...
    def get_token_usage_over_time(self, limit: int = 100) -> list[dict[str, Any]]: ...
    def get_hourly_runs(self, hours: int = 24) -> list[dict[str, Any]]: ...
    def get_tool_usage_stats(self) -> list[dict[str, Any]]: ...


class SQLiteStore(TrackerStore):
    def __init__(self, db_path: str = "tracking.db"):
        self._path = str(Path(db_path).resolve())
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    parent_run_id TEXT,
                    handoff_from_agent TEXT,
                    structured_output_type TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    input_cost REAL DEFAULT 0.0,
                    output_cost REAL DEFAULT 0.0,
                    total_cost REAL DEFAULT 0.0,
                    turn_count INTEGER DEFAULT 0,
                    latency_ms REAL DEFAULT 0,
                    error TEXT,
                    started_at TEXT,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id),
                    agent_name TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    input_cost REAL DEFAULT 0.0,
                    output_cost REAL DEFAULT 0.0,
                    total_cost REAL DEFAULT 0.0,
                    latency_ms REAL DEFAULT 0,
                    started_at TEXT,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id),
                    agent_name TEXT DEFAULT '',
                    tool_name TEXT DEFAULT '',
                    arguments TEXT DEFAULT '',
                    result TEXT,
                    error TEXT,
                    latency_ms REAL DEFAULT 0,
                    started_at TEXT,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS handoffs (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id),
                    from_agent TEXT DEFAULT '',
                    to_agent TEXT DEFAULT '',
                    timestamp TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_llm_run ON llm_calls(run_id);
                CREATE INDEX IF NOT EXISTS idx_tool_run ON tool_calls(run_id);
                CREATE INDEX IF NOT EXISTS idx_handoff_run ON handoffs(run_id);
                CREATE INDEX IF NOT EXISTS idx_runs_agent ON agent_runs(agent_name);
                CREATE INDEX IF NOT EXISTS idx_runs_started ON agent_runs(started_at);
            """)
            for table, cols in [
                ("agent_runs", ["input_cost", "output_cost", "total_cost"]),
                ("llm_calls", ["input_cost", "output_cost", "total_cost"]),
            ]:
                existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col in cols:
                    if col not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL DEFAULT 0.0")

    def record_run_start(self, run: AgentRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO agent_runs
                   (id, agent_name, model, parent_run_id, handoff_from_agent,
                    structured_output_type, input_tokens, output_tokens,
                    total_tokens, input_cost, output_cost, total_cost,
                    turn_count, latency_ms, error,
                    started_at, ended_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run.id, run.agent_name, run.model, run.parent_run_id,
                    run.handoff_from_agent, run.structured_output_type,
                    run.input_tokens, run.output_tokens, run.total_tokens,
                    run.input_cost, run.output_cost, run.total_cost,
                    run.turn_count, run.latency_ms, run.error,
                    run.started_at or _now(), run.ended_at,
                ),
            )

    def record_run_end(self, run_id: str) -> None:
        ended = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT started_at FROM agent_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if row and row["started_at"]:
                try:
                    start = datetime.fromisoformat(row["started_at"])
                    end = datetime.fromisoformat(ended)
                    latency = (end - start).total_seconds() * 1000
                except Exception:
                    latency = 0
            else:
                latency = 0
            conn.execute(
                "UPDATE agent_runs SET ended_at=?, latency_ms=? WHERE id=?",
                (ended, latency, run_id),
            )

    def record_run_error(self, run_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_runs SET error=? WHERE id=?",
                (error, run_id),
            )

    def _update_run(self, run: AgentRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE agent_runs
                   SET input_tokens=?, output_tokens=?, total_tokens=?,
                       input_cost=?, output_cost=?, total_cost=?,
                       turn_count=?, latency_ms=?, ended_at=?, error=?
                   WHERE id=?""",
                (
                    run.input_tokens, run.output_tokens, run.total_tokens,
                    run.input_cost, run.output_cost, run.total_cost,
                    run.turn_count, run.latency_ms, run.ended_at, run.error,
                    run.id,
                ),
            )

    def record_llm_call(self, call: LLMCall) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO llm_calls
                   (id, run_id, agent_name, model, input_tokens, output_tokens,
                    total_tokens, input_cost, output_cost, total_cost,
                    latency_ms, started_at, ended_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    call.id, call.run_id, call.agent_name, call.model,
                    call.input_tokens, call.output_tokens, call.total_tokens,
                    call.input_cost, call.output_cost, call.total_cost,
                    call.latency_ms, call.started_at or _now(),
                    call.ended_at or _now(),
                ),
            )

    def record_tool_call(self, call: ToolCall) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO tool_calls
                   (id, run_id, agent_name, tool_name, arguments, result,
                    error, latency_ms, started_at, ended_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    call.id, call.run_id, call.agent_name, call.tool_name,
                    call.arguments, call.result, call.error, call.latency_ms,
                    call.started_at or _now(), call.ended_at or _now(),
                ),
            )

    def record_handoff(self, h: HandoffRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO handoffs
                   (id, run_id, from_agent, to_agent, timestamp)
                   VALUES (?,?,?,?,?)""",
                (h.id, h.run_id, h.from_agent, h.to_agent, h.timestamp or _now()),
            )

    def get_runs(
        self, limit: int = 50, offset: int = 0, agent: str | None = None
    ) -> list[AgentRun]:
        with self._connect() as conn:
            if agent:
                rows = conn.execute(
                    "SELECT * FROM agent_runs WHERE agent_name=? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (agent, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [AgentRun(**dict(r)) for r in rows]

    def get_run(self, run_id: str) -> AgentRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE id=?", (run_id,)
            ).fetchone()
            return AgentRun(**dict(row)) if row else None

    def get_llm_calls(self, run_id: str) -> list[LLMCall]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_calls WHERE run_id=? ORDER BY started_at",
                (run_id,),
            ).fetchall()
            return [LLMCall(**dict(r)) for r in rows]

    def get_tool_calls(self, run_id: str) -> list[ToolCall]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE run_id=? ORDER BY started_at",
                (run_id,),
            ).fetchall()
            return [ToolCall(**dict(r)) for r in rows]

    def get_handoffs(self, run_id: str) -> list[HandoffRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM handoffs WHERE run_id=? ORDER BY timestamp",
                (run_id,),
            ).fetchall()
            return [HandoffRecord(**dict(r)) for r in rows]

    def get_agents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT
                    agent_name,
                    COUNT(*) as total_runs,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(total_cost), 0) as total_cost,
                    COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
                    COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END), 0) as error_count,
                    COALESCE(AVG(turn_count), 0) as avg_turns
                FROM agent_runs
                GROUP BY agent_name
                ORDER BY total_runs DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM agent_runs").fetchone()["c"]
            tokens = conn.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) as t FROM agent_runs"
            ).fetchone()["t"]
            cost = conn.execute(
                "SELECT COALESCE(SUM(total_cost), 0) as c FROM agent_runs"
            ).fetchone()["c"]
            avg_lat = conn.execute(
                "SELECT COALESCE(AVG(latency_ms), 0) as a FROM agent_runs"
            ).fetchone()["a"]
            errors = conn.execute(
                "SELECT COUNT(*) as c FROM agent_runs WHERE error IS NOT NULL"
            ).fetchone()["c"]
            today = _now()[:10]
            today_runs = conn.execute(
                "SELECT COUNT(*) as c FROM agent_runs WHERE started_at >= ?",
                (today,),
            ).fetchone()["c"]
            agents_count = conn.execute(
                "SELECT COUNT(DISTINCT agent_name) as c FROM agent_runs"
            ).fetchone()["c"]
            return {
                "total_runs": total,
                "total_tokens": tokens,
                "total_cost": round(cost, 6),
                "avg_latency_ms": round(avg_lat, 1),
                "error_count": errors,
                "error_rate": round(errors / total * 100, 1) if total else 0,
                "today_runs": today_runs,
                "unique_agents": agents_count,
            }

    def get_total_runs(self, agent: str | None = None) -> int:
        with self._connect() as conn:
            if agent:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM agent_runs WHERE agent_name=?",
                    (agent,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM agent_runs"
                ).fetchone()
            return row["c"]

    def get_recent_costs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT agent_name, input_cost, output_cost, total_cost, started_at
                   FROM agent_runs ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_recent_latencies(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT agent_name, latency_ms, started_at, error IS NOT NULL as is_error
                   FROM agent_runs ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_token_usage_over_time(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT agent_name, total_tokens, input_tokens, output_tokens,
                          input_cost, output_cost, total_cost, started_at
                   FROM agent_runs ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_hourly_runs(self, hours: int = 24) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT
                    substr(started_at, 12, 5) as hour_slot,
                    COUNT(*) as count,
                    COALESCE(AVG(latency_ms), 0) as avg_latency
                FROM agent_runs
                WHERE started_at >= datetime('now', ?)
                GROUP BY hour_slot
                ORDER BY hour_slot
            """, (f"-{hours} hours",)).fetchall()
            return [dict(r) for r in rows]

    def get_tool_usage_stats(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT tool_name, COUNT(*) as count, COALESCE(AVG(latency_ms), 0) as avg_latency
                FROM tool_calls
                GROUP BY tool_name
                ORDER BY count DESC
            """).fetchall()
            return [dict(r) for r in rows]
