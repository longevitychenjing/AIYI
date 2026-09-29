from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
from typing import Protocol, Sequence

import httpx


@dataclass(frozen=True)
class Citation:
    citation_id: str
    source_id: str
    title: str
    locator: str
    source_url: str


@dataclass(frozen=True)
class KnowledgeChunk:
    citation: Citation
    content: str
    tags: tuple[str, ...] = ()


class Retriever(Protocol):
    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]: ...


class KeywordRetriever:
    """Development fallback; production deployments replace this with Qdrant retrieval."""

    def __init__(self, chunks: Sequence[KnowledgeChunk]) -> None:
        self._chunks = tuple(chunks)

    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]:
        tokens = set(re.findall(r"[A-Za-z0-9]+", query.lower())) | {character for character in query if "\u4e00" <= character <= "\u9fff"}
        ranked = sorted(
            self._chunks,
            key=lambda chunk: sum(token in f"{chunk.content} {' '.join(chunk.tags)}".lower() for token in tokens),
            reverse=True,
        )
        matched = [chunk for chunk in ranked if any(token in chunk.content or token in chunk.tags for token in tokens)]
        return matched[:limit] or ranked[:limit]


class SQLiteRetriever:
    """Local retrieval over the source texts already imported into SQLite.

    This is deliberately simple lexical retrieval: it keeps the first local
    RAG loop usable without a second model or a running vector database.
    """

    def __init__(self, database_path: Path) -> None:
        if not database_path.exists():
            raise FileNotFoundError(f"Knowledge database not found: {database_path}")
        self._chunks = self._load_chunks(database_path)

    @staticmethod
    def _load_chunks(database_path: Path) -> tuple[KnowledgeChunk, ...]:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT source_texts.id, source_texts.hexagram_key,
                       source_texts.line_position, source_texts.text_kind,
                       source_texts.body, source_texts.locator,
                       editions.title, editions.source_url,
                       hexagrams.name
                FROM source_texts
                JOIN editions ON editions.id = source_texts.edition_id
                JOIN hexagrams ON hexagrams.binary_key = source_texts.hexagram_key
                ORDER BY source_texts.hexagram_key, source_texts.text_kind,
                         source_texts.line_position
                """
            ).fetchall()
        finally:
            connection.close()

        chunks: list[KnowledgeChunk] = []
        for row in rows:
            line_tag = f"爻{row['line_position']}" if row["line_position"] else ""
            chunks.append(
                KnowledgeChunk(
                    citation=Citation(
                        citation_id=str(row["id"]),
                        source_id=str(row["id"].split(":", 1)[0]),
                        title=f"{row['title']} · {row['name']}",
                        locator=str(row["locator"]),
                        source_url=str(row["source_url"]),
                    ),
                    content=str(row["body"]),
                    tags=(str(row["name"]), str(row["text_kind"]), line_tag),
                )
            )
        return tuple(chunks)

    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]:
        normalized_query = query.lower()
        chinese_terms = {
            term
            for term in re.findall(r"[\u4e00-\u9fff]{2,}", normalized_query)
            if len(term) >= 2
        }
        query_characters = {
            character
            for term in chinese_terms
            for character in term
            if character not in "的了和与是我你在有请如何什么这个可以结合说明一下"
        }
        latin_terms = set(re.findall(r"[a-z0-9_]+", normalized_query))

        def score(chunk: KnowledgeChunk) -> tuple[int, int]:
            searchable = f"{chunk.citation.title} {chunk.content} {' '.join(chunk.tags)}".lower()
            exact_term_score = sum(8 for term in chinese_terms | latin_terms if term in searchable)
            character_score = sum(1 for character in query_characters if character in searchable)
            tag_score = sum(12 for tag in chunk.tags if tag and tag.lower() in normalized_query)
            return exact_term_score + character_score + tag_score, len(chunk.content)

        ranked = sorted(self._chunks, key=score, reverse=True)
        return [chunk for chunk in ranked[:limit] if score(chunk)[0] > 0] or ranked[:limit]


class QdrantRetriever:
    def __init__(self, qdrant_url: str, collection: str, embedding_base_url: str, embedding_api_key: str, embedding_model: str) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._collection = collection
        self._embedding_base_url = embedding_base_url.rstrip("/")
        self._embedding_api_key = embedding_api_key
        self._embedding_model = embedding_model

    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]:
        embedding_response = httpx.post(
            f"{self._embedding_base_url}/embeddings",
            headers={"Authorization": f"Bearer {self._embedding_api_key}"},
            json={"model": self._embedding_model, "input": query},
            timeout=30,
        )
        embedding_response.raise_for_status()
        vector = embedding_response.json()["data"][0]["embedding"]
        search_response = httpx.post(
            f"{self._qdrant_url}/collections/{self._collection}/points/search",
            json={"vector": vector, "limit": limit, "with_payload": True},
            timeout=15,
        )
        search_response.raise_for_status()
        chunks: list[KnowledgeChunk] = []
        for point in search_response.json().get("result", []):
            payload = point["payload"]
            chunks.append(
                KnowledgeChunk(
                    citation=Citation(
                        citation_id=str(payload["content_hash"]),
                        source_id=str(payload["source_id"]),
                        title=str(payload["title"]),
                        locator=str(payload["locator"]),
                        source_url=str(payload["source_url"]),
                    ),
                    content=str(payload["content"]),
                    tags=tuple(str(tag) for tag in payload.get("tags", [])),
                )
            )
        return chunks


def load_sample_chunks() -> list[KnowledgeChunk]:
    source = Path(__file__).resolve().parents[5] / "data" / "sources" / "sample" / "zhouyi.md"
    if not source.exists():
        return []
    content = source.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return [
        KnowledgeChunk(
            citation=Citation(
                citation_id="zhouyi-sample-001",
                source_id="zhouyi-sample",
                title="《周易》样例摘录",
                locator="样例第 1 段",
                source_url="https://ctext.org/book-of-changes/zh",
            ),
            content=content,
            tags=("周易", "卦", "变卦", "事业", "关系"),
        )
    ]


def build_retriever() -> Retriever:
    mode = os.getenv("YIJING_RETRIEVER", "sqlite").lower()
    if mode in {"sample", "keyword"}:
        return KeywordRetriever(load_sample_chunks())
    if mode in {"local", "sqlite"}:
        database_path = Path(os.getenv("YIJING_KNOWLEDGE_DB", str(_default_database_path())))
        if database_path.exists():
            return SQLiteRetriever(database_path)
        return KeywordRetriever(load_sample_chunks())
    if mode != "qdrant":
        raise ValueError(f"Unsupported YIJING_RETRIEVER: {mode}")
    required = ("EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Qdrant retrieval requires: {', '.join(missing)}")
    return QdrantRetriever(
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        collection=os.getenv("QDRANT_COLLECTION", "yijing_sources"),
        embedding_base_url=os.environ["EMBEDDING_BASE_URL"],
        embedding_api_key=os.environ["EMBEDDING_API_KEY"],
        embedding_model=os.environ["EMBEDDING_MODEL"],
    )


def _default_database_path() -> Path:
    return Path(__file__).resolve().parents[5] / "data" / "knowledge" / "yijing.db"
