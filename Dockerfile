# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci
COPY apps/web ./apps/web
COPY assets ./assets
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /usr/local/bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    SIGNAL_SLATE_ENV_FILE="" \
    SIGNAL_SLATE_RUNTIME_ENABLED=false \
    SIGNAL_SLATE_SECURE_COOKIES=true \
    SIGNAL_SLATE_STATIC_DIR=/app/static
WORKDIR /app
RUN useradd --create-home --uid 10001 slate && chown slate:slate /app
COPY --chown=slate:slate pyproject.toml uv.lock README.md LICENSE alembic.ini ./
COPY --chown=slate:slate services/api ./services/api
USER slate
RUN uv sync --locked --no-dev --no-editable \
    && uvx mcp-grafana==1.3.0 --help >/dev/null
COPY --from=frontend --chown=slate:slate /build/apps/web/dist ./static
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4)"
CMD ["python", "-m", "signal_slate.container_startup"]
