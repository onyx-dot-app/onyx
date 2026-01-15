"""Utilities for encoding/decoding hierarchy node IDs as RoaringBitmaps.

This module provides functions to convert lists of integer hierarchy node IDs
to/from base64-encoded RoaringBitmap representations for efficient storage
and querying in OpenSearch.

RoaringBitmaps provide:
- Compact storage for sparse integer sets
- O(1) set membership testing
- Efficient set operations (union, intersection)
- Scalability to 100k+ IDs

Usage:
    # Indexing: encode ancestor IDs before storing in OpenSearch
    bitmap_str = encode_hierarchy_bitmap([1, 5, 10, 100])

    # Querying: encode filter IDs for terms query
    filter_str = encode_filter_bitmap([10, 100, 200])

    # Debugging: decode stored bitmap back to IDs
    ids = decode_hierarchy_bitmap(bitmap_str)
"""

import base64

from pyroaring import BitMap


def encode_hierarchy_bitmap(node_ids: list[int]) -> str:
    """
    Encode a list of hierarchy node IDs as a base64-encoded RoaringBitmap.

    Args:
        node_ids: List of integer hierarchy node IDs (must be non-negative).
                  Order does not matter; duplicates are ignored.

    Returns:
        Base64-encoded string representation of the bitmap.
        Returns empty string if node_ids is empty.

    Example:
        >>> encode_hierarchy_bitmap([1, 5, 10])
        'OjAAAAMAAA...'
    """
    if not node_ids:
        return ""

    bitmap = BitMap(node_ids)
    serialized = BitMap.serialize(bitmap)
    encoded = base64.b64encode(serialized)
    return encoded.decode("utf-8")


def decode_hierarchy_bitmap(encoded: str) -> list[int]:
    """
    Decode a base64-encoded RoaringBitmap back to a list of hierarchy node IDs.

    Args:
        encoded: Base64-encoded bitmap string from OpenSearch.

    Returns:
        Sorted list of integer hierarchy node IDs.
        Returns empty list if encoded is empty string.

    Example:
        >>> decode_hierarchy_bitmap('OjAAAAMAAA...')
        [1, 5, 10]
    """
    if not encoded:
        return []

    serialized = base64.b64decode(encoded.encode("utf-8"))
    bitmap = BitMap.deserialize(serialized)
    return sorted(bitmap)


def encode_filter_bitmap(node_ids: list[int]) -> str:
    """
    Encode filter hierarchy node IDs for use in OpenSearch terms query.

    This is semantically the same as encode_hierarchy_bitmap, but named
    separately for clarity in query-building code. When filtering, the
    encoded bitmap represents the set of hierarchy node IDs to match against.

    Args:
        node_ids: List of hierarchy node IDs to filter by.

    Returns:
        Base64-encoded bitmap string for use in terms query with
        value_type: "bitmap".
    """
    return encode_hierarchy_bitmap(node_ids)
