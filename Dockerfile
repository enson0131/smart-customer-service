FROM ghcr.io/astral-sh/uv:0.10.9 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt -o /tmp/locked.txt \
 && uv pip install --system --no-cache -c /tmp/locked.txt fastapi uvicorn langchain langchain-deepseek langgraph langgraph-checkpoint-sqlite httpx python-dotenv
COPY constants ./constants
COPY service ./service
COPY knowledge ./knowledge
EXPOSE 8080
CMD ["uvicorn","service.app:app","--host","0.0.0.0","--port","8080"]
