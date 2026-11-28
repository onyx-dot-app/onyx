import os

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

STATUS_URL = f"{API_SERVER_URL}/admin/service-status/opensearch"


@pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="Service status is an enterprise feature",
)
class TestServiceStatus:
    def test_admin_reads_the_cluster_status(self, admin_user: DATestUser) -> None:
        # A fresh read, so the shared result cannot expire before the second read.
        response = client.get(
            STATUS_URL, params={"refresh": "true"}, headers=admin_user.headers
        )
        assert response.status_code == 200
        status = response.json()
        assert status["health"] in {"green", "yellow", "red"}
        assert status["nodes"]
        assert status["data_node_count"] == len(status["nodes"])
        [current] = [index for index in status["indexes"] if index["is_current"]]
        assert current["model_dim"] > 0
        assert current["primary_shards"] >= 1

        # A second read within the cache window returns the same result.
        again = client.get(STATUS_URL, headers=admin_user.headers)
        assert again.status_code == 200
        assert again.json()["checked_at"] == status["checked_at"]

    def test_basic_user_is_denied(self, basic_user: DATestUser) -> None:
        response = client.get(STATUS_URL, headers=basic_user.headers)
        assert response.status_code == 403
