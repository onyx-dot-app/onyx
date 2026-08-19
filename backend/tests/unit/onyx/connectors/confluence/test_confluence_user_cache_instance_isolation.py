"""Regression coverage for instance isolation of the Confluence user-resolution
caches. Confluence Server/DC usernames and userKeys are unique only within one
instance, so the username->email, userKey->email, and userid->display-name caches
must key on the instance base url. Otherwise one instance's user can resolve to
another instance's email (an ACL-affecting leak) when several Confluence connectors
run in the same multi-tenant worker process."""

from unittest.mock import MagicMock

import onyx.connectors.confluence.onyx_confluence as onyx_confluence


def _client(url: str) -> MagicMock:
    client = MagicMock()
    client._url = url
    return client


def test_username_email_cache_is_instance_isolated() -> None:
    onyx_confluence._USER_EMAIL_CACHE.clear()
    username = "jsmith"
    client_a = _client("https://a.example.com")
    client_a.get_mobile_parameters.return_value = {"email": "a@example.com"}
    client_b = _client("https://b.example.com")
    client_b.get_mobile_parameters.return_value = {"email": "b@example.com"}

    assert (
        onyx_confluence.get_user_email_from_username__server(client_a, username)
        == "a@example.com"
    )
    # repeat call for the same instance is served from cache
    assert (
        onyx_confluence.get_user_email_from_username__server(client_a, username)
        == "a@example.com"
    )
    assert client_a.get_mobile_parameters.call_count == 1

    # same username on a different instance must not see instance A's email
    assert (
        onyx_confluence.get_user_email_from_username__server(client_b, username)
        == "b@example.com"
    )
    assert client_b.get_mobile_parameters.call_count == 1


def test_userkey_email_cache_is_instance_isolated() -> None:
    onyx_confluence._USER_KEY_TO_EMAIL_CACHE.clear()
    user_key = "ff8080816f"
    client_a = _client("https://a.example.com")
    client_a.get_user_details_by_userkey.return_value = {"email": "a@example.com"}
    client_b = _client("https://b.example.com")
    client_b.get_user_details_by_userkey.return_value = {"email": "b@example.com"}

    assert (
        onyx_confluence.get_user_email_from_userkey__server(client_a, user_key)
        == "a@example.com"
    )
    assert (
        onyx_confluence.get_user_email_from_userkey__server(client_b, user_key)
        == "b@example.com"
    )
    assert client_a.get_user_details_by_userkey.call_count == 1
    assert client_b.get_user_details_by_userkey.call_count == 1


def test_display_name_cache_is_instance_isolated() -> None:
    onyx_confluence._USER_ID_TO_DISPLAY_NAME_CACHE.clear()
    user_id = "user-1"
    client_a = _client("https://a.example.com")
    client_a.get_user_details_by_userkey.return_value = {"displayName": "Alice A"}
    client_b = _client("https://b.example.com")
    client_b.get_user_details_by_userkey.return_value = {"displayName": "Bob B"}

    assert onyx_confluence._get_user(client_a, user_id) == "Alice A"
    # same id on a different instance must not see instance A's display name
    assert onyx_confluence._get_user(client_b, user_id) == "Bob B"
