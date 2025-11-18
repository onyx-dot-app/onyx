"""Prompt caching framework for LLM providers.

This module provides a framework for enabling prompt caching across different
LLM providers. It supports both implicit caching (automatic provider-side caching)
and explicit caching (with cache metadata management).
"""

from onyx.llm.prompt_cache.cache_manager import CacheManager
from onyx.llm.prompt_cache.cache_manager import generate_cache_key_hash
from onyx.llm.prompt_cache.interfaces import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider
from onyx.llm.prompt_cache.utils import normalize_language_model_input

__all__ = [
    "CacheManager",
    "CacheMetadata",
    "generate_cache_key_hash",
    "normalize_language_model_input",
    "NoOpPromptCacheProvider",
    "PromptCacheProvider",
]
