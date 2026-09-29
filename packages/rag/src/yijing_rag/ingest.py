import argparse
import hashlib
import os
from pathlib import Path
from typing import Iterable

import httpx

from .source import SourceDocument, load_manifest


def split_markdown(text: str, max_characters: int = 700) -> list[tuple[str, str]]:
    heading = "正文"
    chunks: list[tuple[str, str]] = []
    buffer = ""
    for line in text.splitlines():
        if line.startswith("#"):
            if buffer.strip():
                chunks.extend((heading, item) for item in _split_buffer(buffer, max_characters))
                buffer = ""
            heading = line.lstrip("#").strip() or heading
        else:
            buffer += f"{line}\n"
    if buffer.strip():
        chunks.extend((heading, item) for item in _split_buffer(buffer, max_characters))
    return chunks


def _split_buffer(buffer: str, max_characters: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in buffer.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_characters:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def fake_embedding(text: str, dimensions: int = 64) -> list[float]:
    values = [0.0] * dimensions
    for character in text:
        values[ord(character) % dimensions] += 1.0
    magnitude = sum(value * value for value in values) ** 0.5 or 1.0
    return [value / magnitude for value in values]


def openai_embedding(text: str) -> list[float]:
    base_url = os.environ["EMBEDDING_BASE_URL"].rstrip("/")
    response = httpx.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {os.environ['EMBEDDING_API_KEY']}"},
        json={"model": os.environ["EMBEDDING_MODEL"], "input": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def build_points(documents: Iterable[SourceDocument], use_fake_embeddings: bool) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for document in documents:
        for index, (locator, content) in enumerate(split_markdown(document.path.read_text(encoding="utf-8"))):
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            points.append(
                {
                    "id": content_hash,
                    "vector": fake_embedding(content) if use_fake_embeddings else openai_embedding(content),
                    "payload": {
                        "source_id": document.source_id,
                        "title": document.title,
                        "edition": document.edition,
                        "license_basis": document.license_basis,
                        "source_url": document.source_url,
                        "locator": f"{locator} / 段 {index + 1}",
                        "tags": list(document.tags),
                        "content": content,
                        "content_hash": content_hash,
                    },
                }
            )
    return points


def upsert(qdrant_url: str, collection: str, points: list[dict[str, object]]) -> None:
    if not points:
        raise ValueError("No chunks were produced from the supplied source documents.")
    dimensions = len(points[0]["vector"])
    with httpx.Client(timeout=30) as client:
        collection_response = client.put(
            f"{qdrant_url.rstrip('/')}/collections/{collection}",
            json={"vectors": {"size": dimensions, "distance": "Cosine"}},
        )
        collection_response.raise_for_status()
        response = client.put(
            f"{qdrant_url.rstrip('/')}/collections/{collection}/points?wait=true",
            json={"points": points},
        )
        response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest licensed 六爻资料 into Qdrant.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "yijing_sources"))
    parser.add_argument("--fake-embeddings", action="store_true")
    arguments = parser.parse_args()
    if not arguments.fake_embeddings and not all(os.getenv(key) for key in ("EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL")):
        parser.error("Set embedding variables or use --fake-embeddings for local tests.")
    points = build_points(load_manifest(arguments.manifest), arguments.fake_embeddings)
    upsert(arguments.qdrant_url, arguments.collection, points)
    print(f"Upserted {len(points)} source chunks into {arguments.collection}.")