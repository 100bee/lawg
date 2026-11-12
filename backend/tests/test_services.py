import math
from types import SimpleNamespace

import pytest

from app.services import ai
from app.services.ai import embed_texts, generate_answer
from app.services.classifier import infer_incident_type
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


def test_infers_incident_types() -> None:
    assert infer_incident_type("429 rate limit 오류가 발생했어") == "API"
    assert infer_incident_type("문서 색인 worker가 processing에서 멈췄어") == "INGESTION"
    assert infer_incident_type("pgvector DB connection이 부족해") == "INFRASTRUCTURE"
    assert infer_incident_type("관련 없는 문서가 검색돼") == "RETRIEVAL"


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


def test_openai_answer_uses_responses_api(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=ai.GroundedDraft(
                    answerable=True,
                    summary=[ai.CitedStatement(text="근거 기반 답변", source_ids=["S1"])],
                    causes=[], checks=[], actions=[], follow_up_questions=[],
                ),
                usage=SimpleNamespace(input_tokens=120, output_tokens=30),
            )

    fake_client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setattr(ai.settings, "ai_provider", "openai")
    monkeypatch.setattr(ai, "_openai_client", lambda: fake_client)

    generated = generate_answer(
        "429 오류 대응 방법",
        "[S1] 429 Runbook",
        [{"title": "429 Runbook", "heading": "대응", "content": "지수 백오프"}],
    )

    assert captured["model"] == ai.settings.openai_chat_model
    assert captured["store"] is False
    assert "evidence" in captured["input"]
    assert captured["text_format"] is ai.GroundedDraft
    assert generated.input_tokens == 120
    assert generated.output_tokens == 30


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
