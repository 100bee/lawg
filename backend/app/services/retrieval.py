from dataclasses import dataclass, field
import re
from time import perf_counter
from typing import Literal
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentChunk
from app.services.ai import embed_texts, embedding_fingerprint
from app.services.redaction import mask_sensitive_text


RetrievalMode = Literal["vector", "keyword", "hybrid"]
RETRIEVAL_MODES: tuple[RetrievalMode, ...] = ("vector", "keyword", "hybrid")


KEYWORD_PATTERN = re.compile(r"[A-Za-z0-9가-힣_./:-]{2,}")
KEYWORD_STOPWORDS = {
    "그리고",
    "어떻게",
    "있는데",
    "했는데",
    "해야",
    "질문",
    "장애",
    "문서",
    "서비스",
    "알려줘",
}


@dataclass(slots=True)
class RetrievedChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    title: str
    source_name: str
    chunk_index: int
    heading: str
    content: str
    score: float
    vector_score: float
    keyword_score: float
    keyword_coverage: float = 0.0
    keyword_matches: int = 0
    attributes: dict = field(default_factory=dict)  # front matter: document_type, url, effective_date, ...


@dataclass(slots=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    elapsed_ms: int
    mode: RetrievalMode


def _filters(statement, service: str | None, incident_type: str | None):
    if service:
        statement = statement.where(Document.service == service)
    if incident_type:
        statement = statement.where(Document.incident_type == incident_type)
    return statement


def keyword_tokens(question: str) -> list[str]:
    tokens: list[str] = []
    for token in KEYWORD_PATTERN.findall(question.lower()):
        if token in KEYWORD_STOPWORDS or token.startswith("redacted_") or token in tokens:
            continue
        tokens.append(token)
    return tokens[:12]


def _keyword_search_text(question: str) -> str:
    return " OR ".join(keyword_tokens(question))


def keyword_evidence(question: str, content: str) -> tuple[float, int]:
    tokens = keyword_tokens(question)
    content_tokens = set(KEYWORD_PATTERN.findall(content.lower()))
    matches = sum(token in content_tokens for token in tokens)
    return (matches / len(tokens) if tokens else 0.0), matches


def calculate_retrieval_score(
    mode: RetrievalMode,
    vector_score: float,
    keyword_score: float,
) -> float:
    if mode == "vector":
        return vector_score
    if mode == "keyword":
        return keyword_score
    return (
        settings.hybrid_vector_weight * vector_score
        + settings.hybrid_keyword_weight * keyword_score
    )


def retrieve_chunks(
    database: Session,
    question: str,
    service: str | None = None,
    incident_type: str | None = None,
    top_k: int | None = None,
    mode: RetrievalMode = "hybrid",
    *,
    query_embedding: list[float] | None = None,
) -> RetrievalResult:
    started_at = perf_counter()
    question = mask_sensitive_text(question)
    # A model change must never silently compare incompatible vector spaces.
    incompatible = database.scalar(
        select(DocumentChunk.id).where(
            func.coalesce(DocumentChunk.attributes["embedding_fingerprint"].astext, "")
            != embedding_fingerprint()
        ).limit(1)
    )
    if incompatible:
        raise ValueError("현재 임베딩 설정과 다른 색인이 있습니다. 문서를 다시 색인해 주세요.")
    requested_top_k = top_k or settings.retrieval_top_k
    vector_rows = []
    keyword_rows = []

    if mode in ("vector", "hybrid"):
        if query_embedding is None:
            query_embedding = embed_texts([question], task_type="RETRIEVAL_QUERY")[0]
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        vector_statement = (
            select(DocumentChunk, Document, (1 - distance).label("vector_score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .order_by(distance)
            .limit(settings.retrieval_candidate_k)
        )
        vector_statement = _filters(vector_statement, service, incident_type)
        vector_rows = database.execute(vector_statement).all()

    keyword_search_text = _keyword_search_text(question)
    if mode in ("keyword", "hybrid") and keyword_search_text:
        keyword_query = func.websearch_to_tsquery("simple", keyword_search_text)
        keyword_rank = func.ts_rank_cd(
            func.to_tsvector("simple", DocumentChunk.content),
            keyword_query,
        )
        keyword_statement = (
            select(DocumentChunk, Document, keyword_rank.label("keyword_score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(keyword_rank > 0)
            .order_by(keyword_rank.desc())
            .limit(settings.retrieval_candidate_k)
        )
        keyword_statement = _filters(keyword_statement, service, incident_type)
        keyword_rows = database.execute(keyword_statement).all()

    candidates: dict[uuid.UUID, dict] = {}
    for chunk, document, vector_score in vector_rows:
        candidates[chunk.id] = {
            "chunk": chunk,
            "document": document,
            "vector_score": max(float(vector_score or 0), 0.0),
            "keyword_score": 0.0,
        }

    maximum_keyword_score = max((float(row.keyword_score) for row in keyword_rows), default=0.0)
    for chunk, document, keyword_score in keyword_rows:
        normalized_keyword_score = (
            float(keyword_score) / maximum_keyword_score if maximum_keyword_score else 0.0
        )
        candidate = candidates.setdefault(
            chunk.id,
            {
                "chunk": chunk,
                "document": document,
                "vector_score": 0.0,
                "keyword_score": 0.0,
            },
        )
        candidate["keyword_score"] = normalized_keyword_score

    ranked: list[RetrievedChunk] = []
    for candidate in candidates.values():
        chunk = candidate["chunk"]
        document = candidate["document"]
        vector_score = candidate["vector_score"]
        keyword_score = candidate["keyword_score"]
        coverage, matches = keyword_evidence(question, chunk.content)
        combined_score = calculate_retrieval_score(mode, vector_score, keyword_score)
        ranked.append(
            RetrievedChunk(
                id=chunk.id,
                document_id=document.id,
                title=mask_sensitive_text(document.title),
                source_name=mask_sensitive_text(document.source_name),
                chunk_index=chunk.chunk_index,
                heading=mask_sensitive_text(chunk.heading),
                content=mask_sensitive_text(chunk.content),
                score=combined_score,
                vector_score=vector_score,
                keyword_score=keyword_score,
                keyword_coverage=coverage,
                keyword_matches=matches,
                attributes=dict(chunk.attributes or {}),
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    elapsed_ms = round((perf_counter() - started_at) * 1000)
    return RetrievalResult(chunks=ranked[:requested_top_k], elapsed_ms=elapsed_ms, mode=mode)
