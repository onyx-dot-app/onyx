# Locust harness image for running the chat load tests in-cluster.
# Build from the loadtest/ directory:  docker build -t onyx-loadtest .
# Master/worker mode and run flags are supplied by the deployment (see k8s/).
ARG BASE_IMAGE_REGISTRY=docker.io
# Keep the tag in sync with the locust pin in uv.lock.
FROM ${BASE_IMAGE_REGISTRY}/locustio/locust:2.44.1

# prometheus-client isn't in the base locust image. Pinned to match the
# resolved version in uv.lock — bump both together when the lockfile updates.
RUN pip install --no-cache-dir prometheus-client==0.25.0

COPY locustfile.py /loadtest/locustfile.py
COPY shapes.py /loadtest/shapes.py
COPY prometheus_exporter.py /loadtest/prometheus_exporter.py
COPY prometheus_collector.py /loadtest/prometheus_collector.py
COPY onyx_client /loadtest/onyx_client
COPY scenarios /loadtest/scenarios

# 8089 web UI, 5557 worker comms, 9646 Prometheus /metrics (master only).
EXPOSE 9646

ENTRYPOINT ["locust", "-f", "/loadtest/locustfile.py"]
