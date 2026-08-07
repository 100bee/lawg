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


class ChatResponse(BaseModel):
    answer: str
    grounded: bool
    confidence: str
    citations: list[Citation]
    trace_id: uuid.UUID
    diagnostics: Diagnostics


class EvaluationCaseResult(BaseModel):
    question: str
    expected_documents: list[str]
    retrieved_documents: list[str]
    reciprocal_rank: float
    hit_at_k: bool
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
