"""The Google Drive built-in provider: full read/write, Onyx-managed, and its
action catalog matches the request paths the bundled ``gdrive_api.py`` helper
calls. Reads are auto-approved (ALWAYS); mutations default to ASK."""

from __future__ import annotations

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.google_drive import GoogleDriveAction
from onyx.external_apps.providers.google_drive import GoogleDriveProvider
from onyx.external_apps.providers.registry import PROVIDERS

_READ_ACTIONS = {
    GoogleDriveAction.FILES_READ,
    GoogleDriveAction.FILES_EXPORT,
    GoogleDriveAction.DRIVES_READ,
    GoogleDriveAction.DOCS_READ,
}


def _provider() -> GoogleDriveProvider:
    provider = PROVIDERS[ExternalAppType.GOOGLE_DRIVE]
    assert isinstance(provider, GoogleDriveProvider)
    return provider


def test_registered_as_managed_drive_provider() -> None:
    provider = _provider()
    assert isinstance(provider, OnyxManagedExtApp)
    assert provider.spec.app_type == ExternalAppType.GOOGLE_DRIVE


def test_scope_and_patterns_cover_read_and_upload() -> None:
    spec = _provider().spec
    # The single `auth/drive` scope also authorizes the Google Docs API.
    assert spec.oauth.scope == "https://www.googleapis.com/auth/drive"
    # The /upload host path is required for content uploads to be token-injected;
    # the Docs API lives on its own `docs.googleapis.com` host.
    assert spec.descriptor.upstream_url_patterns == [
        "https://www\\.googleapis\\.com/drive/.*",
        "https://www\\.googleapis\\.com/upload/drive/.*",
        "https://docs\\.googleapis\\.com/.*",
    ]
    assert spec.descriptor.auth_template == {"Authorization": "Bearer {access_token}"}


def test_reads_always_writes_ask() -> None:
    """Reads are auto-approved; every mutation defaults to ASK so the egress gate
    prompts the user. GET rules belong only to read actions and vice versa."""
    for endpoint in _provider().spec.endpoint_catalog:
        methods = {r.method for r in endpoint.matches if isinstance(r, RestRoute)}
        if endpoint.id in _READ_ACTIONS:
            assert endpoint.default_policy == EndpointPolicy.ALWAYS
            assert methods == {"GET"}
        else:
            assert endpoint.default_policy == EndpointPolicy.ASK
            assert "GET" not in methods


def test_managed_credential_keys_match_required_fields() -> None:
    provider = _provider()
    required = {f.key for f in provider.spec.descriptor.required_org_credential_fields}
    assert set(provider.managed_org_credentials) == required


def test_catalog_recognises_helper_request_paths() -> None:
    """Each path the helper actually hits must be claimed by exactly one action,
    so per-action policy resolution can't silently misfire."""
    routes = [
        (rule.method, rule.path)
        for endpoint in _provider().spec.endpoint_catalog
        for rule in endpoint.matches
        if isinstance(rule, RestRoute)
    ]

    helper_calls = [
        ("GET", "/drive/v3/files"),  # search / list
        ("GET", "/drive/v3/files/ABC123"),  # get metadata + alt=media download
        ("GET", "/drive/v3/files/ABC123/export"),  # native-doc export
        ("GET", "/drive/v3/drives"),  # list shared drives
        ("POST", "/drive/v3/files"),  # create-folder
        ("POST", "/upload/drive/v3/files"),  # upload new content
        ("PATCH", "/drive/v3/files/ABC123"),  # update metadata / trash
        ("PATCH", "/upload/drive/v3/files/ABC123"),  # replace content
        ("DELETE", "/drive/v3/files/ABC123"),  # delete
        ("GET", "/v1/documents/ABC123"),  # read a Google Doc (Docs API)
        ("POST", "/v1/documents"),  # create a Google Doc
        ("POST", "/v1/documents/ABC123:batchUpdate"),  # edit a Google Doc
    ]
    for method, path in helper_calls:
        matched = [r for r in routes if r[0] == method and path_matches(r[1], path)]
        assert len(matched) == 1, f"{method} {path} matched {matched}, expected one"
