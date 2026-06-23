from datetime import datetime, timezone
from typing import Any

from agents import Agent, ModelResponse, Tool
from agents.lifecycle import (
    AgentHookContext,
    RunContextWrapper,
    RunHooksBase,
)
from agents.items import TResponseInputItem

from openai_agent_tracker.models import AgentRun, HandoffRecord, LLMCall, ToolCall
from openai_agent_tracker.store import TrackerStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrackingHooks(RunHooksBase[Any, Agent[Any]]):
    def __init__(self, store: TrackerStore):
        self._store = store
        self._run_stack: list[str] = []
        self._current_run_id: str | None = None
        self._tokens_by_run: dict[str, dict[str, float]] = {}
        self._turn_count_by_run: dict[str, int] = {}

    @property
    def current_run_id(self) -> str | None:
        return self._current_run_id

    async def on_agent_start(
        self, context: AgentHookContext[Any], agent: Agent[Any]
    ) -> None:
        try:
            parent_id = self._current_run_id
            handoff_from = None
            if self._run_stack:
                handoff_from = self._run_stack[-1]

            model_name = (
                getattr(agent.model, "_model_name", None)
                or getattr(agent.model, "model", None)
                or (str(agent.model) if agent.model else "unknown")
            )
            structured_name = None
            if agent.output_type is not None and agent.output_type is not str:
                try:
                    structured_name = (
                        agent.output_type.__name__
                        if isinstance(agent.output_type, type)
                        else agent.output_type.name
                    )
                    if callable(structured_name):
                        structured_name = structured_name()
                except Exception:
                    structured_name = None

            run = AgentRun(
                agent_name=agent.name,
                model=model_name,
                parent_run_id=parent_id,
                handoff_from_agent=handoff_from,
                structured_output_type=structured_name,
                started_at=_now(),
            )
            self._store.record_run_start(run)

            self._run_stack.append(agent.name)
            self._current_run_id = run.id
            self._tokens_by_run[run.id] = {"input": 0, "output": 0, "total": 0, "input_cost": 0.0, "output_cost": 0.0}
            self._turn_count_by_run[run.id] = 0
        except Exception:
            pass

    async def on_agent_end(
        self,
        context: AgentHookContext[Any],
        agent: Agent[Any],
        output: Any,
    ) -> None:
        if not self._current_run_id:
            return

        rid = self._current_run_id
        tokens = self._tokens_by_run.get(rid, {"input": 0, "output": 0, "total": 0, "input_cost": 0.0, "output_cost": 0.0})
        turns = self._turn_count_by_run.get(rid, 0)

        existing = self._store.get_run(rid)
        if existing:
            existing.input_tokens = int(tokens["input"])
            existing.output_tokens = int(tokens["output"])
            existing.total_tokens = int(tokens["total"])
            existing.input_cost = tokens.get("input_cost", 0.0)
            existing.output_cost = tokens.get("output_cost", 0.0)
            existing.total_cost = tokens.get("input_cost", 0.0) + tokens.get("output_cost", 0.0)
            existing.turn_count = turns

            ended = _now()
            if existing.started_at:
                try:
                    start = datetime.fromisoformat(existing.started_at)
                    end = datetime.fromisoformat(ended)
                    existing.latency_ms = (end - start).total_seconds() * 1000
                except Exception:
                    pass
            existing.ended_at = ended

            self._store._update_run(existing)

        if self._run_stack:
            self._run_stack.pop()
        self._current_run_id = self._run_stack[-1] if self._run_stack else None

    async def on_llm_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        pass

    async def on_llm_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        response: ModelResponse,
    ) -> None:
        if not self._current_run_id:
            return

        rid = self._current_run_id
        model_name = (
            getattr(agent.model, "_model_name", None)
            or getattr(agent.model, "model", None)
            or (str(agent.model) if agent.model else "unknown")
        )
        inp = response.usage.input_tokens if response.usage else 0
        out = response.usage.output_tokens if response.usage else 0
        total = response.usage.total_tokens if response.usage else 0
        inp_cost, out_cost = self._store.compute_cost(model_name, inp, out)

        if rid in self._tokens_by_run:
            self._tokens_by_run[rid]["input"] += inp
            self._tokens_by_run[rid]["output"] += out
            self._tokens_by_run[rid]["total"] += total
            self._tokens_by_run[rid]["input_cost"] = (
                self._tokens_by_run[rid].get("input_cost", 0) + inp_cost
            )
            self._tokens_by_run[rid]["output_cost"] = (
                self._tokens_by_run[rid].get("output_cost", 0) + out_cost
            )
        if rid in self._turn_count_by_run:
            self._turn_count_by_run[rid] += 1

        call = LLMCall(
            run_id=rid,
            agent_name=agent.name,
            model=model_name,
            input_tokens=inp,
            output_tokens=out,
            total_tokens=total,
            input_cost=inp_cost,
            output_cost=out_cost,
            total_cost=inp_cost + out_cost,
            started_at=_now(),
            ended_at=_now(),
        )
        self._store.record_llm_call(call)

    async def on_tool_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        tool: Tool,
    ) -> None:
        tool_name = (
            tool.name if hasattr(tool, "name")
            else getattr(tool, "_name", str(tool))
        )
        args = ""
        if hasattr(context, "tool_arguments") and context.tool_arguments:
            args = str(context.tool_arguments)

        call = ToolCall(
            run_id=self._current_run_id or "",
            agent_name=agent.name,
            tool_name=tool_name,
            arguments=args,
            started_at=_now(),
        )
        context._tracking_tool_call = call

    async def on_tool_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        tool: Tool,
        result: object,
    ) -> None:
        call: ToolCall | None = getattr(context, "_tracking_tool_call", None)
        if call:
            call.ended_at = _now()
            if call.started_at:
                try:
                    start = datetime.fromisoformat(call.started_at)
                    end = datetime.fromisoformat(call.ended_at)
                    call.latency_ms = (end - start).total_seconds() * 1000
                except Exception:
                    pass
            call.result = str(result) if result is not None else None
            self._store.record_tool_call(call)

    async def on_handoff(
        self,
        context: RunContextWrapper[Any],
        from_agent: Agent[Any],
        to_agent: Agent[Any],
    ) -> None:
        if self._current_run_id:
            h = HandoffRecord(
                run_id=self._current_run_id,
                from_agent=from_agent.name,
                to_agent=to_agent.name,
                timestamp=_now(),
            )
            self._store.record_handoff(h)
