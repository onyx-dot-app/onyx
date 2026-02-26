#!/usr/bin/env python3
"""Validate providers_json and write the provider matrix to GITHUB_OUTPUT."""

import json
import os
import sys


def fail(message: str) -> None:
    print(message)
    sys.exit(1)


def as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_models(raw: object, label: str) -> str:
    if isinstance(raw, str):
        models = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        models = [str(item).strip() for item in raw if str(item).strip()]
    else:
        raise ValueError(f"'models' for {label} must be a CSV string or a JSON array")

    if not models:
        raise ValueError(f"'models' must contain at least one model for {label}")
    return ",".join(models)


def parse_custom_config_json(raw: object, label: str) -> str:
    if raw is None:
        return ""

    if isinstance(raw, (dict, list)):
        return json.dumps(raw, separators=(",", ":"))

    raw_text = str(raw).strip()
    if not raw_text:
        return ""

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as ex:
        raise ValueError(
            f"'custom_config_json' for {label} must be valid JSON: {ex}"
        ) from ex

    return json.dumps(parsed, separators=(",", ":"))


def main() -> None:
    providers_json = os.environ.get("INPUT_PROVIDERS_JSON", "").strip()
    if not providers_json:
        fail("Input 'providers_json' must be non-empty")

    try:
        parsed = json.loads(providers_json)
    except json.JSONDecodeError as ex:
        fail(f"Input 'providers_json' must be valid JSON: {ex}")

    if not isinstance(parsed, list):
        fail("Input 'providers_json' must be a JSON array")

    entries: list[dict[str, str]] = []

    for i, item in enumerate(parsed, start=1):
        label = f"providers_json[{i}]"
        provider_for_entry = f"invalid_provider_{i}"
        models_csv = ""
        strict = "true"
        api_base = ""
        custom_config_json = ""
        api_key_secret = ""
        validation_error = ""

        try:
            if not isinstance(item, dict):
                raise ValueError(f"{label} must be a JSON object")

            provider = str(item.get("provider", "")).strip().lower()
            if not provider:
                raise ValueError(f"{label}.provider must be non-empty")
            provider_for_entry = provider

            models_csv = parse_models(item.get("models", ""), label)
            strict = (
                "true" if as_bool(item.get("strict", True), default=True) else "false"
            )
            api_base = str(item.get("api_base", "")).strip()
            custom_config_json = parse_custom_config_json(
                item.get("custom_config_json", ""),
                label,
            )
            api_key_secret = str(item.get("api_key_secret", "")).strip()

            if provider != "ollama_chat" and not api_key_secret:
                raise ValueError(
                    f"{label}.api_key_secret must be set for provider '{provider}'"
                )
        except ValueError as ex:
            validation_error = str(ex)

        entries.append(
            {
                "provider": provider_for_entry,
                "models": models_csv,
                "strict": strict,
                "api_base": api_base,
                "custom_config_json": custom_config_json,
                "api_key_secret": api_key_secret,
                "validation_error": validation_error,
            }
        )

    if not entries:
        fail("No provider entries were generated from 'providers_json'.")

    valid_entries = [entry for entry in entries if not entry["validation_error"]]
    if not valid_entries:
        errors = " | ".join(entry["validation_error"] for entry in entries)
        fail(
            "No valid provider entries were found in 'providers_json'. "
            f"Errors: {errors}"
        )

    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        fail("GITHUB_OUTPUT is required")

    matrix_json = json.dumps({"include": entries}, separators=(",", ":"))
    with open(github_output, "a", encoding="utf-8") as output_file:
        output_file.write(f"matrix={matrix_json}\n")


if __name__ == "__main__":
    main()
