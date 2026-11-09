"""Tests for the company-search skill sections and rendering."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import DocumentSet, User
from onyx.skills.built_in import COMPANY_SEARCH
from onyx.skills.rendering import (
    build_available_document_sets_section,
    build_available_sources_section,
    render_company_search_skill,
)
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

COMPANY_SEARCH_TEMPLATE = COMPANY_SEARCH.source_dir / "SKILL.md.template"


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
        make_cc_pair(db_session, source=DocumentSource.GOOGLE_DRIVE, commit=False)

        result = build_available_sources_section(db_session, test_user)
        assert "google_drive" in result
        assert "Documents, spreadsheets, and presentations" in result

    def test_multiple_sources(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        make_cc_pair(db_session, source=DocumentSource.GOOGLE_DRIVE, commit=False)
        make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
        make_cc_pair(db_session, source=DocumentSource.LINEAR, commit=False)

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
        make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)
        make_cc_pair(db_session, source=DocumentSource.SLACK, commit=False)

        result = build_available_sources_section(db_session, test_user)
        assert result.count("slack") == 1

    def test_source_without_description_falls_back_to_title(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        make_cc_pair(db_session, source=DocumentSource.MOCK_CONNECTOR, commit=False)

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
        make_cc_pair(db_session, source=source, commit=False)
        result = build_available_sources_section(db_session, test_user)
        assert result.startswith("- `")
        assert "` — " in result


class TestBuildAvailableDocumentSetsSection:
    def test_lists_only_document_sets_the_user_can_read(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        suffix = uuid4().hex[:8]
        public_name = f"Engineering Wiki {suffix}"
        private_name = f"Board Minutes {suffix}"
        db_session.add_all(
            [
                DocumentSet(name=public_name, description="Runbooks", is_public=True),
                DocumentSet(name=private_name, description=None, is_public=False),
            ]
        )
        db_session.flush()

        result = build_available_document_sets_section(db_session, test_user)
        assert f"- `{public_name}` — Runbooks" in result.split("\n")
        assert private_name not in result

    def test_rendered_skill_documents_the_flag_and_sets(
        self,
        db_session: Session,
        test_user: User,
        tmp_path: Path,
    ) -> None:
        name = f"Sales Playbooks {uuid4().hex[:8]}"
        db_session.add(DocumentSet(name=name, description="", is_public=True))
        db_session.flush()
        skill_dir = tmp_path / "company-search"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md.template").write_text(
            COMPANY_SEARCH_TEMPLATE.read_text()
        )

        rendered = render_company_search_skill(db_session, test_user, tmp_path)
        assert "{{AVAILABLE_DOCUMENT_SETS_SECTION}}" not in rendered
        assert f"- `{name}`\n" in rendered
        assert "--document-set" in rendered
