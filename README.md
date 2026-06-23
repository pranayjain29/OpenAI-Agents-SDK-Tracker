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
│             │  SQLiteStore (impl) — 5 tables, auto-migrate │
│             │  get_stats(), get_agents(), get_runs() ...   │
└─────────────────────────┬──────────────────────────────────┘
                          ▲
                          │ queries
┌────────────────────────────────────────────────────────────┐
│  dashboard.py  │  FastAPI app served at / or /tracking     │
│                  │  Chart.js graphs, paginated tables      │
│                  │  Pricing UI, cost recalculation         │
│                  │  Runs standalone OR mounted in your app │
└────────────────────────────────────────────────────────────┘
```

## Quick start

```bash
# pip
pip install git+https://github.com/pranayjain29/OpenAI-Agents-SDK-Tracker.git

# uv
uv add "openai-agent-tracker @ git+https://github.com/pranayjain29/OpenAI-Agents-SDK-Tracker.git"
```

```python
from openai_agent_tracker import AgentTracker

tracker = AgentTracker()
result = await Runner.run(agent, input, hooks=tracker.hooks)
```

## Dashboard

### Standalone

```bash
python -m openai_agent_tracker.dashboard
# or via uv:
uv run python -m openai_agent_tracker.dashboard
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

## Routes

| Path | Description |
|---|---|
| `/` | Dashboard — stats, charts, agents table, recent runs |
| `/runs` | Paginated run list (filterable by agent) |
| `/run/{id}` | Run detail — meta, tool calls, LLM calls, handoffs |
| `/pricing` | Inline-editable pricing table with Save/Reset/Add |
| `POST /api/pricing` | Upsert pricing override |
| `DELETE /api/pricing/{model}` | Remove pricing override |

## Pricing

Costs are computed client-side from built-in defaults. Users can override pricing for any model via the `/pricing` dashboard UI — overrides are stored in SQLite and survive restarts. When pricing changes, all stored costs are automatically recalculated.

Built-in defaults:

| Model | Input | Output |
|---|---|---|
| `gemini-2.5-flash` | $0.30 / 1M tokens | $2.50 / 1M tokens |
| `gemini-3-flash-preview` | $0.50 / 1M tokens | $3.00 / 1M tokens |

Add more in `openai_agent_tracker/models.py` → `MODEL_PRICING` dict.

## Files

| File | Role |
|---|---|
| `openai_agent_tracker/__init__.py` | `AgentTracker` class |
| `openai_agent_tracker/models.py` | Dataclasses + pricing lookup |
| `openai_agent_tracker/hooks.py` | `TrackingHooks` — captures lifecycle events |
| `openai_agent_tracker/store.py` | `TrackerStore` interface + `SQLiteStore` |
| `openai_agent_tracker/dashboard.py` | FastAPI app with all routes |
| `openai_agent_tracker/templates/` | 4 Jinja2 templates |
| `openai_agent_tracker/static/style.css` | Dashboard styling |

## Key design decisions

- **`RunHooksBase` over monkey-patching** — the SDK provides clean lifecycle hooks. No fragile internals to patch.
- **Sync SQLite, not async** — writes are fast local inserts. Blocking thread pool handles them fine. Zero extra dependencies.
- **`TrackerStore` interface** — swap `SQLiteStore` for `PostgresStore` later without changing hooks or dashboard.
- **Cost columns via `ALTER TABLE` migration** — existing `tracking.db` files from before costs were added auto-upgrade on next startup.
- **`root_path` in templates** — the dashboard works both standalone (`/`) and mounted at a prefix (`/tracking`) because every link uses `{{ root }}` derived from `request.scope.root_path`.
- **Pricing overrides in SQLite** — no JSON files or config changes needed. Update prices from the dashboard UI, and all stored costs are recalculated automatically.

## Deployment (Railway Volume)

SQLite data is wiped on every Railway deploy unless you attach a persistent volume.

1. Go to your Railway service → **Volumes** → **Add Volume**
2. Mount it at `/data`
3. Set `TRACKING_DB_PATH=/data/tracking.db`

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TRACKING_DB_PATH` | `tracking.db` | SQLite file path |
| `TRACKING_PORT` | `3001` | Port for standalone dashboard |

## PostgreSQL (future)

Swap storage by implementing `TrackerStore`:

```python
from openai_agent_tracker.store import TrackerStore

class PostgresStore(TrackerStore):
    def record_run_start(self, run): ...
    # implement all methods
```
