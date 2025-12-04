"""
Test configuration for LLM tests.

This module loads model metadata enrichments before running tests
so that the model_name_parser has access to the enriched data.
"""

from collections.abc import Generator

import pytest

from onyx.llm.litellm_singleton.config import load_model_metadata_enrichments
from onyx.llm.model_name_parser import parse_litellm_model_name


@pytest.fixture(scope="session", autouse=True)
def load_enrichments() -> Generator[None, None, None]:
    """Load model metadata enrichments before any tests run."""
    load_model_metadata_enrichments()
    # Clear parser cache to ensure fresh lookups
    parse_litellm_model_name.cache_clear()
    yield
