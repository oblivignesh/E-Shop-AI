"""Typed graph state shared across all agent nodes."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State that flows through every LangGraph node.

    Fields are intentionally optional (`total=False`) because different
    nodes populate different subsets. `messages` is the chat history and
    uses LangGraph's built-in `add_messages` reducer for append semantics.
    """

    # Conversation
    messages: Annotated[list, add_messages]

    # Who is talking to AURA?
    #   "customer" -> an authenticated shopper; agent addresses them by name and
    #                 refuses to disclose other customers' data.
    #   "ops"      -> internal staff; agent reports facts in third person and can
    #                 look up any id.
    role: Literal["customer", "ops"] | None
    # For role="customer": the id of the person actually chatting. All refund /
    # order queries must be validated against this id.
    authenticated_customer_id: str | None

    # Routing decision from the supervisor node
    route: Literal[
        "order_agent",
        "returns_agent",
        "insight_agent",
        "finalize",
        "blocked",
    ] | None

    # Working context extracted or asserted during the turn
    customer_id: str | None
    order_id: str | None

    # Filled by the returns agent when a refund needs HITL
    pending_approval: dict[str, Any] | None

    # Guardrail signal
    injection_detected: bool
    pii_redactions: list[str]

    # Final natural language reply for the user (built by finalizer)
    final_reply: str | None
