import pytest

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.string_filtering import (
    MAX_DOCUMENT_ID_ENCODED_LENGTH,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


SINGLE_TENANT_STATE = TenantState(
    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
)
MULTI_TENANT_STATE = TenantState(
    tenant_id="tenant_abcdef12-3456-7890-abcd-ef1234567890", multitenant=True
)
EXPECTED_SHORT_TENANT = "abcdef12"


class TestGetOpensearchDocChunkIdSingleTenant:
    def test_basic(self) -> None:
        result = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, "my-doc-id", chunk_index=0
        )
        assert result == f"my-doc-id__{DEFAULT_MAX_CHUNK_SIZE}__0"

    def test_custom_chunk_size(self) -> None:
        result = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, "doc1", chunk_index=3, max_chunk_size=1024
        )
        assert result == "doc1__1024__3"

    def test_special_chars_are_stripped(self) -> None:
        """Tests characters not matching [A-Za-z0-9_.-~] are removed."""
        result = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, "doc/with?special#chars&more%stuff", chunk_index=0
        )
        assert "/" not in result
        assert "?" not in result
        assert "#" not in result
        assert result == f"docwithspecialcharsmorestuff__{DEFAULT_MAX_CHUNK_SIZE}__0"

    def test_short_doc_id_not_hashed(self) -> None:
        """
        Tests that a short doc ID should appear directly in the result, not as a
        hash.
        """
        doc_id = "short-id"
        result = get_opensearch_doc_chunk_id(SINGLE_TENANT_STATE, doc_id, chunk_index=0)
        assert "short-id" in result

    def test_long_doc_id_is_hashed(self) -> None:
        """
        Tests that a doc ID exceeding the max length should be replaced with a
        blake2b hash.
        """
        # Create a doc ID that will exceed max length after the suffix is
        # appended.
        doc_id = "a" * MAX_DOCUMENT_ID_ENCODED_LENGTH
        result = get_opensearch_doc_chunk_id(SINGLE_TENANT_STATE, doc_id, chunk_index=0)
        # The original doc ID should NOT appear in the result.
        assert doc_id not in result
        # The suffix should still be present.
        assert f"__{DEFAULT_MAX_CHUNK_SIZE}__0" in result

    def test_long_doc_id_hash_is_deterministic(self) -> None:
        doc_id = "x" * MAX_DOCUMENT_ID_ENCODED_LENGTH
        result1 = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, doc_id, chunk_index=5
        )
        result2 = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, doc_id, chunk_index=5
        )
        assert result1 == result2

    def test_long_doc_id_different_inputs_produce_different_hashes(self) -> None:
        doc_id_a = "a" * MAX_DOCUMENT_ID_ENCODED_LENGTH
        doc_id_b = "b" * MAX_DOCUMENT_ID_ENCODED_LENGTH
        result_a = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, doc_id_a, chunk_index=0
        )
        result_b = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, doc_id_b, chunk_index=0
        )
        assert result_a != result_b

    def test_result_never_exceeds_max_length(self) -> None:
        """
        Tests that the final result should always be under
        MAX_DOCUMENT_ID_ENCODED_LENGTH bytes.
        """
        doc_id = "z" * (MAX_DOCUMENT_ID_ENCODED_LENGTH * 2)
        result = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, doc_id, chunk_index=999, max_chunk_size=99999
        )
        assert len(result.encode("utf-8")) < MAX_DOCUMENT_ID_ENCODED_LENGTH

    def test_no_tenant_prefix_in_single_tenant(self) -> None:
        result = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, "mydoc", chunk_index=0
        )
        assert not result.startswith(SINGLE_TENANT_STATE.tenant_id)


class TestGetOpensearchDocChunkIdMultiTenant:
    def test_includes_tenant_prefix(self) -> None:
        result = get_opensearch_doc_chunk_id(MULTI_TENANT_STATE, "mydoc", chunk_index=0)
        assert result.startswith(f"{EXPECTED_SHORT_TENANT}__")

    def test_format(self) -> None:
        result = get_opensearch_doc_chunk_id(
            MULTI_TENANT_STATE, "mydoc", chunk_index=2, max_chunk_size=256
        )
        assert result == f"{EXPECTED_SHORT_TENANT}__mydoc__256__2"

    def test_long_doc_id_is_hashed_multitenant(self) -> None:
        doc_id = "d" * MAX_DOCUMENT_ID_ENCODED_LENGTH
        result = get_opensearch_doc_chunk_id(MULTI_TENANT_STATE, doc_id, chunk_index=0)
        # Should still have tenant prefix.
        assert result.startswith(f"{EXPECTED_SHORT_TENANT}__")
        # The original doc ID should NOT appear in the result.
        assert doc_id not in result
        # The suffix should still be present.
        assert f"__{DEFAULT_MAX_CHUNK_SIZE}__0" in result

    def test_result_never_exceeds_max_length_multitenant(self) -> None:
        doc_id = "q" * (MAX_DOCUMENT_ID_ENCODED_LENGTH * 2)
        result = get_opensearch_doc_chunk_id(
            MULTI_TENANT_STATE, doc_id, chunk_index=999, max_chunk_size=99999
        )
        assert len(result.encode("utf-8")) < MAX_DOCUMENT_ID_ENCODED_LENGTH

    def test_different_tenants_produce_different_ids(self) -> None:
        tenant_a = TenantState(
            tenant_id="tenant_aaaaaaaa-0000-0000-0000-000000000000", multitenant=True
        )
        tenant_b = TenantState(
            tenant_id="tenant_bbbbbbbb-0000-0000-0000-000000000000", multitenant=True
        )
        result_a = get_opensearch_doc_chunk_id(tenant_a, "same-doc", chunk_index=0)
        result_b = get_opensearch_doc_chunk_id(tenant_b, "same-doc", chunk_index=0)
        assert result_a != result_b


class TestGetOpensearchDocChunkIdEdgeCases:
    def test_chunk_index_zero(self) -> None:
        result = get_opensearch_doc_chunk_id(SINGLE_TENANT_STATE, "doc", chunk_index=0)
        assert result.endswith("__0")

    def test_large_chunk_index(self) -> None:
        result = get_opensearch_doc_chunk_id(
            SINGLE_TENANT_STATE, "doc", chunk_index=99999
        )
        assert result.endswith("__99999")

    def test_doc_id_with_only_special_chars_raises(self) -> None:
        """
        Tests that a doc ID that becomes empty after filtering should raise
        ValueError.
        """
        with pytest.raises(ValueError, match="empty after filtering"):
            get_opensearch_doc_chunk_id(SINGLE_TENANT_STATE, "###???///", chunk_index=0)

    def test_doc_id_at_boundary_length(self) -> None:
        """
        Tests that a doc ID right at the boundary should not be hashed.
        """
        suffix = f"__{DEFAULT_MAX_CHUNK_SIZE}__0"
        suffix_len = len(suffix.encode("utf-8"))
        # Max doc ID length that won't trigger hashing (must be <
        # max_encoded_length).
        max_doc_len = MAX_DOCUMENT_ID_ENCODED_LENGTH - suffix_len - 1
        doc_id = "a" * max_doc_len
        result = get_opensearch_doc_chunk_id(SINGLE_TENANT_STATE, doc_id, chunk_index=0)
        assert doc_id in result

    def test_doc_id_one_over_boundary_is_hashed(self) -> None:
        """
        Tests that a doc ID one byte over the boundary should be hashed.
        """
        suffix = f"__{DEFAULT_MAX_CHUNK_SIZE}__0"
        suffix_len = len(suffix.encode("utf-8"))
        # This length will trigger the >= check in filter_and_validate_document_id
        doc_id = "a" * (MAX_DOCUMENT_ID_ENCODED_LENGTH - suffix_len)
        result = get_opensearch_doc_chunk_id(SINGLE_TENANT_STATE, doc_id, chunk_index=0)
        assert doc_id not in result
