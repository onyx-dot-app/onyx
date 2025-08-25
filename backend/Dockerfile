# syntax=docker/dockerfile:1.7

# ----------------------------
# Base runtime image (minimal)
# ----------------------------
FROM python:3.11.7-slim-bookworm AS base

LABEL com.danswer.maintainer="founders@onyx.app"
LABEL com.danswer.description="Optimized multi-stage Onyx backend container"

# Common envs for all stages
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install only runtime system dependencies
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        zip \
        postgresql-client \
        libgnutls30 \
        libblkid1 \
        libmount1 \
        libsmartcols1 \
        libuuid1 \
        libxmlsec1-openssl; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get clean

# ----------------------------
# Builder stage: deps + compilation
# ----------------------------
FROM base AS builder

# Default ONYX_VERSION, typically overridden during builds by CI
ARG ONYX_VERSION=0.0.0-dev
ENV ONYX_VERSION=${ONYX_VERSION}

# Install build dependencies
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        cmake \
        gcc \
        pkg-config \
        libxmlsec1-dev; \
    rm -rf /var/lib/apt/lists/*

# Create and use virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install Python dependencies with BuildKit cache
COPY requirements/default.txt requirements/ee.txt /tmp/
RUN --mount=type=cache,target=/root/.cache/pip \
    set -eux; \
    pip install --upgrade pip; \
    pip install --retries 5 --timeout 30 \
        -r /tmp/default.txt \
        -r /tmp/ee.txt; \
    pip uninstall -y py

# Install Playwright and browsers in builder
RUN set -eux; \
    playwright install chromium; \
    playwright install-deps chromium

# Pre-download models and NLTK data
RUN set -eux; \
    python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('nomic-ai/nomic-embed-text-v1')"; \
    python -c "import nltk; nltk.download('stopwords', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Create symlink for supervisord
RUN ln -s /venv/bin/supervisord /usr/bin/supervisord

# ----------------------------
# Final runtime image
# ----------------------------
FROM base AS runtime

# Default ONYX_VERSION, typically overridden during builds by CI
ARG ONYX_VERSION=0.0.0-dev
ENV ONYX_VERSION=${ONYX_VERSION} \
    DANSWER_RUNNING_IN_DOCKER="true" \
    DO_NOT_TRACK="true"

RUN echo "ONYX_VERSION: ${ONYX_VERSION}"

WORKDIR /app

# Create non-root user for security best practices
RUN groupadd -g 1001 onyx && \
    useradd -u 1001 -g onyx -m -s /bin/bash onyx && \
    chown -R onyx:onyx /app && \
    mkdir -p /var/log/onyx && \
    chmod 755 /var/log/onyx && \
    chown onyx:onyx /var/log/onyx && \
    chown -R onyx:onyx /home/onyx/

# Copy the virtual environment from builder
COPY --from=builder /venv /venv

# Copy Playwright browsers and dependencies to user directory
COPY --from=builder --chown=onyx:onyx /root/.cache /home/onyx/.cache
COPY --from=builder /usr/bin/supervisord /usr/bin/supervisord

# Set PATH to use venv and Playwright browsers path
ENV PATH="/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/home/onyx/.cache/ms-playwright

# Copy application files with proper ownership
COPY --chown=onyx:onyx ee /app/ee
COPY --chown=onyx:onyx onyx /app/onyx
COPY --chown=onyx:onyx shared_configs /app/shared_configs
COPY --chown=onyx:onyx alembic /app/alembic
COPY --chown=onyx:onyx alembic_tenants /app/alembic_tenants
COPY --chown=onyx:onyx alembic.ini /app/alembic.ini
COPY --chown=onyx:onyx static /app/static
COPY --chown=onyx:onyx assets /app/assets

# Copy scripts
COPY --chown=onyx:onyx scripts/debugging /app/scripts/debugging
COPY --chown=onyx:onyx scripts/force_delete_connector_by_id.py /app/scripts/force_delete_connector_by_id.py

# Copy supervisor configs
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY supervisord.conf /usr/etc/supervisord.conf

# Default command which does nothing
# This container is used by api server and background which specify their own CMD
CMD ["tail", "-f", "/dev/null"]
