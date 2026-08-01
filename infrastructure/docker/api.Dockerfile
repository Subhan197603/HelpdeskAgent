FROM ghcr.io/astral-sh/uv:0.11.24 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/workspace/.venv/bin:${PATH}"

RUN groupadd --system app && useradd --system --gid app --home-dir /nonexistent app
WORKDIR /workspace

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project \
    && rm -rf /root/.cache/uv /bin/uv /bin/uvx
COPY --chown=app:app apps/__init__.py ./apps/__init__.py
COPY --chown=app:app apps/api/__init__.py ./apps/api/__init__.py
COPY --chown=app:app apps/api/app ./apps/api/app
COPY --chown=app:app apps/api/alembic.ini ./apps/api/alembic.ini
COPY --chown=app:app apps/api/alembic ./apps/api/alembic

USER app
EXPOSE 8000

CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
