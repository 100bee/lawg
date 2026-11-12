import uuid
from datetime import datetime, timezone

from app.evaluate_reports import score, summarize
from app.schemas import Cited, LawItem, Reading, Refusal, Report, ReportResponse, Source

TITLES = {"형법 제347조 (사기)": "criminal-347.md", "형법 제52조 (자수, 자복)": "criminal-52.md"}


def response(role="victim", laws=("S1",), refusal=None):
    sources = [Source(id="S1", kind="statute", title="형법 제347조 (사기)", text="…"),
               Source(id="S2", kind="statute", title="형법 제52조 (자수, 자복)", text="…")]
    report = None if refusal else Report(summary="요약", laws=[LawItem(source=s, plain="풀이") for s in laws],
                                         penalty=[], facts_to_check=[], actions=[], prepare=[], cannot_answer=[])
    return ReportResponse(reading=Reading(role=role, category="fraud"), report=report,
                          refusal=Refusal(kind=refusal, message="거절") if refusal else None,
                          sources=sources, trace_id=uuid.uuid4(), created_at=datetime.now(timezone.utc))


def item(id, role="victim", refusal=None, expected=("criminal-347.md",), pair=None):
    return {"id": id, "category": "fraud", "role": role, "refusal": refusal, "answerable": refusal is None,
            "expected_documents": [] if refusal else list(expected), "pair": pair}


def test_scores_citations_roles_refusals_and_pairs():
    rows = [
        {**score(item("a", pair="p1"), response(), TITLES, ["형법 제347조 (사기)"]), "seconds": 3.0},
        {**score(item("b", role="offender", pair="p1"), response(role="victim", laws=("S1", "S2")), TITLES), "seconds": 5.0},
        {**score(item("c", refusal="evasion"), response(refusal="evasion"), TITLES), "seconds": 1.0},
        {**score(item("d", refusal="referral"), response(refusal="out_of_scope"), TITLES), "seconds": 1.0},
        score(item("e"), "ProviderBusy", TITLES),
    ]
    summary = summarize(rows)

    assert rows[1]["cited"] == ["criminal-347.md", "criminal-52.md"] and rows[1]["citation_recall"] == 1.0
    assert rows[0]["retrieval_recall"] == 1.0 and rows[1]["retrieval_recall"] == 0.0  # from the trace, not the reply
    assert summary["answerable"]["role_accuracy"] == 0.5  # the offender was read as a victim
    assert summary["refusals"]["refused_any_way"] == 1.0
    assert summary["refusals"]["by_kind"]["referral"]["right_kind"] == 0.0
    assert summary["pairs"] == {"complete": 1, "same_laws": 0.0, "same_statutes": 0.0, "share_a_statute": 1.0}
    assert summary["errors"] == {"ProviderBusy": 1} and summary["seconds"]["max"] == 5.0


def test_penalty_numbers_must_come_from_the_cited_source():
    reply = response()
    reply.sources[0].text = "20년 이하의 징역 또는 5천만원 이하의 벌금에 처한다."
    reply.report.penalty = [Cited(text="20년 이하 징역, 5,000만 원 이하 벌금", sources=["S1"]),
                            Cited(text="10년 이하의 징역 또는 2천만원 이하의 벌금", sources=["S1"]),  # the pre-2025 range
                            Cited(text="실제 형은 재판에서 정해집니다.", sources=[])]
    row = score(item("a"), reply, TITLES)

    assert (row["penalty_claims"], row["penalty_grounded"]) == (2, 1)
