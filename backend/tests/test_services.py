import math
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.services import ai
from app.services.ai import embed_texts
from app.services.evaluation import select_recommended_mode
from app.services.chunking import split_document
from app.services.redaction import mask_sensitive_text, mask_story
from app.services.retrieval import calculate_retrieval_score
from app.schemas import EvaluationResponse


def test_masks_sensitive_values() -> None:
    text = "key=sk-test1234567890 email=dev@example.com에서 ip=10.20.30.40 Bearer abc.def.ghi"

    masked = mask_sensitive_text(text)

    assert "sk-test1234567890" not in masked
    assert "dev@example.com" not in masked
    assert "10.20.30.40" not in masked
    assert "abc.def.ghi" not in masked


def test_local_embedding_is_deterministic_and_normalized() -> None:
    first, second = embed_texts(["pgvector 검색 지연", "pgvector 검색 지연"])

    assert first == second
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_retrieval_modes_use_expected_scores() -> None:
    assert calculate_retrieval_score("vector", 0.8, 0.4) == 0.8
    assert calculate_retrieval_score("keyword", 0.8, 0.4) == 0.4
    assert math.isclose(calculate_retrieval_score("hybrid", 0.8, 0.4), 0.688)


def test_recommended_mode_prioritizes_quality_before_latency() -> None:
    common = {
        "cases": 14,
        "refusal_accuracy": 1.0,
        "results": [],
    }
    vector = EvaluationResponse(
        retrieval_mode="vector",
        recall_at_k=0.8,
        mrr=0.7,
        average_retrieval_ms=4,
        **common,
    )
    hybrid = EvaluationResponse(
        retrieval_mode="hybrid",
        recall_at_k=1.0,
        mrr=0.9,
        average_retrieval_ms=12,
        **common,
    )

    assert select_recommended_mode([vector, hybrid]) == "hybrid"


class Probe(BaseModel):
    answer: str


def test_openai_structured_call_uses_responses_api_without_storing(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=Probe(answer="ok"),
                                   usage=SimpleNamespace(input_tokens=120, output_tokens=30))

    monkeypatch.setattr(ai.settings, "ai_provider", "openai")
    monkeypatch.setattr(ai, "_openai_client", lambda: SimpleNamespace(responses=FakeResponses()))
    parsed, input_tokens, output_tokens = ai.structured_call(
        "지시", {"story": "key=sk-abcdefghijklmnop"}, Probe, max_output_tokens=100)

    assert parsed.answer == "ok" and (input_tokens, output_tokens) == (120, 30)
    assert captured["store"] is False and captured["text_format"] is Probe
    assert "sk-abcdefghijklmnop" not in captured["input"]


@pytest.mark.parametrize(("story", "hidden", "kept"), [
    ("제 이름은 홍길동이고 010-1234-5678로 연락 왔어요", ["홍길동", "010-1234-5678"], ["[이름]", "[전화번호]"]),
    ("국민은행 123-456-789012로 20만원 보냈어요", ["123-456-789012"], ["20만원", "[계좌번호]"]),
    ("주민번호 900101-1234567 알려줬어요", ["900101-1234567"], ["[주민번호]"]),
    ("철수씨가 욕했어요. 판매자님이랑 아저씨는 몰라요", ["철수"], ["판매자님", "아저씨"]),
    ("씨발이라고 했어요. 닉네임 이름이 바뀌었어요", [], ["씨발", "이름이 바뀌었어요"]),
])
def test_story_masking_hides_personal_data_but_keeps_the_story(story, hidden, kept) -> None:
    masked = mask_story(story)
    assert all(value not in masked for value in hidden)
    assert all(value in masked for value in kept)


def test_statutes_and_guides_are_one_chunk_each() -> None:
    body = "제2조(정의) " + "가. 상대방에게 접근하는 행위\n" * 200
    chunks = split_document(body, {"document_type": "statute", "title": "스토킹처벌법 제2조 (정의)"})
    assert len(chunks) == 1 and chunks[0].heading == "스토킹처벌법 제2조 (정의)"
