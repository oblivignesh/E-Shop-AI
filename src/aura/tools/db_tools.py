"""SQL-backed tools exposed to LangGraph agents.

Every tool:
- has a Pydantic input schema (LangChain converts these to the LLM tool schema),
- uses parametrized SQL only (no string interpolation of user input),
- returns a JSON-serializable dict / list of dicts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from aura.db import execute, fetch_all, fetch_one
from aura.guardrails.authz import assert_customer_scope


# ---------- customers ----------


class _CustomerId(BaseModel):
    customer_id: str = Field(description="Customer ID like 'CUST0001'.")


def _get_customer(customer_id: str) -> dict[str, Any] | None:
    assert_customer_scope(customer_id)
    row = fetch_one(
        "SELECT customer_id, first_name, last_name, email, phone, city, state, "
        "country, signup_date, customer_segment "
        "FROM customers WHERE customer_id = :cid",
        {"cid": customer_id},
    )
    return row


get_customer_tool = StructuredTool.from_function(
    func=_get_customer,
    name="get_customer",
    description="Fetch a customer profile (name, contact, segment, signup date) by customer_id.",
    args_schema=_CustomerId,
)


def _list_customer_orders(customer_id: str) -> list[dict[str, Any]]:
    assert_customer_scope(customer_id)
    return fetch_all(
        "SELECT order_id, order_date, order_status, total_amount, payment_method, "
        "order_channel FROM orders WHERE customer_id = :cid ORDER BY order_date DESC",
        {"cid": customer_id},
    )


list_customer_orders_tool = StructuredTool.from_function(
    func=_list_customer_orders,
    name="list_customer_orders",
    description="List all orders placed by a customer, newest first.",
    args_schema=_CustomerId,
)


# ---------- orders ----------


class _OrderId(BaseModel):
    order_id: str = Field(description="Order ID like 'ORD00001'.")


def _get_order(order_id: str) -> dict[str, Any] | None:
    row = fetch_one(
        "SELECT order_id, customer_id, order_date, order_status, total_amount, "
        "payment_method, shipping_address, order_channel "
        "FROM orders WHERE order_id = :oid",
        {"oid": order_id},
    )
    if row:
        assert_customer_scope(row["customer_id"])
    return row


get_order_tool = StructuredTool.from_function(
    func=_get_order,
    name="get_order",
    description="Fetch a single order header (status, total, channel, shipping address).",
    args_schema=_OrderId,
)


def _get_order_items(order_id: str) -> list[dict[str, Any]]:
    order = _get_order(order_id)  # raises AuthorizationError if not the caller's order
    if not order:
        return []
    return fetch_all(
        "SELECT order_item_id, product_id, product_name, category, quantity, "
        "unit_price, subtotal FROM order_items WHERE order_id = :oid",
        {"oid": order_id},
    )


get_order_items_tool = StructuredTool.from_function(
    func=_get_order_items,
    name="get_order_items",
    description="List all line items for an order.",
    args_schema=_OrderId,
)


def _get_shipment_by_order(order_id: str) -> dict[str, Any] | None:
    order = _get_order(order_id)  # raises AuthorizationError if not the caller's order
    if not order:
        return None
    return fetch_one(
        "SELECT shipment_id, order_id, carrier, tracking_number, ship_date, "
        "estimated_delivery_date, actual_delivery_date, shipment_status "
        "FROM shipments WHERE order_id = :oid",
        {"oid": order_id},
    )


get_shipment_by_order_tool = StructuredTool.from_function(
    func=_get_shipment_by_order,
    name="get_shipment_by_order",
    description=(
        "Fetch the shipment row (carrier, tracking, ETA, status: "
        "'In Transit' | 'Delivered' | 'Delayed' | 'Lost') for an order."
    ),
    args_schema=_OrderId,
)


# ---------- refunds ----------


class _RefundId(BaseModel):
    refund_id: str = Field(description="Refund case ID like 'REF00001'.")


def _get_refund_case(refund_id: str) -> dict[str, Any] | None:
    row = fetch_one(
        "SELECT refund_id, order_id, order_item_id, customer_id, reason, "
        "refund_amount, status, request_date, resolution_date "
        "FROM refund_cases WHERE refund_id = :rid",
        {"rid": refund_id},
    )
    if row:
        assert_customer_scope(row["customer_id"])
    return row


get_refund_case_tool = StructuredTool.from_function(
    func=_get_refund_case,
    name="get_refund_case",
    description="Fetch a single refund_case by refund_id.",
    args_schema=_RefundId,
)


def _list_refunds_for_customer(customer_id: str) -> list[dict[str, Any]]:
    assert_customer_scope(customer_id)
    return fetch_all(
        "SELECT refund_id, order_id, reason, refund_amount, status, request_date "
        "FROM refund_cases WHERE customer_id = :cid ORDER BY request_date DESC",
        {"cid": customer_id},
    )


list_refunds_for_customer_tool = StructuredTool.from_function(
    func=_list_refunds_for_customer,
    name="list_refunds_for_customer",
    description=(
        "List all refund cases for a customer, newest first. Use this to check "
        "refund velocity (>=3 in trailing 90 days is a fraud signal)."
    ),
    args_schema=_CustomerId,
)


class _CreateRefund(BaseModel):
    order_id: str
    order_item_id: str | None = Field(
        default=None, description="Optional order_item_id if refund is for a single line item."
    )
    customer_id: str
    reason: str = Field(description="Reason from the customer's message.")
    refund_amount: float = Field(gt=0, description="Refund amount in INR.")


def _create_refund_case(
    order_id: str,
    customer_id: str,
    reason: str,
    refund_amount: float,
    order_item_id: str | None = None,
) -> dict[str, Any]:
    assert_customer_scope(customer_id)
    order = _get_order(order_id)  # also raises if order belongs to someone else
    if not order:
        return {"error": f"order_id {order_id!r} not found"}
    if order["customer_id"] != customer_id:
        return {"error": f"order {order_id} does not belong to customer {customer_id}"}
    # Generate a new refund_id following the REFxxxxx convention.
    last = fetch_one(
        "SELECT refund_id FROM refund_cases ORDER BY refund_id DESC LIMIT 1"
    )
    if last and last["refund_id"].startswith("REF"):
        n = int(last["refund_id"][3:]) + 1
    else:
        n = 1
    new_id = f"REF{n:05d}"
    now = datetime.now(UTC).date().isoformat()
    execute(
        "INSERT INTO refund_cases (refund_id, order_id, order_item_id, customer_id, "
        "reason, refund_amount, status, request_date, resolution_date) "
        "VALUES (:rid, :oid, :oiid, :cid, :reason, :amt, 'Requested', :rd, NULL)",
        {
            "rid": new_id,
            "oid": order_id,
            "oiid": order_item_id,
            "cid": customer_id,
            "reason": reason,
            "amt": refund_amount,
            "rd": now,
        },
    )
    return {"refund_id": new_id, "status": "Requested"}


create_refund_case_tool = StructuredTool.from_function(
    func=_create_refund_case,
    name="create_refund_case",
    description=(
        "Create a new refund_case in 'Requested' status. Returns the new refund_id. "
        "Do NOT call this before checking policy eligibility and fraud signals."
    ),
    args_schema=_CreateRefund,
)


class _UpdateRefundStatus(BaseModel):
    refund_id: str
    new_status: str = Field(
        description="One of: 'Under Review', 'Approved', 'Rejected', 'Completed'."
    )


def _update_refund_status(refund_id: str, new_status: str) -> dict[str, Any]:
    from aura.guardrails.authz import AuthorizationError, assert_can_approve_refund

    _get_refund_case(refund_id)  # raises AuthorizationError if not the caller's refund

    allowed = {"Requested", "Under Review", "Approved", "Rejected", "Completed"}
    if new_status not in allowed:
        return {"error": f"invalid status '{new_status}'", "allowed": sorted(allowed)}
    if new_status in {"Approved", "Completed"}:
        try:
            assert_can_approve_refund(refund_id)
        except AuthorizationError as e:
            return {"error": "authorization_denied", "detail": str(e)}
    now = datetime.now(UTC).date().isoformat()
    resolution = now if new_status in {"Approved", "Rejected", "Completed"} else None
    rows = execute(
        "UPDATE refund_cases SET status = :s, resolution_date = :rd WHERE refund_id = :rid",
        {"s": new_status, "rd": resolution, "rid": refund_id},
    )
    return {"refund_id": refund_id, "new_status": new_status, "rows_updated": rows}


update_refund_status_tool = StructuredTool.from_function(
    func=_update_refund_status,
    name="update_refund_status",
    description="Move a refund_case to a new status. Auto-fills resolution_date on terminal states.",
    args_schema=_UpdateRefundStatus,
)


# ---------- approvals ----------


class _CreateApproval(BaseModel):
    refund_id: str
    requested_by: str = Field(default="AURA Agent", description="Agent or user name.")
    amount: float
    reason: str = Field(description="Why this needs human approval (fraud signal, amount, etc.).")


def _create_approval_request(
    refund_id: str, amount: float, reason: str, requested_by: str = "AURA Agent"
) -> dict[str, Any]:
    last = fetch_one(
        "SELECT approval_id FROM approval_requests ORDER BY approval_id DESC LIMIT 1"
    )
    if last and last["approval_id"].startswith("APR"):
        n = int(last["approval_id"][3:]) + 1
    else:
        n = 1
    new_id = f"APR{n:05d}"
    now = datetime.now(UTC).date().isoformat()
    execute(
        "INSERT INTO approval_requests (approval_id, refund_id, requested_by, approver, "
        "request_type, amount, status, request_date, decision_date, comments) "
        "VALUES (:aid, :rid, :rb, NULL, 'Refund Approval', :amt, 'Pending', :rd, NULL, :c)",
        {
            "aid": new_id,
            "rid": refund_id,
            "rb": requested_by,
            "amt": amount,
            "rd": now,
            "c": reason,
        },
    )
    # Move the refund into 'Under Review'.
    execute(
        "UPDATE refund_cases SET status = 'Under Review' WHERE refund_id = :rid",
        {"rid": refund_id},
    )
    return {"approval_id": new_id, "status": "Pending", "refund_id": refund_id}


create_approval_request_tool = StructuredTool.from_function(
    func=_create_approval_request,
    name="create_approval_request",
    description=(
        "Create a Pending approval_request for a refund that needs human review. "
        "Also moves the refund_case to 'Under Review'."
    ),
    args_schema=_CreateApproval,
)


def _list_pending_approvals() -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT a.approval_id, a.refund_id, a.requested_by, a.amount, a.comments, "
        "a.request_date, r.customer_id, r.order_id, r.reason "
        "FROM approval_requests a LEFT JOIN refund_cases r ON r.refund_id = a.refund_id "
        "WHERE a.status = 'Pending' ORDER BY a.request_date ASC"
    )


list_pending_approvals_tool = StructuredTool.from_function(
    func=_list_pending_approvals,
    name="list_pending_approvals",
    description="List all Pending approval_requests joined with their refund_case context.",
    args_schema=BaseModel,
)


class _ResolveApproval(BaseModel):
    approval_id: str
    decision: str = Field(description="Either 'Approved' or 'Rejected'.")
    approver: str = Field(description="Name of the human approver.")
    comments: str | None = None


def _resolve_approval_request(
    approval_id: str, decision: str, approver: str, comments: str | None = None
) -> dict[str, Any]:
    if decision not in {"Approved", "Rejected"}:
        return {"error": "decision must be 'Approved' or 'Rejected'"}
    now = datetime.now(UTC).date().isoformat()
    execute(
        "UPDATE approval_requests SET status = :s, approver = :ap, "
        "decision_date = :dd, comments = COALESCE(:c, comments) "
        "WHERE approval_id = :aid",
        {"s": decision, "ap": approver, "dd": now, "c": comments, "aid": approval_id},
    )
    ap = fetch_one(
        "SELECT refund_id FROM approval_requests WHERE approval_id = :aid",
        {"aid": approval_id},
    )
    if ap:
        new_refund_status = "Approved" if decision == "Approved" else "Rejected"
        execute(
            "UPDATE refund_cases SET status = :s, resolution_date = :rd WHERE refund_id = :rid",
            {"s": new_refund_status, "rd": now, "rid": ap["refund_id"]},
        )
        return {"approval_id": approval_id, "decision": decision, "refund_id": ap["refund_id"]}
    return {"approval_id": approval_id, "decision": decision}


resolve_approval_request_tool = StructuredTool.from_function(
    func=_resolve_approval_request,
    name="resolve_approval_request",
    description=(
        "Human operator resolves a pending approval_request. Also updates the linked "
        "refund_case status ('Approved' or 'Rejected')."
    ),
    args_schema=_ResolveApproval,
)


# ---------- exported tool sets ----------

ORDER_TOOLS = [
    get_customer_tool,
    get_order_tool,
    get_order_items_tool,
    get_shipment_by_order_tool,
    list_customer_orders_tool,
]

RETURNS_TOOLS = [
    get_customer_tool,
    get_order_tool,
    get_order_items_tool,
    get_shipment_by_order_tool,
    list_refunds_for_customer_tool,
    create_refund_case_tool,
    create_approval_request_tool,
    update_refund_status_tool,
]

INSIGHT_TOOLS = [
    get_customer_tool,
    list_customer_orders_tool,
    list_refunds_for_customer_tool,
]

OPS_TOOLS = [
    list_pending_approvals_tool,
    resolve_approval_request_tool,
]


def _uid() -> str:  # kept for future use (case-note IDs etc.)
    return uuid.uuid4().hex[:8]
