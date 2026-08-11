FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Dependencies resolve from uv.lock alone, so this layer is cached until the lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
# --no-editable so the runtime stage can copy the venv without the source tree.
# --reinstall-package because uv keys its built-wheel cache on name and version: the
# version rarely changes between deploys, so without this a code change silently ships
# the previously cached wheel. Dependencies still come from the cache mount untouched.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --reinstall-package bot-globa

FROM python:3.12-slim AS runtime

ARG APP_VERSION=0.1.0
LABEL org.opencontainers.image.title="Bot Globa" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/build/.venv/bin:${PATH}"

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /build/.venv /build/.venv
COPY migrations ./migrations
COPY alembic.ini ./
COPY docs ./docs
RUN chown -R appuser:appuser /app /build/.venv

USER appuser
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health/ready', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.api.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --timeout-graceful-shutdown \"${GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS:-30}\""]
