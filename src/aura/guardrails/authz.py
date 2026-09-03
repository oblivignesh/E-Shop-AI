"""Authorization guard for destructive refund actions and cross-customer data access.

Wraps `update_refund_status` and `resolve_approval_request` calls so an agent
cannot mark a refund `Approved`/`Completed` without either (a) the amount being
strictly under the auto-approve threshold, or (b) an accompanying approval id
whose status is `Approved`.

Also enforces per-request customer scoping: when a signed-in shopper (role =
"customer") is chatting, every data-access tool must be checked against the
authenticated customer_id *in code*, not just via LLM system-prompt wording.
Prompts can be ignored or bypassed by the model; this module is the actual
security boundary (OWASP A01: Broken Access Control).

The check is enforced at the tool boundary, so even if an agent misbehaves in
its chain-of-thought it still cannot execute an unauthorized write or read.
"""

from __future__ import annotations

from contextvars import ContextVar

from aura.config import settings
from aura.db import fetch_one


class AuthorizationError(RuntimeError):
    """Raised when an agent attempts an unauthorized privileged read or write."""


# ---------------------------------------------------------------------------
# Per-turn identity context
# ---------------------------------------------------------------------------
#
# Set once per graph invocation (see aura.graph._run_specialist) so every tool
# call made during that turn can check "is this data scoped to whoever is
# actually signed in?" without threading the value through every function
# signature.

_current_role: ContextVar[str] = ContextVar("_current_role", default="ops")
_current_customer_id: ContextVar[str | None] = ContextVar("_current_customer_id", default=None)


def set_auth_context(role: str | None, customer_id: str | None) -> None:
    """Bind the current request's role + authenticated customer_id.

    Must be called before any tool invocation for the turn. `role="ops"` (the
    default) disables scoping entirely, matching internal staff's ability to
    look up any customer.
    """
    _current_role.set(role or "ops")
    _current_customer_id.set(customer_id)


def assert_customer_scope(customer_id: str | None) -> None:
    """Raise AuthorizationError if a signed-in customer is reaching outside their
    own account.

    No-op for role="ops". For role="customer", `customer_id` (the id owning the
    record being accessed) must exactly match the authenticated customer_id.
    """
    if _current_role.get() != "customer":
        return
    auth_id = _current_customer_id.get()
    if not auth_id or customer_id != auth_id:
        raise AuthorizationError(
            "Access denied: signed-in customers may only access their own account data."
        )


def assert_can_approve_refund(refund_id: str) -> None:
    """Raise AuthorizationError unless the refund is safe to Approve/Complete."""
    row = fetch_one(
        "SELECT refund_amount, status FROM refund_cases WHERE refund_id = :rid",
        {"rid": refund_id},
    )
    if not row:
        raise AuthorizationError(f"refund_id {refund_id!r} not found")

    amount = float(row["refund_amount"] or 0)
    if amount < settings.refund_auto_approve_max:
        return  # under threshold → agent may auto-approve

    # At/over threshold → require a resolved Approved approval_request.
    ap = fetch_one(
        "SELECT status FROM approval_requests WHERE refund_id = :rid "
        "ORDER BY request_date DESC LIMIT 1",
        {"rid": refund_id},
    )
    if not ap or ap["status"] != "Approved":
        raise AuthorizationError(
            f"refund {refund_id} amount {amount} {settings.currency_code} "
            f">= auto-approve max ({settings.refund_auto_approve_max}); "
            "a resolved 'Approved' approval_request is required."
        )
