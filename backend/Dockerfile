FROM python:3.11.7-slim-bookworm

LABEL com.danswer.maintainer="founders@onyx.app"
LABEL com.danswer.description="This image is the web/frontend container of Onyx which \
contains code for both the Community and Enterprise editions of Onyx. If you do not \
have a contract or agreement with DanswerAI, you are not permitted to use the Enterprise \
Edition features outside of personal development or testing purposes. Please reach out to \
founders@onyx.app for more information. Please visit https://github.com/onyx-dot-app/onyx"

# Default ONYX_VERSION, typically overriden during builds by GitHub Actions.
ARG ONYX_VERSION=0.0.0-dev
# DO_NOT_TRACK is used to disable telemetry for Unstructured
ENV ONYX_VERSION=${ONYX_VERSION} \
    DANSWER_RUNNING_IN_DOCKER="true" \
    DO_NOT_TRACK="true" \
    PLAYWRIGHT_BROWSERS_PATH="/app/.cache/ms-playwright"


RUN echo "ONYX_VERSION: ${ONYX_VERSION}"
# Install system dependencies
# cmake needed for psycopg (postgres)
# libpq-dev needed for psycopg (postgres)
# curl included just for users' convenience
# zip for Vespa step futher down
# ca-certificates for HTTPS
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
        nano \
        vim && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean



# Install Python dependencies
# Remove py which is pulled in by retry, py is not needed and is a CVE
COPY ./requirements/default.txt /tmp/requirements.txt
COPY ./requirements/ee.txt /tmp/ee-requirements.txt
RUN pip install --no-cache-dir --upgrade \
        --retries 5 \
        --timeout 30 \
        -r /tmp/requirements.txt \
        -r /tmp/ee-requirements.txt && \
    pip uninstall -y py && \
    playwright install chromium && \
    playwright install-deps chromium && \
    ln -s /usr/local/bin/supervisord /usr/bin/supervisord

# Cleanup for CVEs and size reduction
# https://github.com/tornadoweb/tornado/issues/3107
# xserver-common and xvfb included by playwright installation but not needed after
# perl-base is part of the base Python Debian image but not needed for Onyx functionality
# perl-base could only be removed with --allow-remove-essential
RUN apt-get update && \
    apt-get remove -y --allow-remove-essential \
        perl-base \
        xserver-common \
        xvfb \
        cmake \
        libldap-2.5-0 \
        libxmlsec1-dev \
        pkg-config \
        gcc && \
    apt-get install -y libxmlsec1-openssl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* && \
    rm -f /usr/local/lib/python3.11/site-packages/tornado/test/test.key

# Install postgresql-client for easy manual tests
# Install it here to avoid it being cleaned up above
RUN apt-get update && apt-get install -y postgresql-client

# Pre-downloading models for setups with limited egress
RUN python -c "from tokenizers import Tokenizer; \
Tokenizer.from_pretrained('nomic-ai/nomic-embed-text-v1')"

# Pre-downloading NLTK for setups with limited egress
RUN python -c "import nltk; \
nltk.download('stopwords', quiet=True); \
nltk.download('punkt_tab', quiet=True);"
# nltk.download('wordnet', quiet=True); introduce this back if lemmatization is needed

# Set up application files
WORKDIR /app

# Create non-root user for security best practices
RUN groupadd -g 1001 onyx && \
    useradd -u 1001 -g onyx -m -s /bin/bash onyx && \
    mkdir -p /var/log/onyx && \
    chmod 755 /var/log/onyx && \
    chown onyx:onyx /var/log/onyx

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

# Escape hatch scripts
COPY --chown=onyx:onyx ./scripts/debugging /app/scripts/debugging
COPY --chown=onyx:onyx ./scripts/force_delete_connector_by_id.py /app/scripts/force_delete_connector_by_id.py
COPY --chown=onyx:onyx ./scripts/supervisord_entrypoint.sh /app/scripts/supervisord_entrypoint.sh
RUN chmod +x /app/scripts/supervisord_entrypoint.sh

# Put logo in assets
COPY --chown=onyx:onyx ./assets /app/assets

ENV PYTHONPATH=/app

# Default command which does nothing
# This container is used by api server and background which specify their own CMD
CMD ["tail", "-f", "/dev/null"]
