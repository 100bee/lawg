import math
from types import SimpleNamespace

from app.services import ai
from app.services.ai import embed_texts, generate_answer
from app.services.answering import confidence_label
from app.services.classifier import infer_incident_type
from app.services.redaction import mask_sensitive_text


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


def test_confidence_thresholds() -> None:
    assert confidence_label(0.8) == "high"
    assert confidence_label(0.4) == "medium"
    assert confidence_label(0.1) == "low"
    assert confidence_label(0.0) == "insufficient"


def test_openai_answer_uses_responses_api(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text="근거 기반 답변 [S1]",
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
    assert "검색 근거" in captured["input"]
    assert generated.input_tokens == 120
    assert generated.output_tokens == 30
