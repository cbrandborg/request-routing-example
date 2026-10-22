"""Around every router run: a human fallback on failure, then delivering and logging the outcome.

The handoff queue and the outcome log are local JSONL files in this prototype.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from opentelemetry import trace
from pydantic_ai import RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.capabilities.abstract import WrapRunHandler
from pydantic_ai.run import AgentRunResult

from request_routing.config import HANDOFF_QUEUE, OUTCOMES_LOG
from request_routing.schemas import Handoff, Outcome, Session

outcome_handling = Hooks()


@outcome_handling.on.run_error
async def fall_back_to_human(ctx: RunContext[Session], *, error: BaseException) -> AgentRunResult:
    """Any failure (usage limits, retries exhausted, API errors) becomes a human handoff."""
    handoff = Handoff(
        priority="normal",
        reason="system_fallback",
        summary=f"Automatic handling failed ({type(error).__name__}: {error}). Please handle manually.",
        customer_message=str(ctx.prompt),
    )
    return AgentRunResult(output=Outcome(handling="human_handoff", intent="other", confidence=0, handoff=handoff))


@outcome_handling.on.run
async def deliver_and_log(ctx: RunContext[Session], *, handler: WrapRunHandler) -> AgentRunResult:
    """Start each message with a clean record, then attach what the tools did, deliver and log."""
    session = ctx.deps
    session.articles_read.clear()
    session.actions.clear()
    session.declined_actions.clear()
    started = perf_counter()

    result = await handler()

    outcome: Outcome = result.output
    outcome.actions = list(session.actions)
    outcome.declined_actions = list(session.declined_actions)
    if outcome.handoff:
        _append(
            HANDOFF_QUEUE, {"run_id": ctx.run_id, "customer_id": session.customer_id, **outcome.handoff.model_dump()}
        )
    _append(
        OUTCOMES_LOG,
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": ctx.run_id,
            "trace_id": f"{trace.get_current_span().get_span_context().trace_id:032x}",
            "message": str(ctx.prompt),
            "seconds": round(perf_counter() - started, 2),
            "requests": ctx.usage.requests,
            "tool_calls": ctx.usage.tool_calls,
            "input_tokens": ctx.usage.input_tokens,
            "output_tokens": ctx.usage.output_tokens,
            "articles_read": sorted(session.articles_read),
            **outcome.model_dump(mode="json"),
        },
    )
    return result


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
