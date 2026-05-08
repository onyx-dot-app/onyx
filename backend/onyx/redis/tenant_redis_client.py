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


def _prefix_key(prefix: str, key: KeyArg) -> KeyArg:
    """Idempotently prepend the tenant prefix to a key.

    Module-level (not a method) so ``TenantRedisClient`` and
    ``TenantRedisPipeline`` share a single definition. The prefixing
    contract is security-relevant — divergence between the client and the
    pipeline would silently break tenant isolation.
    """
    full = f"{prefix}:"
    if isinstance(key, str):
        return key if key.startswith(full) else full + key
    if isinstance(key, bytes):
        full_bytes = full.encode()
        return key if key.startswith(full_bytes) else full_bytes + key
    if isinstance(key, memoryview):
        full_bytes = full.encode()
        key_bytes = key.tobytes()
        if key_bytes.startswith(full_bytes):
            return key
        return memoryview(full_bytes + key_bytes)
    raise TypeError(f"Unsupported key type: {type(key)}")


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

    def _strip_prefix_bytes(self, key: bytes) -> bytes:
        prefix_bytes = f"{self._prefix}:".encode()
        if key.startswith(prefix_bytes):
            return key[len(prefix_bytes) :]
        return key

    # ------------------------------------------------------------------
    # Strings / generic
    # ------------------------------------------------------------------

    def get(self, name: KeyArg) -> bytes | None:
        return cast("bytes | None", self._r.get(_prefix_key(self._prefix, name)))

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
            _prefix_key(self._prefix, name),
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
        return cast(bool, self._r.setex(_prefix_key(self._prefix, name), time, value))

    def delete(self, *names: KeyArg) -> int:
        prefixed = [_prefix_key(self._prefix, n) for n in names]
        return cast(int, self._r.delete(*prefixed))

    def exists(self, *names: KeyArg) -> int:
        prefixed = [_prefix_key(self._prefix, n) for n in names]
        return cast(int, self._r.exists(*prefixed))

    def incr(self, name: KeyArg, amount: int = 1) -> int:
        return cast(int, self._r.incr(_prefix_key(self._prefix, name), amount))

    def incrby(self, name: KeyArg, amount: int = 1) -> int:
        return cast(int, self._r.incrby(_prefix_key(self._prefix, name), amount))

    def getset(self, name: KeyArg, value: str | bytes | int | float) -> bytes | None:
        return cast(
            "bytes | None", self._r.getset(_prefix_key(self._prefix, name), value)
        )

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
                _prefix_key(self._prefix, name),
                key=key,
                value=value,
                mapping=mapping,
                items=items,
            ),
        )

    def hget(self, name: KeyArg, key: str | bytes) -> bytes | None:
        return cast("bytes | None", self._r.hget(_prefix_key(self._prefix, name), key))

    def hmget(
        self,
        name: KeyArg,
        keys: list[str] | list[bytes],
        *args: str | bytes,
    ) -> list[bytes | None]:
        return cast(
            "list[bytes | None]",
            self._r.hmget(_prefix_key(self._prefix, name), keys, *args),
        )

    def hdel(self, name: KeyArg, *keys: str | bytes) -> int:
        return cast(int, self._r.hdel(_prefix_key(self._prefix, name), *keys))

    def hexists(self, name: KeyArg, key: str | bytes) -> bool:
        return cast(bool, self._r.hexists(_prefix_key(self._prefix, name), key))

    # ------------------------------------------------------------------
    # Set
    # ------------------------------------------------------------------

    def smembers(self, name: KeyArg) -> _BuiltinSet[bytes]:
        return cast(
            "_BuiltinSet[bytes]", self._r.smembers(_prefix_key(self._prefix, name))
        )

    def sismember(self, name: KeyArg, value: str | bytes | int | float) -> bool:
        return cast(bool, self._r.sismember(_prefix_key(self._prefix, name), value))

    def sadd(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        return cast(int, self._r.sadd(_prefix_key(self._prefix, name), *values))

    def srem(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        return cast(int, self._r.srem(_prefix_key(self._prefix, name), *values))

    def scard(self, name: KeyArg) -> int:
        return cast(int, self._r.scard(_prefix_key(self._prefix, name)))

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
                _prefix_key(self._prefix, name),
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
                _prefix_key(self._prefix, name),
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
                _prefix_key(self._prefix, name),
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
                _prefix_key(self._prefix, name),
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
        return cast(
            int, self._r.zremrangebyscore(_prefix_key(self._prefix, name), min, max)
        )

    def zscore(self, name: KeyArg, value: str | bytes) -> float | None:
        return cast(
            "float | None", self._r.zscore(_prefix_key(self._prefix, name), value)
        )

    def zcard(self, name: KeyArg) -> int:
        return cast(int, self._r.zcard(_prefix_key(self._prefix, name)))

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def rpush(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        return cast(int, self._r.rpush(_prefix_key(self._prefix, name), *values))

    def lindex(self, name: KeyArg, index: int) -> bytes | None:
        return cast(
            "bytes | None", self._r.lindex(_prefix_key(self._prefix, name), index)
        )

    def _blpop_brpop(
        self,
        method_name: str,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        prefixed_keys: KeyArg | list[KeyArg]
        if isinstance(keys, (str, bytes, memoryview)):
            prefixed_keys = _prefix_key(self._prefix, keys)
        else:
            prefixed_keys = [_prefix_key(self._prefix, k) for k in keys]
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
        return cast(int, self._r.ttl(_prefix_key(self._prefix, name)))

    def pttl(self, name: KeyArg) -> int:
        return cast(int, self._r.pttl(_prefix_key(self._prefix, name)))

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
            self._r.expire(
                _prefix_key(self._prefix, name), time, nx=nx, xx=xx, gt=gt, lt=lt
            ),
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
            self._r.expireat(
                _prefix_key(self._prefix, name), when, nx=nx, xx=xx, gt=gt, lt=lt
            ),
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
            self._r.pexpire(
                _prefix_key(self._prefix, name), time, nx=nx, xx=xx, gt=gt, lt=lt
            ),
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
            self._r.pexpireat(
                _prefix_key(self._prefix, name), when, nx=nx, xx=xx, gt=gt, lt=lt
            ),
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
            cast(str, _prefix_key(self._prefix, name)),
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
        # When `match` is omitted we default to `{prefix}:*` rather than
        # forwarding `None` — `None` would scan every key in Redis and the
        # un-stripped foreign-tenant keys would leak through the else branch
        # below. Defaulting to the tenant prefix keeps `r.scan_iter()` doing
        # the natural thing ("all my keys") without a cross-tenant leak.
        prefix = f"{self._prefix}:"
        prefix_bytes = prefix.encode()
        prefix_len = len(prefix_bytes)
        prefixed_match = (
            _prefix_key(self._prefix, match) if match is not None else f"{prefix}*"
        )
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
            self._r.sscan_iter(
                _prefix_key(self._prefix, name), match=match, count=count
            ),
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
        prefixed_keys = [_prefix_key(self._prefix, k) for k in keys]
        return self._r.eval(script, len(prefixed_keys), *prefixed_keys, *(args or []))

    def evalsha(
        self,
        sha: str,
        keys: list[str] | list[bytes],
        args: list[str] | list[bytes] | list[int] | list[float] | None = None,
    ) -> Any:
        prefixed_keys = [_prefix_key(self._prefix, k) for k in keys]
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
            _prefix_key(self._prefix, name),
            value,
            ex=ex,
            px=px,
            nx=nx,
            xx=xx,
            keepttl=keepttl,
        )
        return self

    def delete(self, *names: KeyArg) -> "TenantRedisPipeline":
        self._p.delete(*(_prefix_key(self._prefix, n) for n in names))
        return self

    def incr(self, name: KeyArg, amount: int = 1) -> "TenantRedisPipeline":
        self._p.incr(_prefix_key(self._prefix, name), amount)
        return self

    def expire(self, name: KeyArg, time: int) -> "TenantRedisPipeline":
        self._p.expire(_prefix_key(self._prefix, name), time)
        return self

    def sadd(
        self,
        name: KeyArg,
        *values: str | bytes | int | float,
    ) -> "TenantRedisPipeline":
        self._p.sadd(_prefix_key(self._prefix, name), *values)
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
