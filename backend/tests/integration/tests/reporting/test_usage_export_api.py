import csv
import os
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from io import BytesIO
from io import StringIO
from zipfile import ZipFile

import pytest
import requests

from ee.onyx.db.usage_export import UsageReportMetadata
from onyx.db.seeding.chat_history_seeding import seed_chat_history
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Usage export is an enterprise feature",
)
class TestUsageExportAPI:
    def test_generate_usage_report(self, reset: None, admin_user: DATestUser) -> None:
        # Seed some chat history data for the report
        seed_chat_history(num_sessions=10, num_messages=4, days=30)

        # Get initial list of reports
        initial_response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report",
            headers=admin_user.headers,
        )
        assert initial_response.status_code == 200
        initial_reports = initial_response.json()
        initial_count = len(initial_reports)

        # Test generating a report without date filters (all time)
        response = requests.post(
            f"{API_SERVER_URL}/admin/usage-report",
            json={},
            headers=admin_user.headers,
        )
        assert response.status_code == 204

        # Wait for the new report to appear (with timeout)
        max_wait_time = 60  # seconds
        start_time = time.time()
        current_reports = initial_reports

        while time.time() - start_time < max_wait_time:
            check_response = requests.get(
                f"{API_SERVER_URL}/admin/usage-report",
                headers=admin_user.headers,
            )
            assert check_response.status_code == 200
            current_reports = check_response.json()

            if len(current_reports) > initial_count:
                # New report has been generated
                break

            time.sleep(2)

        # Verify a new report was created
        assert len(current_reports) > initial_count

        # Find the new report (should be the first one since they're ordered by time)
        new_report = current_reports[0]
        assert "report_name" in new_report
        assert new_report["report_name"].endswith(".zip")

    def test_generate_usage_report_with_date_range(
        self, reset: None, admin_user: DATestUser
    ) -> None:
        # Seed some chat history data
        seed_chat_history(num_sessions=20, num_messages=4, days=60)

        # Get initial list of reports
        initial_response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report",
            headers=admin_user.headers,
        )
        assert initial_response.status_code == 200
        initial_reports = initial_response.json()
        initial_count = len(initial_reports)

        # Generate report for the last 30 days
        period_to = datetime.now(tz=timezone.utc)
        period_from = period_to - timedelta(days=30)

        response = requests.post(
            f"{API_SERVER_URL}/admin/usage-report",
            json={
                "period_from": period_from.isoformat(),
                "period_to": period_to.isoformat(),
            },
            headers=admin_user.headers,
        )
        assert response.status_code == 204

        # Wait for the new report to appear
        max_wait_time = 60
        start_time = time.time()
        current_reports = initial_reports

        while time.time() - start_time < max_wait_time:
            check_response = requests.get(
                f"{API_SERVER_URL}/admin/usage-report",
                headers=admin_user.headers,
            )
            assert check_response.status_code == 200
            current_reports = check_response.json()

            if len(current_reports) > initial_count:
                break

            time.sleep(2)

        assert len(current_reports) > initial_count

        # Find the new report (the one that wasn't in initial_reports)
        new_reports = [r for r in current_reports if r not in initial_reports]
        assert len(new_reports) > 0
        new_report = new_reports[0]

        # Verify the new report has the expected date range
        assert new_report["period_from"] is not None
        assert new_report["period_to"] is not None

    def test_generate_usage_report_invalid_dates(
        self, reset: None, admin_user: DATestUser
    ) -> None:
        # Test with invalid date format
        response = requests.post(
            f"{API_SERVER_URL}/admin/usage-report",
            json={
                "period_from": "not-a-date",
                "period_to": datetime.now(tz=timezone.utc).isoformat(),
            },
            headers=admin_user.headers,
        )
        assert response.status_code == 400

    def test_fetch_usage_reports(self, reset: None, admin_user: DATestUser) -> None:
        # First generate a report to ensure we have at least one
        seed_chat_history(num_sessions=5, num_messages=4, days=30)

        # Get initial count
        initial_response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report",
            headers=admin_user.headers,
        )
        assert initial_response.status_code == 200
        initial_count = len(initial_response.json())

        # Generate a report
        generate_response = requests.post(
            f"{API_SERVER_URL}/admin/usage-report",
            json={},
            headers=admin_user.headers,
        )
        assert generate_response.status_code == 204

        # Wait for the new report to appear
        max_wait_time = 15
        start_time = time.time()
        reports = []

        while time.time() - start_time < max_wait_time:
            response = requests.get(
                f"{API_SERVER_URL}/admin/usage-report",
                headers=admin_user.headers,
            )
            assert response.status_code == 200
            reports = response.json()

            if len(reports) > initial_count:
                break

            time.sleep(2)

        # Verify we have at least one report
        assert isinstance(reports, list)
        assert len(reports) > initial_count

        # Validate the structure of the first report
        first_report = reports[0]
        assert "report_name" in first_report
        assert "requestor" in first_report
        assert "time_created" in first_report
        assert "period_from" in first_report
        assert "period_to" in first_report

        # Verify it's a valid UsageReportMetadata object
        report_metadata = UsageReportMetadata(**first_report)
        assert report_metadata.report_name.endswith(".zip")

    def test_read_usage_report(self, reset: None, admin_user: DATestUser) -> None:
        # First generate a report
        seed_chat_history(num_sessions=5, num_messages=4, days=30)

        # Get initial reports count
        initial_response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report",
            headers=admin_user.headers,
        )
        assert initial_response.status_code == 200
        initial_count = len(initial_response.json())

        generate_response = requests.post(
            f"{API_SERVER_URL}/admin/usage-report",
            json={},
            headers=admin_user.headers,
        )
        assert generate_response.status_code == 204

        # Wait for the new report to appear
        max_wait_time = 15
        start_time = time.time()
        reports = []

        while time.time() - start_time < max_wait_time:
            list_response = requests.get(
                f"{API_SERVER_URL}/admin/usage-report",
                headers=admin_user.headers,
            )
            assert list_response.status_code == 200
            reports = list_response.json()

            if len(reports) > initial_count:
                break

            time.sleep(2)

        assert len(reports) > initial_count

        report_name = reports[0]["report_name"]

        # Download the report
        download_response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report/{report_name}",
            headers=admin_user.headers,
            stream=True,
        )
        assert download_response.status_code == 200
        assert download_response.headers["Content-Type"] == "application/zip"
        assert "Content-Disposition" in download_response.headers
        assert (
            f"filename={report_name}"
            in download_response.headers["Content-Disposition"]
        )

        # Verify it's a valid zip file
        zip_content = BytesIO(download_response.content)
        with ZipFile(zip_content, "r") as zip_file:
            # Check that the zip contains expected files
            file_names = zip_file.namelist()
            assert "chat_messages.csv" in file_names
            assert "users.csv" in file_names

            # Verify chat_messages.csv has the expected columns
            with zip_file.open("chat_messages.csv") as csv_file:
                csv_content = csv_file.read().decode("utf-8")
                csv_reader = csv.DictReader(StringIO(csv_content))

                # Check that all expected columns are present
                expected_columns = {
                    "session_id",
                    "user_id",
                    "flow_type",
                    "time_sent",
                    "assistant_name",
                    "user_email",
                    "number_of_tokens",
                }
                actual_columns = set(csv_reader.fieldnames or [])
                assert (
                    expected_columns == actual_columns
                ), f"Expected columns {expected_columns}, but got {actual_columns}"

                # Verify there's at least one row of data
                rows = list(csv_reader)
                assert len(rows) > 0, "Expected at least one message in the report"

                # Verify the first row has non-empty values for all columns
                first_row = rows[0]
                for column in expected_columns:
                    assert column in first_row, f"Column {column} not found in row"
                    assert first_row[
                        column
                    ], f"Column {column} has empty value in first row"

                # Verify specific new fields have appropriate values
                assert first_row["assistant_name"], "assistant_name should not be empty"
                assert first_row["user_email"], "user_email should not be empty"
                assert first_row[
                    "number_of_tokens"
                ].isdigit(), "number_of_tokens should be a numeric value"
                assert (
                    int(first_row["number_of_tokens"]) >= 0
                ), "number_of_tokens should be non-negative"

    def test_read_nonexistent_report(self, reset: None, admin_user: DATestUser) -> None:
        # Try to download a report that doesn't exist
        response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report/nonexistent_report.zip",
            headers=admin_user.headers,
        )
        assert response.status_code == 404

    def test_non_admin_cannot_generate_report(
        self, reset: None, basic_user: DATestUser
    ) -> None:
        # Try to generate a report as non-admin
        response = requests.post(
            f"{API_SERVER_URL}/admin/usage-report",
            json={},
            headers=basic_user.headers,
        )
        assert response.status_code == 403

    def test_non_admin_cannot_fetch_reports(
        self, reset: None, basic_user: DATestUser
    ) -> None:
        # Try to fetch reports as non-admin
        response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report",
            headers=basic_user.headers,
        )
        assert response.status_code == 403

    def test_non_admin_cannot_download_report(
        self, reset: None, basic_user: DATestUser
    ) -> None:
        # Try to download a report as non-admin
        response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report/some_report.zip",
            headers=basic_user.headers,
        )
        assert response.status_code == 403

    def test_concurrent_report_generation(
        self, reset: None, admin_user: DATestUser
    ) -> None:
        # Seed some data
        seed_chat_history(num_sessions=10, num_messages=4, days=30)

        # Get initial count of reports
        initial_response = requests.get(
            f"{API_SERVER_URL}/admin/usage-report",
            headers=admin_user.headers,
        )
        assert initial_response.status_code == 200
        initial_count = len(initial_response.json())

        # Generate multiple reports concurrently
        num_reports = 3
        for i in range(num_reports):
            response = requests.post(
                f"{API_SERVER_URL}/admin/usage-report",
                json={},
                headers=admin_user.headers,
            )
            assert response.status_code == 204

        # Wait for all reports to be generated
        max_wait_time = 120
        start_time = time.time()
        reports = []

        while time.time() - start_time < max_wait_time:
            response = requests.get(
                f"{API_SERVER_URL}/admin/usage-report",
                headers=admin_user.headers,
            )
            assert response.status_code == 200
            reports = response.json()

            if len(reports) >= initial_count + num_reports:
                break

            time.sleep(2)

        # Verify we have at least 3 new reports
        assert len(reports) >= initial_count + num_reports
