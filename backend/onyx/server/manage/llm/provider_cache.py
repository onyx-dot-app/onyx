"""Per-tenant cache for the non-admin LLM provider listing endpoints.

GET /llm/provider and GET /llm/persona/{persona_id}/providers are hit on every
chat page load and rebuild an identical payload from Postgres each time. The
descriptor construction (ORM hydration + pydantic models over every provider x
model configuration) is CPU-heavy enough to dominate api-server latency under
load, so the final response is memoized here.

Entries are keyed by everything that can change the response for a user
(persona, admin status, group memberships) and namespaced by a per-tenant
version token, so a single token rewrite invalidates every entry at once.
Provider mutations bump the token explicitly; changes that bypass the LLM
provider API (e.g. persona default-model edits) are bounded by the entry TTL.

Cache failures are non-fatal: readers fall through to Postgres.
"""

import hashlib
import uuid

from pydantic import BaseModel
from pydantic import ValidationError

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.cache.interface import CacheBackend
from onyx.server.manage.llm.models import LLMProviderDescriptor
from onyx.server.manage.llm.models import LLMProviderResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

_VERSION_KEY = "llm_provider_listing:version"
_ENTRY_KEY_PREFIX = "llm_provider_listing:entry"
ENTRY_TTL_SECONDS = 60


class ProviderListingCacheLookup(BaseModel):
    """Result of a cache lookup.

    `version` is the namespace token observed at lookup time. The subsequent
    fill MUST write under this token (not a re-read one): a reader that loaded
    pre-mutation DB state would otherwise write its stale payload under a token
    minted after it read, resurrecting stale data past an invalidation.
    `version` is None when the cache was unreachable — the fill is skipped.
    """

    response: LLMProviderResponse[LLMProviderDescriptor] | None
    version: str | None


def _decode_version(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Corrupted LLM provider listing version key; reminting")
        return None


def _current_version(cache: CacheBackend) -> str:
    raw = cache.get(_VERSION_KEY)
    version = _decode_version(raw) if raw is not None else None
    if version is not None:
        return version

    # Missing or corrupted token: mint one, then re-read so concurrent
    # initialisers converge on the winning write (CacheBackend has no NX set;
    # entries filled under a losing token just expire via TTL).
    minted = uuid.uuid4().hex
    cache.set(_VERSION_KEY, minted)
    raw = cache.get(_VERSION_KEY)
    version = _decode_version(raw) if raw is not None else None
    return version if version is not None else minted


def build_entry_key(
    version: str,
    persona_id: int | None,
    is_admin: bool,
    user_group_ids: set[int],
) -> str:
    discriminator = "|".join(
        [
            f"persona={persona_id if persona_id is not None else 'none'}",
            f"admin={is_admin}",
            f"groups={','.join(str(gid) for gid in sorted(user_group_ids))}",
        ]
    )
    digest = hashlib.sha256(discriminator.encode("utf-8")).hexdigest()
    return f"{_ENTRY_KEY_PREFIX}:{version}:{digest}"


def get_cached_provider_listing(
    persona_id: int | None,
    is_admin: bool,
    user_group_ids: set[int],
) -> ProviderListingCacheLookup:
    try:
        cache = get_cache_backend()
        version = _current_version(cache)
        raw = cache.get(build_entry_key(version, persona_id, is_admin, user_group_ids))
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("LLM provider listing cache read failed", exc_info=True)
        return ProviderListingCacheLookup(response=None, version=None)

    if raw is None:
        return ProviderListingCacheLookup(response=None, version=version)

    try:
        return ProviderListingCacheLookup(
            response=LLMProviderResponse[LLMProviderDescriptor].model_validate_json(
                raw
            ),
            version=version,
        )
    except ValidationError:
        logger.warning(
            "Discarding cached LLM provider listing that failed validation",
            exc_info=True,
        )
        return ProviderListingCacheLookup(response=None, version=version)


def cache_provider_listing(
    persona_id: int | None,
    is_admin: bool,
    user_group_ids: set[int],
    response: LLMProviderResponse[LLMProviderDescriptor],
    version: str | None,
) -> None:
    if version is None:
        return
    try:
        cache = get_cache_backend()
        cache.set(
            build_entry_key(version, persona_id, is_admin, user_group_ids),
            response.model_dump_json(),
            ex=ENTRY_TTL_SECONDS,
        )
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("LLM provider listing cache write failed", exc_info=True)


def invalidate_provider_listing_cache() -> None:
    try:
        get_cache_backend().set(_VERSION_KEY, uuid.uuid4().hex)
    except CACHE_TRANSIENT_ERRORS:
        logger.warning(
            "LLM provider listing cache invalidation failed; entries expire via TTL",
            exc_info=True,
        )
