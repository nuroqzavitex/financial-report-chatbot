#!/usr/bin/env bash
# Clean-machine smoke test: fresh virtualenv in a temp dir, uv sync, build the index if missing,
# answer data/sample_questions.json in batch mode and assert 10 rows without status "error".
#
# Exit codes: 0 OK | 1 assertion failed | 2 data/ files missing | 3 the LLM's API key missing
#             | 4 Ollama or its embedding model missing
# Needs: uv, Python 3.11 (uv fetches it if absent), Ollama with qwen3-embedding:4b, the data/ files
# (shipped in the repository, see README.md), and the key of LLM_MODEL (environment first, then .env,
# then .env.example): OPENAI_API_KEY for openai/*, OLLAMA_API_KEY for ollama_chat/* when
# OLLAMA_API_BASE=https://ollama.com; a signed-in local Ollama needs none. Calls the LLM for 10
# questions; embeddings stay on local Ollama (free).
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

# value of a setting: the environment, else .env, else .env.example (values are never printed)
setting() {
  local v="${!1:-}" f
  if [ -z "$v" ]; then
    for f in .env .env.example; do
      [ -f "$f" ] && v="$(sed -n "s/^$1=\([^ #]*\).*/\1/p" "$f" | tail -n 1)"
      [ -n "$v" ] && break
    done
  fi
  printf '%s' "$v"
}

# 2. embeddings run on Ollama (the shipped index was embedded with qwen3-embedding:4b)
OLLAMA="$(setting EMBED_API_BASE)"
OLLAMA="${OLLAMA:-http://localhost:11434}"
if ! curl -fsS "$OLLAMA/api/tags" 2>/dev/null | grep -q '"qwen3-embedding:4b"'; then
  echo "MISSING: Ollama at $OLLAMA with qwen3-embedding:4b (install Ollama, then: ollama pull qwen3-embedding:4b)" >&2
  exit 4
fi

# 3. the API key of the configured LLM
LLM="$(setting LLM_MODEL)"
KEY=""
case "$LLM" in
  openai/*) KEY=OPENAI_API_KEY ;;
  anthropic/*) KEY=ANTHROPIC_API_KEY ;;
  gemini/*) KEY=GEMINI_API_KEY ;;
  ollama/* | ollama_chat/*) case "$(setting OLLAMA_API_BASE)" in *ollama.com*) KEY=OLLAMA_API_KEY ;; esac ;;
esac
if [ -n "$KEY" ] && [ -z "$(setting "$KEY")" ]; then
  echo "MISSING: $KEY for LLM_MODEL=$LLM (set it in the environment or in .env, then run again)." >&2
  [ -f index/manifest.json ] || echo "index/ is not built yet (no index/manifest.json); it is built from the PDF on the next run." >&2
  exit 3
fi
echo "== LLM_MODEL=$LLM"

command -v uv >/dev/null || { echo "MISSING: uv (https://docs.astral.sh/uv/)" >&2; exit 1; }

# 4. everything this run writes goes to a temp dir: fresh venv, empty Qdrant/SQLite/cache/traces
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export UV_PROJECT_ENVIRONMENT="$WORK/venv"
export QDRANT_PATH="$WORK/qdrant"
export DATABASE_URL="sqlite:///$WORK/app.db"
export TRACE_DIR="$WORK/traces"
unset QDRANT_URL || true

echo "== uv sync (fresh venv: $UV_PROJECT_ENVIRONMENT)"
uv sync --frozen

# NOTE: steps 5 and 6 write into the repository working tree (.env and index/), not the temp dir:
# both are meant to stay (index/ is committed with the submission; .env is gitignored).
# 5. .env from the example; never overwrite an existing one. Keys come from the environment or .env.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "== created .env from .env.example (API keys are read from the environment)"
fi

# 6. index (committed in the final submission; built here when absent)
if [ ! -f index/manifest.json ]; then
  echo "== index/ missing: building it from the PDF (embeddings on Ollama)"
  uv run ircb ingest "$PDF" --out index
fi

# 7. batch over the 10 published questions
OUT="$WORK/out.jsonl"
echo "== ircb batch $QUESTIONS"
uv run ircb batch "$QUESTIONS" --out "$OUT"

# 8. assertions
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
