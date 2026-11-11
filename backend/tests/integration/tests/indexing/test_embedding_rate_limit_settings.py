"""Admins set the global rate limit on indexing embedding requests."""

from collections.abc import Iterator

import pytest

from onyx.configs.app_configs import (
    DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
    MAX_EMBEDDING_RATE_LIMIT_REQUESTS,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_SETTINGS_URL = f"{API_SERVER_URL}/admin/settings"
_READ_SETTINGS_URL = f"{API_SERVER_URL}/settings"


@pytest.fixture
def restore_rate_limit(admin_user: DATestUser) -> Iterator[None]:
    yield
    client.patch(
        _SETTINGS_URL,
        json={
            "embedding_rate_limit_requests": None,
            "embedding_rate_limit_period_seconds": DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
        },
        headers=admin_user.headers,
    ).raise_for_status()


def _read_rate_limit(admin_user: DATestUser) -> tuple[int | None, int]:
    settings = client.get(_READ_SETTINGS_URL, headers=admin_user.headers).json()
    return (
        settings["embedding_rate_limit_requests"],
        settings["embedding_rate_limit_period_seconds"],
    )


@pytest.mark.usefixtures("restore_rate_limit")
def test_admin_sets_and_clears_the_rate_limit(admin_user: DATestUser) -> None:
    assert _read_rate_limit(admin_user) == (
        None,
        DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
    )

    client.patch(
        _SETTINGS_URL,
        json={
            "embedding_rate_limit_requests": 600,
            "embedding_rate_limit_period_seconds": 60,
        },
        headers=admin_user.headers,
    ).raise_for_status()
    assert _read_rate_limit(admin_user) == (600, 60)

    client.patch(
        _SETTINGS_URL,
        json={"embedding_rate_limit_requests": None},
        headers=admin_user.headers,
    ).raise_for_status()
    assert _read_rate_limit(admin_user) == (None, 60)


@pytest.mark.usefixtures("restore_rate_limit")
@pytest.mark.parametrize(
    "rate_limit",
    [
        {"embedding_rate_limit_requests": 0},
        {"embedding_rate_limit_requests": MAX_EMBEDDING_RATE_LIMIT_REQUESTS + 1},
        {"embedding_rate_limit_period_seconds": 0},
    ],
)
def test_invalid_rate_limit_is_rejected(
    admin_user: DATestUser, rate_limit: dict[str, int]
) -> None:
    response = client.patch(_SETTINGS_URL, json=rate_limit, headers=admin_user.headers)
    assert response.status_code in (400, 422)
    assert _read_rate_limit(admin_user) == (
        None,
        DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
    )
