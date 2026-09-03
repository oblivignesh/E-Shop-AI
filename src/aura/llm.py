"""LLM factory: returns configured `ChatAnthropic` instances."""

from __future__ import annotations

from functools import lru_cache

from langchain_anthropic import ChatAnthropic

from aura.config import settings


@lru_cache(maxsize=4)
def get_llm(role: str = "agent", temperature: float = 0.1) -> ChatAnthropic:
    model = settings.agent_model if role == "agent" else settings.router_model
    return ChatAnthropic(
        model=model,
        temperature=temperature,
        api_key=settings.anthropic_api_key or None,
        max_tokens=1024,
    )
