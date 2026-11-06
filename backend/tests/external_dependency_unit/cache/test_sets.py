"""Cleanup sets retain concurrent work until each member is removed."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from onyx.cache.interface import CacheBackend


def test_set_members_are_atomic_bounded_and_isolated_by_name(
    cache: CacheBackend,
) -> None:
    key = f"pending:{uuid4().hex}"
    nested_key = key + ":nested"
    members = [str(index) for index in range(20)]
    try:
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda member: cache.set_add(key, member), members))
        cache.set_add(key, members[0])
        cache.set_add(nested_key, b"separate")
        assert len(cache.set_members(key, limit=5)) == 5
        assert set(cache.set_members(key, limit=100)) == {
            member.encode() for member in members
        }
        assert cache.set_members(nested_key, limit=100) == [b"separate"]
        cache.set_remove(key, members[0])
        cache.set_remove(key, members[0])
        assert set(cache.set_members(key, limit=100)) == {
            member.encode() for member in members[1:]
        }
        with pytest.raises(ValueError, match="positive"):
            cache.set_members(key, limit=0)
    finally:
        for member in members:
            cache.set_remove(key, member)
        cache.set_remove(nested_key, b"separate")
    assert cache.set_members(key, limit=100) == []
