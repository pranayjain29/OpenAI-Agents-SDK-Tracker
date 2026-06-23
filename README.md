# OpenAI Agent Tracker

Self-contained agent observability for the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) — no external services, no cloud vendor lock-in. Drop it into any project and get a real-time dashboard with run history, token usage, cost, latency, tool calls, and handoff traces.

```text
┌────────────────────────────────────────────────────────────┐
│                    your code                                │
│  tracker = AgentTracker()                                  │
│  await Runner.run(agent, input, hooks=tracker.hooks)      │
└─────────────────────┬──────────────────────────────────────┘
                      │ lifecycle events
                      ▼
┌────────────────────────────────────────────────────────────┐
│  openai_agent_tracker/  │  hooks.py  │  TrackingHooks      │
│                         │  on_agent_start/end → AgentRun   │
│                         │  on_llm_start/end   → LLMCall    │
│                         │  on_tool_start/end  → ToolCall   │
│                         │  on_handoff         → Handoff    │
└─────────────────────────┴────────────────┬─────────────────┘
                                           │ record_*()
                                           ▼
┌────────────────────────────────────────────────────────────┐
│  store.py  │  TrackerStore (interface)                     │
│             │  SQLiteStore (impl) — 4 tables, auto-migrate │
│             │  get_stats(), get_agents(), get_runs() ...   │
└─────────────────────────┬──────────────────────────────────┘
                          ▲
                          │ queries
┌────────────────────────────────────────────────────────────┐
│  dashboard.py  │  FastAPI app served at / or /tracking     │
│                  │  Chart.js graphs, paginated tables      │
│                  │  Runs standalone OR mounted in your app │
└────────────────────────────────────────────────────────────┘
```

## Quick start

```bash
pip install git+https://github.com/pranayjain29/OpenAI-Agents-SDK-Tracker.git
```

```python
from openai_agent_tracker import AgentTracker

tracker = AgentTracker()
result = await Runner.run(agent, input, hooks=tracker.hooks)
```

That's it. `tracking.db` is created in the current directory. Open the dashboard to see everything.

### Error tracking

```python
try:
    result = await Runner.run(agent, input, hooks=tracker.hooks)
except Exception as e:
    tracker.record_error(str(e))
    raise
```

## Dashboard

### Standalone

```bash
python -m openai_agent_tracker.dashboard
```

Open `http://localhost:3001`.

### Mounted in your FastAPI app

```python
from fastapi import FastAPI
from openai_agent_tracker.store import SQLiteStore
from openai_agent_tracker.dashboard import create_dashboard_app

store = SQLiteStore("tracking.db")
dashboard = create_dashboard_app(store)

app = FastAPI()
app.mount("/tracking", dashboard)
```

Open `http://localhost:8000/tracking`.

## Files

| File | Role |
|---|---|
| `openai_agent_tracker/__init__.py` | `AgentTracker` class — the only import you need |
| `openai_agent_tracker/models.py` | Dataclasses (`AgentRun`, `LLMCall`, `ToolCall`, `HandoffRecord`) + pricing lookup |
| `openai_agent_tracker/hooks.py` | `TrackingHooks(RunHooksBase)` — captures every lifecycle event |
| `openai_agent_tracker/store.py` | `TrackerStore` abstract interface + `SQLiteStore` implementation |
| `openai_agent_tracker/dashboard.py` | FastAPI app with `/`, `/runs`, `/run/{id}` routes |
| `openai_agent_tracker/templates/` | 3 Jinja2 templates (index, runs list, run detail) |
| `openai_agent_tracker/static/style.css` | Dark-theme dashboard styling |

## Pricing

Costs are computed client-side from this table (add models as needed):

| Model | Input | Output |
|---|---|---|
| `gemini-2.5-flash` | $0.30 / 1M tokens | $2.50 / 1M tokens |
| `gemini-3-flash-preview` | $0.50 / 1M tokens | $3.00 / 1M tokens |
| anything else | $0 | $0 |

Add new models in `openai_agent_tracker/models.py` → `MODEL_PRICING` dict.

## Key design decisions

- **`RunHooksBase` over monkey-patching** — the SDK provides clean lifecycle hooks. No fragile internals to patch.
- **Sync SQLite, not async** — writes are fast local inserts. Blocking thread pool handles them fine. Zero extra dependencies.
- **`TrackerStore` interface** — swap `SQLiteStore` for `PostgresStore` later without changing hooks or dashboard.
- **Cost columns via `ALTER TABLE` migration** — existing `tracking.db` files from before costs were added auto-upgrade on next startup.
- **`root_path` in templates** — the dashboard works both standalone (`/`) and mounted at a prefix (`/tracking`) because every link uses `{{ root }}` derived from `request.scope.root_path`.

## Deployment (Railway Volume)

SQLite stores data in a file. Every Railway deploy creates a fresh filesystem, so data is wiped unless you attach a persistent volume.

1. In your Railway dashboard, go to your service → **Volumes** → **Add Volume**
2. Mount it at `/data` (default)
3. Set environment variable: `TRACKING_DB_PATH=/data/tracking.db`

Data now survives all redeploys.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TRACKING_DB_PATH` | `tracking.db` | SQLite file path (local or `/data/tracking.db` on Railway) |
| `TRACKING_PORT` | `3001` | Port for standalone dashboard |

## PostgreSQL (future)

The `TrackerStore` interface makes swapping trivial:

```python
from openai_agent_tracker.store import TrackerStore

class PostgresStore(TrackerStore):
    def record_run_start(self, run): ...
    # implement all methods

AgentTracker(store=PostgresStore("postgresql://..."))
```

The hooks and dashboard never reference `SQLiteStore` directly — they go through the interface.
