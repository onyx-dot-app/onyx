# Locust harness image for running the chat load tests in-cluster.
# Build from the tools/loadtest/ directory:  docker build -t onyx-loadtest .
# Master/worker mode and run flags are supplied by the deployment (see k8s/).
ARG BASE_IMAGE_REGISTRY=docker.io
# Keep the tag in sync with the locust pin in uv.lock.
FROM ${BASE_IMAGE_REGISTRY}/locustio/locust:2.46.6

# The base image is built once per Locust release, so its OS packages trail
# Debian security.
USER root
RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean
USER locust

# prometheus-client isn't in the base image. The rest ship in it at vulnerable
# versions. Pins match the root lockfile's `loadtest` group, so bump them with it.
# uv is mounted for this step only, so it never reaches the shipped image.
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9,source=/uv,target=/bin/uv \
    uv pip install --python /opt/venv/bin/python --no-cache-dir \
    prometheus-client==0.23.1 \
    brotli==1.2.1 \
    certifi==2026.10.19 \
    msgpack==1.2.4 \
    werkzeug==3.1.9

COPY locustfile.py /loadtest/locustfile.py
COPY shapes.py /loadtest/shapes.py
COPY prometheus_exporter.py /loadtest/prometheus_exporter.py
COPY prometheus_collector.py /loadtest/prometheus_collector.py
COPY onyx_client /loadtest/onyx_client
COPY scenarios /loadtest/scenarios

# 8089 web UI, 5557 worker comms, 9646 Prometheus /metrics (master only).
EXPOSE 9646

ENTRYPOINT ["locust", "-f", "/loadtest/locustfile.py"]
