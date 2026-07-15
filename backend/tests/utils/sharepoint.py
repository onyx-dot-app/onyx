import base64
from uuid import UUID


def make_sharing_token(guid: str, header: bytes = b"!\x00") -> str:
    """Build a SharePoint sharing-link token: header + item GUID (little-endian)
    + opaque tail."""
    raw = header + UUID(guid).bytes_le + b"\x01" + bytes(16)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_drive_item_id(guid: str, drive_hash: bytes = b"\x8d\xa9\x4d\xbd") -> str:
    """Build a Graph drive-item Document.id: "01" + base32(drive hash + GUID
    little-endian)."""
    return "01" + base64.b32encode(drive_hash + UUID(guid).bytes_le).decode()
