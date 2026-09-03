#!/usr/bin/env bash
set -euo pipefail

api_url="${RAGOPS_API_URL:-http://localhost:8000}"
repetitions="${RAGOPS_EVAL_REPETITIONS:-1}"
ready=false
for attempt in {1..30}; do
  if curl --silent --fail "$api_url/api/health" > /dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  echo "Backend did not become ready within 30 seconds." >&2
  exit 1
fi
curl --silent --show-error --fail "$api_url/api/health"
printf '\n'
seed_result="$(curl --silent --show-error --fail -X POST "$api_url/api/documents/seed")"
printf '%s\n' "$seed_result"
if ! printf '%s' "$seed_result" | python3 -c 'import json,sys; sys.exit(bool(json.load(sys.stdin)["failed"]))'; then
  echo "Indexing failed; experiment aborted. Check provider configuration and quota." >&2
  exit 1
fi
curl --silent --show-error --fail -X POST "$api_url/api/evaluations/compare?repetitions=$repetitions"
printf '\n'
