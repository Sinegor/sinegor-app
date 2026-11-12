FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SINEGOR_ENV_FILE=/dev/null
WORKDIR /app
RUN groupadd --gid 10001 sinegor && useradd --uid 10001 --gid sinegor --no-create-home sinegor \
    && mkdir -p /var/lib/sinegor/agreements /var/lib/sinegor/destruction \
    && chown -R sinegor:sinegor /var/lib/sinegor \
    && chmod 0700 /var/lib/sinegor/agreements /var/lib/sinegor/destruction
COPY --from=build /app/.venv ./.venv
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3)"]
CMD ["python", "-m", "uvicorn", "sinegor.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
