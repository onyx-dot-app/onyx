"""The direct Redis check counts imports of `redis`, this repo's client
accessors and Lua script calls, honors the allow marker, and fails when a
file's count rises above the committed baseline."""

from pathlib import Path

import pytest
from lint import check_no_direct_redis
from lint.check_no_direct_redis import Use


def _whats(source: str) -> list[str]:
    return [use.what for use in check_no_direct_redis.find_direct_redis_uses(source)]


# Shapes taken from application code.
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import redis", ["import of `redis`"]),
        ("import redis.asyncio as aioredis", ["import of `redis.asyncio`"]),
        ("from redis import Redis", ["import of `redis.Redis`"]),
        # Types and exceptions count too: backend-neutral code needs neither.
        ("from redis.lock import Lock as RedisLock", ["import of `redis.lock.Lock`"]),
        (
            "from redis.exceptions import ConnectionError as RedisConnectionError",
            ["import of `redis.exceptions.ConnectionError`"],
        ),
        (
            "from onyx.redis.redis_pool import get_redis_client\n"
            "r = get_redis_client()\n",
            ["import of `get_redis_client`", "call of `get_redis_client`"],
        ),
        (
            "from onyx.redis.redis_pool import get_redis_client as grc\n"
            "r = grc(tenant_id=tenant_id)\n",
            ["import of `get_redis_client`", "call of `get_redis_client`"],
        ),
        (
            "from onyx.redis import redis_pool\n"
            "r = redis_pool.get_shared_redis_client()\n",
            ["import of `redis_pool`", "call of `get_shared_redis_client`"],
        ),
        (
            "from onyx.redis.redis_pool import get_async_redis_connection\n"
            "async def f() -> None:\n"
            "    redis = await get_async_redis_connection()\n",
            [
                "import of `get_async_redis_connection`",
                "call of `get_async_redis_connection`",
            ],
        ),
        (
            "from onyx.redis.tenant_redis_client import TenantRedisClient",
            ["import of `TenantRedisClient`"],
        ),
        (
            "from onyx.redis.lock_context import redis_shared_lock\n"
            "with redis_shared_lock(name, timeout=5):\n"
            "    pass\n",
            ["import of `redis_shared_lock`", "call of `redis_shared_lock`"],
        ),
        (
            "wait_ms = self._redis.eval(_ACQUIRE_SCRIPT, keys=[_WINDOW_KEY], args=[1])",
            ["Lua script call `eval`"],
        ),
        (
            "redis_client.eval(_RELEASE_IF_OWNED, [CHAIN_ACTIVE], [chain_token])",
            ["Lua script call `eval`"],
        ),
        ("r.eval(script, 1, key, value)", ["Lua script call `eval`"]),
        # A module import reaches every accessor through an attribute.
        (
            "import onyx.redis.redis_pool as pool\n"
            "r = pool.redis_pool.get_client(tenant_id)\n",
            ["import of module `onyx.redis.redis_pool`"],
        ),
        ("import onyx.redis", ["import of module `onyx.redis`"]),
        ("from onyx import redis", ["import of module `onyx.redis`"]),
        (
            "from onyx.redis import tenant_redis_client",
            ["import of module `onyx.redis.tenant_redis_client`"],
        ),
        (
            "from ...redis.redis_pool import get_redis_client\nr = get_redis_client()\n",
            ["import of `get_redis_client`", "call of `get_redis_client`"],
        ),
        ("sha = r.register_script(SCRIPT)", ["Lua script call `register_script`"]),
        ("r.evalsha(sha, 1, key)", ["Lua script call `evalsha`"]),
    ],
)
def test_direct_uses_are_found(source: str, expected: list[str]) -> None:
    assert _whats(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "from onyx.cache.factory import get_cache_backend\n"
        "cache = get_cache_backend()\n"
        'cache.set("k", b"v", ex=60)\n',
        # Redis-backed objects in `onyx.redis` are not client accessors.
        "from onyx.redis.redis_connector import RedisConnector",
        "from onyx.redis.redis_pool import retrieve_auth_token_data_from_redis",
        "from onyx.configs.app_configs import REDIS_HOST",
        "from onyx.background.celery.celery_redis import celery_get_broker_client",
        "from .models import RedisSettings",
        "from . import redis_helpers",
        # Another library's `eval`.
        "model.eval()",
        'df.eval("a + b")',
        "provider.eval(task=task, configuration=configuration, data=data)",
        # A local function with an accessor's name.
        "def get_redis_client() -> None: ...\nget_redis_client()\n",
    ],
)
def test_other_code_is_not_found(source: str) -> None:
    assert _whats(source) == []


def test_allow_marker_exempts_its_line() -> None:
    source = (
        "from onyx.redis.redis_pool import (\n"
        "    get_redis_client,  # no-direct-redis: allow Redis stream, no cache state\n"
        "    get_redis_replica_client,\n"
        ")\n"
        "r = get_redis_client()  # no-direct-redis: allow Redis stream\n"
        "replica = get_redis_replica_client()\n"
    )
    assert check_no_direct_redis.find_direct_redis_uses(source) == [
        Use(3, "import of `get_redis_replica_client`"),
        Use(6, "call of `get_redis_replica_client`"),
    ]


def test_allow_marker_on_the_comment_line_above() -> None:
    source = (
        "# no-direct-redis: allow session store for AUTH_BACKEND=redis\n"
        "from onyx.redis.redis_pool import get_async_redis_connection\n"
        "\n"
        "async def f() -> None:\n"
        "    # no-direct-redis: allow session store for AUTH_BACKEND=redis\n"
        "    redis = await get_async_redis_connection()\n"
        "    x = 1  # no-direct-redis: allow a marker on other code does not count\n"
        "    other = await get_async_redis_connection()\n"
    )
    assert check_no_direct_redis.find_direct_redis_uses(source) == [
        Use(8, "call of `get_async_redis_connection`"),
    ]


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("backend/onyx/redis/redis_pool.py", True),
        ("backend/onyx/cache/redis_backend.py", True),
        ("backend/onyx/background/celery/celery_redis.py", True),
        ("backend/onyx/background/celery/tasks/pruning/tasks.py", True),
        ("backend/ee/onyx/background/celery/tasks/cloud/tasks.py", True),
        ("backend/onyx/background/indexing/run_docfetching.py", True),
        ("backend/onyx/indexing/adapters/document_indexing_adapter.py", False),
        ("backend/onyx/redis_helpers.py", False),
        ("backend/ee/onyx/redis/thing.py", False),
    ],
)
def test_allowed_locations(path: str, allowed: bool) -> None:
    assert (check_no_direct_redis.allowed_reason(path) is not None) == allowed


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


_DIRECT = "from onyx.redis.redis_pool import get_redis_client\nr = get_redis_client()\n"


def test_scan_skips_allowed_locations_and_clean_files(tmp_path: Path) -> None:
    _write(tmp_path, "backend/onyx/redis/redis_pool.py", "import redis\n")
    _write(tmp_path, "backend/onyx/cache/redis_backend.py", _DIRECT)
    _write(tmp_path, "backend/onyx/server/clean.py", "x = 1\n")
    _write(tmp_path, "backend/onyx/server/dirty.py", _DIRECT)
    # No lowercase `redis` in the source.
    _write(tmp_path, "backend/onyx/server/upper.py", "p = pool.RedisPool()\n")
    _write(tmp_path, "backend/tests/unit/test_x.py", _DIRECT)

    found, unparsed = check_no_direct_redis.scan_tree(tmp_path)

    assert unparsed == []
    assert {path: len(uses) for path, uses in found.items()} == {
        "backend/onyx/server/dirty.py": 2,
        "backend/onyx/server/upper.py": 1,
    }


def test_new_file_and_raised_count_fail() -> None:
    found = {
        "backend/onyx/new.py": [Use(1, "import of `redis`")],
        "backend/onyx/old.py": [Use(1, "a"), Use(2, "b"), Use(3, "c")],
        "backend/onyx/same.py": [Use(1, "a")],
    }
    baseline = {"backend/onyx/old.py": 2, "backend/onyx/same.py": 1}

    failures, stale = check_no_direct_redis.compare(found, baseline)

    assert failures[0] == "backend/onyx/new.py: 1 direct Redis uses, baseline allows 0"
    assert "  backend/onyx/new.py:1: import of `redis`" in failures
    assert "backend/onyx/old.py: 3 direct Redis uses, baseline allows 2" in failures
    assert not any("same.py" in failure for failure in failures)
    assert stale == []


def test_lowered_count_is_reported_as_stale() -> None:
    found = {"backend/onyx/old.py": [Use(1, "a")]}
    baseline = {"backend/onyx/old.py": 2, "backend/onyx/gone.py": 1}

    failures, stale = check_no_direct_redis.compare(found, baseline)

    assert failures == []
    assert stale == [
        "backend/onyx/gone.py: baseline 1, now 0",
        "backend/onyx/old.py: baseline 2, now 1",
    ]


def test_baseline_round_trips() -> None:
    found = {"backend/onyx/b.py": [Use(1, "a")], "backend/onyx/a.py": [Use(1, "a")] * 3}
    text = check_no_direct_redis.format_baseline(found)

    path_counts = {
        line.split(maxsplit=1)[1]: int(line.split(maxsplit=1)[0])
        for line in text.splitlines()
        if not line.startswith("#")
    }

    assert path_counts == {"backend/onyx/a.py": 3, "backend/onyx/b.py": 1}


def test_fix_message_names_the_cache_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path, "backend/onyx/server/dirty.py", _DIRECT)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("# header\n")
    monkeypatch.setattr(check_no_direct_redis, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_no_direct_redis, "BASELINE_PATH", baseline)

    assert check_no_direct_redis.main([]) == 1
    output = capsys.readouterr().out
    assert "backend/onyx/server/dirty.py:2: call of `get_redis_client`" in output
    assert "get_cache_backend()" in output
    assert "get_shared_cache_backend()" in output
    assert "both Redis and PostgreSQL implementations" in output

    # The refresh command does not accept the new use either.
    assert check_no_direct_redis.main(["--write-baseline"]) == 1
    assert "The baseline cannot rise" in capsys.readouterr().out
    assert baseline.read_text() == "# header\n"


def test_write_baseline_lowers_counts_and_makes_the_first_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "backend/onyx/server/dirty.py", _DIRECT)
    baseline = tmp_path / "baseline.txt"
    monkeypatch.setattr(check_no_direct_redis, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_no_direct_redis, "BASELINE_PATH", baseline)

    assert check_no_direct_redis.main([]) == 1
    assert check_no_direct_redis.main(["--write-baseline"]) == 0
    assert check_no_direct_redis.read_baseline(baseline) == {
        "backend/onyx/server/dirty.py": 2
    }

    _write(tmp_path, "backend/onyx/server/dirty.py", "x = 1\n")
    assert check_no_direct_redis.main([]) == 1
    assert check_no_direct_redis.main(["--write-baseline"]) == 0
    assert check_no_direct_redis.read_baseline(baseline) == {}
    assert check_no_direct_redis.main([]) == 0


def test_unparsed_file_keeps_its_baseline_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old system python3 cannot parse new syntax. The file is not counted."""
    _write(tmp_path, "backend/onyx/server/new_syntax.py", "import redis\ndef f(:\n")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("1 backend/onyx/server/new_syntax.py\n")
    monkeypatch.setattr(check_no_direct_redis, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_no_direct_redis, "BASELINE_PATH", baseline)

    assert check_no_direct_redis.main([]) == 0
    assert check_no_direct_redis.main(["--write-baseline"]) == 1


def test_current_tree_matches_the_committed_baseline() -> None:
    found, unparsed = check_no_direct_redis.scan_tree(check_no_direct_redis.REPO_ROOT)
    assert unparsed == []
    baseline = check_no_direct_redis.read_baseline(check_no_direct_redis.BASELINE_PATH)
    assert check_no_direct_redis.compare(found, baseline) == ([], [])
