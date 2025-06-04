import json
from datetime import datetime

import pytest
import requests

from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import KGConfig
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager


@pytest.mark.parametrize(
    "req, expected_status_code, expected_updated_config",
    [
        (
            EnableKGConfigRequest(
                enabled=True,
                vendor="Test",
                vendor_domains=["test.app", "tester.ai"],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
            200,
            KGConfig(
                enabled=True,
                vendor="Test",
                vendor_domains=["test.app", "tester.ai"],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
        ),
        (
            EnableKGConfigRequest(
                enabled=True,
                vendor="Test",
                vendor_domains=[],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
            400,
            KGConfig(
                enabled=True,
                vendor="Test",
                vendor_domains=["test.app", "tester.ai"],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
        ),
    ],
)
def test_kg_enable(
    reset: None,
    req: EnableKGConfigRequest,
    expected_status_code: int,
    expected_updated_config: KGConfig,
):
    admin_user = UserManager.create(name="admin_user")

    res1 = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        # Need to `.model_dump_json()` and then `json.loads`.
        # Seems redundant, but this is because simply calling `json=data.model_dump()`
        # returns in a "datetime cannot be JSON serialized error".
        json=json.loads(req.model_dump_json()),
    )
    assert res1.status_code == expected_status_code

    # We only check if the update has indeed been written to the DB iff the prior `PUT` was successful.
    if expected_status_code == 200:
        res2 = requests.get(
            f"{API_SERVER_URL}/admin/kg/config",
            headers=admin_user.headers,
        )
        assert res2.status_code == 200

        actual_config = KGConfig.model_validate_json(res2.text)

        assert actual_config == expected_updated_config
