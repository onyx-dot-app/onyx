FROM python:3.11.7-slim-bookworm
# Dockerfile for integration tests
# Currently needs all dependencies, since the ITs use some of the Onyx
# backend code.

# Needed for playwright to work
ENV PLAYWRIGHT_BROWSERS_PATH="/app/.cache/ms-playwright"

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

# Set up application files
WORKDIR /app

# Enterprise Version Files
COPY ./ee /app/ee
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Set up application files
COPY ./onyx /app/onyx
COPY ./generated /app/generated
COPY ./shared_configs /app/shared_configs
COPY ./alembic_tenants /app/alembic_tenants
COPY ./alembic /app/alembic
COPY ./alembic.ini /app/alembic.ini
COPY ./pytest.ini /app/pytest.ini
COPY supervisord.conf /usr/etc/supervisord.conf

# Integration test stuff
COPY ./requirements/dev.txt /tmp/dev-requirements.txt
RUN pip install --no-cache-dir --upgrade \
        -r /tmp/dev-requirements.txt
COPY ./tests/integration /app/tests/integration
# copies all files, but not folders, in the tests directory
COPY ./tests/* /app/tests/

ENV PYTHONPATH=/app

ENTRYPOINT ["pytest", "-s"]
CMD ["/app/tests/integration", "--ignore=/app/tests/integration/multitenant_tests"]