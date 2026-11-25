from collections.abc import Iterator
from unittest.mock import patch

import pytest

from onyx.natural_language_processing.embedding_providers.vertex_credentials import (
    VERTEX_CREDENTIALS,
)
from onyx.natural_language_processing.embedding_providers.vertex_scheduler import (
    VertexRequestScheduler,
)


@pytest.fixture(autouse=True)
def _fresh_vertex_credentials() -> Iterator[None]:
    VERTEX_CREDENTIALS.clear()
    yield
    VERTEX_CREDENTIALS.clear()


@pytest.fixture(autouse=True)
def vertex_scheduler() -> Iterator[VertexRequestScheduler]:
    scheduler = VertexRequestScheduler(max_concurrency=128, initial_concurrency=16)
    with patch(
        "onyx.natural_language_processing.embedding_providers.vertex.VERTEX_SCHEDULER",
        scheduler,
    ):
        yield scheduler
