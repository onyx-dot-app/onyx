"""Validate the edits of the image generation maintenance task."""

import json
import py_compile
import sys
from pathlib import Path

PRICE_TABLE_DIR = Path("backend/onyx/llm/price_table")
SUPPLEMENT_PATH = PRICE_TABLE_DIR / "_supplement.json"
IMAGE_GEN_DIR = Path("backend/onyx/image_gen")


def _upstream_models(provider: str) -> dict[str, dict]:
    path = PRICE_TABLE_DIR / f"{provider}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text()).get("models") or {}


def _supplement_errors() -> list[str]:
    errors: list[str] = []
    supplement = json.loads(SUPPLEMENT_PATH.read_text())
    for provider, section in supplement.items():
        if provider.startswith("_"):
            continue
        upstream = _upstream_models(provider)
        for model_id, entry in (section.get("models") or {}).items():
            if "status" not in entry:
                continue
            if entry["status"] != "deprecated":
                errors.append(f"{provider}/{model_id}: status must be 'deprecated'")
            catalog_entry = upstream.get(model_id) or entry
            if catalog_entry.get("mode") != "image_generation":
                errors.append(
                    f"{provider}/{model_id}: only image generation models can be retired"
                )
    return errors


def main() -> int:
    errors = _supplement_errors()
    for path in sorted(IMAGE_GEN_DIR.rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as error:
            errors.append(str(error))
    for error in errors:
        print(f"::error::{error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
