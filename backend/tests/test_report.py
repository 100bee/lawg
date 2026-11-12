import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.schemas import Cited, LawItem, Term
from app.services import report
from app.services.ai import ContentBlocked, ProviderBusy
from app.services.retrieval import RetrievalResult, RetrievedChunk


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, row):
        row.id, row.created_at = uuid.uuid4(), datetime.now(timezone.utc)
        self.added.append(row)

    def commit(self):
        pass

    def refresh(self, row):
        pass


def statute(title="형법 제347조 (사기)", content="제347조(사기) ① 사람을 기망하여 재물의 교부를 받은 자는 처벌한다.",
            document_type="statute"):
    return RetrievedChunk(id=uuid.uuid4(), document_id=uuid.uuid4(), title=title, source_name="criminal-347.md",
                          chunk_index=0, heading=title, content=content, score=0.8, vector_score=0.8,
                          keyword_score=0.0, attributes={"document_type": document_type, "url": "https://law.go.kr",
                                                         "effective_date": "2026-10-02"})


def classified(role="victim", category="fraud", request="report"):
    return report.Classification(role=role, category=category, request=request,
                                 terms=[Term(said="먹튀", legal=["거래 사기"])])


def draft(**overrides):
    values = dict(answerable=True, summary="돈을 보냈지만 물건을 받지 못했습니다.",
                  laws=[LawItem(source="S1", plain="속여서 돈을 받으면 사기가 될 수 있습니다.")],
                  penalty=[Cited(text="법정형은 조문에 적혀 있습니다.", sources=["S1"])],
                  facts_to_check=["대화가 남아 있나요?"], actions=[Cited(text="캡처해 둡니다.", sources=[])],
                  prepare=["이체 확인증"], cannot_answer=["실제 처벌"])
    return report.ReportDraft(**{**values, **overrides})


@pytest.fixture
def gemini(monkeypatch):
    """Pretend to be in Gemini mode; each test decides what classify/retrieve/write return."""
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    calls = {"retrieve": 0, "write": 0}
    state = {"classification": classified(), "chunks": [statute()], "draft": draft()}

    def structured_call(instructions, payload, schema, *, max_output_tokens):
        if schema is report.Classification:
            return state["classification"], 10, 5
        calls["write"] += 1
        calls["payload"] = payload
        return state["draft"], 100, 50

    def retrieve(database, query, *, mode):
        calls["retrieve"] += 1
        calls["query"] = query
        return RetrievalResult(state["chunks"], 3, mode)

    monkeypatch.setattr(report, "structured_call", structured_call)
    monkeypatch.setattr(report, "retrieve_chunks", retrieve)
    monkeypatch.setattr(report, "evidence_chunks", lambda chunks, mode: chunks)
    return state, calls


def test_report_cites_verbatim_statute_without_its_heading(gemini):
    state, calls = gemini
    result = report.build_report(FakeSession(), "메소 사려고 010-1234-5678로 연락했는데 먹튀 당했어요")

    assert result.report and not result.refusal
    assert result.sources[0].text == "① 사람을 기망하여 재물의 교부를 받은 자는 처벌한다."
    assert result.sources[0].effective_date.isoformat() == "2026-10-02"
    assert "010-1234-5678" not in calls["query"] and "010-1234-5678" not in str(calls["payload"])
    assert "거래 사기" in calls["query"]  # legal terms join the story in the search query


@pytest.mark.parametrize(("request_kind", "category", "expected"), [
    ("evasion", "fraud", "evasion"),
    ("referral", "obscenity", "referral"),
    ("report", "out_of_scope", "out_of_scope"),
    ("individual_conclusion", "fraud", "individual_conclusion"),
])
def test_refusals_decided_before_search_skip_search_and_writing(gemini, request_kind, category, expected):
    state, calls = gemini
    state["classification"] = classified(category=category, request=request_kind)
    result = report.build_report(FakeSession(), "사건")

    assert result.refusal.kind == expected and result.report is None
    assert calls["retrieve"] == 0 and calls["write"] == 0


def test_no_statute_evidence_refuses_without_writing(gemini):
    state, calls = gemini
    state["chunks"] = [statute(title="안내", content="신고 안내", document_type="guide")]
    result = report.build_report(FakeSession(), "사건")

    assert result.refusal.kind == "no_evidence" and result.sources == []
    assert calls["write"] == 0


@pytest.mark.parametrize("bad", [
    {"answerable": False},
    {"laws": [LawItem(source="S9", plain="없는 출처")]},
    {"penalty": [Cited(text="출처 없이 1년 이하 징역", sources=[])]},
    {"laws": []},
])
def test_model_refusal_or_bad_citation_becomes_no_evidence(gemini, bad):
    state, _ = gemini
    state["draft"] = draft(**bad)
    result = report.build_report(FakeSession(), "사건")

    assert result.report is None and result.refusal.kind == "no_evidence"


def test_unclear_role_asks_instead_of_searching(gemini):
    state, calls = gemini
    state["classification"] = classified(role="unclear")
    result = report.build_report(FakeSession(), "사건")

    assert result.reading.role == "unclear" and not result.report and not result.refusal
    assert calls["retrieve"] == 0


def test_role_correction_overrides_the_model(gemini):
    _, calls = gemini
    result = report.build_report(FakeSession(), "사건", role_override="offender")

    assert result.reading.role == "offender" and calls["payload"]["role"] == "offender"


def test_trace_stores_only_the_masked_story(gemini):
    session = FakeSession()
    report.build_report(session, "제 이름은 홍길동이고 계좌 123-456-789012로 보냈어요")

    trace = session.added[0]
    assert "홍길동" not in trace.question and "123-456-789012" not in trace.question
    assert trace.input_tokens == 110 and trace.output_tokens == 55


@pytest.mark.parametrize(("error", "status"), [
    (ContentBlocked("차단"), 422),  # visitor can rephrase
    (ProviderBusy("바빠요"), 503),  # visitor can retry later
    (RuntimeError("GEMINI_API_KEY 없음"), 502),  # operator problem; the page shows a generic message
])
def test_report_errors_map_to_status_codes(monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr("app.api.routes.build_report", fail)
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(app).post("/api/report", json={"story": "욕설이 든 사건"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status and response.json()["detail"] == str(error)


def test_local_classifier_reads_role_category_and_requests() -> None:
    assert report._classify_local("메소 보냈는데 먹튀 당했어요").model_dump(include={"role", "category"}) == {
        "role": "victim", "category": "fraud"}
    assert report._classify_local("게임에서 욕했는데 고소당했어요").role == "offender"
    assert report._classify_local("대화 내역 지우면 안 걸리나요").request == "evasion"
    assert report._classify_local("이혼 절차 알려줘").category == "out_of_scope"


def test_admin_endpoints_need_the_token_when_one_is_set(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    try:
        for method, path in [("post", "/api/documents/seed"), ("post", "/api/evaluations/run"),
                             ("post", "/api/evaluations/compare"), ("get", f"/api/traces/{uuid.uuid4()}")]:
            assert getattr(client, method)(path).status_code == 401
            assert getattr(client, method)(path, headers={"x-admin-token": "wrong"}).status_code == 401
        assert client.post("/api/documents/upload", files={"file": ("a.md", "x")}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_report_rate_limit_is_per_client(monkeypatch):
    from app.api import routes
    monkeypatch.setattr(settings, "report_rate_limit", 2)
    monkeypatch.setattr(routes, "_report_times", routes.defaultdict(routes.deque))
    monkeypatch.setattr(routes, "build_report", lambda *args: (_ for _ in ()).throw(ContentBlocked("x")))
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    try:
        statuses = [client.post("/api/report", json={"story": "사건 설명"},
                                headers={"x-forwarded-for": "6.6.6.6, 1.1.1.1"}).status_code for _ in range(3)]
        other = client.post("/api/report", json={"story": "사건 설명"}, headers={"x-forwarded-for": "2.2.2.2"})
    finally:
        app.dependency_overrides.clear()
    assert statuses == [422, 422, 429]  # the forged left-most entry does not give a fresh budget
    assert other.status_code == 422


def test_precedent_sources_carry_case_number_and_date(gemini):
    state, _ = gemini
    precedent = statute(title="대법원 2020도0000 (예시)", content="판결요지 예시", document_type="precedent")
    precedent.attributes.update(case_number="2020도0000", decided_on="2020-01-01")
    state["chunks"] = [statute(), precedent]
    state["draft"] = draft(laws=[LawItem(source="S1", plain="풀이"), LawItem(source="S2", plain="판례 기준")])
    result = report.build_report(FakeSession(), "사건")

    assert result.report and result.sources[1].kind == "precedent"
    assert result.sources[1].case_number == "2020도0000" and result.sources[1].decided_on.isoformat() == "2020-01-01"


def test_uncited_penalty_note_without_numbers_is_fine(gemini):
    state, _ = gemini
    state["draft"] = draft(penalty=[Cited(text="법정형은 조문에 적혀 있습니다 1년", sources=["S1"]),
                                    Cited(text="실제 형은 재판에서 정해집니다.", sources=[])])
    assert report.build_report(FakeSession(), "사건").report is not None
