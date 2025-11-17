# syntax=docker/dockerfile:1.6
# This image is only for running integration tests. It layers test-specific
# files and dependencies on top of the backend image.
FROM base AS integration-base

WORKDIR /app

# Integration test stuff
COPY ./requirements/dev.txt /tmp/dev-requirements.txt
RUN uv pip install --system --no-cache-dir --upgrade -r /tmp/dev-requirements.txt && \
    rm -rf ~/.cache/uv /tmp/*.txt

COPY ./generated /app/generated
COPY ./pytest.ini /app/pytest.ini
COPY ./tests/integration /app/tests/integration
# copies all files, but not folders, in the tests directory
COPY ./tests/* /app/tests/

FROM integration-base AS openapi-schema
COPY ./scripts/onyx_openapi_schema.py /app/scripts/onyx_openapi_schema.py
RUN python scripts/onyx_openapi_schema.py --filename generated/openapi.json

FROM openapitools/openapi-generator-cli:latest AS openapi-client
WORKDIR /local
COPY --from=openapi-schema /app/generated/openapi.json /local/openapi.json
RUN openapi-generator-cli generate \
    -i /local/openapi.json \
    -g python \
    -o /local/onyx_openapi_client \
    --package-name onyx_openapi_client \
    --skip-validate-spec \
    --openapi-normalizer "SIMPLIFY_ONEOF_ANYOF=true,SET_OAS3_NULLABLE=true"

FROM integration-base AS integration
COPY --from=openapi-schema /app/generated/openapi.json /app/generated/openapi.json
COPY --from=openapi-client /local/onyx_openapi_client /app/generated/onyx_openapi_client


ENV PYTHONPATH=/app

ENTRYPOINT ["pytest", "-s"]
CMD ["/app/tests/integration", "--ignore=/app/tests/integration/multitenant_tests"]
