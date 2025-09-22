from datetime import datetime
from datetime import timezone

import pytest

from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.connector_job_tests.jira.conftest import JiraTestEnvSetupTuple


@pytest.mark.xfail(reason="Needs to be tested for flakiness")
def test_jira_permission_sync_full(
    reset: None,
    jira_test_env_setup: JiraTestEnvSetupTuple,
) -> None:
    (
        admin_user,
        credential,
        connector,
        cc_pair,
    ) = jira_test_env_setup

    before = datetime.now(tz=timezone.utc)

    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
        timeout=float("inf"),
    )
