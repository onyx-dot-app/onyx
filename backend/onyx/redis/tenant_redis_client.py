"""Composition-based tenant-aware Redis client.

Replaces the old ``__getattribute__``-based ``TenantRedis`` (a ``redis.Redis``
subclass that wrapped a hand-maintained allowlist of methods) with an explicit,
hand-written client built by composition. Every public method that touches a key
prefixes it explicitly. Calling a Redis method that is not exposed here is a
typing error, not a silent cross-tenant write.
"""

# PEP 563 — annotations are stored as strings so that ``def set`` and ``def
# hset`` etc. don't shadow the builtin types they reference in return
# annotations like ``-> set[bytes]``.
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
# builtin. Alias it once outside the class so static checkers (and ``ty``) pick
# the right thing up.
_BuiltinSet = set


def _prefix_key(prefix: str, key: KeyArg) -> KeyArg:
    """Idempotently prepends the tenant prefix to a key.

    Module-level (not a method) so ``TenantRedisClient`` and
    ``TenantRedisPipeline`` share a single definition. The prefixing contract is
    security-relevant — divergence between the client and the pipeline would
    silently break tenant isolation.

    Args:
        prefix: The tenant id (or shared namespace prefix) to prepend.
        key: The user-supplied key. ``str``, ``bytes``, and ``memoryview`` are
            all supported because redis-py accepts all three at runtime even
            where its stubs say otherwise.

    Raises:
        TypeError: If ``key`` is not one of the supported key types.

    Returns:
        The key with ``"{prefix}:"`` prepended, in the same type the caller
        passed in. If the key already starts with the prefix it is returned
        unchanged.
    """
    full = f"{prefix}:"
    if isinstance(key, str):
        return key if key.startswith(full) else full + key
    elif isinstance(key, bytes):
        full_bytes = full.encode()
        return key if key.startswith(full_bytes) else full_bytes + key
    elif isinstance(key, memoryview):
        full_bytes = full.encode()
        key_bytes = key.tobytes()
        if key_bytes.startswith(full_bytes):
            return key
        return memoryview(full_bytes + key_bytes)
    else:
        raise TypeError(f"Unsupported key type: {type(key)}.")


class TenantRedisClient:
    """Tenant-aware Redis client built by composition.

    ``prefix`` is either a tenant id (per-tenant isolation) or the shared
    namespace prefix (``DEFAULT_REDIS_PREFIX``, used for cross-tenant data).
    """

    def __init__(self, prefix: str, client: redis.Redis) -> None:
        """Initializes the wrapper around a redis-py client.

        Args:
            prefix: Tenant ID, or the shared namespace prefix for cross-tenant
                data. All key-bearing commands prepend ``"{prefix}:"`` to their
                key argument.
            client: The underlying ``redis.Redis`` instance to delegate to.
        """
        self._prefix: str = prefix
        # Typed as ``Any`` internally because redis-py's type stubs are
        # inconsistent (some commands declare ``name: str`` even though
        # ``bytes`` and ``memoryview`` work at runtime). The public API of this
        # class accepts the wider ``KeyArg`` union — strict types stay on the
        # boundary that callers actually see.
        self._r: Any = client

    @property
    def tenant_id(self) -> str:
        """The tenant ID (or shared namespace prefix) used for keys."""
        return self._prefix

    @property
    def raw_client(self) -> redis.Redis:
        """Escape hatch for code that genuinely needs the unwrapped client.

        Used by the lock-diagnostic helper, which inspects a `Lock` whose `name`
        attribute already carries the prefix and so must round-trip through a
        non-prefixing client. Prefer adding a method on this class over reaching
        for this.
        """
        return self._r

    # --------------------------------------------------------------------------
    # Internal helpers
    # --------------------------------------------------------------------------

    def _strip_prefix_bytes(self, key: bytes) -> bytes:
        """Strips the leading ``"{prefix}:"`` from a Redis-returned key.

        Used on the return path of commands like BLPOP that echo back the key
        the server matched on — the server sees the prefixed form, and callers
        expect the unprefixed form.

        Args:
            key: A key as returned by the Redis server, typically still carrying
                the tenant prefix.

        Returns:
            ``key`` with the leading prefix removed if present, otherwise
                ``key`` unchanged.
        """
        prefix_bytes = f"{self._prefix}:".encode()
        if key.startswith(prefix_bytes):
            return key[len(prefix_bytes) :]
        return key

    # --------------------------------------------------------------------------
    # Strings / generic
    # --------------------------------------------------------------------------

    def get(self, name: KeyArg) -> bytes | None:
        """Issues a GET against a tenant-prefixed key.

        Args:
            name: The (unprefixed) key to read.

        Returns:
            The stored value as ``bytes``, or ``None`` if the key does not
            exist.
        """
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
        """Issues a SET against a tenant-prefixed key.

        Args:
            name: The (unprefixed) key to write.
            value: The value to store.
            ex: Expire time in seconds.
            px: Expire time in milliseconds.
            nx: Only set the key if it does not already exist.
            xx: Only set the key if it already exists.
            keepttl: Retain the existing TTL when overwriting.
            get: Return the previous value of the key.
            exat: Absolute Unix timestamp (seconds) at which the key expires.
            pxat: Absolute Unix timestamp (milliseconds) at which the key
                expires.

        Returns:
            ``True`` on success, ``None`` if ``nx``/``xx`` prevented the write,
                or — when ``get=True`` — the previous value.
        """
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
        """Issues a SETEX against a tenant-prefixed key.

        Args:
            name: The (unprefixed) key to write.
            time: TTL in seconds.
            value: The value to store.

        Returns:
            ``True`` on success.
        """
        return cast(bool, self._r.setex(_prefix_key(self._prefix, name), time, value))

    def delete(self, *names: KeyArg) -> int:
        """Issues a DEL against one or more tenant-prefixed keys.

        Args:
            *names: The (unprefixed) keys to delete.

        Returns:
            The number of keys that were actually removed.
        """
        prefixed = [_prefix_key(self._prefix, n) for n in names]
        return cast(int, self._r.delete(*prefixed))

    def exists(self, *names: KeyArg) -> int:
        """Issues an EXISTS against one or more tenant-prefixed keys.

        Args:
            *names: The (unprefixed) keys to test.

        Returns:
            The number of keys that exist (a key listed twice is counted twice —
            this matches Redis semantics).
        """
        prefixed = [_prefix_key(self._prefix, n) for n in names]
        return cast(int, self._r.exists(*prefixed))

    def incr(self, name: KeyArg, amount: int = 1) -> int:
        """Atomically increments the integer at a tenant-prefixed key.

        Args:
            name: The (unprefixed) counter key.
            amount: The amount to add. Defaults to ``1``.

        Returns:
            The new integer value after the increment.
        """
        return cast(int, self._r.incr(_prefix_key(self._prefix, name), amount))

    def incrby(self, name: KeyArg, amount: int = 1) -> int:
        """Alias of :meth:`incr` exposed for parity with redis-py.

        Args:
            name: The (unprefixed) counter key.
            amount: The amount to add. Defaults to ``1``.

        Returns:
            The new integer value after the increment.
        """
        return cast(int, self._r.incrby(_prefix_key(self._prefix, name), amount))

    def getset(self, name: KeyArg, value: str | bytes | int | float) -> bytes | None:
        """Atomically sets a tenant-prefixed key and returns its old value.

        Args:
            name: The (unprefixed) key.
            value: The new value to store.

        Returns:
            The previous value as ``bytes``, or ``None`` if the key did not
                exist.
        """
        return cast(
            "bytes | None", self._r.getset(_prefix_key(self._prefix, name), value)
        )

    # --------------------------------------------------------------------------
    # Hash
    # --------------------------------------------------------------------------

    def hset(
        self,
        name: KeyArg,
        key: str | bytes | None = None,
        value: str | bytes | int | float | None = None,
        mapping: Mapping[Any, Any] | None = None,
        items: list[Any] | None = None,
    ) -> int:
        """Issues an HSET against a tenant-prefixed hash key.

        Hash fields (``key``) are not prefixed — only the outer Redis key is
        namespaced.

        Args:
            name: The (unprefixed) hash key.
            key: Single hash field to set. Use with ``value``.
            value: Value for the single hash field set via ``key``.
            mapping: ``{field: value}`` dict to set in one call.
            items: Flat ``[field1, value1, field2, value2, ...]`` list to set in
                one call.

        Returns:
            The number of fields that were newly added (existing fields updated
                in place do not count).
        """
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
        """Issues an HGET against a tenant-prefixed hash key.

        Args:
            name: The (unprefixed) hash key.
            key: The hash field to read.

        Returns:
            The field value as ``bytes``, or ``None`` if either the hash or the
                field is missing.
        """
        return cast("bytes | None", self._r.hget(_prefix_key(self._prefix, name), key))

    def hmget(
        self,
        name: KeyArg,
        keys: list[str] | list[bytes],
        *args: str | bytes,
    ) -> list[bytes | None]:
        """Issues an HMGET against a tenant-prefixed hash key.

        Args:
            name: The (unprefixed) hash key.
            keys: List of hash fields to read in a single round trip.
            *args: Additional hash fields, appended to ``keys``.

        Returns:
            A list with one entry per requested field, in input order. Missing
                fields are returned as ``None``.
        """
        return cast(
            "list[bytes | None]",
            self._r.hmget(_prefix_key(self._prefix, name), keys, *args),
        )

    def hdel(self, name: KeyArg, *keys: str | bytes) -> int:
        """Issues an HDEL against a tenant-prefixed hash key.

        Args:
            name: The (unprefixed) hash key.
            *keys: One or more hash fields to delete.

        Returns:
            The number of fields that were actually removed.
        """
        return cast(int, self._r.hdel(_prefix_key(self._prefix, name), *keys))

    def hexists(self, name: KeyArg, key: str | bytes) -> bool:
        """Tests whether a field exists in a tenant-prefixed hash key.

        Args:
            name: The (unprefixed) hash key.
            key: The hash field to test.

        Returns:
            ``True`` if the field exists, ``False`` otherwise.
        """
        return cast(bool, self._r.hexists(_prefix_key(self._prefix, name), key))

    # --------------------------------------------------------------------------
    # Set
    # --------------------------------------------------------------------------

    def smembers(self, name: KeyArg) -> _BuiltinSet[bytes]:
        """Returns every member of a tenant-prefixed set key.

        Set members are not prefixed — only the outer Redis key is.

        Args:
            name: The (unprefixed) set key.

        Returns:
            The full set of members as ``bytes``.
        """
        return cast(
            "_BuiltinSet[bytes]", self._r.smembers(_prefix_key(self._prefix, name))
        )

    def sismember(self, name: KeyArg, value: str | bytes | int | float) -> bool:
        """Tests whether ``value`` is a member of a tenant-prefixed set key.

        Args:
            name: The (unprefixed) set key.
            value: The candidate member.

        Returns:
            ``True`` if ``value`` is in the set, ``False`` otherwise.
        """
        return cast(bool, self._r.sismember(_prefix_key(self._prefix, name), value))

    def sadd(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        """Adds one or more values to a tenant-prefixed set key.

        Args:
            name: The (unprefixed) set key.
            *values: Members to add. Stored verbatim (no prefixing).

        Returns:
            The number of newly added members (existing members are not
                counted).
        """
        return cast(int, self._r.sadd(_prefix_key(self._prefix, name), *values))

    def srem(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        """Removes one or more values from a tenant-prefixed set key.

        Args:
            name: The (unprefixed) set key.
            *values: Members to remove.

        Returns:
            The number of members that were actually removed.
        """
        return cast(int, self._r.srem(_prefix_key(self._prefix, name), *values))

    def scard(self, name: KeyArg) -> int:
        """Returns the cardinality of a tenant-prefixed set key.

        Args:
            name: The (unprefixed) set key.

        Returns:
            The number of members in the set, or ``0`` if the key is missing.
        """
        return cast(int, self._r.scard(_prefix_key(self._prefix, name)))

    # --------------------------------------------------------------------------
    # Sorted set
    # --------------------------------------------------------------------------

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
    ) -> int | float | None:
        """Adds or updates members of a tenant-prefixed sorted-set key.

        Args:
            name: The (unprefixed) sorted-set key.
            mapping: ``{member: score}`` dict to upsert.
            nx: Only add new members; never update existing scores.
            xx: Only update existing members; never add new ones.
            ch: Change the return value semantics from "added" to "added or
                updated".
            incr: Treat the score as a delta and increment instead of replacing.
                Limits ``mapping`` to a single entry.
            gt: Only update an existing score if the new score is greater.
            lt: Only update an existing score if the new score is less.

        Returns:
            With default flags: the ``int`` count of members added (or, with
                ``ch=True``, added or updated). With ``incr=True``: the new
                score as a ``float``, or ``None`` if ``nx``/``xx`` prevented the
                write.
        """
        return cast(
            "int | float | None",
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
        """Returns a slice of a tenant-prefixed sorted-set key by index.

        Args:
            name: The (unprefixed) sorted-set key.
            start: Inclusive start index (zero-based; negative counts from end).
            end: Inclusive end index.
            desc: Iterate in descending score order instead of ascending.
            withscores: If ``True``, include the score alongside each member.
            score_cast_func: Callable applied to each returned score. Defaults
                to ``float``.

        Returns:
            A list of members, or — with ``withscores=True`` — a list of
                ``(member, score)`` tuples.
        """
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
        """
        Returns a slice of a tenant-prefixed sorted-set key in descending order.

        Args:
            name: The (unprefixed) sorted-set key.
            start: Inclusive start index in the reversed order.
            end: Inclusive end index in the reversed order.
            withscores: If ``True``, include the score alongside each member.
            score_cast_func: Callable applied to each returned score. Defaults
                to ``float``.

        Returns:
            A list of members, or — with ``withscores=True`` — a list of
                ``(member, score)`` tuples.
        """
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
        """Returns members of a tenant-prefixed sorted set within a score range.

        Args:
            name: The (unprefixed) sorted-set key.
            min: Inclusive lower bound. Use ``"-inf"`` or a ``"(value"`` string
                for an exclusive bound (Redis convention).
            max: Inclusive upper bound. Same exclusive-bound convention.
            start: Offset into the result for pagination.
            num: Maximum number of results to return when paginating.
            withscores: If ``True``, include the score alongside each member.
            score_cast_func: Callable applied to each returned score. Defaults
                to ``float``.

        Returns:
            A list of members, or — with ``withscores=True`` — a list of
            ``(member, score)`` tuples.
        """
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
        """Removes members of a tenant-prefixed sorted set within a score range.

        Args:
            name: The (unprefixed) sorted-set key.
            min: Inclusive lower bound (``"-inf"`` or ``"(value"`` accepted).
            max: Inclusive upper bound.

        Returns:
            The number of members removed.
        """
        return cast(
            int, self._r.zremrangebyscore(_prefix_key(self._prefix, name), min, max)
        )

    def zscore(self, name: KeyArg, value: str | bytes) -> float | None:
        """Returns the score of a member of a tenant-prefixed sorted-set key.

        Args:
            name: The (unprefixed) sorted-set key.
            value: The member to look up.

        Returns:
            The score as ``float``, or ``None`` if the member is missing.
        """
        return cast(
            "float | None", self._r.zscore(_prefix_key(self._prefix, name), value)
        )

    def zcard(self, name: KeyArg) -> int:
        """Returns the cardinality of a tenant-prefixed sorted-set key.

        Args:
            name: The (unprefixed) sorted-set key.

        Returns:
            The number of members in the sorted set, or ``0`` if missing.
        """
        return cast(int, self._r.zcard(_prefix_key(self._prefix, name)))

    # --------------------------------------------------------------------------
    # List
    # --------------------------------------------------------------------------

    def rpush(self, name: KeyArg, *values: str | bytes | int | float) -> int:
        """Appends one or more values to a tenant-prefixed list key.

        Args:
            name: The (unprefixed) list key.
            *values: Values to append. Stored verbatim (no prefixing).

        Returns:
            The new length of the list after the push.
        """
        return cast(int, self._r.rpush(_prefix_key(self._prefix, name), *values))

    def lindex(self, name: KeyArg, index: int) -> bytes | None:
        """Returns the element at ``index`` of a tenant-prefixed list key.

        Args:
            name: The (unprefixed) list key.
            index: Zero-based index. Negative values count from the tail.

        Returns:
            The element at that position as ``bytes``, or ``None`` if the index
                is out of range or the key does not exist.
        """
        return cast(
            "bytes | None", self._r.lindex(_prefix_key(self._prefix, name), index)
        )

    def _blpop_brpop(
        self,
        method_name: str,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        """Shared body for :meth:`blpop` and :meth:`brpop`.

        Prefixes every key on the way in and strips the prefix from the returned
        key on the way out — the server echoes back the matched key in its
        prefixed form, but callers expect the unprefixed form.

        Args:
            method_name: Either ``"blpop"`` or ``"brpop"`` — the redis-py method
                to dispatch to.
            keys: A single (unprefixed) key or a list of (unprefixed) keys to
                wait on.
            timeout: Maximum seconds to block. ``0`` blocks indefinitely.

        Returns:
            ``(key, value)`` with ``key`` stripped of its prefix on success, or
                ``None`` if the timeout elapses.
        """
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
        # The bytes contract is security-relevant: if the key isn't bytes the
        # `_strip_prefix_bytes` path silently degrades to "return the prefixed
        # form unchanged", leaking the tenant namespace. Fail loudly so a future
        # `decode_responses=True` flip is noisy rather than insecure.
        if not isinstance(key, bytes):
            raise TypeError(
                f"{method_name.upper()} returned non-bytes key "
                f"{type(key).__name__}; TenantRedisClient requires "
                "decode_responses=False."
            )
        if not isinstance(value, bytes):
            raise TypeError(
                f"{method_name.upper()} returned non-bytes value "
                f"{type(value).__name__}; TenantRedisClient requires "
                "decode_responses=False."
            )
        return (self._strip_prefix_bytes(key), value)

    def blpop(
        self,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        """Blocking left-pops across one or more tenant-prefixed list keys.

        Args:
            keys: A single (unprefixed) key or a list of (unprefixed) keys to
                wait on. The server pops from the first key with data.
            timeout: Maximum seconds to block. ``0`` blocks indefinitely.

        Returns:
            ``(key, value)`` where ``key`` has been stripped of its tenant
                prefix, or ``None`` if the timeout elapses.
        """
        return self._blpop_brpop("blpop", keys, timeout)

    def brpop(
        self,
        keys: list[str] | list[bytes] | KeyArg,
        timeout: int = 0,
    ) -> tuple[bytes, bytes] | None:
        """Blocking right-pops across one or more tenant-prefixed list keys.

        Args:
            keys: A single (unprefixed) key or a list of (unprefixed) keys to
                wait on. The server pops from the first key with data.
            timeout: Maximum seconds to block. ``0`` blocks indefinitely.

        Returns:
            ``(key, value)`` where ``key`` has been stripped of its tenant
                prefix, or ``None`` if the timeout elapses.
        """
        return self._blpop_brpop("brpop", keys, timeout)

    # --------------------------------------------------------------------------
    # TTL family
    # --------------------------------------------------------------------------

    def ttl(self, name: KeyArg) -> int:
        """Returns the remaining TTL of a tenant-prefixed key, in seconds.

        Args:
            name: The (unprefixed) key.

        Returns:
            Seconds until expiry, ``-1`` if the key has no TTL set, or ``-2`` if
                the key does not exist.
        """
        return cast(int, self._r.ttl(_prefix_key(self._prefix, name)))

    def pttl(self, name: KeyArg) -> int:
        """Returns the remaining TTL of a tenant-prefixed key, in milliseconds.

        Args:
            name: The (unprefixed) key.

        Returns:
            Milliseconds until expiry, ``-1`` if the key has no TTL set, or
                ``-2`` if the key does not exist.
        """
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
        """Sets a TTL on a tenant-prefixed key.

        Args:
            name: The (unprefixed) key.
            time: TTL in seconds.
            nx: Only set if the key has no current TTL.
            xx: Only set if the key already has a TTL.
            gt: Only set if the new TTL is greater than the current one.
            lt: Only set if the new TTL is less than the current one.

        Returns:
            ``True`` if the TTL was set, ``False`` otherwise (key missing or a
                flag prevented the write).
        """
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
        """Sets an absolute expiry on a tenant-prefixed key (Unix seconds).

        Args:
            name: The (unprefixed) key.
            when: Unix timestamp in seconds at which the key should expire.
            nx: Only set if the key has no current TTL.
            xx: Only set if the key already has a TTL.
            gt: Only set if the new deadline is later than the current one.
            lt: Only set if the new deadline is earlier than the current one.

        Returns:
            ``True`` if the expiry was set, ``False`` otherwise.
        """
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
        """Sets a TTL on a tenant-prefixed key, in milliseconds.

        Args:
            name: The (unprefixed) key.
            time: TTL in milliseconds.
            nx: Only set if the key has no current TTL.
            xx: Only set if the key already has a TTL.
            gt: Only set if the new TTL is greater than the current one.
            lt: Only set if the new TTL is less than the current one.

        Returns:
            ``True`` if the TTL was set, ``False`` otherwise.
        """
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
        """Sets an absolute expiry on a tenant-prefixed key (Unix milliseconds).

        Args:
            name: The (unprefixed) key.
            when: Unix timestamp in milliseconds at which the key should expire.
            nx: Only set if the key has no current TTL.
            xx: Only set if the key already has a TTL.
            gt: Only set if the new deadline is later than the current one.
            lt: Only set if the new deadline is earlier than the current one.

        Returns:
            ``True`` if the expiry was set, ``False`` otherwise.
        """
        return cast(
            bool,
            self._r.pexpireat(
                _prefix_key(self._prefix, name), when, nx=nx, xx=xx, gt=gt, lt=lt
            ),
        )

    # --------------------------------------------------------------------------
    # Locks
    #
    # The returned `redis.lock.Lock` operates on the prefixed name internally
    # (its `name` attribute is the prefixed string). None of the lock's own
    # methods take a key argument, so this is safe — but callers should treat
    # `lock.name` as already-prefixed if they ever inspect it.
    # --------------------------------------------------------------------------

    def lock(
        self,
        name: str,
        timeout: float | None = None,
        sleep: float = 0.1,
        blocking: bool = True,
        blocking_timeout: float | None = None,
        thread_local: bool = True,
    ) -> RedisLock:
        """Constructs a ``redis.lock.Lock`` over a tenant-prefixed key.

        The returned lock's ``.name`` attribute is the *prefixed* string —
        callers that read it back must treat it as already-prefixed.

        Args:
            name: The (unprefixed) lock key.
            timeout: Maximum lifetime of the lock in seconds; ``None`` means no
                auto-release.
            sleep: How long to sleep between acquisition attempts when blocking.
            blocking: Whether ``acquire()`` should block waiting for the lock.
            blocking_timeout: Maximum seconds ``acquire()`` will wait when
                ``blocking=True``. ``None`` blocks indefinitely.
            thread_local: Whether the lock token is stored in thread-local state
                — see redis-py for the trade-offs.

        Returns:
            A ``redis.lock.Lock`` bound to the prefixed key.
        """
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
        """Alias for :meth:`lock` — redis-py exposes both names.

        Args:
            name: The (unprefixed) lock key.
            timeout: Maximum lifetime of the lock in seconds.
            sleep: Sleep between blocking acquisition attempts.
            blocking: Whether ``acquire()`` should block.
            blocking_timeout: Max seconds to wait when blocking.
            thread_local: Whether the lock token is thread-local.

        Returns:
            A ``redis.lock.Lock`` bound to the prefixed key.
        """
        return self.lock(
            name,
            timeout=timeout,
            sleep=sleep,
            blocking=blocking,
            blocking_timeout=blocking_timeout,
            thread_local=thread_local,
        )

    # --------------------------------------------------------------------------
    # Scan
    # --------------------------------------------------------------------------

    def scan_iter(
        self,
        match: str | bytes | None = None,
        count: int | None = None,
        _type: str | None = None,
    ) -> Generator[bytes, None, None]:
        """Iterates every tenant-scoped key matching ``match``.

        When ``match`` is omitted we default to ``"{prefix}:*"`` rather than
        forwarding ``None`` — ``None`` would scan every key in Redis and
        un-stripped foreign-tenant keys would leak through the else branch
        below. Defaulting to the tenant prefix keeps ``r.scan_iter()`` doing the
        natural thing ("all my keys") without a cross-tenant leak.

        Args:
            match: Glob-style pattern, e.g. ``"users:*"``. Tenant-prefixed
                before being sent to the server. ``None`` means "every key
                inside this tenant's namespace".
            count: Hint to the server about how many keys to return per round
                trip. Does not affect total results.
            _type: Filter by Redis type (``"string"``, ``"hash"``, ...).

        Yields:
            Each matching key as ``bytes``, with the tenant prefix stripped.
        """
        prefix = f"{self._prefix}:"
        prefix_bytes = prefix.encode()
        prefix_len = len(prefix_bytes)
        prefixed_match = (
            _prefix_key(self._prefix, match) if match is not None else f"{prefix}*"
        )
        for key in self._r.scan_iter(match=prefixed_match, count=count, _type=_type):
            # Same security contract as `_blpop_brpop`: a non-bytes key would
            # silently leak the tenant prefix to the caller. Fail loudly.
            if not isinstance(key, bytes):
                raise TypeError(
                    f"SCAN returned non-bytes key {type(key).__name__}; "
                    "TenantRedisClient requires decode_responses=False."
                )
            # By construction MATCH was `{prefix}*`, so every returned key must
            # start with the prefix. Assert it instead of falling through to
            # "yield prefixed".
            if not key.startswith(prefix_bytes):
                raise RuntimeError(
                    f"SCAN returned key {key!r} that does not start with "
                    f"tenant prefix {prefix_bytes!r}; this should be impossible."
                )
            yield key[prefix_len:]

    def sscan_iter(
        self,
        name: KeyArg,
        match: str | bytes | None = None,
        count: int | None = None,
    ) -> Generator[bytes, None, None]:
        """Iterates the members of a tenant-prefixed set key.

        The set members themselves are not prefixed and are returned verbatim —
        only the outer key is namespaced.

        Args:
            name: The (unprefixed) set key.
            match: Optional glob pattern applied to set members server-side.
            count: Hint to the server about how many members to return per round
                trip.

        Yields:
            Each matching member as ``bytes``.
        """
        return cast(
            "Generator[bytes, None, None]",
            self._r.sscan_iter(
                _prefix_key(self._prefix, name), match=match, count=count
            ),
        )

    # --------------------------------------------------------------------------
    # Scripting
    #
    # The signature is `(script, keys, args)` rather than the redis-py native
    # `(script, numkeys, *keys_and_args)` so callers can't accidentally cross
    # the key/arg boundary. `numkeys` is computed from `len(keys)`.
    # --------------------------------------------------------------------------

    def eval(
        self,
        script: str,
        keys: list[str] | list[bytes],
        args: list[str] | list[bytes] | list[int] | list[float] | None = None,
    ) -> Any:
        """Runs a Lua script with an explicit ``(keys, args)`` split.

        Tenant-prefixes every entry in ``keys``; ``args`` are passed through
        verbatim. By convention Lua scripts must not put key names in ``ARGV``,
        otherwise tenant scoping is bypassed.

        Args:
            script: The Lua script source.
            keys: Keys the script will operate on, in ``KEYS[i]`` order. Each is
                tenant-prefixed before being sent to the server.
            args: Non-key arguments, in ``ARGV[i]`` order. ``None`` is treated
                as an empty list.

        Returns:
            Whatever the script returns, encoded per redis-py conventions.
        """
        prefixed_keys = [_prefix_key(self._prefix, k) for k in keys]
        return self._r.eval(script, len(prefixed_keys), *prefixed_keys, *(args or []))

    def evalsha(
        self,
        sha: str,
        keys: list[str] | list[bytes],
        args: list[str] | list[bytes] | list[int] | list[float] | None = None,
    ) -> Any:
        """
        Runs a previously-loaded Lua script by SHA, with explicit key/arg split.

        Args:
            sha: The SHA1 digest of a script previously loaded via ``SCRIPT
                LOAD``.
            keys: Keys the script will operate on, in ``KEYS[i]`` order. Each is
                tenant-prefixed before being sent to the server.
            args: Non-key arguments, in ``ARGV[i]`` order. ``None`` is treated
                as an empty list.

        Returns:
            Whatever the script returns, encoded per redis-py conventions.
        """
        prefixed_keys = [_prefix_key(self._prefix, k) for k in keys]
        return self._r.evalsha(sha, len(prefixed_keys), *prefixed_keys, *(args or []))

    # --------------------------------------------------------------------------
    # Pipeline
    # --------------------------------------------------------------------------

    def pipeline(self, transaction: bool = True) -> TenantRedisPipeline:
        """Opens a tenant-scoped pipeline that prefixes keys on every write.

        Args:
            transaction: Whether the queued commands run as a MULTI/EXEC
                transaction. Defaults to ``True`` (matches redis-py).

        Returns:
            A :class:`TenantRedisPipeline` ready to accept queued commands.
        """
        return TenantRedisPipeline(
            self._prefix, self._r.pipeline(transaction=transaction)
        )

    # --------------------------------------------------------------------------
    # Passthrough (no key)
    # --------------------------------------------------------------------------

    def ping(self) -> bool:
        """Issues a PING. No key, so no prefixing happens.

        Returns:
            ``True`` if the server responded.
        """
        return cast(bool, self._r.ping())

    def info(self, section: str | None = None) -> dict[str, Any]:
        """Issues an INFO. Server-level command — no key, no prefix.

        Args:
            section: Optional INFO section name (e.g. ``"memory"``,
                ``"clients"``). ``None`` returns the default sections.

        Returns:
            A dict of server stats keyed by stat name.
        """
        return cast("dict[str, Any]", self._r.info(section))

    def close(self) -> None:
        """
        Closes the underlying redis-py client and releases its connection pool.
        """
        self._r.close()


class TenantRedisPipeline:
    """Tenant-aware wrapper around ``redis.client.Pipeline``.

    Mirrors the explicit-prefix-on-write contract of ``TenantRedisClient`` for
    pipeline usage. Only the methods Onyx actually uses inside pipelines are
    exposed; expand this class when a new pipeline call is needed.
    """

    def __init__(self, prefix: str, pipeline: Pipeline) -> None:
        """Initializes the wrapper around a redis-py pipeline.

        Args:
            prefix: Tenant ID, or the shared namespace prefix. Must match the
                prefix of the parent :class:`TenantRedisClient` — callers should
                always obtain pipelines via ``TenantRedisClient.pipeline()``
                rather than constructing one directly.
            pipeline: The underlying ``redis.client.Pipeline`` to delegate to.
        """
        self._prefix: str = prefix
        # Typed as ``Any`` internally for the same reason as
        # ``TenantRedisClient._r``: redis-py's stubs are too narrow to accept
        # the wider key types we actually pass at runtime.
        self._p: Any = pipeline

    # --------------------------------------------------------------------------
    # Write commands
    # --------------------------------------------------------------------------

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
    ) -> TenantRedisPipeline:
        """Queues a SET against a tenant-prefixed key.

        Args:
            name: The (unprefixed) key to write.
            value: The value to store.
            ex: Expire time in seconds.
            px: Expire time in milliseconds.
            nx: Only set the key if it does not already exist.
            xx: Only set the key if it already exists.
            keepttl: Retain the existing TTL when overwriting.
            get: Return the previous value (visible after :meth:`execute`).
            exat: Absolute Unix timestamp (seconds) at which the key expires.
            pxat: Absolute Unix timestamp (milliseconds) at which the key
                expires.

        Returns:
            ``self``, to allow chaining further pipeline commands.
        """
        self._p.set(
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
        return self

    def delete(self, *names: KeyArg) -> TenantRedisPipeline:
        """Queues a DEL against one or more tenant-prefixed keys.

        Args:
            *names: The (unprefixed) keys to delete.

        Returns:
            ``self``, to allow chaining further pipeline commands.
        """
        self._p.delete(*(_prefix_key(self._prefix, n) for n in names))
        return self

    def incr(self, name: KeyArg, amount: int = 1) -> TenantRedisPipeline:
        """Queues an INCRBY against a tenant-prefixed counter key.

        Args:
            name: The (unprefixed) counter key.
            amount: The amount to add. Defaults to ``1``.

        Returns:
            ``self``, to allow chaining further pipeline commands.
        """
        self._p.incr(_prefix_key(self._prefix, name), amount)
        return self

    def expire(
        self,
        name: KeyArg,
        time: int,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> TenantRedisPipeline:
        """Queues an EXPIRE against a tenant-prefixed key.

        Args:
            name: The (unprefixed) key.
            time: TTL in seconds.
            nx: Only set if the key has no current TTL.
            xx: Only set if the key already has a TTL.
            gt: Only set if the new TTL is greater than the current one.
            lt: Only set if the new TTL is less than the current one.

        Returns:
            ``self``, to allow chaining further pipeline commands.
        """
        self._p.expire(
            _prefix_key(self._prefix, name), time, nx=nx, xx=xx, gt=gt, lt=lt
        )
        return self

    def sadd(
        self,
        name: KeyArg,
        *values: str | bytes | int | float,
    ) -> TenantRedisPipeline:
        """Queues an SADD against a tenant-prefixed set key.

        Args:
            name: The (unprefixed) set key.
            *values: Members to add. Stored verbatim (no prefixing).

        Returns:
            ``self``, to allow chaining further pipeline commands.
        """
        self._p.sadd(_prefix_key(self._prefix, name), *values)
        return self

    # --------------------------------------------------------------------------
    # Passthrough
    # --------------------------------------------------------------------------

    def execute(self) -> list[Any]:
        """Sends every queued command to Redis and returns their results.

        Returns:
            A list of per-command results in queue order. With
                ``transaction=True`` (the default) the list is the result of a
                single MULTI/EXEC.
        """
        return cast("list[Any]", self._p.execute())

    def reset(self) -> None:
        """Discards the queued commands without executing them."""
        self._p.reset()

    def __enter__(self) -> TenantRedisPipeline:
        """
        Enters a ``with`` block; returns ``self`` so callers can queue commands.
        """
        return self

    def __exit__(self, *exc_info: Any) -> None:
        """Exits a ``with`` block, discarding any commands not yet executed."""
        self.reset()
