import os
from datetime import datetime
from datetime import timezone

from onyx.connectors.models import InputType
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_connector_creation(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # create connectors
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )

    cc_pair_info = CCPairManager.get_single(
        cc_pair_1.id, user_performing_action=admin_user
    )
    assert cc_pair_info
    assert cc_pair_info.creator
    assert str(cc_pair_info.creator) == admin_user.id
    assert cc_pair_info.creator_email == admin_user.email


def test_overlapping_connector_creation(reset: None) -> None:
    """Tests that connectors indexing the same documents don't interfere with each other.
    A previous bug involved document by cc pair entries not being added for new connectors
    when the docs existed already via another connector and were up to date relative to the source.
    """
    admin_user: DATestUser = UserManager.create(name="admin_user")

    config = {
        "wiki_base": os.environ["CONFLUENCE_TEST_SPACE_URL"],
        "space": "DailyConne",
        "is_cloud": True,
    }

    credential = {
        "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
        "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
    }

    # store the time before we create the connector so that we know after
    # when the indexing should have started
    now = datetime.now(timezone.utc)

    # create connector
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.CONFLUENCE,
        connector_specific_config=config,
        credential_json=credential,
        user_performing_action=admin_user,
        input_type=InputType.POLL,
    )

    CCPairManager.wait_for_indexing_completion(
        cc_pair_1, now, timeout=300, user_performing_action=admin_user
    )

    now = datetime.now(timezone.utc)

    cc_pair_2 = CCPairManager.create_from_scratch(
        source=DocumentSource.CONFLUENCE,
        connector_specific_config=config,
        credential_json=credential,
        user_performing_action=admin_user,
        input_type=InputType.POLL,
    )

    CCPairManager.wait_for_indexing_completion(
        cc_pair_2, now, timeout=300, user_performing_action=admin_user
    )

    info_1 = CCPairManager.get_single(cc_pair_1.id, user_performing_action=admin_user)
    assert info_1

    info_2 = CCPairManager.get_single(cc_pair_2.id, user_performing_action=admin_user)
    assert info_2

    assert info_1.num_docs_indexed == info_2.num_docs_indexed


def test_connector_pause_while_indexing(reset: None) -> None:
    """Tests that we can pause a connector while indexing is in progress and that
    tasks end early or abort as a result.

    TODO: This does not specifically test for soft or hard termination code paths.
    Design specific tests for those use cases.
    """
    admin_user: DATestUser = UserManager.create(name="admin_user")

    config = {
        "wiki_base": os.environ["CONFLUENCE_TEST_SPACE_URL"],
        "is_cloud": True,
    }

    credential = {
        "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
        "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
    }

    # store the time before we create the connector so that we know after
    # when the indexing should have started
    datetime.now(timezone.utc)

    # create connector
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.CONFLUENCE,
        connector_specific_config=config,
        credential_json=credential,
        user_performing_action=admin_user,
        input_type=InputType.POLL,
    )

    CCPairManager.wait_for_indexing_in_progress(
        cc_pair_1, timeout=60, num_docs=16, user_performing_action=admin_user
    )

    CCPairManager.pause_cc_pair(cc_pair_1, user_performing_action=admin_user)

    CCPairManager.wait_for_indexing_inactive(
        cc_pair_1, timeout=60, user_performing_action=admin_user
    )
    return
