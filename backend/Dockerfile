####################################################################################################
# Builder stage
#
# Installs the build toolchain and compiles/installs all Python dependencies. Only the resulting
# site-packages + console scripts are copied into the runtime stage; the build toolchain never
# reaches the shipped image.
####################################################################################################
# Registry prefix for base images. Defaults to Docker Hub; CI overrides this to the ECR
# pull-through cache (<account>.dkr.ecr.us-east-2.amazonaws.com/docker-hub) to avoid Docker
# Hub rate limits. Declared before the first FROM so it applies to every base image below.
ARG BASE_IMAGE_REGISTRY=docker.io
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:b04b5d7233d2ad9c379e22ea8927cd1378cd15c60d4ef876c065b25ea8fb3bf3 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/

# System dependencies for compiling the Python wheels.
# cmake/libxmlsec1-dev/pkg-config/gcc needed to compile native wheels (e.g. xmlsec)
# ca-certificates for HTTPS when fetching from PyPI
RUN apt-get update && \
    apt-get install -y \
        cmake \
        curl \
        zip \
        ca-certificates \
        libgnutls30 \
        libblkid1 \
        libmount1 \
        libsmartcols1 \
        libuuid1 \
        libxmlsec1-dev \
        pkg-config \
        gcc \
        && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# Install Python dependencies
COPY ./requirements/default.txt /tmp/requirements.txt
COPY ./requirements/ee.txt /tmp/ee-requirements.txt
# requirements/*.txt are a complete, pre-resolved lock export, so --no-deps installs them as-is
# without re-resolving. It is also required, not just an optimization: mitmproxy pins tight
# transitive caps (e.g. hyperframe<=6.0.1) that are only loosened by [tool.uv] override-dependencies
# in pyproject.toml, which is absent from this build context — a resolving install would fail.
RUN uv pip install --system --no-cache-dir --no-deps --require-hashes \
        -r /tmp/requirements.txt \
        -r /tmp/ee-requirements.txt && \
    # https://github.com/tornadoweb/tornado/issues/3107
    rm -f /usr/local/lib/python3.13/site-packages/tornado/test/test.key && \
    rm -rf ~/.cache/uv /tmp/*.txt


####################################################################################################
# psql builder stage
#
# postgresql-client pulls in perl (via postgresql-client-common). We want psql for manual DB
# debugging but not perl in the shipped image, so we install the client here only to extract the
# standalone psql binary; the runtime stage copies just that binary.
####################################################################################################
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:b04b5d7233d2ad9c379e22ea8927cd1378cd15c60d4ef876c065b25ea8fb3bf3 AS psql-builder

RUN apt-get update && \
    apt-get install -y postgresql-client && \
    # /usr/bin/psql is a perl wrapper; copy the real binary to a fixed path so the runtime COPY
    # doesn't depend on the postgres major-version directory.
    cp /usr/lib/postgresql/*/bin/psql /usr/local/bin/psql && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean


####################################################################################################
# Runtime stage
#
# The actual shipped image. Installs only runtime system libraries and copies the already-built
# Python packages from the builder stage.
####################################################################################################
FROM ${BASE_IMAGE_REGISTRY}/library/python:3.13-slim@sha256:b04b5d7233d2ad9c379e22ea8927cd1378cd15c60d4ef876c065b25ea8fb3bf3 AS runtime

LABEL com.danswer.maintainer="founders@onyx.app"
LABEL com.danswer.description="This image is the web/frontend container of Onyx which \
contains code for both the Community and Enterprise editions of Onyx. If you do not \
have a contract or agreement with DanswerAI, you are not permitted to use the Enterprise \
Edition features outside of personal development or testing purposes. Please reach out to \
founders@onyx.app for more information. Please visit https://github.com/onyx-dot-app/onyx"

# DO_NOT_TRACK is used to disable telemetry for Unstructured
ENV ONYX_RUNNING_IN_DOCKER="true" \
    DO_NOT_TRACK="true" \
    PLAYWRIGHT_BROWSERS_PATH="/app/.cache/ms-playwright"

# Create non-root user for security best practices
RUN groupadd -g 1001 onyx && \
    useradd -u 1001 -g onyx -m -s /bin/bash onyx && \
    mkdir -p /var/log/onyx && \
    chmod 755 /var/log/onyx && \
    chown onyx:onyx /var/log/onyx

# Install runtime system dependencies only (no build toolchain).
# curl included just for users' convenience
# zip for Vespa step further down
# ca-certificates for HTTPS
# libxmlsec1-openssl is the runtime counterpart to the build-time libxmlsec1-dev
# libpq5 + libreadline8 are the shared libraries for the standalone psql binary from the
#   psql-builder stage (avoids postgresql-client, which would pull in perl)
# procps so kubernetes exec sessions can use ps aux for debugging
RUN apt-get update && \
    apt-get install -y \
        curl \
        zip \
        ca-certificates \
        libgnutls30 \
        libblkid1 \
        libmount1 \
        libsmartcols1 \
        libuuid1 \
        libpq5 \
        libreadline8 \
        nano \
        vim \
        procps \
        libjemalloc2 \
        libxmlsec1-openssl \
        && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# Copy the compiled Python packages and only the console scripts our services launch (api server,
# celery workers/beat, alembic migrations, supervisord, Playwright). Both stages share the same base
# image digest, so paths and ABI match. Listing the scripts explicitly keeps the base interpreter
# binaries and any build-stage executables out of the shipped /usr/local/bin.
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder \
    /usr/local/bin/alembic \
    /usr/local/bin/celery \
    /usr/local/bin/uvicorn \
    /usr/local/bin/supervisord \
    /usr/local/bin/supervisorctl \
    /usr/local/bin/playwright \
    /usr/local/bin/

# psql for manual DB debugging — just the standalone binary, so postgresql-client's perl dependency
# never lands in the runtime image.
COPY --from=psql-builder /usr/local/bin/psql /usr/local/bin/psql

# Install the Chromium browser for Playwright and its OS-level runtime libs. Must run after the
# site-packages copy so the playwright CLI is available.
#
# perl-base ships in the base image but Onyx doesn't need it, so we remove it for CVE reduction
# (--allow-remove-essential), which cascades out the whole perl stack. Ordering matters: remove perl
# AFTER the first install-deps (the font/X11 packages run perl in their postinst), then run
# install-deps again to restore chromium libs (libnss3, etc.) that autoremove swept up. Nothing
# reinstalls perl afterwards — psql comes from the psql-builder stage as a standalone binary.
#
# The trailing commands verify the result in this same layer: psql runs (which proves its shared
# libraries resolve) and perl is gone. ldd is logged only as a diagnostic.
RUN ln -s /usr/local/bin/supervisord /usr/bin/supervisord && \
    playwright install chromium && \
    playwright install-deps chromium && \
    apt-get remove -y --allow-remove-essential perl-base && \
    apt-get autoremove -y && \
    playwright install-deps chromium && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean && \
    ldd "$(command -v psql)" && \
    psql --version && \
    ! command -v perl && \
    ! test -e /usr/bin/perl

# Pre-downloading models for setups with limited egress
RUN python -c "from tokenizers import Tokenizer; \
Tokenizer.from_pretrained('nomic-ai/nomic-embed-text-v1')"

# Pre-downloading NLTK for setups with limited egress
RUN python -c "import nltk; \
    nltk.download('stopwords', quiet=True); \
    nltk.download('punkt_tab', quiet=True);"
# nltk.download('wordnet', quiet=True); introduce this back if lemmatization is needed

# Pre-downloading tiktoken for setups with limited egress
RUN python -c "import tiktoken; \
tiktoken.get_encoding('cl100k_base')"

# Set up application files
WORKDIR /app

# Enterprise Version Files
COPY --chown=onyx:onyx ./ee /app/ee
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Set up application files
COPY --chown=onyx:onyx ./onyx /app/onyx
COPY --chown=onyx:onyx ./shared_configs /app/shared_configs
COPY --chown=onyx:onyx ./alembic /app/alembic
COPY --chown=onyx:onyx ./alembic_tenants /app/alembic_tenants
COPY --chown=onyx:onyx ./alembic.ini /app/alembic.ini
COPY supervisord.conf /usr/etc/supervisord.conf
COPY --chown=onyx:onyx ./static /app/static
COPY --chown=onyx:onyx ./keys /app/keys

# Escape hatch scripts
COPY --chown=onyx:onyx ./scripts/debugging /app/scripts/debugging
COPY --chown=onyx:onyx ./scripts/force_delete_connector_by_id.py /app/scripts/force_delete_connector_by_id.py
COPY --chown=onyx:onyx ./scripts/supervisord_entrypoint.sh /app/scripts/supervisord_entrypoint.sh
COPY --chown=onyx:onyx ./scripts/reencrypt_secrets.py /app/scripts/reencrypt_secrets.py
COPY --chown=onyx:onyx ./scripts/rotate_llm_provider_keys.py /app/scripts/rotate_llm_provider_keys.py
COPY --chown=onyx:onyx ./scripts/seed_dev_license.py /app/scripts/seed_dev_license.py
RUN chmod +x /app/scripts/supervisord_entrypoint.sh

# Put logo in assets
COPY --chown=onyx:onyx ./assets /app/assets

ENV PYTHONPATH=/app

# Default ONYX_VERSION, typically overriden during builds by GitHub Actions.
ARG ONYX_VERSION=0.0.0-dev
ENV ONYX_VERSION=${ONYX_VERSION}

# Use jemalloc instead of glibc malloc to reduce memory fragmentation
# in long-running Python processes (API server, Celery workers).
# The soname is architecture-independent; the dynamic linker resolves
# the correct path from standard library directories.
# Placed after all RUN steps so build-time processes are unaffected.
ENV LD_PRELOAD=libjemalloc.so.2

# Default command which does nothing
# This container is used by api server and background which specify their own CMD
CMD ["tail", "-f", "/dev/null"]
