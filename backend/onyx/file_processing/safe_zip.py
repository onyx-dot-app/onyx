"""Bounded zip-extraction helpers for upload endpoints.

Decompression on the api_server happens in-process before files are forwarded
to object storage. Any zip-handling endpoint that calls ``zipfile.ZipFile.read``
materialises the entire entry into RAM, which can exhaust memory if the entry
expands far beyond what the central directory's ``file_size`` field claims —
that field is attacker-controlled and must never be trusted as a safety
boundary.

``read_zip_entry_bounded`` decompresses one entry through ``zipfile.ZipFile.open``
in fixed-size chunks, counting the bytes actually produced and aborting as
soon as the running total would exceed ``max_bytes``. The caller chooses what
to do on overflow: connector uploads abort the whole request, user-library
uploads skip the offending entry.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

ZIP_READ_CHUNK_BYTES = 1024 * 1024


def read_zip_entry_bounded(
    zf: zipfile.ZipFile,
    name: str | zipfile.ZipInfo,
    max_bytes: int,
) -> bytes | None:
    """Stream-decompress a single zip entry with a hard byte cap.

    Returns the decompressed bytes when the entry fits within ``max_bytes``,
    or ``None`` when it would exceed it (no full buffer is held in that case;
    decompression stops at the first chunk that pushes the running total over
    the cap).
    """
    out = BytesIO()
    bytes_read = 0
    with zf.open(name, "r") as entry:
        while True:
            chunk = entry.read(ZIP_READ_CHUNK_BYTES)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                return None
            out.write(chunk)
    return out.getvalue()
