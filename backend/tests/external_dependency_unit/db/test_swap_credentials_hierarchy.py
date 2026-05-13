"""Test that swapping a cc_pair's credential_id cascades to the
hierarchy_node_by_connector_credential_pair join table.

Regression for ForeignKeyViolation on
`hierarchy_node_by_connector_cre_connector_id_credential_id_fkey` when a
connector with hierarchy nodes has its credential swapped (e.g. Confluence).
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import HierarchyNode
from onyx.db.models import HierarchyNodeByConnectorCredentialPair


def test_cc_pair_credential_swap_cascades_to_hierarchy_join(
    db_session: Session,
) -> None:
    unique = uuid4().hex[:8]
    connector = Connector(
        name="test-connector-%s" % unique,
        source=DocumentSource.CONFLUENCE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    old_credential = Credential(
        source=DocumentSource.CONFLUENCE,
        credential_json={"token": "old"},
        admin_public=True,
    )
    new_credential = Credential(
        source=DocumentSource.CONFLUENCE,
        credential_json={"token": "new"},
        admin_public=True,
    )
    db_session.add_all([old_credential, new_credential])
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=old_credential.id,
        name="test-cc-pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.flush()

    hierarchy_node = HierarchyNode(
        raw_node_id="test-space-%s" % unique,
        display_name="Test Space",
        source=DocumentSource.CONFLUENCE,
        node_type=HierarchyNodeType.SPACE,
    )
    db_session.add(hierarchy_node)
    db_session.flush()

    join_row = HierarchyNodeByConnectorCredentialPair(
        hierarchy_node_id=hierarchy_node.id,
        connector_id=connector.id,
        credential_id=old_credential.id,
    )
    db_session.add(join_row)
    db_session.commit()

    # Mirror swap_credentials_connector's UPDATE
    cc_pair.credential_id = new_credential.id
    db_session.commit()

    reloaded = db_session.execute(
        select(HierarchyNodeByConnectorCredentialPair).where(
            HierarchyNodeByConnectorCredentialPair.hierarchy_node_id
            == hierarchy_node.id,
            HierarchyNodeByConnectorCredentialPair.connector_id == connector.id,
        )
    ).scalar_one()
    assert reloaded.credential_id == new_credential.id

    db_session.delete(hierarchy_node)
    db_session.delete(cc_pair)
    db_session.delete(old_credential)
    db_session.delete(new_credential)
    db_session.delete(connector)
    db_session.commit()
