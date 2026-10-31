# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to the ECR
# pull-through cache (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker
# Hub rate limits.
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb

WORKDIR /app

RUN pip install --no-cache-dir "pydantic-core>=2.28.0" fastapi uvicorn

COPY ./main.py /app/main.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
