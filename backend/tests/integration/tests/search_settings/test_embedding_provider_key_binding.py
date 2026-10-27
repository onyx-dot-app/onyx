from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

EMBEDDING_URL = f"{API_SERVER_URL}/admin/embedding"
PROVIDER_TYPE = "litellm"
STORED_KEY = "sk-stored-embedding-key"
STORED_URL = "https://proxy.example.com/v1/embeddings"
OTHER_URL = "https://attacker.example.com/v1/embeddings"


def _put_provider(user: DATestUser, **fields: Any) -> httpx.Response:
    return client.put(
        f"{EMBEDDING_URL}/embedding-provider",
        json={"provider_type": PROVIDER_TYPE, **fields},
        headers=user.headers,
    )


def _get_provider(user: DATestUser) -> dict[str, Any]:
    response = client.get(
        f"{EMBEDDING_URL}/embedding-provider/{PROVIDER_TYPE}", headers=user.headers
    )
    response.raise_for_status()
    return response.json()


@pytest.fixture
def stored_provider(admin_user: DATestUser) -> Iterator[DATestUser]:
    response = _put_provider(
        admin_user, api_key=STORED_KEY, api_key_changed=True, api_url=STORED_URL
    )
    response.raise_for_status()
    yield admin_user
    client.delete(
        f"{EMBEDDING_URL}/embedding-provider/{PROVIDER_TYPE}",
        headers=admin_user.headers,
    )


def test_stored_key_is_not_sent_to_a_new_url(stored_provider: DATestUser) -> None:
    user = stored_provider
    masked_key: str = _get_provider(user)["api_key"]
    assert masked_key != STORED_KEY

    # The admin UI leaves an untouched key out of the request.
    kept_key = _put_provider(user, api_key_changed=False, api_url=OTHER_URL)
    assert kept_key.status_code == 400
    assert "Enter the API key again" in kept_key.json()["detail"]

    # Older callers echo the masked key back.
    echoed_mask = _put_provider(user, api_key=masked_key, api_url=OTHER_URL)
    assert echoed_mask.status_code == 400

    # The credential test fills in the stored key, so it must refuse a new URL
    # before it sends any request.
    probe = client.post(
        f"{EMBEDDING_URL}/test-embedding",
        json={
            "provider_type": PROVIDER_TYPE,
            "api_url": OTHER_URL,
            "model_name": "text-embedding-3-small",
        },
        headers=user.headers,
    )
    assert probe.status_code == 400
    assert "Enter the API key again" in probe.json()["detail"]

    assert _get_provider(user)["api_url"] == STORED_URL


def test_url_changes_with_the_key_or_edits_without_a_new_url_still_save(
    stored_provider: DATestUser,
) -> None:
    user = stored_provider

    same_url = _put_provider(user, api_key_changed=False, api_url=f"{STORED_URL}/")
    assert same_url.status_code == 200

    with_key = _put_provider(
        user, api_key=STORED_KEY, api_key_changed=True, api_url=OTHER_URL
    )
    assert with_key.status_code == 200
    assert _get_provider(user)["api_url"] == OTHER_URL
