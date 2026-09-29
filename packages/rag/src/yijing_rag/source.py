from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    title: str
    edition: str
    license_basis: str
    source_url: str
    path: Path
    tags: tuple[str, ...]


def load_manifest(manifest_path: Path) -> list[SourceDocument]:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents: list[SourceDocument] = []
    required = {"source_id", "title", "edition", "license_basis", "source_url", "path"}
    for item in raw.get("sources", []):
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Source metadata is incomplete: {', '.join(sorted(missing))}")
        if not str(item["license_basis"]).strip():
            raise ValueError(f"Source {item['source_id']} has no license or public-domain basis.")
        source_path = manifest_path.parent / str(item["path"])
        if not source_path.is_file():
            raise ValueError(f"Source text does not exist: {source_path}")
        documents.append(
            SourceDocument(
                source_id=str(item["source_id"]),
                title=str(item["title"]),
                edition=str(item["edition"]),
                license_basis=str(item["license_basis"]),
                source_url=str(item["source_url"]),
                path=source_path,
                tags=tuple(str(tag) for tag in item.get("tags", [])),
            )
        )
    if not documents:
        raise ValueError("The source manifest does not contain any documents.")
    return documents