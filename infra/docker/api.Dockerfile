# API image: FastAPI app (ircb_api) on the core library, installed from the workspace lock.
# Build context is the repo root (see docker-compose.yml). index/ and data/ are mounted at run time,
# never baked in: data/ is confidential and index/ is built locally.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# dependency layer: only the manifests every workspace member needs to resolve the lock
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/cli/pyproject.toml apps/cli/pyproject.toml
RUN uv sync --frozen --no-dev --package ircb-api --no-install-workspace

COPY packages/core packages/core
COPY apps/api apps/api
COPY apps/cli apps/cli
COPY config config
RUN uv sync --frozen --no-dev --package ircb-api

ENV PATH="/app/.venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=12 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "ircb_api"]
