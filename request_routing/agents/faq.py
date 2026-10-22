"""FAQ specialist: answers information questions from the FAQ articles, with citations."""

from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext

from request_routing.agents.toolsets.faq import INDEX, faq_toolset
from request_routing.config import MODEL
from request_routing.schemas import FaqAnswer, Session

PROMPT = (Path(__file__).parent / "prompts" / "faq.md").read_text(encoding="utf-8")

faq_agent = Agent(
    MODEL,
    name="faq_specialist",
    deps_type=Session,
    output_type=FaqAnswer,
    toolsets=[faq_toolset],
    retries=2,
    defer_model_check=True,
    instructions=PROMPT.format(faq_index=INDEX),
)


@faq_agent.output_validator
def check_grounding(ctx: RunContext[Session], answer: FaqAnswer) -> FaqAnswer:
    unread = set(answer.citations) - ctx.deps.articles_read
    if unread:
        raise ModelRetry(f"You cited {sorted(unread)} without reading them. Read them or remove the citations.")
    if answer.status != "not_covered" and not answer.citations:
        raise ModelRetry("An answer must cite the articles it relies on. Otherwise use not_covered.")
    return answer
