"""Composition-based tenant-aware Redis client.

Replaces the old ``__getattribute__``-based ``TenantRedis`` (a ``redis.Redis``
subclass that wrapped a hand-maintained allowlist of methods) with an
explicit, hand-written client built by composition. Every public method that
touches a key prefixes it deliberately. Calling a Redis method that is not
exposed here is a typing error, not a silent cross-tenant write.

See `plans/2026-05-07-tenant-redis-composition-refactor.md` for context.
"""

# PEP 563 — annotations are stored as strings so that ``def set`` and
# ``def hset`` etc. don't shadow the builtin types they reference in
# return annotations like ``-> set[bytes]``.
from __future__ import annotations

from collections.abc import Generator
from collections.abc import Mapping
from typing import Any
from typing import cast

import redis
from redis.client import Pipeline
from redis.lock import Lock as RedisLock

KeyArg = str | bytes | memoryview

# `set` is shadowed inside the class body by ``def set``, so a return-type
# annotation like ``-> set[bytes]`` resolves to the method instead of the
# builtin. Alias it once outside the class so static checkers (and ``ty``)
# pick the right thing up.
_BuiltinSet = set


class TenantRedisClient:
    """Tenant-aware Redis client built by composition.

    ``prefix`` is either a tenant id (per-tenant isolation) or the shared
    namespace prefix (``DEFAULT_REDIS_PREFIX``, used for cross-tenant data).
    """

    def __init__(self, prefix: str, client: redis.Redis) -> None:
        self._prefix: str = prefix
        # Typed as ``Any`` internally because redis-py's type stubs are
        # inconsistent (some commands declare ``name: str`` even though
        # ``bytes`` and ``memoryview`` work at runtime). The public API of
        # this class accepts the wider ``KeyArg`` union — strict types stay
        # on the boundary that callers actually see.
        self._r: Any = client

    @property
    def tenant_id(self) -> str:
        """The tenant id (or shared namespace prefix) used for keys."""
        return self._prefix

    @property
    def raw_client(self) -> redis.Redis:
        """Escape hatch for code that genuinely needs the unwrapped client.

        Used by the lock-diagnostic helper, which inspects a `Lock` whose
        `name` attribute already carries the prefix and so must round-trip
        through a non-prefixing client. Prefer adding a method on this class
        over reaching for this.
        """
        return self._r

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prefix_key(self, key: KeyArg) -> KeyArg:
        """Idempotently prepend the tenant prefix to a key."""
        prefix = f"{self._prefix}:"
        if isinstance(key, str):
            return key if key.startswith(prefix) else prefix + key
        if isinstance(key, bytes):
            prefix_bytes = prefix.encode()
            return key if key.startswith(prefix_bytes) else prefix_bytes + key
        if isinstance(key, memoryview):
            prefix_bytes = prefix.encode()
            key_bytes = key.tobytes()
            if key_bytes.startswith(prefix_bytes):
                return key
            return memoryview(prefix_bytes + key_bytes)
        raise TypeError(f"Unsupported key type: {type(key)}")

    def _strip_prefix_bytes(self, key: bytes) -> bytes:
        prefix_bytes = f"{self._prefix}:".encode()
        if key.startswith(prefix_bytes):
            return key[len(prefix_bytes) :]
        return key

    # ------------------------------------------------------------------
    # Strings / generic
    # ------------------------------------------------------------------

    def get(self, name: KeyArg) -> bytes | None:
        return cast("bytes | None", self._r.get(self._prefix_key(name)))

    def set(
        self,
        name: KeyArg,
        value: str | bytes | int | float,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
        keepttl: bool = False,
        get: bool = False,
        exat: int | None = None,
        pxat: int | None = None,
    ) -> Any:
        return self._r.set(
            self._prefix_key(name),
            value,
            ex=ex,
            px=px,
            nx=nx,
            xx=xx,
            keepttl=keepttl,
            get=get,
            exat=exat,
            pxat=pxat,
        )

    def setex(
        self,
        name: KeyArg,
        time: int,
        value: str | bytes | int | float,
    ) -> bool:
        return cast(bool, self._r.setex(self._prefix_key(name), time, value))

    def delete(self, *names: KeyArg) -> int:
        prefixed = [self._prefix_key(n) for n in names]
        return cast(int, self._r.delete(*prefixed))

    def exists(self, *names: KeyArg) -> int:
        prefixed = [self._prefix_key(n) for n in names]
        return cast(int, self._r.exists(*prefixed))

    def incr(self, name: KeyArg, amount: int = 1) -> int:
        return cast(int, self._r.incr(self._prefix_key(name), amount))

    def incrby(self, name: KeyArg, amount: int = 1) -> int:
        return cast(int, self._r.incrby(self._prefix_key(name), amount))

    def getset(self, name: KeyArg, value: str | bytes | int | float) -> bytes | None:
        return cast("bytes | None", self._r.getset(self._prefix_key(name), value))

    # ------------------------------------------------------------------
    # Hash
    # ------------------------------------------------------------------

    def hset(
        self,
        name: KeyArg,
        key: str | bytes | None = None,
        value: str | bytes | int | float | None = None,
        mapping: Mapping[Any, Any] | None = None,
        items: list[Any] | None = None,
    ) -> int:
        return cast(
            int,
            self._r.hset(
                self._prefix_key(name),
                key=key,
                value=value,
                mapping=mapping,
                items=items,
            ),
        )

    def hget(self, name: KeyArg, key: str | bytes) -> bytes | None:
        return cast("bytes | None", self._r.hget(self._prefix_key(name), key))

    def hmget(
        self,
        name: KeyArg,
        keys: list[str] | list[bytes],
        *args: str | bytes,
    ) -> list[bytes | None]:
        return cast(
            "list[bytes | None]",
            self._r.hmget(self._prefix_key(name), keys, *args),
        )

    def hdel(self, name: KeyArg, *keys: str | bytes) -> int:
        return cast(int, self._r.hdel(self._prefix_key(name), *keys))

    def hexists(self, name: KeyArg, key: str | bytes) -> bool:
        return cast(bool, self._r.hexists(self._prefix_key(name), key))

    # ------------------------------------------------------------------
    # Set
    # ------------------------------------------------------------------

    def smembers(self, name: KeyArg) -> _BuiltinSet[bytes]:
        return cast("_BuiltinSet[bytes]", self._r.smembers(self._prefix_key(name)))

    def sismember(self, name: KeyArg, value: str | bytes | int | float) -> bool:
        return cast(bool, self._r.sismember(self._prefix_key(name), value))

    def sadd(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        return cast(int, self._r.sadd(self._prefix_key(name), *values))

    def srem(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        return cast(int, self._r.srem(self._prefix_key(name), *values))

    def scard(self, name: KeyArg) -> int:
        return cast(int, self._r.scard(self._prefix_key(name)))

    # ------------------------------------------------------------------
    # Sorted set
    # ------------------------------------------------------------------

    def zadd(
        self,
        name: KeyArg,
        mapping: Mapping[Any, float | int],
        nx: bool = False,
        xx: bool = False,
        ch: bool = False,
        incr: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> int:
        return cast(
            int,
            self._r.zadd(
                self._prefix_key(name),
                dict(mapping),
                nx=nx,
                xx=xx,
                ch=ch,
                incr=incr,
                gt=gt,
                lt=lt,
            ),
        )

    def zrange(
        self,
        name: KeyArg,
        start: int,
        end: int,
        desc: bool = False,
        withscores: bool = False,
        score_cast_func: Any = float,
    ) -> list[Any]:
        return cast(
            list,
            self._r.zrange(
                self._prefix_key(name),
                start,
                end,
                desc=desc,
                withscores=withscores,
                score_cast_func=score_cast_func,
            ),
        )

    def zrevrange(
        self,
        name: KeyArg,
        start: int,
        end: int,
        withscores: bool = False,
        score_cast_func: Any = float,
    ) -> list[Any]:
        return cast(
            list,
            self._r.zrevrange(
                self._prefix_key(name),
                start,
                end,
                withscores=withscores,
                score_cast_func=score_cast_func,
            ),
        )

    def zrangebyscore(
        self,
        name: KeyArg,
        min: float | int | str | bytes,
        max: float | int | str | bytes,
        start: int | None = None,
        num: int | None = None,
        withscores: bool = False,
        score_cast_func: Any = float,
    ) -> list[Any]:
        return cast(
            list,
            self._r.zrangebyscore(
                self._prefix_key(name),
                min,
                max,
                start=start,
                num=num,
                withscores=withscores,
                score_cast_func=score_cast_func,
            ),
        )

    def zremrangebyscore(
        self,
        name: KeyArg,
        min: float | int | str | bytes,
        max: float | int | str | bytes,
    ) -> int:
        return cast(int, self._r.zremrangebyscore(self._prefix_key(name), min, max))

    def zscore(self, name: KeyArg, value: str | bytes) -> float | None:
        return cast("float | None", self._r.zscore(self._prefix_key(name), value))

    def zcard(self, name: KeyArg) -> int:
        return cast(int, self._r.zcard(self._prefix_key(name)))

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def rpush(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        return cast(int, self._r.rpush(self._prefix_key(name), *values))

    def lindex(self, name: KeyArg, index: int) -> bytes | None:
        return cast("bytes | None", self._r.lindex(self._prefix_key(name), index))

    def _blpop_brpop(
        self,
        method_name: str,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        prefixed_keys: KeyArg | list[KeyArg]
        if isinstance(keys, (str, bytes, memoryview)):
            prefixed_keys = self._prefix_key(keys)
        else:
            prefixed_keys = [self._prefix_key(k) for k in keys]
        method = getattr(self._r, method_name)
        result = method(prefixed_keys, timeout=timeout)
        if result is None:
            return None
        key, value = result[0], result[1]
        if isinstance(key, bytes):
            key = self._strip_prefix_bytes(key)
        return (key, value)

    def blpop(
        self,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        return self._blpop_brpop("blpop", keys, timeout)

    def brpop(
        self,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        return self._blpop_brpop("brpop", keys, timeout)

    # ------------------------------------------------------------------
    # TTL family
    # ------------------------------------------------------------------

    def ttl(self, name: KeyArg) -> int:
        return cast(int, self._r.ttl(self._prefix_key(name)))

    def pttl(self, name: KeyArg) -> int:
        return cast(int, self._r.pttl(self._prefix_key(name)))

    def expire(
        self,
        name: KeyArg,
        time: int,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> bool:
        return cast(
            bool,
            self._r.expire(self._prefix_key(name), time, nx=nx, xx=xx, gt=gt, lt=lt),
        )

    def expireat(
        self,
        name: KeyArg,
        when: int,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> bool:
        return cast(
            bool,
            self._r.expireat(self._prefix_key(name), when, nx=nx, xx=xx, gt=gt, lt=lt),
        )

    def pexpire(
        self,
        name: KeyArg,
        time: int,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> bool:
        return cast(
            bool,
            self._r.pexpire(self._prefix_key(name), time, nx=nx, xx=xx, gt=gt, lt=lt),
        )

    def pexpireat(
        self,
        name: KeyArg,
        when: int,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> bool:
        return cast(
            bool,
            self._r.pexpireat(self._prefix_key(name), when, nx=nx, xx=xx, gt=gt, lt=lt),
        )

    # ------------------------------------------------------------------
    # Locks
    #
    # The returned `redis.lock.Lock` operates on the prefixed name internally
    # (its `name` attribute is the prefixed string). None of the lock's own
    # methods take a key argument, so this is safe — but callers should treat
    # `lock.name` as already-prefixed if they ever inspect it.
    # ------------------------------------------------------------------

    def lock(
        self,
        name: str,
        timeout: float | None = None,
        sleep: float = 0.1,
        blocking: bool = True,
        blocking_timeout: float | None = None,
        thread_local: bool = True,
    ) -> RedisLock:
        return self._r.lock(
            cast(str, self._prefix_key(name)),
            timeout=timeout,
            sleep=sleep,
            blocking=blocking,
            blocking_timeout=blocking_timeout,
            thread_local=thread_local,
        )

    def create_lock(
        self,
        name: str,
        timeout: float | None = None,
        sleep: float = 0.1,
        blocking: bool = True,
        blocking_timeout: float | None = None,
        thread_local: bool = True,
    ) -> RedisLock:
        return self.lock(
            name,
            timeout=timeout,
            sleep=sleep,
            blocking=blocking,
            blocking_timeout=blocking_timeout,
            thread_local=thread_local,
        )

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan_iter(
        self,
        match: str | bytes | None = None,
        count: int | None = None,
        _type: str | None = None,
    ) -> Generator[bytes, None, None]:
        prefixed_match = self._prefix_key(match) if match is not None else None
        prefix_bytes = f"{self._prefix}:".encode()
        prefix_len = len(prefix_bytes)
        for key in self._r.scan_iter(match=prefixed_match, count=count, _type=_type):
            if isinstance(key, bytes) and key.startswith(prefix_bytes):
                yield key[prefix_len:]
            else:
                yield key

    def sscan_iter(
        self,
        name: KeyArg,
        match: str | bytes | None = None,
        count: int | None = None,
    ) -> Generator[bytes, None, None]:
        return cast(
            "Generator[bytes, None, None]",
            self._r.sscan_iter(self._prefix_key(name), match=match, count=count),
        )

    # ------------------------------------------------------------------
    # Scripting
    #
    # The signature is `(script, keys, args)` rather than the redis-py native
    # `(script, numkeys, *keys_and_args)` so callers can't accidentally cross
    # the key/arg boundary. `numkeys` is computed from `len(keys)`.
    # ------------------------------------------------------------------

    def eval(
        self,
        script: str,
        keys: list[str] | list[bytes],
        args: list[str] | list[bytes] | list[int] | list[float] | None = None,
    ) -> Any:
        prefixed_keys = [self._prefix_key(k) for k in keys]
        return self._r.eval(script, len(prefixed_keys), *prefixed_keys, *(args or []))

    def evalsha(
        self,
        sha: str,
        keys: list[str] | list[bytes],
        args: list[str] | list[bytes] | list[int] | list[float] | None = None,
    ) -> Any:
        prefixed_keys = [self._prefix_key(k) for k in keys]
        return self._r.evalsha(sha, len(prefixed_keys), *prefixed_keys, *(args or []))

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def pipeline(self, transaction: bool = True) -> "TenantRedisPipeline":
        return TenantRedisPipeline(
            self._prefix, self._r.pipeline(transaction=transaction)
        )

    # ------------------------------------------------------------------
    # Passthrough (no key)
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        return cast(bool, self._r.ping())

    def info(self, section: str | None = None) -> dict[str, Any]:
        return cast("dict[str, Any]", self._r.info(section))

    def close(self) -> None:
        self._r.close()


class TenantRedisPipeline:
    """Tenant-aware wrapper around ``redis.client.Pipeline``.

    Mirrors the explicit-prefix-on-write contract of ``TenantRedisClient`` for
    pipeline usage. Only the methods Onyx actually uses inside pipelines are
    exposed; expand this class when a new pipeline call is needed.
    """

    def __init__(self, prefix: str, pipeline: Pipeline) -> None:
        self._prefix: str = prefix
        # Typed as ``Any`` internally for the same reason as
        # ``TenantRedisClient._r``: redis-py's stubs are too narrow to accept
        # the wider key types we actually pass at runtime.
        self._p: Any = pipeline

    def _prefix_key(self, key: KeyArg) -> KeyArg:
        prefix = f"{self._prefix}:"
        if isinstance(key, str):
            return key if key.startswith(prefix) else prefix + key
        if isinstance(key, bytes):
            prefix_bytes = prefix.encode()
            return key if key.startswith(prefix_bytes) else prefix_bytes + key
        if isinstance(key, memoryview):
            prefix_bytes = prefix.encode()
            key_bytes = key.tobytes()
            if key_bytes.startswith(prefix_bytes):
                return key
            return memoryview(prefix_bytes + key_bytes)
        raise TypeError(f"Unsupported key type: {type(key)}")

    # write commands
    def set(
        self,
        name: KeyArg,
        value: str | bytes | int | float,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
        keepttl: bool = False,
    ) -> "TenantRedisPipeline":
        self._p.set(
            self._prefix_key(name),
            value,
            ex=ex,
            px=px,
            nx=nx,
            xx=xx,
            keepttl=keepttl,
        )
        return self

    def delete(self, *names: KeyArg) -> "TenantRedisPipeline":
        self._p.delete(*(self._prefix_key(n) for n in names))
        return self

    def incr(self, name: KeyArg, amount: int = 1) -> "TenantRedisPipeline":
        self._p.incr(self._prefix_key(name), amount)
        return self

    def expire(self, name: KeyArg, time: int) -> "TenantRedisPipeline":
        self._p.expire(self._prefix_key(name), time)
        return self

    def sadd(
        self,
        name: KeyArg,
        *values: str | bytes | int | float,
    ) -> "TenantRedisPipeline":
        self._p.sadd(self._prefix_key(name), *values)
        return self

    # ---- terminators ----

    def execute(self) -> list[Any]:
        return cast("list[Any]", self._p.execute())

    def reset(self) -> None:
        self._p.reset()

    def __enter__(self) -> "TenantRedisPipeline":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.reset()
