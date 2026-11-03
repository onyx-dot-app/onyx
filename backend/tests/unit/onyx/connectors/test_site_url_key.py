"""Site URLs compare equal only when the connector reaches the same place
with them: a bare host's trailing slash is ignored, a path's is not."""

from urllib.parse import urljoin

from onyx.connectors.connector_config import BaseUrlCredentialBinding, site_url_key


def _key(base_url: str) -> str:
    return BaseUrlCredentialBinding(base_url=base_url).comparison_values()["base_url"]


def test_a_bare_host_with_or_without_its_slash_is_one_site() -> None:
    assert _key("https://forum.example.com") == _key("HTTPS://Forum.example.com/")


def test_a_path_keeps_its_trailing_slash() -> None:
    # urljoin resolves against "/forum/" and "/forum" differently.
    assert urljoin("https://h.example.com/forum/", "latest.json") != urljoin(
        "https://h.example.com/forum", "latest.json"
    )
    assert _key("https://h.example.com/forum/") != _key("https://h.example.com/forum")


def test_another_path_on_the_same_host_is_another_site() -> None:
    assert site_url_key("https://h.example.com/forum") != site_url_key(
        "https://h.example.com/other"
    )
