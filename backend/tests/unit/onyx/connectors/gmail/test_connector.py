import datetime
import json
import os
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.gmail.connector import _build_time_range_query
from onyx.connectors.gmail.connector import thread_to_document
from onyx.connectors.models import Document
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.models import ConnectorMissingCredentialError


def test_thread_to_document() -> None:
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        full_email_thread = json.load(f)

    doc = thread_to_document(full_email_thread)
    assert type(doc) == Document
    assert doc.source == DocumentSource.GMAIL
    assert doc.semantic_identifier == "Email Chain 1"
    assert doc.doc_updated_at == datetime.datetime(
        2024, 11, 2, 17, 34, 55, tzinfo=datetime.timezone.utc
    )
    assert len(doc.sections) == 4
    assert doc.metadata == {}


def test_build_time_range_query() -> None:
    time_range_start = 1703066296.159339
    time_range_end = 1704984791.657404
    query = _build_time_range_query(time_range_start, time_range_end)
    assert query == "after:1703066296 before:1704984791"
    query = _build_time_range_query(time_range_start, None)
    assert query == "after:1703066296"
    query = _build_time_range_query(None, time_range_end)
    assert query == "before:1704984791"
    query = _build_time_range_query(0.0, time_range_end)
    assert query == "before:1704984791"
    query = _build_time_range_query(None, None)
    assert query is None


def test_time_str_to_utc() -> None:
    str_to_dt = {
        "Tue, 5 Oct 2021 09:38:25 GMT": datetime.datetime(
            2021, 10, 5, 9, 38, 25, tzinfo=datetime.timezone.utc
        ),
        "Sat, 24 Jul 2021 09:21:20 +0000 (UTC)": datetime.datetime(
            2021, 7, 24, 9, 21, 20, tzinfo=datetime.timezone.utc
        ),
        "Thu, 29 Jul 2021 04:20:37 -0400 (EDT)": datetime.datetime(
            2021, 7, 29, 8, 20, 37, tzinfo=datetime.timezone.utc
        ),
        "30 Jun 2023 18:45:01 +0300": datetime.datetime(
            2023, 6, 30, 15, 45, 1, tzinfo=datetime.timezone.utc
        ),
        "22 Mar 2020 20:12:18 +0000 (GMT)": datetime.datetime(
            2020, 3, 22, 20, 12, 18, tzinfo=datetime.timezone.utc
        ),
    }
    for strptime, expected_datetime in str_to_dt.items():
        assert time_str_to_utc(strptime) == expected_datetime


def test_load_from_state_without_credentials():
    """
    Test that calling load_from_state without loaded credentials raises ConnectorMissingCredentialError.
    This covers the scenario where the GitHub credentials were not set prior to fetching data.
    """
    connector = GithubConnector(repo_owner="dummy_owner", repo_name="dummy_repo")
    # Since load_from_state returns a generator, we force evaluation with list().
    with pytest.raises(ConnectorMissingCredentialError):
        list(connector.load_from_state())


def test_validate_connector_settings_success(monkeypatch):
    """
    Test that validate_connector_settings passes when proper credentials and a valid repository are provided.
    This test mocks the github_client to simulate a valid repository without errors.
    """
    connector = GithubConnector(repo_owner="dummy_owner", repo_name="dummy_repo")
    
    class DummyRepo:
        def get_contents(self, path):
            # Simulate returning contents without error.
            return ["dummy content"]
    
    class DummyGithub:
        def get_repo(self, repo_full_name):
            # Ensure that the connector is calling with the correct repository identifier.
            assert repo_full_name == "dummy_owner/dummy_repo"
            return DummyRepo()
    
    connector.github_client = DummyGithub()
    
    # validate_connector_settings should complete without raising any errors.
    connector.validate_connector_settings()
