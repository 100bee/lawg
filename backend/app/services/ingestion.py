import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentChunk
from app.services.ai import embed_texts
from app.services.chunking import split_document


def _parse_frontmatter(raw_text: str) -> tuple[dict[str, str], str]:
    if not raw_text.startswith("---\n"):
        return {}, raw_text

    _, frontmatter, body = raw_text.split("---", 2)
    metadata: dict[str, str] = {}
    for line in frontmatter.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, body.strip()


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def ingest_markdown_text(
    database: Session,
    source_name: str,
    raw_text: str,
) -> tuple[Document, bool]:
    metadata, body = _parse_frontmatter(raw_text)
    checksum = _checksum(raw_text)

    existing = database.scalar(select(Document).where(Document.source_name == source_name))
    if existing and existing.checksum == checksum:
        return existing, False
    if existing:
        database.delete(existing)
        database.flush()

    document = Document(
        title=metadata.get("title", Path(source_name).stem),
        source_name=source_name,
        document_type=metadata.get("document_type", "runbook"),
        service=metadata.get("service", "unknown"),
        incident_type=metadata.get("incident_type", "UNKNOWN"),
        severity=metadata.get("severity", "P3"),
        version=metadata.get("version", "all"),
        checksum=checksum,
        status="processing",
    )
    database.add(document)
    database.flush()

    chunks = split_document(body, metadata)
    embeddings = embed_texts([chunk.content for chunk in chunks])
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        database.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.index,
                heading=chunk.heading,
                content=chunk.content,
                token_count=chunk.token_count,
                attributes=metadata,
                embedding=embedding,
            )
        )

    document.status = "indexed"
    database.commit()
    database.refresh(document)
    return document, True


def ingest_markdown(database: Session, path: Path) -> tuple[Document, bool]:
    raw_text = path.read_text(encoding="utf-8")
    return ingest_markdown_text(database, path.name, raw_text)


def ingest_sample_documents(database: Session) -> tuple[list[Document], int, int, int]:
    data_directory = Path(settings.sample_data_dir)
    documents: list[Document] = []
    indexed = 0
    skipped = 0
    failed = 0

    for path in sorted(data_directory.glob("*.md")):
        try:
            document, created = ingest_markdown(database, path)
            documents.append(document)
            indexed += int(created)
            skipped += int(not created)
        except Exception:
            database.rollback()
            failed += 1

    return documents, indexed, skipped, failed
