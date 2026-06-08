"""Tests for build_available_sources_section() and company-search skill rendering."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import User
from onyx.skills.rendering import build_available_sources_section
from tests.external_dependency_unit.craft._test_helpers import make_cc_pair


class TestBuildAvailableSourcesSection:
    def test_no_connectors(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        result = build_available_sources_section(db_session, test_user)
        assert result == "No connected sources available for this user."

    def test_single_source(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        make_cc_pair(db_session, source=DocumentSource.GOOGLE_DRIVE)

        result = build_available_sources_section(db_session, test_user)
        assert "google_drive" in result
        assert "Documents, spreadsheets, and presentations" in result

    def test_multiple_sources(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        make_cc_pair(db_session, source=DocumentSource.GOOGLE_DRIVE)
        make_cc_pair(db_session, source=DocumentSource.SLACK)
        make_cc_pair(db_session, source=DocumentSource.LINEAR)

        result = build_available_sources_section(db_session, test_user)
        lines = result.strip().split("\n")
        assert len(lines) == 3
        assert any("google_drive" in line for line in lines)
        assert any("slack" in line for line in lines)
        assert any("linear" in line for line in lines)

    def test_duplicate_sources_deduplicated(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        make_cc_pair(db_session, source=DocumentSource.SLACK)
        make_cc_pair(db_session, source=DocumentSource.SLACK)

        result = build_available_sources_section(db_session, test_user)
        assert result.count("slack") == 1

    def test_source_without_description_falls_back_to_title(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        make_cc_pair(db_session, source=DocumentSource.MOCK_CONNECTOR)

        result = build_available_sources_section(db_session, test_user)
        assert "Mock Connector" in result

    @pytest.mark.parametrize(
        "source",
        [DocumentSource.GOOGLE_DRIVE, DocumentSource.SLACK, DocumentSource.CONFLUENCE],
    )
    def test_output_format(
        self,
        db_session: Session,
        test_user: User,
        source: DocumentSource,
    ) -> None:
        make_cc_pair(db_session, source=source)
        result = build_available_sources_section(db_session, test_user)
        assert result.startswith("- `")
        assert "` — " in result
