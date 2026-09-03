from dataclasses import dataclass
from time import perf_counter

from app.services.ai import GeneratedAnswer, generate_answer
from app.services.grounding import evidence_chunks
from app.services.redaction import mask_sensitive_text
from app.services.retrieval import RetrievedChunk, RetrievalMode


REFUSAL_TEXT = """## 근거 부족
현재 등록된 운영 문서에서는 이 질문을 뒷받침할 충분한 근거를 찾지 못했습니다.

## 추가로 필요한 정보
- 오류 발생 시각과 요청 ID
- 영향을 받은 서비스와 배포 버전
- 전체 오류 메시지와 직전 변경 사항

추측으로 대응하지 말고 위 정보를 확보한 뒤 담당 팀에 전달해 주세요."""


def build_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        (
            f"[S{index}] 문서: {chunk.title}\n"
            f"섹션: {chunk.heading}\n"
            f"검색 점수: {chunk.score:.4f}\n"
            f"내용:\n{chunk.content}"
        )
        for index, chunk in enumerate(chunks, start=1)
    )


@dataclass(slots=True)
class EvidenceAnswer:
    generated: GeneratedAnswer
    grounded: bool
    confidence: str
    elapsed_ms: int
    citations: list[RetrievedChunk]


def answer_with_evidence(
    question: str,
    chunks: list[RetrievedChunk],
    mode: RetrievalMode = "hybrid",
) -> EvidenceAnswer:
    chunks = evidence_chunks(chunks, mode)
    if not chunks:
        return EvidenceAnswer(
            GeneratedAnswer(REFUSAL_TEXT, 0, 0, False, "insufficient-retrieval-evidence"),
            False, "insufficient", 0, [],
        )

    started_at = perf_counter()
    citation_payload = [
        {
            "title": chunk.title,
            "heading": chunk.heading,
            "content": chunk.content,
        }
        for chunk in chunks
    ]
    generated = generate_answer(mask_sensitive_text(question), build_context(chunks), citation_payload)
    generated.text = mask_sensitive_text(generated.text)
    elapsed_ms = round((perf_counter() - started_at) * 1000)
    if not generated.answerable:
        generated.text = REFUSAL_TEXT
        return EvidenceAnswer(generated, False, "insufficient", elapsed_ms, [])
    # This describes the gate, not a calibrated probability of answer correctness.
    return EvidenceAnswer(generated, True, "heuristic", elapsed_ms, chunks)
