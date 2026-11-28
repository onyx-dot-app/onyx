# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to the ECR
# pull-through cache (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker
# Hub rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic cryptography python-docx python-pptx

COPY ./mock_gdrive /app/mock_gdrive

CMD ["uvicorn", "mock_gdrive.app:app", "--host", "0.0.0.0", "--port", "9650", "--timeout-keep-alive", "120"]
