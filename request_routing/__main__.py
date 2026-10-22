"""Chat with the router as a customer: `uv run python -m request_routing` from the repository root.

Bank actions that need confirmation ask you in the terminal, standing in for the customer's MitID approval.
"""

from pydantic_ai import ToolCallPart
from rich.prompt import Confirm

from request_routing.agents.router import LIMITS, router
from request_routing.config import TRACES_DIR
from request_routing.schemas import Session
from request_routing.tracing import configure_tracing


def ask_in_terminal(call: ToolCallPart) -> bool:
    return Confirm.ask(f"[yellow]Customer confirmation:[/] {call.tool_name} {call.args_as_dict()}?", default=False)


def main() -> None:
    configure_tracing(TRACES_DIR)
    session = Session(customer_id="demo-customer", confirm=ask_in_terminal)
    router.to_cli_sync(deps=session, usage_limits=LIMITS, prog_name="request-routing")


if __name__ == "__main__":
    main()
