"""Typed access to the vendored model catalog in ``price_table/``.

This catalog is the single source of truth for model pricing, limits, and
capability metadata. LiteLLM's ``model_cost`` table is not consulted —
litellm remains only as the provider call/translation layer.

The catalog is refreshed by ``backend/scripts/sync_price_table.py`` (weekly CI
job), which aggregates models.dev (canonical chat pricing), litellm's cost map
(``mode``, per-image/per-second pricing, the 1h cache-write tier, non-chat
models), and OpenRouter (gap-fill pricing for its section).
``model_metadata_enrichments.json`` adds Onyx-owned display fields
(display_name / model_vendor / model_version) on top.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from onyx.utils.logger import setup_logger

logger = setup_logger()

_CATALOG_DIR = Path(__file__).parent / "price_table"
_SUPPLEMENT_PATH = _CATALOG_DIR / "_supplement.json"
_ENRICHMENTS_PATH = Path(__file__).parent / "model_metadata_enrichments.json"

# Bedrock cross-region inference-profile prefixes (us., eu., global., apac.,
# ...). Matches the sync script's alias derivation.
_BEDROCK_REGION_PREFIXES = (
    "us",
    "eu",
    "global",
    "apac",
    "ap",
    "ca",
    "au",
    "jp",
    "sa",
    "af",
    "me",
)

# Providers whose entries should own a bare (unprefixed) model key when several
# provider sections carry the same model id (e.g. "gpt-4o" under both "openai"
# and "azure"). Matches the canonical-owner convention litellm's map followed.
_BARE_KEY_PROVIDER_PRIORITY = (
    "openai",
    "anthropic",
    "gemini",
    "vertex_ai",
    "azure",
    "bedrock",
)

# Extra entries merged into the rendered map. These register capability flags
# for models that live outside the catalog (locally hosted Ollama models have
# no catalog entry but do support tool calls).
_EXTRA_MODEL_ENTRIES: dict[str, dict[str, Any]] = {
    f"{provider}/{model}": {"supports_function_calling": True}
    for provider in ("ollama_chat", "ollama")
    for model in (
        "gpt-oss:120b-cloud",
        "gpt-oss:120b",
        "gpt-oss:20b-cloud",
        "gpt-oss:20b",
        "deepseek-r1:latest",
        "deepseek-r1:1.5b",
        "deepseek-r1:7b",
        "deepseek-r1:8b",
        "deepseek-r1:14b",
        "deepseek-r1:32b",
        "deepseek-r1:70b",
        "deepseek-r1:671b",
        "deepseek-v3.1:latest",
        "deepseek-v3.1:671b",
        "deepseek-v3.1:671b-cloud",
        "gemma3:latest",
        "gemma3:270m",
        "gemma3:1b",
        "gemma3:4b",
        "gemma3:12b",
        "gemma3:27b",
        "qwen3-coder:latest",
        "qwen3-coder:30b",
        "qwen3-coder:480b",
        "qwen3-coder:480b-cloud",
        "qwen3-vl:latest",
        "qwen3-vl:2b",
        "qwen3-vl:4b",
        "qwen3-vl:8b",
        "qwen3-vl:30b",
        "qwen3-vl:32b",
        "qwen3-vl:235b",
        "qwen3-vl:235b-cloud",
        "qwen3-vl:235b-instruct-cloud",
        "kimi-k2:1t",
        "kimi-k2:1t-cloud",
        "glm-4.6:cloud",
        "glm-4.6",
        "glm-4.6-cloud",
    )
}


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict[str, Any]]:
    """Load every vendored provider file. Returns
    {provider: {"models": {id: entry}, "aliases": {alias: id}}}."""
    catalog: dict[str, dict[str, Any]] = {}
    if not _CATALOG_DIR.is_dir():
        logger.error("Model catalog directory missing: %s", _CATALOG_DIR)
        return catalog

    for path in sorted(_CATALOG_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text())
            catalog[path.stem] = {
                "models": data.get("models") or {},
                "aliases": data.get("aliases") or {},
            }
        except Exception:
            logger.exception("Failed to load catalog file %s", path)

    # Hand-maintained entries fill upstream gaps (models.dev prunes deprecated
    # generations). Supplement entries never override synced data.
    if _SUPPLEMENT_PATH.exists():
        try:
            supplement = json.loads(_SUPPLEMENT_PATH.read_text())
            for provider, section in supplement.items():
                if provider.startswith("_"):
                    continue
                target = catalog.setdefault(provider, {"models": {}, "aliases": {}})
                for model_id, entry in (section.get("models") or {}).items():
                    if model_id not in target["models"]:
                        target["models"][model_id] = entry
                    if provider == "bedrock":
                        for region in _BEDROCK_REGION_PREFIXES:
                            target["aliases"].setdefault(
                                f"{region}.{model_id}", model_id
                            )
                target["aliases"].update(
                    {
                        k: v
                        for k, v in (section.get("aliases") or {}).items()
                        if k not in target["aliases"]
                    }
                )
        except Exception:
            logger.exception("Failed to load catalog supplement")
    return catalog


def provider_names() -> list[str]:
    return sorted(_catalog())


def iter_models(provider: str, mode: str | None = None) -> list[str]:
    """Real model ids under a provider (aliases excluded). Pass ``mode``
    (e.g. "chat") to restrict to that kind; entries without a mode field
    are chat models."""
    models = _catalog().get(provider, {}).get("models", {})
    if mode is None:
        return sorted(models)
    return sorted(
        model_id
        for model_id, entry in models.items()
        if entry.get("mode", "chat") == mode
    )


def _lookup_provider(provider: str, model_name: str) -> dict[str, Any] | None:
    section = _catalog().get(provider)
    if not section:
        return None
    entry = section["models"].get(model_name)
    if entry is not None:
        return entry
    target = section["aliases"].get(model_name)
    return section["models"].get(target) if target else None


def _strip_colon_tag(model_name: str) -> str:
    return ":".join(model_name.split(":")[:-1]) if ":" in model_name else model_name


def find_model_entry(provider: str, model_name: str) -> dict[str, Any] | None:
    """Resolve a catalog entry for (provider, model_name).

    Tries provider-scoped direct hits and aliases first, with the same name
    normalization find_model_obj used (extra provider prefix strip, Ollama
    ``:tag`` strip), then a bare-name scan across providers.
    """
    candidates = [model_name]
    if "/" in model_name:
        candidates.append(model_name.split("/", 1)[1])
    candidates.extend(
        _strip_colon_tag(c) for c in list(candidates) if ":" in c.split("/")[-1]
    )

    for candidate in candidates:
        entry = _lookup_provider(provider, candidate)
        if entry is not None:
            return entry

    for other in provider_names():
        if other == provider:
            continue
        for candidate in candidates:
            entry = _lookup_provider(other, candidate)
            if entry is not None:
                return entry
    return None


# Providers whose inference runs on customer-owned hardware — there is no
# per-token API bill, so catalog pricing (and the cross-provider fallback scan,
# which could match identically-named hosted models) must not apply. Admins
# can still assign a rate via ModelCostOverride.
_LOCAL_PROVIDERS = frozenset({"ollama_chat", "lm_studio"})


def find_model_cost(provider: str, model_name: str) -> dict[str, Any] | None:
    """Cost block for a model: {input, output, cache_read?, cache_write?,
    context_over_200k?}. Values are USD per million tokens."""
    if provider in _LOCAL_PROVIDERS:
        return None
    entry = find_model_entry(provider, model_name)
    return entry.get("cost") if entry else None


def _compat_entry(provider: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Render a catalog entry in the legacy litellm.model_cost shape consumed
    by model_capabilities and the model name parser."""
    limit = entry.get("limit") or {}
    modalities = entry.get("modalities") or {}
    inputs = modalities.get("input") or []
    display_name = re.sub(r"\s*\(latest\)\s*$", "", entry.get("name") or "")

    return {
        "litellm_provider": provider,
        "mode": entry.get("mode") or "chat",
        "max_input_tokens": limit.get("input") or limit.get("context"),
        "max_tokens": limit.get("context"),
        "max_output_tokens": limit.get("output"),
        "supports_vision": "image" in inputs,
        "supports_reasoning": entry.get("reasoning"),
        "supports_none_reasoning_effort": entry.get("supports_none_reasoning_effort"),
        "supports_function_calling": entry.get("tool_call"),
        "supports_response_schema": entry.get("structured_output"),
        "supports_pdf_input": "pdf" in inputs,
        "display_name": display_name or None,
    }


@lru_cache(maxsize=1)
def build_model_map() -> dict[str, dict[str, Any]]:
    """Render the catalog as a litellm.model_cost-shaped dict.

    Keys are ``{provider}/{model_id}`` plus bare ``{model_id}`` (canonical
    owner wins collisions), matching what find_model_obj and the name parser
    resolve against. Aliases get the same two forms. Enrichments and extra
    entries merge on top, as they did into litellm.model_cost.
    """
    catalog = _catalog()
    ordered_providers = [p for p in _BARE_KEY_PROVIDER_PRIORITY if p in catalog]
    ordered_providers += sorted(
        p for p in catalog if p not in _BARE_KEY_PROVIDER_PRIORITY
    )

    model_map: dict[str, dict[str, Any]] = {}
    for provider in ordered_providers:
        section = catalog[provider]
        for model_id, entry in section["models"].items():
            compat = _compat_entry(provider, entry)
            model_map[f"{provider}/{model_id}"] = compat
            model_map.setdefault(model_id, compat)
        for alias, target in section["aliases"].items():
            entry = section["models"].get(target)
            if entry is None:
                continue
            compat = _compat_entry(provider, entry)
            model_map[f"{provider}/{alias}"] = compat
            model_map.setdefault(alias, compat)

    model_map.update(_EXTRA_MODEL_ENTRIES)

    if _ENRICHMENTS_PATH.exists():
        try:
            enrichments = json.loads(_ENRICHMENTS_PATH.read_text())
            for model_key, metadata in enrichments.items():
                if model_key in model_map:
                    model_map[model_key].update(metadata)
                else:
                    model_map[model_key] = dict(metadata)
        except Exception:
            logger.exception("Failed to load model metadata enrichments")

    return model_map


# Name-pattern heuristic for models outside the catalog — used to filter
# model lists fetched from user gateways (LiteLLM proxy, OpenRouter, LM
# Studio). Catalog-known models use their ``mode`` field instead.
_EMBEDDING_NAME_PATTERN = re.compile(
    r"embed|e5-|bge-|gte-|jina|voyage|rerank|colbert|uae-|instructor",
    re.IGNORECASE,
)


def is_embedding_model_name(model_name: str) -> bool:
    entry = build_model_map().get(model_name)
    if entry is not None and entry.get("mode"):
        return entry["mode"] == "embedding"
    return bool(_EMBEDDING_NAME_PATTERN.search(model_name.split("/")[-1]))
