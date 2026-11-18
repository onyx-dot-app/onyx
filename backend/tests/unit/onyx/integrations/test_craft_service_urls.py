from types import SimpleNamespace
from typing import cast

import pytest

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.integrations.craft import craft_service_urls


@pytest.mark.parametrize(
    ("app_type", "patterns", "origins"),
    [
        (
            ExternalAppType.LINEAR,
            [r"https://api\.linear\.app/.*"],
            ["https://api.linear.app"],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://api.linear.app/*"],
            ["https://api.linear.app"],
        ),
        (
            ExternalAppType.ZENDESK,
            [r"https://acme\-support\.zendesk\.com/api/v2/.*"],
            ["https://acme-support.zendesk.com"],
        ),
        (
            ExternalAppType.LINEAR,
            ["https://api.linear.app/.*", r"https://api\.linear.app/.*"],
            [],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://user:secret@API.Example.com:443/private?token=secret#fragment"],
            ["https://api.example.com"],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://api.example.com?token=secret", "https://api.example.com:8443/*"],
            ["https://api.example.com", "https://api.example.com:8443"],
        ),
        (
            ExternalAppType.CUSTOM,
            [
                "http://API.Example.com:80/a",
                "http://api.example.com/*",
                "https://api.example.com:443/*",
            ],
            ["http://api.example.com", "https://api.example.com"],
        ),
        (
            ExternalAppType.LINEAR,
            [
                r"https://(?:api|www)\.linear\.app/.*",
                r"https://api\.linear\.app?/.*",
                r"https://.*\.linear\.app/.*",
            ],
            [],
        ),
        (
            ExternalAppType.CUSTOM,
            [
                "https://*.example.com/*",
                "https://api.example.com:bad/*",
                "ftp://api.example.com/*",
                "https://api%2eexample.com/*",
                "https://api?.example.com/*",
                "https://api\n.example.com/*",
            ],
            [],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://[2001:db8::1]:443/*"],
            ["https://[2001:db8::1]"],
        ),
    ],
)
def test_craft_service_urls_keep_only_clean_origins(
    app_type: ExternalAppType, patterns: list[str], origins: list[str]
) -> None:
    app = cast(
        ExternalApp,
        SimpleNamespace(app_type=app_type, upstream_url_patterns=patterns),
    )

    urls = craft_service_urls(app)

    assert urls == origins
    assert not any("secret" in url for url in urls)
