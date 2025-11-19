# syntax=docker/dockerfile:1.6
# This image is only for running integration tests. It layers test-specific
# files and dependencies on top of the backend image.
FROM base

WORKDIR /app

# TODO: This has been added to the base image but kept here for backwards compatibility.
# Once the latest backend image is released, this can be removed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Integration test stuff
COPY ./requirements/dev.txt /tmp/dev-requirements.txt
RUN uv pip install --system --no-cache-dir --upgrade -r /tmp/dev-requirements.txt && \
    rm -rf ~/.cache/uv /tmp/*.txt

COPY ./generated /app/generated
COPY ./pytest.ini /app/pytest.ini
COPY ./tests/integration /app/tests/integration
# copies all files, but not folders, in the tests directory
COPY ./tests/* /app/tests/


ENV PYTHONPATH=/app

ENTRYPOINT ["pytest", "-s"]
CMD ["/app/tests/integration", "--ignore=/app/tests/integration/multitenant_tests"]