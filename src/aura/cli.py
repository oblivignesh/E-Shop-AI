"""CLI entry point.

Currently supports:
- `aura demo`         : run 3 scripted turns against the graph (needs ANTHROPIC_API_KEY)
- `aura approvals`    : list pending approvals from the DB
- `aura sanity`       : verify DB + Chroma index without touching the LLM
"""

from __future__ import annotations

import json
import uuid

import typer
from rich.console import Console
from rich.table import Table

from aura.config import settings

app = typer.Typer(help="AURA CLI", no_args_is_help=True)
console = Console()


@app.command()
def sanity() -> None:
    """Verify DB tables, row counts, and policy index."""
    from aura.db import fetch_one
    from aura.tools.policy_tool import _search_policy

    tables = [
        "customers",
        "orders",
        "order_items",
        "shipments",
        "refund_cases",
        "approval_requests",
    ]
    t = Table(title="Sanity check")
    t.add_column("Table")
    t.add_column("Rows", justify="right")
    for tbl in tables:
        r = fetch_one(f"SELECT COUNT(*) AS n FROM {tbl}")
        t.add_row(tbl, str(r["n"] if r else 0))
    console.print(t)

    hits = _search_policy("what is the refund window for electronics", k=1)
    if hits:
        console.print(
            f"[green]Policy RAG OK[/green] — top hit from {hits[0]['source']}"
        )
    else:
        console.print("[red]Policy RAG returned 0 hits[/red]")


@app.command()
def approvals() -> None:
    """List Pending approvals."""
    from aura.tools.db_tools import _list_pending_approvals

    rows = _list_pending_approvals()
    if not rows:
        console.print("[yellow]No pending approvals.[/yellow]")
        return
    t = Table(title="Pending approvals")
    for col in ("approval_id", "refund_id", "amount", "reason", "customer_id"):
        t.add_column(col)
    for r in rows:
        t.add_row(
            r.get("approval_id", ""),
            r.get("refund_id", ""),
            str(r.get("amount", "")),
            (r.get("reason") or "")[:40],
            r.get("customer_id", "") or "",
        )
    console.print(t)


@app.command()
def demo() -> None:
    """Run three scripted conversation turns end-to-end."""
    if not settings.anthropic_api_key:
        console.print(
            "[red]ANTHROPIC_API_KEY not set.[/red] Add it to .env before running the demo."
        )
        raise typer.Exit(1)

    from langchain_core.messages import HumanMessage

    from aura.graph import build_graph, get_checkpointer

    ckpt = get_checkpointer()
    graph = build_graph(checkpointer=ckpt)

    scripts = [
        ("ops", None, "Where is order ORD00001? Customer CUST0047 is asking."),
        (
            "ops",
            None,
            "Customer CUST0091 wants a refund on order ORD00004 for ₹998 — reason: item damaged on arrival.",
        ),
        ("ops", None, "Give me a customer profile for CUST0047."),
    ]
    for i, (role, auth, msg) in enumerate(scripts, 1):
        thread_id = f"demo-{uuid.uuid4().hex[:6]}"
        console.rule(f"[bold]Turn {i}[/bold]  role={role}  thread={thread_id}")
        console.print(f"[cyan]User:[/cyan] {msg}")
        cfg = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(
            {
                "messages": [HumanMessage(msg)],
                "role": role,
                "authenticated_customer_id": auth,
            },
            config=cfg,
        )
        console.print(f"[green]AURA:[/green] {result.get('final_reply', '(no reply)')}")
        if result.get("pending_approval"):
            console.print(
                f"[yellow]HITL:[/yellow] {json.dumps(result['pending_approval'], indent=2)}"
            )


if __name__ == "__main__":
    app()
