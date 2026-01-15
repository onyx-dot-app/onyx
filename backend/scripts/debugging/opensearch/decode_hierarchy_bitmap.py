#!/usr/bin/env python3
"""
Debug utility for decoding hierarchy bitmaps stored in OpenSearch.

This script can be copied into the OpenSearch container for debugging.
It converts base64-encoded RoaringBitmap values back to integer lists,
or encodes integer lists to base64 bitmaps.

Usage:
    # Decode a base64 bitmap to list of IDs
    python decode_hierarchy_bitmap.py "OjAAAAEAAAAAAAIAEAAAAG8A3gBNAQ=="

    # Encode a comma-separated list of IDs to bitmap
    python decode_hierarchy_bitmap.py "1,5,10,100"
    python decode_hierarchy_bitmap.py 42

Dependencies:
    pip install pyroaring

Examples:
    $ python decode_hierarchy_bitmap.py "OjAAAAEAAA..."
    Decoded IDs: [1, 5, 10, 100]
    Count: 4

    $ python decode_hierarchy_bitmap.py "1,5,10,100"
    IDs: [1, 5, 10, 100]
    Encoded bitmap: OjAAAAEAAA...
    Bitmap size: 24 bytes
"""

import base64
import sys

from pyroaring import BitMap


def decode_bitmap(encoded: str) -> list[int]:
    """Decode base64-encoded RoaringBitmap to list of integers."""
    if not encoded:
        return []
    serialized = base64.b64decode(encoded.encode("utf-8"))
    bitmap = BitMap.deserialize(serialized)
    return sorted(bitmap)


def encode_bitmap(ids: list[int]) -> str:
    """Encode list of integers to base64-encoded RoaringBitmap."""
    if not ids:
        return ""
    bitmap = BitMap(ids)
    serialized = BitMap.serialize(bitmap)
    return base64.b64encode(serialized).decode("utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]

    # Check if it looks like a comma-separated list of integers (for encoding)
    if "," in arg or arg.isdigit():
        try:
            ids = [int(x.strip()) for x in arg.split(",")]
            encoded = encode_bitmap(ids)
            print(f"IDs: {ids}")
            print(f"Encoded bitmap: {encoded}")
            print(f"Bitmap size: {len(encoded)} bytes")
        except ValueError:
            print(f"Error: Could not parse as integer list: {arg}")
            sys.exit(1)
    else:
        # Assume it's a base64-encoded bitmap
        try:
            ids = decode_bitmap(arg)
            print(f"Decoded IDs: {ids}")
            print(f"Count: {len(ids)}")
        except Exception as e:
            print(f"Error decoding bitmap: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
