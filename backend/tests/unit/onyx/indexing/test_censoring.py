import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.db.models import User
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

_post_query_chunk_censoring = fetch_ee_implementation_or_noop(
    "onyx.external_permissions.post_query_censoring", "_post_query_chunk_censoring"
)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permissions tests are enterprise only",
)
class TestPostQueryChunkCensoring:
    @pytest.fixture(autouse=True)
    def setUp(self) -> None:
        self.mock_user = User(id=1, email="test@example.com")
        self.mock_chunk_1 = InferenceChunk(
            document_id="doc1",
            chunk_id=1,
            content="chunk1 content",
            source_type=DocumentSource.SALESFORCE,
            semantic_identifier="doc1_1",
            title="doc1",
            boost=1,
            recency_bias=1.0,
            score=0.9,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="doc1 summary",
            chunk_context="doc1 context",
            updated_at=None,
            image_file_id=None,
            source_links={},
            section_continuation=False,
            blurb="chunk1",
        )
        self.mock_chunk_2 = InferenceChunk(
            document_id="doc2",
            chunk_id=2,
            content="chunk2 content",
            source_type=DocumentSource.SLACK,
            semantic_identifier="doc2_2",
            title="doc2",
            boost=1,
            recency_bias=1.0,
            score=0.8,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="doc2 summary",
            chunk_context="doc2 context",
            updated_at=None,
            image_file_id=None,
            source_links={},
            section_continuation=False,
            blurb="chunk2",
        )
        self.mock_chunk_3 = InferenceChunk(
            document_id="doc3",
            chunk_id=3,
            content="chunk3 content",
            source_type=DocumentSource.SALESFORCE,
            semantic_identifier="doc3_3",
            title="doc3",
            boost=1,
            recency_bias=1.0,
            score=0.7,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="doc3 summary",
            chunk_context="doc3 context",
            updated_at=None,
            image_file_id=None,
            source_links={},
            section_continuation=False,
            blurb="chunk3",
        )
        self.mock_chunk_4 = InferenceChunk(
            document_id="doc4",
            chunk_id=4,
            content="chunk4 content",
            source_type=DocumentSource.SALESFORCE,
            semantic_identifier="doc4_4",
            title="doc4",
            boost=1,
            recency_bias=1.0,
            score=0.6,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="doc4 summary",
            chunk_context="doc4 context",
            updated_at=None,
            image_file_id=None,
            source_links={},
            section_continuation=False,
            blurb="chunk4",
        )

    @patch(
        "ee.onyx.external_permissions.post_query_censoring._get_all_censoring_enabled_sources"
    )
    def test_post_query_chunk_censoring_no_user(
        self, mock_get_sources: MagicMock
    ) -> None:
        mock_get_sources.return_value = {DocumentSource.SALESFORCE}
        chunks = [self.mock_chunk_1, self.mock_chunk_2]
        result = _post_query_chunk_censoring(chunks, None)
        assert result == chunks

    @patch(
        "ee.onyx.external_permissions.post_query_censoring._get_all_censoring_enabled_sources"
    )
    @patch(
        "ee.onyx.external_permissions.post_query_censoring.DOC_SOURCE_TO_CHUNK_CENSORING_FUNCTION"
    )
    def test_post_query_chunk_censoring_salesforce_censored(
        self, mock_censor_func: MagicMock, mock_get_sources: MagicMock
    ) -> None:
        mock_get_sources.return_value = {DocumentSource.SALESFORCE}
        mock_censor_func_impl = MagicMock(
            return_value=[self.mock_chunk_1]
        )  # Only return chunk 1
        mock_censor_func.__getitem__.return_value = mock_censor_func_impl

        chunks = [self.mock_chunk_1, self.mock_chunk_2, self.mock_chunk_3]
        result = _post_query_chunk_censoring(chunks, self.mock_user)
        assert len(result) == 2
        assert self.mock_chunk_1 in result
        assert self.mock_chunk_2 in result
        assert self.mock_chunk_3 not in result
        mock_censor_func_impl.assert_called_once()

    @patch(
        "ee.onyx.external_permissions.post_query_censoring._get_all_censoring_enabled_sources"
    )
    @patch(
        "ee.onyx.external_permissions.post_query_censoring.DOC_SOURCE_TO_CHUNK_CENSORING_FUNCTION"
    )
    def test_post_query_chunk_censoring_salesforce_error(
        self, mock_censor_func: MagicMock, mock_get_sources: MagicMock
    ) -> None:
        mock_get_sources.return_value = {DocumentSource.SALESFORCE}
        mock_censor_func_impl = MagicMock(side_effect=Exception("Censoring error"))
        mock_censor_func.__getitem__.return_value = mock_censor_func_impl

        chunks = [self.mock_chunk_1, self.mock_chunk_2, self.mock_chunk_3]
        result = _post_query_chunk_censoring(chunks, self.mock_user)
        assert len(result) == 1
        assert self.mock_chunk_2 in result
        mock_censor_func_impl.assert_called_once()

    @patch(
        "ee.onyx.external_permissions.post_query_censoring._get_all_censoring_enabled_sources"
    )
    @patch(
        "ee.onyx.external_permissions.post_query_censoring.DOC_SOURCE_TO_CHUNK_CENSORING_FUNCTION"
    )
    def test_post_query_chunk_censoring_no_censoring(
        self, mock_censor_func: MagicMock, mock_get_sources: MagicMock
    ) -> None:
        mock_get_sources.return_value = set()  # No sources to censor
        mock_censor_func_impl = MagicMock()
        mock_censor_func.__getitem__.return_value = mock_censor_func_impl

        chunks = [self.mock_chunk_1, self.mock_chunk_2, self.mock_chunk_3]
        result = _post_query_chunk_censoring(chunks, self.mock_user)
        assert result == chunks
        mock_censor_func_impl.assert_not_called()

    @patch(
        "ee.onyx.external_permissions.post_query_censoring._get_all_censoring_enabled_sources"
    )
    @patch(
        "ee.onyx.external_permissions.post_query_censoring.DOC_SOURCE_TO_CHUNK_CENSORING_FUNCTION"
    )
    def test_post_query_chunk_censoring_order_maintained(
        self, mock_censor_func: MagicMock, mock_get_sources: MagicMock
    ) -> None:
        mock_get_sources.return_value = {DocumentSource.SALESFORCE}
        mock_censor_func_impl = MagicMock(
            return_value=[self.mock_chunk_3, self.mock_chunk_1]
        )  # Return chunk 3 and 1
        mock_censor_func.__getitem__.return_value = mock_censor_func_impl

        chunks = [
            self.mock_chunk_1,
            self.mock_chunk_2,
            self.mock_chunk_3,
            self.mock_chunk_4,
        ]
        result = _post_query_chunk_censoring(chunks, self.mock_user)
        assert len(result) == 3
        assert result[0] == self.mock_chunk_1
        assert result[1] == self.mock_chunk_2
        assert result[2] == self.mock_chunk_3
        assert self.mock_chunk_4 not in result
        mock_censor_func_impl.assert_called_once()
