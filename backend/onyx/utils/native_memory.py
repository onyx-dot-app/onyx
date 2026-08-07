"""Release freed native memory back to the OS (Linux).

Long-lived workers churning through multi-hour connector crawls accumulate
freed-but-retained allocator memory, ratcheting RSS until the pod OOMs even
though the live Python heap stays flat. The backend image LD_PRELOADs
jemalloc (see backend/Dockerfile), so the release goes through jemalloc's
mallctl (epoch bump + purge of all arenas); glibc malloc_trim(0) is the
fallback when jemalloc is absent (e.g. bare-metal dev installs).
"""

import ctypes
import sys

from onyx.utils.logger import setup_logger

logger = setup_logger()

# jemalloc's MALLCTL_ARENAS_ALL sentinel (jemalloc/jemalloc.h)
_MALLCTL_ARENAS_ALL = 4096

_jemalloc: ctypes.CDLL | None = None
_glibc: ctypes.CDLL | None = None
_unavailable = False


def _load() -> None:
    global _jemalloc, _glibc, _unavailable
    try:
        _jemalloc = ctypes.CDLL("libjemalloc.so.2")
        _jemalloc.mallctl  # raises AttributeError if the symbol is missing
        return
    except (OSError, AttributeError):
        _jemalloc = None
    try:
        _glibc = ctypes.CDLL(None)
        _glibc.malloc_trim
    except (OSError, AttributeError):
        _glibc = None
        _unavailable = True
        logger.warning("no jemalloc or glibc malloc_trim available; not retrying")


def release_freed_native_memory() -> bool:
    """Return allocator-retained freed memory to the OS. No-op off Linux."""
    global _unavailable

    if sys.platform != "linux" or _unavailable:
        return False

    if _jemalloc is None and _glibc is None:
        _load()

    try:
        if _jemalloc is not None:
            # advance the epoch so the purge sees current state, then purge
            # dirty+muzzy pages from every arena
            epoch = ctypes.c_uint64(1)
            epoch_sz = ctypes.c_size_t(ctypes.sizeof(epoch))
            _jemalloc.mallctl(
                b"epoch",
                ctypes.byref(epoch),
                ctypes.byref(epoch_sz),
                ctypes.byref(epoch),
                epoch_sz,
            )
            _jemalloc.mallctl(
                f"arena.{_MALLCTL_ARENAS_ALL}.purge".encode(), None, None, None, 0
            )
            return True
        if _glibc is not None:
            _glibc.malloc_trim(0)
            return True
    except Exception:
        logger.warning("native memory release failed; not retrying", exc_info=True)

    _unavailable = True
    return False
