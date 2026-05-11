# Craft sandbox sidecar — HTTP server for file I/O, exec, snapshot triggers, and idle tracking.
# Runs as a separate container in the sandbox pod alongside the main sandbox container.

FROM python:3.11-slim

WORKDIR /app

# uv: deterministic, fast dependency installs from pyproject.toml + uv.lock.
RUN set -eux \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"

COPY pyproject.toml uv.lock README.md ./
COPY app ./app

RUN uv sync --frozen --no-dev

# Non-root UID/GID 1000 — matches the sandbox container's securityContext so shared
# volumes (workspace PVC) have consistent ownership.
RUN groupadd --gid 1000 sidecar \
    && useradd --uid 1000 --gid sidecar --create-home --home-dir /home/sidecar sidecar \
    && chown -R sidecar:sidecar /app

USER sidecar

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["sandbox-sidecar"]
