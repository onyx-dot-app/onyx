from collections.abc import Iterator

import pytest

from onyx.natural_language_processing.embedding_providers.vertex_credentials import (
    VERTEX_CREDENTIALS,
)


@pytest.fixture(autouse=True)
def _fresh_vertex_credentials() -> Iterator[None]:
    VERTEX_CREDENTIALS.clear()
    yield
    VERTEX_CREDENTIALS.clear()
