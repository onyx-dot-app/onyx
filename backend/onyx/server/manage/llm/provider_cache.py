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


def _current_version(cache: CacheBackend) -> str:
    raw = cache.get(_VERSION_KEY)
    if raw is not None:
        return raw.decode("utf-8")
    version = uuid.uuid4().hex
    cache.set(_VERSION_KEY, version)
    return version


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
) -> LLMProviderResponse[LLMProviderDescriptor] | None:
    try:
        cache = get_cache_backend()
        raw = cache.get(
            build_entry_key(
                _current_version(cache), persona_id, is_admin, user_group_ids
            )
        )
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("LLM provider listing cache read failed", exc_info=True)
        return None

    if raw is None:
        return None

    try:
        return LLMProviderResponse[LLMProviderDescriptor].model_validate_json(raw)
    except ValidationError:
        logger.warning(
            "Discarding cached LLM provider listing that failed validation",
            exc_info=True,
        )
        return None


def cache_provider_listing(
    persona_id: int | None,
    is_admin: bool,
    user_group_ids: set[int],
    response: LLMProviderResponse[LLMProviderDescriptor],
) -> None:
    try:
        cache = get_cache_backend()
        cache.set(
            build_entry_key(
                _current_version(cache), persona_id, is_admin, user_group_ids
            ),
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
