"""Validate the edits of the image generation maintenance task.

The only allowed catalog edit is retiring an image generation model with
`status: deprecated` in the supplement.
"""

import json
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any

PRICE_TABLE_DIR = Path("backend/onyx/llm/price_table")
SUPPLEMENT_PATH = PRICE_TABLE_DIR / "_supplement.json"
IMAGE_GEN_DIR = Path("backend/onyx/image_gen")


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _upstream_models(provider: str) -> dict[str, Any]:
    path = PRICE_TABLE_DIR / f"{provider}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text()).get("models") or {}


def _base_supplement() -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"HEAD:{SUPPLEMENT_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _supplement_errors() -> list[str]:
    errors: list[str] = []
    base = _base_supplement()
    supplement = json.loads(SUPPLEMENT_PATH.read_text())
    for provider in sorted(set(base) | set(supplement)):
        base_section = base.get(provider)
        section = supplement.get(provider)
        if provider.startswith("_") or not isinstance(section, dict):
            if not _same_json(section, base_section):
                errors.append(f"{provider}: only model status may change")
            continue
        base_models = (base_section or {}).get("models") or {}
        models = section.get("models") or {}
        if not _same_json(
            {k: v for k, v in section.items() if k != "models"},
            {k: v for k, v in (base_section or {}).items() if k != "models"},
        ):
            errors.append(f"{provider}: only model status may change")
        upstream = _upstream_models(provider)
        for model_id in sorted(set(base_models) | set(models)):
            entry = models.get(model_id)
            base_entry = base_models.get(model_id)
            if model_id in models and not isinstance(entry, dict):
                errors.append(f"{provider}/{model_id}: model entry must be an object")
                continue
            if (model_id in models) == (model_id in base_models) and _same_json(
                entry, base_entry
            ):
                continue
            if not _same_json(entry, {**(base_entry or {}), "status": "deprecated"}):
                errors.append(
                    f"{provider}/{model_id}: only 'status: deprecated' may be added"
                )
                continue
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
