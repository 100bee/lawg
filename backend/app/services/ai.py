import hashlib
import math
import re
from dataclasses import dataclass

from openai import OpenAI

from app.config import settings


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣_./:-]+")


@dataclass(slots=True)
class GeneratedAnswer:
    text: str
    input_tokens: int
    output_tokens: int


def _openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("AI_PROVIDER=openai 사용 시 OPENAI_API_KEY가 필요합니다.")
    return OpenAI(api_key=settings.openai_api_key)


def _local_embedding(text: str) -> list[float]:
    vector = [0.0] * settings.embedding_dimensions
    tokens = TOKEN_PATTERN.findall(text.lower())
    features = tokens + [
        f"{tokens[index]}::{tokens[index + 1]}"
        for index in range(len(tokens) - 1)
    ]

    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        raw_value = int.from_bytes(digest, byteorder="big", signed=False)
        vector_index = raw_value % settings.embedding_dimensions
        sign = 1.0 if raw_value & 1 else -1.0
        vector[vector_index] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.ai_provider == "local":
        return [_local_embedding(text) for text in texts]

    response = _openai_client().embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
        encoding_format="float",
    )
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]


def generate_answer(question: str, context: str, citations: list[dict]) -> GeneratedAnswer:
    if settings.ai_provider == "local":
        source_lines = "\n".join(
            f"- [{index}] {citation['title']} · {citation['heading']}"
            for index, citation in enumerate(citations, start=1)
        )
        excerpts = []
        for citation in citations[:3]:
            compact = re.sub(r"\s+", " ", citation["content"]).strip()
            excerpts.append(compact[:280])
        evidence = "\n".join(f"- {excerpt}" for excerpt in excerpts)
        text = (
            "## 장애 요약\n"
            f"입력한 증상과 관련된 운영 문서 {len(citations)}건을 찾았습니다.\n\n"
            "## 확인된 근거\n"
            f"{evidence}\n\n"
            "## 권장 대응 절차\n"
            "1. 아래 출처의 즉시 확인 항목을 순서대로 점검합니다.\n"
            "2. 최근 배포·설정 변경 여부를 확인합니다.\n"
            "3. 재현 시각과 요청 ID를 확보해 담당 서비스 로그와 대조합니다.\n\n"
            "## 출처\n"
            f"{source_lines}\n\n"
            "로컬 개발 모드의 템플릿 응답입니다. OpenAI 모드에서는 검색 근거를 종합한 답변을 생성합니다."
        )
        return GeneratedAnswer(text=text, input_tokens=0, output_tokens=0)

    instructions = (
        "당신은 기업용 RAG 서비스의 장애 대응 Copilot이다. "
        "제공된 검색 근거만 사용하고, 근거에 없는 원인을 사실처럼 말하지 않는다. "
        "한국어로 장애 요약, 가능성이 높은 원인, 즉시 확인할 항목, 대응 절차, 추가 확인 질문을 작성한다. "
        "각 핵심 주장 뒤에 [S1] 형식으로 출처를 표시한다. "
        "명령 실행이나 설정 변경을 직접 수행했다고 표현하지 않는다."
    )
    response = _openai_client().responses.create(
        model=settings.openai_chat_model,
        instructions=instructions,
        input=f"사용자 질문:\n{question}\n\n검색 근거:\n{context}",
        store=False,
    )
    usage = response.usage
    return GeneratedAnswer(
        text=response.output_text,
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
    )

