import base64
from uuid import UUID


def make_sharing_token(guid: str, header: bytes = b"!\x00") -> str:
    """Build a SharePoint sharing-link token: header + item GUID (little-endian)
    + opaque tail."""
    raw = header + UUID(guid).bytes_le + b"\x01" + bytes(16)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
