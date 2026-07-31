"""Log collection helpers for the admin log-export feature.

Shared by the api_server download endpoint today and intended to be reused by
per-worker celery collector tasks once fan-out collection lands.
"""

import socket
import tempfile
import zipfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from onyx import __version__
from onyx.file_store.constants import MAX_IN_MEMORY_SIZE
from onyx.utils.platform_utils import is_running_in_container

README_FILE_NAME = "README.txt"

# Matches the base log files plus their rotations (e.g. ``onyx_debug.log.3``).
LOG_FILE_GLOB = "*.log*"

# Known Debian package-manager logs at the top level of ``/var/log`` in the
# backend image; build-time noise with no diagnostic value. Exact names only,
# so unknown system logs fail open: they are collected as noise rather than
# risking dropped Onyx logs.
EXCLUDED_SYSTEM_LOG_FILE_NAMES = frozenset(
    {"dpkg.log", "alternatives.log", "fontconfig.log"}
)

SENSITIVE_DATA_WARNING = (
    "WARNING: Log files may contain sensitive data such as user emails, "
    "document titles, search queries, URLs, and error payloads. Review the "
    "contents before sharing them outside your organization."
)


def get_default_log_directories() -> list[Path]:
    """Returns the directories this process writes file logs to.

    Mirrors the path selection in ``onyx.utils.logger._add_file_handlers``:
    containers log under ``/var/log/onyx``, dev processes under ``./log``.
    """
    if is_running_in_container():
        return [Path("/var/log/onyx")]
    return [Path("./log")]


def _find_log_files(
    log_directories: Sequence[Path],
    shallow_log_directories: Sequence[Path] = (),
) -> list[Path]:
    """Returns all log files under the given directories, without duplicates.

    Directories in ``log_directories`` are searched recursively; those in
    ``shallow_log_directories`` only at their top level. Files named in
    ``EXCLUDED_SYSTEM_LOG_FILE_NAMES`` are skipped.
    """
    seen: set[Path] = set()
    log_files: list[Path] = []
    searches = [(directory, True) for directory in log_directories] + [
        (directory, False) for directory in shallow_log_directories
    ]
    for directory, recursive in searches:
        if not directory.is_dir():
            continue
        root = directory.resolve()
        glob = directory.rglob if recursive else directory.glob
        for path in sorted(glob(LOG_FILE_GLOB)):
            if not path.is_file():
                continue
            if path.name in EXCLUDED_SYSTEM_LOG_FILE_NAMES:
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                # A planted ``*.log*`` symlink pointing outside the log
                # directory would otherwise pull arbitrary server-readable
                # files into the archive.
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            log_files.append(resolved)
    return log_files


def _build_readme(
    scope_note: str,
    included: list[tuple[str, int]],
    skipped: list[tuple[str, str]],
) -> str:
    """Builds the README.txt content describing the export."""
    lines = [
        "Onyx log export",
        "===============",
        "",
        SENSITIVE_DATA_WARNING,
        "",
        scope_note,
        "",
        f"Onyx version: {__version__}",
        f"Hostname: {socket.gethostname()}",
        f"Collected at (UTC): {datetime.now(tz=timezone.utc).isoformat()}",
        "",
    ]

    if included:
        lines.append("Included files:")
        lines.extend(f"  {name} ({size} bytes)" for name, size in included)
    else:
        lines.append(
            "No log files were found. This process may be logging to stdout "
            "only (e.g. a read-only container or a deployment with "
            "LOG_TO_FILE=false)."
        )

    if skipped:
        lines.append("")
        lines.append("Skipped files (unreadable):")
        lines.extend(f"  {name}: {error}" for name, error in skipped)

    lines.append("")
    return "\n".join(lines)


def build_log_zip(
    log_directories: Sequence[Path],
    scope_note: str,
    shallow_log_directories: Sequence[Path] = (),
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Collects every log file under the given directories into a zip.

    The archive always contains a ``README.txt`` (sensitive-data warning, scope
    note, and the list of collected files); log files are stored under their
    absolute path minus the leading slash. Unreadable files are noted in the
    README instead of failing the export, and known system log files (e.g.
    ``dpkg.log``) are excluded.

    Args:
        log_directories: Directories to search recursively for log files
            (``*.log*``, so rotations are included). Missing directories are
            skipped; files reachable from more than one entry are only added
            once.
        scope_note: Human-readable description of what this export covers,
            included verbatim in the README.
        shallow_log_directories: Directories to search without recursing into
            subdirectories (e.g. ``/var/log``, where only the top-level
            supervisord-captured logs are wanted). Same skip and dedupe rules
            as ``log_directories``.

    Returns:
        A spooled temporary file containing the zip archive, positioned at
        offset 0. The caller owns the file and is responsible for closing it.
    """
    log_files = _find_log_files(log_directories, shallow_log_directories)

    included: list[tuple[str, int]] = []
    skipped: list[tuple[str, str]] = []

    zip_buffer: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE
    )
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path in log_files:
            arcname = str(path).removeprefix("/")
            try:
                size = path.stat().st_size
                zip_file.write(path, arcname)
                included.append((arcname, size))
            except OSError as e:
                skipped.append((arcname, str(e)))

        zip_file.writestr(
            README_FILE_NAME, _build_readme(scope_note, included, skipped)
        )

    zip_buffer.seek(0)
    return zip_buffer
