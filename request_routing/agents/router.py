"""Router agent: classifies a customer message and finishes with exactly one outcome.

Tools gather what the router needs (FAQ specialist, bank actions). Output functions end the run; each checks
the router's claims against what the tools did. Capabilities handle what happens around the run.
Usage: `await router.run(message, deps=Session(...), usage_limits=LIMITS)`.
"""

import re
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from request_routing.agents.capabilities.confirmation import customer_confirmation
from request_routing.agents.capabilities.outcomes import outcome_handling
from request_routing.agents.faq import faq_agent
from request_routing.agents.toolsets.bank import bank_toolset
from request_routing.config import MODEL
from request_routing.schemas import Confidence, EscalationReason, FaqAnswer, Handoff, Intent, Outcome, Priority, Session
from request_routing.taxonomy import DOMAINS, OTHER

LIMITS = UsageLimits(request_limit=15, tool_calls_limit=10)
"""Per message, across the router and the FAQ specialist. Pydantic AI sets limits per run, so callers pass this."""

ARTICLE_ID = re.compile(r"\bdoc_\d+\b")


def _check_reply(ctx: RunContext[Session], text: str | None, citations: list[str]) -> None:
    """Customer-facing text must not expose internal article IDs and may only cite articles read in this run."""
    if text and ARTICLE_ID.search(text):
        raise ModelRetry("Remove article IDs from the customer-facing text; pass them in citations instead.")
    unread = set(citations) - ctx.deps.articles_read
    if unread:
        raise ModelRetry(f"Citations {sorted(unread)} were not read by the FAQ specialist in this run.")


async def reply_to_customer(
    ctx: RunContext[Session], intent: Intent, confidence: Confidence, reply: str, citations: list[str]
) -> Outcome:
    """Finish with an automatic reply.

    Only for replies grounded in FAQ articles returned by consult_faq (cite them), or to report the
    result of bank actions from this run (quote the reference, and claim nothing beyond the result).
    """
    _check_reply(ctx, reply, citations)
    if not (citations or ctx.deps.actions or ctx.deps.declined_actions):
        raise ModelRetry(
            "An automatic reply needs grounding: FAQ citations or a bank action from this run. "
            "Otherwise use escalate_to_human."
        )
    handling = "action_taken" if ctx.deps.actions else "auto_reply"
    return Outcome(handling=handling, intent=intent, confidence=confidence, reply=reply, citations=citations)


async def escalate_to_human(
    ctx: RunContext[Session],
    intent: Intent,
    confidence: Confidence,
    summary: str,
    reason: EscalationReason,
    priority: Priority,
    holding_reply: str | None = None,
    citations: list[str] | None = None,
) -> Outcome:
    """Finish by handing the message to a human agent.

    summary is written for the human agent. holding_reply is an optional immediate message to the
    customer, e.g. self-service steps from the FAQ (cite them). Use priority 'urgent' for security and fraud.
    """
    # Citations describe what the customer-facing reply relies on; without a reply there is nothing to cite.
    citations = (citations or []) if holding_reply else []
    _check_reply(ctx, holding_reply, citations)
    handoff = Handoff(priority=priority, reason=reason, summary=summary, customer_message=str(ctx.prompt))
    return Outcome(
        handling="human_handoff",
        intent=intent,
        confidence=confidence,
        reply=holding_reply,
        citations=citations,
        handoff=handoff,
    )


async def ask_clarification(ctx: RunContext[Session], intent: Intent, confidence: Confidence, question: str) -> Outcome:
    """Finish by asking the customer one clarifying question.

    Only when you cannot tell what the customer wants. The answer arrives as a new message in the thread.
    """
    return Outcome(handling="clarification", intent=intent, confidence=confidence, reply=question)


def _taxonomy_markdown() -> str:
    lines = [f"- {domain}: {', '.join(intents)}" for domain, intents in DOMAINS.items()]
    lines.append(f"- {OTHER}: {OTHER} (nothing above fits)")
    return "\n".join(lines)


PROMPT = (Path(__file__).parent / "prompts" / "router.md").read_text(encoding="utf-8")

router = Agent(
    MODEL,
    name="router",
    deps_type=Session,
    output_type=[reply_to_customer, escalate_to_human, ask_clarification],
    toolsets=[bank_toolset],
    capabilities=[customer_confirmation, outcome_handling],
    retries={"output": 2},
    defer_model_check=True,
    instructions=PROMPT.format(taxonomy=_taxonomy_markdown()),
)


@router.tool
async def consult_faq(ctx: RunContext[Session], question: str) -> FaqAnswer:
    """Ask the FAQ specialist a self-contained information question. Returns an answer with article
    citations, or status not_covered."""
    result = await faq_agent.run(question, deps=ctx.deps, usage=ctx.usage)
    return result.output
