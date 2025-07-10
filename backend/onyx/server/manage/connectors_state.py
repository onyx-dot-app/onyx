from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.db.engine import get_session
from onyx.db.engine import get_current_tenant_id

from onyx.server.documents.models import ConnectorIndexingStatus
from onyx.redis.redis_pool import get_redis_client
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.db.index_attempt import get_latest_index_attempts
from onyx.db.index_attempt import get_latest_index_attempts_by_status
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.connector_credential_pair import get_cc_pair_groups_for_ids
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.server.documents.models import ConnectorSnapshot

from onyx.redis.redis_connector import RedisConnector

from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.server.documents.models import CredentialSnapshot
from onyx.db.deletion_attempt import check_deletion_attempt_is_allowed
from onyx.db.models import SearchSettings
from onyx.redis.redis_connector_utils import get_deletion_attempt_snapshot
from onyx.server.documents.models import IndexAttemptSnapshot


def get_connectors_state(db_session, tenant_id) -> list[ConnectorIndexingStatus]:
    indexing_statuses: list[ConnectorIndexingStatus] = []

    user = None
    secondary_index = False
    r = get_redis_client(tenant_id=tenant_id)

    # NOTE: If the connector is deleting behind the scenes,
    # accessing cc_pairs can be inconsistent and members like
    # connector or credential may be None.
    # Additional checks are done to make sure the connector and credential still exists.
    # TODO: make this one query ... possibly eager load or wrap in a read transaction
    # to avoid the complexity of trying to error check throughout the function
    cc_pairs = get_connector_credential_pairs(
        db_session=db_session,
        #        user=user,
        #        get_editable=False,
    )

    cc_pair_identifiers = [
        ConnectorCredentialPairIdentifier(
            connector_id=cc_pair.connector_id, credential_id=cc_pair.credential_id)
        for cc_pair in cc_pairs
    ]

    latest_index_attempts = get_latest_index_attempts(
        secondary_index=secondary_index,
        db_session=db_session,
    )

    cc_pair_to_latest_index_attempt = {
        (
            index_attempt.connector_credential_pair.connector_id,
            index_attempt.connector_credential_pair.credential_id,
        ): index_attempt
        for index_attempt in latest_index_attempts
    }

    document_count_info = get_document_counts_for_cc_pairs(
        db_session=db_session,
        cc_pairs=cc_pair_identifiers,
    )
    cc_pair_to_document_cnt = {(connector_id, credential_id)
                                : cnt for connector_id, credential_id, cnt in document_count_info}

    group_cc_pair_relationships = get_cc_pair_groups_for_ids(
        db_session=db_session,
        cc_pair_ids=[cc_pair.id for cc_pair in cc_pairs],
    )
    group_cc_pair_relationships_dict: dict[int, list[int]] = {}
    for relationship in group_cc_pair_relationships:
        group_cc_pair_relationships_dict.setdefault(
            relationship.cc_pair_id, []).append(relationship.user_group_id)

    search_settings: SearchSettings | None = None
    if not secondary_index:
        search_settings = get_current_search_settings(db_session)
    else:
        search_settings = get_secondary_search_settings(db_session)

    for cc_pair in cc_pairs:
        # TODO remove this to enable ingestion API
        if cc_pair.name == "DefaultCCPair":
            continue

        connector = cc_pair.connector
        credential = cc_pair.credential
        if not connector or not credential:
            # This may happen if background deletion is happening
            continue

        in_progress = False
        if search_settings:
            redis_connector = RedisConnector(tenant_id, cc_pair.id)
            redis_connector_index = redis_connector.new_index(
                search_settings.id)
            if redis_connector_index.fenced:
                in_progress = True

        #        if search_settings:
        #            rci = RedisConnectorIndexing(cc_pair.id, search_settings.id)
        #            if r.exists(rci.fence_key):
        #                in_progress = True

        latest_index_attempt = cc_pair_to_latest_index_attempt.get(
            (connector.id, credential.id))

        latest_finished_attempt = get_latest_index_attempt_for_cc_pair_id(
            db_session=db_session,
            connector_credential_pair_id=cc_pair.id,
            secondary_index=secondary_index,
            only_finished=True,
        )

        indexing_statuses.append(
            ConnectorIndexingStatus(
                cc_pair_id=cc_pair.id,
                name=cc_pair.name,
                cc_pair_status=cc_pair.status,
                connector=ConnectorSnapshot.from_connector_db_model(connector),
                credential=CredentialSnapshot.from_credential_db_model(
                    credential),
                access_type=cc_pair.access_type,
                owner=credential.user.email if credential.user else "",
                groups=group_cc_pair_relationships_dict.get(cc_pair.id, []),
                last_finished_status=(
                    latest_finished_attempt.status if latest_finished_attempt else None),
                last_status=(
                    latest_index_attempt.status if latest_index_attempt else None),
                last_success=cc_pair.last_successful_index_time,
                docs_indexed=cc_pair_to_document_cnt.get(
                    (connector.id, credential.id), 0),
                error_msg=(
                    latest_index_attempt.error_msg if latest_index_attempt else None),
                latest_index_attempt=(
                    IndexAttemptSnapshot.from_index_attempt_db_model(
                        latest_index_attempt) if latest_index_attempt else None
                ),
                deletion_attempt=get_deletion_attempt_snapshot(
                    connector_id=connector.id,
                    credential_id=credential.id,
                    db_session=db_session,
                    tenant_id=tenant_id,
                ),
                is_deletable=check_deletion_attempt_is_allowed(
                    connector_credential_pair=cc_pair,
                    db_session=db_session,
                    # allow scheduled indexing attempts here, since on deletion request we will cancel them
                    allow_scheduled=True,
                )
                is None,
                in_progress=in_progress,
            )
        )
    return indexing_statuses
