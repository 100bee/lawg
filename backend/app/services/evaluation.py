import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import perf_counter

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.config import settings
from app.schemas import EvaluationCaseResult, EvaluationResponse, RetrievalComparisonResponse
from app.models import Document
from app.services.ai import embed_texts, embedding_fingerprint
from app.services.grounding import evidence_chunks
from app.services.redaction import mask_sensitive_text
from app.services.retrieval import RETRIEVAL_MODES, RetrievalMode, retrieve_chunks


def _reciprocal_rank(expected: set[str], retrieved: list[str]) -> float:
    for rank, source_name in enumerate(retrieved, start=1):
        if source_name in expected:
            return 1.0 / rank
    return 0.0


def _load_cases(split: str) -> list[dict]:
    dataset_path = Path(settings.evaluation_dataset_path)
    cases = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if split != "all":
        cases = [case for case in cases if case.get("split", "dev") == split]
    if not cases:
        raise ValueError("평가 데이터가 비어 있습니다.")
    return cases


def run_evaluation(
    database: Session,
    top_k: int = 5,
    retrieval_mode: RetrievalMode = "hybrid",
    split: str = "all",
    *,
    query_embeddings: dict[str, list[float]] | None = None,
) -> EvaluationResponse:
    cases = _load_cases(split)

    results: list[EvaluationCaseResult] = []
    retrieval_times: list[int] = []
    for case in cases:
        question = mask_sensitive_text(case["question"])
        retrieval = retrieve_chunks(
            database,
            question,
            top_k=top_k,
            mode=retrieval_mode,
            query_embedding=(query_embeddings[question]
                             if query_embeddings is not None and retrieval_mode != "keyword" else None),
        )
        retrieved_documents = list(dict.fromkeys(chunk.source_name for chunk in retrieval.chunks))
        expected_documents = set(case["expected_documents"])
        reciprocal_rank = _reciprocal_rank(expected_documents, retrieved_documents)
        predicted_answerable = bool(evidence_chunks(retrieval.chunks, retrieval_mode))
        expected_answerable = bool(case["answerable"])
        passed_refusal = predicted_answerable == expected_answerable
        retrieval_times.append(retrieval.elapsed_ms)
        results.append(
            EvaluationCaseResult(
                case_id=case.get("id", ""),
                category=case.get("category", "baseline"),
                question=mask_sensitive_text(case["question"]),
                expected_documents=case["expected_documents"],
                retrieved_documents=retrieved_documents,
                reciprocal_rank=reciprocal_rank,
                hit_at_k=bool(expected_documents.intersection(retrieved_documents)),
                recall_at_k=(len(expected_documents.intersection(retrieved_documents)) / len(expected_documents)
                             if expected_documents else 0.0),
                expected_answerable=expected_answerable,
                predicted_answerable=predicted_answerable,
                passed_refusal=passed_refusal,
            )
        )

    answerable_results = [result for result in results if result.expected_answerable]
    unanswerable_results = [result for result in results if not result.expected_answerable]
    return EvaluationResponse(
        retrieval_mode=retrieval_mode,
        cases=len(results),
        recall_at_k=(
            mean(result.recall_at_k for result in answerable_results)
            if answerable_results
            else 0.0
        ),
        mrr=(
            mean(result.reciprocal_rank for result in answerable_results)
            if answerable_results
            else 0.0
        ),
        refusal_accuracy=mean(result.passed_refusal for result in results) if results else 0.0,
        average_retrieval_ms=mean(retrieval_times) if retrieval_times else 0.0,
        answerable_cases=len(answerable_results),
        unanswerable_cases=len(unanswerable_results),
        false_acceptance_rate=(mean(result.predicted_answerable for result in unanswerable_results)
                               if unanswerable_results else None),
        false_refusal_rate=(mean(not result.predicted_answerable for result in answerable_results)
                           if answerable_results else None),
        results=results,
    )


def select_recommended_mode(results: list[EvaluationResponse]) -> RetrievalMode:
    recommended = max(
        results,
        key=lambda result: (
            result.recall_at_k,
            result.mrr,
            result.refusal_accuracy,
            -result.average_retrieval_ms,
        ),
    )
    return recommended.retrieval_mode


def run_retrieval_comparison(
    database: Session,
    top_k: int = 5,
    repetitions: int = 3,
    split: str = "all",
    *,
    reuse_query_embeddings: bool = False,
) -> RetrievalComparisonResponse:
    if not 1 <= repetitions <= 10:
        raise ValueError("반복 횟수는 1~10이어야 합니다.")
    documents = list(database.scalars(select(Document).order_by(Document.source_name)).all())
    if not documents:
        raise ValueError("먼저 샘플 문서를 색인해 주세요.")
    questions = [mask_sensitive_text(case["question"]) for case in _load_cases(split)]
    query_embeddings = None
    preparation_ms = 0
    embedding_inputs = questions * (2 * repetitions)
    if reuse_query_embeddings:
        # One experiment-local cache: no reuse across models, corpora or later runs.
        embedding_inputs = list(dict.fromkeys(questions))
        started_at = perf_counter()
        vectors = embed_texts(embedding_inputs, task_type="RETRIEVAL_QUERY")
        query_embeddings = dict(zip(embedding_inputs, vectors, strict=True))
        preparation_ms = round((perf_counter() - started_at) * 1000)
    runs_by_mode = {mode: [] for mode in RETRIEVAL_MODES}
    # Rotate execution order to reduce systematic cache/order bias.
    for repetition in range(repetitions):
        offset = repetition % len(RETRIEVAL_MODES)
        for mode in RETRIEVAL_MODES[offset:] + RETRIEVAL_MODES[:offset]:
            runs_by_mode[mode].append(run_evaluation(
                database, top_k, mode, split, query_embeddings=query_embeddings,
            ))
    results: list[EvaluationResponse] = []
    for mode in RETRIEVAL_MODES:
        runs = runs_by_mode[mode]
        first_run = runs[0]
        results.append(
            EvaluationResponse(
                retrieval_mode=mode,
                cases=first_run.cases,
                recall_at_k=mean(run.recall_at_k for run in runs),
                mrr=mean(run.mrr for run in runs),
                refusal_accuracy=mean(run.refusal_accuracy for run in runs),
                average_retrieval_ms=mean(run.average_retrieval_ms for run in runs),
                answerable_cases=first_run.answerable_cases,
                unanswerable_cases=first_run.unanswerable_cases,
                false_acceptance_rate=first_run.false_acceptance_rate,
                false_refusal_rate=first_run.false_refusal_rate,
                results=first_run.results,
            )
        )
    return RetrievalComparisonResponse(
        dataset=f"{Path(settings.evaluation_dataset_path).name}:{split}",
        top_k=top_k,
        cases=results[0].cases if results else 0,
        repetitions=repetitions,
        vector_weight=settings.hybrid_vector_weight,
        keyword_weight=settings.hybrid_keyword_weight,
        recommended_mode=select_recommended_mode(results),
        recommendation_policy="Recall@K, MRR, refusal accuracy 순으로 우선하고 동률이면 검색시간이 짧은 방식을 선택",
        results=results,
        provider=settings.ai_provider,
        embedding_fingerprint=embedding_fingerprint(),
        dataset_sha256=hashlib.sha256(Path(settings.evaluation_dataset_path).read_bytes()).hexdigest(),
        corpus_sha256=hashlib.sha256(json.dumps(
            [(document.source_name, document.checksum) for document in documents],
            ensure_ascii=False,
        ).encode()).hexdigest(),
        document_count=len(documents),
        candidate_k=settings.retrieval_candidate_k,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        grounding_policy={
            "local_vector_min": settings.minimum_grounding_score,
            "semantic_vector_min": settings.minimum_semantic_score,
            "keyword_coverage_min": settings.minimum_keyword_coverage,
            "keyword_matches_min": settings.minimum_keyword_matches,
            "version": "coverage-v1",
            "scope": "retrieval-gate-only; generated answer correctness is not evaluated",
        },
        evaluated_at=datetime.now(timezone.utc),
        query_embedding_reuse=reuse_query_embeddings,
        query_embedding_inputs=len(embedding_inputs),
        query_embedding_input_characters=sum(len(question) for question in embedding_inputs),
        query_embedding_preparation_ms=preparation_ms,
        retrieval_timing_scope=("database-and-ranking-only" if reuse_query_embeddings
                                else "query-embedding-and-database"),
    )
