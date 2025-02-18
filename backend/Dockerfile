FROM python:3.11.7-slim-bookworm

LABEL com.danswer.maintainer="founders@onyx.app"
LABEL com.danswer.description="This image is the web/frontend container of Onyx which \
contains code for both the Community and Enterprise editions of Onyx. If you do not \
have a contract or agreement with DanswerAI, you are not permitted to use the Enterprise \
Edition features outside of personal development or testing purposes. Please reach out to \
founders@onyx.app for more information. Please visit https://github.com/onyx-dot-app/onyx"

# Default ONYX_VERSION, typically overriden during builds by GitHub Actions.
ARG ONYX_VERSION=0.8-dev
# DO_NOT_TRACK is used to disable telemetry for Unstructured
ENV ONYX_VERSION=${ONYX_VERSION} \
    DANSWER_RUNNING_IN_DOCKER="true" \
    DO_NOT_TRACK="true"


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


# Pre-downloading models for setups with limited egress
RUN python -c "from tokenizers import Tokenizer; \
Tokenizer.from_pretrained('nomic-ai/nomic-embed-text-v1')"

# Pre-downloading NLTK for setups with limited egress
RUN python -c "import nltk; \
nltk.download('stopwords', quiet=True); \
nltk.download('punkt', quiet=True);"
# nltk.download('wordnet', quiet=True); introduce this back if lemmatization is needed

# Set up application files
WORKDIR /app

# Enterprise Version Files
COPY ./ee /app/ee
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Set up application files
COPY ./onyx /app/onyx
COPY ./shared_configs /app/shared_configs
COPY ./alembic /app/alembic
COPY ./alembic_tenants /app/alembic_tenants
COPY ./alembic.ini /app/alembic.ini
COPY supervisord.conf /usr/etc/supervisord.conf

# Escape hatch scripts
COPY ./scripts/debugging /app/scripts/debugging
COPY ./scripts/force_delete_connector_by_id.py /app/scripts/force_delete_connector_by_id.py

# Put logo in assets
COPY ./assets /app/assets

ENV PYTHONPATH=/app

# Default command which does nothing
# This container is used by api server and background which specify their own CMD
CMD ["tail", "-f", "/dev/null"]
