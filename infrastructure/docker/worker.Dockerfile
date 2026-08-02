FROM ghcr.io/astral-sh/uv:0.11.24 AS uv

FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/workspace/.venv/bin:${PATH}"

RUN apk add --no-cache libstdc++ \
    && addgroup -S app \
    && adduser -S -G app -h /nonexistent app
WORKDIR /workspace

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project \
    && rm -rf /root/.cache/uv /bin/uv /bin/uvx
COPY --chown=app:app apps/__init__.py ./apps/__init__.py
COPY --chown=app:app apps/api/__init__.py ./apps/api/__init__.py
COPY --chown=app:app apps/api/app ./apps/api/app
COPY --chown=app:app apps/worker ./apps/worker
COPY --chown=app:app ingestion ./ingestion

USER app

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 \
    CMD ["python", "-m", "apps.worker.worker.health"]

CMD ["python", "-m", "apps.worker.worker.main"]
