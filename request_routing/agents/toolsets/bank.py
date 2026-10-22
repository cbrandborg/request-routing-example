"""Bank toolset: the router's MCP client connection to the bank systems.

The tools themselves are defined by the server (mcp_servers/bank) and discovered on connect. This module
decides where the server runs, which customer each call is for, and which calls need confirmation.
"""

import sys

from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset

from request_routing.config import ROOT, RUNS_DIR
from request_routing.schemas import ActionRecord, Session

# Protective and reversible: runs without waiting for customer confirmation. Everything else pauses.
NO_CONFIRMATION_NEEDED = {"cards_block_card"}


async def _call_with_customer_identity(ctx: RunContext[Session], call_tool, name: str, args: dict):
    """Attach the authenticated customer to every bank call and record what was executed."""
    metadata = {"customer_id": ctx.deps.customer_id, "run_id": ctx.run_id}
    result = await call_tool(name, args, metadata=metadata)
    ctx.deps.actions.append(ActionRecord(operation=name, arguments=args, result=result))
    return result


# The bank server runs as a separate process, reached over MCP stdio. It gets only the runs directory,
# not the assistant's environment (no model credentials). Its logs go to a file, not the terminal.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
bank_server = StdioTransport(
    sys.executable,
    ["-m", "mcp_servers.bank.server"],
    env={"REQUEST_ROUTING_RUNS_DIR": str(RUNS_DIR)},
    cwd=str(ROOT),
    log_file=RUNS_DIR / "bank_server.log",
)
bank_toolset = MCPToolset(bank_server, process_tool_call=_call_with_customer_identity).approval_required(
    lambda ctx, tool_def, args: tool_def.name not in NO_CONFIRMATION_NEEDED
)
