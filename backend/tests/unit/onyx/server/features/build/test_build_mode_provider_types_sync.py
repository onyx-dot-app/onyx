"""Guards for the Craft-supported provider list, which is maintained in two
runtimes: BUILD_MODE_ALLOWED_PROVIDER_TYPES (backend, used for provisioning /
DB filtering) and CRAFT_PROVIDERS (frontend, used for the model picker). These
tests fail loudly if they drift, or if the shared recommended-models config is
missing a default for a supported type."""

from __future__ import annotations

import re
from pathlib import Path

from onyx.llm.well_known_providers.llm_provider_options import (
    _load_bundled_recommendations,
)
from onyx.server.features.build.configs import BUILD_MODE_ALLOWED_PROVIDER_TYPES


def _frontend_craft_provider_keys() -> list[str]:
    rel = Path("web/src/app/craft/onboarding/constants.ts")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            text = candidate.read_text()
            start = text.index("export const CRAFT_PROVIDERS")
            block = text[start : text.index("\n];", start)]
            return re.findall(r'key:\s*"([^"]+)"', block)
    raise FileNotFoundError(f"Could not locate {rel} above {__file__}")


def test_frontend_and_backend_craft_provider_types_match() -> None:
    assert _frontend_craft_provider_keys() == BUILD_MODE_ALLOWED_PROVIDER_TYPES


def test_recommended_config_covers_allowed_provider_types() -> None:
    recommendations = _load_bundled_recommendations()
    for provider_type in BUILD_MODE_ALLOWED_PROVIDER_TYPES:
        assert recommendations.get_default_model(provider_type) is not None, (
            f"recommended-models.json has no default_model for Craft provider "
            f"type {provider_type!r}"
        )
