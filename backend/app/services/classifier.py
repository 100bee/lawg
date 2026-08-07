import re


INCIDENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "API": ("429", "401", "403", "timeout", "rate limit", "api", "인증", "타임아웃"),
    "INGESTION": ("색인", "인덱싱", "파싱", "청킹", "worker", "업로드", "ingestion"),
    "RETRIEVAL": ("검색", "유사도", "문서가 나오", "엉뚱", "retrieval", "top-k", "rerank"),
    "PERFORMANCE": ("지연", "느려", "비용", "토큰", "latency", "cost", "slow"),
    "INFRASTRUCTURE": ("postgres", "pgvector", "db", "connection", "cpu", "memory", "인프라"),
}


def infer_incident_type(question: str) -> str | None:
    normalized = re.sub(r"\s+", " ", question.lower())
    scores = {
        incident_type: sum(1 for pattern in patterns if pattern in normalized)
        for incident_type, patterns in INCIDENT_PATTERNS.items()
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    return best_type if best_score > 0 else None

