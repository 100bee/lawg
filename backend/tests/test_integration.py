"""Real PostgreSQL/pgvector checks. Each test rolls back its own transaction."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Document, DocumentChunk, RetrievalTrace
from app.services.ingestion import ingest_markdown_text
from app.services.retrieval import retrieve_chunks


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
    monkeypatch.setattr(settings, "ai_provider", "local")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
    engine.dispose()


@pytest.fixture
def client(database):
    app.dependency_overrides[get_db] = lambda: database
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_upload_sanitizes_before_embedding_and_deduplicates(client, database, monkeypatch):
    from app.services import ingestion
    captured = []
    original_embed = ingestion.embed_texts
    def embed(texts):
        captured.extend(texts)
        return original_embed(texts)
    monkeypatch.setattr(ingestion, "embed_texts", embed)
    content = "# API 429\n재시도 횟수 제한. user@example.com sk-abcdefghijklmnop 10.20.30.40"
    first = client.post("/api/documents/upload", files={"file": ("test-secret.md", content)})
    second = client.post("/api/documents/upload", files={"file": ("copy-secret.md", content)})
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    saved = " ".join(database.scalars(select(DocumentChunk.content)).all())
    assert "user@example.com" not in saved
    assert "sk-abcdefghijklmnop" not in saved
    assert "10.20.30.40" not in saved
    assert all("user@example.com" not in value for value in captured)
    assert len(captured) == 1


def test_report_end_to_end_in_local_mode_keeps_personal_data_out(client, database):
    ingest_markdown_text(database, "test-347.md", (
        "---\ntitle: 형법 제347조 (사기)\ndocument_type: statute\neffective_date: 2026-10-02\n---\n"
        "제347조(사기) 게임 아이템 거래에서 돈을 보냈는데 먹튀 당했어요 같은 사기 사건에 쓰이는 조문 예시"))
    response = client.post("/api/report", json={"story": "게임 아이템 거래에서 돈을 보냈는데 먹튀 당했어요 010-1234-5678"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["report"] and payload["reading"]["category"] == "fraud"
    assert payload["sources"][0]["title"] == "형법 제347조 (사기)"
    assert "010-1234-5678" not in response.text
    trace = client.get(f"/api/traces/{payload['trace_id']}")
    assert trace.status_code == 200 and "010-1234-5678" not in trace.text
    assert all("010-1234-5678" not in row.question for row in database.scalars(select(RetrievalTrace)))
    assert client.post("/api/report", json={"story": "이혼 절차 알려줘"}).json()["refusal"]["kind"] == "out_of_scope"


def test_model_mismatch_requires_reindex_without_deleting_documents(database, monkeypatch):
    document, _ = ingest_markdown_text(database, "test-model.md", "# API 429\nAPI 429 재시도 제한.")
    original_id = document.id
    from app.services import retrieval, ingestion
    monkeypatch.setattr(retrieval, "embedding_fingerprint", lambda: "changed-model")
    with pytest.raises(ValueError, match="다시 색인"):
        retrieve_chunks(database, "API 429")
    monkeypatch.setattr(ingestion, "embedding_fingerprint", lambda: "changed-model")
    updated, indexed = ingest_markdown_text(database, "test-model.md", "# API 429\nAPI 429 재시도 제한.")
    assert indexed and updated.id == original_id
    assert updated.chunks[0].attributes["embedding_fingerprint"] == "changed-model"


def test_bad_uploads_return_400_and_do_not_replace_existing_document(client, database):
    document, _ = ingest_markdown_text(database, "test-bad.md", "# API 429\nAPI 429 재시도 제한.")
    for content in ("  ", "---\ntitle: missing delimiter", b"\xff\xfe", b"x" * 2_000_001):
        response = client.post("/api/documents/upload", files={"file": ("test-bad.md", content)})
        assert response.status_code == 400
    assert database.get(Document, document.id) is not None


def test_evaluation_uses_real_postgres_and_exports_configuration(client, database):
    removed, _ = ingest_markdown_text(database, "statute-dropped.md", "---\ntitle: 빠진 조문\ndocument_type: statute\n---\n본문")
    upload, _ = ingest_markdown_text(database, "upload.md", "# 업로드\n운영 문서")
    seed = client.post("/api/documents/seed")
    assert seed.status_code == 200 and seed.json()["failed"] == 0
    # a statute file taken out of the folder stops being searchable; other uploads stay
    assert database.get(Document, removed.id) is None and database.get(Document, upload.id) is not None
    result = client.post("/api/evaluations/compare?repetitions=1&split=challenge")
    assert result.status_code == 200
    payload = result.json()
    assert payload["cases"] == 6
    assert len(payload["results"]) == 3
    assert payload["provider"] == "local"
    assert len(payload["dataset_sha256"]) == 64
    assert payload["document_count"] == len(list(Path(settings.sample_data_dir).glob("*.md"))) + 1  # + the upload
    assert all(row["unanswerable_cases"] == 3 for row in payload["results"])


def test_reused_query_embeddings_preserve_results_without_extra_calls(database, monkeypatch):
    from app.services import evaluation, retrieval
    from app.services.ingestion import ingest_sample_documents

    ingest_sample_documents(database)
    baseline = evaluation.run_retrieval_comparison(database, repetitions=1, split="challenge")
    requests = []
    original_embed = evaluation.embed_texts

    def embed_once(texts, *, task_type):
        requests.append(list(texts))
        assert task_type == "RETRIEVAL_QUERY"
        return original_embed(texts, task_type=task_type)

    def unexpected_embed(*args, **kwargs):
        pytest.fail("Retrieval must reuse the supplied embedding instead of calling the provider")

    monkeypatch.setattr(evaluation, "embed_texts", embed_once)
    monkeypatch.setattr(retrieval, "embed_texts", unexpected_embed)
    cached = evaluation.run_retrieval_comparison(
        database, repetitions=2, split="challenge", reuse_query_embeddings=True,
    )
    assert len(requests) == 1 and len(requests[0]) == 6
    assert cached.query_embedding_inputs == 6
    assert cached.query_embedding_input_characters == sum(map(len, requests[0]))
    assert cached.query_embedding_reuse
    assert cached.retrieval_timing_scope == "database-and-ranking-only"
    for original, reused in zip(baseline.results, cached.results, strict=True):
        assert original.model_dump(exclude={"average_retrieval_ms"}) == reused.model_dump(
            exclude={"average_retrieval_ms"},
        )
