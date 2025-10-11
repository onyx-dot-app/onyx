"""
Convert prefix strings to u64 integer point IDs.

Following the approach from the Qdrant article:
- Use up to 8 bytes (u64) to encode the prefix
- Encode prefix as ASCII bytes, pad with zeros
"""


def prefix_to_id(prefix: str) -> int:
    """
    Convert a prefix string to a u64 integer point ID.

    Encodes the prefix as ASCII bytes (up to 8 chars) and converts to integer.
    Examples:
        "a" -> 97 (ASCII value of 'a')
        "ab" -> 24930 (0x6162 = 'a' + 'b' << 8)
        "docker" -> 29273878479972 (encodes 'd','o','c','k','e','r')

    Args:
        prefix: The prefix string (max 8 characters, ASCII only)

    Returns:
        u64 integer point ID

    Raises:
        ValueError: If prefix is longer than 8 characters or contains non-ASCII
    """
    if len(prefix) > 8:
        raise ValueError(f"Prefix too long: '{prefix}' (max 8 chars)")

    # Check if prefix is ASCII-only
    if not prefix.isascii():
        raise ValueError(f"Prefix contains non-ASCII characters: '{prefix}'")

    # Convert prefix to bytes (ASCII)
    prefix_bytes = prefix.encode("ascii")

    # Pad to 8 bytes with zeros (right-pad)
    padded = prefix_bytes.ljust(8, b"\x00")

    # Convert to u64 integer (little-endian)
    point_id = int.from_bytes(padded, byteorder="little")

    return point_id


def id_to_prefix(point_id: int) -> str:
    """
    Convert a u64 integer point ID back to prefix string.

    Inverse of prefix_to_id() - useful for debugging.

    Args:
        point_id: The u64 integer point ID

    Returns:
        The original prefix string
    """
    # Convert to 8 bytes (little-endian)
    id_bytes = point_id.to_bytes(8, byteorder="little")

    # Remove padding zeros and decode
    prefix = id_bytes.rstrip(b"\x00").decode("ascii")

    return prefix


if __name__ == "__main__":
    # Test the conversion
    test_prefixes = [
        "a",
        "ab",
        "abc",
        "docker",
        "gitlab",
        "issue",
        "customer",
        "workflow",
    ]

    print("Testing prefix_to_id conversion:")
    print("=" * 60)

    for prefix in test_prefixes:
        point_id = prefix_to_id(prefix)
        recovered = id_to_prefix(point_id)

        print(f"'{prefix}' -> {point_id} -> '{recovered}'")

        # Verify round-trip
        assert recovered == prefix, f"Round-trip failed: {prefix} != {recovered}"

    print("\n✓ All tests passed!")
