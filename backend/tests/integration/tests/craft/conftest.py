"""Shared fixtures for build-mode integration tests.

Tests in this directory hit the running Onyx API server (build router) against
real Postgres / Redis / file store. The integration CI workflow sets
``ENABLE_CRAFT=true`` so the Craft endpoints are available.
"""

from __future__ import annotations

import pytest

from tests.integration.common_utils.test_models import DATestLLMProvider


@pytest.fixture(autouse=True)
def _reset_db(reset: None) -> None:  # noqa: ARG001
    """Auto-reset DB before each build test."""


@pytest.fixture(autouse=True)
def _ensure_llm_provider(llm_provider: DATestLLMProvider) -> None:  # noqa: ARG001
    """Seed a default LLM provider after each DB reset."""
