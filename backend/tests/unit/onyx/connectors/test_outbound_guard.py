import ast
import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.egnyte.connector import EgnyteConnector
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.zulip.connector import ZulipConnector
from onyx.server.security.models import SSRFProtectionLevel

_CONNECTORS_DIR = Path(__file__).parents[4] / "onyx" / "connectors"
_HTTP_MODULES = frozenset({"requests", "httpx", "rl_requests"})

# Modules that still call an HTTP client directly. Move a module to a guarded
# session, then remove it here. Do not add new entries.
_RAW_HTTP_BASELINE = frozenset(
    {
        "axero.connector",
        "bitbucket.utils",
        "bookstack.client",
        "braintrust.connector",
        "canvas.client",
        "clickup.connector",
        "coda.connector",
        "confluence.utils",
        "cross_connector_utils.download",
        "cross_connector_utils.miscellaneous_utils",
        "discourse.connector",
        "document360.connector",
        "fireflies.connector",
        "freshdesk.connector",
        "gitbook.connector",
        "gong.connector",
        "guru.connector",
        "highspot.client",
        "hubspot.source_operations",
        "linear.source_operations",
        "lumapps.client",
        "microsoft_utils.drive_items",
        "microsoft_utils.graph_client",
        "mock_connector.connector",
        "notion.source_operations",
        "outline.client",
        "productboard.connector",
        "slab.connector",
        "teams.files",
        "testrail.connector",
        "web.connector",
        "xenforo.connector",
        "zendesk.connector",
        "zoom.client",
    }
)

_URL_LIKE_KEY = re.compile(r"url|host|domain|wiki_base|zuliprc")

# URL-like keys that the connector validates itself, that are not declared yet,
# or that pick no request target.
_UNDECLARED_URL_KEYS = frozenset(
    {
        (DocumentSource.WEB, "base_url"),
        (DocumentSource.WEB, "url_rewrites"),
        (DocumentSource.GOOGLE_DRIVE, "shared_drive_urls"),
        (DocumentSource.GOOGLE_DRIVE, "shared_folder_urls"),
        (DocumentSource.GOOGLE_DRIVE, "exclude_domain_link_only"),
        (DocumentSource.SLAB, "base_url"),
        (DocumentSource.ZULIP, "realm_url"),
        (DocumentSource.ZULIP, "zuliprc_content"),
        (DocumentSource.GOOGLE_SITES, "base_url"),
        (DocumentSource.SHAREPOINT, "authority_host"),
        (DocumentSource.SHAREPOINT, "graph_api_host"),
        (DocumentSource.SHAREPOINT, "sharepoint_domain_suffix"),
        (DocumentSource.ONEDRIVE, "authority_host"),
        (DocumentSource.ONEDRIVE, "graph_api_host"),
        (DocumentSource.TEAMS, "authority_host"),
        (DocumentSource.TEAMS, "graph_api_host"),
        (DocumentSource.OUTLOOK, "authority_host"),
        (DocumentSource.OUTLOOK, "graph_api_host"),
        (DocumentSource.AIRTABLE, "airtable_url"),
        (DocumentSource.IMAP, "host"),
        (DocumentSource.MOCK_CONNECTOR, "mock_server_host"),
        (DocumentSource.CONFLUENCE, "wiki_base"),
        (DocumentSource.GITHUB, "github_base_url"),
        (DocumentSource.GITLAB, "gitlab_url"),
        (DocumentSource.GONG, "gong_base_url"),
        (DocumentSource.LOOPIO, "loopio_subdomain"),
        (DocumentSource.ZOOM, "host_emails"),
    }
)


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(_CONNECTORS_DIR).with_suffix("").parts)


def _raw_http_modules() -> set[str]:
    modules: set[str] = set()
    for path in _CONNECTORS_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in _HTTP_MODULES
            ):
                modules.add(_module_name(path))
    return modules


def _credential_keys(package: Path) -> set[str]:
    """String keys read from a ``credentials`` mapping in the package."""
    keys: set[str] = set()
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            target: ast.expr | None = None
            key: ast.expr | None = None
            if isinstance(node, ast.Subscript):
                target, key = node.value, node.slice
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
            ):
                target, key = node.func.value, node.args[0]
            if (
                isinstance(target, ast.Name)
                and target.id == "credentials"
                and isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            ):
                keys.add(key.value)
    return keys


def test_no_new_module_calls_an_http_client_directly() -> None:
    found = _raw_http_modules()
    assert found - _RAW_HTTP_BASELINE == set(), "use a guarded session instead"
    assert _RAW_HTTP_BASELINE - found == set(), "remove fixed modules from baseline"


def test_url_like_fields_are_declared() -> None:
    missing: set[tuple[DocumentSource, str]] = set()
    for source, mapping in CONNECTOR_CLASS_MAP.items():
        declared = {field.key for field in mapping.outbound_fields}
        package = _CONNECTORS_DIR / mapping.module_path.split(".")[2]
        keys = set(mapping.config_class.model_fields) | _credential_keys(package)
        for key in keys:
            if _URL_LIKE_KEY.search(key) and key not in declared:
                missing.add((source, key))
    assert missing - _UNDECLARED_URL_KEYS == set()


@pytest.fixture
def no_dns() -> Iterator[MagicMock]:
    with patch.object(
        socket, "getaddrinfo", side_effect=AssertionError("DNS lookup")
    ) as lookup:
        yield lookup


def _settings(level: SSRFProtectionLevel) -> Any:
    return patch(
        "onyx.connectors.cross_connector_utils.outbound.get_security_settings",
        return_value=MagicMock(ssrf_protection_level=level),
    )


def _connector_class() -> MagicMock:
    connector_class = MagicMock()
    connector_class.return_value.load_credentials.return_value = None
    return connector_class


def _instantiate(
    source: DocumentSource,
    config: dict[str, Any],
    credential: dict[str, Any],
    connector_class: MagicMock,
) -> None:
    stored = MagicMock()
    stored.credential_json.get_value.return_value = credential
    with (
        patch(
            "onyx.connectors.factory.identify_connector_class",
            return_value=connector_class,
        ),
        patch("onyx.connectors.factory.emit_credential_access"),
        patch(
            "onyx.connectors.factory.get_image_extraction_and_analysis_enabled",
            return_value=False,
        ),
    ):
        instantiate_connector(MagicMock(), source, None, config, stored)


_ZENDESK = {"zendesk_email": "a@example.com", "zendesk_token": "t"}
_FRESHDESK = {"freshdesk_api_key": "k"}


@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
@pytest.mark.parametrize(
    ("source", "config", "credential"),
    [
        (DocumentSource.JIRA, {"jira_base_url": "http://169.254.169.254/"}, {}),
        (DocumentSource.CANVAS, {"canvas_base_url": "https://169.254.169.254"}, {}),
        (DocumentSource.MEDIAWIKI, {"hostname": "169.254.169.254"}, {}),
        (
            DocumentSource.BOOKSTACK,
            {},
            {"bookstack_base_url": "http://169.254.169.254/"},
        ),
        (
            DocumentSource.ZENDESK,
            {},
            {**_ZENDESK, "zendesk_subdomain": "attacker.example/"},
        ),
        (
            DocumentSource.ZENDESK,
            {},
            {**_ZENDESK, "zendesk_subdomain": "10.0.0.5:6379/"},
        ),
        (
            DocumentSource.FRESHDESK,
            {},
            {**_FRESHDESK, "freshdesk_domain": "attacker.example/x.freshdesk.com"},
        ),
        (
            DocumentSource.EGNYTE,
            {},
            {"domain": "attacker.example/", "access_token": "t"},
        ),
    ],
)
def test_rejects_internal_or_injected_host_at_every_level(
    level: SSRFProtectionLevel,
    source: DocumentSource,
    config: dict[str, Any],
    credential: dict[str, Any],
    no_dns: MagicMock,  # noqa: ARG001
) -> None:
    connector_class = _connector_class()
    with _settings(level), pytest.raises(ConnectorValidationError):
        _instantiate(source, config, credential, connector_class)
    connector_class.return_value.load_credentials.assert_not_called()
    if config:
        connector_class.assert_not_called()


@pytest.mark.parametrize(
    ("source", "config", "credential"),
    [
        (DocumentSource.JIRA, {"jira_base_url": "https://10.0.0.5:6379/"}, {}),
        (DocumentSource.OUTLINE, {}, {"outline_base_url": "http://127.0.0.1:8080"}),
        (DocumentSource.TESTRAIL, {}, {"testrail_base_url": "https://192.168.1.1"}),
    ],
)
def test_rejects_private_host_at_default_level(
    source: DocumentSource,
    config: dict[str, Any],
    credential: dict[str, Any],
    no_dns: MagicMock,  # noqa: ARG001
) -> None:
    with (
        _settings(SSRFProtectionLevel.VALIDATE_ALL),
        pytest.raises(ConnectorValidationError),
    ):
        _instantiate(source, config, credential, _connector_class())


@pytest.mark.parametrize(
    "subdomain", ["acme", "https://acme.zendesk.com", "https://acme.zendesk.com/"]
)
def test_accepts_vendor_subdomain(subdomain: str, no_dns: MagicMock) -> None:  # noqa: ARG001
    connector_class = _connector_class()
    with _settings(SSRFProtectionLevel.VALIDATE_ALL):
        _instantiate(
            DocumentSource.ZENDESK,
            {},
            {**_ZENDESK, "zendesk_subdomain": subdomain},
            connector_class,
        )
    connector_class.return_value.load_credentials.assert_called_once()


def test_accepts_private_host_when_level_is_relaxed() -> None:
    connector_class = _connector_class()
    with _settings(SSRFProtectionLevel.VALIDATE_LLM):
        _instantiate(
            DocumentSource.JIRA,
            {"jira_base_url": "https://10.0.0.5"},
            {},
            connector_class,
        )
    connector_class.assert_called_once()


def test_egnyte_oauth_rejects_injected_domain() -> None:
    with pytest.raises(ValueError):
        EgnyteConnector.AdditionalOauthKwargs(egnyte_domain="attacker.example/")
    EgnyteConnector.AdditionalOauthKwargs(egnyte_domain="acme")


def test_zulip_rejects_metadata_site_before_connecting() -> None:
    connector = ZulipConnector("realm", "https://chat.example.com")
    zuliprc = "[api] email=a@example.com key=k site=http://169.254.169.254"
    with (
        _settings(SSRFProtectionLevel.DISABLED),
        patch("onyx.connectors.zulip.connector.Client") as client,
        pytest.raises(ConnectorValidationError),
    ):
        connector.load_credentials({"zuliprc_content": zuliprc})
    client.assert_not_called()
