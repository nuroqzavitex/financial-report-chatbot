#!/usr/bin/env bash
# Clean-machine smoke test: fresh virtualenv in a temp dir, uv sync, build the index if missing,
# answer data/sample_questions.json in batch mode and assert 10 rows without status "error".
#
# Exit codes: 0 OK | 1 assertion failed | 2 data/ files missing | 3 OPENAI_API_KEY missing
# Needs: uv, Python 3.11 (uv fetches it if absent), OPENAI_API_KEY in the environment, and the
# data/ files (shipped in the repository, see README.md). Uses the real OpenAI API (about the cost of one index
# build plus 10 questions).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PDF="data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf"
QUESTIONS="data/sample_questions.json"

# 1. inputs under data/
missing=0
for f in "$PDF" "$QUESTIONS"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f" >&2
    missing=1
  fi
done
if [ "$missing" -eq 1 ]; then
  cat >&2 <<MSG

data/ files are missing (they ship with the repository; restore them with git checkout -- data/):
  $PDF
  $QUESTIONS
then run this script again.
MSG
  exit 2
fi

# 2. API key (the default configuration uses OpenAI for the LLM and for embeddings)
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "MISSING: OPENAI_API_KEY is not set in the environment." >&2
  if [ ! -f index/manifest.json ]; then
    echo "index/ is not built yet (no index/manifest.json): the first run builds it with the embedding API," >&2
    echo "so a key is required: export OPENAI_API_KEY=sk-... and run this script again." >&2
  else
    echo "export OPENAI_API_KEY=sk-... and run this script again." >&2
  fi
  exit 3
fi

command -v uv >/dev/null || { echo "MISSING: uv (https://docs.astral.sh/uv/)" >&2; exit 1; }

# 3. everything this run writes goes to a temp dir: fresh venv, empty Qdrant/SQLite/cache/traces
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export UV_PROJECT_ENVIRONMENT="$WORK/venv"
export QDRANT_PATH="$WORK/qdrant"
export DATABASE_URL="sqlite:///$WORK/app.db"
export TRACE_DIR="$WORK/traces"
unset QDRANT_URL || true

echo "== uv sync (fresh venv: $UV_PROJECT_ENVIRONMENT)"
uv sync --frozen

# NOTE: steps 4 and 5 write into the repository working tree (.env and index/), not the temp dir:
# both are meant to stay (index/ is committed with the submission; .env is gitignored).
# 4. .env from the example; never overwrite an existing one. The key comes from the environment.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "== created .env from .env.example (OPENAI_API_KEY is read from the environment)"
fi

# 5. index (committed in the final submission; built here when absent)
if [ ! -f index/manifest.json ]; then
  echo "== index/ missing: building it from the PDF (embedding API calls)"
  uv run ircb ingest "$PDF" --out index
fi

# 6. batch over the 10 published questions
OUT="$WORK/out.jsonl"
echo "== ircb batch $QUESTIONS"
uv run ircb batch "$QUESTIONS" --out "$OUT"

# 7. assertions
uv run python -I - "$OUT" <<'PY'
import json
import sys

rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
errors = [r.get("id") for r in rows if r.get("status") == "error"]
if len(rows) != 10:
    sys.exit(f"FAIL: expected 10 rows, got {len(rows)}")
if errors:
    sys.exit(f"FAIL: rows with status=error: {errors}")
print(f"OK {len(rows)}/10")
PY
