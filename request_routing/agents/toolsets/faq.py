"""FAQ toolset: open the pages listed in the FAQ index.

Retrieval is index navigation, as in PageIndex: the agent reads the index in its instructions and decides
which pages to open. No embeddings and no search.
"""

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from request_routing.config import FAQ_DIR
from request_routing.schemas import Session

INDEX = (FAQ_DIR / "index.md").read_text(encoding="utf-8")
PAGES = {path.stem: path.read_text(encoding="utf-8") for path in sorted(FAQ_DIR.glob("doc_*.md"))}

faq_toolset = FunctionToolset()


@faq_toolset.tool
def read_faq(ctx: RunContext[Session], article_id: str) -> str:
    """Read one FAQ article by its ID from the index, e.g. 'doc_007'."""
    if article_id not in PAGES:
        raise ModelRetry(f"Unknown article ID {article_id!r}. Use an ID from the index.")
    ctx.deps.articles_read.add(article_id)
    return PAGES[article_id]
