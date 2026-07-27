"""Release freed native memory back to the OS (Linux/glibc).

glibc retains freed allocations in its arenas, so a long-lived worker
churning through a multi-hour connector crawl ratchets its RSS until the
pod OOMs even though the live Python heap stays flat. Periodic
malloc_trim(0) returns that memory to the kernel.
"""

import ctypes
import sys

from onyx.utils.logger import setup_logger

logger = setup_logger()

_libc: ctypes.CDLL | None = None
_unavailable = False


def release_freed_native_memory() -> bool:
    """Return glibc-retained freed memory to the OS. No-op off Linux."""
    global _libc, _unavailable

    if sys.platform != "linux" or _unavailable:
        return False

    try:
        if _libc is None:
            _libc = ctypes.CDLL(None)
        _libc.malloc_trim(0)
        return True
    except Exception:
        _unavailable = True
        logger.warning("malloc_trim unavailable; not retrying", exc_info=True)
        return False
