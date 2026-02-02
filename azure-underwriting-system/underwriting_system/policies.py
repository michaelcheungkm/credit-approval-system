from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_community.vectorstores import Chroma
except Exception:  # pragma: no cover
    Chroma = None  # type: ignore


@dataclass(frozen=True)
class PolicyStore:
    """
    Wrapper that supports vector retrieval when embeddings are configured,
    otherwise falls back to simple keyword snippets.
    """

    mode: str  # "vector" | "keyword"
    vectorstore: object | None
    raw_pages: List[str]


def _load_pdf_pages(pdf_path: str) -> List[str]:
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    return [d.page_content for d in docs]


def create_policy_store(
    pdf_path: str,
    embeddings: object | None,
    persist_dir: str,
    collection_name: str = "underwriting_policies",
) -> PolicyStore:
    pages = _load_pdf_pages(pdf_path)

    if embeddings is None or Chroma is None:
        return PolicyStore(mode="keyword", vectorstore=None, raw_pages=pages)

    # If a persisted Chroma exists, reuse it (avoid re-embedding the whole PDF).
    os.makedirs(persist_dir, exist_ok=True)
    try:
        if any(os.scandir(persist_dir)):
            vs = Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,  # type: ignore[arg-type]
                persist_directory=persist_dir,
            )
            return PolicyStore(mode="vector", vectorstore=vs, raw_pages=pages)
    except Exception:
        # Fall back to rebuilding if open fails
        pass

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    # rebuild chunks from pages
    documents = []
    for i, page in enumerate(pages):
        documents.append({"page_content": page, "metadata": {"page": i + 1}})

    # Convert to LangChain Document only when needed to avoid import churn
    from langchain_core.documents import Document

    doc_objs = [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in documents]
    chunks = splitter.split_documents(doc_objs)

    vs = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=collection_name,
        persist_directory=persist_dir,
    )

    return PolicyStore(mode="vector", vectorstore=vs, raw_pages=pages)


def retrieve_relevant_policies(query: str, store: PolicyStore, k: int = 6) -> str:
    if store.mode == "vector" and store.vectorstore is not None:
        docs = store.vectorstore.similarity_search(query, k=k)  # type: ignore[attr-defined]
        section_map: dict[str, str] = {}
        for doc in docs:
            text = (doc.page_content or "").strip()
            match = re.match(r"^\d+\.\d+\s+[A-Za-z ].+", text)
            section = match.group(0) if match else "OTHER"
            if section not in section_map:
                section_map[section] = text
            elif text not in section_map[section]:
                section_map[section] += "\n" + text
        return "\n\n".join(section_map.values()).strip()

    # Keyword fallback (no embeddings configured)
    q_terms = [t for t in re.split(r"\W+", query.lower()) if len(t) >= 4][:10]
    hits: List[str] = []
    for page in store.raw_pages:
        p_low = page.lower()
        if any(t in p_low for t in q_terms):
            # return a small snippet
            snippet = page.strip()
            if len(snippet) > 1200:
                snippet = snippet[:1200] + " ..."
            hits.append(snippet)
        if len(hits) >= k:
            break
    return "\n\n".join(hits).strip()

