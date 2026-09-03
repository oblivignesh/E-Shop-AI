"""Lightweight PII detection & redaction using regex.

Covers the common shapes in this dataset: emails, phone numbers (Indian +
generic international), credit-card-like sequences. Presidio can be swapped in
later without changing the interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-]{8,}\d)(?!\d)")
_CC_RE = re.compile(r"(?<!\d)(?:\d[\s-]?){13,19}(?!\d)")


@dataclass
class PIIResult:
    redacted_text: str
    hits: list[str]


def redact(text: str) -> PIIResult:
    hits: list[str] = []

    def _sub(pattern: re.Pattern[str], token: str, s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            hits.append(f"{token}:{m.group(0)}")
            return f"[REDACTED_{token}]"

        return pattern.sub(repl, s)

    out = text
    out = _sub(_EMAIL_RE, "EMAIL", out)
    out = _sub(_CC_RE, "CC", out)
    out = _sub(_PHONE_RE, "PHONE", out)
    return PIIResult(redacted_text=out, hits=hits)


def contains_pii(text: str) -> bool:
    return bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text) or _CC_RE.search(text))
