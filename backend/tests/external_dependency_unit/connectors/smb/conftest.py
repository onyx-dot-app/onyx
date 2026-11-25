"""Fixtures for the Windows file share tests. They need the Samba Active
Directory domain controller of ``docker-compose.yml``: see README.md."""

import os
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.smb import source_operations
from onyx.connectors.smb.connector import SmbConnector
from onyx.connectors.smb.source_operations import SmbSourceOperations
from onyx.server.security.models import SSRFProtectionLevel
from tests.external_dependency_unit.connectors.smb.smb_share_admin import ShareAdmin

# The name in the domain controller's certificate, which LDAP with TLS and
# Kerberos need. README.md maps it to the loopback address.
HOST = os.environ.get("SMB_TEST_HOST", "dc1.onyx.test")
SMB_PORT = int(os.environ.get("SMB_TEST_PORT", "1445"))
LDAPS_PORT = int(os.environ.get("SMB_TEST_LDAPS_PORT", "1636"))
LDAP_PORT = int(os.environ.get("SMB_TEST_LDAP_PORT", "1389"))
PASSWORD = os.environ.get("SMB_TEST_PASSWORD", "Onyx-Test-Passw0rd")
CA_CERT_PATH = Path(
    os.environ.get("SMB_TEST_CA_CERT", Path(__file__).parent / ".certs" / "ca.pem")
)
DOMAIN = "ONYXTEST"
SHARE = "plans"
SERVICE_ACCOUNT = "svc-onyx"
MAIL_DOMAIN = "onyx.test"

ConnectorFactory = Callable[..., SmbConnector]


def credential_json(**overrides: Any) -> dict[str, Any]:
    """The service account, with the domain controller for permission sync."""
    return {
        "smb_domain": DOMAIN,
        "smb_username": SERVICE_ACCOUNT,
        "smb_password": PASSWORD,
        "ldap_host": HOST,
        "ldap_port": LDAPS_PORT,
        "ldap_tls": "ldaps",
        "ldap_ca_cert": CA_CERT_PATH.read_text(),
        **overrides,
    }


@pytest.fixture(autouse=True)
def _self_hosted_network_policy() -> Generator[None, None, None]:
    """The test server is on the loopback address, which only the lowest SSRF
    protection level lets a connector reach. The settings come from Postgres,
    which these tests do not need."""
    settings = MagicMock(ssrf_protection_level=SSRFProtectionLevel.DISABLED)
    with (
        patch.object(source_operations, "get_security_settings", return_value=settings),
        patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key",
            return_value=None,
        ),
    ):
        yield


@pytest.fixture(scope="session")
def share_admin() -> Generator[ShareAdmin, None, None]:
    admin = ShareAdmin(
        host=HOST,
        port=SMB_PORT,
        share=SHARE,
        username=f"{DOMAIN}\\Administrator",
        password=PASSWORD,
    )
    yield admin
    admin.close()


@pytest.fixture
def workspace(share_admin: ShareAdmin) -> Generator[str, None, None]:
    """A folder of the share that one test owns. Removed after the test."""
    path = share_admin.make_workspace()
    yield path
    share_admin.rmtree(path)


@pytest.fixture
def connector_factory() -> ConnectorFactory:
    def build(
        path_prefix: str = "",
        excluded_paths: list[str] | None = None,
        credentials: dict[str, Any] | None = None,
    ) -> SmbConnector:
        connector = SmbConnector(
            host=HOST,
            share=SHARE,
            port=SMB_PORT,
            path_prefix=path_prefix,
            excluded_paths=excluded_paths,
            share_permissions_confirmed=True,
        )
        connector.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.SMB.value, credentials or credential_json()
            )
        )
        return connector

    return build


@pytest.fixture
def ops(connector_factory: ConnectorFactory) -> SmbSourceOperations:
    return connector_factory().ops
