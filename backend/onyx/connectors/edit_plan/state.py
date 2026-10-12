from sqlalchemy.orm import Session

from onyx.connectors.edit_plan.models import CurrentPairState
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.models import UserGroup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


def fetch_current_pair_state(db_session: Session, cc_pair_id: int) -> CurrentPairState:
    """The pair's stored state, in the shape an edit proposes. Data-access
    groups are an EE feature; CE pairs have none.

    Raises:
        OnyxError: CONNECTOR_NOT_FOUND when the pair does not exist.
    """
    cc_pair = get_connector_credential_pair_from_id(
        db_session, cc_pair_id, eager_load_connector=True
    )
    if cc_pair is None:
        raise OnyxError(
            OnyxErrorCode.CONNECTOR_NOT_FOUND,
            f"Connector-credential pair {cc_pair_id} does not exist.",
        )
    data_access_groups: list[UserGroup] = fetch_ee_implementation_or_noop(
        "onyx.db.cc_pair_data_access",
        "fetch_data_access_groups_for_cc_pair",
        noop_return_value=[],
    )(db_session, cc_pair_id)
    connector = cc_pair.connector
    return CurrentPairState(
        cc_pair_id=cc_pair.id,
        connector_id=connector.id,
        status=cc_pair.status,
        source=connector.source,
        input_type=connector.input_type,
        connector_specific_config=connector.connector_specific_config,
        access_type=cc_pair.access_type,
        data_access_group_ids=[group.id for group in data_access_groups],
        credential_id=cc_pair.credential_id,
        indexing_start=connector.indexing_start,
        name=cc_pair.name,
        refresh_freq=connector.refresh_freq,
        prune_freq=connector.prune_freq,
    )
