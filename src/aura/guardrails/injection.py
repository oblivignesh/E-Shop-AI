"""Heuristic prompt-injection detector.

For the MVP we use a curated set of override phrases + a signature match.
This is intentionally conservative: false positives are safer than false
negatives in an agent that can create refunds. A stronger LLM-classifier
variant can be swapped in behind the same `detect()` interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|system)\b.{0,20}\b(instructions?|prompt|rules?)\b",
        re.IGNORECASE,
    )),
    ("role_switch", re.compile(
        r"\byou are now\b|\bact as\b.{0,30}\b(admin|developer|system)\b|\bdeveloper mode\b",
        re.IGNORECASE,
    )),
    ("reveal_system", re.compile(
        r"\b(reveal|print|show|leak)\b.{0,20}\b(system prompt|hidden instructions|your instructions)\b",
        re.IGNORECASE,
    )),
    ("tool_hijack", re.compile(
        r"\b(call|use|invoke)\b.{0,20}\b(create_refund_case|resolve_approval)\b.{0,40}\b(without|skip|bypass)\b",
        re.IGNORECASE,
    )),
    ("policy_bypass", re.compile(
        r"\b(bypass|skip|ignore|override)\b.{0,20}\b(policy|approval|guardrail|check|threshold)\b",
        re.IGNORECASE,
    )),
]


@dataclass
class InjectionResult:
    detected: bool
    matched_rules: list[str]

    @property
    def reason(self) -> str:
        return ", ".join(self.matched_rules) if self.matched_rules else ""


def detect(text: str) -> InjectionResult:
    matched = [name for name, pat in _PATTERNS if pat.search(text)]
    return InjectionResult(detected=bool(matched), matched_rules=matched)
