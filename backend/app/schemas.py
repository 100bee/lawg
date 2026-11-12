import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# --- Lawg report API (frontend/app/report.ts mirrors these types) ---

Role = Literal["victim", "offender", "third_party", "unclear"]
Category = Literal["fraud", "insult", "defamation", "obscenity", "account", "threat"]
RefusalKind = Literal["out_of_scope", "no_evidence", "individual_conclusion", "evasion", "referral"]
SourceKind = Literal["statute", "precedent", "sentencing", "guide"]


class ReportRequest(BaseModel):
    story: str = Field(min_length=2, max_length=2000)
    role: Role | None = None  # set when the user corrects the inferred role


class Term(BaseModel):
    said: str  # the user's own words, e.g. "먹튀"
    legal: list[str] = Field(min_length=1)  # the legal issues they map to


class Reading(BaseModel):
    role: Role
    category: Category | None  # None when the story is out of scope
    terms: list[Term] = Field(default_factory=list)


class Source(BaseModel):
    id: str = Field(pattern=r"^S[1-9][0-9]*$")
    kind: SourceKind
    title: str
    text: str  # verbatim excerpt from the indexed document, never model-written
    effective_date: date | None = None  # statutes
    case_number: str | None = None  # precedents
    decided_on: date | None = None  # precedents
    url: str | None = None


class Cited(BaseModel):
    text: str
    sources: list[str] = Field(default_factory=list)


class LawItem(BaseModel):
    source: str
    plain: str  # plain-language explanation of the source


class Report(BaseModel):
    summary: str
    laws: list[LawItem] = Field(min_length=1)
    penalty: list[Cited]
    facts_to_check: list[str]
    actions: list[Cited]
    prepare: list[str]
    cannot_answer: list[str]

    def cited_ids(self) -> set[str]:
        ids = {item.source for item in self.laws}
        for claim in (*self.penalty, *self.actions):
            ids.update(claim.sources)
        return ids


class Refusal(BaseModel):
    kind: RefusalKind
    message: str
    alternatives: list[str] = Field(default_factory=list)
    rephrase: str | None = None


class ReportResponse(BaseModel):
    reading: Reading
    report: Report | None = None
    refusal: Refusal | None = None
    sources: list[Source] = Field(default_factory=list)
    trace_id: uuid.UUID
    created_at: datetime

    @model_validator(mode="after")
    def check_shape(self) -> "ReportResponse":
        if self.report and self.refusal:
            raise ValueError("report and refusal are mutually exclusive")
        if not self.report and not self.refusal and self.reading.role != "unclear":
            raise ValueError("without a report or refusal the role must be unclear (the UI asks for it)")
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source id")
        if self.report and (missing := self.report.cited_ids() - set(ids)):
            raise ValueError(f"cited sources missing: {sorted(missing)}")
        return self
