# Locust harness image for running the chat load tests in-cluster.
# Build from the loadtest/ directory:  docker build -t onyx-loadtest .
# Master/worker mode and run flags are supplied by the deployment (see k8s/).
ARG BASE_IMAGE_REGISTRY=docker.io
# Keep the tag in sync with the locust pin in uv.lock.
FROM ${BASE_IMAGE_REGISTRY}/locustio/locust:2.44.1

COPY locustfile.py /loadtest/locustfile.py
COPY shapes.py /loadtest/shapes.py
COPY onyx_client /loadtest/onyx_client
COPY scenarios /loadtest/scenarios

ENTRYPOINT ["locust", "-f", "/loadtest/locustfile.py"]
