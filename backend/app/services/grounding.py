"""A retrieval evidence gate, not a guarantee that a generated claim is true.

Ranking scores are relative to candidates. Acceptance uses query coverage and
provider-specific vector evidence instead, shared by chat and offline evaluation.
"""
from app.config import settings
from app.services.retrieval import RetrievedChunk, RetrievalMode


def evidence_chunks(chunks: list[RetrievedChunk], mode: RetrievalMode) -> list[RetrievedChunk]:
    accepted = []
    for chunk in chunks:
        lexical = (
            chunk.keyword_matches >= settings.minimum_keyword_matches
            and chunk.keyword_coverage >= settings.minimum_keyword_coverage
        )
        if settings.ai_provider == "local":
            # Hashing measures token overlap, not semantic entailment.
            vector = lexical and chunk.vector_score >= settings.minimum_grounding_score
        else:
            vector = chunk.vector_score >= settings.minimum_semantic_score
        sufficient = vector if mode == "vector" else lexical if mode == "keyword" else lexical or vector
        if sufficient:
            accepted.append(chunk)
    return accepted
