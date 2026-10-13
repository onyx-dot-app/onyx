"""Admins set the backoff between retries of indexing embedding calls."""

from collections.abc import Iterator

import pytest

from onyx.configs.app_configs import (
    DEFAULT_EMBEDDING_RETRY_BACKOFF_MAX_SECONDS,
    DEFAULT_EMBEDDING_RETRY_BACKOFF_SCALE_SECONDS,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_SETTINGS_URL = f"{API_SERVER_URL}/admin/settings"
_READ_SETTINGS_URL = f"{API_SERVER_URL}/settings"


@pytest.fixture
def restore_backoff(admin_user: DATestUser) -> Iterator[None]:
    yield
    client.patch(
        _SETTINGS_URL,
        json={
            "embedding_retry_backoff_scale_seconds": DEFAULT_EMBEDDING_RETRY_BACKOFF_SCALE_SECONDS,
            "embedding_retry_backoff_max_seconds": DEFAULT_EMBEDDING_RETRY_BACKOFF_MAX_SECONDS,
        },
        headers=admin_user.headers,
    ).raise_for_status()


@pytest.mark.usefixtures("restore_backoff")
def test_admin_sets_embedding_retry_backoff(admin_user: DATestUser) -> None:
    response = client.patch(
        _SETTINGS_URL,
        json={
            "embedding_retry_backoff_scale_seconds": 2.5,
            "embedding_retry_backoff_max_seconds": 120,
        },
        headers=admin_user.headers,
    )
    response.raise_for_status()

    settings = client.get(_READ_SETTINGS_URL, headers=admin_user.headers).json()
    assert settings["embedding_retry_backoff_scale_seconds"] == 2.5
    assert settings["embedding_retry_backoff_max_seconds"] == 120


@pytest.mark.usefixtures("restore_backoff")
@pytest.mark.parametrize(
    "backoff",
    [
        # The cap is below the first wait.
        {
            "embedding_retry_backoff_scale_seconds": 30,
            "embedding_retry_backoff_max_seconds": 10,
        },
        {"embedding_retry_backoff_scale_seconds": 0},
        {"embedding_retry_backoff_max_seconds": 100_000},
    ],
)
def test_invalid_embedding_retry_backoff_is_rejected(
    admin_user: DATestUser, backoff: dict[str, float]
) -> None:
    response = client.patch(_SETTINGS_URL, json=backoff, headers=admin_user.headers)
    assert response.status_code in (400, 422)

    settings = client.get(_READ_SETTINGS_URL, headers=admin_user.headers).json()
    assert (
        settings["embedding_retry_backoff_scale_seconds"]
        == DEFAULT_EMBEDDING_RETRY_BACKOFF_SCALE_SECONDS
    )
    assert (
        settings["embedding_retry_backoff_max_seconds"]
        == DEFAULT_EMBEDDING_RETRY_BACKOFF_MAX_SECONDS
    )
