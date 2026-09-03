"""Run reproducible retrieval experiments: python -m app.evaluate --seed."""
import argparse
import json
from pathlib import Path

from app.database import SessionLocal, init_database
from app.services.evaluation import run_retrieval_comparison
from app.services.ingestion import ingest_sample_documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="Index/reindex sample documents first")
    parser.add_argument("--repetitions", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--split", choices=["all", "dev", "challenge"], default="all")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reuse-query-embeddings", action="store_true",
                        help="Embed each distinct question once; report preparation time separately")
    args = parser.parse_args()
    init_database()
    with SessionLocal() as database:
        if args.seed:
            _, _, _, failed = ingest_sample_documents(database)
            if failed:
                parser.error(f"{failed} sample documents failed to index; experiment aborted")
        result = run_retrieval_comparison(
            database, repetitions=args.repetitions, split=args.split,
            reuse_query_embeddings=args.reuse_query_embeddings,
        )
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
