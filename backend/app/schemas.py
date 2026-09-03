import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    provider: str
    database: str


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_name: str
    document_type: str
    service: str
    incident_type: str
    severity: str
    version: str
    status: str
    created_at: datetime


class SeedResponse(BaseModel):
    indexed: int
    skipped: int
    failed: int
    documents: list[DocumentResponse]


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=8000)
    service: str | None = None
    incident_type: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)
    retrieval_mode: Literal["vector", "keyword", "hybrid"] = "hybrid"


class Citation(BaseModel):
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


class Diagnostics(BaseModel):
    masked_question: str
    inferred_incident_type: str | None
    retrieval_ms: int
    generation_ms: int
    total_ms: int
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    prompt_version: str
    top_score: float
    retrieval_mode: Literal["vector", "keyword", "hybrid"]
    evidence_reason: str
    candidate_count: int


class ChatResponse(BaseModel):
    answer: str
    grounded: bool
    confidence: str
    citations: list[Citation]
    retrieved_chunks: list[Citation] = Field(default_factory=list)
    trace_id: uuid.UUID
    diagnostics: Diagnostics


class EvaluationCaseResult(BaseModel):
    case_id: str = ""
    category: str = "baseline"
    question: str
    expected_documents: list[str]
    retrieved_documents: list[str]
    reciprocal_rank: float
    hit_at_k: bool
    recall_at_k: float = 0.0
    expected_answerable: bool
    predicted_answerable: bool
    passed_refusal: bool


class EvaluationResponse(BaseModel):
    retrieval_mode: Literal["vector", "keyword", "hybrid"]
    cases: int
    recall_at_k: float
    mrr: float
    refusal_accuracy: float
    average_retrieval_ms: float
    answerable_cases: int = 0
    unanswerable_cases: int = 0
    false_acceptance_rate: float | None = None
    false_refusal_rate: float | None = None
    results: list[EvaluationCaseResult]


class RetrievalComparisonResponse(BaseModel):
    dataset: str
    top_k: int
    cases: int
    repetitions: int
    vector_weight: float
    keyword_weight: float
    recommended_mode: Literal["vector", "keyword", "hybrid"]
    recommendation_policy: str
    results: list[EvaluationResponse]
    provider: str = "local"
    embedding_fingerprint: str = ""
    dataset_sha256: str = ""
    corpus_sha256: str = ""
    document_count: int = 0
    candidate_k: int = 20
    chunk_size: int = 900
    chunk_overlap: int = 120
    grounding_policy: dict = Field(default_factory=dict)
    evaluated_at: datetime | None = None
    query_embedding_reuse: bool = False
    query_embedding_inputs: int = 0
    query_embedding_input_characters: int = 0
    query_embedding_preparation_ms: int = 0
    retrieval_timing_scope: str = "query-embedding-and-database"
