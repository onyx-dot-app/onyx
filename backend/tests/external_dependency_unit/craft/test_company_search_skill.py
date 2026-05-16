"""Tests for build_available_sources_section() and company-search skill rendering."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import User
from onyx.skills.rendering import build_available_sources_section


def _create_cc_pair(
    db_session: Session,
    user: User,
    source: DocumentSource,
    connector_config: dict | None = None,
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"test-{source.value}-{uuid4().hex[:6]}",
        source=source,
        input_type=None,
        connector_specific_config=connector_config or {},
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        credential_json={},
        user_id=user.id,
        source=source,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        name=f"test-cc-{uuid4().hex[:6]}",
        connector_id=connector.id,
        credential_id=credential.id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        creator_id=user.id,
    )
    db_session.add(cc_pair)
    db_session.flush()
    return cc_pair


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
        _create_cc_pair(db_session, test_user, DocumentSource.GOOGLE_DRIVE)

        result = build_available_sources_section(db_session, test_user)
        assert "google_drive" in result
        assert "Documents, spreadsheets, and presentations" in result

    def test_multiple_sources(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        _create_cc_pair(db_session, test_user, DocumentSource.GOOGLE_DRIVE)
        _create_cc_pair(db_session, test_user, DocumentSource.SLACK)
        _create_cc_pair(db_session, test_user, DocumentSource.LINEAR)

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
        _create_cc_pair(db_session, test_user, DocumentSource.SLACK)
        _create_cc_pair(db_session, test_user, DocumentSource.SLACK)

        result = build_available_sources_section(db_session, test_user)
        assert result.count("slack") == 1

    def test_source_without_description_falls_back_to_title(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        _create_cc_pair(db_session, test_user, DocumentSource.MOCK_CONNECTOR)

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
        _create_cc_pair(db_session, test_user, source)
        result = build_available_sources_section(db_session, test_user)
        assert result.startswith("- `")
        assert "` — " in result
