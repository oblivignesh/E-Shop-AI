"""AURA — Streamlit UI.

Two tabs:
  1. Customer chat — talk to the agent, see the final reply and per-turn trace.
  2. Ops console — pending approvals + resolve buttons that resume interrupted graphs.

Run:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Ensure src/ is importable regardless of where streamlit is launched from.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

# Load .env before anything imports aura.config.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

import streamlit as st  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.types import Command  # noqa: E402

from aura.config import settings  # noqa: E402
from aura.graph import build_graph, get_checkpointer  # noqa: E402
from aura.tools.db_tools import (  # noqa: E402
    _list_pending_approvals,
    _resolve_approval_request,
)

st.set_page_config(page_title="AURA — E-commerce Agent", page_icon="🛒", layout="wide")

# ---- Cached graph so we don't rebuild on every rerun ---------------------------


@st.cache_resource
def _get_graph():
    ckpt = get_checkpointer()
    return build_graph(checkpointer=ckpt)


graph = _get_graph()


# ---- Session state ------------------------------------------------------------

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"chat-{uuid.uuid4().hex[:8]}"
if "history" not in st.session_state:
    st.session_state.history: list[dict[str, str]] = []
if "pending_interrupt" not in st.session_state:
    st.session_state.pending_interrupt: dict | None = None
if "role" not in st.session_state:
    st.session_state.role = ""
if "auth_customer_id" not in st.session_state:
    st.session_state.auth_customer_id = ""
if "auth_customer_name" not in st.session_state:
    st.session_state.auth_customer_name = ""
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False


def _find_customer_by_name(first_name: str, last_name: str) -> list[dict]:
    from aura.db import fetch_all

    rows = fetch_all(
        "SELECT customer_id, first_name || ' ' || last_name AS name "
        "FROM customers WHERE lower(first_name) = lower(:first_name) "
        "AND lower(last_name) = lower(:last_name) ORDER BY customer_id",
        {"first_name": first_name.strip(), "last_name": last_name.strip()},
    )
    return rows


def _get_customer_orders(customer_id: str) -> list[dict]:
    from aura.db import fetch_all

    customer_id = customer_id.strip()
    if not customer_id:
        return []
    return fetch_all(
        "SELECT order_id, total_amount FROM orders WHERE customer_id = :cid "
        "ORDER BY order_date DESC",
        {"cid": customer_id},
    )


def _reset_session() -> None:
    st.session_state.thread_id = f"chat-{uuid.uuid4().hex[:8]}"
    st.session_state.history = []
    st.session_state.pending_interrupt = None


def _log_out() -> None:
    st.session_state.authenticated = False
    st.session_state.role = ""
    st.session_state.auth_customer_id = ""
    st.session_state.auth_customer_name = ""
    _reset_session()


# ---- Login gate ----------------------------------------------------------------

if not st.session_state.authenticated:
    st.title("🛒 AURA — Sign in")
    tab_customer, tab_admin = st.tabs(["👤 Customer login", "🛠 Admin login"])

    with tab_customer:
        st.caption("Sign in with your first and last name as registered on your account.")
        with st.form("customer_login_form"):
            first_name = st.text_input("First name")
            last_name = st.text_input("Last name")
            submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            if not first_name.strip() or not last_name.strip():
                st.error("Please enter both first and last name.")
            else:
                matches = _find_customer_by_name(first_name, last_name)
                if not matches:
                    st.error("No customer found with that name. Please check spelling.")
                elif len(matches) == 1:
                    st.session_state.authenticated = True
                    st.session_state.role = "customer"
                    st.session_state.auth_customer_id = matches[0]["customer_id"]
                    st.session_state.auth_customer_name = matches[0]["name"]
                    _reset_session()
                    st.rerun()
                else:
                    st.session_state._customer_name_matches = matches

        matches = st.session_state.get("_customer_name_matches")
        if matches:
            st.info("Multiple customers matched that name — pick your account:")
            options = [f"{m['customer_id']} — {m['name']}" for m in matches]
            picked = st.selectbox("Which one is you?", options, key="disambiguate_customer")
            if st.button("Confirm sign in", use_container_width=True):
                cid = picked.split(" ", 1)[0]
                chosen = next(m for m in matches if m["customer_id"] == cid)
                st.session_state.authenticated = True
                st.session_state.role = "customer"
                st.session_state.auth_customer_id = chosen["customer_id"]
                st.session_state.auth_customer_name = chosen["name"]
                st.session_state.pop("_customer_name_matches", None)
                _reset_session()
                st.rerun()

    with tab_admin:
        st.caption("Internal ops staff sign-in.")
        with st.form("admin_login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            admin_submitted = st.form_submit_button("Sign in", use_container_width=True)
        if admin_submitted:
            if username == "admin" and password == "admin":
                st.session_state.authenticated = True
                st.session_state.role = "ops"
                st.session_state.auth_customer_id = ""
                st.session_state.auth_customer_name = ""
                _reset_session()
                st.rerun()
            else:
                st.error("Invalid username or password.")

    st.stop()


# ---- Sidebar: session controls + config ---------------------------------------

with st.sidebar:
    st.header("Account")
    if st.session_state.role == "customer":
        st.caption(
            f"Signed in as **{st.session_state.auth_customer_name}** "
            f"(`{st.session_state.auth_customer_id}`)"
        )
    else:
        st.caption("Signed in as **admin** (ops)")
    if st.button("Log out", use_container_width=True):
        _log_out()
        st.rerun()

    st.divider()
    st.header("Session")
    st.caption(f"thread_id: `{st.session_state.thread_id}`")
    if st.button("New conversation", use_container_width=True):
        st.session_state.thread_id = f"chat-{uuid.uuid4().hex[:8]}"
        st.session_state.history = []
        st.session_state.pending_interrupt = None
        st.rerun()

    st.divider()
    st.header("Demo prompts")
    if st.session_state.role == "ops":
        demo_cid = st.text_input(
            "Customer ID for demo prompts",
            value="CUST0047",
            key="demo_customer_id",
            help="Enter a customer id — the buttons below will use it.",
        )
        demo_orders = _get_customer_orders(demo_cid)
        order_ids = [o["order_id"] for o in demo_orders]
        if demo_cid.strip() and not order_ids:
            st.caption("⚠️ No orders found for this customer id.")

        lookup_order = order_ids[0] if order_ids else "ORD00001"
        small_refund_order = order_ids[0] if order_ids else "ORD00004"
        hitl_refund_order = order_ids[1] if len(order_ids) > 1 else lookup_order

        demos = [
            ("Order lookup", f"Where is order {lookup_order}? Customer {demo_cid} is asking."),
            (
                "Small refund (auto)",
                f"Customer {demo_cid} wants a refund on order {small_refund_order} for ₹998 — "
                "reason: item damaged on arrival.",
            ),
            (
                "High-value refund (HITL)",
                f"Customer {demo_cid} requests a refund on order {hitl_refund_order} for ₹8,500 — "
                "reason: defective product.",
            ),
            ("Customer profile", f"Give me a customer profile for {demo_cid}."),
        ]
    else:
        # Customer mode — first-person prompts. Ids are examples; the customer's
        # own orders are dynamic. We keep prompts generic so any signed-in
        # customer can run them (they'll get identity-refusal or success
        # depending on ownership, which itself is a useful demo).
        demos = [
            ("Where is my last order?", "Where is my most recent order?"),
            ("My order history", "How many orders have I placed and what did I spend?"),
            (
                "Refund on my order",
                "I want a refund on my most recent order — the item arrived damaged.",
            ),
        ]
    for label, prompt in demos:
        if st.button(label, use_container_width=True, key=f"demo-{label}"):
            if st.session_state.role == "ops" and not demo_cid.strip():
                st.warning("Enter a customer id first.")
            else:
                st.session_state._prefill = prompt
                st.rerun()


# ---- Tabs ---------------------------------------------------------------------

is_ops = st.session_state.role == "ops"

if is_ops:
    chat_tab_title = "💬 Ops chat"
    tab_chat, tab_ops, tab_data = st.tabs(
        [chat_tab_title, "🛡 Ops console", "📊 Data browser"]
    )
else:
    chat_tab_title = "💬 My chat"
    (tab_chat,) = st.tabs([chat_tab_title])
    tab_ops = None
    tab_data = None


# ---------- Chat tab ------------------------------------------------------------


def _run_graph(user_text: str) -> None:
    """Invoke the graph, capture pending_approval if it interrupts."""
    cfg = {"configurable": {"thread_id": st.session_state.thread_id}}
    # Persist role + auth id into state so specialists build the right persona.
    payload = {
        "messages": [HumanMessage(user_text)],
        "role": st.session_state.role,
        "authenticated_customer_id": st.session_state.auth_customer_id or None,
    }
    try:
        result = graph.invoke(payload, config=cfg)
    except Exception as e:  # noqa: BLE001
        st.session_state.history.append(
            {"role": "assistant", "content": f"⚠️ Error: {type(e).__name__}: {e}"}
        )
        return

    reply = result.get("final_reply") or "(no reply)"
    st.session_state.history.append({"role": "assistant", "content": reply})
    if result.get("pending_approval"):
        st.session_state.pending_interrupt = {
            **result["pending_approval"],
            "thread_id": st.session_state.thread_id,
        }


with tab_chat:
    st.title("AURA — E-commerce Operations Agent")
    if st.session_state.role == "customer":
        st.caption(
            f"You are chatting as customer **`{st.session_state.auth_customer_id}`**. "
            "AURA will only discuss orders and refunds on your account."
        )
        placeholder = "Ask about your order, request a refund, or check your profile…"
    else:
        st.caption(
            "You are the internal ops operator. AURA reports facts in third-person "
            "and can look up any customer, order, refund, or approval."
        )
        placeholder = (
            "Look up an order, refund, approval, or customer by id "
            "(e.g. 'profile for CUST0047')…"
        )

    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prefill = st.session_state.pop("_prefill", None)
    user_input = st.chat_input(placeholder)
    if prefill and not user_input:
        user_input = prefill

    if user_input:
        st.session_state.history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                _run_graph(user_input)
            st.markdown(st.session_state.history[-1]["content"])
        st.rerun()

    if st.session_state.pending_interrupt:
        if is_ops:
            st.warning(
                f"🕒 This turn produced approval "
                f"**{st.session_state.pending_interrupt.get('approval_id')}** "
                f"(refund `{st.session_state.pending_interrupt.get('refund_id')}`). "
                "Head to **Ops console** to resolve it."
            )
        else:
            st.warning(
                "🕒 Your refund request needs manager approval. "
                "You'll be notified once it's resolved."
            )


# ---------- Ops console tab ----------------------------------------------------

if tab_ops is not None:
    with tab_ops:
        st.title("Ops console — pending approvals")
        st.caption(
            "Human-in-the-loop: approve or reject refund escalations from the agent."
        )

        approvals = _list_pending_approvals()
        if not approvals:
            st.success("No pending approvals. ✅")
        else:
            for ap in approvals:
                with st.expander(
                    f"{ap['approval_id']} · refund {ap['refund_id']} · "
                    f"{settings.currency_symbol}{float(ap['amount']):,.0f} · "
                    f"customer {ap.get('customer_id') or '?'}",
                    expanded=False,
                ):
                    cols = st.columns([2, 1])
                    with cols[0]:
                        st.markdown(f"**Reason on refund**: {ap.get('reason') or '—'}")
                        st.markdown(f"**Comments**: {ap.get('comments') or '—'}")
                        st.markdown(
                            f"**Requested by**: {ap.get('requested_by') or '—'}"
                        )
                        st.markdown(
                            f"**Requested on**: {ap.get('request_date') or '—'}"
                        )
                        approver = st.text_input(
                            "Approver name",
                            value="ops-user",
                            key=f"approver-{ap['approval_id']}",
                        )
                        note = st.text_area(
                            "Decision note (optional)",
                            key=f"note-{ap['approval_id']}",
                        )
                    with cols[1]:
                        if st.button(
                            "✅ Approve",
                            key=f"approve-{ap['approval_id']}",
                            use_container_width=True,
                        ):
                            res = _resolve_approval_request(
                                approval_id=ap["approval_id"],
                                decision="Approved",
                                approver=approver,
                                comments=note or None,
                            )
                            st.success(f"Approved: {res}")
                            # Resume any interrupted graph tied to this approval.
                            pi = st.session_state.pending_interrupt
                            if pi and pi.get("approval_id") == ap["approval_id"]:
                                cfg = {"configurable": {"thread_id": pi["thread_id"]}}
                                graph.invoke(Command(resume="Approved"), config=cfg)
                                st.session_state.pending_interrupt = None
                            st.rerun()
                        if st.button(
                            "❌ Reject",
                            key=f"reject-{ap['approval_id']}",
                            use_container_width=True,
                        ):
                            res = _resolve_approval_request(
                                approval_id=ap["approval_id"],
                                decision="Rejected",
                                approver=approver,
                                comments=note or None,
                            )
                            st.error(f"Rejected: {res}")
                            pi = st.session_state.pending_interrupt
                            if pi and pi.get("approval_id") == ap["approval_id"]:
                                cfg = {"configurable": {"thread_id": pi["thread_id"]}}
                                graph.invoke(Command(resume="Rejected"), config=cfg)
                                st.session_state.pending_interrupt = None
                            st.rerun()


# ---------- Data browser tab --------------------------------------------------

if tab_data is not None:
    with tab_data:
        st.title("Data browser")
        st.caption(
            "Browse the ingested SQLite database. Copy any id into a chat prompt, "
            "or use the quick prompt buttons at the bottom of each table."
        )

        import pandas as pd

        from aura.db import fetch_all

        QUERIES: dict[str, dict[str, str]] = {
            "Customers": {
                "sql": (
                    "SELECT customer_id, first_name || ' ' || last_name AS name, "
                    "email, city, state, customer_segment, signup_date "
                    "FROM customers ORDER BY customer_id"
                ),
                "id_col": "customer_id",
            },
            "Orders": {
                "sql": (
                    "SELECT order_id, customer_id, order_date, order_status, "
                    "total_amount, payment_method, order_channel "
                    "FROM orders ORDER BY order_date DESC"
                ),
                "id_col": "order_id",
            },
            "Order items": {
                "sql": (
                    "SELECT order_item_id, order_id, product_id, product_name, "
                    "category, quantity, unit_price, subtotal "
                    "FROM order_items ORDER BY order_item_id"
                ),
                "id_col": "order_item_id",
            },
            "Shipments": {
                "sql": (
                    "SELECT shipment_id, order_id, carrier, tracking_number, "
                    "ship_date, estimated_delivery_date, actual_delivery_date, "
                    "shipment_status FROM shipments ORDER BY ship_date DESC"
                ),
                "id_col": "shipment_id",
            },
            "Refund cases": {
                "sql": (
                    "SELECT refund_id, order_id, customer_id, reason, refund_amount, "
                    "status, request_date, resolution_date FROM refund_cases "
                    "ORDER BY request_date DESC"
                ),
                "id_col": "refund_id",
            },
            "Approval requests": {
                "sql": (
                    "SELECT approval_id, refund_id, requested_by, approver, "
                    "request_type, amount, status, request_date, decision_date "
                    "FROM approval_requests ORDER BY request_date DESC"
                ),
                "id_col": "approval_id",
            },
        }

        table_choice = st.selectbox("Table", list(QUERIES.keys()))
        meta = QUERIES[table_choice]
        rows = fetch_all(meta["sql"])
        df = pd.DataFrame(rows)

        # Simple text filter across all columns
        filter_text = st.text_input(
            "Filter (matches any column, case-insensitive)",
            placeholder="e.g. CUST0047, FedEx, Shipped, Premium…",
        )
        if filter_text:
            mask = df.astype(str).apply(
                lambda s: s.str.contains(filter_text, case=False, na=False)
            )
            df = df[mask.any(axis=1)]

        st.caption(f"{len(df)} rows")
        st.dataframe(df, use_container_width=True, hide_index=True, height=420)

        # Quick "prefill a chat prompt" helpers based on the current table
        st.subheader("Quick prompts from selected table")
        id_col = meta["id_col"]
        if id_col in df.columns and len(df):
            sample_id = str(df.iloc[0][id_col])

            col1, col2, col3, col4 = st.columns(4)
            if table_choice == "Customers":
                with col1:
                    if st.button("Customer profile", use_container_width=True):
                        st.session_state._prefill = (
                            f"Give me a customer profile for {sample_id}."
                        )
                        st.rerun()
                with col2:
                    if st.button("List orders", use_container_width=True):
                        st.session_state._prefill = (
                            f"How many orders has customer {sample_id} placed "
                            "and what's their spend?"
                        )
                        st.rerun()
            elif table_choice == "Orders":
                cid = str(df.iloc[0].get("customer_id", ""))
                with col1:
                    if st.button("Track this order", use_container_width=True):
                        st.session_state._prefill = (
                            f"Where is order {sample_id}? Customer {cid} is asking."
                        )
                        st.rerun()
                with col2:
                    if st.button("Refund (small)", use_container_width=True):
                        st.session_state._prefill = (
                            f"Customer {cid} wants a refund on order {sample_id} for ₹500 "
                            "— reason: item damaged on arrival."
                        )
                        st.rerun()
                with col3:
                    if st.button("Refund (HITL)", use_container_width=True):
                        st.session_state._prefill = (
                            f"Customer {cid} requests a refund on order {sample_id} "
                            "for ₹8,500 — reason: defective product."
                        )
                        st.rerun()
            elif table_choice == "Shipments":
                oid = str(df.iloc[0].get("order_id", ""))
                with col1:
                    if st.button("Track this shipment", use_container_width=True):
                        st.session_state._prefill = f"What's the status of order {oid}?"
                        st.rerun()
            elif table_choice == "Refund cases":
                with col1:
                    if st.button("Check refund status", use_container_width=True):
                        st.session_state._prefill = (
                            f"What's the status of refund case {sample_id}?"
                        )
                        st.rerun()

        st.info(
            "**Tip:** click any cell in the table above to select it, then use "
            "⌘/Ctrl+C to copy the id. Or type a custom message in the chat tab "
            "using ids from here."
        )
