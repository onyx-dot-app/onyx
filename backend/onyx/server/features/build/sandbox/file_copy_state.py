"""The copy generation of the background chat file copies into sandbox VMs
(`tools/tool_implementations/sandbox/file_copies.py`, whose docstring has
the rules): one per chat session. Each turn's copy and each chat purge take
the next one. It expires COPY_STATE_SECONDS after the chat's last copy or
purge.
"""

from uuid import UUID

_GENERATION_PREFIX = "sandbox_fc:file_copy_generation:"
COPY_STATE_SECONDS = 30 * 24 * 3600


def copy_generation_key(session_id: UUID) -> str:
    return f"{_GENERATION_PREFIX}{session_id}"
