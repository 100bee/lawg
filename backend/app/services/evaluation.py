import json
from pathlib import Path
from statistics import mean

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import EvaluationCaseResult, EvaluationResponse, RetrievalComparisonResponse
from app.services.retrieval import RETRIEVAL_MODES, RetrievalMode, retrieve_chunks


def _reciprocal_rank(expected: set[str], retrieved: list[str]) -> float:
    for rank, source_name in enumerate(retrieved, start=1):
        if source_name in expected:
            return 1.0 / rank
    return 0.0


def run_evaluation(
    database: Session,
    top_k: int = 5,
    retrieval_mode: RetrievalMode = "hybrid",
) -> EvaluationResponse:
    dataset_path = Path(settings.evaluation_dataset_path)
    cases = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results: list[EvaluationCaseResult] = []
    retrieval_times: list[int] = []
    for case in cases:
        retrieval = retrieve_chunks(
            database,
            case["question"],
            top_k=top_k,
            mode=retrieval_mode,
        )
        retrieved_documents = [chunk.source_name for chunk in retrieval.chunks]
        expected_documents = set(case["expected_documents"])
        reciprocal_rank = _reciprocal_rank(expected_documents, retrieved_documents)
        top_score = retrieval.chunks[0].score if retrieval.chunks else 0.0
        predicted_answerable = bool(retrieval.chunks) and top_score >= settings.minimum_grounding_score
        expected_answerable = bool(case["answerable"])
        passed_refusal = predicted_answerable == expected_answerable
        retrieval_times.append(retrieval.elapsed_ms)
        results.append(
            EvaluationCaseResult(
                question=case["question"],
                expected_documents=case["expected_documents"],
                retrieved_documents=retrieved_documents,
                reciprocal_rank=reciprocal_rank,
                hit_at_k=bool(expected_documents.intersection(retrieved_documents)),
                expected_answerable=expected_answerable,
                predicted_answerable=predicted_answerable,
                passed_refusal=passed_refusal,
            )
        )

    answerable_results = [result for result in results if result.expected_answerable]
    return EvaluationResponse(
        retrieval_mode=retrieval_mode,
        cases=len(results),
        recall_at_k=(
            mean(result.hit_at_k for result in answerable_results)
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
) -> RetrievalComparisonResponse:
    results: list[EvaluationResponse] = []
    for mode in RETRIEVAL_MODES:
        runs = [
            run_evaluation(database, top_k=top_k, retrieval_mode=mode)
            for _ in range(repetitions)
        ]
        first_run = runs[0]
        results.append(
            EvaluationResponse(
                retrieval_mode=mode,
                cases=first_run.cases,
                recall_at_k=mean(run.recall_at_k for run in runs),
                mrr=mean(run.mrr for run in runs),
                refusal_accuracy=mean(run.refusal_accuracy for run in runs),
                average_retrieval_ms=mean(run.average_retrieval_ms for run in runs),
                results=first_run.results,
            )
        )
    return RetrievalComparisonResponse(
        dataset=Path(settings.evaluation_dataset_path).name,
        top_k=top_k,
        cases=results[0].cases if results else 0,
        repetitions=repetitions,
        vector_weight=settings.hybrid_vector_weight,
        keyword_weight=settings.hybrid_keyword_weight,
        recommended_mode=select_recommended_mode(results),
        recommendation_policy="Recall@K, MRR, refusal accuracy 순으로 우선하고 동률이면 검색시간이 짧은 방식을 선택",
        results=results,
    )
