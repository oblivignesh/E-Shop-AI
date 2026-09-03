"""Comms tool: drafts a customer-facing reply (never sends).

In the MVP the finalizer node uses this to compose the outbound message so the
core reasoning trace stays separate from customer prose. The tool itself is a
thin template; the calling agent supplies the summary and tone.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class _DraftReply(BaseModel):
    subject_hint: str = Field(description="Short subject like 'Refund for ORD00001'.")
    summary: str = Field(description="What was decided and any next steps.")
    tone: str = Field(default="empathetic-professional", description="Tone label.")
    case_reference: str | None = Field(
        default=None, description="Refund or approval id to include in the reply."
    )


def _draft_customer_reply(
    subject_hint: str,
    summary: str,
    tone: str = "empathetic-professional",
    case_reference: str | None = None,
) -> dict[str, str]:
    ref_line = f"\nReference: {case_reference}\n" if case_reference else ""
    body = (
        f"Hi there,\n\n"
        f"Thanks for reaching out about {subject_hint}. "
        f"{summary.strip()}"
        f"{ref_line}\n"
        "If you have any questions, just reply to this message.\n\n"
        "— AURA Customer Care"
    )
    return {"subject": subject_hint, "body": body, "tone": tone}


draft_customer_reply_tool = StructuredTool.from_function(
    func=_draft_customer_reply,
    name="draft_customer_reply",
    description=(
        "Compose a customer-facing reply (email-style) from a decision summary. "
        "Does NOT send anything. Include the refund_id or approval_id as case_reference."
    ),
    args_schema=_DraftReply,
)
