"""LangGraph state graph tying together supervisor, specialists, HITL, and finalizer."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from aura.agents.prompts import (
    SUPERVISOR_SYSTEM,
    finalizer_prompt,
    insight_agent_prompt,
    order_agent_prompt,
    returns_agent_prompt,
)
from aura.config import settings
from aura.guardrails.authz import set_auth_context
from aura.guardrails.injection import detect as detect_injection
from aura.guardrails.pii import redact
from aura.llm import get_llm
from aura.state import AgentState
from aura.tools.db_tools import (
    INSIGHT_TOOLS,
    ORDER_TOOLS,
    RETURNS_TOOLS,
)
from aura.tools.policy_tool import search_policy_tool


def _last_human_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""


# ---------------------------------------------------------------------------
# Node: guardrails input
# ---------------------------------------------------------------------------

def guardrails_node(state: AgentState) -> dict[str, Any]:
    text = _last_human_text(state.get("messages", []))
    turn_reset: dict[str, Any] = {
        "route": None,
        "pending_approval": None,
        "final_reply": None,
        "injection_detected": False,
        "pii_redactions": [],
    }
    if not text:
        return turn_reset
    injection = detect_injection(text)
    if injection.detected:
        refusal = (
            "I can't help with that request. Your message looked like it was trying to "
            "override my safety rules, so I'm escalating this to a human operator."
        )
        return {
            **turn_reset,
            "injection_detected": True,
            "route": "blocked",
            "final_reply": refusal,
            "messages": [AIMessage(content=refusal)],
        }
    pii = redact(text)
    return {
        **turn_reset,
        "pii_redactions": [h.split(":", 1)[0] for h in pii.hits],
    }


# ---------------------------------------------------------------------------
# Node: supervisor router
# ---------------------------------------------------------------------------

_VALID_ROUTES = {"order_agent", "returns_agent", "insight_agent", "finalize", "blocked"}


def supervisor_node(state: AgentState) -> dict[str, Any]:
    if state.get("route") == "blocked":
        return {}
    llm = get_llm(role="router", temperature=0.0)
    convo = state.get("messages", [])
    recent = convo[-6:]
    transcript_lines: list[str] = []
    for m in recent:
        if isinstance(m, HumanMessage):
            transcript_lines.append(f"User: {m.content}")
        elif isinstance(m, AIMessage):
            content = m.content if isinstance(m.content, str) else ""
            if content:
                transcript_lines.append(f"Agent: {content[:200]}")
    transcript = "\n".join(transcript_lines) or "User: hi"
    resp = llm.invoke(
        [SystemMessage(SUPERVISOR_SYSTEM), HumanMessage(f"Conversation so far:\n{transcript}")]
    )
    token = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip().lower()
    for route in _VALID_ROUTES:
        if route in token:
            return {"route": route}
    return {"route": "finalize"}


# ---------------------------------------------------------------------------
# Specialist agents — role-aware ReAct loop
# ---------------------------------------------------------------------------

_MAX_TOOL_ITERS = 6


def _run_specialist(
    state: AgentState, system_prompt: str, tools: list, name: str
) -> dict[str, Any]:
    # Bind the real security boundary for this turn: every tool call below is
    # checked in code against who is actually signed in (see
    # aura.guardrails.authz), not just told via the system prompt.
    set_auth_context(state.get("role"), state.get("authenticated_customer_id"))
    llm = get_llm(role="agent", temperature=0.1).bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}
    msgs = [SystemMessage(system_prompt), *state.get("messages", [])]
    pending_approval: dict[str, Any] | None = None
    for _ in range(_MAX_TOOL_ITERS):
        ai = llm.invoke(msgs)
        msgs.append(ai)
        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            return {"messages": [ai], "pending_approval": pending_approval}
        for call in calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                result: Any = {"error": f"unknown tool {call['name']!r}"}
            else:
                try:
                    result = tool.invoke(call["args"])
                except Exception as e:  # noqa: BLE001
                    result = {"error": type(e).__name__, "detail": str(e)}
            if call["name"] == "create_approval_request" and isinstance(result, dict):
                pending_approval = {
                    "approval_id": result.get("approval_id"),
                    "refund_id": result.get("refund_id"),
                    "agent": name,
                }
            msgs.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"])
            )
    return {
        "messages": [AIMessage(content="(specialist hit iteration limit)")],
        "pending_approval": pending_approval,
    }


def order_agent_node(state: AgentState) -> dict[str, Any]:
    role = state.get("role") or "ops"
    auth = state.get("authenticated_customer_id")
    return _run_specialist(
        state, order_agent_prompt(role, auth), [*ORDER_TOOLS, search_policy_tool], "order"
    )


def returns_agent_node(state: AgentState) -> dict[str, Any]:
    role = state.get("role") or "ops"
    auth = state.get("authenticated_customer_id")
    return _run_specialist(
        state,
        returns_agent_prompt(role, auth),
        [*RETURNS_TOOLS, search_policy_tool],
        "returns",
    )


def insight_agent_node(state: AgentState) -> dict[str, Any]:
    role = state.get("role") or "ops"
    auth = state.get("authenticated_customer_id")
    return _run_specialist(
        state, insight_agent_prompt(role, auth), INSIGHT_TOOLS, "insight"
    )


# ---------------------------------------------------------------------------
# HITL gate
# ---------------------------------------------------------------------------

def hitl_gate_node(state: AgentState) -> dict[str, Any]:
    pending = state.get("pending_approval")
    if not pending:
        return {}
    decision = interrupt(
        {
            "kind": "refund_approval",
            "approval_id": pending.get("approval_id"),
            "refund_id": pending.get("refund_id"),
            "message": (
                "A refund requires human approval. Approve or reject in the Ops console."
            ),
        }
    )
    return {"pending_approval": {**pending, "human_decision": decision}}


# ---------------------------------------------------------------------------
# Finalizer
# ---------------------------------------------------------------------------

def finalizer_node(state: AgentState) -> dict[str, Any]:
    if state.get("final_reply"):
        return {"messages": [AIMessage(content=state["final_reply"])]}
    role = state.get("role") or "ops"
    auth = state.get("authenticated_customer_id")
    llm = get_llm(role="agent", temperature=0.2)
    convo = state.get("messages", [])
    summary_msg = next(
        (m for m in reversed(convo) if isinstance(m, AIMessage) and m.content),
        None,
    )
    if summary_msg is None:
        summary_text = "The request has been processed."
    else:
        content = summary_msg.content
        if isinstance(content, str):
            summary_text = content
        else:
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        inp = block.get("input") or {}
                        for key in ("summary", "body", "text"):
                            if inp.get(key):
                                parts.append(str(inp[key]))
                                break
                elif isinstance(block, str):
                    parts.append(block)
            summary_text = "\n".join(p for p in parts if p) or "The request has been processed."
    pending = state.get("pending_approval")
    approval_hint = ""
    if pending:
        approval_hint = (
            f"\n\nNote: this request has been escalated for review. "
            f"Reference approval id: {pending.get('approval_id')}."
        )
    msgs = [
        SystemMessage(finalizer_prompt(role, auth)),
        HumanMessage(
            f"Internal specialist summary:\n\n{summary_text}\n\n"
            f"{approval_hint}\n\n"
            "Rewrite for the intended reader per the persona rules. Do not call any tools."
        ),
    ]
    ai = llm.invoke(msgs)
    content = ai.content
    if isinstance(content, str):
        reply = content
    else:
        reply = "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ) or summary_text
    return {"final_reply": reply.strip(), "messages": [AIMessage(content=reply.strip())]}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _route_from_supervisor(state: AgentState) -> str:
    if state.get("injection_detected"):
        return "finalize"
    return state.get("route") or "finalize"


def _route_after_specialist(state: AgentState) -> str:
    return "hitl_gate" if state.get("pending_approval") else "finalize"


def build_graph(checkpointer: Any | None = None):
    builder = StateGraph(AgentState)

    builder.add_node("guardrails", guardrails_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("order_agent", order_agent_node)
    builder.add_node("returns_agent", returns_agent_node)
    builder.add_node("insight_agent", insight_agent_node)
    builder.add_node("hitl_gate", hitl_gate_node)
    builder.add_node("finalize", finalizer_node)

    builder.add_edge(START, "guardrails")
    builder.add_edge("guardrails", "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "order_agent": "order_agent",
            "returns_agent": "returns_agent",
            "insight_agent": "insight_agent",
            "finalize": "finalize",
            "blocked": "finalize",
        },
    )

    for spec in ("order_agent", "returns_agent", "insight_agent"):
        builder.add_conditional_edges(
            spec,
            _route_after_specialist,
            {"hitl_gate": "hitl_gate", "finalize": "finalize"},
        )

    builder.add_edge("hitl_gate", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


def get_checkpointer() -> SqliteSaver:
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    conn = sqlite3.connect(str(settings.checkpoint_db_path), check_same_thread=False)
    return SqliteSaver(conn)
