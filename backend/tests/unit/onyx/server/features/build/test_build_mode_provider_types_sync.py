"""Guards that the backend Craft-allowed provider types stay in sync with the
frontend source of truth (``BUILD_MODE_PROVIDERS`` keys in
``web/src/app/craft/onboarding/constants.ts``). Drift (e.g. adding a type on one
side only) fails CI instead of silently mismatching onboarding vs. provisioning."""

from __future__ import annotations

import re
from pathlib import Path

from onyx.server.features.build.configs import BUILD_MODE_ALLOWED_PROVIDER_TYPES


def _find_frontend_constants() -> Path:
    rel = Path("web/src/app/craft/onboarding/constants.ts")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not locate {rel} above {__file__}")


def _frontend_provider_keys() -> list[str]:
    text = _find_frontend_constants().read_text()
    start = text.index("export const BUILD_MODE_PROVIDERS")
    end = text.index("\n];", start)
    # Within BUILD_MODE_PROVIDERS only provider objects carry a `key:` field
    # (models use `name:`), so this captures provider types in order.
    return re.findall(r'key:\s*"([^"]+)"', text[start:end])


def test_backend_provider_types_match_frontend() -> None:
    assert _frontend_provider_keys() == BUILD_MODE_ALLOWED_PROVIDER_TYPES
