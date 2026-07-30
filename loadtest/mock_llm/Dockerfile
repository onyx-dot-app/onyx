# Mock OpenAI-compatible LLM server for Onyx load testing.
# Build from the loadtest/ directory:  docker build -f mock_llm/Dockerfile -t onyx-mock-llm .
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:b04b5d7233d2ad9c379e22ea8927cd1378cd15c60d4ef876c065b25ea8fb3bf3

WORKDIR /app

# Keep pins in sync with ../pyproject.toml + uv.lock (reproducible builds).
RUN pip install --no-cache-dir fastapi==0.136.3 uvicorn==0.49.0

COPY ./mock_llm /app/mock_llm

EXPOSE 8000

CMD ["uvicorn", "mock_llm.app:app", "--host", "0.0.0.0", "--port", "8000"]
