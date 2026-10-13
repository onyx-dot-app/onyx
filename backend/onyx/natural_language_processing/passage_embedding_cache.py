"""Fail-open cache for passage embeddings used by the indexing pipeline."""

import hashlib
import struct

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

logger = setup_logger()
_KEY_PREFIX = "passage_emb"


def _key(text: str, model_name: str, tenant_id: str | None) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    tenant = tenant_id or "global"
    return f"{_KEY_PREFIX}:{tenant}:{model_name}:{digest}"


def _unpack(value: bytes) -> Embedding | None:
    if not value or len(value) % 4:
        return None
    try:
        return list(struct.unpack(f"<{len(value) // 4}f", value))
    except struct.error:
        return None


def get_cached_passage_embeddings(
    texts: list[str], model_name: str, tenant_id: str | None
) -> list[Embedding | None]:
    if not texts:
        return []
    try:
        cache = get_cache_backend()
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("Unable to initialize passage embedding cache", exc_info=True)
        return [None] * len(texts)
    values: list[Embedding | None] = []
    for text in texts:
        try:
            raw = cache.get(_key(text, model_name, tenant_id))
            values.append(_unpack(raw) if raw is not None else None)
        except CACHE_TRANSIENT_ERRORS:
            logger.debug("Passage embedding cache lookup failed", exc_info=True)
            values.append(None)
    return values


def cache_passage_embeddings(
    texts: list[str], embeddings: list[Embedding], model_name: str,
    tenant_id: str | None, ttl_seconds: int
) -> None:
    if len(texts) != len(embeddings):
        raise ValueError("texts and embeddings must have the same length")
    try:
        cache = get_cache_backend()
    except CACHE_TRANSIENT_ERRORS:
        logger.warning("Unable to initialize passage embedding cache", exc_info=True)
        return
    for text, embedding in zip(texts, embeddings, strict=True):
        try:
            packed = struct.pack(f"<{len(embedding)}f", *embedding)
            cache.set(_key(text, model_name, tenant_id), packed, ex=ttl_seconds)
        except struct.error:
            logger.debug("Passage embedding cache write failed", exc_info=True)
        except CACHE_TRANSIENT_ERRORS:
            logger.debug("Passage embedding cache write failed", exc_info=True)
