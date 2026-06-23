import json
import os

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai_agent_tracker.store import SQLiteStore

HERE = os.path.dirname(os.path.abspath(__file__))


def create_dashboard_app(
    store: SQLiteStore,
    templates_dir: str | None = None,
    static_dir: str | None = None,
) -> FastAPI:
    templates = Jinja2Templates(
        directory=templates_dir or os.path.join(HERE, "templates")
    )

    app = FastAPI(title="Agent Tracker")

    app.mount(
        "/static",
        StaticFiles(directory=static_dir or os.path.join(HERE, "static")),
        name="tracking_static",
    )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        root = request.scope.get("root_path", "")
        stats = store.get_stats()
        agents = store.get_agents()
        runs = store.get_runs(limit=20)
        latencies = store.get_recent_latencies(limit=50)
        token_data = store.get_token_usage_over_time(limit=50)
        cost_data = store.get_recent_costs(limit=50)
        tool_data = store.get_tool_usage_stats()
        hourly_data = store.get_hourly_runs()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "root": root,
                "stats": stats,
                "agents": agents,
                "runs": runs,
                "latencies": latencies,
                "latencies_json": json.dumps(latencies),
                "token_data": token_data,
                "token_data_json": json.dumps(token_data),
                "cost_data": cost_data,
                "cost_data_json": json.dumps(cost_data),
                "tool_data": tool_data,
                "tool_data_json": json.dumps(tool_data),
                "hourly_data": hourly_data,
                "hourly_data_json": json.dumps(hourly_data),
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    async def runs_list(
        request: Request,
        page: int = Query(1, ge=1),
        agent: str | None = Query(None),
    ):
        root = request.scope.get("root_path", "")
        limit = 50
        offset = (page - 1) * limit
        runs = store.get_runs(limit=limit, offset=offset, agent=agent)
        total = store.get_total_runs(agent=agent)
        total_pages = max(1, (total + limit - 1) // limit)

        all_agents_raw = store.get_agents()
        all_agents = [a["agent_name"] for a in all_agents_raw]

        return templates.TemplateResponse(
            request=request,
            name="runs.html",
            context={
                "root": root,
                "runs": runs,
                "page": page,
                "total_pages": total_pages,
                "total_runs": total,
                "selected_agent": agent or "",
                "all_agents": all_agents,
            },
        )

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str):
        root = request.scope.get("root_path", "")
        run = store.get_run(run_id)
        if not run:
            return HTMLResponse("Run not found", status_code=404)
        llm_calls = store.get_llm_calls(run_id)
        tool_calls = store.get_tool_calls(run_id)
        handoffs = store.get_handoffs(run_id)
        return templates.TemplateResponse(
            request=request,
            name="run_detail.html",
            context={
                "root": root,
                "run": run,
                "llm_calls": llm_calls,
                "tool_calls": tool_calls,
                "handoffs": handoffs,
            },
        )

    return app


if __name__ == "__main__":
    import uvicorn

    db_path = os.getenv("TRACKING_DB_PATH", "tracking.db")
    store = SQLiteStore(db_path)
    app = create_dashboard_app(store)
    port = int(os.getenv("TRACKING_PORT", "3001"))
    print(f"Agent Tracker Dashboard -> http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
