from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.30 / 1_000_000, "output": 2.50 / 1_000_000},
    "gemini-3-flash-preview": {"input": 0.50 / 1_000_000, "output": 3.00 / 1_000_000},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return (0.0, 0.0)
    return (input_tokens * pricing["input"], output_tokens * pricing["output"])


@dataclass
class AgentRun:
    id: str = field(default_factory=lambda: str(uuid4()))
    agent_name: str = ""
    model: str = ""
    parent_run_id: str | None = None
    handoff_from_agent: str | None = None
    structured_output_type: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    turn_count: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


@dataclass
class LLMCall:
    id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    agent_name: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    latency_ms: float = 0.0
    started_at: str | None = None
    ended_at: str | None = None


@dataclass
class ToolCall:
    id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    agent_name: str = ""
    tool_name: str = ""
    arguments: str = ""
    result: str | None = None
    error: str | None = None
    latency_ms: float = 0.0
    started_at: str | None = None
    ended_at: str | None = None


@dataclass
class HandoffRecord:
    id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    from_agent: str = ""
    to_agent: str = ""
    timestamp: str | None = None
