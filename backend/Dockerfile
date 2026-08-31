FROM python:3.12-slim

# Use uv for dependency resolution and installation. The uv binary is copied
# from the official image so the runtime image does not need pip to bootstrap
# the environment.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN uv pip install --system --index-url https://pypi.tuna.tsinghua.edu.cn/simple .

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/backend/storage /app/backend/exports \
    && chown -R app:app /app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
