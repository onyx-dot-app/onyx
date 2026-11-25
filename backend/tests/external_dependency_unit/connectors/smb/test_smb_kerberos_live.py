"""Kerberos sign-in against the live domain: the file server and the
directory, with a ticket from the service account's password.

These tests need the Kerberos libraries (``uv sync --group kerberos``) and
port 88 of the test server: see README.md.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.models import SlimDocument
from onyx.connectors.smb.capability_checks import (
    KERBEROS_TICKET_CHECK_ID,
    SIGN_IN_CHECK_ID,
    build_smb_indexing_checks,
)
from tests.external_dependency_unit.connectors.smb.conftest import (
    HOST,
    SERVICE_ACCOUNT,
    ConnectorFactory,
    credential_json,
)
from tests.external_dependency_unit.connectors.smb.smb_share_admin import ShareAdmin

REALM = "ONYX.TEST"


def _kerberos_credentials() -> dict[str, object]:
    return credential_json(
        authentication_method="kerberos", kerberos_realm=REALM, kerberos_kdc=HOST
    )


def test_kerberos_signs_in_to_the_file_server_and_the_directory(
    share_admin: ShareAdmin, workspace: str, connector_factory: ConnectorFactory
) -> None:
    share_admin.write(f"{workspace}/plan.txt", "plan")
    connector = connector_factory(workspace, credentials=_kerberos_credentials())

    session = connector.ops.connect()
    listed = [
        item.id
        for batch in connector.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    ]
    domain = connector.ops.get_directory_info()

    assert session.encrypted
    assert [document_id.rsplit("/", 1)[-1] for document_id in listed] == ["plan.txt"]
    assert domain.base_dn == "DC=onyx,DC=test"


def test_the_ticket_and_sign_in_checks_name_the_kerberos_principal(
    connector_factory: ConnectorFactory,
) -> None:
    connector = connector_factory(credentials=_kerberos_credentials())
    context = CapabilityCheckContext(
        source=DocumentSource.SMB,
        credential_json=_kerberos_credentials(),
        connector_specific_config=connector.config().model_dump(mode="json"),
        source_operations=connector.ops,
    )
    checks = {check.check_id: check for check in build_smb_indexing_checks()}

    ticket = checks[KERBEROS_TICKET_CHECK_ID].run(context)
    sign_in = checks[SIGN_IN_CHECK_ID].run(context)

    principal = f"{SERVICE_ACCOUNT}@{REALM}"
    assert isinstance(ticket, CheckOutput) and isinstance(sign_in, CheckOutput)
    assert ticket.summary == f"The KDC issued a ticket for {principal}"
    assert not ticket.advisories
    assert sign_in.summary == f"Signed in as {principal} with Kerberos"
