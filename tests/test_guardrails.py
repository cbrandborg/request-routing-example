"""Guardrail tests with scripted models: no API calls, so they show the rules are enforced in code."""

import asyncio
import contextvars
import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from mcp_servers.bank.server import AUDIT_LOG
from request_routing.agents.faq import faq_agent
from request_routing.agents.router import LIMITS, router
from request_routing.config import HANDOFF_QUEUE
from request_routing.schemas import Outcome, Session


@pytest.fixture(scope="module")
def run():
    """One event loop for all tests: the MCP client stays bound to the loop it first connected on.

    Each call copies the caller's context so `agent.override(model=...)` is visible inside the run.
    """
    with asyncio.Runner() as runner:
        yield lambda coro: runner.run(coro, context=contextvars.copy_context())


def scripted(*steps: tuple[str, dict]) -> FunctionModel:
    """A model that makes the given tool calls in order. Output functions are matched by name suffix."""
    remaining = iter(steps)

    def respond(messages, info: AgentInfo) -> ModelResponse:
        name, args = next(remaining)
        available = [t.name for t in info.function_tools + info.output_tools]
        tool = name if name in available else next(t for t in available if t.endswith(name))
        return ModelResponse(parts=[ToolCallPart(tool, args)])

    return FunctionModel(respond)


def never_asked(call):
    raise AssertionError(f"{call.tool_name} should not need customer confirmation")


def route(run, message: str, *, model: FunctionModel, customer_id: str, confirm=never_asked) -> Outcome:
    session = Session(customer_id=customer_id, confirm=confirm)
    with router.override(model=model):
        return run(router.run(message, deps=session, usage_limits=LIMITS)).output


def audit_entries(customer_id: str) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    entries = [json.loads(line) for line in AUDIT_LOG.read_text().splitlines()]
    return [e for e in entries if e["customer_id"] == customer_id]


def test_blocking_a_card_runs_immediately_under_the_session_identity(run):
    model = scripted(
        ("cards_block_card", {"reason": "stolen"}),
        (
            "escalate_to_human",
            {
                "intent": "lost_or_stolen_card",
                "confidence": 0.9,
                "summary": "Wallet stolen; card blocked; check for misuse.",
                "reason": "security_or_fraud",
                "priority": "urgent",
            },
        ),
    )
    outcome = route(run, "My card was stolen, block it", model=model, customer_id="c-1")

    assert outcome.handling == "human_handoff"
    assert outcome.handoff.priority == "urgent"
    assert outcome.actions[0].result["status"] == "blocked"
    [entry] = audit_entries("c-1")  # identity came from the session, not from tool arguments
    assert entry["operation"] == "cards_block_card"
    queued = [json.loads(line) for line in HANDOFF_QUEUE.read_text().splitlines()]
    assert outcome.handoff.ticket_id in {ticket["ticket_id"] for ticket in queued}


def test_cancelling_a_transfer_waits_for_confirmation_and_respects_a_denial(run):
    asked = []
    model = scripted(
        ("payments_cancel_transfer", {"transfer_description": "last transfer"}),
        (
            "reply_to_customer",
            {
                "intent": "cancel_transfer",
                "confidence": 0.9,
                "reply": "You did not confirm, so nothing was changed.",
                "citations": [],
            },
        ),
    )
    outcome = route(
        run, "Cancel my last transfer", model=model, customer_id="c-2", confirm=lambda call: asked.append(call) or False
    )

    assert [call.tool_name for call in asked] == ["payments_cancel_transfer"]
    assert outcome.declined_actions == ["payments_cancel_transfer"]
    assert outcome.actions == []
    assert audit_entries("c-2") == []


def test_reply_citing_an_unread_article_ends_with_a_human_instead(run):
    ungrounded = (
        "reply_to_customer",
        {"intent": "change_pin", "confidence": 0.9, "reply": "Change it in the app.", "citations": ["doc_027"]},
    )
    outcome = route(run, "How do I change my PIN?", model=scripted(*[ungrounded] * 5), customer_id="c-3")

    assert outcome.handling == "human_handoff"
    assert outcome.handoff.reason == "system_fallback"


def test_faq_specialist_must_read_the_articles_it_cites(run):
    answer = {"status": "answered", "answer": "Use Cards > PIN settings.", "citations": ["doc_027"]}
    model = scripted(("final_result", answer), ("read_faq", {"article_id": "doc_027"}), ("final_result", answer))
    session = Session(customer_id="c-4", confirm=never_asked)

    with faq_agent.override(model=model):
        result = run(faq_agent.run("How do I change my PIN?", deps=session))

    assert result.output.citations == ["doc_027"]
    assert session.articles_read == {"doc_027"}


def test_customer_text_with_internal_article_ids_is_retried(run):
    def reply(text: str) -> tuple[str, dict]:
        return (
            "reply_to_customer",
            {"intent": "lost_or_stolen_card", "confidence": 0.9, "reply": text, "citations": []},
        )

    model = scripted(
        ("cards_block_card", {"reason": "lost"}),
        reply("Your card is blocked (doc_001)."),
        reply("Your card is blocked."),
    )
    outcome = route(run, "I lost my card, block it", model=model, customer_id="c-5")

    assert outcome.handling == "action_taken"
    assert outcome.reply == "Your card is blocked."
