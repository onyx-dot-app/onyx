"""Tests for `setup_document_index`, the startup check that the document index
exists and matches the expected schema."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.document_index.opensearch.client import OpenSearchIndexWriteBlockedError
from onyx.setup import setup_document_index


@pytest.fixture(autouse=True)
def _no_sleep() -> Iterator[MagicMock]:
    with patch("onyx.setup.time.sleep") as sleep:
        yield sleep


def _index_setting(embedding_dim: int = 768) -> MagicMock:
    index_setting = MagicMock()
    index_setting.final_embedding_dim = embedding_dim
    return index_setting


def test_success_on_first_attempt() -> None:
    document_index = MagicMock()

    assert setup_document_index(document_index, _index_setting(768), num_attempts=3)

    document_index.verify_and_create_index_if_necessary.assert_called_once_with(
        embedding_dim=768
    )


def test_retries_until_the_index_is_ready(_no_sleep: MagicMock) -> None:
    document_index = MagicMock()
    document_index.verify_and_create_index_if_necessary.side_effect = [
        ConnectionError("not ready"),
        ConnectionError("not ready"),
        None,
    ]

    assert setup_document_index(document_index, _index_setting(), num_attempts=5)

    assert document_index.verify_and_create_index_if_necessary.call_count == 3
    assert _no_sleep.call_count == 2


def test_gives_up_after_the_attempt_limit() -> None:
    document_index = MagicMock()
    document_index.verify_and_create_index_if_necessary.side_effect = ConnectionError(
        "down"
    )

    assert not setup_document_index(document_index, _index_setting(), num_attempts=3)

    assert document_index.verify_and_create_index_if_necessary.call_count == 3


def test_write_blocked_index_starts_degraded() -> None:
    """A readable but write-blocked index must not stop startup."""
    document_index = MagicMock()
    document_index.verify_and_create_index_if_necessary.side_effect = (
        OpenSearchIndexWriteBlockedError("read_only_allow_delete")
    )

    assert setup_document_index(document_index, _index_setting(), num_attempts=3)

    document_index.verify_and_create_index_if_necessary.assert_called_once()
