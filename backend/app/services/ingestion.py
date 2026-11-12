import hashlib
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentChunk
from app.services.ai import embed_texts, embedding_fingerprint
from app.services.chunking import split_document
from app.services.redaction import REDACTION_VERSION, mask_sensitive_text


def _parse_frontmatter(raw_text: str) -> tuple[dict[str, str], str]:
    raw_text = raw_text.replace("\r\n", "\n")
    if not raw_text.startswith("---\n"):
        return {}, raw_text

    parts = raw_text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("문서 메타데이터의 닫는 --- 구분자가 없습니다.")
    _, frontmatter, body = parts
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
    raw_text = mask_sensitive_text(raw_text)
    source_name = mask_sensitive_text(Path(source_name.replace("\\", "/")).name)
    metadata, body = _parse_frontmatter(raw_text)
    if not body.strip():
        raise ValueError("색인할 문서 본문이 없습니다.")
    if len(source_name) > 255 or len(metadata.get("title", "")) > 255:
        raise ValueError("파일 이름과 문서 제목은 255자 이하여야 합니다.")
    checksum = _checksum(raw_text)

    duplicate = database.scalar(select(Document).where(Document.checksum == checksum))
    existing = duplicate or database.scalar(select(Document).where(Document.source_name == source_name))
    if existing and existing.checksum == checksum and existing.chunks and all(
        chunk.attributes.get("embedding_fingerprint") == embedding_fingerprint()
        and chunk.attributes.get("redaction_version") == REDACTION_VERSION
        for chunk in existing.chunks
    ):
        return existing, False

    index_metadata = {**metadata, "embedding_fingerprint": embedding_fingerprint(), "redaction_version": REDACTION_VERSION}
    chunks = split_document(body, metadata)
    if not chunks:
        raise ValueError("색인할 수 있는 문서 내용이 없습니다.")
    embeddings = embed_texts([chunk.content for chunk in chunks])
    document = existing or Document()
    if existing:
        document.chunks.clear()
        database.flush()
    document.title = metadata.get("title", Path(source_name).stem)
    document.source_name = existing.source_name if duplicate else source_name
    document.document_type = metadata.get("document_type", "runbook")
    document.service = metadata.get("service", "unknown")
    document.incident_type = metadata.get("incident_type", "UNKNOWN")
    document.severity = metadata.get("severity", "P3")
    document.version = metadata.get("version", "all")
    document.checksum = checksum
    document.status = "processing"
    database.add(document)
    database.flush()

    for chunk, embedding in zip(chunks, embeddings, strict=True):
        database.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.index,
                heading=chunk.heading,
                content=chunk.content,
                token_count=chunk.token_count,
                attributes=index_metadata,
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


SEED_KINDS = ("statute", "precedent", "sentencing", "guide")


def ingest_sample_documents(database: Session) -> tuple[list[Document], int, int, int]:
    data_directory = Path(settings.sample_data_dir)
    documents: list[Document] = []
    indexed = 0
    skipped = 0
    failed = 0

    paths = sorted(data_directory.glob("*.md"))
    for path in paths:
        try:
            document, created = ingest_markdown(database, path)
            documents.append(document)
            indexed += int(created)
            skipped += int(not created)
        except Exception:
            logging.getLogger(__name__).exception("could not index %s", path.name)
            database.rollback()
            failed += 1

    # a source file removed from the folder must stop being cited
    # shortcut: an upload whose front matter says statute/precedent/sentencing/guide is removed too; mark uploads if they matter
    # kept: matched by content (a renamed file keeps its first name) or by name (a file that failed to re-index this time)
    stale = select(Document).where(Document.document_type.in_(SEED_KINDS),
                                   Document.id.not_in([document.id for document in documents]),
                                   Document.source_name.not_in([path.name for path in paths]))
    for document in database.scalars(stale).all():
        database.delete(document)
    database.commit()
    return documents, indexed, skipped, failed
