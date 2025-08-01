"""
S3 key sanitization utilities for ensuring AWS S3 compatibility.

This module provides utilities for sanitizing file names to be compatible with
AWS S3 object key naming guidelines while ensuring uniqueness when significant
sanitization occurs.

Reference: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
"""

import hashlib
import re
import urllib.parse
from re import Match

# Constants for S3 key generation
HASH_LENGTH = 64  # SHA256 hex digest length
HASH_SEPARATOR_LENGTH = 1  # Length of underscore separator
HASH_WITH_SEPARATOR_LENGTH = HASH_LENGTH + HASH_SEPARATOR_LENGTH


def _encode_special_char(match: Match[str]) -> str:
    """Helper function to URL encode special characters."""
    return urllib.parse.quote(match.group(0), safe="")


def sanitize_s3_key_name(file_name: str) -> str:
    """
    Sanitize file name to be S3-compatible according to AWS guidelines.

    This method:
    1. Replaces problematic characters with safe alternatives
    2. URL-encodes characters that might require special handling
    3. Ensures the result is safe for S3 object keys
    4. Adds uniqueness when significant sanitization occurs

    Args:
        file_name: The original file name to sanitize

    Returns:
        A sanitized file name that is S3-compatible

    Reference: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
    """
    if not file_name:
        return "unnamed_file"

    original_name = file_name

    # Characters to avoid completely (replace with underscore)
    # These are characters that AWS recommends avoiding
    avoid_chars = r'[\\{}^%`\[\]"<>#|~/]'

    # Replace avoided characters with underscore
    sanitized = re.sub(avoid_chars, "_", file_name)
    # Characters that might require special handling but are allowed
    # We'll URL encode these to be safe
    special_chars = r"[&$@=;:+,?\s]"

    sanitized = re.sub(special_chars, _encode_special_char, sanitized)

    # Handle non-ASCII characters by URL encoding them
    # This ensures Unicode characters are properly handled
    needs_unicode_encoding = False
    try:
        # Try to encode as ASCII to check if it contains non-ASCII chars
        sanitized.encode("ascii")
    except UnicodeEncodeError:
        needs_unicode_encoding = True
        # Contains non-ASCII characters, URL encode the entire string
        # but preserve safe ASCII characters
        sanitized = urllib.parse.quote(
            sanitized,
            safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.()!*",
        )

    # Ensure we don't have consecutive periods at the start (relative path issue)
    sanitized = re.sub(r"^\.+", "", sanitized)

    # Remove any trailing periods to avoid download issues
    sanitized = sanitized.rstrip(".")

    # Remove multiple separators
    sanitized = re.sub(r"[-_]{2,}", "-", sanitized)

    # If sanitization resulted in empty string, use a default
    if not sanitized:
        sanitized = "sanitized_file"

    # Check if significant sanitization occurred and add uniqueness if needed
    significant_changes = (
        # Check if we replaced many characters
        len(re.findall(avoid_chars, original_name)) > 3
        or
        # Check if we had to URL encode Unicode characters
        needs_unicode_encoding
        or
        # Check if the sanitized name is very different in length (expansion due to encoding)
        len(sanitized) > len(original_name) * 2
        or
        # Check if the original had many special characters
        len(re.findall(special_chars, original_name)) > 5
    )

    if significant_changes:
        # Add a short hash to ensure uniqueness while keeping some readability
        name_hash = hashlib.sha256(original_name.encode("utf-8")).hexdigest()[:8]

        # Try to preserve file extension if it exists and is reasonable
        if "." in sanitized and len(sanitized.split(".")[-1]) <= 10:
            name_parts = sanitized.rsplit(".", 1)
            sanitized = f"{name_parts[0]}_{name_hash}.{name_parts[1]}"
        else:
            sanitized = f"{sanitized}_{name_hash}"

    return sanitized


def generate_s3_key(
    file_name: str, prefix: str, tenant_id: str, max_key_length: int = 1024
) -> str:
    """
    Generate a complete S3 key from file name with prefix and tenant ID.

    Args:
        file_name: The original file name
        prefix: S3 key prefix (e.g., 'onyx-files')
        tenant_id: Tenant identifier
        max_key_length: Maximum allowed S3 key length (default: 1024)

    Returns:
        A complete S3 key that fits within the length limit
    """
    # Strip slashes from prefix and tenant_id to avoid double slashes
    prefix_clean = prefix.strip("/")
    tenant_clean = tenant_id.strip("/")

    # Sanitize the file name first
    sanitized_file_name = sanitize_s3_key_name(file_name)

    # Handle long file names that could exceed S3's key limit
    # S3 key format: {prefix}/{tenant_id}/{file_name}
    prefix_and_tenant_parts = [prefix_clean, tenant_clean]
    prefix_and_tenant = "/".join(prefix_and_tenant_parts) + "/"
    max_file_name_length = max_key_length - len(prefix_and_tenant)

    if len(sanitized_file_name) < max_file_name_length:
        return "/".join(prefix_and_tenant_parts + [sanitized_file_name])

    # For very long file names, use hash-based approach to ensure uniqueness
    # Use the original file name for the hash to maintain consistency
    file_hash = hashlib.sha256(file_name.encode("utf-8")).hexdigest()

    # Calculate how much space we have for the readable part
    # Reserve space for hash (64 chars) + underscore separator (1 char)
    readable_part_max_length = max(0, max_file_name_length - HASH_WITH_SEPARATOR_LENGTH)

    if readable_part_max_length > 0:
        # Use first part of sanitized name + hash to maintain some readability
        readable_part = sanitized_file_name[:readable_part_max_length]
        truncated_name = f"{readable_part}_{file_hash}"
    else:
        # If no space for readable part, just use hash
        truncated_name = file_hash

    return "/".join(prefix_and_tenant_parts + [truncated_name])
