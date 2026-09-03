"""RAG tool: `search_policy` retrieves policy chunks from the Chroma index."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_chroma import Chroma
from langchain_core.tools import StructuredTool
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel, Field

from aura.config import settings

COLLECTION = "aura_policies"


@lru_cache(maxsize=1)
def _get_store() -> Chroma:
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(settings.chroma_dir),
    )


class _PolicyQuery(BaseModel):
    query: str = Field(description="Natural language question about policy.")
    k: int = Field(default=4, ge=1, le=10, description="Number of chunks to return.")


def _search_policy(query: str, k: int = 4) -> list[dict[str, Any]]:
    store = _get_store()
    docs = store.similarity_search(query, k=k)
    return [
        {"source": d.metadata.get("source", "?"), "text": d.page_content}
        for d in docs
    ]


search_policy_tool = StructuredTool.from_function(
    func=_search_policy,
    name="search_policy",
    description=(
        "Search company policies (refund policy, return windows, shipping SLAs, "
        "fraud rules) and return the most relevant chunks. ALWAYS call this "
        "before recommending a refund decision."
    ),
    args_schema=_PolicyQuery,
)
