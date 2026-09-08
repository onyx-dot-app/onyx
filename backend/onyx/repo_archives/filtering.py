"""Rewriting a repository archive without some of its files.

Consumers that hand a whole repository to something other than the indexing
pipeline need the same exclusions the pipeline applies. Filtering the archive
rather than the extracted tree keeps the exclusion ahead of anything that
reads the files.
"""

import tarfile
from collections.abc import Callable
from pathlib import Path

from onyx.utils.logger import setup_logger

logger = setup_logger()


def write_filtered_archive(
    source: Path, dest: Path, exclude: Callable[[str], bool]
) -> int:
    """Copy the tar.gz at `source` to `dest`, dropping members whose path
    `exclude` accepts. Returns the number of members dropped.

    Both archives are streamed, so an archive far larger than memory costs
    one decompress/recompress pass and nothing else.
    """
    dropped = 0
    with (
        tarfile.open(source, mode="r|gz") as archive,
        tarfile.open(dest, mode="w|gz") as filtered,
    ):
        for member in archive:
            if exclude(member.name):
                dropped += 1
                continue
            content = archive.extractfile(member) if member.isreg() else None
            filtered.addfile(member, content)
    return dropped
