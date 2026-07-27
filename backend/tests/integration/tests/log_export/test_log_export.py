import os
from io import BytesIO
from zipfile import ZipFile

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Log export is an enterprise feature",
)
class TestLogExport:
    def test_admin_can_download_log_zip(self, admin_user: DATestUser) -> None:
        response = client.get(
            f"{API_SERVER_URL}/admin/log-export/download",
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/zip"
        assert "attachment" in response.headers["Content-Disposition"]

        # The environment may or may not write file logs, so assert the export
        # structure rather than the presence of specific log files.
        with ZipFile(BytesIO(response.content)) as zip_file:
            names = zip_file.namelist()
            assert "README.txt" in names
            readme = zip_file.read("README.txt").decode("utf-8")
            assert "api_server" in readme
            assert "WARNING" in readme

    def test_sequential_downloads_both_succeed(self, admin_user: DATestUser) -> None:
        # The export lock must be released once a download completes; a wedged
        # lock would 429 every subsequent request until the server restarts.
        for _ in range(2):
            response = client.get(
                f"{API_SERVER_URL}/admin/log-export/download",
                headers=admin_user.headers,
            )
            assert response.status_code == 200

    def test_non_admin_cannot_download_log_zip(self, basic_user: DATestUser) -> None:
        response = client.get(
            f"{API_SERVER_URL}/admin/log-export/download",
            headers=basic_user.headers,
        )
        assert response.status_code == 403
