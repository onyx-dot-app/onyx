import sys
from typing import TypeVar

T = TypeVar("T", dict, list, tuple, set, frozenset)


def deep_getsizeof(obj: T, seen: set[int] | None = None) -> int:
    """Recursively sum size of objects, handling circular references."""
    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return 0  # Prevent infinite recursion for circular references

    seen.add(obj_id)
    size = sys.getsizeof(obj)

    if isinstance(obj, dict):
        size += sum(
            deep_getsizeof(k, seen) + deep_getsizeof(v, seen) for k, v in obj.items()
        )
    elif isinstance(obj, (list, tuple, set, frozenset)):
        size += sum(deep_getsizeof(i, seen) for i in obj)

    return size
