"""Build the offline capability catalog from https://models.dev/api.json.

Run with a downloaded source file to reproduce a reviewed snapshot:
    uv run python backend/scripts/update_model_catalog.py models.dev.json
"""

import argparse
import gzip
import json
from pathlib import Path

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

PROVIDER_ALIASES = {
    "amazon-bedrock": "bedrock",
    "google-vertex": "vertex_ai",
    "google": "gemini",
    "togetherai": "together_ai",
    "fireworks-ai": "fireworks_ai",
}


class Limits(BaseModel):
    context: int = 0
    input: int | None = None
    output: int = 0


class Modalities(BaseModel):
    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class SourceModel(BaseModel):
    name: str
    family: str = ""
    limit: Limits = Field(default_factory=Limits)
    modalities: Modalities = Field(default_factory=Modalities)
    cost: dict[str, JsonValue] = Field(default_factory=dict)
    reasoning: bool = False
    tool_call: bool = False


class SourceProvider(BaseModel):
    models: dict[str, SourceModel]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "onyx" / "llm"
    source = TypeAdapter(dict[str, SourceProvider]).validate_json(
        args.source.read_bytes()
    )
    catalog: dict[str, dict[str, JsonValue]] = {}
    for provider_id, provider in source.items():
        provider_name = PROVIDER_ALIASES.get(provider_id, provider_id)
        for model_id, model in provider.models.items():
            metadata: dict[str, JsonValue] = {
                "display_name": model.name,
                "model_provider": provider_name,
                "max_input_tokens": model.limit.input or model.limit.context,
                "max_output_tokens": model.limit.output,
                "mode": "embedding"
                if "embed" in model.family or "embed" in model_id
                else "chat",
                "supports_reasoning": model.reasoning,
                "supports_function_calling": model.tool_call,
                "supports_vision": "image" in model.modalities.input,
            }
            for source_key, target_key in (
                ("input", "input_cost_per_token"),
                ("output", "output_cost_per_token"),
                ("cache_read", "cache_read_input_token_cost"),
                ("cache_write", "cache_creation_input_token_cost"),
            ):
                value = model.cost.get(source_key)
                if isinstance(value, (int, float)):
                    metadata[target_key] = value / 1_000_000
            catalog[f"{provider_name}/{model_id}"] = metadata
    overrides = TypeAdapter(dict[str, dict[str, JsonValue]]).validate_json(
        (root / "model_catalog_overrides.json").read_bytes()
    )
    for key, metadata in overrides.items():
        catalog.setdefault(key, {}).update(metadata)
    output: Path = args.output or root / "model_catalog.json.gz"
    data = (json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n").encode()
    output.write_bytes(gzip.compress(data, mtime=0))


if __name__ == "__main__":
    main()
