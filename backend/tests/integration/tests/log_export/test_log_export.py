import json
import os
import time
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

# Comfortably above the server-side 90s collection deadline, which bounds how
# long an export can stay in ``collecting`` when a worker never reports.
ASYNC_EXPORT_READY_TIMEOUT_SECONDS = 120


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Log export is an enterprise feature",
)
class TestLogExport:
    def test_async_export_flow(self, admin_user: DATestUser) -> None:
        # Start an export.
        response = client.post(
            f"{API_SERVER_URL}/admin/log-export",
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        export_id = response.json()["export_id"]

        # A second export while one is collecting is rejected.
        conflict = client.post(
            f"{API_SERVER_URL}/admin/log-export",
            headers=admin_user.headers,
        )
        assert conflict.status_code == 429

        # Poll status until ready; bounded by the server-side deadline, so
        # this terminates even if some worker type never reports.
        poll_deadline = time.monotonic() + ASYNC_EXPORT_READY_TIMEOUT_SECONDS
        while True:
            status = client.get(
                f"{API_SERVER_URL}/admin/log-export/{export_id}",
                headers=admin_user.headers,
            )
            assert status.status_code == 200
            body = status.json()
            if body["state"] == "ready":
                break
            assert time.monotonic() < poll_deadline, "Export never became ready."
            time.sleep(2)

        # Every fanned-out worker must have reported: reaching ``ready`` via the
        # deadline with workers still pending means fan-out is broken (bad queue
        # map, lost task registration, dead broker).
        assert body["pending_worker_names"] == []
        reported = {receipt["worker_name"] for receipt in body["receipts"]}
        assert "api_server" in reported

        # The downloaded bundle parses and describes itself.
        download = client.get(
            f"{API_SERVER_URL}/admin/log-export/{export_id}/download",
            headers=admin_user.headers,
        )
        assert download.status_code == 200
        assert download.headers["Content-Type"] == "application/zip"
        with ZipFile(BytesIO(download.content)) as zip_file:
            names = zip_file.namelist()
            assert "README.txt" in names
            assert "manifest.json" in names
            manifest = json.loads(zip_file.read("manifest.json"))
            assert manifest["export_id"] == export_id
            assert any(
                receipt["worker_name"] == "api_server"
                for receipt in manifest["receipts"]
            )

    def test_status_of_unknown_export_is_not_found(
        self, admin_user: DATestUser
    ) -> None:
        response = client.get(
            f"{API_SERVER_URL}/admin/log-export/{uuid4().hex}",
            headers=admin_user.headers,
        )
        assert response.status_code == 404

    def test_non_admin_cannot_start_export(self, basic_user: DATestUser) -> None:
        response = client.post(
            f"{API_SERVER_URL}/admin/log-export",
            headers=basic_user.headers,
        )
        assert response.status_code == 403
