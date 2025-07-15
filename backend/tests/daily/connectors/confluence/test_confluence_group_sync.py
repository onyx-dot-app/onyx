from typing import Any

from ee.onyx.external_permissions.confluence.group_sync import confluence_group_sync
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from shared_configs.contextvars import get_current_tenant_id


def test_confluence_group_sync(
    confluence_connector_config: dict[str, Any],
    confluence_credential_json: dict[str, Any],
) -> None:
    SqlEngine.init_engine(pool_size=10, max_overflow=10)

    with get_session_with_current_tenant() as db_session:
        connector = Connector(
            name="Test Connector",
            source=DocumentSource.CONFLUENCE,
            input_type=InputType.POLL,
            connector_specific_config=confluence_connector_config,
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        )
        db_session.add(connector)
        db_session.flush()

        credential = Credential(
            source=DocumentSource.CONFLUENCE,
            credential_json=confluence_credential_json,
        )
        db_session.add(credential)
        db_session.flush()

        cc_pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name="Test CC Pair",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.SYNC,
            auto_sync_options=None,
        )
        db_session.add(cc_pair)
        db_session.commit()
        db_session.refresh(cc_pair)

        tenant_id = get_current_tenant_id()
        group_sync_iter = confluence_group_sync(
            tenant_id=tenant_id,
            cc_pair=cc_pair,
        )

        for external_user_group in group_sync_iter:
            print(external_user_group)
