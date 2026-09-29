import json
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.gitlab.connector import GitlabConnector
from onyx.connectors.google_utils import google_auth, google_kv
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY,
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)
from onyx.connectors.highspot.utils import scrape_url_content
from onyx.connectors.web.connector import (
    ScrapeSessionContext,
    WebConnector,
    extract_urls_from_sitemap,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import SSRFProtectionLevel
from onyx.utils import playwright_fetch, sitemap
from onyx.utils.url import SSRFException


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example/api/v1/courses",
        "http://canvas.example/api/v1/courses",
        "https://canvas.example:8443/api/v1/courses",
        "https://user@canvas.example/api/v1/courses",
        "https://canvas.example:0/api/v1/courses",
        "https://canvas.example:invalid/api/v1/courses",
    ],
)
def test_canvas_rejects_checkpoint_destination(url: str) -> None:
    client = CanvasApiClient("test-token", "https://canvas.example")
    with patch("onyx.connectors.canvas.client.rl_requests.get") as get:
        get.return_value.status_code = 200
        get.return_value.headers = {}
        with pytest.raises(OnyxError):
            client.get(full_url=url)
        get.assert_not_called()


@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
def test_gitlab_blocks_metadata_before_constructing_client(
    level: SSRFProtectionLevel,
) -> None:
    with (
        patch(
            "onyx.connectors.gitlab.connector.get_security_settings", create=True
        ) as settings,
        patch("onyx.connectors.gitlab.connector.gitlab.Gitlab") as client,
    ):
        settings.return_value.ssrf_protection_level = level
        connector = GitlabConnector("owner", "project")
        with pytest.raises(ConnectorValidationError):
            connector.load_credentials(
                {
                    "gitlab_url": "https://169.254.169.254",
                    "gitlab_access_token": "test-token",
                }
            )
        client.assert_not_called()


def test_highspot_rejects_private_url_before_starting_browser() -> None:
    with patch("onyx.connectors.highspot.utils.sync_playwright") as browser:
        scrape_url_content("http://127.0.0.1/admin")
        browser.assert_not_called()


def test_google_service_account_pins_token_endpoint() -> None:
    with patch.object(
        google_auth.ServiceAccountCredentials, "from_service_account_info"
    ) as build:
        build.return_value.valid = True
        build.return_value.expired = True
        google_auth.get_google_creds(
            {
                DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: json.dumps(
                    {"token_uri": "https://other.example/token"}
                )
            },
            DocumentSource.GOOGLE_DRIVE,
        )
        assert (
            build.call_args.args[0]["token_uri"]
            == "https://oauth2.googleapis.com/token"
        )


@pytest.mark.parametrize("section", ["web", "installed", "reconstructed"])
def test_google_stored_app_pins_endpoints(section: str) -> None:
    config = {
        "client_id": "test-client",
        "client_secret": "test-secret",
        "token_uri": "https://other.example/token",
        "auth_uri": "https://other.example/auth",
    }
    stored = (
        {DB_CREDENTIALS_DICT_TOKEN_KEY: json.dumps(config)}
        if section == "reconstructed"
        else {DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY: {section: config}}
    )
    credential = MagicMock()
    credential.credential_json.get_value.return_value = stored
    with (
        patch.object(
            google_kv, "fetch_credential_by_id_for_user", return_value=credential
        ),
        patch.object(google_kv, "update_credential_json"),
    ):
        result = google_kv._app_cred_on_row(1, MagicMock(), MagicMock())
    client_config = result["web" if section == "reconstructed" else section]
    assert client_config["token_uri"] == "https://oauth2.googleapis.com/token"
    assert client_config["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
    assert config["token_uri"] == "https://other.example/token"


def test_playwright_fallback_does_not_attach_connector_token() -> None:
    with (
        patch.object(playwright_fetch, "sync_playwright"),
        patch.object(playwright_fetch, "WEB_CONNECTOR_OAUTH_CLIENT_ID", "test-client"),
        patch.object(
            playwright_fetch, "WEB_CONNECTOR_OAUTH_CLIENT_SECRET", "test-secret"
        ),
        patch.object(
            playwright_fetch,
            "WEB_CONNECTOR_OAUTH_TOKEN_URL",
            "https://auth.example/token",
        ),
        patch(
            "requests_oauthlib.OAuth2Session.fetch_token",
            return_value={"access_token": "test-token"},
        ) as fetch_token,
    ):
        playwright_fetch.start_playwright()
        fetch_token.assert_not_called()
        playwright_fetch.get_connector_oauth_header()
        fetch_token.assert_called_once()


def test_sitemap_discovery_blocks_private_targets() -> None:
    with patch("requests.get") as get:
        get.return_value.status_code = 404
        assert sitemap.list_pages_for_site("http://127.0.0.1") == []
        get.assert_not_called()


def test_web_sitemap_uses_safe_fetch_after_initial_check() -> None:
    response = MagicMock()
    response.content = (
        b"<urlset><url><loc>https://example.com/page</loc></url></urlset>"
    )
    with (
        patch("onyx.connectors.web.connector.protected_url_check"),
        patch("onyx.connectors.web.connector.get_security_settings") as settings,
        patch("requests.get", return_value=response) as get,
    ):
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.VALIDATE_ALL
        with pytest.raises(RuntimeError):
            extract_urls_from_sitemap("http://169.254.169.254/sitemap.xml")
        get.assert_not_called()


def test_sitemap_index_cycles_are_bounded() -> None:
    response = MagicMock()
    response.status_code = 200
    response.content = b"<sitemapindex><sitemap><loc>https://example.com/sitemap.xml</loc></sitemap></sitemapindex>"
    response.text = ""
    with (
        patch("onyx.utils.url.ssrf_safe_get", return_value=response),
        patch.object(
            sitemap, "ssrf_safe_get", return_value=response, create=True
        ) as safe_get,
        patch("requests.get", return_value=response) as unsafe_get,
    ):
        assert sitemap.list_pages_for_site("https://example.com") == []
        assert safe_get.call_count + unsafe_get.call_count == 3


def test_playwright_rechecks_final_url_before_returning_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch.object(playwright_fetch, "playwright_session") as session:
        page = session.return_value.__enter__.return_value.new_page.return_value
        page.url = "http://127.0.0.1/private?token=private-test-value"
        page.content.return_value = "private content"
        page.goto.return_value.status = 200
        page.goto.return_value.header_value.return_value = None
        result = playwright_fetch.fetch_rendered_html("https://93.184.216.34")
        assert result is None
        page.content.assert_not_called()
        assert "disallowed" in caplog.text
        assert "private-test-value" not in caplog.text
        assert "127.0.0.1" not in caplog.text


def test_gitlab_normalizes_credential_destination() -> None:
    with (
        patch("onyx.connectors.gitlab.connector.get_security_settings") as settings,
        patch("onyx.connectors.gitlab.connector.gitlab.Gitlab") as client,
    ):
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.DISABLED
        GitlabConnector("owner", "project").load_credentials(
            {
                "gitlab_url": "  https://10.0.0.1  ",
                "gitlab_access_token": "test-token",
            }
        )
        assert client.call_args.args[0] == "https://10.0.0.1"


@pytest.mark.parametrize(
    "destination",
    [
        "https://other.example/api",
        "https://127.0.0.1/api",
        "https://gitlab.example:444/api",
    ],
)
def test_gitlab_checks_each_redirect(destination: str) -> None:
    import socket
    from typing import Any

    import requests

    sent: list[str | None] = []

    def respond(request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        sent.append(request.url)
        response = requests.Response()
        response.request = request
        response.url = request.url or ""
        response.status_code = 302 if len(sent) < 3 else 200
        response._content = b"[]"
        response.headers["Location"] = (
            "https://gitlab.example/api/v4/projects?page=2"
            if len(sent) == 1
            else destination
        )
        return response

    with (
        patch("onyx.connectors.gitlab.connector.get_security_settings") as settings,
        patch(
            "socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", 443),
                )
            ],
        ),
        patch("requests.adapters.HTTPAdapter.send", side_effect=respond),
    ):
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.VALIDATE_ALL
        connector = GitlabConnector("owner", "project")
        connector.load_credentials(
            {
                "gitlab_url": "https://gitlab.example",
                "gitlab_access_token": "test-token",
            }
        )
        assert connector.gitlab_client is not None
        with pytest.raises(ConnectorValidationError):
            connector.gitlab_client.http_get("/projects")
    assert len(sent) == 2


def test_disabled_sitemap_policy_allows_loopback_but_not_metadata() -> None:
    response = MagicMock()
    response.status_code = 200
    response.is_redirect = False
    response.content = (
        b"<urlset><url><loc>https://example.com/page</loc></url></urlset>"
    )
    response.text = ""
    with (
        patch("onyx.connectors.web.connector.get_security_settings") as settings,
        patch("requests.get", return_value=response),
    ):
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.DISABLED
        assert extract_urls_from_sitemap("http://127.0.0.1/sitemap.xml") == [
            "https://example.com/page"
        ]
        assert sitemap.list_pages_for_site(
            "http://127.0.0.1", allow_private_network=True, allow_loopback=True
        ) == ["https://example.com/page"]
        with pytest.raises(RuntimeError):
            extract_urls_from_sitemap("http://169.254.169.254/sitemap.xml")


def test_web_connector_preflight_and_pdf_validate_redirects() -> None:
    from typing import Any

    import requests

    source = "https://93.184.216.34/document"
    sent: list[str | None] = []

    def respond(request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        sent.append(request.url)
        response = requests.Response()
        response.request = request
        response.url = request.url or ""
        redirect = request.url == source
        response.status_code = 302 if redirect else 200
        response.headers.update(
            {
                "Location": "http://127.0.0.1/private",
                "Content-Type": "application/pdf",
            }
        )
        response._content = b"pdf"
        response.raw = MagicMock()
        return response

    session = ScrapeSessionContext(source, [source])
    session.playwright = MagicMock()
    session.playwright_context = MagicMock()
    with (
        patch("onyx.connectors.web.connector.get_security_settings") as settings,
        patch("requests.adapters.HTTPAdapter.send", side_effect=respond),
        patch(
            "onyx.connectors.web.connector.extract_pdf_text", return_value=("text", {})
        ),
    ):
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.VALIDATE_ALL
        with pytest.raises(SSRFException):
            WebConnector(source)._do_scrape(0, source, session)
    assert sent == [source]


@pytest.mark.parametrize(
    "destination",
    [
        "https://other.example/courses",
        "https://canvas.example:8443/courses",
        "http://canvas.example/courses",
    ],
)
def test_canvas_checks_redirect_destinations(destination: str) -> None:
    from typing import Any

    import requests

    sent: list[str | None] = []

    def respond(request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        sent.append(request.url)
        response = requests.Response()
        response.url = request.url or ""
        response.request = request
        response.status_code = 302 if len(sent) < 3 else 200
        response.headers["Location"] = (
            "/api/v1/relocated" if len(sent) == 1 else destination
        )
        response._content = b"[]"
        response.raw = MagicMock()
        return response

    with patch("requests.adapters.HTTPAdapter.send", side_effect=respond):
        with pytest.raises(OnyxError):
            CanvasApiClient("test-token", "https://canvas.example").get("courses")
    assert sent == [
        "https://canvas.example/api/v1/courses",
        "https://canvas.example/api/v1/relocated",
    ]


@pytest.mark.parametrize("port", ["invalid", "65536"])
def test_gitlab_invalid_port_is_validation_error(port: str) -> None:
    with patch("onyx.connectors.gitlab.connector.get_security_settings") as settings:
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.DISABLED
        with pytest.raises(ConnectorValidationError):
            GitlabConnector("owner", "project").load_credentials(
                {
                    "gitlab_url": f"https://10.0.0.1:{port}",
                    "gitlab_access_token": "test-token",
                }
            )


def test_failed_connector_oauth_does_not_launch_browser() -> None:
    with (
        patch(
            "onyx.connectors.web.connector.get_connector_oauth_header",
            side_effect=RuntimeError("token unavailable"),
        ),
        patch("onyx.connectors.web.connector.start_playwright") as launch,
    ):
        launch.return_value = (MagicMock(), MagicMock())
        with pytest.raises(RuntimeError, match="token unavailable"):
            ScrapeSessionContext("https://example.com", []).initialize()
        launch.assert_not_called()


def test_sitemap_keeps_configured_authorization_origin() -> None:
    configured = "https://example.com/sitemap.xml"
    foreign_page = "https://other.example/page"
    page = MagicMock()
    page.url = foreign_page
    page.content.return_value = "<html><body>content</body></html>"
    page.evaluate.return_value = "<html><body>content</body></html>"
    page.goto.return_value.status = 200
    page.goto.return_value.header_value.return_value = None
    context = MagicMock()
    context.new_page.return_value = page
    with (
        patch(
            "onyx.connectors.web.connector.extract_urls_from_sitemap",
            return_value=[foreign_page],
        ),
        patch(
            "onyx.connectors.web.connector.start_playwright",
            return_value=(MagicMock(), context),
        ),
        patch(
            "onyx.connectors.web.connector.get_connector_oauth_header",
            return_value="Bearer test-token",
        ),
        patch("onyx.connectors.web.connector.check_internet_connection"),
        patch("onyx.connectors.web.connector.protected_url_check"),
        patch("onyx.connectors.web.connector.ssrf_safe_get") as preflight,
        patch("onyx.connectors.web.connector.install_ssrf_guard") as guard,
    ):
        preflight.return_value.__enter__.return_value.headers = {
            "content-type": "text/html"
        }
        connector = WebConnector(configured, web_connector_type="sitemap")
        list(connector.load_from_state(slim=True))
    assert guard.call_args.kwargs["authorization_url"] == configured
