FROM python:3.11.7-slim-bookworm

LABEL com.danswer.maintainer="founders@onyx.app"
LABEL com.danswer.description="This image is the web/frontend container of Onyx which \
contains code for both the Community and Enterprise editions of Onyx. If you do not \
have a contract or agreement with DanswerAI, you are not permitted to use the Enterprise \
Edition features outside of personal development or testing purposes. Please reach out to \
founders@onyx.app for more information. Please visit https://github.com/onyx-dot-app/onyx"

# Default ONYX_VERSION, typically overridden during builds by GitHub Actions.
ARG ONYX_VERSION=0.0.0-dev

# DO_NOT_TRACK is used to disable telemetry for Unstructured
# TREE_SITTER_SO tells our embedding.py where to find the compiled grammars
ENV ONYX_VERSION=${ONYX_VERSION} \
    DANSWER_RUNNING_IN_DOCKER="true" \
    DO_NOT_TRACK="true" \
    TREE_SITTER_SO="/usr/local/lib/my-languages.so"

RUN echo "ONYX_VERSION: ${ONYX_VERSION}"

# 1) Install system dependencies (including build-essential, make, git, etc.)
#    These are needed for pip installs that compile C extensions AND for tree-sitter bundle build.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
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
        g++ \
        make \
        nano \
        vim && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# 2) Install Python dependencies
#    - default.txt and ee.txt should list everything EXCEPT tree_sitter (if it's the wrong one)
COPY ./requirements/default.txt /tmp/requirements.txt
COPY ./requirements/ee.txt /tmp/ee-requirements.txt

RUN pip install --no-cache-dir --upgrade \
        --retries 5 \
        --timeout 30 \
        -r /tmp/requirements.txt \
        -r /tmp/ee-requirements.txt && \
    # If requirements installed 'tree-sitter' (hyphen) by mistake, uninstall it:
    pip uninstall -y tree-sitter || true && \
    # Also uninstall 'tree_sitter' (underscore) just in case it was present from requirements
    pip uninstall -y tree_sitter || true && \
    # Now install the correct Tree-sitter binding, pinned to a specific version:
    # Using 0.21.0 as an example. Adjust if your code needs a different one.
    pip install --no-cache-dir --upgrade tree_sitter==0.21.0 && \
    # Uninstall 'py' (pulled in by retry) because of a known CVE
    pip uninstall -y py && \
    # Install Playwright and its dependencies
    playwright install chromium && \
    playwright install-deps chromium && \
    ln -s /usr/local/bin/supervisord /usr/bin/supervisord


# 3) Pre-download certain ML models/resources for offline use
RUN python -c "from tokenizers import Tokenizer; \
Tokenizer.from_pretrained('nomic-ai/nomic-embed-text-v1')" && \
    python -c "import nltk; \
nltk.download('stopwords', quiet=True); \
nltk.download('punkt_tab', quiet=True);"

# 4) Set up application files
WORKDIR /app

# Enterprise Edition files
COPY ./ee /app/ee
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy Onyx source (including our new connector)
COPY ./onyx /app/onyx
COPY ./shared_configs /app/shared_configs
COPY ./alembic /app/alembic
COPY ./alembic_tenants /app/alembic_tenants
COPY ./alembic.ini /app/alembic.ini
COPY supervisord.conf /usr/etc/supervisord.conf
COPY ./static /app/static

# Escape‐hatch scripts
COPY ./scripts/debugging /app/scripts/debugging
COPY ./scripts/force_delete_connector_by_id.py /app/scripts/force_delete_connector_by_id.py

# Static assets
COPY ./assets /app/assets

# Ensure Python can import /app modules
ENV PYTHONPATH=/app

# 5) DIAGNOSTICS: Check tree-sitter installation before attempting to build the bundle
RUN echo "--- Diagnosing tree_sitter ---" && \
    echo "import tree_sitter;\n\
print(f'TS loaded from: {tree_sitter.__file__}');\n\
print(f'TS object: {tree_sitter}');\n\
has_version = hasattr(tree_sitter, '__version__');\n\
print(f'TS has __version__: {has_version}');\n\
if has_version: print(f'TS version: {tree_sitter.__version__}');\n\
has_lang = hasattr(tree_sitter, 'Language');\n\
print(f'TS has Language: {has_lang}');\n\
if has_lang:\n\
    print(f'TS Language obj: {tree_sitter.Language}');\n\
    print(f'TS Language.build_library exists: {hasattr(tree_sitter.Language, \"build_library\")}');\n\
else:\n\
    print('TS Language obj: Not found');\n\
    print('TS Language.build_library exists: N/A')" | python && \
    echo "--- End diagnosing tree_sitter ---"

# 6) Build the Tree-sitter shared library
#    Expects onyx/vendor/tree-sitter-grammars to exist with:
#      tree-sitter-javascript
#      tree-sitter-typescript (with a nested 'typescript' folder)
#      tree-sitter-ruby
#      tree-sitter-c-sharp
#    Build tools (gcc, make) MUST be present here.
RUN python /app/onyx/connectors/github_code/build_treesitter_bundle.py

# 7) Cleanup unneeded packages to reduce image size and avoid CVEs
RUN apt-get update && \
    apt-get remove -y --allow-remove-essential \
        perl-base \
        xserver-common \
        xvfb \
        cmake \
        libxmlsec1-dev \
        pkg-config \
        gcc \
        g++ \
        make && \
    apt-get install -y --no-install-recommends libxmlsec1-openssl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* && \
    rm -f /usr/local/lib/python3.11/site-packages/tornado/test/test.key

# 8) Default command
CMD ["tail", "-f", "/dev/null"]