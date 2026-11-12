import hashlib
import json
import math
import re
import time
from typing import TypeVar

import httpx
from openai import APIError, OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services.redaction import mask_sensitive_data, mask_sensitive_text


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣_./:-]+")


T = TypeVar("T", bound=BaseModel)

BLOCKED_MESSAGE = "이 내용은 AI 모델이 처리하지 않았어요. 욕설이나 성적인 표현을 조금 줄여서 다시 적어 주세요."
BLOCK_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}


class ContentBlocked(RuntimeError):
    """The provider refused the input or output on safety grounds."""


class ProviderBusy(RuntimeError):
    """Overload or quota. Temporary, and the message is written for site visitors."""


BUSY_MESSAGE = "AI 서버가 바빠서 응답하지 못했어요. 잠시 뒤 다시 시도해 주세요."
RATE_MESSAGE = "요청이 몰려서 처리하지 못했어요. 1분쯤 뒤에 다시 시도해 주세요."
DAILY_MESSAGE = "오늘 쓸 수 있는 AI 사용량을 모두 썼어요. 내일 다시 시도해 주세요."


def embedding_fingerprint() -> str:
    model = settings.openai_embedding_model if settings.ai_provider == "openai" else "feature-hashing-v1"
    if settings.ai_provider == "gemini":
        model = settings.gemini_embedding_model
    return f"{settings.ai_provider}:{model}:{settings.embedding_dimensions}"


RETRYABLE_STATUS = {429, 500, 503, 504}


def _gemini_request(model: str, method: str, payload: dict, *, fallback_model: str | None = None) -> dict:
    """Retry once on overload/rate limit/timeout, then try fallback_model once (generation only)."""
    if not settings.gemini_api_key:
        raise RuntimeError("AI_PROVIDER=gemini 사용 시 .env에 GEMINI_API_KEY를 입력해 주세요.")
    attempts = [model, model] + ([fallback_model] if fallback_model and fallback_model != model else [])
    last_status: int | str = ""
    daily_quota = False
    for attempt, current in enumerate(attempts):
        if attempt:
            time.sleep(settings.gemini_retry_delay_seconds * attempt)
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{current}:{method}",
                headers={"x-goog-api-key": settings.gemini_api_key},
                json=payload,
                timeout=settings.gemini_timeout_seconds,
            )
        except httpx.TimeoutException:
            last_status = "timeout"
            continue
        except httpx.HTTPError as error:
            # Never reflect provider error bodies, request headers or API keys to clients.
            raise RuntimeError("Gemini API 호출에 실패했습니다. 키, 모델 이름과 제공자 상태를 확인해 주세요.") from error
        if response.status_code in RETRYABLE_STATUS:
            last_status = response.status_code
            # Free-tier 429 bodies name the exhausted quota, e.g. GenerateRequestsPerDayPerProjectPerModel.
            daily_quota = daily_quota or (last_status == 429 and "PerDay" in response.text)
            continue
        if response.is_error:
            raise RuntimeError("Gemini API 호출에 실패했습니다. 키, 모델 이름과 제공자 상태를 확인해 주세요.")
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError("Gemini API 응답을 해석하지 못했습니다.") from error
    if last_status == 429:
        raise ProviderBusy(DAILY_MESSAGE if daily_quota else RATE_MESSAGE)
    raise ProviderBusy(BUSY_MESSAGE)


def _openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("AI_PROVIDER=openai 사용 시 OPENAI_API_KEY가 필요합니다.")
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds, max_retries=1)


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


def embed_texts(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    if not texts:
        return []
    texts = [mask_sensitive_text(text) for text in texts]
    if settings.ai_provider == "local":
        return [_local_embedding(text) for text in texts]
    if settings.ai_provider == "gemini":
        vectors = []
        # Standard synchronous embedding requests; no paid asynchronous Batch API.
        for start in range(0, len(texts), 20):
            response = _gemini_request(settings.gemini_embedding_model, "batchEmbedContents", {
                "requests": [
                    {"model": f"models/{settings.gemini_embedding_model}",
                     "content": {"parts": [{"text": text}]},
                     "taskType": task_type, "outputDimensionality": settings.embedding_dimensions}
                    for text in texts[start:start + 20]
                ],
            })
            batch = response.get("embeddings", [])
            if len(batch) != len(texts[start:start + 20]):
                raise RuntimeError("Gemini 임베딩 응답 개수가 요청과 다릅니다.")
            for item in batch:
                vector = item.get("values", [])
                if len(vector) != settings.embedding_dimensions:
                    raise RuntimeError("Gemini 임베딩 차원이 설정과 다릅니다.")
                magnitude = math.sqrt(sum(value * value for value in vector))
                if not magnitude or not math.isfinite(magnitude):
                    raise RuntimeError("Gemini 임베딩에 유효하지 않은 값이 있습니다.")
                vectors.append([value / magnitude for value in vector])
        return vectors

    try:
        response = _openai_client().embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
            dimensions=settings.embedding_dimensions,
            encoding_format="float",
        )
    except APIError as error:
        raise RuntimeError("임베딩 API 호출에 실패했습니다. 설정과 제공자 상태를 확인해 주세요.") from error
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]


def structured_call(instructions: str, payload: dict, schema: type[T], *, max_output_tokens: int) -> tuple[T, int, int]:
    """One JSON-schema call to the chat model. Returns (parsed, input_tokens, output_tokens)."""
    data = json.dumps(mask_sensitive_data(payload), ensure_ascii=False)
    if settings.ai_provider == "gemini":
        spent = [0, 0]
        for attempt in range(2):  # the model occasionally returns JSON that misses the schema; ask once more
            response = _gemini_request(settings.gemini_chat_model, "generateContent", {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": data}]}],
                "generationConfig": {"responseMimeType": "application/json",
                                     "responseJsonSchema": schema.model_json_schema(),
                                     "maxOutputTokens": max_output_tokens, "temperature": 0},
            }, fallback_model=settings.gemini_fallback_chat_model)
            usage = response.get("usageMetadata", {})
            spent[0] += usage.get("promptTokenCount", 0)
            spent[1] += usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
            if response.get("promptFeedback", {}).get("blockReason"):
                raise ContentBlocked(BLOCKED_MESSAGE)
            candidate = (response.get("candidates") or [{}])[0]
            finish = candidate.get("finishReason")
            if finish in BLOCK_FINISH_REASONS:
                raise ContentBlocked(BLOCKED_MESSAGE)
            text = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", [])
                           if not part.get("thought"))
            try:
                if finish == "STOP":
                    return schema.model_validate_json(text), *spent
            except ValidationError:
                pass
        raise RuntimeError("모델 응답 형식이 올바르지 않습니다. 잠시 뒤 다시 시도해 주세요.")
    if settings.ai_provider == "openai":
        try:
            response = _openai_client().responses.parse(
                model=settings.openai_chat_model, instructions=instructions, input=data,
                text_format=schema, store=False,
            )
        except APIError as error:
            raise RuntimeError("답변 API 호출에 실패했습니다. 설정과 제공자 상태를 확인해 주세요.") from error
        except ValidationError as error:
            raise RuntimeError("모델 응답 형식이 올바르지 않습니다. 잠시 뒤 다시 시도해 주세요.") from error
        if response.output_parsed is None:
            raise ContentBlocked(BLOCKED_MESSAGE)
        usage = response.usage
        return (response.output_parsed, getattr(usage, "input_tokens", 0) if usage else 0,
                getattr(usage, "output_tokens", 0) if usage else 0)
    raise RuntimeError("로컬 모드에는 생성 모델이 없습니다.")
