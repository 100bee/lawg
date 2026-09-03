import json
import math
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services import ai, answering, evaluation
from app.services.grounding import evidence_chunks
from app.services.redaction import mask_sensitive_text
from app.services.retrieval import RetrievedChunk, RetrievalResult


def chunk(**overrides):
    values = dict(id=uuid.uuid4(), document_id=uuid.uuid4(), title="429 Runbook",
                  source_name="429.md", chunk_index=0, heading="대응", content="API 429 재시도",
                  score=0.28, vector_score=0.0, keyword_score=1.0,
                  keyword_coverage=0.1, keyword_matches=1)
    return RetrievedChunk(**{**values, **overrides})


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_one_matching_word_is_not_sufficient_even_with_high_rank(monkeypatch, mode):
    monkeypatch.setattr(settings, "ai_provider", "local")
    assert evidence_chunks([chunk(score=1, vector_score=0.9)], mode) == []


def test_retrieval_refusal_does_not_call_model(monkeypatch):
    def forbidden(*args):
        pytest.fail("No model call is needed without evidence")
    monkeypatch.setattr(answering, "generate_answer", forbidden)
    result = answering.answer_with_evidence("API 주식 배당일", [chunk()])
    assert not result.grounded
    assert result.citations == []


@pytest.mark.parametrize("answerable,source_id", [(False, "S1"), (True, "S99")])
def test_model_refusal_or_invalid_citation_is_not_grounded(monkeypatch, answerable, source_id):
    monkeypatch.setattr(settings, "ai_provider", "openai")
    draft = ai.GroundedDraft(answerable=answerable,
        summary=[ai.CitedStatement(text="대응", source_ids=[source_id])],
        causes=[], checks=[], actions=[], follow_up_questions=[])
    monkeypatch.setattr(ai, "_openai_client", lambda: SimpleNamespace(responses=SimpleNamespace(
        parse=lambda **kwargs: SimpleNamespace(output_parsed=draft, usage=None))))
    result = answering.answer_with_evidence("API 429 재시도", [chunk(vector_score=0.8)])
    assert not result.grounded
    assert result.citations == []
    assert "근거 부족" in result.generated.text


def test_google_key_masking():
    secret = "AIza" + "a" * 35
    assert secret not in mask_sensitive_text(f"key={secret}")
    assert "opaque-auth-key" not in mask_sensitive_text("GEMINI_API_KEY=opaque-auth-key")


def test_gemini_embeddings_normalize_mask_and_use_query_task(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(settings, "embedding_dimensions", 2)
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, json={"embeddings": [{"values": [3, 4]}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(ai.httpx, "post", post)
    vector = ai.embed_texts(["API user@example.com"], task_type="RETRIEVAL_QUERY")[0]
    assert math.isclose(sum(value * value for value in vector), 1)
    assert vector == [0.6, 0.8]
    request = captured["json"]["requests"][0]
    assert request["taskType"] == "RETRIEVAL_QUERY"
    assert request["outputDimensionality"] == 2
    assert "user@example.com" not in json.dumps(request)
    assert "fake-key" not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "fake-key"


def test_gemini_structured_answer_and_token_usage(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    draft = dict(answerable=True, summary=[dict(text="재시도 횟수를 제한합니다.", source_ids=["S1"])],
                 causes=[], checks=[], actions=[], follow_up_questions=[])
    def request(model, method, payload):
        assert method == "generateContent"
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert "user@example.com" not in json.dumps(payload)
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(draft)}]}}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 3}}
    monkeypatch.setattr(ai, "_gemini_request", request)
    generated = ai.generate_answer("API 429 user@example.com", "[S1] 재시도 횟수 제한", [{}])
    assert generated.answerable
    assert "[S1]" in generated.text
    assert generated.input_tokens == 100
    assert generated.output_tokens == 23


def test_gemini_rate_limit_is_reported_without_fallback_or_secret(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-secret")
    def post(url, **kwargs):
        return httpx.Response(429, json={"error": "fake-secret"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(ai.httpx, "post", post)
    with pytest.raises(RuntimeError, match="요청 한도") as error:
        ai._gemini_request("test-model", "generateContent", {})
    assert "fake-secret" not in str(error.value)


def test_recall_requires_all_relevant_documents_and_gate_matches_chat(tmp_path, monkeypatch):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps({"id": "multi", "question": "API 429", "answerable": True,
                                  "expected_documents": ["429.md", "latency.md"]}) + "\n")
    monkeypatch.setattr(settings, "evaluation_dataset_path", str(dataset))
    retrieved = [chunk(keyword_coverage=0.5, keyword_matches=2)]
    monkeypatch.setattr(evaluation, "retrieve_chunks", lambda *args, **kwargs:
                        RetrievalResult(retrieved, 1, "hybrid"))
    result = evaluation.run_evaluation(None)
    assert result.recall_at_k == 0.5
    assert result.results[0].hit_at_k
    assert result.results[0].predicted_answerable == bool(evidence_chunks(retrieved, "hybrid"))
