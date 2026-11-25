"""The test-side patches that point Onyx at the mock SharePoint server, in a
test block and for a whole process (sitecustomize.py)."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from onyx.connectors.sharepoint import connector_utils
from onyx.connectors.sharepoint.connector_utils import SiteUrlHostError
from onyx.server.security.models import SSRFProtectionLevel
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
)
from tests.integration.mock_services.mock_sharepoint_server.mock_sharepoint.patch_onyx import (
    mock_url_for,
    point_onyx_at_mock,
)

_MOCK_URL = "http://127.0.0.1:9651"
_OTHER_MOCK_URL = "http://127.0.0.1:9652"
_MOCK_DIR = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "integration"
    / "mock_services"
    / "mock_sharepoint_server"
)


def test_microsoft_urls_map_to_the_mock_prefixes() -> None:
    graph = mock_url_for(
        "https://graph.microsoft.com/v1.0/drives/b!x/root/delta?$top=200&token=a%2Bb",
        _MOCK_URL,
    )
    login = mock_url_for(
        "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token", _MOCK_URL
    )
    sharepoint = mock_url_for(
        "https://onyxmock.sharepoint.com/sites/site1/_api/Web/"
        "getFileByServerRelativeUrl('%2Fsites%2Fsite1%2FSitePages%2FHome.aspx')",
        _MOCK_URL,
    )

    assert graph == (
        f"{_MOCK_URL}/graph/v1.0/drives/b!x/root/delta?$top=200&token=a%2Bb"
    )
    assert login == f"{_MOCK_URL}/login/tenant-id/oauth2/v2.0/token"
    # The encoded slashes stay encoded.
    assert sharepoint == (
        f"{_MOCK_URL}/sharepoint/onyxmock.sharepoint.com/sites/site1/_api/Web/"
        "getFileByServerRelativeUrl('%2Fsites%2Fsite1%2FSitePages%2FHome.aspx')"
    )
    assert mock_url_for("https://example.com/v1.0/sites", _MOCK_URL) is None
    assert mock_url_for("https://sharepoint.com.example.com/x", _MOCK_URL) is None
    assert mock_url_for(f"{_MOCK_URL}/graph/v1.0/sites", _MOCK_URL) is None


def test_the_patches_end_with_the_block() -> None:
    send = requests.Session.send
    getaddrinfo = socket.getaddrinfo

    with point_onyx_at_mock(_MOCK_URL):
        assert requests.Session.send is not send
        assert socket.getaddrinfo is not getaddrinfo
        # A SharePoint host resolves with no lookup.
        resolved = socket.getaddrinfo("no-such-tenant.sharepoint.com", 443)
        assert resolved

    assert requests.Session.send is send
    assert socket.getaddrinfo is getaddrinfo


def test_the_inner_block_selects_the_url(mock_sharepoint: MockSharepoint) -> None:
    """A nested block sends calls to its own URL, and the outer URL comes
    back when the nested block ends."""
    site_listing = "https://graph.microsoft.com/v1.0/sites/getAllSites"

    with point_onyx_at_mock(_OTHER_MOCK_URL):
        with point_onyx_at_mock(mock_sharepoint.url):
            inner = requests.get(site_listing, timeout=10)
        with pytest.raises(requests.ConnectionError) as outer:
            requests.get(site_listing, timeout=10)

    # The inner block reached the mock, which refused the call with no token.
    assert inner.status_code == 401
    assert inner.json()["error"]["code"] == "InvalidAuthenticationToken"
    assert outer.value.request is not None
    assert outer.value.request.url == f"{_OTHER_MOCK_URL}/graph/v1.0/sites/getAllSites"


def test_site_url_validation_passes_for_a_mock_site(
    mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The outbound URL guard resolves the site host. The mock tenant has no
    DNS record, so the patch answers the lookup."""
    # The strict level makes the guard refuse a host that does not resolve.
    settings = connector_utils.get_security_settings().model_copy(
        update={"ssrf_protection_level": SSRFProtectionLevel.VALIDATE_ALL}
    )
    monkeypatch.setattr(connector_utils, "get_security_settings", lambda: settings)
    site_url = mock_sharepoint.site_urls()[0]

    mock_sharepoint.build_connector(sites=[site_url]).validate_connector_settings()

    other_tenant = mock_sharepoint.build_connector(
        sites=[site_url, "https://othertenant.sharepoint.com/sites/site1"]
    )
    with pytest.raises(SiteUrlHostError):
        other_tenant.validate_connector_settings()


def _run_with_sitecustomize(script: str, mock_url: str) -> dict[str, str]:
    backend_dir = _MOCK_DIR.parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_MOCK_DIR), str(backend_dir)])
    env["MOCK_SHAREPOINT_URL"] = mock_url
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_sitecustomize_patches_a_new_process(mock_sharepoint: MockSharepoint) -> None:
    """With the mock folder on PYTHONPATH and MOCK_SHAREPOINT_URL set, the
    unchanged connector signs in at the mock and lists its sites."""
    credentials = mock_sharepoint.credentials()
    script = (
        "import json\n"
        "from onyx.connectors.sharepoint.connector import SharepointConnector\n"
        "connector = SharepointConnector()\n"
        f"connector.load_credentials({credentials!r})\n"
        "sites = [site.url for site in connector.fetch_sites()]\n"
        "print(json.dumps({'sites': ','.join(sites)}))\n"
    )

    seen = _run_with_sitecustomize(script, mock_sharepoint.url + "/")

    assert seen["sites"].split(",") == mock_sharepoint.site_urls()
