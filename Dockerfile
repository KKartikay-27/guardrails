# Hugging Face Spaces (Docker SDK) serves on 7860; also works on Fly.io / Render.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
RUN useradd -m -u 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY policies ./policies
COPY product ./product
RUN uv sync --frozen --no-dev && chown -R app /app
USER app
ENV GUARD_ROOT=/app GUARD_DECISION_LOG=/tmp/decisions.jsonl GUARD_LLM_CACHE_DIR=/tmp/llm-cache PATH="/app/.venv/bin:$PATH"
EXPOSE 7860
# One worker: prometheus_client metrics are per-process. Scale with replicas, not workers.
CMD ["uvicorn", "guardrail.server:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
