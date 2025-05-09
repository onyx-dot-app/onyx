from sqlalchemy.orm import Session

from ee.onyx.external_permissions.sync_params import (
    source_group_sync_is_cc_pair_agnostic,
)
from onyx.db.connector import mark_cc_pair_as_external_group_synced
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_source
from onyx.db.models import ConnectorCredentialPair


def _get_all_cc_pair_ids_to_mark_as_group_synced(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> list[int]:
    if not source_group_sync_is_cc_pair_agnostic(cc_pair.connector.source):
        return [cc_pair.id]

    cc_pairs = get_connector_credential_pairs_for_source(
        db_session, cc_pair.connector.source
    )
    return [cc_pair.id for cc_pair in cc_pairs]


def mark_all_relevant_cc_pairs_as_external_group_synced(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """For some source types, one successful group sync run should count for all
    cc pairs of that type. This function handles that case."""
    cc_pair_ids = _get_all_cc_pair_ids_to_mark_as_group_synced(db_session, cc_pair)
    for cc_pair_id in cc_pair_ids:
        mark_cc_pair_as_external_group_synced(db_session, cc_pair_id)
