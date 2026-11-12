import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas import ReportResponse

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["victim", "offender", "refused"])
def test_examples_match_the_report_schema(name: str) -> None:
    ReportResponse.model_validate(load(name))


def test_rejects_citation_to_missing_source() -> None:
    body = load("victim")
    body["sources"] = [source for source in body["sources"] if source["id"] != "S2"]

    with pytest.raises(ValidationError, match="S2"):
        ReportResponse.model_validate(body)


def test_rejects_report_and_refusal_together() -> None:
    body = load("victim")
    body["refusal"] = load("refused")["refusal"]

    with pytest.raises(ValidationError, match="mutually exclusive"):
        ReportResponse.model_validate(body)


def test_empty_response_only_when_role_is_unclear() -> None:
    body = load("refused")
    body["refusal"] = None

    with pytest.raises(ValidationError, match="unclear"):
        ReportResponse.model_validate(body)
    body["reading"]["role"] = "unclear"
    ReportResponse.model_validate(body)


@pytest.mark.parametrize(("story", "role", "expected"), [
    ("메소 사려고 20만원 보냈는데 먹튀 당했어요", None, "victim"),
    ("아이템 판다고 하고 돈만 받고 차단했어요", None, "offender"),
    ("대화 내역 지우면 안 걸리나요?", None, "refused"),
    ("메소 사려고 20만원 보냈는데 먹튀 당했어요", "third_party", "third_party"),
])
def test_example_report_endpoint(story: str, role: str | None, expected: str) -> None:
    # no lifespan: the example endpoint does not touch the database
    response = TestClient(app).post("/api/report", json={"story": story, "role": role})

    assert response.status_code == 200
    body = ReportResponse.model_validate(response.json())
    assert (body.refusal is not None) if expected == "refused" else body.reading.role == expected
