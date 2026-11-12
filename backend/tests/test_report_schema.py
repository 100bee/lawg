import json
from pathlib import Path

import pytest
from pydantic import ValidationError

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

