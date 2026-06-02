"""Guards that the backend Craft-allowed provider types stay in sync with the
frontend source of truth (``BUILD_MODE_PROVIDERS`` keys in
``web/src/app/craft/onboarding/constants.ts``). Drift (e.g. adding a type on one
side only) fails CI instead of silently mismatching onboarding vs. provisioning."""

from __future__ import annotations

import re
from pathlib import Path

from onyx.server.features.build.configs import BUILD_MODE_ALLOWED_PROVIDER_TYPES
from onyx.server.features.build.configs import BUILD_MODE_RECOMMENDED_MODEL_BY_TYPE


def _build_mode_providers_block() -> str:
    rel = Path("web/src/app/craft/onboarding/constants.ts")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            text = candidate.read_text()
            start = text.index("export const BUILD_MODE_PROVIDERS")
            return text[start : text.index("\n];", start)]
    raise FileNotFoundError(f"Could not locate {rel} above {__file__}")


def _frontend_provider_keys() -> list[str]:
    # Within BUILD_MODE_PROVIDERS only provider objects carry a `key:` field
    # (models use `name:`), so this captures provider types in order.
    return re.findall(r'key:\s*"([^"]+)"', _build_mode_providers_block())


def _frontend_recommended_by_type() -> dict[str, str]:
    block = _build_mode_providers_block()
    result: dict[str, str] = {}
    # Split into per-provider chunks on `key: "..."`, then within each find the
    # model object flagged `recommended: true`.
    for m in re.finditer(r'key:\s*"([^"]+)".*?models:\s*\[(.*?)\]', block, re.DOTALL):
        key, models_blob = m.group(1), m.group(2)
        rec = re.search(
            r'name:\s*"([^"]+)"[^}]*?recommended:\s*true', models_blob, re.DOTALL
        )
        if rec:
            result[key] = rec.group(1)
    return result


def test_backend_provider_types_match_frontend() -> None:
    assert _frontend_provider_keys() == BUILD_MODE_ALLOWED_PROVIDER_TYPES


def test_backend_recommended_models_match_frontend() -> None:
    assert _frontend_recommended_by_type() == BUILD_MODE_RECOMMENDED_MODEL_BY_TYPE
