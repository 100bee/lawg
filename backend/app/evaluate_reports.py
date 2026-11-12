"""End-to-end report evaluation over a JSONL set.

usage: python -m app.evaluate_reports --dataset data/eval/dev.jsonl [--split dev] [--output out.json]

Model calls are cached on disk (keyed by model, prompt version, instructions and payload), so a rerun only pays
for new or changed items; the free tier allows roughly 500 generation calls a day.
"""
import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from statistics import mean

from app.config import settings
from app.database import SessionLocal, init_database
from app.models import RetrievalTrace
from app.services import report
from app.services.ai import ContentBlocked, ProviderBusy

SOURCES = Path(__file__).resolve().parents[1] / "data" / "sources"


def _title_to_file() -> dict[str, str]:
    titles = {}
    for path in SOURCES.glob("*.md"):
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            if line.startswith("title:"):
                titles[line.split(":", 1)[1].strip()] = path.name
                break
            if line == "---":
                break
    return titles


def cached(call, cache_path: Path, counter: Counter):
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    def wrapper(instructions, payload, schema, *, max_output_tokens):
        key = hashlib.sha256(json.dumps(
            [schema.__name__, settings.chat_model, settings.prompt_version, instructions, payload],
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if key in cache:
            counter["cache_hits"] += 1
            hit = cache[key]
            return schema.model_validate(hit["value"]), *hit["tokens"]
        counter["model_calls"] += 1
        value, used_in, used_out = call(instructions, payload, schema, max_output_tokens=max_output_tokens)
        cache[key] = {"value": value.model_dump(mode="json"), "tokens": [used_in, used_out]}
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        return value, used_in, used_out

    return wrapper


def score(item: dict, response, titles: dict[str, str], evidence_titles: list[str] = ()) -> dict:
    """One row per item. response is a ReportResponse, or a string naming the error.
    evidence_titles: what passed the evidence gate (from the trace); the response itself keeps only cited sources."""
    row = {"id": item["id"], "category": item["category"], "role": item["role"],
           "expected_refusal": item["refusal"], "answerable": item["answerable"], "pair": item.get("pair")}
    if isinstance(response, str):
        return {**row, "error": response}
    by_id = {source.id: titles.get(source.title, source.title) for source in response.sources}
    # every section counts: guides are cited from actions, not laws
    cited = sorted({by_id[source] for source in response.report.cited_ids()}) if response.report else []
    laws = sorted({by_id[law.source] for law in response.report.laws}) if response.report else []
    expected = set(item["expected_documents"])
    retrieved = sorted({titles.get(title, title) for title in evidence_titles})
    predicted_refusal = response.refusal.kind if response.refusal else ("ask_role" if not response.report else None)
    return {
        **row,
        "predicted_role": response.reading.role,
        "predicted_category": response.reading.category or "out_of_scope",
        "predicted_refusal": predicted_refusal,
        "cited": cited,
        "cited_laws": laws,
        "retrieved": retrieved,
        "citation_recall": len(expected & set(cited)) / len(expected) if expected else None,
        "retrieval_recall": len(expected & set(retrieved)) / len(expected) if expected else None,
    }


def summarize(rows: list[dict]) -> dict:
    ok = [row for row in rows if "error" not in row]
    answerable = [row for row in ok if row["answerable"]]
    refusals = [row for row in ok if not row["answerable"]]
    known_role = [row for row in answerable if row["role"] != "unclear"]
    pairs: dict[str, list[dict]] = {}
    for row in answerable:
        if row["pair"]:
            pairs.setdefault(row["pair"], []).append(row)
    complete_pairs = [members for members in pairs.values() if len(members) == 2]
    by_kind = {kind: [row for row in refusals if row["expected_refusal"] == kind]
               for kind in sorted({row["expected_refusal"] for row in refusals})}

    def rate(values):
        values = list(values)
        return round(mean(values), 3) if values else None

    return {
        "items": len(rows),
        "errors": Counter(row["error"] for row in rows if "error" in row),
        "answerable": {
            "items": len(answerable),
            # an unclear-role story should get the role question, not a report
            "report_rate": rate(row["predicted_refusal"] == ("ask_role" if row["role"] == "unclear" else None)
                                for row in answerable),
            "citation_recall": rate(row["citation_recall"] for row in answerable),
            "retrieval_recall": rate(row["retrieval_recall"] for row in answerable),
            "role_accuracy": rate(row["predicted_role"] == row["role"] for row in known_role),
            "category_accuracy": rate(row["predicted_category"] == row["category"] for row in answerable),
        },
        "refusals": {
            "items": len(refusals),
            "refused_any_way": rate(row["predicted_refusal"] is not None for row in refusals),
            "by_kind": {kind: {"items": len(members),
                               "right_kind": rate(row["predicted_refusal"] == kind for row in members)}
                        for kind, members in by_kind.items()},
        },
        "pairs": {"complete": len(complete_pairs),
                  "same_laws": rate(a["cited_laws"] == b["cited_laws"] for a, b in complete_pairs)},
        "seconds": {"mean": rate(row["seconds"] for row in rows if "seconds" in row),
                    "max": max((row["seconds"] for row in rows if "seconds" in row), default=None)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", default="all")
    parser.add_argument("--cache", type=Path, default=Path("data/eval-cache.json"))
    parser.add_argument("--sleep", type=float, default=4.5, help="seconds between items that called the model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    items = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = [item for item in items if args.split == "all" or item["split"] == args.split]
    counter: Counter = Counter()
    report.structured_call = cached(report.structured_call, args.cache, counter)
    titles = _title_to_file()
    init_database()
    rows = []
    with SessionLocal() as database:
        for index, item in enumerate(items, start=1):
            calls_before, started = counter["model_calls"], time.perf_counter()
            try:
                response = report.build_report(database, item["question"])
            except (ContentBlocked, ProviderBusy, RuntimeError, ValueError) as error:  # ValueError: stale index
                database.rollback()
                response = type(error).__name__
            trace = None if isinstance(response, str) else database.get(RetrievalTrace, response.trace_id)
            evidence = [chunk["title"] for chunk in trace.retrieved_chunks if chunk["accepted"]] if trace else []
            rows.append({**score(item, response, titles, evidence), "seconds": round(time.perf_counter() - started, 2)})
            print(f"[{index}/{len(items)}] {item['id']} {rows[-1].get('predicted_refusal') or rows[-1].get('error') or 'report'}",
                  flush=True)
            if counter["model_calls"] > calls_before and settings.ai_provider != "local":
                time.sleep(args.sleep)
    summary = {**summarize(rows), "model_calls": counter["model_calls"], "cache_hits": counter["cache_hits"],
               "provider": settings.ai_provider, "model": settings.chat_model, "prompt_version": settings.prompt_version,
               "threshold": settings.gemini_minimum_semantic_score, "retrieval_mode": settings.report_retrieval_mode,
               "dataset": f"{args.dataset.name}:{args.split}"}
    payload = json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2, default=list)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=list))


if __name__ == "__main__":
    main()
