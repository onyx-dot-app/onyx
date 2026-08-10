"""Release freed native memory back to the OS (Linux).

The backend image LD_PRELOADs jemalloc (see backend/Dockerfile), where the
release is a mallctl epoch bump + purge of all arenas; glibc `malloc_trim(0)`
is the fallback for non-jemalloc installs. Without this, long crawls ratchet
worker RSS with freed-but-retained allocator memory until the pod OOMs.
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
        _jemalloc.mallctl
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
            # advance the epoch so the purge sees current state
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
