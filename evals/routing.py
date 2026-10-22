"""Routing evals with Pydantic Evals: the demo set (intent and handling) and a Banking77 intent sample."""

import csv
import json
import random
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected, Evaluator, EvaluatorContext
from pydantic_evals.reporting import RenderValueConfig

from request_routing.agents.router import LIMITS, router
from request_routing.config import BANKING77_TEST, DEMO_MESSAGES
from request_routing.schemas import Outcome, Session


class Expected(BaseModel):
    intent: str
    handling: str


@dataclass
class IntentMatches(Evaluator[str, Outcome, Expected]):
    def evaluate(self, ctx: EvaluatorContext[str, Outcome, Expected]) -> bool:
        return ctx.output.intent == ctx.expected_output.intent


@dataclass
class HandlingMatches(Evaluator[str, Outcome, Expected]):
    def evaluate(self, ctx: EvaluatorContext[str, Outcome, Expected]) -> bool:
        return ctx.output.handling == ctx.expected_output.handling


async def route(message: str) -> Outcome:
    """The task under evaluation: one message through the router, with bank confirmations approved."""
    session = Session(customer_id="eval-customer", confirm=lambda call: True)
    result = await router.run(message, deps=session, usage_limits=LIMITS)
    return result.output


async def route_intent(message: str) -> str:
    return (await route(message)).intent


def _demo_items() -> list[dict]:
    return json.loads(DEMO_MESSAGES.read_text(encoding="utf-8"))


async def run_demo(concurrency: int, rows: list[int] | None) -> None:
    """Run the demo messages, optionally only the given Banking77 rows (in that order)."""
    items = {item["row"]: item for item in _demo_items()}
    dataset = Dataset(
        name="demo",
        cases=[
            Case(
                name=f"row {item['row']}",
                inputs=item["text"],
                expected_output=Expected(intent=item["intent"], handling=item["expected_handling"]),
            )
            for item in (items[row] for row in rows or items)
        ],
        evaluators=[IntentMatches(), HandlingMatches()],
    )
    async with router:  # one bank MCP server for all cases
        report = await dataset.evaluate(route, max_concurrency=concurrency)
    report.print(include_input=True, include_output=True, output_config=RenderValueConfig(value_formatter=_summary))


def _summary(outcome: Outcome) -> str:
    lines = [f"{outcome.handling} · {outcome.intent}"]
    lines += [f"{action.operation} → {action.result['status']}" for action in outcome.actions]
    if outcome.handoff:
        lines.append(f"{outcome.handoff.ticket_id} · {outcome.handoff.priority} · {outcome.handoff.reason}")
    if outcome.reply:
        lines.append(f"“{outcome.reply}”")
    return "\n".join(lines)


async def run_banking77(sample_size: int, seed: int, concurrency: int) -> None:
    """Intent accuracy on a seeded test-split sample. Demo rows are excluded: they shaped the prompts."""
    demo_rows = {item["row"] for item in _demo_items()}
    with BANKING77_TEST.open(newline="", encoding="utf-8") as f:
        rows = [row for i, row in enumerate(csv.DictReader(f)) if i not in demo_rows]
    sample = random.Random(seed).sample(rows, sample_size)
    dataset = Dataset(
        name="banking77-intent",
        cases=[Case(inputs=row["text"], expected_output=row["category"]) for row in sample],
        evaluators=[EqualsExpected()],
    )
    async with router:
        report = await dataset.evaluate(route_intent, max_concurrency=concurrency)
    report.print(include_input=True, include_output=True, include_expected_output=True)
