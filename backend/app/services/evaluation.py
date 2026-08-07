import json
from pathlib import Path
from statistics import mean

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import EvaluationCaseResult, EvaluationResponse
from app.services.retrieval import retrieve_chunks


def _reciprocal_rank(expected: set[str], retrieved: list[str]) -> float:
    for rank, source_name in enumerate(retrieved, start=1):
        if source_name in expected:
            return 1.0 / rank
    return 0.0


def run_evaluation(database: Session, top_k: int = 5) -> EvaluationResponse:
    dataset_path = Path(settings.evaluation_dataset_path)
    cases = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results: list[EvaluationCaseResult] = []
    retrieval_times: list[int] = []
    for case in cases:
        retrieval = retrieve_chunks(database, case["question"], top_k=top_k)
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
