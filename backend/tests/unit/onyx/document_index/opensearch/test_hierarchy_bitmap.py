"""Unit tests for hierarchy bitmap encoding/decoding."""

from onyx.document_index.opensearch.hierarchy_bitmap import decode_hierarchy_bitmap
from onyx.document_index.opensearch.hierarchy_bitmap import encode_filter_bitmap
from onyx.document_index.opensearch.hierarchy_bitmap import encode_hierarchy_bitmap


class TestHierarchyBitmap:
    def test_empty_list_returns_empty_string(self) -> None:
        assert encode_hierarchy_bitmap([]) == ""

    def test_empty_string_returns_empty_list(self) -> None:
        assert decode_hierarchy_bitmap("") == []

    def test_roundtrip_single_id(self) -> None:
        original = [42]
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert decoded == original

    def test_roundtrip_multiple_ids(self) -> None:
        original = [1, 5, 10, 100, 1000]
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert sorted(decoded) == sorted(original)

    def test_roundtrip_sequential_ids(self) -> None:
        """Test with sequential IDs (RoaringBitmap is efficient for runs)."""
        original = list(range(1, 101))  # 1-100
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert sorted(decoded) == sorted(original)

    def test_roundtrip_sparse_ids(self) -> None:
        """Test with sparse/random IDs."""
        original = [7, 42, 256, 1024, 8192, 65536]
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert sorted(decoded) == sorted(original)

    def test_roundtrip_large_set(self) -> None:
        """Test with 10k+ IDs to verify bitmap efficiency."""
        original = list(range(0, 50000, 3))  # 16,667 IDs
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert sorted(decoded) == sorted(original)

        # Bitmap should be much smaller than storing raw integers
        # 16,667 ints * 4 bytes = 66,668 bytes; bitmap should be ~10% of that
        # Base64 encoding adds ~33% overhead, so check for reasonable size
        assert len(encoded) < 15000

    def test_encode_filter_bitmap_same_as_hierarchy(self) -> None:
        """encode_filter_bitmap should be identical to encode_hierarchy_bitmap."""
        ids = [1, 2, 3, 100, 200]
        assert encode_filter_bitmap(ids) == encode_hierarchy_bitmap(ids)

    def test_order_independence(self) -> None:
        """Order of input IDs shouldn't matter."""
        ids1 = [1, 5, 3, 2, 4]
        ids2 = [5, 4, 3, 2, 1]
        assert encode_hierarchy_bitmap(ids1) == encode_hierarchy_bitmap(ids2)

    def test_duplicates_ignored(self) -> None:
        """Duplicate IDs should be deduplicated."""
        with_dups = [1, 1, 2, 2, 3, 3]
        without_dups = [1, 2, 3]
        assert encode_hierarchy_bitmap(with_dups) == encode_hierarchy_bitmap(
            without_dups
        )

    def test_zero_id(self) -> None:
        """Zero should be a valid hierarchy node ID."""
        original = [0]
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert decoded == original

    def test_large_single_id(self) -> None:
        """Large IDs should work (within 32-bit unsigned range)."""
        original = [2**31 - 1]  # Max 32-bit signed int
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert decoded == original

    def test_encoded_string_is_base64(self) -> None:
        """Verify the output is valid base64."""
        import base64

        encoded = encode_hierarchy_bitmap([1, 2, 3])
        # Should not raise
        base64.b64decode(encoded)

    def test_decoded_list_is_sorted(self) -> None:
        """Decoded list should be sorted in ascending order."""
        original = [100, 1, 50, 25, 75]
        encoded = encode_hierarchy_bitmap(original)
        decoded = decode_hierarchy_bitmap(encoded)
        assert decoded == sorted(original)
