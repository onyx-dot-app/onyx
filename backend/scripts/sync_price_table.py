#!/usr/bin/env python3
"""Sync upstream model catalogs into the vendored Onyx price table.

Sources, in precedence order:

1. models.dev api.json — canonical chat-model pricing, limits, capabilities.
2. litellm model_prices_and_context_window.json — enriches existing entries
   with `mode`, per-image cost, and the 1h cache-write tier; also contributes
   non-chat models (embedding, image, audio, rerank) that models.dev does not
   carry.
3. OpenRouter /api/v1/models — fills missing prices on openrouter entries and
   adds models models.dev has not indexed yet (listed there = callable).

models.dev provider slugs are mapped onto Onyx provider keys; each model entry
is normalized and lookup aliases are derived (region prefixes, version/date
suffixes). One JSON file per provider is written under
backend/onyx/llm/price_table/. Output is deterministic so diffs reflect real
upstream changes only. Secondary-source failures warn and degrade to the
models.dev-only output rather than failing the sync.

Run weekly by .github/workflows/weekly-models-dev-price-sync.yml. Local use:

    python3 backend/scripts/sync_price_table.py
    python3 backend/scripts/sync_price_table.py --input /tmp/api.json
    python3 backend/scripts/sync_price_table.py --check   # exit 1 if files would change
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

SOURCE_URL = "https://models.dev/api.json"
LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "onyx" / "llm" / "price_table"

# Onyx provider key -> models.dev provider slugs, in preference order.
# Later slugs fill gaps; earlier entries win on model-id collisions.
PROVIDER_MAP: dict[str, list[str]] = {
    # Well-known providers (onyx/llm/constants.py LlmProviderNames)
    "openai": ["openai"],
    "anthropic": ["anthropic"],
    "google": ["google"],
    "vertex_ai": ["google-vertex", "google-vertex-anthropic"],
    "bedrock": ["amazon-bedrock"],
    "bedrock_converse": ["amazon-bedrock"],
    "openrouter": ["openrouter"],
    "azure": ["azure", "azure-cognitive-services"],
    # ollama_chat is deliberately unmapped: self-hosted Ollama has no API bill,
    # and mapping it to ollama-cloud would price local inference at cloud rates.
    "lm_studio": ["lmstudio"],
    "mistral": ["mistral"],
    "nebius_tokenfactory": ["nebius"],
    # Custom-provider keys (onyx/llm/constants.py PROVIDER_DISPLAY_NAMES)
    "azure_ai": ["azure", "azure-cognitive-services"],
    "cohere_chat": ["cohere"],
    "deepinfra": ["deepinfra"],
    "fireworks_ai": ["fireworks-ai"],
    "friendliai": ["friendli"],
    "github_copilot": ["github-copilot"],
    "huggingface": ["huggingface"],
    "meta_llama": ["llama"],
    "minimax": ["minimax"],
    "nvidia_nim": ["nvidia"],
    "oci": ["oci"],
    "ovhcloud": ["ovhcloud"],
    "together_ai": ["togetherai"],
    "vercel_ai_gateway": ["vercel"],
    "volcengine": ["volcengine"],
    "wandb": ["wandb"],
    "watsonx": ["watsonx"],
    "zai": ["zai"],
    # Vendor names users also configure as custom providers
    "groq": ["groq"],
    "deepseek": ["deepseek"],
    "xai": ["xai"],
    "cohere": ["cohere"],
    "perplexity": ["perplexity"],
    "databricks": ["databricks"],
    "ai21": ["ai21"],
    "nvidia": ["nvidia"],
    "cerebras": ["cerebras"],
    "baseten": ["baseten"],
    "novita-ai": ["novita-ai"],
    "moonshotai": ["moonshotai"],
    "zhipuai": ["zhipuai"],
}

# Scalar fields kept from each models.dev model entry. cost/limit/modalities
# subdicts are copied verbatim — already the shape consumers need.
_SCALAR_FIELDS = (
    "name",
    "family",
    "release_date",
    "status",
    "reasoning",
    "tool_call",
    "structured_output",
    "attachment",
    "temperature",
    "open_weights",
)
_DICT_FIELDS = ("cost", "limit", "modalities")

# Bedrock cross-region inference-profile prefixes (us., eu., global., apac., ...).
_REGION_PREFIX_RE = re.compile(r"^(us|eu|global|apac|ap|ca|au|jp|sa|af|me)\.")
# Vertex-style revision suffix: claude-sonnet-4@20250514
_AT_SUFFIX_RE = re.compile(r"@[^@]+$")
# Bedrock version suffix: ...-v1:0
_VERSION_SUFFIX_RE = re.compile(r"-v\d+:\d+$")
# Dated model variant: ...-20250929
_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")


def _alias_candidates(model_id: str) -> list[str]:
    """Mechanical name variants that should resolve to this model.

    Emitted most-specific to least-specific; each step chains off the previous
    so a fully-qualified Bedrock id yields all of its shorter forms.
    """
    candidates: list[str] = []
    current = model_id

    stripped = _REGION_PREFIX_RE.sub("", current)
    if stripped != current:
        candidates.append(stripped)
        current = stripped

    stripped = _AT_SUFFIX_RE.sub("", current)
    if stripped != current:
        candidates.append(stripped)
        current = stripped

    stripped = _VERSION_SUFFIX_RE.sub("", current)
    if stripped != current:
        candidates.append(stripped)
        current = stripped

    stripped = _DATE_SUFFIX_RE.sub("", current)
    if stripped != current:
        candidates.append(stripped)

    return candidates


def _normalize_model(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in _SCALAR_FIELDS:
        if field in entry:
            out[field] = entry[field]
    for field in _DICT_FIELDS:
        if entry.get(field) is not None:
            out[field] = entry[field]
    return out


# Entry fields models.dev publishes that we deliberately do not vendor. New
# upstream fields appear in the unmapped-field report instead of being
# silently dropped — that report is how we learn the schema grew.
_IGNORED_ENTRY_FIELDS = {
    "id",
    "description",
    "last_updated",
    "reasoning_options",
    "knowledge",
    "interleaved",
    "provider",
    "experimental",
}

# Minimum fraction of entries expected to carry each field, measured against
# the real feed (~95% cost, ~100% limit). If models.dev renames or drops a
# field the coverage collapses and the sync fails rather than vendoring a
# gutted table.
_MIN_FIELD_COVERAGE = {
    ("cost", "input"): 0.80,
    ("cost", "output"): 0.80,
    ("limit", "context"): 0.90,
}


def _check_source_schema(api: dict[str, Any]) -> None:
    """Fail loudly when the upstream payload's shape drifts from what the
    transform expects; report fields we do not map so additions surface."""
    coverage = dict.fromkeys(_MIN_FIELD_COVERAGE, 0)
    unmapped: dict[str, int] = {}
    total = 0
    for slug, provider in api.items():
        assert isinstance(provider.get("models"), dict), (
            f"upstream entry {slug!r} has no 'models' dict — schema changed?"
        )
        for entry in provider["models"].values():
            if not isinstance(entry, dict):
                continue
            total += 1
            for section, field in _MIN_FIELD_COVERAGE:
                value = entry.get(section)
                if isinstance(value, dict) and value.get(field) is not None:
                    coverage[(section, field)] += 1
            for key in entry:
                if (
                    key not in _SCALAR_FIELDS
                    and key not in _DICT_FIELDS
                    and key not in _IGNORED_ENTRY_FIELDS
                ):
                    unmapped[key] = unmapped.get(key, 0) + 1

    assert total > 0, "upstream catalog contained no model entries"
    for (section, field), minimum in _MIN_FIELD_COVERAGE.items():
        ratio = coverage[(section, field)] / total
        assert ratio >= minimum, (
            f"only {ratio:.0%} of entries carry {section}.{field} "
            f"(expected ≥{minimum:.0%}) — upstream renamed or dropped the field"
        )
    if unmapped:
        print(
            "upstream fields not vendored: "
            + ", ".join(f"{k} ({n} models)" for k, n in sorted(unmapped.items())),
            file=sys.stderr,
        )


def _build_provider_section(
    api: dict[str, Any], slugs: list[str]
) -> dict[str, Any] | None:
    models: dict[str, Any] = {}
    for slug in slugs:
        for model_id, entry in (api.get(slug, {}).get("models") or {}).items():
            models.setdefault(model_id, _normalize_model(entry))
    if not models:
        return None

    # Alias -> canonical model id. Candidates that are themselves real model
    # ids need no alias. An alias claimed by more than one canonical id is
    # ambiguous — drop it and let lookups fall back rather than mis-price.
    claims: dict[str, set[str]] = {}
    for model_id in models:
        for alias in _alias_candidates(model_id):
            if alias not in models:
                claims.setdefault(alias, set()).add(model_id)
    aliases = {
        alias: min(ids) if len(ids) == 1 else None for alias, ids in claims.items()
    }
    aliases = {a: c for a, c in aliases.items() if c is not None}

    return {
        "models_dev_providers": slugs,
        "models": dict(sorted(models.items())),
        "aliases": dict(sorted(aliases.items())),
    }


def build_price_table(api: dict[str, Any]) -> dict[str, Any]:
    _check_source_schema(api)

    providers: dict[str, Any] = {}
    missing: list[str] = []
    for onyx_key, slugs in PROVIDER_MAP.items():
        section = _build_provider_section(api, slugs)
        if section is None:
            missing.append(onyx_key)
        else:
            providers[onyx_key] = section

    if missing:
        print(
            f"WARNING: no models.dev data for: {', '.join(missing)}",
            file=sys.stderr,
        )

    # Guard against a gutted upstream response landing as a "sync".
    total_models = sum(len(p["models"]) for p in providers.values())
    for required in ("anthropic", "openai", "amazon-bedrock", "openrouter"):
        assert required in api, f"upstream catalog missing provider {required!r}"
    assert total_models > 1000, (
        f"only {total_models} models after transform — upstream regression?"
    )

    return dict(sorted(providers.items()))


# ---------------------------------------------------------------------------
# Secondary source: litellm model_prices_and_context_window.json
#
# litellm covers modalities models.dev ignores (embedding, image, audio,
# rerank) and is the only public source for Anthropic's 1h cache-write rate.
# It enriches existing entries in place; chat-mode models it alone knows are
# NOT added — models.dev stays canonical for chat coverage.
# ---------------------------------------------------------------------------

# litellm_provider tag -> Onyx provider keys it should enrich. Vertex uses a
# zoo of suffixed tags handled by prefix match.
_LITELLM_PROVIDER_MAP: dict[str, tuple[str, ...]] = {
    "openai": ("openai",),
    "azure": ("azure", "azure_ai"),
    "anthropic": ("anthropic",),
    "gemini": ("google",),
    "bedrock": ("bedrock", "bedrock_converse"),
    "openrouter": ("openrouter",),
    "deepseek": ("deepseek",),
    "xai": ("xai",),
    "mistral": ("mistral",),
    "groq": ("groq",),
    "cohere": ("cohere", "cohere_chat"),
    "cohere_chat": ("cohere_chat",),
    "deepinfra": ("deepinfra",),
    "together_ai": ("together_ai",),
    "fireworks_ai": ("fireworks_ai",),
    "perplexity": ("perplexity",),
    "databricks": ("databricks",),
    "voyage": (),
    "dashscope": (),
    "nvidia_nim": ("nvidia_nim", "nvidia"),
    "watsonx": ("watsonx",),
    "oci": ("oci",),
    "github_copilot": ("github_copilot",),
    "huggingface": ("huggingface",),
    "ai21": ("ai21",),
    "baseten": ("baseten",),
    "cerebras": ("cerebras",),
    "moonshot": ("moonshotai",),
    "zai": ("zai",),
    "minimax": ("minimax",),
}

# Per-token litellm cost fields -> our per-Mtok cost keys.
_LITELLM_TOKEN_COST_FIELDS = {
    "input_cost_per_token": "input",
    "output_cost_per_token": "output",
    "cache_read_input_token_cost": "cache_read",
    "cache_creation_input_token_cost": "cache_write",
    "cache_creation_input_token_cost_above_1hr": "cache_write_above_1hr",
}

# Per-unit litellm cost fields -> our cost keys, USD per unit (image, second).
_LITELLM_UNIT_COST_FIELDS = {
    "output_cost_per_image": "image",
    "input_cost_per_image": "image_input",
    "output_cost_per_second": "second",
    "input_cost_per_second": "second_input",
}

# litellm modes that are chat-shaped; models.dev stays canonical for these.
_LITELLM_CHAT_MODES = {"chat", "responses", "completion"}


def _litellm_onyx_providers(tag: str | None) -> tuple[str, ...]:
    if not tag:
        return ()
    if tag.startswith("vertex_ai"):
        return ("vertex_ai",)
    return _LITELLM_PROVIDER_MAP.get(tag, ())


def _litellm_cost(entry: dict[str, Any]) -> dict[str, float]:
    """litellm cost fields -> our cost block (per-Mtok tokens, per-unit rest)."""
    cost: dict[str, float] = {}
    for src_key, dst_key in _LITELLM_TOKEN_COST_FIELDS.items():
        value = entry.get(src_key)
        if value is not None:
            cost[dst_key] = float(value) * 1_000_000
    for src_key, dst_key in _LITELLM_UNIT_COST_FIELDS.items():
        value = entry.get(src_key)
        if value is not None:
            cost[dst_key] = float(value)
    return cost


def _litellm_new_entry(model_key: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Minimal catalog entry for a non-chat model only litellm carries."""
    out: dict[str, Any] = {"name": model_key, "mode": entry["mode"]}
    cost = _litellm_cost(entry)
    if cost:
        out["cost"] = cost
    if entry.get("supports_none_reasoning_effort"):
        out["supports_none_reasoning_effort"] = True
    context = entry.get("max_input_tokens") or entry.get("max_tokens")
    output = entry.get("max_output_tokens")
    if context or output:
        out["limit"] = {
            k: v for k, v in (("context", context), ("output", output)) if v is not None
        }
    return out


def merge_litellm(providers: dict[str, Any], litellm_map: dict[str, Any]) -> None:
    """Enrich catalog entries with litellm-only fields; add non-chat models."""
    enriched = added = 0
    for model_key, entry in litellm_map.items():
        if not isinstance(entry, dict):
            continue
        onyx_keys = _litellm_onyx_providers(entry.get("litellm_provider"))
        if not onyx_keys:
            continue

        # litellm keys are bare model ids or "<litellm_provider>/<id>".
        model_id = model_key
        provider_tag = entry.get("litellm_provider") or ""
        if model_key.startswith(f"{provider_tag}/"):
            model_id = model_key[len(provider_tag) + 1 :]

        for onyx_key in onyx_keys:
            section = providers.get(onyx_key)
            if section is None:
                continue
            models = section["models"]
            target_id = model_id
            if target_id not in models:
                target_id = section["aliases"].get(model_id, model_id)
            existing = models.get(target_id)

            if existing is None:
                mode = entry.get("mode")
                if mode and mode not in _LITELLM_CHAT_MODES:
                    models[model_id] = _litellm_new_entry(model_id, entry)
                    added += 1
                continue

            mode = entry.get("mode")
            if mode:
                existing.setdefault("mode", mode)
            if entry.get("supports_none_reasoning_effort"):
                existing["supports_none_reasoning_effort"] = True
            litellm_cost = _litellm_cost(entry)
            if litellm_cost:
                cost = existing.setdefault("cost", {})
                # models.dev rates win; litellm only supplies fields it lacks.
                for key, value in litellm_cost.items():
                    cost.setdefault(key, value)
                enriched += 1

    print(f"litellm merge: enriched {enriched} entries, added {added} non-chat models")


# ---------------------------------------------------------------------------
# Secondary source: OpenRouter /api/v1/models
#
# Machine-readable pricing for everything the gateway serves. Fills missing
# cost fields on models.dev entries and adds models not yet indexed upstream —
# being listed on OpenRouter means the model is callable through it.
# ---------------------------------------------------------------------------


def _openrouter_entry(raw: dict[str, Any]) -> dict[str, Any] | None:
    pricing = raw.get("pricing") or {}
    try:
        prompt = float(pricing.get("prompt") or 0)
        completion = float(pricing.get("completion") or 0)
    except (TypeError, ValueError):
        return None
    if prompt == 0 and completion == 0:
        return None

    cost: dict[str, float] = {
        "input": prompt * 1_000_000,
        "output": completion * 1_000_000,
    }
    for src_key, dst_key in (
        ("input_cache_read", "cache_read"),
        ("input_cache_write", "cache_write"),
    ):
        try:
            value = pricing.get(src_key)
            if value is not None:
                cost[dst_key] = float(value) * 1_000_000
        except (TypeError, ValueError):
            continue
    # pricing.image is USD per image, not per token.
    try:
        if pricing.get("image") is not None:
            cost["image_input"] = float(pricing["image"])
    except (TypeError, ValueError):
        pass

    entry: dict[str, Any] = {"name": raw.get("name") or raw["id"], "cost": cost}
    context = raw.get("context_length")
    max_out = (raw.get("top_provider") or {}).get("max_completion_tokens")
    if context or max_out:
        entry["limit"] = {
            k: v for k, v in (("context", context), ("output", max_out)) if v
        }
    arch = raw.get("architecture") or {}
    if arch.get("input_modalities") or arch.get("output_modalities"):
        entry["modalities"] = {
            k: v
            for k, v in (
                ("input", arch.get("input_modalities")),
                ("output", arch.get("output_modalities")),
            )
            if v
        }
    params = raw.get("supported_parameters") or []
    entry["tool_call"] = "tools" in params
    entry["structured_output"] = "structured_outputs" in params or (
        "response_format" in params
    )
    entry["reasoning"] = "reasoning" in params
    return entry


def merge_openrouter(
    providers: dict[str, Any], or_models: list[dict[str, Any]]
) -> None:
    section = providers.get("openrouter")
    if section is None:
        return
    models = section["models"]
    filled = added = 0
    for raw in or_models:
        model_id = raw.get("id")
        if not model_id:
            continue
        merged = _openrouter_entry(raw)
        if merged is None:
            continue
        existing = models.get(model_id)
        if existing is None:
            existing = models.get(section["aliases"].get(model_id, ""))
        if existing is None:
            models[model_id] = merged
            added += 1
            continue
        cost = existing.setdefault("cost", {})
        for key, value in merged["cost"].items():
            if key not in cost:
                cost[key] = value
                filled += 1
    print(f"openrouter merge: filled {filled} missing rates, added {added} models")


def _check_litellm_schema(litellm_map: dict[str, Any]) -> None:
    """litellm entries must carry litellm_provider/mode and token-cost fields —
    a schema change would silently degrade the merge."""
    total = tagged = priced = 0
    for entry in litellm_map.values():
        if not isinstance(entry, dict):
            continue
        total += 1
        if entry.get("litellm_provider") and entry.get("mode"):
            tagged += 1
        if entry.get("input_cost_per_token") is not None:
            priced += 1
    assert total > 1000, f"litellm map has only {total} entries — upstream regression?"
    assert tagged / total >= 0.95, (
        f"only {tagged / total:.0%} of litellm entries carry "
        "litellm_provider+mode — upstream renamed or dropped the fields"
    )
    assert priced / total >= 0.70, (
        f"only {priced / total:.0%} of litellm entries carry "
        "input_cost_per_token — upstream renamed or dropped the field"
    )


def _check_openrouter_schema(models: list[Any]) -> None:
    """OpenRouter items must carry id and pricing.prompt/completion."""
    total = priced = 0
    for raw in models:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        total += 1
        pricing = raw.get("pricing")
        if (
            isinstance(pricing, dict)
            and pricing.get("prompt") is not None
            and pricing.get("completion") is not None
        ):
            priced += 1
    assert total > 100, f"OpenRouter listed only {total} models — schema changed?"
    assert priced / total >= 0.95, (
        f"only {priced / total:.0%} of OpenRouter models carry "
        "pricing.prompt+completion — upstream renamed or dropped the fields"
    )


def _fetch_json(url: str, timeout: int = 60) -> Any:
    assert url.startswith("https://"), f"refusing non-https source: {url}"
    # models.dev's edge blocks the default Python-urllib UA with a 403.
    req = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "onyx-price-sync"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read())


def _fetch_optional(url: str, label: str) -> Any | None:
    try:
        return _fetch_json(url)
    except Exception as e:
        print(
            f"WARNING: {label} fetch failed ({e}); continuing without it",
            file=sys.stderr,
        )
        return None


def _render_outputs(table: dict[str, Any]) -> dict[str, str]:
    """filename -> file contents for the output directory."""
    meta = {
        "schema_version": table["schema_version"],
        "sources": table["sources"],
    }
    outputs = {
        "_meta.json": json.dumps(meta, indent=2, sort_keys=True) + "\n",
    }
    for provider, section in table["providers"].items():
        outputs[f"{provider}.json"] = (
            json.dumps(section, indent=2, sort_keys=True) + "\n"
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="local api.json instead of fetching")
    parser.add_argument(
        "--litellm-input", type=Path, help="local litellm cost map instead of fetching"
    )
    parser.add_argument(
        "--openrouter-input",
        type=Path,
        help="local OpenRouter /api/v1/models response instead of fetching",
    )
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--litellm-url", default=LITELLM_URL)
    parser.add_argument("--openrouter-url", default=OPENROUTER_URL)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the output files would change; writes nothing",
    )
    args = parser.parse_args()

    if args.input:
        api = json.loads(args.input.read_text())
    else:
        api = _fetch_json(args.source_url)

    litellm_map = (
        json.loads(args.litellm_input.read_text())
        if args.litellm_input
        else _fetch_optional(args.litellm_url, "litellm cost map")
    )
    openrouter_models = (
        json.loads(args.openrouter_input.read_text()).get("data")
        if args.openrouter_input
        else (_fetch_optional(args.openrouter_url, "OpenRouter") or {}).get("data")
    )

    providers = build_price_table(api)
    if litellm_map:
        _check_litellm_schema(litellm_map)
        merge_litellm(providers, litellm_map)
    if openrouter_models:
        _check_openrouter_schema(openrouter_models)
        merge_openrouter(providers, openrouter_models)

    table = {
        "schema_version": 2,
        "sources": [args.source_url, args.litellm_url, args.openrouter_url],
        "providers": providers,
    }
    outputs = _render_outputs(table)

    existing: dict[str, str] = {}
    if args.output_dir.exists():
        for path in args.output_dir.glob("*.json"):
            # Files prefixed with "_" are hand-maintained (e.g.
            # _supplement.json) and never owned by the sync — except
            # _meta.json, which the sync writes itself.
            if not path.name.startswith("_") or path.name == "_meta.json":
                existing[path.name] = path.read_text()

    if existing == outputs:
        print("price table already up to date")
        return 0

    changed = sorted(
        (set(outputs) - set(existing))
        | {k for k in outputs if existing.get(k) != outputs[k]}
    )
    summary = f"{len(changed)} files differ: {', '.join(changed[:10])}"

    if args.check:
        print(f"price table is stale ({summary})")
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in set(existing) - set(outputs):
        if not name.startswith("_"):
            (args.output_dir / name).unlink()
    for name, content in outputs.items():
        if existing.get(name) != content:
            (args.output_dir / name).write_text(content)
    print(f"wrote {args.output_dir} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
