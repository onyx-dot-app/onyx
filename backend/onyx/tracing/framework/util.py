import hashlib
import uuid
from datetime import datetime
from datetime import timezone


def time_iso() -> str:
    """Return the current time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def gen_trace_id() -> str:
    """Generate a new trace ID."""
    return f"trace_{uuid.uuid4().hex}"


def gen_span_id() -> str:
    """Generate a new span ID."""
    return f"span_{uuid.uuid4().hex[:24]}"


def generate_deterministic_trace_id(chat_session_id: str, message_id: int) -> str:
    """Generate a deterministic 32-char hex trace_id from session and message.

    This function creates a deterministic trace_id by hashing the combination of
    chat_session_id and message_id. This allows us to reconstruct the trace_id
    without storing it in the database.

    Args:
        chat_session_id: The chat session UUID as a string
        message_id: The message ID (integer)

    Returns:
        A trace_id in the format "trace_{32_hex_chars}" where the hex part is
        a 32-character MD5 hash of "{chat_session_id}:{message_id}"
    """
    input_str = f"{chat_session_id}:{message_id}"
    hash_bytes = hashlib.md5(input_str.encode()).digest()
    hex_hash = hash_bytes.hex()  # 32-char hex string
    return f"trace_{hex_hash}"
