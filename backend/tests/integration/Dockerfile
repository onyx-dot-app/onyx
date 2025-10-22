# Dockerfile for integration tests
# Currently needs all dependencies, since the ITs use some of the Onyx
# backend code.
ARG BASE_IMAGE=onyxdotapp/onyx-backend:latest
FROM "${BASE_IMAGE}"

# TODO: This has been added to the base image. This helps with backwards compatibility.
# Once latest base image is released, this can be removed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Integration test stuff
COPY ./requirements/dev.txt /tmp/dev-requirements.txt
RUN uv pip install --system --no-cache-dir --upgrade \
        -r /tmp/dev-requirements.txt
COPY ./tests/integration /app/tests/integration
# copies all files, but not folders, in the tests directory
COPY ./tests/* /app/tests/

ENV PYTHONPATH=/app

ENTRYPOINT ["pytest", "-s"]
CMD ["/app/tests/integration", "--ignore=/app/tests/integration/multitenant_tests"]