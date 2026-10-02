FROM node:22-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.11.23 AS uv
FROM python:3.13-slim-bookworm

COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PERSONAL_AI_DATA_DIR=/app/data
COPY pyproject.toml uv.lock ./
ARG LEGACY_EMBEDDING=false
RUN if [ "$LEGACY_EMBEDDING" = "true" ]; then \
      uv sync --frozen --no-install-project --group legacy-embedding; \
    else uv sync --frozen --no-install-project; fi
COPY apps/api ./apps/api
COPY apps/__init__.py ./apps/__init__.py
COPY core ./core
COPY infrastructure ./infrastructure
COPY prompts ./prompts
COPY mcp_servers ./mcp_servers
COPY scripts/__init__.py scripts/mcp_demo_server.py ./scripts/
COPY config ./config
COPY plugins ./plugins
COPY skills ./skills
RUN mkdir -p /app/data /workspace
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8787", "--no-proxy-headers"]
