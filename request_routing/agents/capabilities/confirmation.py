"""Customer confirmation: bank calls that need approval are answered by the customer inside the run."""

from pydantic_ai import DeferredToolRequests, DeferredToolResults, RunContext, ToolDenied
from pydantic_ai.capabilities import HandleDeferredToolCalls

from request_routing.schemas import Session


def _ask_customer(ctx: RunContext[Session], requests: DeferredToolRequests) -> DeferredToolResults:
    approvals = {}
    for call in requests.approvals:
        if ctx.deps.confirm(call):
            approvals[call.tool_call_id] = True
        else:
            approvals[call.tool_call_id] = ToolDenied("The customer did not confirm this operation.")
            ctx.deps.declined_actions.append(call.tool_name)
    return requests.build_results(approvals=approvals)


customer_confirmation = HandleDeferredToolCalls(_ask_customer)
