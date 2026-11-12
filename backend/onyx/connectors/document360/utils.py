from datetime import datetime


def parse_document360_datetime(value: str) -> datetime:
    """Parse a Document360 ISO-8601 timestamp.

    Document360 returns timestamps with a trailing ``Z`` but the fractional
    seconds part is optional (e.g. ``2025-02-03T14:06:14Z`` vs
    ``2025-04-24T09:23:54.494Z``).  ``datetime.fromisoformat`` on Python
    3.11+ handles both forms and returns a timezone-aware datetime.
    """
    return datetime.fromisoformat(value)


def flatten_child_categories(category: dict) -> list[dict]:
    if not category["child_categories"]:
        return [category]
    else:
        flattened_categories = [category]
        for child_category in category["child_categories"]:
            flattened_categories.extend(flatten_child_categories(child_category))
        return flattened_categories
