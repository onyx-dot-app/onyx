import fnmatch


def is_path_excluded(item_path: str, excluded_path_patterns: list[str]) -> bool:
    """Check if a path matches any of the exclusion glob patterns.

    item_path is a relative path, e.g. "Engineering/API/report.docx".
    Matches are attempted against the full path and the filename alone so that
    patterns like "*.tmp" match files at any depth.
    """
    filename = item_path.rsplit("/", 1)[-1] if "/" in item_path else item_path
    for pattern in excluded_path_patterns:
        if fnmatch.fnmatch(item_path, pattern) or fnmatch.fnmatch(filename, pattern):
            return True
    return False
