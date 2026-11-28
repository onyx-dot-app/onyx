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


def test_set_contains_and_replace(cache: CacheBackend) -> None:
    key = f"gated:{uuid4().hex}"
    other_key = key + ":other"
    try:
        assert cache.set_contains(key, "a") is False
        cache.set_add(key, "a")
        cache.set_add(other_key, "kept")
        assert cache.set_contains(key, "a") is True
        assert cache.set_contains(key, b"a") is True
        assert cache.set_contains(key, "b") is False

        cache.set_replace(key, ["b", "c", "c"])
        assert set(cache.set_members(key, limit=100)) == {b"b", b"c"}
        assert cache.set_contains(key, "a") is False
        assert cache.set_contains(key, "c") is True
        assert cache.set_members(other_key, limit=100) == [b"kept"]

        many = [str(index) for index in range(2500)]
        cache.set_replace(key, many)
        assert len(cache.set_members(key, limit=5000)) == 2500
        assert cache.set_contains(key, "2499") is True

        cache.set_replace(key, [])
        assert cache.set_members(key, limit=100) == []
    finally:
        cache.set_replace(key, [])
        cache.set_replace(other_key, [])


def test_concurrent_replacements_do_not_merge(cache: CacheBackend) -> None:
    key = f"gated:{uuid4().hex}"
    replacements = [[f"a{index}", "shared"] for index in range(12)]
    try:
        with ThreadPoolExecutor(max_workers=6) as workers:
            list(
                workers.map(
                    lambda members: cache.set_replace(key, members), replacements
                )
            )
        members = set(cache.set_members(key, limit=100))
        assert members in [
            {member.encode() for member in replacement} for replacement in replacements
        ]
    finally:
        cache.set_replace(key, [])
