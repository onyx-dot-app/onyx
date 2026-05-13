"""Test that swapping a cc_pair's credential_id cascades to the
hierarchy_node_by_connector_credential_pair join table.

Regression for ForeignKeyViolation on
`hierarchy_node_by_connector_cre_connector_id_credential_id_fkey` when a
connector with hierarchy nodes has its credential swapped (e.g. Confluence).
"""

from uuid import uuid4

from sqlalchemy import delete
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
    connector_id: int | None = None
    old_credential_id: int | None = None
    new_credential_id: int | None = None
    hierarchy_node_id: int | None = None
    try:
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
        connector_id = connector.id

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
        old_credential_id = old_credential.id
        new_credential_id = new_credential.id

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
        hierarchy_node_id = hierarchy_node.id

        join_row = HierarchyNodeByConnectorCredentialPair(
            hierarchy_node_id=hierarchy_node.id,
            connector_id=connector.id,
            credential_id=old_credential.id,
        )
        db_session.add(join_row)
        db_session.commit()

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
    finally:
        db_session.rollback()
        if hierarchy_node_id is not None:
            db_session.execute(
                delete(HierarchyNode).where(HierarchyNode.id == hierarchy_node_id)
            )
        if connector_id is not None:
            db_session.execute(
                delete(ConnectorCredentialPair).where(
                    ConnectorCredentialPair.connector_id == connector_id
                )
            )
        for cred_id in (old_credential_id, new_credential_id):
            if cred_id is not None:
                db_session.execute(delete(Credential).where(Credential.id == cred_id))
        if connector_id is not None:
            db_session.execute(delete(Connector).where(Connector.id == connector_id))
        db_session.commit()
