from time import perf_counter

from app.config import settings
from app.services.ai import GeneratedAnswer, generate_answer
from app.services.retrieval import RetrievedChunk


REFUSAL_TEXT = """## 근거 부족
현재 등록된 운영 문서에서는 이 질문을 뒷받침할 충분한 근거를 찾지 못했습니다.

## 추가로 필요한 정보
- 오류 발생 시각과 요청 ID
- 영향을 받은 서비스와 배포 버전
- 전체 오류 메시지와 직전 변경 사항

추측으로 대응하지 말고 위 정보를 확보한 뒤 담당 팀에 전달해 주세요."""


def confidence_label(score: float) -> str:
    if score >= 0.62:
        return "high"
    if score >= 0.30:
        return "medium"
    if score >= settings.minimum_grounding_score:
        return "low"
    return "insufficient"


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


def answer_with_evidence(
    question: str,
    chunks: list[RetrievedChunk],
) -> tuple[GeneratedAnswer, bool, str, int]:
    top_score = chunks[0].score if chunks else 0.0
    confidence = confidence_label(top_score)
    if not chunks or top_score < settings.minimum_grounding_score:
        return GeneratedAnswer(REFUSAL_TEXT, 0, 0), False, confidence, 0

    started_at = perf_counter()
    citation_payload = [
        {
            "title": chunk.title,
            "heading": chunk.heading,
            "content": chunk.content,
        }
        for chunk in chunks
    ]
    generated = generate_answer(question, build_context(chunks), citation_payload)
    elapsed_ms = round((perf_counter() - started_at) * 1000)
    return generated, True, confidence, elapsed_ms

