"""Post-query censoring must touch only chunks of documents indexed under a
perm-synced cc_pair of a censoring source and not under a public one. Every
other chunk passes through unchanged, in its original position."""

from collections.abc import Generator
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.external_permissions.post_query_censoring import (
    _get_censored_document_ids,
    _post_query_chunk_censoring,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.db.enums import AccessType

_MODULE = "ee.onyx.external_permissions.post_query_censoring"


def _chunk(doc_id: str, source: DocumentSource, score: float) -> InferenceChunk:
    return InferenceChunk(
        document_id=doc_id,
        chunk_id=0,
        content=f"{doc_id} content",
        source_type=source,
        semantic_identifier=doc_id,
        title=doc_id,
        boost=1,
        score=score,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary=f"{doc_id} summary",
        chunk_context=f"{doc_id} context",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb=doc_id,
    )


def _user(anonymous: bool = False) -> MagicMock:
    user = MagicMock()
    user.email = "test@example.com"
    user.is_anonymous = anonymous
    return user


@pytest.mark.parametrize("censors_private_connectors", [False, True])
def test_censored_document_selection(censors_private_connectors: bool) -> None:
    access_types = {
        "synced": {AccessType.SYNC},
        "restricted": {AccessType.SYNC_RESTRICTED},
        "synced_and_private": {AccessType.SYNC, AccessType.PRIVATE},
        "synced_and_public": {AccessType.SYNC, AccessType.PUBLIC},
        "private": {AccessType.PRIVATE},
        "public": {AccessType.PUBLIC},
    }
    sync_config = MagicMock()
    sync_config.censoring_config.censors_private_connectors = censors_private_connectors
    with (
        patch(f"{_MODULE}.get_session_with_current_tenant"),
        patch(f"{_MODULE}.get_document_access_types", return_value=access_types),
        patch(f"{_MODULE}.get_source_perm_sync_config", return_value=sync_config),
    ):
        censored = _get_censored_document_ids(
            {DocumentSource.SALESFORCE: set(access_types) | {"gone"}}
        )

    expected = {"synced", "restricted", "synced_and_private", "gone"}
    if censors_private_connectors:
        expected.add("private")
    assert censored == expected


class TestPostQueryChunkCensoring:
    @pytest.fixture(autouse=True)
    def setUp(self) -> Generator[None, None, None]:
        self.synced_1 = _chunk("sf_synced_1", DocumentSource.SALESFORCE, 0.9)
        self.slack = _chunk("slack_doc", DocumentSource.SLACK, 0.8)
        self.synced_2 = _chunk("sf_synced_2", DocumentSource.SALESFORCE, 0.7)
        self.sf_public = _chunk("sf_public", DocumentSource.SALESFORCE, 0.6)
        self.chunks = [self.synced_1, self.slack, self.synced_2, self.sf_public]
        self.censor = MagicMock()
        sync_config = MagicMock()
        sync_config.censoring_config.chunk_censoring_func = self.censor
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    f"{_MODULE}.get_all_censoring_enabled_sources",
                    return_value={DocumentSource.SALESFORCE},
                )
            )
            stack.enter_context(
                patch(
                    f"{_MODULE}._get_censored_document_ids",
                    return_value={"sf_synced_1", "sf_synced_2"},
                )
            )
            stack.enter_context(
                patch(
                    f"{_MODULE}.get_source_perm_sync_config", return_value=sync_config
                )
            )
            yield

    def test_only_censored_documents_reach_the_censor(self) -> None:
        self.censor.return_value = [self.synced_1]

        result = _post_query_chunk_censoring(self.chunks, _user())

        assert result == [self.synced_1, self.slack, self.sf_public]
        self.censor.assert_called_once_with(
            [self.synced_1, self.synced_2], "test@example.com"
        )

    def test_anonymous_user_loses_censored_documents_only(self) -> None:
        result = _post_query_chunk_censoring(self.chunks, _user(anonymous=True))

        assert result == [self.slack, self.sf_public]
        self.censor.assert_not_called()

    def test_censor_error_drops_censored_documents_only(self) -> None:
        self.censor.side_effect = Exception("Censoring error")

        result = _post_query_chunk_censoring(self.chunks, _user())

        assert result == [self.slack, self.sf_public]

    def test_order_is_preserved(self) -> None:
        self.censor.return_value = [self.synced_2, self.synced_1]

        result = _post_query_chunk_censoring(self.chunks, _user())

        assert result == self.chunks

    def test_no_censored_documents_passes_everything_through(self) -> None:
        with patch(f"{_MODULE}._get_censored_document_ids", return_value=set()):
            result = _post_query_chunk_censoring(self.chunks, _user())

        assert result == self.chunks
        self.censor.assert_not_called()
