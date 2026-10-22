"""Data structures: the session the agents run with, what the FAQ specialist returns, and the outcome."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, computed_field
from pydantic_ai import ToolCallPart

from request_routing.taxonomy import INTENT_DOMAIN, INTENTS

Intent = Literal[tuple(INTENTS)]  # type: ignore[valid-type]
Confidence = Annotated[float, Field(ge=0, le=1)]
Handling = Literal["auto_reply", "action_taken", "human_handoff", "clarification"]
Priority = Literal["normal", "urgent"]
EscalationReason = Literal[
    "not_covered_by_faq",
    "needs_investigation",
    "needs_customer_data",
    "complaint",
    "security_or_fraud",
    "action_not_supported",
    "system_fallback",
]


class FaqAnswer(BaseModel):
    """What the FAQ specialist returns to the router."""

    status: Literal["answered", "partially_answered", "not_covered"]
    answer: str = Field(description="Answer grounded only in the cited articles, or what is missing if not covered.")
    citations: list[str] = Field(default_factory=list, description="IDs of the articles the answer relies on.")
    source_conflict: str | None = Field(
        default=None, description="How the cited articles disagree, if they do. Do not resolve the conflict."
    )


class ActionRecord(BaseModel):
    operation: str
    arguments: dict[str, Any]
    result: Any


class Handoff(BaseModel):
    """A ticket for the human customer-service queue."""

    ticket_id: str = Field(default_factory=lambda: f"HUM-{uuid.uuid4().hex[:8].upper()}")
    priority: Priority
    reason: EscalationReason
    summary: str
    customer_message: str


class Outcome(BaseModel):
    """The single result of handling one customer message."""

    handling: Handling
    intent: Intent
    confidence: Confidence
    reply: str | None = None
    citations: list[str] = Field(default_factory=list)
    handoff: Handoff | None = None
    # What the bank tools did, attached after the run from the session.
    actions: list[ActionRecord] = Field(default_factory=list)
    declined_actions: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def domain(self) -> str:
        return INTENT_DOMAIN[self.intent]


Confirm = Callable[[ToolCallPart], bool]
"""The customer's answer to a bank action that needs confirmation (MitID in the app, simulated here)."""


@dataclass
class Session:
    """Deps for one authenticated customer: who they are, how they confirm, and what the tools did.

    The record fields cover the current message (they are reset at the start of each run). Output functions
    and validators check the agents' claims against them.
    """

    customer_id: str
    confirm: Confirm
    articles_read: set[str] = field(default_factory=set)
    actions: list[ActionRecord] = field(default_factory=list)
    declined_actions: list[str] = field(default_factory=list)
