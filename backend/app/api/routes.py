import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Document, RetrievalTrace
from app.schemas import (
    DocumentResponse,
    EvaluationResponse,
    HealthResponse,
    ReportRequest,
    ReportResponse,
    RetrievalComparisonResponse,
    SeedResponse,
)
from app.services.ai import ContentBlocked, ProviderBusy
from app.services.evaluation import run_evaluation, run_retrieval_comparison
from app.services.ingestion import ingest_markdown_text, ingest_sample_documents
from app.services.redaction import mask_sensitive_data
from app.services.report import build_report


router = APIRouter()


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if settings.admin_token and not secrets.compare_digest(x_admin_token or "", settings.admin_token):
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다.")


# shortcut: per-process memory, reset on restart; move to Redis if the API ever runs more than one instance.
_report_times: dict[str, deque[float]] = defaultdict(deque)
_report_lock = threading.Lock()


def limit_reports(request: Request) -> None:
    # The right-most X-Forwarded-For entry is added by the hosting proxy; earlier ones can be forged by the client.
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[-1].strip() or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    with _report_lock:
        times = _report_times[client]
        while times and now - times[0] > settings.report_rate_window_seconds:
            times.popleft()
        if len(times) >= settings.report_rate_limit:
            raise HTTPException(status_code=429, detail=(
                f"짧은 시간에 너무 많이 요청했어요. {settings.report_rate_window_seconds // 60}분쯤 뒤에 다시 시도해 주세요."))
        times.append(now)


@router.post("/report", response_model=ReportResponse, dependencies=[Depends(limit_reports)])
def report(request: ReportRequest, database: Session = Depends(get_db)) -> ReportResponse:
    try:
        return build_report(database, request.story, request.role)
    except ContentBlocked as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ProviderBusy as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:  # configuration or provider errors: for the operator, not the visitor
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/health", response_model=HealthResponse)
def health(database: Session = Depends(get_db)) -> HealthResponse:
    database.execute(text("SELECT 1"))
    return HealthResponse(status="ok", provider=settings.ai_provider, database="connected")


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(database: Session = Depends(get_db)) -> list[DocumentResponse]:
    documents = database.scalars(select(Document).order_by(Document.created_at.desc())).all()
    return [DocumentResponse.model_validate(mask_sensitive_data(
        DocumentResponse.model_validate(document).model_dump()
    )) for document in documents]


@router.post("/documents/seed", response_model=SeedResponse, dependencies=[Depends(require_admin)])
def seed_documents(database: Session = Depends(get_db)) -> SeedResponse:
    documents, indexed, skipped, failed = ingest_sample_documents(database)
    return SeedResponse(
        indexed=indexed,
        skipped=skipped,
        failed=failed,
        documents=[DocumentResponse.model_validate(document) for document in documents],
    )


@router.post("/documents/upload", response_model=DocumentResponse, dependencies=[Depends(require_admin)])
async def upload_document(
    file: UploadFile = File(...),
    database: Session = Depends(get_db),
) -> DocumentResponse:
    if not file.filename or not file.filename.lower().endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Markdown 또는 TXT 파일만 업로드할 수 있습니다.")
    raw_bytes = await file.read(2_000_001)
    if len(raw_bytes) > 2_000_000:
        raise HTTPException(status_code=400, detail="파일 크기는 2MB 이하여야 합니다.")
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="UTF-8 문서만 지원합니다.") from error

    try:
        document, _ = await run_in_threadpool(ingest_markdown_text, database, file.filename, raw_text)
    except ValueError as error:
        database.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        database.rollback()
        raise HTTPException(status_code=503, detail=str(error)) from error
    return DocumentResponse.model_validate(document)


@router.get("/traces/{trace_id}", dependencies=[Depends(require_admin)])
def get_trace(trace_id: uuid.UUID, database: Session = Depends(get_db)) -> dict:
    trace = database.get(RetrievalTrace, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="실행 기록을 찾을 수 없습니다.")
    return mask_sensitive_data({
        "id": trace.id,
        "question": trace.question,
        "masked_question": trace.masked_question,
        "category": trace.inferred_incident_type,
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
        "diagnostics": trace.diagnostics,
        "created_at": trace.created_at,
    })


@router.post("/evaluations/run", response_model=EvaluationResponse, dependencies=[Depends(require_admin)])
def evaluate(database: Session = Depends(get_db)) -> EvaluationResponse:
    document_count = database.scalar(select(func.count()).select_from(Document))
    if not document_count:
        raise HTTPException(status_code=409, detail="먼저 샘플 문서를 색인해 주세요.")
    try:
        return run_evaluation(database)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/evaluations/compare", response_model=RetrievalComparisonResponse,
             dependencies=[Depends(require_admin)])
def compare_retrieval(
    repetitions: int = Query(default=3, ge=1, le=10),
    split: Literal["all", "dev", "challenge"] = "all",
    database: Session = Depends(get_db),
) -> RetrievalComparisonResponse:
    document_count = database.scalar(select(func.count()).select_from(Document))
    if not document_count:
        raise HTTPException(status_code=409, detail="먼저 샘플 문서를 색인해 주세요.")
    try:
        return run_retrieval_comparison(database, repetitions=repetitions, split=split)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
