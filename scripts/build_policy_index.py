"""Build (or rebuild) the ChromaDB policy index used by the RAG tool.

Reads every .md file in policies/, chunks with RecursiveCharacterTextSplitter,
embeds using a local sentence-transformers model (no API cost), and persists
to data/chroma/. Idempotent.

Run:
    python scripts/build_policy_index.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aura.config import settings  # noqa: E402

console = Console()

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
COLLECTION = "aura_policies"


def main() -> int:
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    policies_dir = settings.policies_dir
    if not policies_dir.exists():
        console.print(f"[red]No policies dir at {policies_dir}[/red]")
        return 1

    md_files = sorted(policies_dir.glob("*.md"))
    if not md_files:
        console.print(f"[red]No .md files in {policies_dir}[/red]")
        return 1

    # Fresh rebuild to avoid duplicate chunks.
    if settings.chroma_dir.exists():
        shutil.rmtree(settings.chroma_dir)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    texts: list[str] = []
    metadatas: list[dict] = []
    for md in md_files:
        content = md.read_text(encoding="utf-8")
        for chunk in splitter.split_text(content):
            texts.append(chunk)
            metadatas.append({"source": md.name})

    Chroma.from_texts(
        texts=texts,
        metadatas=metadatas,
        embedding=embeddings,
        collection_name=COLLECTION,
        persist_directory=str(settings.chroma_dir),
    )
    console.print(
        f"[green]Indexed[/green] {len(texts)} chunks from {len(md_files)} policy files "
        f"into {settings.chroma_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
