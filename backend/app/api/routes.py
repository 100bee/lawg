import uuid
from time import perf_counter

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Document, RetrievalTrace
from app.schemas import (
    ChatRequest,
    ChatResponse,
    Citation,
    Diagnostics,
    DocumentResponse,
    EvaluationResponse,
    HealthResponse,
    RetrievalComparisonResponse,
    SeedResponse,
)
from app.services.answering import answer_with_evidence
from app.services.classifier import infer_incident_type
from app.services.evaluation import run_evaluation, run_retrieval_comparison
from app.services.ingestion import ingest_markdown_text, ingest_sample_documents
from app.services.redaction import mask_sensitive_text
from app.services.retrieval import retrieve_chunks


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(database: Session = Depends(get_db)) -> HealthResponse:
    database.execute(text("SELECT 1"))
    return HealthResponse(status="ok", provider=settings.ai_provider, database="connected")


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(database: Session = Depends(get_db)) -> list[Document]:
    return list(database.scalars(select(Document).order_by(Document.created_at.desc())).all())


@router.post("/documents/seed", response_model=SeedResponse)
def seed_documents(database: Session = Depends(get_db)) -> SeedResponse:
    documents, indexed, skipped, failed = ingest_sample_documents(database)
    return SeedResponse(
        indexed=indexed,
        skipped=skipped,
        failed=failed,
        documents=[DocumentResponse.model_validate(document) for document in documents],
    )


@router.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    database: Session = Depends(get_db),
) -> DocumentResponse:
    if not file.filename or not file.filename.lower().endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Markdown 또는 TXT 파일만 업로드할 수 있습니다.")
    raw_bytes = await file.read()
    if len(raw_bytes) > 2_000_000:
        raise HTTPException(status_code=400, detail="파일 크기는 2MB 이하여야 합니다.")
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="UTF-8 문서만 지원합니다.") from error

    try:
        document, _ = ingest_markdown_text(database, file.filename, raw_text)
    except RuntimeError as error:
        database.rollback()
        raise HTTPException(status_code=503, detail=str(error)) from error
    return DocumentResponse.model_validate(document)


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, database: Session = Depends(get_db)) -> ChatResponse:
    total_started_at = perf_counter()
    masked_question = mask_sensitive_text(request.question)
    inferred_incident_type = infer_incident_type(masked_question)

    try:
        retrieval = retrieve_chunks(
            database,
            masked_question,
            service=request.service,
            incident_type=request.incident_type,
            top_k=request.top_k,
        )
        generated, grounded, confidence, generation_ms = answer_with_evidence(
            masked_question,
            retrieval.chunks,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    citations = [
        Citation(
            document_id=chunk.document_id,
            title=chunk.title,
            source_name=chunk.source_name,
            chunk_index=chunk.chunk_index,
            heading=chunk.heading,
            content=chunk.content,
            score=chunk.score,
            vector_score=chunk.vector_score,
            keyword_score=chunk.keyword_score,
        )
        for chunk in retrieval.chunks
    ]
    top_score = retrieval.chunks[0].score if retrieval.chunks else 0.0
    trace = RetrievalTrace(
        question=request.question,
        masked_question=masked_question,
        inferred_incident_type=inferred_incident_type,
        retrieved_chunks=[citation.model_dump(mode="json") for citation in citations],
        answer=generated.text,
        grounded=grounded,
        top_score=top_score,
        provider=settings.ai_provider,
        model=settings.openai_chat_model if settings.ai_provider == "openai" else "local-template",
        prompt_version=settings.prompt_version,
        input_tokens=generated.input_tokens,
        output_tokens=generated.output_tokens,
        retrieval_ms=retrieval.elapsed_ms,
        generation_ms=generation_ms,
    )
    database.add(trace)
    database.commit()
    database.refresh(trace)

    total_ms = round((perf_counter() - total_started_at) * 1000)
    return ChatResponse(
        answer=generated.text,
        grounded=grounded,
        confidence=confidence,
        citations=citations,
        trace_id=trace.id,
        diagnostics=Diagnostics(
            masked_question=masked_question,
            inferred_incident_type=inferred_incident_type,
            retrieval_ms=retrieval.elapsed_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            input_tokens=generated.input_tokens,
            output_tokens=generated.output_tokens,
            provider=settings.ai_provider,
            model=trace.model,
            prompt_version=settings.prompt_version,
            top_score=top_score,
        ),
    )


@router.get("/traces/{trace_id}")
def get_trace(trace_id: uuid.UUID, database: Session = Depends(get_db)) -> dict:
    trace = database.get(RetrievalTrace, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="실행 기록을 찾을 수 없습니다.")
    return {
        "id": trace.id,
        "question": trace.question,
        "masked_question": trace.masked_question,
        "incident_type": trace.inferred_incident_type,
        "retrieved_chunks": trace.retrieved_chunks,
        "answer": trace.answer,
        "grounded": trace.grounded,
        "provider": trace.provider,
        "model": trace.model,
        "prompt_version": trace.prompt_version,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "retrieval_ms": trace.retrieval_ms,
        "generation_ms": trace.generation_ms,
        "created_at": trace.created_at,
    }


@router.post("/evaluations/run", response_model=EvaluationResponse)
def evaluate(database: Session = Depends(get_db)) -> EvaluationResponse:
    document_count = database.scalar(select(func.count()).select_from(Document))
    if not document_count:
        raise HTTPException(status_code=409, detail="먼저 샘플 문서를 색인해 주세요.")
    return run_evaluation(database)


@router.post("/evaluations/compare", response_model=RetrievalComparisonResponse)
def compare_retrieval(
    repetitions: int = Query(default=3, ge=1, le=10),
    database: Session = Depends(get_db),
) -> RetrievalComparisonResponse:
    document_count = database.scalar(select(func.count()).select_from(Document))
    if not document_count:
        raise HTTPException(status_code=409, detail="먼저 샘플 문서를 색인해 주세요.")
    return run_retrieval_comparison(database, repetitions=repetitions)
