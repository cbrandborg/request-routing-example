"""Mock bank systems exposed as an MCP server.

Stands in for core banking behind its own authorization layer. The customer identity comes from
request metadata set by the assistant's bank toolset, never from tool arguments chosen by a model.
Every executed operation is written to an audit log, and an identical request repeated for the same
customer message (a retry) returns the original result instead of running twice.

A separate system: imports nothing from request_routing. Run on its own over stdio with
`python -m mcp_servers.bank.server`.
"""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

# Deliberately independent of the assistant's configuration: this process gets no model credentials.
RUNS_DIR = Path(os.getenv("REQUEST_ROUTING_RUNS_DIR", Path(__file__).resolve().parents[2] / "runs"))
AUDIT_LOG = RUNS_DIR / "audit" / "actions.jsonl"

server = FastMCP("bank-systems")


def _execute(ctx: Context, operation: str, details: dict, status: str) -> dict:
    meta = (ctx.request_context.meta if ctx.request_context else None) or {}
    customer_id = meta.get("customer_id")
    if not customer_id:
        raise ToolError("Unauthenticated request: no customer identity in request metadata.")

    request = [customer_id, meta.get("run_id"), operation, details]
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
    if AUDIT_LOG.exists():
        for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry["idempotency_key"] == key:
                return {**entry["result"], "duplicate_request": True}

    result = {"reference": f"ACT-{uuid.uuid4().hex[:8].upper()}", "operation": operation, "status": status}
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "customer_id": customer_id,
            "run_id": meta.get("run_id"),
            "operation": operation,
            "details": details,
            "idempotency_key": key,
            "result": result,
        }
        f.write(json.dumps(entry) + "\n")
    return result


@server.tool
def cards_block_card(reason: Literal["lost", "stolen", "compromised"], ctx: Context) -> dict:
    """Block the customer's card immediately. Protective and reversible."""
    return _execute(ctx, "cards_block_card", {"reason": reason}, "blocked")


@server.tool
def cards_order_replacement(
    reason: Literal["lost", "stolen", "compromised", "damaged", "expiring"], ctx: Context
) -> dict:
    """Order a replacement card to the customer's registered address."""
    return _execute(ctx, "cards_order_replacement", {"reason": reason}, "replacement_ordered")


@server.tool
def cards_unblock_pin(ctx: Context) -> dict:
    """Unblock the customer's PIN after too many wrong attempts."""
    return _execute(ctx, "cards_unblock_pin", {}, "pin_unblock_requested")


@server.tool
def payments_cancel_transfer(transfer_description: str, ctx: Context) -> dict:
    """Request cancellation of a pending transfer. Processed transfers cannot be cancelled this way."""
    return _execute(ctx, "payments_cancel_transfer", {"transfer": transfer_description}, "cancellation_requested")


@server.tool
def payments_request_refund(transaction_description: str, reason: str, ctx: Context) -> dict:
    """Open a refund request for a card payment the customer made."""
    details = {"transaction": transaction_description, "reason": reason}
    return _execute(ctx, "payments_request_refund", details, "refund_requested")


@server.tool
def account_close(reason: str, ctx: Context) -> dict:
    """Request closure of the customer's account. Irreversible once processed."""
    return _execute(ctx, "account_close", {"reason": reason}, "closure_requested")


@server.tool
def account_update_contact_details(field: Literal["address", "phone", "email"], new_value: str, ctx: Context) -> dict:
    """Request an update of the customer's contact details."""
    return _execute(ctx, "account_update_contact_details", {"field": field, "new_value": new_value}, "update_requested")


if __name__ == "__main__":
    server.run(show_banner=False)
