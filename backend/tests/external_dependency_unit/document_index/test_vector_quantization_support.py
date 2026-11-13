"""External dependency tests for the vector quantization support endpoint and the
reindex validator, which share one OpenSearch version rule."""

from typing import cast
from unittest.mock import patch

import pytest

from onyx.db.enums import VectorQuantization
from onyx.db.models import User
from onyx.document_index.opensearch.client import (
    OpenSearchClient,
    wait_for_opensearch_with_timeout,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.models import VectorQuantizationSupport
from onyx.server.manage.search_settings import (
    _validate_vector_quantization_supported,
    get_vector_quantization_support,
)


def _support() -> VectorQuantizationSupport:
    return get_vector_quantization_support(cast(User, None))


def _supported_levels(support: VectorQuantizationSupport) -> dict[str, bool]:
    return {
        level.vector_quantization.value: level.supported for level in support.levels
    }


def test_live_cluster_reports_its_version_and_supports_every_level() -> None:
    """The local test cluster runs OpenSearch 3.6, so every level is supported."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    support: VectorQuantizationSupport = _support()

    assert support.opensearch_version is not None
    assert _supported_levels(support) == {
        "none": True,
        "scalar_7_bit": True,
        "scalar_1_bit": True,
    }
    min_versions: dict[str, str | None] = {
        level.vector_quantization.value: level.min_opensearch_version
        for level in support.levels
    }
    assert min_versions == {"none": None, "scalar_7_bit": "2.16", "scalar_1_bit": "3.6"}


def test_older_cluster_disables_only_the_levels_it_cannot_index() -> None:
    """OpenSearch 3.3 indexes 7-bit but not 1-bit, and the validator agrees."""
    with patch.object(OpenSearchClient, "get_opensearch_version", return_value=(3, 3)):
        support: VectorQuantizationSupport = _support()
        assert support.opensearch_version == "3.3"
        assert _supported_levels(support) == {
            "none": True,
            "scalar_7_bit": True,
            "scalar_1_bit": False,
        }
        _validate_vector_quantization_supported(VectorQuantization.SCALAR_7_BIT)
        with pytest.raises(OnyxError, match="needs OpenSearch 3.6 or later"):
            _validate_vector_quantization_supported(VectorQuantization.SCALAR_1_BIT)


def test_cluster_without_a_version_restricts_nothing() -> None:
    """A cluster that does not report its version is not restricted."""
    with patch.object(OpenSearchClient, "get_opensearch_version", return_value=None):
        support: VectorQuantizationSupport = _support()
        assert support.opensearch_version is None
        assert all(_supported_levels(support).values())
        _validate_vector_quantization_supported(VectorQuantization.SCALAR_1_BIT)
