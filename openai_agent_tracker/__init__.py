import os

from openai_agent_tracker.hooks import TrackingHooks
from openai_agent_tracker.store import SQLiteStore, TrackerStore


def _resolve_db_path(db_path: str | None = None) -> str:
    if db_path is not None:
        return db_path
    return os.getenv("TRACKING_DB_PATH", "tracking.db")


class AgentTracker:
    """Plug-and-play agent tracking.

    Usage:
        tracker = AgentTracker()
        result = await Runner.run(agent, input, hooks=tracker.hooks)

    The database path is resolved in this order:
      1. Explicit ``db_path`` argument
      2. ``TRACKING_DB_PATH`` environment variable
      3. ``tracking.db`` in the current working directory
    """

    def __init__(self, db_path: str | None = None):
        resolved = _resolve_db_path(db_path)
        self.store: TrackerStore = SQLiteStore(resolved)
        self.hooks = TrackingHooks(self.store)

    def record_error(self, error: str) -> None:
        """Record an error on the currently active run (if any)."""
        rid = self.hooks.current_run_id
        if rid:
            self.store.record_run_error(rid, error)
