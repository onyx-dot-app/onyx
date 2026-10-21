# Mock OpenAI-compatible LLM server for Onyx load testing.
# Build from the tools/loadtest/ directory:  docker build -f mock_llm/Dockerfile -t onyx-mock-llm .
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

WORKDIR /app

# Keep pins in sync with the root pyproject.toml + uv.lock (reproducible builds).
RUN pip install --no-cache-dir fastapi==0.136.3 uvicorn==0.49.0

COPY ./mock_llm /app/mock_llm

EXPOSE 8000

CMD ["uvicorn", "mock_llm.app:app", "--host", "0.0.0.0", "--port", "8000"]
