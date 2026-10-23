# Mock OpenAI-compatible LLM server for Onyx load testing.
# Build from the tools/loadtest/ directory:  docker build -f mock_llm/Dockerfile -t onyx-mock-llm .
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39

WORKDIR /app

# Keep pins in sync with the root pyproject.toml + uv.lock (reproducible builds).
RUN pip install --no-cache-dir fastapi==0.136.3 uvicorn==0.49.0 tiktoken==0.13.0 prometheus-client==0.23.1

ENV TIKTOKEN_CACHE_DIR=/app/tokenizer-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY ./mock_llm /app/mock_llm

EXPOSE 8000

CMD ["uvicorn", "mock_llm.app:app", "--host", "0.0.0.0", "--port", "8000"]
