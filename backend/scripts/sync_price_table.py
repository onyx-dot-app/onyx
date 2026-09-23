#!/usr/bin/env python3
"""Sync the models.dev catalog into the vendored Onyx price table.

Fetches https://models.dev/api.json, maps models.dev providers onto Onyx
provider keys, normalizes each model entry, derives lookup aliases (region
prefixes, version/date suffixes), and writes one JSON file per provider under
backend/onyx/llm/price_table/. Output is deterministic so diffs reflect real
upstream changes only.

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
    "ollama_chat": ["ollama-cloud"],
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

    return {
        "schema_version": 1,
        "source": SOURCE_URL,
        "providers": dict(sorted(providers.items())),
    }


def _render_outputs(table: dict[str, Any]) -> dict[str, str]:
    """filename -> file contents for the output directory."""
    meta = {"schema_version": table["schema_version"], "source": table["source"]}
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
    parser.add_argument("--source-url", default=SOURCE_URL)
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
        assert args.source_url.startswith("https://"), (
            f"refusing non-https source: {args.source_url}"
        )
        # models.dev's edge blocks the default Python-urllib UA with a 403.
        req = urllib.request.Request(  # noqa: S310
            args.source_url, headers={"User-Agent": "onyx-price-sync"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            api = json.loads(resp.read())

    outputs = _render_outputs(build_price_table(api))

    existing: dict[str, str] = {}
    if args.output_dir.exists():
        for path in args.output_dir.glob("*.json"):
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
        (args.output_dir / name).unlink()
    for name, content in outputs.items():
        if existing.get(name) != content:
            (args.output_dir / name).write_text(content)
    print(f"wrote {args.output_dir} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
