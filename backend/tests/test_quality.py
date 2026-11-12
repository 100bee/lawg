import json
import math
import uuid

import httpx
import pytest
from pydantic import BaseModel

from app.config import settings
from app.services import ai, evaluation
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


@pytest.mark.parametrize("vector_score,accepted", [(0.55, False), (0.70, True)])
def test_gemini_vector_gate_uses_calibrated_threshold(monkeypatch, vector_score, accepted):
    # Off-domain Gemini questions still score about 0.54; answerable ones score 0.69 or higher.
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    assert bool(evidence_chunks([chunk(vector_score=vector_score)], "vector")) is accepted


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


class Probe(BaseModel):
    answer: str


def test_gemini_structured_call_parses_json_counts_tokens_and_allows_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    seen = {}
    def request(model, method, payload, *, fallback_model=None):
        seen.update(model=model, method=method, fallback=fallback_model, payload=json.dumps(payload, ensure_ascii=False))
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"answer": "ok"}'}]}}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 3}}
    monkeypatch.setattr(ai, "_gemini_request", request)
    parsed, input_tokens, output_tokens = ai.structured_call(
        "지시", {"story": "user@example.com"}, Probe, max_output_tokens=64)
    assert parsed.answer == "ok" and (input_tokens, output_tokens) == (100, 23)
    assert seen["method"] == "generateContent" and seen["fallback"] == settings.gemini_fallback_chat_model
    assert "user@example.com" not in seen["payload"]
    assert '"responseMimeType": "application/json"' in seen["payload"]


@pytest.mark.parametrize("response", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"finishReason": "PROHIBITED_CONTENT"}]},
])
def test_gemini_safety_block_is_reported_as_blocked(monkeypatch, response):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(ai, "_gemini_request", lambda *args, **kwargs: response)
    with pytest.raises(ai.ContentBlocked):
        ai.structured_call("지시", {"story": "욕설"}, Probe, max_output_tokens=64)


def test_gemini_rate_limit_retries_once_then_reports_without_secret(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-secret")
    monkeypatch.setattr(settings, "gemini_retry_delay_seconds", 0)
    calls = []
    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(429, json={"error": "fake-secret"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(ai.httpx, "post", post)
    with pytest.raises(ai.ProviderBusy, match="1분쯤") as error:
        ai._gemini_request("test-model", "generateContent", {})
    assert "fake-secret" not in str(error.value)
    assert len(calls) == 2


def test_gemini_daily_quota_says_come_back_tomorrow(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-secret")
    monkeypatch.setattr(settings, "gemini_retry_delay_seconds", 0)
    body = {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
    monkeypatch.setattr(ai.httpx, "post", lambda url, **kwargs: httpx.Response(
        429, json=body, request=httpx.Request("POST", url)))
    with pytest.raises(ai.ProviderBusy, match="내일"):
        ai._gemini_request("model", "embedContent", {})


def test_gemini_overload_falls_back_to_the_other_model(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-secret")
    monkeypatch.setattr(settings, "gemini_retry_delay_seconds", 0)
    calls = []
    def post(url, **kwargs):
        calls.append(url)
        if "primary" in url:
            return httpx.Response(503, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))
    monkeypatch.setattr(ai.httpx, "post", post)
    assert ai._gemini_request("primary", "generateContent", {}, fallback_model="backup") == {"ok": True}
    assert [url.split("/models/")[1] for url in calls] == ["primary:generateContent"] * 2 + ["backup:generateContent"]


def test_gemini_bad_request_is_not_retried(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-secret")
    calls = []
    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(400, json={"error": "fake-secret"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(ai.httpx, "post", post)
    with pytest.raises(RuntimeError, match="호출에 실패") as error:
        ai._gemini_request("model", "generateContent", {}, fallback_model="backup")
    assert "fake-secret" not in str(error.value) and len(calls) == 1


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


def test_gemini_schema_miss_is_asked_once_more(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    replies = iter(['{"answer": 1}', '{"answer": "ok"}'])
    monkeypatch.setattr(ai, "_gemini_request", lambda *args, **kwargs: {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": next(replies)}]}}]})
    assert ai.structured_call("지시", {}, Probe, max_output_tokens=64)[0].answer == "ok"
